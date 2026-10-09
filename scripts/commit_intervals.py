"""Allocate confirmed daily work to closing commits, excluding lunch and Calendar.

Commit timestamps are minute-floored to match the timesheet's HH:MM precision.
An ending commit describes all remaining pieces of its interval, even when lunch
or Calendar separates the pieces. It is completion evidence, not an assertion
that the commit happened inside each piece. PR actions use ordinary [start,end)
assignment; same-minute merges with a matching commit SHA use its allocation.
Neither assignment generates additional minutes.
Historical models merge 1–19 work-minute allocations backward before splitting.
New pipeline models freeze a commit_grouping policy: resolve work identity from
PR/ticket evidence, then group adjacent pieces after exclusions and work types
are split. Confirmed-end tails remain separate in both versions.
"""
import datetime
import re

from block_identity import BlockIdentityError
from block_settings import (COMMIT_STRATEGY, LEGACY_STRATEGY, SHORT_COMMIT_MERGE_MINUTES,
                            DEVELOPMENT_EVIDENCE_POLICY)


def work_confirmation(date, start, end=None, *, windows=None):
    """Validate explicit per-day local clock input; never default a start time."""
    if windows is not None:
        from work_windows import validate_work_windows
        windows = validate_work_windows(windows)
        if start != windows[0]['start'] or end != windows[-1]['end']:
            raise BlockIdentityError('Confirmed work window boundaries conflict with daily start/end')
    clock = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
    if not isinstance(start, str) or not re.fullmatch(clock, start):
        raise BlockIdentityError("commit_intervals requires a confirmed --work-start HH:MM for this date")
    if end is not None and (not isinstance(end, str) or
                            not (re.fullmatch(clock, end) or end == "24:00") or end <= start):
        raise BlockIdentityError("--work-end must be HH:MM (or 24:00), after --work-start on the same day")
    return {"date": date, "start": start, **({"end": end} if end is not None else {}),
            **({'windows': windows} if windows is not None else {})}


def subtract_intervals(start, end, excluded):
    cursor = start
    for left, right in sorted(excluded):
        if right <= cursor:
            continue
        if left >= end:
            break
        if cursor < left:
            yield cursor, left
        cursor = max(cursor, right)
        if cursor >= end:
            return
    if cursor < end:
        yield cursor, end


