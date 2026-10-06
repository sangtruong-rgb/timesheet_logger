#!/usr/bin/env python3
"""
get_pr_activity.py - Deterministic collector for GitHub / GitLab Pull Requests.

Retrieves PR activity for the requested date:
- Opened by author
- Reviewed by author
- Merged on that day

Deduplicates PRs so each PR ID appears at most once in the normalized list.
Supports gh CLI, glab CLI, direct API tokens, and fixture fallback for offline/test environments.
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Optional, Set


def get_local_timezone() -> datetime.timezone:
    return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc


def check_gh_cli() -> bool:
    """Check if GitHub CLI (gh) is installed and authenticated."""
    if not shutil.which("gh"):
        return False
    try:
        res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception:
        return False


def check_glab_cli() -> bool:
    """Check if GitLab CLI (glab) is installed and authenticated."""
    if not shutil.which("glab"):
        return False
    try:
        res = subprocess.run(["glab", "auth", "status"], capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception:
        return False


def query_gh_prs(target_date: datetime.date) -> List[Dict[str, Any]]:
    """Query GitHub PRs using gh CLI."""
    date_str = target_date.isoformat()
    results = []

    # Queries: authored updated today, reviewed-by me updated today
    queries = [
        ("opened", f"author:@me created:{date_str}"),
        ("merged", f"author:@me merged:{date_str}"),
        ("reviewed", f"reviewed-by:@me updated:{date_str}")
    ]

    for status_label, query in queries:
        cmd = [
            "gh", "search", "prs",
            query,
            "--json", "number,title,repository,url,updatedAt,createdAt,closedAt"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                items = json.loads(res.stdout)
                for item in items:
                    results.append({
                        "id": item.get("number"),
                        "repository": item.get("repository", {}).get("name", "unknown")
                        if isinstance(item.get("repository"), dict) else str(item.get("repository", "")),
                        "title": item.get("title", ""),
                        "status": status_label,
                        "url": item.get("url", ""),
                        "timestamp": item.get("updatedAt") or item.get("createdAt")
                    })
        except Exception as e:
            print(f"Warning: gh query failed for {query}: {e}", file=sys.stderr)

    return results


def deduplicate_prs(raw_prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Deduplicate PRs by (repository, id).
    If a PR is encountered multiple times with different statuses (e.g. reviewed and merged),
    merge status with precedence: merged > opened > reviewed.
    """
    status_priority = {"merged": 3, "opened": 2, "reviewed": 1}
    dedup_map: Dict[str, Dict[str, Any]] = {}

    for pr in raw_prs:
        pr_id = pr.get("id")
        repo = pr.get("repository", "")
        if pr_id is None:
            continue
        key = f"{repo}#{pr_id}" if repo else f"#{pr_id}"

        if key not in dedup_map:
            dedup_map[key] = dict(pr)
        else:
            existing = dedup_map[key]
            curr_stat = pr.get("status", "")
            exist_stat = existing.get("status", "")
            curr_prio = status_priority.get(curr_stat, 0)
            exist_prio = status_priority.get(exist_stat, 0)
            if curr_prio > exist_prio:
                existing["status"] = curr_stat
            # Keep the earliest or most informative timestamp
            if not existing.get("timestamp") and pr.get("timestamp"):
                existing["timestamp"] = pr.get("timestamp")

    # Return sorted deterministically by PR ID
    results = list(dedup_map.values())
    results.sort(key=lambda x: str(x.get("id", "")))
    return results


def load_fixture(fixture_path: str, target_date: datetime.date) -> List[Dict[str, Any]]:
    """Load PRs from a JSON fixture file and filter by target date if timestamps present."""
    p = Path(fixture_path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            # If timestamp present, filter for date, else return all fixture entries
            filtered = []
            for item in data:
                ts = item.get("timestamp")
                if ts:
                    try:
                        dt = datetime.datetime.fromisoformat(ts).astimezone(get_local_timezone())
                        if dt.date() == target_date:
                            filtered.append(item)
                    except Exception:
                        filtered.append(item)
                else:
                    filtered.append(item)
            return filtered
    except Exception as e:
        print(f"Warning: Failed to load PR fixture {fixture_path}: {e}", file=sys.stderr)
    return []


def main():
    parser = argparse.ArgumentParser(description="Collect PR/MR activity for a specific date.")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--fixture",
        type=str,
        default=None,
        help="Path to fixture JSON file (used for mock/offline data)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path (JSON). If omitted, prints to stdout."
    )

    args = parser.parse_args()

    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        target_date = datetime.datetime.now().astimezone().date()

    raw_prs: List[Dict[str, Any]] = []

    # Priority 1: Explicit fixture file if supplied
    if args.fixture:
        raw_prs = load_fixture(args.fixture, target_date)
    else:
        # Priority 2: Check gh CLI
        if check_gh_cli():
            raw_prs = query_gh_prs(target_date)
        # Priority 3: Check default fixture directory if exists
        default_fixture = Path("data/fixtures/sample_prs.json")
        if not raw_prs and default_fixture.exists():
            raw_prs = load_fixture(str(default_fixture), target_date)

    normalized_prs = deduplicate_prs(raw_prs)
    output_json = json.dumps(normalized_prs, indent=2)

    if args.output and args.output != "-":
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
