"""AI may group related adjacent work; Python owns coverage and source identity."""
import copy

from block_identity import BlockIdentityError, get_block_id, index_blocks

POLICY = 'adjacent_workstream_v1'
MAX_GROUP_MINUTES = 240  # Gradion accepts at most four hours in one entry.
MAX_DESCRIPTION_CHARS = 600


def block_id(block):
    return get_block_id(block['date'], block['start_time'], block['end_time'])


def eligible_repository(block):
    from commit_groups import SUPPORTED_GROUPING_POLICIES
    if (block.get('commit_grouping') not in SUPPORTED_GROUPING_POLICIES
            or block.get('block_type') != 'development'
            or block.get('time_basis') != 'estimated'
            or block.get('allocation', {}).get('basis') != 'ending_commit'
            or block.get('calendar_overlap') or block.get('calendar_events')
            or block.get('calendar_titles') or block.get('review')
            or not block.get('commits') or 'interval' not in block
            or block['duration_minutes'] > MAX_GROUP_MINUTES):
        return None
    repos = {c.get('repository', '').casefold() for c in block['commits']}
    repos.update(p.get('repository', '').casefold() for p in block.get('prs', []))
    return next(iter(repos)) if len(repos) == 1 and '' not in repos else None


def candidate_segments(blocks):
    """Partition at every hard boundary before exposing opaque candidates to AI."""
    index_blocks(blocks)
    segments, previous, minutes = [], None, 0
    context = ('date', 'timezone', 'work_type', 'main_work_windows',
               'work_confirmation', 'work_schedule', 'overtime_confirmation', 'estimation_policy')
    for block in sorted(blocks, key=lambda b: (b['date'], b['start_time'])):
        repo = eligible_repository(block)
        adjacent = (repo is not None and previous is not None
                    and eligible_repository(previous) == repo
                    and previous['interval']['end'] == block['interval']['start']
                    and all(previous.get(k) == block.get(k) for k in context)
                    and minutes + block['duration_minutes'] <= MAX_GROUP_MINUTES)
        if repo is None:
            previous, minutes = None, 0
            continue
        if adjacent:
            segments[-1].append(block_id(block))
            minutes += block['duration_minutes']
        else:
            segments.append([block_id(block)])
            minutes = block['duration_minutes']
        previous = block
    return [s for s in segments if len(s) > 1]


def validate_group(ids, candidates):
    if not isinstance(ids, list) or len(ids) < 2 or any(not isinstance(i, str) for i in ids):
        raise BlockIdentityError('Workstream group requires at least two source IDs')
    if len(ids) != len(set(ids)):
        raise BlockIdentityError('Duplicate source in workstream group')
    if not any(any(s[i:i + len(ids)] == ids for i in range(len(s) - len(ids) + 1)) for s in candidates):
        raise BlockIdentityError('Workstream group crosses a gap, meeting, work type, repository or four-hour boundary')


def merge_entries(blocks, entries, ai_by_key):
    """Revalidate proposed groups on original blocks, then combine assembled rows."""
    proposals = {key: item['workstream_group'] for key, item in ai_by_key.items() if 'workstream_group' in item}
    if not proposals:
        return entries
    candidates = candidate_segments(blocks)
    seen, groups = set(), []
    for key, ids in proposals.items():
        validate_group(ids, candidates)
        if key not in ids:
            raise BlockIdentityError('Workstream source is not a member of its group')
        if key in seen:
            continue
        if seen.intersection(ids) or any(proposals.get(i) != ids for i in ids):
            raise BlockIdentityError('Workstream members must agree on one complete group')
        if len({ai_by_key[i]['description'].strip() for i in ids}) != 1:
            raise BlockIdentityError('Workstream members require one shared description')
        if len(ai_by_key[key]['description'].strip()) > MAX_DESCRIPTION_CHARS:
            raise BlockIdentityError('Workstream description exceeds concise-summary limit')
        seen.update(ids)
        groups.append(ids)
    by_id = {r['block_id']: r for r in entries}
    first = {ids[0]: ids for ids in groups}
    result = []
    from build_timesheet import format_pr_suffix
    from get_pr_activity import deduplicate_prs
    from interval_validation import validate_interval
    from overtime import validate_classification
    for original in entries:
        key = original['block_id']
        if key not in seen:
            result.append(original)
            continue
        if key not in first:
            continue
        ids = first[key]
        sources = [by_id[i] for i in ids]
        merged = copy.deepcopy(sources[0])
        merged['entry']['end'] = sources[-1]['entry']['end']
        merged['interval']['end'] = sources[-1]['interval']['end']
        merged['entry']['duration_minutes'] = sum(r['entry']['duration_minutes'] for r in sources)
        merged['block_id'] = get_block_id(merged['entry']['date'], merged['entry']['start'], merged['entry']['end'])
        # Preserve exact source objects (including distinct PR actions), deduplicating only exact copies.
        for field in ('commits', 'pull_requests', 'calendar', 'calendar_events'):
            values = []
            for row in sources:
                for value in row['sources'].get(field, []):
                    if value not in values:
                        values.append(copy.deepcopy(value))
            if values or field in merged['sources']:
                merged['sources'][field] = values
        merged['sources']['pull_requests'] = deduplicate_prs(merged['sources']['pull_requests'])
        description = ai_by_key[key]['description'].strip().rstrip('.') + '.'
        merged['entry']['description'] = description + ' ' + format_pr_suffix(merged['sources']['pull_requests'])
        merged['source_block_ids'] = ids
        merged['allocation'] = {'basis': 'workstream_group', 'policy': POLICY,
                                'source_allocations': [copy.deepcopy(r.get('allocation')) for r in sources]}
        merged['summary_source'] = 'ai'
        validate_interval(merged['entry']['date'], merged['entry']['start'], merged['entry']['end'],
                          merged['entry']['duration_minutes'], merged['interval'])
        validate_classification(merged)
        result.append(merged)
    if sum(r['entry']['duration_minutes'] for r in result) != sum(r['entry']['duration_minutes'] for r in entries):
        raise BlockIdentityError('Workstream grouping changed total duration')
    return result
