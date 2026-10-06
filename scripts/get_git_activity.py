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
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def get_local_timezone() -> datetime.timezone:
    """Return local timezone from system clock."""
    return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc


def get_git_user(repo_path: Optional[str] = None) -> Dict[str, str]:
    """Retrieve git user.name and user.email from repository configuration or global config."""
    name, email = "", ""
    if repo_path and Path(repo_path).exists() and Path(repo_path).is_dir():
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

    # Fallback to global git config
    if not name:
        try:
            res_name = subprocess.run(
                ["git", "config", "user.name"],
                capture_output=True, text=True, check=False
            )
            name = res_name.stdout.strip()
        except Exception:
            pass
    if not email:
        try:
            res_email = subprocess.run(
                ["git", "config", "user.email"],
                capture_output=True, text=True, check=False
            )
            email = res_email.stdout.strip()
        except Exception:
            pass

    return {"name": name, "email": email}


def parse_github_repo_slug(repo_str: str) -> Optional[Tuple[str, str]]:
    """
    Parse a GitHub repository target into (owner, repo).
    Supports:
    - https://github.com/owner/repo[.git]
    - http://github.com/owner/repo[.git]
    - git@github.com:owner/repo.git
    - owner/repo (when not an existing local directory)
    Returns None if the target is a local path or not a valid GitHub identifier.
    """
    repo_str = repo_str.strip()
    if not repo_str:
        return None

    # Explicit HTTP(S) URL (supports optional branch or subpath suffix)
    http_match = re.match(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+?)(?:\.git)?(?:/.*)?$", repo_str)
    if http_match:
        return http_match.group(1), http_match.group(2)

    # Explicit SSH URL
    ssh_match = re.match(r"^git@github\.com:([^/]+)/([^/#?]+?)(?:\.git)?(?:/.*)?$", repo_str)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    # Local path indicators
    if repo_str.startswith((".", "/", "~", "\\")):
        return None
    if Path(repo_str).exists():
        return None

    # Slug format: owner/repo
    slug_match = re.match(r"^([a-zA-Z0-9][-a-zA-Z0-9_]*)/([a-zA-Z0-9_.-]+)$", repo_str)
    if slug_match:
        return slug_match.group(1), slug_match.group(2)

    return None


def check_gh_cli() -> bool:
    """Check if GitHub CLI (gh) is installed and authenticated."""
    if not shutil.which("gh"):
        return False
    try:
        res = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, check=False)
        return res.returncode == 0
    except Exception:
        return False


def normalize_api_commits(
    raw_items: List[Dict[str, Any]],
    repo_name: str,
    target_date: datetime.date,
    author: Optional[str] = None,
    tz: Optional[datetime.timezone] = None
) -> List[Dict[str, Any]]:
    """
    Normalize GitHub REST API commit objects and filter by date and author in timezone tz.
    """
    if tz is None:
        tz = get_local_timezone()

    normalized: List[Dict[str, Any]] = []
    for item in raw_items:
        sha = item.get("sha", "")
        commit_info = item.get("commit", {})
        author_info = commit_info.get("author", {})
        author_name = author_info.get("name", "")
        author_email = author_info.get("email", "")
        date_str = author_info.get("date", "")
        message = commit_info.get("message", "")
        first_line = message.split("\n")[0].strip() if message else ""

        commit_dt = parse_iso_datetime(date_str)
        if not commit_dt:
            continue
        local_dt = commit_dt.astimezone(tz)

        normalized.append({
            "repository": repo_name,
            "hash": sha,
            "short_hash": sha[:7] if len(sha) >= 7 else sha,
            "timestamp": local_dt.isoformat(),
            "author": author_name,
            "email": author_email,
            "message": first_line,
            "branch": None
        })

    return filter_commits(normalized, target_date, author=author, tz=tz)


def fetch_github_api_commits(
    owner: str,
    repo: str,
    target_date: datetime.date,
    author: Optional[str] = None,
    tz: Optional[datetime.timezone] = None
) -> List[Dict[str, Any]]:
    """
    Fetch commits for a remote GitHub repository using GitHub REST API.
    Uses gh CLI if available; falls back to direct HTTPS requests with optional GITHUB_TOKEN.
    """
    if tz is None:
        tz = get_local_timezone()

    start_dt = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=tz)
    end_dt = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=tz)
    since_utc = start_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    until_utc = end_dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw_items: List[Dict[str, Any]] = []

    # Priority 1: gh CLI if installed and authenticated
    if check_gh_cli():
        endpoint = f"repos/{owner}/{repo}/commits?since={since_utc}&until={until_utc}&per_page=100"
        try:
            res = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, check=False)
            if res.returncode == 0:
                parsed = json.loads(res.stdout) if res.stdout.strip() else []
                if isinstance(parsed, list):
                    return normalize_api_commits(parsed, repo, target_date, author=author, tz=tz)
        except Exception as e:
            print(f"Warning: gh api failed for {owner}/{repo}: {e}", file=sys.stderr)

    # Priority 2: Direct HTTPS API fallback via urllib
    url = f"https://api.github.com/repos/{owner}/{repo}/commits?since={since_utc}&until={until_utc}&per_page=100"
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "personal-timesheet-logger")

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            parsed = json.loads(resp.read().decode("utf-8"))
            if isinstance(parsed, list):
                raw_items = parsed
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"Warning: GitHub repository {owner}/{repo} not found or requires authentication (HTTP 404).", file=sys.stderr)
        elif e.code == 403:
            print(f"Warning: GitHub API rate limit reached or access forbidden for {owner}/{repo} (HTTP 403). Set GITHUB_TOKEN to increase limits.", file=sys.stderr)
        else:
            print(f"Warning: GitHub API HTTP error {e.code} for {owner}/{repo}: {e.reason}", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Error querying GitHub API for {owner}/{repo}: {e}", file=sys.stderr)

    return normalize_api_commits(raw_items, repo, target_date, author=author, tz=tz)


def parse_iso_datetime(date_str: str) -> Optional[datetime.datetime]:
    """Parse ISO 8601 datetime string, supporting python 3.9+ and 'Z' suffix."""
    if not date_str:
        return None
    try:
        # Handles 2026-10-06T10:24:00+07:00 and 2026-10-06T03:00:00Z
        cleaned = date_str.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(cleaned)
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
        if author and author not in ("*", "all", ""):
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
        if author_filter and author_filter not in ("*", "all", ""):
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
        help="List of repository paths or GitHub targets (owner/repo or URL) to scan (default: current directory)"
    )
    parser.add_argument(
        "--author",
        type=str,
        default=None,
        help="Author name or email substring to filter commits (default: git config user.name/email; '*' or 'all' for all authors)"
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

    local_tz = get_local_timezone()
    author_filter = args.author
    if author_filter is None:
        git_user = get_git_user(".")
        author_filter = git_user.get("name") or git_user.get("email")

    all_commits: List[Dict[str, Any]] = []
    seen_hashes = set()

    for repo_target in args.repos:
        gh_slug = parse_github_repo_slug(repo_target)
        if gh_slug:
            owner, repo = gh_slug
            repo_commits = fetch_github_api_commits(
                owner=owner,
                repo=repo,
                target_date=target_date,
                author=author_filter,
                tz=local_tz
            )
        else:
            repo_commits = get_commits_for_repo(repo_target, target_date, author_filter)

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
