#!/usr/bin/env python3
"""
get_pr_activity.py - Deterministic collector for GitHub / GitLab Pull Requests.

Retrieves PR activity for the requested date:
- Opened by author
- Reviewed by author
- Merged on that day

Deduplicates PRs so each PR ID appears at most once in the normalized list.
Uses authenticated gh CLI, or an explicitly selected fixture for testing.
Outputs a source-status envelope; never substitutes fixtures for live results.
"""

import argparse
import datetime
import json
import shutil
import subprocess
import sys
from typing import List, Dict, Any

from collection_result import collection_result, emit_result, load_fixture_records


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
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            raise RuntimeError(f"GitHub {status_label} query failed (exit {res.returncode})")
        items = json.loads(res.stdout)
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError(f"Invalid GitHub {status_label} response")
        for item in items:
            if item.get("number") is None or not isinstance(item.get("title"), str):
                raise ValueError(f"Invalid GitHub {status_label} PR fields")
            results.append({
                "id": item.get("number"),
                "repository": item.get("repository", {}).get("name", "unknown")
                if isinstance(item.get("repository"), dict) else str(item.get("repository", "")),
                "title": item.get("title", ""),
                "status": status_label,
                "url": item.get("url", ""),
                "timestamp": item.get("updatedAt") or item.get("createdAt")
            })

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
    data = load_fixture_records(fixture_path)
    filtered = []
    for item in data:
        if item.get("id") is None or not isinstance(item.get("title"), str):
            raise ValueError("PR fixture records require id and title")
        ts = item.get("timestamp")
        if ts:
            try:
                dt = datetime.datetime.fromisoformat(ts).astimezone(get_local_timezone())
                if dt.date() == target_date:
                    filtered.append(item)
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid PR fixture timestamp") from exc
        else:
            filtered.append(item)
    return filtered


def collect_pr_activity(target_date, fixture_path=None):
    mode = "fixture" if fixture_path is not None else "live"
    if fixture_path is None and not check_gh_cli():
        return collection_result("github", mode, "unavailable", reason=
                                 "Install gh and authenticate with gh auth login")
    try:
        raw = load_fixture(fixture_path, target_date) if fixture_path is not None else query_gh_prs(target_date)
        return collection_result("github", mode, "success", deduplicate_prs(raw))
    except Exception as exc:
        return collection_result("github", mode, "error", reason=
                                 f"PR collection failed ({type(exc).__name__})")


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

    return emit_result(collect_pr_activity(target_date, args.fixture), args.output)


if __name__ == "__main__":
    sys.exit(main())
