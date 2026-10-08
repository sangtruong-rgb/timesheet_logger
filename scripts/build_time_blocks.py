#!/usr/bin/env python3
"""
build_time_blocks.py - Deterministic time blocking and activity association.

Rules:
0. With commit_intervals, allocate the user's confirmed daily start to closing
   commits, subtract lunch/Calendar, and include a tail only with confirmed end.
   Merge commit allocations under 20 work minutes into the previous allocation;
   there is no idle split, padding to a minimum or maximum block size.
1. When calendar events exist:
   - Calendar events define explicit blocks (meetings, stand-ups, focus time).
   - Overlapping events are partitioned into disjoint intervals with all sources;
     overlap requires attendance review, not an assumption of attendance.
   - Timed events are clipped to the selected local day; midnight end is 24:00.
     All-day events belong to audit context and never form timed work blocks.
   - Development gaps require a timestamped commit/PR inside their interval.
     These durations are estimated, not proof of continuous work.
   - Calendar development gaps are restricted to the frozen work schedule
     (default 09:00–12:00 / 13:30–17:30) before checking activity.
     Scheduled Calendar events outside these windows are retained.
2. With an explicit activity-cluster policy:
   - Group timestamped development actions by idle gap and maximum duration.
   - Round inferred boundaries to 15 minutes inside work/lunch/Calendar bounds.
   - Dense PR batches stay in one short estimated block and require review.
   - Profiles and frozen snapshots without a policy retain the legacy fallback.
3. Associate commits and PRs deterministically with time blocks based on timestamps
   (commit_intervals uses the closing commit as completion context).
   Preserve unmatched activity separately for review, never in an arbitrary block.
4. Calculate duration in minutes/hours deterministically in code.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from block_identity import BlockIdentityError
from activity_settings import resolve_timezone, timezone_settings
from block_settings import CLUSTER_STRATEGY, COMMIT_STRATEGY, policy_from_model, SHORT_COMMIT_MERGE_MINUTES


CLUSTER_ROUNDING_MINUTES = 15


def parse_dt(ts_str: str) -> Optional[datetime.datetime]:
    if not ts_str:
        return None
    try:
        return datetime.datetime.fromisoformat(ts_str)
    except Exception:
        return None


def format_hhmm(dt: datetime.datetime) -> str:
    return dt.strftime("%H:%M")


def calculate_minutes(start_dt: datetime.datetime, end_dt: datetime.datetime) -> int:
    delta = end_dt.astimezone(datetime.timezone.utc) - start_dt.astimezone(datetime.timezone.utc)
    return max(0, int(delta.total_seconds() // 60))


def _floor_time(value: datetime.datetime, minutes: int) -> datetime.datetime:
    midnight = value.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((value - midnight).total_seconds() // 60)
    return midnight + datetime.timedelta(minutes=(elapsed // minutes) * minutes)


def _ceil_after_time(value: datetime.datetime, minutes: int) -> datetime.datetime:
    """Return a rounded exclusive end that still contains an action on a boundary."""
    floor = _floor_time(value, minutes)
    return floor + datetime.timedelta(minutes=minutes)


def _materialize_cluster(first, last, window_start, window_end, policy):
    start = max(window_start, _floor_time(first, CLUSTER_ROUNDING_MINUTES))
    end = min(window_end, _ceil_after_time(last, CLUSTER_ROUNDING_MINUTES))
    minimum = datetime.timedelta(minutes=policy["minimum_block_minutes"])
    if end - start < minimum:
        extended_end = min(window_end, start + minimum)
        if extended_end - start >= minimum:
            end = extended_end
        else:
            start = max(window_start, end - minimum)
    return start, end


def activity_cluster_bounds(start, end, activities, policy):
    """Build bounded estimated sessions from timestamps; every session has evidence."""
    points = []
    for activity in activities:
        timestamp = parse_dt(activity.get("timestamp"))
        if timestamp and timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone(start.tzinfo)
            if start <= timestamp < end:
                points.append(timestamp)
    points.sort()
    if not points:
        return []

    gap = datetime.timedelta(minutes=policy["inactivity_gap_minutes"])
    maximum = datetime.timedelta(minutes=policy["maximum_block_minutes"])
    clusters = []
    first = previous = points[0]
    for point in points[1:]:
        proposed = _materialize_cluster(first, point, start, end, policy)
        if point - previous > gap or proposed[1] - proposed[0] > maximum:
            clusters.append(_materialize_cluster(first, previous, start, end, policy))
            first = point
        previous = point
    clusters.append(_materialize_cluster(first, previous, start, end, policy))

    # Defensive validation: inferred intervals must be ordered, disjoint and
    # bounded. A policy that cannot meet these invariants is rejected.
    for index, (cluster_start, cluster_end) in enumerate(clusters):
        duration = cluster_end - cluster_start
        if (not start <= cluster_start < cluster_end <= end
                or duration < datetime.timedelta(minutes=policy["minimum_block_minutes"])
                or duration > maximum
                or (index and clusters[index - 1][1] > cluster_start)):
            raise BlockIdentityError("Activity cluster policy produced invalid or overlapping intervals")
    return clusters


def build_time_blocks(normalized_data: Dict[str, Any], *, unassigned_activity=None,
                      merge_short_commits=True,
                      short_commit_merge_minutes=SHORT_COMMIT_MERGE_MINUTES,
                      commit_allocation_version=2) -> List[Dict[str, Any]]:
    """Build timed proposals; callers persisting evidence must collect unassigned_activity."""
    if unassigned_activity is not None:
        from copy import deepcopy
        from activity_review import validate_unassigned_activity
        retained = normalized_data.get("unassigned_activity", [])
        validate_unassigned_activity(retained)
        unassigned_activity.extend(deepcopy(retained))
    try:
        tz = (resolve_timezone(normalized_data["timezone"], allow_legacy_offset=True)
              if "timezone" in normalized_data else timezone_settings()[1])
    except (ValueError, OSError) as exc:
        raise BlockIdentityError("Daily model requires a valid named timezone or legacy UTC offset") from exc
    target_date_str = normalized_data.get("date", "")
    target_date = datetime.date.fromisoformat(target_date_str) if target_date_str else datetime.datetime.now(tz).date()
    target_date_str = target_date.isoformat()
    try:
        block_policy = policy_from_model(normalized_data)
        from work_schedule import schedule_bounds
        schedule, work_windows, _ = schedule_bounds(normalized_data, target_date, tz)
    except ValueError as exc:
        raise BlockIdentityError(str(exc)) from exc
    clustered = block_policy["strategy"] == CLUSTER_STRATEGY
    if block_policy["strategy"] == COMMIT_STRATEGY:
        from commit_intervals import build_commit_intervals
        return build_commit_intervals(normalized_data, target_date, tz, unassigned_activity,
                                      merge_short_commits=merge_short_commits,
                                      short_commit_merge_minutes=short_commit_merge_minutes,
                                      allocation_version=commit_allocation_version)

    calendar = [ev for ev in normalized_data.get("calendar", [])
                if not ev.get("all_day") and not (len(ev.get("start", "")) == 10 and len(ev.get("end", "")) == 10)]
    commits = normalized_data.get("commits", [])
    # Associate each actual action at its own time, then deduplicate references
    # within each block. One PR may legitimately have actions in two blocks.
    prs = []
    for reference in normalized_data.get("pull_requests", []):
        if reference.get("events"):
            for event in reference["events"]:
                prs.append({**reference, "status": event["action"], "timestamp": event["timestamp"],
                            "actor": event.get("actor"), "events": [event]})
        else:
            prs.append(reference)
    development_activity = [*commits, *prs]

    daily_start = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=tz)
    daily_end = datetime.datetime.combine(target_date + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
    # Keep original source extents, but construct blocks only for the target day.
    scoped_calendar = []
    for ev in calendar:
        s, e = parse_dt(ev.get("start")), parse_dt(ev.get("end"))
        if not s or not e or s.tzinfo is None or e.tzinfo is None or e <= s:
            raise BlockIdentityError("Daily Calendar scope requires aware timestamps and end after start")
        if s < daily_end and e > daily_start:
            scoped_calendar.append(ev)
    calendar = scoped_calendar

    blocks: List[Dict[str, Any]] = []
    block_bounds = []

    def has_activity(start, end):
        for activity in [*commits, *prs]:
            timestamp = parse_dt(activity.get("timestamp"))
            if timestamp and timestamp.tzinfo is not None and start <= timestamp < end:
                return True
        return False

    # CASE A: Calendar events exist
    if calendar:
        day_start = work_windows[0][0] if work_windows else daily_start
        day_end = work_windows[-1][1] if work_windows else daily_end

        # Partition at event boundaries; each minute has one set of active sources.
        event_bounds = []
        for ev in calendar:
            s = parse_dt(ev["start"])
            e = parse_dt(ev["end"])
            s, e = s.astimezone(tz), e.astimezone(tz)
            s, e = max(s, daily_start), min(e, daily_end)
            event_bounds.append((s, e, ev))
        boundaries = sorted({time for s, e, _ in event_bounds for time in (s, e)})
        segments = []
        for s, e in zip(boundaries, boundaries[1:]):
            active = [dict(ev) for start, end, ev in event_bounds if start <= s and e <= end]
            if not active:
                continue
            active.sort(key=lambda ev: (parse_dt(ev["start"]), parse_dt(ev["end"]),
                                        ev.get("title", ""), ev["start"], ev["end"]))
            segments.append({
                "type": "calendar",
                "calendar_events": active,
                "calendar_titles": list(dict.fromkeys(ev.get("title", "") for ev in active if ev.get("title"))),
                "calendar_overlap": len(active) > 1,
                "start": s,
                "end": e
            })

        # Candidate gaps use the existing workday/lunch rules and 30-minute minimum;
        # timestamped activity evidence is checked below.
        timeline: List[Dict[str, Any]] = []
        cur_cursor = day_start

        def append_development_gap(start, end):
            # Intersect gaps with work windows before checking duration/activity.
            # Cluster mode then narrows each gap around timestamped activity.
            for window_start, window_end in work_windows:
                gap_start, gap_end = max(start, window_start), min(end, window_end)
                minimum = block_policy.get("minimum_block_minutes", 30) if clustered else 30
                if (gap_end - gap_start).total_seconds() < minimum * 60:
                    continue
                bounds = (activity_cluster_bounds(gap_start, gap_end, development_activity, block_policy)
                          if clustered else [(gap_start, gap_end)])
                for cluster_start, cluster_end in bounds:
                    timeline.append({
                        "type": "development",
                        "start": cluster_start,
                        "end": cluster_end,
                        "estimation_reason": ("activity_cluster" if clustered
                                              else "calendar_gap_with_activity")
                    })

        for seg in segments:
            seg_start = seg["start"]
            seg_end = seg["end"]

            # If there's a gap between cur_cursor and seg_start
            if seg_start > cur_cursor:
                append_development_gap(cur_cursor, seg_start)

            timeline.append(seg)
            if seg_end > cur_cursor:
                cur_cursor = seg_end

        # Check gap between last event and day_end
        if cur_cursor < day_end:
            append_development_gap(cur_cursor, day_end)

        # Build blocks from timeline
        for item in timeline:
            s_dt = item["start"]
            e_dt = item["end"]
            estimated = item["type"] == "development"
            if estimated and not has_activity(s_dt, e_dt):
                continue
            blocks.append({
                "date": target_date_str,
                "start_time": format_hhmm(s_dt),
                "end_time": "24:00" if e_dt == daily_end else format_hhmm(e_dt),
                "duration_minutes": calculate_minutes(s_dt, e_dt),
                "calendar_titles": item.get("calendar_titles", []),
                **({"calendar_events": item["calendar_events"]} if not estimated else {}),
                **({"calendar_overlap": True, "review": {
                    "status": "required", "reasons": ["calendar_overlap"], "attendance": "unconfirmed"
                }} if item.get("calendar_overlap") else {}),
                "block_type": item["type"],
                "time_basis": "estimated" if estimated else "scheduled",
                **({"estimation_reason": item.get("estimation_reason", "calendar_gap_with_activity")} if estimated else {}),
                **({"review": {"status": "required", "reasons": ["inferred_activity_boundaries"]},
                    "estimation_policy": dict(block_policy)} if estimated and clustered else {}),
                "commits": [],
                "prs": []
            })
            block_bounds.append((s_dt, e_dt))

    # CASE B: Fallback when NO Calendar events exist
    else:
        if not commits and not prs:
            # Empty day
            return []

        if clustered or 'work_schedule' in normalized_data:
            for window_start, window_end in work_windows:
                if clustered and calculate_minutes(window_start, window_end) < block_policy['minimum_block_minutes']:
                    continue
                bounds = (activity_cluster_bounds(window_start, window_end, development_activity, block_policy)
                          if clustered else [(window_start, window_end)])
                for cluster_start, cluster_end in bounds:
                    blocks.append({
                        "date": target_date_str,
                        "start_time": format_hhmm(cluster_start),
                        "end_time": "24:00" if cluster_end == daily_end else format_hhmm(cluster_end),
                        "duration_minutes": calculate_minutes(cluster_start, cluster_end),
                        "calendar_titles": [],
                        "commits": [],
                        "prs": [],
                        "estimation_reason": "activity_cluster" if clustered else "activity_workday_window",
                        **({"review": {"status": "required", "reasons": ["inferred_activity_boundaries"]},
                            "estimation_policy": dict(block_policy)} if clustered else {}),
                    })

        # Analyze commit / PR timestamps
        all_times = []
        for c in commits:
            dt = parse_dt(c.get("timestamp"))
            if dt and dt.tzinfo is not None and daily_start <= dt < daily_end:
                all_times.append(dt)
        for p in prs:
            dt = parse_dt(p.get("timestamp"))
            if dt and dt.tzinfo is not None and daily_start <= dt < daily_end:
                all_times.append(dt)

        noon = datetime.datetime.combine(target_date, datetime.time(12, 30), tzinfo=tz)

        has_morning = any(t < noon for t in all_times)
        has_afternoon = any(t >= noon for t in all_times) if all_times else False

        if clustered or 'work_schedule' in normalized_data:
            pass
        elif has_morning and has_afternoon:
            s1 = datetime.datetime.combine(target_date, datetime.time(9, 0), tzinfo=tz)
            e1 = datetime.datetime.combine(target_date, datetime.time(12, 0), tzinfo=tz)
            s2 = datetime.datetime.combine(target_date, datetime.time(13, 30), tzinfo=tz)
            e2 = datetime.datetime.combine(target_date, datetime.time(17, 30), tzinfo=tz)
            blocks.append({
                "date": target_date_str,
                "start_time": format_hhmm(s1),
                "end_time": format_hhmm(e1),
                "duration_minutes": calculate_minutes(s1, e1),
                "calendar_titles": [],
                "commits": [],
                "prs": []
            })
            blocks.append({
                "date": target_date_str,
                "start_time": format_hhmm(s2),
                "end_time": format_hhmm(e2),
                "duration_minutes": calculate_minutes(s2, e2),
                "calendar_titles": [],
                "commits": [],
                "prs": []
            })
        elif has_afternoon:
            s = datetime.datetime.combine(target_date, datetime.time(13, 30), tzinfo=tz)
            e = datetime.datetime.combine(target_date, datetime.time(17, 30), tzinfo=tz)
            blocks.append({
                "date": target_date_str,
                "start_time": format_hhmm(s),
                "end_time": format_hhmm(e),
                "duration_minutes": calculate_minutes(s, e),
                "calendar_titles": [],
                "commits": [],
                "prs": []
            })
        elif has_morning:
            s = datetime.datetime.combine(target_date, datetime.time(9, 0), tzinfo=tz)
            e = datetime.datetime.combine(target_date, datetime.time(12, 30), tzinfo=tz)
            blocks.append({
                "date": target_date_str,
                "start_time": format_hhmm(s),
                "end_time": format_hhmm(e),
                "duration_minutes": calculate_minutes(s, e),
                "calendar_titles": [],
                "commits": [],
                "prs": []
            })

    if not calendar:
        for block in blocks:
            block["block_type"] = "development"
            block["time_basis"] = "estimated"
            block.setdefault("estimation_reason", "activity_workday_window")
            start = datetime.datetime.combine(target_date, datetime.time.fromisoformat(block["start_time"]), tzinfo=tz)
            from work_schedule import local_clock
            end = local_clock(target_date, block["end_time"], tz)
            block_bounds.append((start, end))

        # A timestamp outside the candidate window must not create estimated hours.
        supported = [(block, bounds) for block, bounds in zip(blocks, block_bounds)
                     if has_activity(*bounds)]
        blocks = [block for block, _ in supported]
        block_bounds = [bounds for _, bounds in supported]

    for block, (start, end) in zip(blocks, block_bounds):
        block["interval"] = {"start": start.isoformat(), "end": end.isoformat()}
        block["timezone"] = normalized_data.get("timezone", getattr(tz, "key", str(tz)))
        if 'work_schedule' in normalized_data:
            from copy import deepcopy
            block['work_schedule'] = deepcopy(schedule)

    def retain_unassigned(source, activity, timestamp):
        if unassigned_activity is None:
            return
        if not activity.get("timestamp"):
            reason = "missing_timestamp"
        elif timestamp is None:
            reason = "invalid_timestamp"
        elif timestamp.tzinfo is None:
            reason = "naive_timestamp"
        elif not daily_start <= timestamp < daily_end:
            reason = "outside_target_day"
        else:
            reason = "outside_blocks"
        unassigned_activity.append({"source": source, "reason": reason, "activity": dict(activity)})

    # Use the same aware intervals for qualifying gap evidence and direct assignment.
    for c in commits:
        c_dt = parse_dt(c.get("timestamp"))
        assigned = False
        if c_dt and c_dt.tzinfo is not None:
            for b, (start, end) in zip(blocks, block_bounds):
                if start <= c_dt < end:
                    b["commits"].append(c)
                    assigned = True
                    break
        if not assigned:
            retain_unassigned("git", c, c_dt)

    # Associate PRs with blocks
    for p in prs:
        p_dt = parse_dt(p.get("timestamp"))
        assigned = False
        if p_dt and p_dt.tzinfo is not None:
            for b, (start, end) in zip(blocks, block_bounds):
                if start <= p_dt < end:
                    b["prs"].append(p)
                    assigned = True
                    break
        if not assigned:
            retain_unassigned("github", p, p_dt)

    from get_pr_activity import deduplicate_prs
    for block in blocks:
        block["prs"] = deduplicate_prs(block["prs"])
    return blocks


def _main():
    parser = argparse.ArgumentParser(description="Build candidate time blocks and associate activities.")
    parser.add_argument("--normalized-file", "-i", type=str, required=True, help="Path to normalized activity JSON file")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output time blocks JSON file")

    args = parser.parse_args()

    norm_path = Path(args.normalized_file)
    if not norm_path.exists():
        print(f"Error: {args.normalized_file} not found.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(norm_path.read_text(encoding="utf-8"))
    unassigned = []
    blocks = build_time_blocks(data, unassigned_activity=unassigned)
    output_json = json.dumps({"blocks": blocks, "unassigned_activity": unassigned}, indent=2)
    if args.output and args.output != "-":
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


def main():
    try:
        return _main()
    except (OSError, ValueError) as exc:
        print(f"Output/validation blocked ({type(exc).__name__}); review supplied inputs and output path.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
