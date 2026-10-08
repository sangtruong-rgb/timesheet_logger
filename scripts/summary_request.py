"""Lossless text sharing and semantic jobs; interval mapping stays in Python."""
import hashlib
import json


def serialize_request(request):
    return json.dumps(request, ensure_ascii=False, separators=(',', ':'))


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
    for block in blocks:
        group = block.get('summary_group_id')
        if group is not None and (not isinstance(group, str) or not group):
            raise ValueError('Summary group ID must be nonempty text')
        key = ('group', group) if group is not None else ('block', block['block_id'])
        grouped.setdefault(key, []).append(block)

    for group_key, pieces in grouped.items():
        content = {'commits': references([t for b in pieces for t in b['commit_messages']]),
                   'prs': references([p['title'] for b in pieces for p in b['prs']])}
        calendar = [t for b in pieces for t in b['calendar_titles']]
        if calendar:
            content['calendar'] = references(calendar)
        if any(b.get('calendar_overlap') for b in pieces):
            content['calendar_unconfirmed'] = True
        # Explicit allocation groups stay distinct even if their text matches.
        # Unmarked v1/v2 inputs retain the original semantic deduplication.
        key = (group_key, serialize_request(content)) if group_key[0] == 'group' else serialize_request(content)
        if key not in by_content:
            job_id = f'j{len(jobs) + 1}'
            by_content[key] = job_id
            jobs.append({'id': job_id, **content})
            mapping[job_id] = []
        mapping[by_content[key]].extend(b['block_id'] for b in pieces)
    return {'texts': texts, 'jobs': jobs}, mapping


def expand_judgments(request, mapping, judgments):
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
