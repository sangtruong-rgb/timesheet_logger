#!/usr/bin/env python3
"""
get_git_activity.py - Deterministic collector for Git commits authored on a specific date.

Captures:
- repository
- commit hash
- timestamp (ISO 8601 with timezone)
- author / email
- commit message
- branch name (if resolvable)
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional


def get_local_timezone() -> datetime.timezone:
    """Return local timezone from system clock."""
    return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc


def get_git_user(repo_path: str) -> Dict[str, str]:
    """Retrieve git user.name and user.email from repository configuration or global config."""
    name, email = "", ""
    try:
        res_name = subprocess.run(
            ["git", "-C", repo_path, "config", "user.name"],
            capture_output=True, text=True, check=False
        )
        name = res_name.stdout.strip()
    except Exception:
        pass

    try:
        res_email = subprocess.run(
            ["git", "-C", repo_path, "config", "user.email"],
            capture_output=True, text=True, check=False
        )
        email = res_email.stdout.strip()
    except Exception:
        pass

    return {"name": name, "email": email}


def parse_iso_datetime(date_str: str) -> Optional[datetime.datetime]:
    """Parse ISO 8601 datetime string, supporting python 3.9+ fromisoformat."""
    if not date_str:
        return None
    try:
        # Handles 2026-10-06T10:24:00+07:00
        return datetime.datetime.fromisoformat(date_str)
    except Exception:
        return None


def filter_commits(
    commits: List[Dict[str, Any]],
    target_date: datetime.date,
    author: Optional[str] = None,
    tz: Optional[datetime.timezone] = None
) -> List[Dict[str, Any]]:
    """Filter commits by author and target date in the specified timezone."""
    if tz is None:
        tz = get_local_timezone()
    filtered = []
    for c in commits:
        if author:
            af_lower = author.lower()
            name = c.get("author", "").lower()
            email = c.get("email", "").lower()
            if af_lower not in name and af_lower not in email:
                continue
        dt = parse_iso_datetime(c.get("timestamp", ""))
        if not dt:
            continue
        if dt.astimezone(tz).date() != target_date:
            continue
        filtered.append(c)
    filtered.sort(key=lambda x: x["timestamp"])
    return filtered


def get_commits_for_repo(
    repo_path: str,
    target_date: datetime.date,
    author_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Query git log in repo_path and return normalized commits for target_date in local timezone."""
    resolved_path = Path(repo_path).resolve()
    if not (resolved_path / ".git").exists() and not (resolved_path / "HEAD").exists():
        # Check if git recognizes it as a work tree
        try:
            check = subprocess.run(
                ["git", "-C", str(resolved_path), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, check=False
            )
            if check.returncode != 0:
                return []
        except Exception:
            return []

    repo_name = resolved_path.name
    local_tz = get_local_timezone()

    # Determine author filter if not provided
    if not author_filter:
        git_user = get_git_user(str(resolved_path))
        author_filter = git_user.get("name") or git_user.get("email")

    # Delimiter for field splitting
    delimiter = "%x1f"
    format_spec = f"%H{delimiter}%an{delimiter}%ae{delimiter}%ad{delimiter}%s{delimiter}%D"

    # Fetch commits with strict ISO date format
    cmd = [
        "git", "-C", str(resolved_path),
        "log",
        "--all",
        "--date=iso-strict",
        f"--format={format_spec}"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return []
    except Exception as e:
        print(f"Error querying git in {repo_path}: {e}", file=sys.stderr)
        return []

    commits: List[Dict[str, Any]] = []
    lines = result.stdout.strip().split("\n")

    for line in lines:
        if not line:
            continue
        parts = line.split("\x1f")
        if len(parts) < 5:
            continue

        commit_hash = parts[0].strip()
        author_name = parts[1].strip()
        author_email = parts[2].strip()
        date_str = parts[3].strip()
        subject = parts[4].strip()
        ref_decorations = parts[5].strip() if len(parts) > 5 else ""

        # Filter by author if author_filter is given
        if author_filter:
            af_lower = author_filter.lower()
            if af_lower not in author_name.lower() and af_lower not in author_email.lower():
                continue

        # Parse commit timestamp and convert to local timezone
        commit_dt = parse_iso_datetime(date_str)
        if not commit_dt:
            continue

        local_commit_dt = commit_dt.astimezone(local_tz)
        if local_commit_dt.date() != target_date:
            continue

        # Extract primary branch if available from ref decorations
        branch = None
        if ref_decorations:
            # ref_decorations looks like: "HEAD -> feat/foo, origin/main, main"
            refs = [r.strip() for r in ref_decorations.split(",")]
            for ref in refs:
                if "->" in ref:
                    branch = ref.split("->")[-1].strip()
                    break
                elif not ref.startswith("tag:"):
                    branch = ref
                    break

        commits.append({
            "repository": repo_name,
            "hash": commit_hash,
            "short_hash": commit_hash[:7],
            "timestamp": local_commit_dt.isoformat(),
            "author": author_name,
            "email": author_email,
            "message": subject,
            "branch": branch
        })

    # Sort deterministically by timestamp ascending
    commits.sort(key=lambda c: c["timestamp"])
    return commits


def main():
    parser = argparse.ArgumentParser(description="Collect Git commits authored on a specific date.")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date in YYYY-MM-DD format (default: today in local timezone)"
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=["."],
        help="List of repository paths to scan (default: current directory)"
    )
    parser.add_argument(
        "--author",
        type=str,
        default=None,
        help="Author name or email substring to filter commits (default: git config user.name/email)"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path (JSON). If omitted, prints to stdout."
    )

    args = parser.parse_args()

    # Determine target date
    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        target_date = datetime.datetime.now().astimezone().date()

    all_commits: List[Dict[str, Any]] = []
    seen_hashes = set()

    for repo_path in args.repos:
        repo_commits = get_commits_for_repo(repo_path, target_date, args.author)
        for commit in repo_commits:
            # Deduplicate by commit hash across repo scans
            if commit["hash"] not in seen_hashes:
                seen_hashes.add(commit["hash"])
                all_commits.append(commit)

    # Sort globally by timestamp
    all_commits.sort(key=lambda c: c["timestamp"])

    output_json = json.dumps(all_commits, indent=2)

    if args.output and args.output != "-":
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
