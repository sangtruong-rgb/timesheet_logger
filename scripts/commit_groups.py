"""Verified commit/PR lookup and conservative grouping of adjacent work pieces."""
import copy
import re

from activity_text import extract_tickets

LEGACY_GROUPING_POLICY = 'adjacent_pr_or_ticket_v1'
GROUPING_POLICY = 'adjacent_pr_or_ticket_v2'
SUPPORTED_GROUPING_POLICIES = (LEGACY_GROUPING_POLICY, GROUPING_POLICY)


def enrich_commit_prs(commits, *, client=None, use_git_credentials=False):
    """Lookup each qualified SHA once. Unknown is never equivalent to no PR."""
    from github_api import GitHubAPI
    from get_pr_activity import github_repo
    cache = {}
    for commit in commits:
        key = (commit['repository'], commit['hash'])
        if key not in cache:
            try:
                repository = github_repo(key[0])
                if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
                    raise ValueError('Unresolved GitHub repository')
                if not re.fullmatch(r'[0-9a-fA-F]{7,64}', key[1]):
                    raise ValueError('Unresolved commit SHA')
                if client is None:
                    client = GitHubAPI(use_git_credentials)
                references = {}
                for pr in client.items(f'repos/{repository}/commits/{key[1]}/pulls'):
                    number, title = pr.get('number'), pr.get('title')
                    if type(number) is not int or number < 1 or not isinstance(title, str):
                        raise ValueError('Malformed commit PR association')
                    # A repository-qualified identity prevents same-number collisions.
                    base_repo = ((pr.get('base') or {}).get('repo') or {}).get('full_name', repository)
                    if base_repo.casefold() != repository.casefold():
                        raise ValueError('Unexpected association repository')
                    references[number] = {'repository': repository, 'id': number, 'title': title}
                cache[key] = {'status': 'resolved', 'prs': [references[n] for n in sorted(references)]}
            except Exception as exc:
                # Do not leak credential/provider diagnostics into snapshots.
                cache[key] = {'status': 'unknown', 'prs': [], 'reason': type(exc).__name__}
        commit['pr_association'] = copy.deepcopy(cache[key])
    return {'resolved': sum(c['pr_association']['status'] == 'resolved' for c in commits),
            'unknown': sum(c['pr_association']['status'] == 'unknown' for c in commits)}


def commit_work_key(commit):
    association = commit.get('pr_association', {})
    if association.get('status') != 'resolved':
        return None
    prs = association.get('prs', [])
    if len(prs) == 1:
        return ('pr', prs[0]['repository'].casefold(), prs[0]['id'])
    if prs:  # Multiple associated PRs are ambiguous, even if tickets match.
        return None
    tickets = extract_tickets([commit.get('message', '')])
    if len(tickets) == 1:
        return ('ticket', commit['repository'].casefold(), tickets[0])
    return None


def block_work_key(block, *, policy=GROUPING_POLICY):
    if block.get('block_type') != 'development' or block.get('allocation', {}).get('basis') != 'ending_commit':
        return None
    keys = [commit_work_key(c) for c in block.get('commits', [])]
    if keys and keys[0] is not None and all(k == keys[0] for k in keys):
        return keys[0]
    # Same-minute batches may contain several different, individually verified
    # PRs. Only the exact same complete set can group with the next batch.
    # An ambiguous association on any individual commit still prevents grouping.
    if policy == GROUPING_POLICY and keys and all(k is not None and k[0] == 'pr' for k in keys):
        return ('pr_set', *(f'{k[1]}#{k[2]}' for k in sorted(set(keys))))
    return None


def group_adjacent_blocks(blocks, *, policy=GROUPING_POLICY):
    """Run after exclusion/type splitting; never bridge lunch, meetings, or OT."""
    from get_pr_activity import deduplicate_prs
    from summary_request import allocation_group_id
    if policy not in SUPPORTED_GROUPING_POLICIES:
        raise ValueError('Unsupported commit grouping policy')
    result = []
    for source in blocks:
        block = copy.deepcopy(source)
        block['commit_grouping'] = policy
        linked_prs = [{**p, 'events': [], 'association': 'commit'}
                      for c in block.get('commits', [])
                      for p in c.get('pr_association', {}).get('prs', [])]
        block['prs'] = deduplicate_prs(block.get('prs', []) + linked_prs)
        key = block_work_key(block, policy=policy)
        previous = result[-1] if result else None
        if (key is not None and previous is not None and block_work_key(previous, policy=policy) == key
                and previous['interval']['end'] == block['interval']['start']
                and previous.get('work_type') == block.get('work_type')):
            previous['end_time'] = block['end_time']
            previous['interval']['end'] = block['interval']['end']
            previous['duration_minutes'] += block['duration_minutes']
            commits = {(c['repository'], c['hash']): c for c in previous['commits'] + block['commits']}
            previous['commits'] = sorted(commits.values(), key=lambda c: (c['repository'], c['hash']))
            previous['prs'] = deduplicate_prs(previous['prs'] + block['prs'])
            previous['allocation']['grouped_intervals'].extend(block['allocation'].get('grouped_intervals', [block['interval']]))
            previous['allocation']['end'] = block['interval']['end']
            previous['allocation']['closing_commits'] = [
                {'repository': c['repository'], 'hash': c['hash']} for c in previous['commits']]
            previous['allocation']['summary_group_id'] = allocation_group_id(
                previous['date'], previous['timezone'], previous['allocation'])
        else:
            if key is not None:
                # Each piece has its own description scope across excluded time.
                block['allocation'].update(start=block['interval']['start'], end=block['interval']['end'],
                                           grouping=policy, work_key=list(key),
                                           grouped_intervals=[dict(block['interval'])])
                block['allocation']['summary_group_id'] = allocation_group_id(
                    block['date'], block['timezone'], block['allocation'])
            result.append(block)
    return result
