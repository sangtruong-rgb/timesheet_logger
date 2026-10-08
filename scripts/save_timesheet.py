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

import re
import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple
from activity_review import REASONS, validate_unassigned_activity, unpack_activity_snapshot
from atomic_storage import StorageError, directory_lock, write_bundle
from output_paths import validate_auxiliary_output, OutputPathError


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


def render_markdown(date_str: str, items: List[Dict[str, Any]], collection_status=None, calendar_context=None,
                    unassigned_activity=None) -> str:
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

    has_estimates = any(item.get("time_basis") == "estimated" for item in items)
    has_schedule = any(item.get("time_basis") == "scheduled" for item in items)
    if has_schedule:
        lines[4:4] = ["> Theo lịch, chưa xác nhận tham dự. Scheduled intervals are proposals, including future meetings; they are not confirmed work time.", ""]
    has_overlap = any(item.get("calendar_overlap") for item in items)
    if has_overlap:
        lines[4:4] = ["> REVIEW REQUIRED: overlapping Calendar events need attendance confirmation. Scheduled coverage is not confirmed meeting time.", ""]
    has_inferred_boundaries = any("inferred_activity_boundaries" in item.get("review", {}).get("reasons", [])
                                  for item in items)
    if has_inferred_boundaries:
        lines[4:4] = ["> REVIEW REQUIRED: development boundaries were inferred from activity clusters; confirm them before publishing.", ""]
    if has_estimates:
        lines[4:4] = ["> Estimated intervals are proposals based on activity timestamps, not measured work time.", ""]
    if any(item.get("estimation_policy", {}).get("strategy") == "commit_intervals" for item in items):
        lines[4:4] = ["> Commit intervals: confirmed daily start → each closing commit; lunch 12:00–13:30 and scheduled Calendar intervals are excluded. Continuous work is assumed between commits. Time after the last commit is included only with a confirmed end. Closing commit evidence may describe multiple split rows.", ""]
    if unassigned_activity:
        lines[4:4] = ["> REVIEW REQUIRED: some activity could not be assigned by timestamp. It contributes no work duration.", ""]

    total_minutes = 0
    scheduled_minutes = 0
    estimated_minutes = 0
    overlap_minutes = 0
    for it in items:
        e = it.get("entry", {})
        s = it.get("sources", {})
        start = e.get("start", "")
        end = e.get("end", "")
        dur = e.get("duration_minutes", 0)
        total_minutes += dur
        basis = it.get("time_basis")
        if basis == "scheduled":
            scheduled_minutes += dur
        elif basis == "estimated":
            estimated_minutes += dur
        duration_text = f"{dur}m" + (f" ({basis})" if basis in ("scheduled", "estimated") else "")
        if it.get("calendar_overlap"):
            overlap_minutes += dur
            duration_text += " — attendance review required"
        elif "inferred_activity_boundaries" in it.get("review", {}).get("reasons", []):
            duration_text += " — boundary review required"
        desc = markdown_cell(e.get("description", ""))

        src_parts = []
        cals = s.get("calendar", [])
        commits = s.get("commits", [])
        prs = s.get("pull_requests", [])

        if cals:
            src_parts.append(f"Cal: {', '.join(cals)}")
        if commits:
            src_parts.append(f"{len(commits)} commit{'s' if len(commits) > 1 else ''}")
        if prs:
            from build_timesheet import format_pr_suffix
            src_parts.append(format_pr_suffix(prs))

        evidence_str = markdown_cell("; ".join(src_parts) if src_parts else "Manual")
        lines.append(f"| {start} – {end} | {duration_text} | {desc} | {evidence_str} |")

    hours = total_minutes // 60
    mins = total_minutes % 60
    lines.append("")
    total_label = "Total Proposed Time" if has_estimates or has_schedule or has_overlap or unassigned_activity else "Total Tracked Time"
    lines.append(f"**{total_label}:** {total_minutes} mins ({hours}h {mins:02d}m)")
    if any(item.get("time_basis") in ("scheduled", "estimated") for item in items):
        lines.append(f"Scheduled Calendar: {scheduled_minutes} mins; estimated development: {estimated_minutes} mins; "
                     f"manual/unclassified: {total_minutes - scheduled_minutes - estimated_minutes} mins.")
    if has_overlap:
        lines.append(f"Calendar overlap awaiting attendance confirmation: {overlap_minutes} mins (included in scheduled total).")
    lines.append("")
    if calendar_context:
        lines.extend(["## Calendar context (not counted as work time)", "",
                      "All-day events provide context; they do not confirm work duration or a day off.", ""])
        for event in calendar_context:
            title = event["title"].replace("\n", " ")
            lines.append(f"- {title} — all-day, {event['start']} to {event['end']} (end date exclusive).")
        lines.append("")
    if unassigned_activity:
        lines.extend(["## Unassigned activity — review required", "",
                      "These events are retained as evidence, outside timed entries and totals.", ""])
        for record in unassigned_activity:
            activity = record["activity"]
            identity = (f"Commit {activity.get('hash', '(unknown)')}: {activity.get('message', '')}"
                        if record["source"] == "git" else
                        f"Calendar: {activity['title']} ({activity['start']} to {activity['end']})"
                        if record["source"] == "google_calendar" else
                        f"PR #{activity['id']} ({activity.get('repository', '')}), {activity.get('status', '')}: {activity.get('title', '')}")
            timestamp = activity.get("timestamp") or "(missing)"
            lines.append(f"- {identity} — {timestamp}; {REASONS[record['reason']]}.".replace("\n", " "))
        lines.append("")
    return "\n".join(lines)


