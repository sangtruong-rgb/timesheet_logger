#!/usr/bin/env python3
"""
build_time_blocks.py - Deterministic time blocking and activity association.

Rules:
1. When calendar events exist:
   - Calendar events define explicit blocks (meetings, stand-ups, focus time).
   - Development gaps require a timestamped commit/PR inside their interval.
     These durations are estimated, not proof of continuous work.
   - All development gaps exclude 12:00–13:30 before checking activity.
     Scheduled Calendar events during lunch are retained.
2. When NO calendar events exist (deterministic fallback):
   - Inspect commit and PR timestamps.
   - If activity exists only in morning (< 12:30): block is 09:00–12:30.
   - If activity exists only in afternoon (>= 12:30): block is 13:30–17:30.
   - If activity spans both: split into 09:00–12:00 and 13:30–17:30.
3. Associate commits and PRs deterministically with time blocks based on timestamps.
4. Calculate duration in minutes/hours deterministically in code.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


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
    delta = end_dt - start_dt
    return max(0, int(delta.total_seconds() // 60))


def build_time_blocks(normalized_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    target_date_str = normalized_data.get("date", "")
    target_date = datetime.date.fromisoformat(target_date_str) if target_date_str else datetime.date.today()

    calendar = normalized_data.get("calendar", [])
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

    # Extract timezone from calendar or commits or default to system
    tz = datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc
    if calendar and parse_dt(calendar[0].get("start")):
        tz = parse_dt(calendar[0]["start"]).tzinfo or tz
    elif commits and parse_dt(commits[0].get("timestamp")):
        tz = parse_dt(commits[0]["timestamp"]).tzinfo or tz

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
        # Sort calendar events
        sorted_events = sorted(
            [e for e in calendar if parse_dt(e.get("start")) and parse_dt(e.get("end"))],
            key=lambda e: parse_dt(e["start"])
        )

        # Standard bounds
        day_start = datetime.datetime.combine(target_date, datetime.time(9, 0), tzinfo=tz)
        lunch_start = datetime.datetime.combine(target_date, datetime.time(12, 0), tzinfo=tz)
        lunch_end = datetime.datetime.combine(target_date, datetime.time(13, 30), tzinfo=tz)
        day_end = datetime.datetime.combine(target_date, datetime.time(17, 30), tzinfo=tz)

        # We construct timeline segments
        segments = []
        for ev in sorted_events:
            s = parse_dt(ev["start"])
            e = parse_dt(ev["end"])
            segments.append({
                "type": "calendar",
                "title": ev.get("title", ""),
                "start": s,
                "end": e
            })

        # Candidate gaps use the existing workday/lunch rules and 30-minute minimum;
        # timestamped activity evidence is checked below.
        timeline: List[Dict[str, Any]] = []
        cur_cursor = day_start

        def append_development_gap(start, end):
            # Subtract lunch first, then apply the existing 30-minute minimum
            # to each remaining interval. Activity is checked per interval below.
            for gap_start, gap_end in ((start, min(end, lunch_start)),
                                       (max(start, lunch_end), end)):
                if (gap_end - gap_start).total_seconds() >= 1800:
                    timeline.append({
                        "type": "development",
                        "start": gap_start,
                        "end": gap_end
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
                "end_time": format_hhmm(e_dt),
                "duration_minutes": calculate_minutes(s_dt, e_dt),
                "calendar_titles": [item["title"]] if not estimated and item.get("title") else [],
                "block_type": item["type"],
                "time_basis": "estimated" if estimated else "scheduled",
                **({"estimation_reason": "calendar_gap_with_activity"} if estimated else {}),
                "commits": [],
                "prs": []
            })
            block_bounds.append((s_dt, e_dt))

    # CASE B: Fallback when NO Calendar events exist
    else:
        if not commits and not prs:
            # Empty day
            return []

        # Analyze commit / PR timestamps
        all_times = []
        for c in commits:
            dt = parse_dt(c.get("timestamp"))
            if dt:
                all_times.append(dt)
        for p in prs:
            dt = parse_dt(p.get("timestamp"))
            if dt:
                all_times.append(dt)

        noon = datetime.datetime.combine(target_date, datetime.time(12, 30), tzinfo=tz)

        has_morning = any(t < noon for t in all_times) if all_times else True
        has_afternoon = any(t >= noon for t in all_times) if all_times else False

        if has_morning and has_afternoon:
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
        else:
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
            block["estimation_reason"] = "activity_workday_window"
            start = datetime.datetime.combine(target_date, datetime.time.fromisoformat(block["start_time"]), tzinfo=tz)
            end = datetime.datetime.combine(target_date, datetime.time.fromisoformat(block["end_time"]), tzinfo=tz)
            block_bounds.append((start, end))

    # Use the same aware intervals for qualifying gap evidence and direct assignment.
    unassigned_commits = []
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
            unassigned_commits.append(c)

    # Existing unmatched-activity fallback remains pending F08 review.
    if unassigned_commits and blocks:
        # Find development block or first available block
        dev_blocks = [b for b in blocks if b.get("block_type") == "development" or "Focus" in "".join(b["calendar_titles"])]
        target_b = dev_blocks[0] if dev_blocks else blocks[-1]
        for c in unassigned_commits:
            target_b["commits"].append(c)

    # Associate PRs with blocks
    unassigned_prs = []
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
            unassigned_prs.append(p)

    if unassigned_prs and blocks:
        # Associate with the block that has commits, or first development block
        blocks_with_commits = [b for b in blocks if b["commits"]]
        target_b = blocks_with_commits[0] if blocks_with_commits else blocks[0]
        for p in unassigned_prs:
            target_b["prs"].append(p)

    from get_pr_activity import deduplicate_prs
    for block in blocks:
        block["prs"] = deduplicate_prs(block["prs"])
    return blocks


def main():
    parser = argparse.ArgumentParser(description="Build candidate time blocks and associate activities.")
    parser.add_argument("--normalized-file", "-i", type=str, required=True, help="Path to normalized activity JSON file")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output time blocks JSON file")

    args = parser.parse_args()

    norm_path = Path(args.normalized_file)
    if not norm_path.exists():
        print(f"Error: {args.normalized_file} not found.", file=sys.stderr)
        sys.exit(1)

    data = json.loads(norm_path.read_text(encoding="utf-8"))
    blocks = build_time_blocks(data)

    output_json = json.dumps(blocks, indent=2)
    if args.output and args.output != "-":
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
