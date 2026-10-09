"""Lossless text sharing and semantic jobs; interval mapping stays in Python."""
import hashlib
import json


def serialize_request(request):
    return json.dumps(request, ensure_ascii=False, separators=(',', ':'))


def allocation_group_id(date, timezone, allocation):
    identity = {'date': date, 'timezone': timezone,
                'allocation': {k: v for k, v in allocation.items() if k != 'summary_group_id'}}
    data = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return 'cg:' + hashlib.sha256(data.encode('utf-8')).hexdigest()


def commit_summary_group_id(block):
    """Identify pieces of one allocation, without merging different work groups."""
    allocation = block.get('allocation', {})
    policy = block.get('estimation_policy', {})
    if not isinstance(allocation, dict) or not isinstance(policy, dict):
        return None
    if (block.get('block_type') != 'development' or block.get('time_basis') != 'estimated'
            or policy.get('strategy') != 'commit_intervals'
            or allocation.get('basis') != 'ending_commit' or not block.get('commits')):
        return None
    if 'summary_group_id' in allocation:
        expected = allocation_group_id(block['date'], block.get('timezone'), allocation)
        if allocation['summary_group_id'] != expected:
            raise ValueError('Allocation summary group conflicts with its identity')
        return expected
    evidence = []
    for commit in block['commits']:
        if any(not isinstance(commit.get(key), str) or not commit[key] for key in ('repository', 'hash')):
            return None
        evidence.append((commit['repository'], commit['hash'], commit.get('message', '')))
    identity = {'date': block['date'], 'timezone': block.get('timezone'),
                'allocation': allocation, 'commits': sorted(evidence),
                'calendar': sorted(set(block.get('calendar_titles', []))),
                'calendar_overlap': bool(block.get('calendar_overlap'))}
    data = json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return 'cg:' + hashlib.sha256(data.encode('utf-8')).hexdigest()


def commit_group_mapping(blocks):
    mapping = {}
    for block in blocks:
        group = block.get('summary_group_id')
        if group is not None:
            if not isinstance(group, str) or not group:
                raise ValueError('Summary group ID must be nonempty text')
            mapping.setdefault(group, []).append(block['block_id'])
    return mapping


def build_summary_request(blocks):
    texts, identifiers, jobs, by_content, mapping = {}, {}, [], {}, {}
    workstream = any('workstream_segment' in b for b in blocks)

    def references(values):
        result = []
        for value in sorted(set(values)):
            if value not in identifiers:
                identifier = f't{len(texts) + 1}'
                identifiers[value] = identifier
                texts[identifier] = value
            result.append(identifiers[value])
        return result

    grouped = {}
    def pr_context(pr):
        if 'actions' not in pr:
            return pr['title']
        facts = list(pr['actions'])
        if pr.get('commit_association'):
            facts.append('associated with commits; title is context, not completed scope')
        return '[' + '; '.join(facts or ['context only']) + '] ' + pr['title']
    for block in blocks:
        group = None if workstream else block.get('summary_group_id')
        if group is not None and (not isinstance(group, str) or not group):
            raise ValueError('Summary group ID must be nonempty text')
        key = ('group', group) if group is not None else ('block', block['block_id'])
        grouped.setdefault(key, []).append(block)

    for group_key, pieces in grouped.items():
        content = {'commits': references([t for b in pieces for t in b['commit_messages']]),
                   'prs': references([pr_context(p) for b in pieces for p in b['prs']])}
        calendar = [t for b in pieces for t in b['calendar_titles']]
        if calendar:
            content['calendar'] = references(calendar)
        if any(b.get('calendar_overlap') for b in pieces):
            content['calendar_unconfirmed'] = True
        # Explicit allocation groups stay distinct even if their text matches.
        # Unmarked v1/v2 inputs retain the original semantic deduplication.
        key = (group_key, serialize_request(content)) if workstream or group_key[0] == 'group' else serialize_request(content)
        if key not in by_content:
            job_id = f'j{len(jobs) + 1}'
            by_content[key] = job_id
            jobs.append({'id': job_id, **content})
            mapping[job_id] = []
        mapping[by_content[key]].extend(b['block_id'] for b in pieces)
    request = {'texts': texts, 'jobs': jobs}
    if workstream:
        segments = {}
        by_block = {b['block_id']: b for b in blocks}
        for job, keys in mapping.items():
            segment = by_block[keys[0]]['workstream_segment']
            if segment is not None:
                segments.setdefault(segment, []).append(job)
        request['merge_candidates'] = list(segments.values())
        if any('session_grouping' in b for b in blocks):
            if any(b.get('session_grouping') != 'related_work_session_v1' for b in blocks):
                raise ValueError('Unsupported or inconsistent session grouping policy')
            request['grouping_policy'] = 'related_work_session_v1'
    return request, mapping


def expand_judgments(request, mapping, judgments):
    if 'merge_candidates' in request:
        return expand_workstream_judgments(request, mapping, judgments)
    if not isinstance(judgments, list):
        raise ValueError('Summary judgments must be an array')
    resolved = {}
    for item in judgments:
        if not isinstance(item, dict) or set(item) != {'id', 'description'}:
            raise ValueError('Summary requires only id and description')
        identifier = item['id']
        if not isinstance(identifier, str) or identifier not in mapping or identifier in resolved:
            raise ValueError('Unknown or duplicate summary job')
        if not isinstance(item['description'], str) or not item['description'].strip():
            raise ValueError('Summary description must be nonempty')
        resolved[identifier] = item['description']
    if set(resolved) != {j['id'] for j in request['jobs']}:
        raise ValueError('Summary output must cover exactly all jobs')
    return [{'block_id': block_id, 'description': resolved[job_id]}
            for job_id, block_ids in mapping.items() for block_id in block_ids]


def expand_workstream_judgments(request, mapping, judgments):
    from workstream_groups import validate_group, MAX_DESCRIPTION_CHARS
    if not isinstance(judgments, list):
        raise ValueError('Workstream judgments must be an array')
    result, covered = [], []
    for item in judgments:
        if not isinstance(item, dict) or set(item) != {'job_ids', 'description'}:
            raise ValueError('Workstream judgment requires only job_ids and description')
        ids, description = item['job_ids'], item['description']
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(i, str) or i not in mapping for i in ids)
                or not isinstance(description, str) or not description.strip()
                or len(description.strip()) > MAX_DESCRIPTION_CHARS):
            raise ValueError('Invalid workstream jobs or description')
        if len(ids) > 1:
            validate_group(ids, request['merge_candidates'])
        keys = [key for i in ids for key in mapping[i]]
        result.extend({'block_id': key, 'description': description,
                       **({'workstream_group': keys} if len(ids) > 1 else {})} for key in keys)
        covered.extend(ids)
    if covered != [j['id'] for j in request['jobs']]:
        raise ValueError('Workstream output must cover every job exactly once in order')
    return result
