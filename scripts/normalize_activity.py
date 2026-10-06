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
from typing import List, Dict, Any, Optional
from activity_settings import add_timezone_arguments, timezone_settings, resolve_timezone


def get_local_timezone_str() -> str:
    """Compatibility helper returning the profile's authoritative named zone."""
    return timezone_settings()[0]


def clean_commits(raw_commits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_hashes = set()
    cleaned = []
    for c in raw_commits:
        h = c.get("hash") or c.get("short_hash")
        key = (c.get("repository", "default"), h)
        if not h or key in seen_hashes:
            continue
        seen_hashes.add(key)
        cleaned.append({
            "repository": str(c.get("repository", "default")),
            "hash": str(c.get("hash", h)),
            "short_hash": str(c.get("short_hash", h[:7] if len(h) >= 7 else h)),
            "timestamp": str(c.get("timestamp", "")),
            "author": str(c.get("author", "")),
            "message": str(c.get("message", "")).strip(),
            "branch": c.get("branch"),
            **({"github_author": c["github_author"]} if c.get("github_author") else {}),
            **({"identity_match": c["identity_match"]} if c.get("identity_match") else {})
        })
    cleaned.sort(key=lambda x: x.get("timestamp", ""))
    return cleaned


def clean_prs(raw_prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from get_pr_activity import deduplicate_prs
    fields = ("id", "repository", "title", "status", "url", "timestamp", "actor", "events")
    return [{key: pr[key] for key in fields if key in pr}
            for pr in deduplicate_prs(raw_prs)]


def clean_calendar(raw_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_events = set()
    cleaned = []
    for ev in raw_events:
        title = str(ev.get("title", "")).strip()
        start = str(ev.get("start", "")).strip()
        end = str(ev.get("end", "")).strip()
        all_day = ev.get("all_day", len(start) == 10 and len(end) == 10)
        key = (title, start, end, all_day)
        if key in seen_events:
            continue
        seen_events.add(key)
        cleaned.append({
            "title": title,
            "start": start,
            "end": end,
            **({"all_day": True} if all_day else {})
        })
    cleaned.sort(key=lambda x: x.get("start", ""))
    return cleaned


def normalize_all(
    target_date: str,
    commits: List[Dict[str, Any]],
    prs: List[Dict[str, Any]],
    calendar: List[Dict[str, Any]],
    timezone_str: Optional[str] = None
) -> Dict[str, Any]:
    zone_name = timezone_str if timezone_str is not None else get_local_timezone_str()
    resolve_timezone(zone_name, allow_legacy_offset=True)
    events = clean_calendar(calendar)
    return {
        "date": target_date,
        "timezone": zone_name,
        "calendar": [ev for ev in events if not ev.get("all_day")],
        "calendar_context": [ev for ev in events if ev.get("all_day")],
        "commits": clean_commits(commits),
        "pull_requests": clean_prs(prs)
    }


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

    if args.commits_file and Path(args.commits_file).exists():
        commits = read_source(args.commits_file, "git")
    if args.prs_file and Path(args.prs_file).exists():
        prs = read_source(args.prs_file, "pull_requests")
    if args.calendar_file and Path(args.calendar_file).exists():
        calendar = read_source(args.calendar_file, "calendar")

    # If raw-dir requested, persist raw copies for audit
    if args.raw_dir:
        raw_path = Path(args.raw_dir)
        raw_path.mkdir(parents=True, exist_ok=True)
        (raw_path / f"raw_commits_{target_date_str}.json").write_text(json.dumps(commits, indent=2), encoding="utf-8")
        (raw_path / f"raw_prs_{target_date_str}.json").write_text(json.dumps(prs, indent=2), encoding="utf-8")
        (raw_path / f"raw_calendar_{target_date_str}.json").write_text(json.dumps(calendar, indent=2), encoding="utf-8")

    normalized = normalize_all(target_date_str, commits, prs, calendar, zone_name)
    if collection_sources:
        normalized["collection_sources"] = collection_sources
    output_json = json.dumps(normalized, indent=2)

    if args.output and args.output != "-":
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