def markdown_cell(value):
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


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
    try:
        from interval_validation import validate_interval
        validate_interval(target_date, entry["start"], entry["end"], duration, item.get("interval"))
    except ValueError as exc:
        raise TimesheetReconciliationError(str(exc)) from exc
    for field in ("commits", "pull_requests", "calendar_events", "calendar"):
        values = item.get("sources", {}).get(field, [])
        if not isinstance(values, list) or any(not isinstance(v, str if field == "calendar" else dict) for v in values):
            raise TimesheetReconciliationError("Invalid source evidence arrays in stored/incoming row")
    return start, end


def validate_generated_suffix(item):
    try:
        from build_timesheet import format_pr_suffix
        references = item.get("sources", {}).get("pull_requests", [])
        for pr in references:
            if isinstance(pr.get("id"), bool) or not isinstance(pr.get("id"), int) or pr["id"] < 1:
                raise ValueError("Invalid PR identity")
            if not isinstance(pr.get("repository", ""), str): raise ValueError("Invalid repository")
        description = item["entry"]["description"]
        if len(re.findall(r"\bPRs\s*:", description, re.IGNORECASE)) != 1 or not description.endswith(format_pr_suffix(references)):
            raise ValueError("Suffix conflicts with source references")
    except (ValueError, TypeError, KeyError) as exc:
        raise TimesheetReconciliationError("Generated description must end with exactly one script-owned suffix matching its source PRs") from exc


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
            validate_generated_suffix(item)
            old_generated[key] = item
        elif kind in ("manual", "override"):
            protected.append(item)
        else:
            raise TimesheetReconciliationError("Unknown row provenance; review before reconciliation")

    for item in incoming:
        start, end = entry_interval(item, target_date)
        metadata = item.get("collection", {})
        if not isinstance(metadata, dict) or metadata.get("status", collection_status) != collection_status:
            raise TimesheetReconciliationError("Incoming row collection status does not match the successful snapshot")
        if item["entry"]["description"].count("PRs:") != 1:
            raise TimesheetReconciliationError("Generated descriptions require exactly one script-owned PRs suffix")
        for field in ("commits", "pull_requests", "calendar_events", "calendar"):
            values = item.get("sources", {}).get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str if field == "calendar" else dict) for v in values):
                raise TimesheetReconciliationError("Invalid generated source evidence arrays")
        validate_generated_suffix(item)
        provenance = item.get("provenance")
        if provenance is not None and provenance != {"kind": "generated", "generator": "timesheet_logger"}:
            raise TimesheetReconciliationError("Incoming snapshots may only contain pipeline-generated rows")
        key = get_entry_key(item)
        if key in candidates:
            raise TimesheetReconciliationError("Incoming snapshot has duplicate intervals")
        for candidate in candidates.values():
            other_start, other_end = entry_interval(candidate, target_date)
            if start < other_end and other_start < end:
                raise TimesheetReconciliationError(
                    f"Generated intervals {candidate['entry']['start']}–{candidate['entry']['end']} and "
                    f"{item['entry']['start']}–{item['entry']['end']} overlap; review required")
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