def build_commit_intervals(model, date, tz, unassigned, *, merge_short_commits=True,
                           short_commit_merge_minutes=SHORT_COMMIT_MERGE_MINUTES,
                           allocation_version=2, work_types=None, allow_minute_end_commits=False):
    from build_time_blocks import build_time_blocks, parse_dt, calculate_minutes
    from get_pr_activity import deduplicate_prs
    from commit_groups import SUPPORTED_GROUPING_POLICIES
    evidence_policy = model.get('development_evidence_policy')
    if evidence_policy is not None and evidence_policy != DEVELOPMENT_EVIDENCE_POLICY:
        raise BlockIdentityError('Unsupported development evidence policy')
    grouping = model.get('commit_grouping')
    if grouping is not None and grouping not in SUPPORTED_GROUPING_POLICIES:
        raise BlockIdentityError('Unsupported commit grouping policy')
    if grouping:
        merge_short_commits = False

    if type(short_commit_merge_minutes) is not int or short_commit_merge_minutes < 1:
        raise BlockIdentityError('Short commit merge threshold must be a positive integer')
    if type(allocation_version) is not int or allocation_version not in (1, 2):
        raise BlockIdentityError('Unsupported commit allocation version')

    confirmation = model.get("work_confirmation")
    if not isinstance(confirmation, dict) or confirmation.get("date") != date.isoformat():
        raise BlockIdentityError("commit_intervals requires work_confirmation for the selected date")
    if set(confirmation) - {"date", "start", "end", "windows"}:
        raise BlockIdentityError("Unsupported work_confirmation fields")
    if 'windows' in confirmation and confirmation['windows'] is None:
        raise BlockIdentityError('Confirmed work windows cannot be null')
    confirmation = work_confirmation(date.isoformat(), confirmation.get("start"), confirmation.get("end"),
                                     windows=confirmation.get('windows'))
    midnight = datetime.datetime.combine(date, datetime.time(), tzinfo=tz)
    day_end = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(), tzinfo=tz)

    def local_clock(value):
        from work_schedule import local_clock as schedule_clock
        return schedule_clock(date, value, tz)

    start = local_clock(confirmation["start"])
    finish = local_clock(confirmation["end"]) if "end" in confirmation else None
    # Reuse the existing Calendar clipping/overlap rules, with no development
    # sources so the legacy builder cannot infer any development gaps.
    blocks = build_time_blocks({**model, "commits": [], "pull_requests": [],
                               "unassigned_activity": [], "block_policy": {"strategy": LEGACY_STRATEGY}})
    from work_schedule import schedule_bounds
    schedule, _, excluded = schedule_bounds(model, date, tz)
    windows = None
    if 'windows' in confirmation:
        windows = [(local_clock(item['start']), local_clock(item['end'])) for item in confirmation['windows']]
        # Explicit windows replace profile breaks for this date. Their complement
        # is excluded, so custom lunch and all other gaps remain uncounted.
        excluded = [(right, left) for (_, right), (left, _) in zip(windows, windows[1:])]
        clipped = []
        for block in blocks:
            left, right = (parse_dt(block['interval'][field]) for field in ('start', 'end'))
            for window_start, window_end in windows:
                piece_start, piece_end = max(left, window_start), min(right, window_end)
                if piece_start < piece_end:
                    clipped.append({**block, 'start_time': piece_start.strftime('%H:%M'),
                                    'end_time': '24:00' if piece_end == day_end else piece_end.strftime('%H:%M'),
                                    'duration_minutes': calculate_minutes(piece_start, piece_end),
                                    'interval': {'start': piece_start.isoformat(), 'end': piece_end.isoformat()},
                                    'work_confirmation': dict(confirmation)})
        blocks = clipped
        # Keep excluded scheduled evidence for review; never create time for it.
        if unassigned is not None:
            for event in model.get('calendar', []):
                if event.get('all_day') or len(event.get('start', '')) == 10:
                    continue
                left, right = parse_dt(event.get('start')), parse_dt(event.get('end'))
                if left is not None and right is not None and any(subtract_intervals(left, right, windows)):
                    unassigned.append({'source': 'google_calendar', 'reason': 'outside_blocks', 'activity': dict(event)})
    excluded += [(parse_dt(b["interval"]["start"]), parse_dt(b["interval"]["end"])) for b in blocks]

    def timestamp(activity):
        value = parse_dt(activity.get("timestamp"))
        return value.astimezone(tz) if value is not None and value.tzinfo is not None else None

    # Bucket simultaneous/same-minute commits to avoid zero-length rows, using
    # qualified commit identities for stable ordering across repositories.
    groups = {}
    commits = model.get("commits", [])
    for index, commit in enumerate(commits):
        instant = timestamp(commit)
        boundary_instant = (instant.replace(second=0, microsecond=0)
                            if instant is not None and allow_minute_end_commits else instant)
        if (boundary_instant is not None and start < boundary_instant < day_end and (finish is None or boundary_instant <= finish)
                and (windows is None or any(left < boundary_instant <= right for left, right in windows))):
            minute = instant.replace(second=0, microsecond=0)
            if minute > start:
                groups.setdefault(minute, []).append((index, commit))

    assigned = set()

    def append_work(left, right, closing, merged_intervals=None):
        pieces = list(subtract_intervals(left, right, excluded))
        if work_types is not None:
            pieces = [(max(left, start), min(right, end)) for left, right in pieces
                      for start, end, _ in sorted(work_types) if max(left, start) < min(right, end)]
        evidence = [c for _, c in sorted(closing, key=lambda pair: (pair[1].get("repository", ""), pair[1].get("hash", "")))]
        allocation = {"start": left.isoformat(), "end": right.isoformat(),
                      "basis": "ending_commit" if closing else "confirmed_end",
                      "commit_precision": "minute_floor",
                      **({"short_commit_merge_minutes": short_commit_merge_minutes,
                          "merged_intervals": merged_intervals} if merged_intervals else {})}
        timezone = model.get("timezone", getattr(tz, "key", str(tz)))
        if closing and allocation_version >= 2:
            from summary_request import allocation_group_id
            allocation['closing_commits'] = [{'repository': c.get('repository', ''), 'hash': c.get('hash', '')}
                                             for c in evidence]
            allocation['summary_group_id'] = allocation_group_id(date.isoformat(), timezone, allocation)
        for piece_start, piece_end in pieces:
            if calculate_minutes(piece_start, piece_end) < 1 or piece_start.strftime("%H:%M") == piece_end.strftime("%H:%M"):
                continue
            blocks.append({
                "date": date.isoformat(), "start_time": piece_start.strftime("%H:%M"),
                "end_time": "24:00" if piece_end == day_end else piece_end.strftime("%H:%M"),
                "duration_minutes": calculate_minutes(piece_start, piece_end),
                "interval": {"start": piece_start.isoformat(), "end": piece_end.isoformat()},
                "timezone": timezone,
                "block_type": "development", "time_basis": "estimated",
                "estimation_reason": "commit_interval" if closing else "confirmed_work_window",
                "estimation_policy": {"strategy": COMMIT_STRATEGY},
                "work_confirmation": dict(confirmation),
                "allocation": dict(allocation),
                "calendar_titles": [], "commits": list(evidence), "prs": [],
            })
            assigned.update(i for i, _ in closing)

    cursor = start
    allocations = []
    for boundary, closing in sorted(groups.items()):
        minutes = sum(calculate_minutes(left, right)
                      for left, right in subtract_intervals(cursor, boundary, excluded))
        original = {"start": cursor.isoformat(), "end": boundary.isoformat()}
        typed_pieces = ([kind for left, right in subtract_intervals(cursor, boundary, excluded)
                        for start, end, kind in sorted(work_types) if start < right and left < end]
                       if work_types is not None else [])
        kinds = set(typed_pieces) if work_types is not None else None
        last_kind = typed_pieces[-1] if typed_pieces else None
        same_kind = (work_types is None or len(kinds) == 1 and allocations
                     and allocations[-1]['last_kind'] in kinds)
        if (merge_short_commits and 0 < minutes < short_commit_merge_minutes and allocations
                and allocations[-1]['work_minutes'] > 0 and same_kind):
            previous = allocations[-1]
            previous['end'] = boundary
            previous['closing'].extend(closing)
            previous['work_minutes'] += minutes
            previous['intervals'].append(original)
            previous['last_kind'] = last_kind
        else:
            allocations.append({'start': cursor, 'end': boundary, 'closing': list(closing),
                                'work_minutes': minutes, 'intervals': [original], 'last_kind': last_kind})
        cursor = boundary
    for allocation in allocations:
        append_work(allocation['start'], allocation['end'], allocation['closing'],
                    allocation['intervals'] if len(allocation['intervals']) > 1 else None)
    if finish is not None and cursor < finish:
        append_work(cursor, finish, [])
    blocks.sort(key=lambda b: (b["start_time"], b["end_time"]))
    if work_types is not None:
        typed_blocks = []
        for block in blocks:
            left, right = (parse_dt(block['interval'][field]) for field in ('start', 'end'))
            for start, end, kind in sorted(work_types):
                piece_start, piece_end = max(left, start), min(right, end)
                if piece_start < piece_end:
                    typed_blocks.append({**block, 'start_time': piece_start.strftime('%H:%M'),
                                         'end_time': '24:00' if piece_end == day_end else piece_end.strftime('%H:%M'),
                                         'duration_minutes': calculate_minutes(piece_start, piece_end),
                                         'interval': {'start': piece_start.isoformat(), 'end': piece_end.isoformat()},
                                         'work_type': kind, 'commits': list(block['commits']), 'prs': []})
        blocks = sorted(typed_blocks, key=lambda b: (b['start_time'], b['end_time']))

    def assign_by_timestamp(activity, field):
        instant = timestamp(activity)
        if instant is not None:
            for block in blocks:
                if parse_dt(block["interval"]["start"]) <= instant < parse_dt(block["interval"]["end"]):
                    block[field].append(activity)
                    return True
        return False

    def retain(source, activity):
        if unassigned is None:
            return
        raw = parse_dt(activity.get("timestamp"))
        reason = ("missing_timestamp" if not activity.get("timestamp") else
                  "invalid_timestamp" if raw is None else "naive_timestamp" if raw.tzinfo is None else
                  "outside_target_day" if not midnight <= raw < day_end else "outside_blocks")
        unassigned.append({"source": source, "reason": reason, "activity": dict(activity)})

    for index, commit in enumerate(commits):
        if index not in assigned and not assign_by_timestamp(commit, "commits"):
            retain("git", commit)

    def assign_merge_by_commit(action):
        # Associate only proven merge identities in the closing commit's minute.
        # The event remains at its original timestamp and creates no minutes.
        sha = action.get('merge_commit_sha')
        instant = timestamp(action)
        if (allocation_version < 2 or action.get('status') != 'merged' or not sha
                or instant is None or not start <= instant < day_end
                or (finish is not None and (instant.replace(second=0, microsecond=0)
                                           if allow_minute_end_commits else instant) > finish)):
            return False
        matches = []
        for block in blocks:
            refs = block.get('allocation', {}).get('closing_commits', [])
            if not any(ref['hash'] == sha and ref['repository'] == action.get('repository') for ref in refs):
                continue
            for closing in block['commits']:
                closing_time = timestamp(closing)
                if (closing.get('hash') == sha and closing.get('repository') == action.get('repository')
                        and closing_time is not None
                        and closing_time.replace(second=0, microsecond=0) == instant.replace(second=0, microsecond=0)):
                    matches.append(block)
                    break
        if not matches:
            return False
        last = max(matches, key=lambda block: block['interval']['end'])
        associated = {**action, 'assignment': {'basis': 'matching_merge_commit', 'commit_hash': sha,
                                             'repository': action['repository']}}
        associated['events'] = [{**event, 'assignment': associated['assignment']}
                                for event in action.get('events', [])]
        last['prs'].append(associated)
        return True

    for reference in model.get("pull_requests", []):
        actions = ([{**reference, "status": event["action"], "timestamp": event["timestamp"],
                     "actor": event.get("actor"), "events": [event]} for event in reference["events"]]
                   if reference.get("events") else [reference])
        for action in actions:
            if not assign_merge_by_commit(action) and not assign_by_timestamp(action, "prs"):
                retain("github", action)
    for block in blocks:
        block["prs"] = deduplicate_prs(block["prs"])
        if 'work_schedule' in model:
            from copy import deepcopy
            block['work_schedule'] = deepcopy(schedule)
    if evidence_policy:
        # Assign evidence first: PR-only work and a closing commit's split pieces
        # remain supported, while empty windows/tails must not become work logs.
        blocks = [block for block in blocks if block['block_type'] != 'development'
                  or block['commits'] or block['prs']]
    if grouping:
        from commit_groups import group_adjacent_blocks
        blocks = group_adjacent_blocks(blocks, policy=grouping)
    return blocks
