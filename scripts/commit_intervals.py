"""Allocate confirmed daily work to closing commits, excluding lunch and Calendar.

Commit timestamps are minute-floored to match the timesheet's HH:MM precision.
An ending commit describes all remaining pieces of its interval, even when lunch
or Calendar separates the pieces. It is completion evidence, not an assertion
that the commit happened inside each piece. PR actions use ordinary [start,end)
assignment and never generate additional minutes.
Allocations with 1–19 work minutes merge backward before exclusions are split
into rows. The first allocation, zero-work allocations and confirmed-end tails
remain separate. Lunch/Calendar are never counted as development by a merge.
"""
import datetime
import re

from block_identity import BlockIdentityError
from block_settings import COMMIT_STRATEGY, LEGACY_STRATEGY, SHORT_COMMIT_MERGE_MINUTES


def work_confirmation(date, start, end=None):
    """Validate explicit per-day local clock input; never default a start time."""
    clock = r"(?:[01][0-9]|2[0-3]):[0-5][0-9]"
    if not isinstance(start, str) or not re.fullmatch(clock, start):
        raise BlockIdentityError("commit_intervals requires a confirmed --work-start HH:MM for this date")
    if end is not None and (not isinstance(end, str) or
                            not (re.fullmatch(clock, end) or end == "24:00") or end <= start):
        raise BlockIdentityError("--work-end must be HH:MM (or 24:00), after --work-start on the same day")
    return {"date": date, "start": start, **({"end": end} if end is not None else {})}


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
                           short_commit_merge_minutes=SHORT_COMMIT_MERGE_MINUTES):
    from build_time_blocks import build_time_blocks, parse_dt, calculate_minutes
    from get_pr_activity import deduplicate_prs

    if type(short_commit_merge_minutes) is not int or short_commit_merge_minutes < 1:
        raise BlockIdentityError('Short commit merge threshold must be a positive integer')

    confirmation = model.get("work_confirmation")
    if not isinstance(confirmation, dict) or confirmation.get("date") != date.isoformat():
        raise BlockIdentityError("commit_intervals requires work_confirmation for the selected date")
    if set(confirmation) - {"date", "start", "end"}:
        raise BlockIdentityError("Unsupported work_confirmation fields")
    confirmation = work_confirmation(date.isoformat(), confirmation.get("start"), confirmation.get("end"))
    midnight = datetime.datetime.combine(date, datetime.time(), tzinfo=tz)
    day_end = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(), tzinfo=tz)

    def local_clock(value):
        return day_end if value == "24:00" else datetime.datetime.combine(date, datetime.time.fromisoformat(value), tzinfo=tz)

    start = local_clock(confirmation["start"])
    finish = local_clock(confirmation["end"]) if "end" in confirmation else None
    # Reuse the existing Calendar clipping/overlap rules, with no development
    # sources so the legacy builder cannot infer any development gaps.
    blocks = build_time_blocks({**model, "commits": [], "pull_requests": [],
                               "unassigned_activity": [], "block_policy": {"strategy": LEGACY_STRATEGY}})
    excluded = [(local_clock("12:00"), local_clock("13:30"))]
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
        if instant is not None and start < instant < day_end and (finish is None or instant <= finish):
            minute = instant.replace(second=0, microsecond=0)
            if minute > start:
                groups.setdefault(minute, []).append((index, commit))

    assigned = set()

    def append_work(left, right, closing, merged_intervals=None):
        pieces = list(subtract_intervals(left, right, excluded))
        evidence = [c for _, c in sorted(closing, key=lambda pair: (pair[1].get("repository", ""), pair[1].get("hash", "")))]
        for piece_start, piece_end in pieces:
            if calculate_minutes(piece_start, piece_end) < 1 or piece_start.strftime("%H:%M") == piece_end.strftime("%H:%M"):
                continue
            blocks.append({
                "date": date.isoformat(), "start_time": piece_start.strftime("%H:%M"),
                "end_time": "24:00" if piece_end == day_end else piece_end.strftime("%H:%M"),
                "duration_minutes": calculate_minutes(piece_start, piece_end),
                "interval": {"start": piece_start.isoformat(), "end": piece_end.isoformat()},
                "timezone": model.get("timezone", getattr(tz, "key", str(tz))),
                "block_type": "development", "time_basis": "estimated",
                "estimation_reason": "commit_interval" if closing else "confirmed_work_window",
                "estimation_policy": {"strategy": COMMIT_STRATEGY},
                "work_confirmation": dict(confirmation),
                "allocation": {"start": left.isoformat(), "end": right.isoformat(),
                               "basis": "ending_commit" if closing else "confirmed_end",
                               "commit_precision": "minute_floor",
                               **({"short_commit_merge_minutes": short_commit_merge_minutes,
                                   "merged_intervals": merged_intervals} if merged_intervals else {})},
                "calendar_titles": [], "commits": list(evidence), "prs": [],
            })
            assigned.update(i for i, _ in closing)

    cursor = start
    allocations = []
    for boundary, closing in sorted(groups.items()):
        minutes = sum(calculate_minutes(left, right)
                      for left, right in subtract_intervals(cursor, boundary, excluded))
        original = {"start": cursor.isoformat(), "end": boundary.isoformat()}
        if (merge_short_commits and 0 < minutes < short_commit_merge_minutes and allocations
                and allocations[-1]['work_minutes'] > 0):
            previous = allocations[-1]
            previous['end'] = boundary
            previous['closing'].extend(closing)
            previous['work_minutes'] += minutes
            previous['intervals'].append(original)
        else:
            allocations.append({'start': cursor, 'end': boundary, 'closing': list(closing),
                                'work_minutes': minutes, 'intervals': [original]})
        cursor = boundary
    for allocation in allocations:
        append_work(allocation['start'], allocation['end'], allocation['closing'],
                    allocation['intervals'] if len(allocation['intervals']) > 1 else None)
    if finish is not None and cursor < finish:
        append_work(cursor, finish, [])
    blocks.sort(key=lambda b: (b["start_time"], b["end_time"]))

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
    for reference in model.get("pull_requests", []):
        actions = ([{**reference, "status": event["action"], "timestamp": event["timestamp"],
                     "actor": event.get("actor"), "events": [event]} for event in reference["events"]]
                   if reference.get("events") else [reference])
        for action in actions:
            if not assign_by_timestamp(action, "prs"):
                retain("github", action)
    for block in blocks:
        block["prs"] = deduplicate_prs(block["prs"])
    return blocks