def validate_calendar_context(context, target_date):
    """All-day context has date extents, never daily entry intervals or durations."""
    if not isinstance(context, list):
        raise TimesheetReconciliationError("Calendar context must be an array")
    for event in context:
        try:
            if not isinstance(event, dict) or event.get("all_day") is not True or not isinstance(event.get("title"), str):
                raise ValueError("Invalid context")
            start, end = (datetime.date.fromisoformat(event[key]) for key in ("start", "end"))
            if (start.isoformat() != event["start"] or end.isoformat() != event["end"]
                    or not start <= datetime.date.fromisoformat(target_date) < end):
                raise ValueError("Context outside target day")
        except (KeyError, TypeError, ValueError) as exc:
            raise TimesheetReconciliationError("All-day context requires valid dates overlapping the target day") from exc


def save_timesheet(entries, output_dir="data/timesheets", *, target_date, collection_status, calendar_context=None,
                   unassigned_activity=None, collection_manifest=None, extra_files=None, token_records=None, token_csv=None):
    try:
        for path in (extra_files or {}):
            validate_auxiliary_output(path)
        if token_records and token_csv is None:
            raise TimesheetReconciliationError("Token CSV path required for usage")
        extra = list(extra_files or {}) + ([token_csv] if token_records else [])
        with directory_lock(output_dir, extra_paths=extra):
            return _save_timesheet(entries, output_dir, target_date=target_date, collection_status=collection_status,
                calendar_context=calendar_context, unassigned_activity=unassigned_activity,
                collection_manifest=collection_manifest, extra_files=extra_files, token_records=token_records, token_csv=token_csv)
    except (OutputPathError, StorageError, OSError) as exc:
        raise TimesheetReconciliationError(str(exc)) from exc


