#!/usr/bin/env python3
"""
normalize_activity.py - Deterministic normalizer combining Git, PR, and Calendar sources.

Produces a compact daily model:
{
  "date": "2026-10-06",
  "timezone": "+07:00",
  "calendar": [...],
  "commits": [...],
  "pull_requests": [...]
}

Ensures:
- Raw API fields are stripped
- Timestamps are properly normalized and sorted
- Duplicates are eliminated
- Output payload is minimal and deterministic
"""

import argparse
import datetime
import json
import sys
from pathlib import Path
from activity_settings import add_timezone_arguments, timezone_settings, resolve_timezone, day_bounds, timestamp_sort_key


def get_local_timezone_str() -> str:
    """Compatibility helper returning the profile's authoritative named zone."""
    return timezone_settings()[0]


class ActivityNormalizationError(ValueError):
    """Malformed source structure cannot safely become a final daily snapshot."""
    def __init__(self, source, index, reason):
        self.issues = [{"source": source, "index": index, "reason": reason}]
        super().__init__(f"{source}[{index}]: {reason}")


def _fail(source, index, reason):
    raise ActivityNormalizationError(source, index, reason)


def _rows(value, source):
    if not isinstance(value, list):
        _fail(source, None, "Source records must be an array")
    for index, record in enumerate(value):
        if not isinstance(record, dict):
            _fail(source, index, "Source record must be an object")
        yield index, record


def _text(record, field, source, index, default="", allow_none=False):
    value = record.get(field, default)
    if allow_none and value is None:
        return None
    if not isinstance(value, str):
        _fail(source, index, f"{field} must be a string")
    return value


def clean_commits(raw_commits):
    seen, cleaned = {}, []
    for index, c in _rows(raw_commits, "git"):
        for field in ("hash", "short_hash"):
            if field in c:
                _text(c, field, "git", index)
        h = c.get("hash") or c.get("short_hash")
        if not h or not h.strip():
            _fail("git", index, "Commit identity requires a nonempty hash or short_hash")
        repo = _text(c, "repository", "git", index, "default")
        record = {"repository": repo, "hash": h,
                  "short_hash": _text(c, "short_hash", "git", index, h[:7]),
                  "timestamp": c.get("timestamp"),
                  "author": _text(c, "author", "git", index),
                  "message": _text(c, "message", "git", index).strip(),
                  "branch": _text(c, "branch", "git", index, None, allow_none=True)}
        for field in ("github_author", "identity_match", "original_timestamp"):
            if c.get(field) is not None:
                record[field] = _text(c, field, "git", index)
        key = (repo, h)
        if key in seen:
            if record != seen[key]:
                _fail("git", index, "Conflicting records for the same qualified commit identity")
            continue
        seen[key] = record
        cleaned.append(record)
    return sorted(cleaned, key=lambda x: (timestamp_sort_key(x.get("timestamp")), x["repository"], x["hash"]))


def clean_prs(raw_prs):
    from get_pr_activity import deduplicate_prs
    cleaned = []
    for index, pr in _rows(raw_prs, "github"):
        if not isinstance(pr.get("id"), int) or isinstance(pr["id"], bool) or pr["id"] <= 0:
            _fail("github", index, "PR identity requires a positive integer id")
        record = {"id": pr["id"], "repository": _text(pr, "repository", "github", index),
                  "title": _text(pr, "title", "github", index)}
        for field in ("url", "original_timestamp"):
            if field in pr:
                record[field] = _text(pr, field, "github", index)
        for field in ("status", "timestamp", "actor"):
            if field in pr:
                record[field] = pr[field]
        if record.get("status", "opened") not in ("opened", "reviewed", "merged"):
            _fail("github", index, "Unsupported PR action")
        if record.get("actor") is not None:
            _text(record, "actor", "github", index)
        if "events" in pr:
            if not isinstance(pr["events"], list):
                _fail("github", index, "PR events must be an array")
            events = []
            for event in pr["events"]:
                if not isinstance(event, dict) or event.get("action") not in ("opened", "reviewed", "merged"):
                    _fail("github", index, "Each PR event requires a supported action")
                item = {"action": event["action"], "timestamp": event.get("timestamp")}
                for field in ("actor", "original_timestamp"):
                    if field in event:
                        item[field] = _text(event, field, "github", index, allow_none=field == "actor")
                if "id" in event:
                    if not isinstance(event["id"], int) or isinstance(event["id"], bool) or event["id"] <= 0:
                        _fail("github", index, "PR event identity must be a positive integer")
                    item["id"] = event["id"]
                events.append(item)
            record["events"] = events
        if not record.get("events"):
            record["events"] = [{"action": record.get("status", "opened"), "timestamp": record.get("timestamp"),
                                 **({"actor": record["actor"]} if "actor" in record else {}),
                                 **({"original_timestamp": record["original_timestamp"]} if "original_timestamp" in record else {})}]
        cleaned.append(record)
    return deduplicate_prs(cleaned)


