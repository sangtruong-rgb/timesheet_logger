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


def get_local_timezone_str() -> str:
    now = datetime.datetime.now().astimezone()
    tz = now.strftime("%z")
    return f"{tz[:3]}:{tz[3:]}" if len(tz) == 5 else tz


def clean_commits(raw_commits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_hashes = set()
    cleaned = []
    for c in raw_commits:
        h = c.get("hash") or c.get("short_hash")
        if not h or h in seen_hashes:
            continue
        seen_hashes.add(h)
        cleaned.append({
            "repository": str(c.get("repository", "default")),
            "hash": str(c.get("hash", h)),
            "short_hash": str(c.get("short_hash", h[:7] if len(h) >= 7 else h)),
            "timestamp": str(c.get("timestamp", "")),
            "author": str(c.get("author", "")),
            "message": str(c.get("message", "")).strip(),
            "branch": c.get("branch")
        })
    cleaned.sort(key=lambda x: x.get("timestamp", ""))
    return cleaned


def clean_prs(raw_prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    status_priority = {"merged": 3, "opened": 2, "reviewed": 1}
    dedup_map: Dict[str, Dict[str, Any]] = {}

    for p in raw_prs:
        pid = p.get("id")
        if pid is None:
            continue
        repo = p.get("repository", "")
        key = f"{repo}#{pid}" if repo else f"#{pid}"

        if key not in dedup_map:
            dedup_map[key] = {
                "id": pid,
                "repository": str(repo),
                "title": str(p.get("title", "")).strip(),
                "status": str(p.get("status", "opened")),
                "url": str(p.get("url", "")),
                "timestamp": p.get("timestamp")
            }
        else:
            curr_stat = p.get("status", "")
            exist_stat = dedup_map[key].get("status", "")
            if status_priority.get(curr_stat, 0) > status_priority.get(exist_stat, 0):
                dedup_map[key]["status"] = curr_stat
            if not dedup_map[key].get("timestamp") and p.get("timestamp"):
                dedup_map[key]["timestamp"] = p.get("timestamp")

    cleaned = list(dedup_map.values())
    cleaned.sort(key=lambda x: str(x["id"]))
    return cleaned


def clean_calendar(raw_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen_events = set()
    cleaned = []
    for ev in raw_events:
        title = str(ev.get("title", "")).strip()
        start = str(ev.get("start", "")).strip()
        end = str(ev.get("end", "")).strip()
        key = (title, start, end)
        if key in seen_events:
            continue
        seen_events.add(key)
        cleaned.append({
            "title": title,
            "start": start,
            "end": end
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
    return {
        "date": target_date,
        "timezone": timezone_str or get_local_timezone_str(),
        "calendar": clean_calendar(calendar),
        "commits": clean_commits(commits),
        "pull_requests": clean_prs(prs)
    }


def main():
    parser = argparse.ArgumentParser(description="Normalize daily activity data into compact model.")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--commits-file", type=str, default=None, help="Path to raw commits JSON file")
    parser.add_argument("--prs-file", type=str, default=None, help="Path to raw PRs JSON file")
    parser.add_argument("--calendar-file", type=str, default=None, help="Path to raw calendar JSON file")
    parser.add_argument("--raw-dir", type=str, default=None, help="Optional directory to save raw inputs")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output normalized JSON file")

    args = parser.parse_args()

    if args.date:
        target_date_str = args.date
    else:
        target_date_str = datetime.datetime.now().astimezone().date().isoformat()

    commits = []
    prs = []
    calendar = []

    if args.commits_file and Path(args.commits_file).exists():
        commits = json.loads(Path(args.commits_file).read_text(encoding="utf-8"))
    if args.prs_file and Path(args.prs_file).exists():
        prs = json.loads(Path(args.prs_file).read_text(encoding="utf-8"))
    if args.calendar_file and Path(args.calendar_file).exists():
        calendar = json.loads(Path(args.calendar_file).read_text(encoding="utf-8"))

    # If raw-dir requested, persist raw copies for audit
    if args.raw_dir:
        raw_path = Path(args.raw_dir)
        raw_path.mkdir(parents=True, exist_ok=True)
        (raw_path / f"raw_commits_{target_date_str}.json").write_text(json.dumps(commits, indent=2), encoding="utf-8")
        (raw_path / f"raw_prs_{target_date_str}.json").write_text(json.dumps(prs, indent=2), encoding="utf-8")
        (raw_path / f"raw_calendar_{target_date_str}.json").write_text(json.dumps(calendar, indent=2), encoding="utf-8")

    normalized = normalize_all(target_date_str, commits, prs, calendar)
    output_json = json.dumps(normalized, indent=2)

    if args.output and args.output != "-":
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
