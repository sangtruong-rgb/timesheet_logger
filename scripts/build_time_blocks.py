#!/usr/bin/env python3
"""
build_time_blocks.py - Deterministic time blocking and activity association.

Rules:
1. When calendar events exist:
   - Calendar events define explicit blocks (meetings, stand-ups, focus time).
   - Significant work gaps between meetings within standard workday (09:00 - 18:00)
     are segmented into development blocks if activity exists or calendar spans it.
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
    prs = normalized_data.get("pull_requests", [])

    # Extract timezone from calendar or commits or default to system
    tz = datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc
    if calendar and parse_dt(calendar[0].get("start")):
        tz = parse_dt(calendar[0]["start"]).tzinfo or tz
    elif commits and parse_dt(commits[0].get("timestamp")):
        tz = parse_dt(commits[0]["timestamp"]).tzinfo or tz

    blocks: List[Dict[str, Any]] = []

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

        # Interleave gap blocks if there are gaps >= 45 minutes between meetings
        # and inside working hours
        timeline: List[Dict[str, Any]] = []
        cur_cursor = day_start

        for seg in segments:
            seg_start = seg["start"]
            seg_end = seg["end"]

            # If there's a gap between cur_cursor and seg_start
            if seg_start > cur_cursor:
                # Check if gap intersects lunch
                gap_start = cur_cursor
                gap_end = seg_start

                # If gap spans across lunch, split around lunch
                if gap_start < lunch_start and gap_end > lunch_end:
                    if (lunch_start - gap_start).total_seconds() >= 1800:
                        timeline.append({
                            "type": "development",
                            "title": "Development",
                            "start": gap_start,
                            "end": lunch_start
                        })
                    if (gap_end - lunch_end).total_seconds() >= 1800:
                        timeline.append({
                            "type": "development",
                            "title": "Development",
                            "start": lunch_end,
                            "end": gap_end
                        })
                elif not (gap_start >= lunch_start and gap_end <= lunch_end):
                    # Gap is not purely lunch
                    if (gap_end - gap_start).total_seconds() >= 1800:
                        # Exclude lunch if overlaps
                        actual_start = max(gap_start, lunch_end) if gap_start >= lunch_start and gap_start < lunch_end else gap_start
                        actual_end = min(gap_end, lunch_start) if gap_end > lunch_start and gap_end <= lunch_end else gap_end
                        if actual_end > actual_start and (actual_end - actual_start).total_seconds() >= 1800:
                            timeline.append({
                                "type": "development",
                                "title": "Development",
                                "start": actual_start,
                                "end": actual_end
                            })

            timeline.append(seg)
            if seg_end > cur_cursor:
                cur_cursor = seg_end

        # Check gap between last event and day_end
        if cur_cursor < day_end and (day_end - cur_cursor).total_seconds() >= 1800:
            timeline.append({
                "type": "development",
                "title": "Development",
                "start": cur_cursor,
                "end": day_end
            })

        # Build blocks from timeline
        for item in timeline:
            s_dt = item["start"]
            e_dt = item["end"]
            blocks.append({
                "date": target_date_str,
                "start_time": format_hhmm(s_dt),
                "end_time": format_hhmm(e_dt),
                "duration_minutes": calculate_minutes(s_dt, e_dt),
                "calendar_titles": [item["title"]] if item.get("title") else [],
                "commits": [],
                "prs": []
            })

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
                "calendar_titles": ["Morning Development"],
                "commits": [],
                "prs": []
            })
            blocks.append({
                "date": target_date_str,
                "start_time": format_hhmm(s2),
                "end_time": format_hhmm(e2),
                "duration_minutes": calculate_minutes(s2, e2),
                "calendar_titles": ["Afternoon Development"],
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
                "calendar_titles": ["Afternoon Development"],
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
                "calendar_titles": ["Development"],
                "commits": [],
                "prs": []
            })

    # Associate commits with blocks based on timestamp
    unassigned_commits = []
    for c in commits:
        c_dt = parse_dt(c.get("timestamp"))
        assigned = False
        if c_dt:
            c_time_str = format_hhmm(c_dt)
            for b in blocks:
                if b["start_time"] <= c_time_str < b["end_time"]:
                    b["commits"].append(c)
                    assigned = True
                    break
        if not assigned:
            unassigned_commits.append(c)

    # Distribute unassigned commits to the closest development block
    if unassigned_commits and blocks:
        # Find development block or first available block
        dev_blocks = [b for b in blocks if "Development" in "".join(b["calendar_titles"]) or "Focus" in "".join(b["calendar_titles"])]
        target_b = dev_blocks[0] if dev_blocks else blocks[-1]
        for c in unassigned_commits:
            target_b["commits"].append(c)

    # Associate PRs with blocks
    unassigned_prs = []
    for p in prs:
        p_dt = parse_dt(p.get("timestamp"))
        assigned = False
        if p_dt:
            p_time_str = format_hhmm(p_dt)
            for b in blocks:
                if b["start_time"] <= p_time_str < b["end_time"]:
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
