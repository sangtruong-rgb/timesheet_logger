#!/usr/bin/env python3
"""
save_timesheet.py - Idempotent storage for daily timesheets.

Generates both:
1. Machine-readable audit store: data/timesheets/YYYY-MM-DD.json (with source evidence)
2. Human-readable document:      data/timesheets/YYYY-MM-DD.md

Reconciles one complete daily snapshot, including a successfully empty day.
Replaces obsolete generated rows, preserves explicitly marked manual rows and
exact-interval overrides, and refuses ambiguous legacy stores or conflicts.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple


class TimesheetReconciliationError(ValueError):
    """The daily store needs review before its generated rows can be replaced."""


def get_entry_key(entry_item: Dict[str, Any]) -> str:
    e = entry_item.get("entry", {})
    return f"{e.get('date', '')}_{e.get('start', '')}_{e.get('end', '')}"


def upsert_entries(
    existing_items: List[Dict[str, Any]],
    new_items: List[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Legacy partial-merge utility; not used to persist daily snapshots.
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


def render_markdown(date_str: str, items: List[Dict[str, Any]], collection_status=None) -> str:
    lines = [
        f"# Timesheet — {date_str}",
        "",
        f"> Generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (Idempotent run)",
        "",
        "| Time | Duration | Description | Evidence / Sources |",
        "| :--- | :---: | :--- | :--- |"
    ]

    if collection_status == "demo" or any(item.get("collection", {}).get("status") == "demo" for item in items):
        lines[4:4] = ["> DEMO: contains explicitly selected fixture data; not a live work record.", ""]

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


def entry_interval(item, target_date):
    """Validate enough daily-row structure to reconcile manual conflicts safely."""
    if not isinstance(item, dict) or not isinstance(item.get("entry"), dict):
        raise TimesheetReconciliationError("Timesheet rows must contain an entry object")
    entry = item["entry"]
    if entry.get("date") != target_date:
        raise TimesheetReconciliationError("Every row must belong to the explicit target date")

    def minutes(value, allow_midnight_end=False):
        if value == "24:00" and allow_midnight_end:
            return 1440
        if not isinstance(value, str) or len(value) != 5:
            raise ValueError("Expected HH:MM")
        parsed = datetime.datetime.strptime(value, "%H:%M")
        if parsed.strftime("%H:%M") != value:
            raise ValueError("Expected HH:MM")
        return parsed.hour * 60 + parsed.minute

    try:
        start = minutes(entry.get("start"))
        end = minutes(entry.get("end"), True)
    except (TypeError, ValueError) as exc:
        raise TimesheetReconciliationError("Timesheet intervals require valid HH:MM times") from exc
    if end <= start:
        raise TimesheetReconciliationError("Timesheet intervals must end after their start; review cross-day/all-day rows")
    duration = entry.get("duration_minutes")
    if (not isinstance(duration, int) or isinstance(duration, bool) or duration < 0
            or not isinstance(entry.get("description"), str)
            or not isinstance(item.get("sources", {}), dict)):
        raise TimesheetReconciliationError("Invalid duration, description, or sources in timesheet row")
    return start, end


def reconcile_daily_entries(existing, incoming, target_date, collection_status):
    """Replace the generated set, not just matching keys; never infer legacy ownership."""
    if collection_status not in ("complete", "demo"):
        raise TimesheetReconciliationError("Only successful complete/demo snapshots may replace daily rows")
    if not isinstance(existing, list) or not isinstance(incoming, list):
        raise TimesheetReconciliationError("Timesheet stores and incoming snapshots must be JSON arrays")
    old_generated, protected, candidates = {}, [], {}
    known_keys = set()
    for item in existing:
        entry_interval(item, target_date)
        key = get_entry_key(item)
        if key in known_keys:
            raise TimesheetReconciliationError("Existing store has duplicate intervals; review before reconciliation")
        known_keys.add(key)
        provenance = item.get("provenance")
        if not isinstance(provenance, dict):
            raise TimesheetReconciliationError(
                "Legacy rows lack provenance: back up and classify them as generated, manual, or override before rerunning")
        kind = provenance.get("kind")
        if kind == "generated" and provenance.get("generator") == "timesheet_logger":
            old_generated[key] = item
        elif kind in ("manual", "override"):
            protected.append(item)
        else:
            raise TimesheetReconciliationError("Unknown row provenance; review before reconciliation")

    for item in incoming:
        entry_interval(item, target_date)
        metadata = item.get("collection", {})
        if not isinstance(metadata, dict) or metadata.get("status", collection_status) != collection_status:
            raise TimesheetReconciliationError("Incoming row collection status does not match the successful snapshot")
        provenance = item.get("provenance")
        if provenance is not None and provenance != {"kind": "generated", "generator": "timesheet_logger"}:
            raise TimesheetReconciliationError("Incoming snapshots may only contain pipeline-generated rows")
        key = get_entry_key(item)
        if key in candidates:
            raise TimesheetReconciliationError("Incoming snapshot has duplicate intervals")
        candidates[key] = {**item, "provenance": {"kind": "generated", "generator": "timesheet_logger"}}

    overridden = 0
    for item in protected:
        key = get_entry_key(item)
        if item["provenance"]["kind"] == "override" and key in candidates:
            del candidates[key]
            overridden += 1
    for item in protected:
        start, end = entry_interval(item, target_date)
        for candidate in candidates.values():
            new_start, new_end = entry_interval(candidate, target_date)
            if start < new_end and new_start < end:
                raise TimesheetReconciliationError(
                    f"Manual/override interval {item['entry']['start']}–{item['entry']['end']} overlaps regenerated rows; review required")
    for index, item in enumerate(protected):
        start, end = entry_interval(item, target_date)
        for other in protected[index + 1:]:
            other_start, other_end = entry_interval(other, target_date)
            if start < other_end and other_start < end:
                raise TimesheetReconciliationError("Protected manual/override rows overlap; review required")

    merged = sorted([*protected, *candidates.values()], key=lambda item: (item["entry"]["start"], item["entry"]["end"]))
    counts = {
        "inserted": sum(key not in old_generated for key in candidates),
        "updated": sum(key in old_generated and item != old_generated[key] for key, item in candidates.items()),
        "removed": sum(key not in candidates for key in old_generated),
        "preserved_manual": len(protected),
        "overridden": overridden,
        "total_entries": len(merged),
    }
    return merged, counts


def save_timesheet(entries, output_dir="data/timesheets", *, target_date, collection_status):
    """Persist exactly one successful daily snapshot; [] explicitly clears generated rows."""
    try:
        if datetime.date.fromisoformat(target_date).isoformat() != target_date:
            raise ValueError("Noncanonical date")
    except (TypeError, ValueError) as exc:
        raise TimesheetReconciliationError("An explicit YYYY-MM-DD target date is required") from exc
    dir_path = Path(output_dir)
    json_file = dir_path / f"{target_date}.json"
    md_file = dir_path / f"{target_date}.md"
    if md_file.exists() and not json_file.exists():
        raise TimesheetReconciliationError("Markdown exists without its audit JSON; review before replacing it")
    existing = []
    if json_file.exists():
        try:
            existing = json.loads(json_file.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise TimesheetReconciliationError("Cannot read existing daily JSON; original files were preserved") from exc
    merged, counts = reconcile_daily_entries(existing, entries, target_date, collection_status)
    # Validate/render before any final output mutation. Exact reruns keep bytes unchanged.
    json_content = json.dumps(merged, indent=2)
    md_content = render_markdown(target_date, merged, collection_status)
    dir_path.mkdir(parents=True, exist_ok=True)
    if merged != existing or not json_file.exists():
        json_file.write_text(json_content, encoding="utf-8")
    if merged != existing or not md_file.exists():
        md_file.write_text(md_content, encoding="utf-8")
    return {"dates": {target_date: {**counts, "json_path": str(json_file), "md_path": str(md_file)}}}


def main():
    parser = argparse.ArgumentParser(description="Reconcile one complete daily timesheet snapshot.")
    parser.add_argument("--entries-file", "-i", type=str, required=True, help="Path to entries JSON file")
    parser.add_argument("--output-dir", "-d", type=str, default="data/timesheets", help="Directory for timesheet stores")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD, required even for an empty snapshot")
    parser.add_argument("--collection-status", required=True, choices=("complete", "demo"),
                        help="Assert successful full-day collection; demo output is isolated under demo/")

    args = parser.parse_args()

    in_path = Path(args.entries_file)
    if not in_path.exists():
        print(f"Error: {args.entries_file} not found.", file=sys.stderr)
        sys.exit(1)

    try:
        entries = json.loads(in_path.read_text(encoding="utf-8"))
        output_dir = Path(args.output_dir) / "demo" if args.collection_status == "demo" else Path(args.output_dir)
        res = save_timesheet(entries, str(output_dir), target_date=args.date, collection_status=args.collection_status)
    except (ValueError, OSError) as exc:
        print(f"Save blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
