#!/usr/bin/env python3
"""
save_timesheet.py - Idempotent storage for daily timesheets.

Generates both:
1. Machine-readable audit store: data/timesheets/YYYY-MM-DD.json (with source evidence)
2. Human-readable document:      data/timesheets/YYYY-MM-DD.md

Ensures idempotency:
- Uses stable key (date + start + end).
- Running multiple times updates existing entries or skips unchanged entries.
- Never blindly duplicates timesheet rows.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple


def get_entry_key(entry_item: Dict[str, Any]) -> str:
    e = entry_item.get("entry", {})
    return f"{e.get('date', '')}_{e.get('start', '')}_{e.get('end', '')}"


def upsert_entries(
    existing_items: List[Dict[str, Any]],
    new_items: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Idempotently merge new_items into existing_items.
    Returns (merged_items, inserted_count, updated_count).
    """
    merged_map: Dict[str, Dict[str, Any]] = {}
    for item in existing_items:
        key = get_entry_key(item)
        merged_map[key] = item

    inserted = 0
    updated = 0

    for item in new_items:
        key = get_entry_key(item)
        if key in merged_map:
            # Check if description or sources changed
            if merged_map[key] != item:
                merged_map[key] = item
                updated += 1
        else:
            merged_map[key] = item
            inserted += 1

    # Sort merged entries by start time
    sorted_items = list(merged_map.values())
    sorted_items.sort(key=lambda x: x.get("entry", {}).get("start", ""))
    return sorted_items, inserted, updated


def render_markdown(date_str: str, items: List[Dict[str, Any]]) -> str:
    lines = [
        f"# Timesheet — {date_str}",
        "",
        f"> Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Idempotent run)",
        "",
        "| Time | Duration | Description | Evidence / Sources |",
        "| :--- | :---: | :--- | :--- |"
    ]

    total_minutes = 0
    for it in items:
        e = it.get("entry", {})
        s = it.get("sources", {})
        start = e.get("start", "")
        end = e.get("end", "")
        dur = e.get("duration_minutes", 0)
        total_minutes += dur
        desc = e.get("description", "").replace("\n", " ").replace("|", "\\|")

        src_parts = []
        cals = s.get("calendar", [])
        commits = s.get("commits", [])
        prs = s.get("pull_requests", [])

        if cals:
            src_parts.append(f"Cal: {', '.join(cals)}")
        if commits:
            src_parts.append(f"{len(commits)} commit{'s' if len(commits) > 1 else ''}")
        if prs:
            pr_tags = [f"#{p.get('id')}" for p in prs if p.get('id') is not None]
            src_parts.append(f"PRs: {', '.join(pr_tags)}")

        evidence_str = "; ".join(src_parts) if src_parts else "Manual"
        lines.append(f"| {start} – {end} | {dur}m | {desc} | {evidence_str} |")

    hours = total_minutes // 60
    mins = total_minutes % 60
    lines.append("")
    lines.append(f"**Total Tracked Time:** {total_minutes} mins ({hours}h {mins:02d}m)")
    lines.append("")
    return "\n".join(lines)


def save_timesheet(
    entries: List[Dict[str, Any]],
    output_dir: str = "data/timesheets"
) -> Dict[str, Any]:
    if not entries:
        return {"status": "empty", "inserted": 0, "updated": 0, "total": 0}

    # Group incoming entries by date
    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for it in entries:
        d = it.get("entry", {}).get("date") or datetime.date.today().isoformat()
        by_date.setdefault(d, []).append(it)

    dir_path = Path(output_dir)
    dir_path.mkdir(parents=True, exist_ok=True)

    summary = {"dates": {}}
    for d, date_entries in by_date.items():
        json_file = dir_path / f"{d}.json"
        md_file = dir_path / f"{d}.md"

        existing_entries = []
        if json_file.exists():
            try:
                existing_entries = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                existing_entries = []

        merged, ins, upd = upsert_entries(existing_entries, date_entries)

        # Write JSON
        json_file.write_text(json.dumps(merged, indent=2), encoding="utf-8")

        # Write Markdown
        md_content = render_markdown(d, merged)
        md_file.write_text(md_content, encoding="utf-8")

        summary["dates"][d] = {
            "inserted": ins,
            "updated": upd,
            "total_entries": len(merged),
            "json_path": str(json_file),
            "md_path": str(md_file)
        }

    return summary


def main():
    parser = argparse.ArgumentParser(description="Save timesheet entries idempotently.")
    parser.add_argument("--entries-file", "-i", type=str, required=True, help="Path to entries JSON file")
    parser.add_argument("--output-dir", "-d", type=str, default="data/timesheets", help="Directory for timesheet stores")

    args = parser.parse_args()

    in_path = Path(args.entries_file)
    if not in_path.exists():
        print(f"Error: {args.entries_file} not found.", file=sys.stderr)
        sys.exit(1)

    entries = json.loads(in_path.read_text(encoding="utf-8"))
    res = save_timesheet(entries, args.output_dir)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