def clean_calendar(raw_events):
    seen, cleaned = set(), []
    for index, ev in _rows(raw_events, "google_calendar"):
        title = _text(ev, "title", "google_calendar", index).strip()
        start = _text(ev, "start", "google_calendar", index).strip()
        end = _text(ev, "end", "google_calendar", index).strip()
        all_day = ev.get("all_day", len(start) == 10 and len(end) == 10)
        if not isinstance(all_day, bool):
            _fail("google_calendar", index, "all_day must be a boolean")
        record = {"title": title, "start": start, "end": end, **({"all_day": True} if all_day else {})}
        for field in ("original_start", "original_end"):
            if field in ev:
                record[field] = _text(ev, field, "google_calendar", index)
        key = (title, start, end, all_day)
        if key not in seen:
            seen.add(key)
            cleaned.append(record)
    return cleaned


def _normalize_timestamp(record, field, tz):
    value = record.get(field)
    if value is None or value == "":
        return None, "missing_timestamp"
    if not isinstance(value, str):
        return None, "invalid_timestamp"
    try:
        parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None, "naive_timestamp"
        normalized = parsed.astimezone(tz).isoformat()
        instant = parsed.astimezone(datetime.timezone.utc)
    except (ValueError, OverflowError):
        return None, "invalid_timestamp"
    if normalized != value:
        record.setdefault("original_" + field, value)
    record[field] = normalized
    return instant, None


def normalize_all(target_date, commits, prs, calendar, timezone_str=None):
    zone_name = timezone_str if timezone_str is not None else get_local_timezone_str()
    try:
        tz = resolve_timezone(zone_name, allow_legacy_offset=True)
        date = datetime.date.fromisoformat(target_date)
        if date.isoformat() != target_date:
            raise ValueError("Noncanonical date")
        day_start, day_end = day_bounds(date, tz)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ActivityNormalizationError("daily_model", None, "Valid timezone and canonical YYYY-MM-DD date required") from exc
    active_commits, active_prs, timed, context, unassigned = [], [], [], [], []

    def classify(source, record):
        timestamp, reason = _normalize_timestamp(record, "timestamp", tz)
        if not reason and not day_start <= timestamp < day_end:
            reason = "outside_target_day"
        if reason:
            unassigned.append({"source": source, "reason": reason, "activity": record})
            return False
        return True

    for commit in clean_commits(commits):
        if classify("git", commit):
            active_commits.append(commit)
    for reference in clean_prs(prs):
        common = {key: value for key, value in reference.items()
                  if key not in ("status", "timestamp", "actor", "events", "original_timestamp")}
        events = reference.get("events") or [{"action": reference.get("status", "opened"),
                  "timestamp": reference.get("timestamp"), **({"actor": reference["actor"]} if "actor" in reference else {})}]
        for event in events:
            event = dict(event)
            atom = {**common, "status": event["action"], "timestamp": event.get("timestamp"),
                    **({"actor": event["actor"]} if "actor" in event else {})}
            valid = classify("github", atom)
            event["timestamp"] = atom.get("timestamp")
            if "original_timestamp" in atom or "original_timestamp" in event:
                atom.setdefault("original_timestamp", event.get("original_timestamp"))
                event["original_timestamp"] = atom["original_timestamp"]
            atom["events"] = [event]
            if valid:
                active_prs.append(atom)

    for index, event in enumerate(clean_calendar(calendar)):
        if event.get("all_day"):
            try:
                start, end = (datetime.date.fromisoformat(event[field]) for field in ("start", "end"))
                if (start.isoformat() != event["start"] or end.isoformat() != event["end"] or end <= start):
                    raise ValueError("Invalid dates")
            except (ValueError, TypeError) as exc:
                raise ActivityNormalizationError("google_calendar", index, "All-day dates require canonical exclusive end after start") from exc
            relevant = start <= date < end
            destination = context
        else:
            start, start_reason = _normalize_timestamp(event, "start", tz)
            end, end_reason = _normalize_timestamp(event, "end", tz)
            if start_reason or end_reason or end <= start:
                _fail("google_calendar", index, "Timed Calendar events require aware timestamps and end after start")
            relevant = start < day_end and end > day_start
            destination = timed
        if relevant:
            destination.append(event)
        else:
            unassigned.append({"source": "google_calendar", "reason": "outside_target_day", "activity": event})

    from get_pr_activity import deduplicate_prs
    active_prs = deduplicate_prs(active_prs)
    active_commits.sort(key=lambda record: (timestamp_sort_key(record["timestamp"]), record["repository"], record["hash"]))
    for reference in active_prs:
        reference["events"].sort(key=lambda event: timestamp_sort_key(event["timestamp"]))
    active_prs.sort(key=lambda reference: (timestamp_sort_key(reference["events"][0]["timestamp"]),
                                         reference["repository"], reference["id"]))
    timed.sort(key=lambda event: (timestamp_sort_key(event["start"]), timestamp_sort_key(event["end"]), event["title"]))
    context.sort(key=lambda event: (event["start"], event["end"], event["title"]))
    unassigned.sort(key=lambda record: (timestamp_sort_key(record["activity"].get("timestamp", record["activity"].get("start"))),
                                       record["source"], str(record["activity"].get("hash", record["activity"].get("id", record["activity"].get("title", ""))))))
    return {"date": target_date, "timezone": zone_name, "calendar": timed, "calendar_context": context,
            "commits": active_commits, "pull_requests": active_prs, "unassigned_activity": unassigned}