def _save_timesheet(entries, output_dir="data/timesheets", *, target_date, collection_status, calendar_context=None,
                   unassigned_activity=None, collection_manifest=None, extra_files=None, token_records=None, token_csv=None):
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
    context_file = dir_path / f"{target_date}.calendar-context.json"
    old_context = None
    if context_file.exists():
        try:
            old_context = json.loads(context_file.read_text(encoding="utf-8"))
            if (not isinstance(old_context, dict) or old_context.get("date") != target_date
                    or old_context.get("collection_status") not in ("complete", "demo")):
                raise ValueError("Invalid context store")
            validate_calendar_context(old_context["calendar_context"], target_date)
        except (KeyError, ValueError, OSError) as exc:
            raise TimesheetReconciliationError("Cannot read existing Calendar context; original files were preserved") from exc
    # Standalone callers omitting context preserve it; a supplied [] clears old context.
    context = calendar_context
    if context is None:
        context = old_context["calendar_context"] if old_context else []
    validate_calendar_context(context, target_date)
    context_record = {"date": target_date, "collection_status": collection_status, "calendar_context": context}
    write_context = bool(context) or context_file.exists()
    context_changed = write_context and context_record != old_context
    review_file = dir_path / f"{target_date}.activity-review.json"
    old_review = None
    try:
        if review_file.exists():
            old_review = json.loads(review_file.read_text(encoding="utf-8"))
            if (not isinstance(old_review, dict) or old_review.get("date") != target_date
                    or old_review.get("collection_status") not in ("complete", "demo")):
                raise ValueError("Invalid activity review store")
            validate_unassigned_activity(old_review["unassigned_activity"])
            expected = "required" if old_review["unassigned_activity"] else "none"
            if old_review.get("review") != {"status": expected}:
                raise ValueError("Invalid activity review status")
        unassigned = unassigned_activity
        if unassigned is None:
            unassigned = old_review["unassigned_activity"] if old_review else []
        validate_unassigned_activity(unassigned)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise TimesheetReconciliationError("Invalid unassigned activity/review store; original files were preserved") from exc
    review_record = {"date": target_date, "collection_status": collection_status,
                     "review": {"status": "required" if unassigned else "none"}, "unassigned_activity": unassigned}
    write_review = bool(unassigned) or review_file.exists()
    review_changed = write_review and review_record != old_review
    # Validate/render before any final output mutation. Exact reruns keep bytes unchanged.
    json_content = json.dumps(merged, indent=2)
    context_content = json.dumps(context_record, indent=2)
    md_content = render_markdown(target_date, merged, collection_status, context, unassigned)
    reserved = {json_file.resolve(), md_file.resolve(), context_file.resolve(), review_file.resolve(),
                (dir_path / f"{target_date}.collection.json").resolve()}
    for path in (extra_files or {}):
        validate_auxiliary_output(path, protected_paths=reserved)
    contents = dict(extra_files or {})
    if merged != existing or not json_file.exists():
        contents[json_file] = json_content
    if merged != existing or context_changed or review_changed or not md_file.exists():
        contents[md_file] = md_content
    if context_changed:
        contents[context_file] = context_content
    if review_changed:
        contents[review_file] = json.dumps(review_record, indent=2)
    if collection_manifest is not None:
        manifest = {"date": target_date, **collection_manifest,
            "calendar_context_count": len(context), "calendar_context_file": context_file.name if write_context else None,
            "unassigned_activity_count": len(unassigned), "activity_review_file": review_file.name if write_review else None,
            "review": {"status": "required" if unassigned or any(e.get("calendar_overlap") or e.get("time_basis") in ("scheduled", "estimated") for e in merged) else "none"}}
        contents[dir_path / f"{target_date}.collection.json"] = json.dumps(manifest, indent=2)
    if token_records:
        try:
            from collect_token_usage import csv_contents
            token_content, _ = csv_contents(token_csv, token_records)
            token_path = Path(token_csv)
            if token_path.resolve() in reserved or token_path.resolve() in {Path(p).resolve() for p in (extra_files or {})}:
                raise ValueError("Token CSV cannot overwrite timesheet/audit/AI output")
            contents[token_path] = token_content
        except (ValueError, TypeError, OSError) as exc:
            raise TimesheetReconciliationError("Token CSV validation failed; final files and token records preserved") from exc
    write_bundle(contents, dir_path)
    return {"dates": {target_date: {**counts, "json_path": str(json_file), "md_path": str(md_file),
                                   "unassigned_activity_count": len(unassigned),
                                   **({"activity_review_path": str(review_file)} if write_review else {}),
                                   **({"calendar_context_path": str(context_file)} if write_context else {})}}}


def main():
    parser = argparse.ArgumentParser(description="Reconcile one complete daily timesheet snapshot.")
    parser.add_argument("--entries-file", "-i", type=str, required=True, help="Path to entries JSON file")
    parser.add_argument("--output-dir", "-d", type=str, default="data/timesheets", help="Directory for timesheet stores")
    parser.add_argument("--date", required=True, help="Target date YYYY-MM-DD, required even for an empty snapshot")
    parser.add_argument("--calendar-context-file", help="Optional JSON array of all-day context; [] explicitly clears it")
    parser.add_argument("--unassigned-activity-file", help="Optional JSON array of unassigned evidence; [] explicitly clears it")
    parser.add_argument("--collection-status", required=True, choices=("complete", "demo"),
                        help="Assert successful full-day collection; demo output is isolated under demo/")

    args = parser.parse_args()

    in_path = Path(args.entries_file)
    if not in_path.exists():
        print(f"Error: {args.entries_file} not found.", file=sys.stderr)
        sys.exit(1)

    try:
        entries, unassigned = unpack_activity_snapshot(json.loads(in_path.read_text(encoding="utf-8")), "entries")
        if args.unassigned_activity_file:
            unassigned = json.loads(Path(args.unassigned_activity_file).read_text(encoding="utf-8"))
        context = json.loads(Path(args.calendar_context_file).read_text(encoding="utf-8")) if args.calendar_context_file else None
        output_dir = Path(args.output_dir) / "demo" if args.collection_status == "demo" else Path(args.output_dir)
        res = save_timesheet(entries, str(output_dir), target_date=args.date, collection_status=args.collection_status,
                             calendar_context=context, unassigned_activity=unassigned)
    except (KeyError, ValueError, OSError) as exc:
        print(f"Save blocked: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
