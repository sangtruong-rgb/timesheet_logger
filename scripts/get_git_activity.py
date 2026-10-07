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
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from activity_settings import add_settings_arguments, day_bounds, identity_match, settings_from_args, timezone_settings
from collection_result import SourceUnavailable, collection_result, emit_result
from github_api import GitHubAPI, GitHubAPIError, check_gh_cli


def get_local_timezone() -> datetime.tzinfo:
    """Compatibility helper: return the configured named timezone, not host offset."""
    return timezone_settings()[1]


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

    if re.match(r"^https?://(?:www\.)?github\.com/[^/]+/[^/]+/(?:tree|blob)/", repo_str):
        raise ValueError("Branch/file URLs are unsupported; use owner/repo for the default branch or a local checkout")
    # Explicit HTTP(S) repository URL
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


def normalize_api_commits(
    raw_items: List[Dict[str, Any]],
    repo_name: str,
    target_date: datetime.date,
    author: Optional[str] = None,
    tz: Optional[datetime.tzinfo] = None
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
        if commit_dt.tzinfo is None:
            raise ValueError("GitHub author timestamps must include a timezone")
        local_dt = commit_dt.astimezone(tz)

        normalized.append({
            "repository": repo_name,
            "hash": sha,
            "short_hash": sha[:7] if len(sha) >= 7 else sha,
            "timestamp": local_dt.isoformat(),
            "author": author_name,
            "email": author_email,
            "message": first_line,
            "branch": None,
            "github_author": (item.get("author") or {}).get("login")
        })

    return filter_commits(normalized, target_date, author=author, tz=tz)


def fetch_github_api_commits(
    owner, repo, target_date, author=None, tz=None, use_git_credentials=False, max_commits=10000
):
    """Read all default-branch pages; filter author dates by one local day."""
    tz = tz or get_local_timezone()
    # API since/until uses commit chronology and can miss backdated author dates.
    # Scan a bounded complete default-branch history, then filter author dates.
    client = GitHubAPI(use_git_credentials)
    raw = []
    for item in client.items(f"repos/{owner}/{repo}/commits"):
        if len(raw) >= max_commits:
            raise ValueError("Remote history exceeds max-remote-commits; increase the explicit bound")
        raw.append(item)
    return normalize_api_commits(raw, f"{owner}/{repo}", target_date, author, tz)


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


def filter_commits(commits, target_date, author=None, tz=None):
    """Exact configured identities; an explicit '*' is diagnostic-only."""
    tz = tz or get_local_timezone()
    start, end = day_bounds(target_date, tz)
    filtered = []
    for commit in commits:
        basis = None
        if isinstance(author, dict):
            basis = identity_match(commit, author)
            if not basis:
                continue
        elif author and author not in ("*", "all"):
            if author.casefold() not in (commit.get("author", "").casefold(), commit.get("email", "").casefold()):
                continue
            basis = "exact_author_override"
        elif author in ("*", "all"):
            basis = "explicit_all_authors"
        timestamp = parse_iso_datetime(commit.get("timestamp", ""))
        if not timestamp or timestamp.tzinfo is None or not start <= timestamp < end:
            continue
        filtered.append({**commit, **({"identity_match": basis} if basis else {})})
    return sorted(filtered, key=lambda commit: commit["timestamp"])


def get_commits_for_repo(
    repo_path: str,
    target_date: datetime.date,
    author_filter=None, tz=None, max_commits=10000
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
                raise ValueError("Explicit repository is not a Git worktree")
        except Exception as exc:
            raise ValueError("Explicit repository could not be opened") from exc

    try:
        from activity_settings import github_repo
        repo_name = github_repo(str(resolved_path))
    except ValueError:
        repo_name = "local:" + str(resolved_path)
    local_tz = tz or get_local_timezone()

    # Determine author filter if not provided
    if author_filter is None:
        git_user = get_git_user(str(resolved_path))
        author_filter = {"github_users": [], "names": [git_user["name"]] if git_user["name"] else [],
                         "emails": [git_user["email"]] if git_user["email"] else []}
        if not any(author_filter.values()):
            raise SourceUnavailable("Configure an author identity before collecting local Git activity")

    # Delimiter for field splitting
    delimiter = "%x1f"
    format_spec = f"%H{delimiter}%an{delimiter}%ae{delimiter}%ad{delimiter}%s{delimiter}%D"

    # Fetch commits with strict ISO date format
    cmd = [
        "git", "-C", str(resolved_path),
        "log",
        "--all",
        f"--max-count={max_commits + 1}",
        "--date=iso-strict",
        f"--format={format_spec}"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
        if result.returncode != 0:
            raise ValueError("Git log failed; source collection is not complete")
        if len(result.stdout.splitlines()) > max_commits:
            raise ValueError("Local history exceeds max-local-commits; increase the explicit bound before collecting")
    except Exception as e:
        raise ValueError("Local Git query failed or exceeded its collection bound") from e

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

        # Parse commit timestamp and convert to local timezone
        commit_dt = parse_iso_datetime(date_str)
        if not commit_dt or commit_dt.tzinfo is None:
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
    return filter_commits(commits, target_date, author_filter, local_tz)


def main():
    parser = argparse.ArgumentParser(description="Collect personal local/remote Git activity.")
    parser.add_argument("--date", help="Local date YYYY-MM-DD")
    parser.add_argument("--repos", nargs="+", default=None, help="Local paths or GitHub repositories")
    parser.add_argument("--author", help="Exact author name/email override; '*' for diagnostic all-author collection")
    parser.add_argument("--envelope", action="store_true", help="Include source status (used by pipeline)")
    parser.add_argument("--max-local-commits", type=int, default=10000, help="History bound; exceeding it reports error, never partial success")
    parser.add_argument("--max-remote-commits", type=int, default=10000, help="Default-branch history bound, preserving author-date filtering")
    parser.add_argument("--output", "-o", help="Output JSON file")
    add_settings_arguments(parser)
    args = parser.parse_args()
    try:
        selected = settings_from_args(args)
        if min(args.max_local_commits, args.max_remote_commits) < 1:
            raise ValueError("Commit history bounds must be positive")
        date = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(selected["timezone"]).date()
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    try:
        identity = selected["identity"]
        if args.author is not None:
            author = args.author
            if not author.strip():
                raise SourceUnavailable("An empty author override is not a personal identity")
        else:
            if not any(identity.values()):
                current = get_git_user(".")
                identity = {"github_users": [], "names": [current["name"]] if current["name"] else [],
                            "emails": [current["email"]] if current["email"] else []}
            if not any(identity.values()):
                raise SourceUnavailable("Configure confirmed author identities; no Git identity is available")
            author = identity
        commits = []
        seen = set()
        for target in selected["repos"]:
            slug = parse_github_repo_slug(target)
            items = (fetch_github_api_commits(*slug, date, author, selected["timezone"], selected["use_git_credentials"], args.max_remote_commits)
                     if slug else get_commits_for_repo(target, date, author, selected["timezone"], args.max_local_commits))
            for commit in items:
                key = (commit["repository"], commit["hash"])
                if key not in seen:
                    seen.add(key)
                    commits.append(commit)
        commits.sort(key=lambda commit: (commit["timestamp"], commit["repository"], commit["hash"]))
        result = collection_result("git", "live", "success", commits)
    except SourceUnavailable as exc:
        result = collection_result("git", "live", "unavailable", reason=str(exc))
    except GitHubAPIError as exc:
        result = collection_result("git", "live", "error", reason=str(exc))
    except Exception as exc:
        result = collection_result("git", "live", "error", reason=f"Git collection failed ({type(exc).__name__})")
    if args.envelope or result["status"] != "success":
        return emit_result(result, args.output)
    output = json.dumps(result["items"], indent=2)
    try:
        if args.output and args.output != "-":
            from atomic_storage import directory_lock, atomic_write
            path = Path(args.output)
            with directory_lock(path.parent): atomic_write(path, output)
        else:
            print(output)
    except (OSError, ValueError) as exc:
        print(f"Git output blocked ({type(exc).__name__}); review output path.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