def main():
    parser = argparse.ArgumentParser(description="Normalize daily activity data into compact model.")
    add_timezone_arguments(parser)
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--commits-file", type=str, default=None, help="Path to raw commits JSON file")
    parser.add_argument("--prs-file", type=str, default=None, help="Path to raw PRs JSON file")
    parser.add_argument("--calendar-file", type=str, default=None, help="Path to raw calendar JSON file")
    parser.add_argument("--raw-dir", type=str, default=None, help="Optional directory to save raw inputs")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output normalized JSON file")

    args = parser.parse_args()

    try:
        zone_name, tz = timezone_settings(args.config, args.timezone)
        target_date_str = args.date or datetime.datetime.now(tz).date().isoformat()
        datetime.date.fromisoformat(target_date_str)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    commits = []
    prs = []
    calendar = []
    collection_sources = {}

    def read_source(path, name):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if data.get("status") != "success" or not isinstance(data.get("items"), list):
                parser.error(f"{name} collection was not successful; use run_pipeline.py to review an incomplete draft")
            from collection_result import source_metadata
            collection_sources[name] = source_metadata(data)
            return data["items"]
        return data  # Existing list-only fixtures remain supported.

    try:
        if args.commits_file:
            commits = read_source(args.commits_file, "git")
        if args.prs_file:
            prs = read_source(args.prs_file, "pull_requests")
        if args.calendar_file:
            calendar = read_source(args.calendar_file, "calendar")
    except (OSError, ValueError):
        parser.error("Explicit source file could not be read as JSON; output was preserved")

    try:
        normalized = normalize_all(target_date_str, commits, prs, calendar, zone_name)
    except ActivityNormalizationError as exc:
        draft = {"date": target_date_str, "activity_format": "raw", "normalization": {"status": "blocked", "issues": exc.issues},
                 "activity": {"commits": commits, "pull_requests": prs, "calendar": calendar}}
        if args.output and args.output != "-":
            path = Path(args.output).parent / "drafts" / f"{target_date_str}.normalization.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
            print(f"NORMALIZATION BLOCKED: raw evidence draft: {path}", file=sys.stderr)
        else:
            print(json.dumps(draft, indent=2))
        return 2

    # If raw-dir requested, persist raw copies for audit
    if args.raw_dir:
        raw_path = Path(args.raw_dir)
        raw_path.mkdir(parents=True, exist_ok=True)
        (raw_path / f"raw_commits_{target_date_str}.json").write_text(json.dumps(commits, indent=2), encoding="utf-8")
        (raw_path / f"raw_prs_{target_date_str}.json").write_text(json.dumps(prs, indent=2), encoding="utf-8")
        (raw_path / f"raw_calendar_{target_date_str}.json").write_text(json.dumps(calendar, indent=2), encoding="utf-8")

    if collection_sources:
        normalized["collection_sources"] = collection_sources
    output_json = json.dumps(normalized, indent=2)

    if args.output and args.output != "-":
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
