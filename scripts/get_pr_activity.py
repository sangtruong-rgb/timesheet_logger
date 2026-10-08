#!/usr/bin/env python3
"""Collect scoped GitHub PR references with actual, timestamped action events."""

import argparse
import datetime
from typing import List, Dict, Any

from activity_settings import (add_settings_arguments, day_bounds, github_repo,
                               parse_timestamp, settings_from_args, timezone_settings, timestamp_sort_key)
from collection_result import (SourceUnavailable, collection_result, emit_result,
                               load_fixture_records)
from github_api import GitHubAPI, GitHubAPIError


def get_local_timezone():
    return timezone_settings()[1]


def deduplicate_prs(raw_prs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One qualified PR reference, while retaining each distinct action event."""
    priority = {"merged": 3, "opened": 2, "reviewed": 1}
    references = {}
    for pr in raw_prs:
        if pr.get("id") is None:
            continue
        key = (pr.get("repository", ""), pr["id"])
        if key not in references:
            references[key] = {**pr, "events": []}
        record = references[key]
        if pr.get('merge_commit_sha'):
            if record.get('merge_commit_sha') not in (None, pr['merge_commit_sha']):
                raise ValueError('Conflicting PR merge commit identities')
            record['merge_commit_sha'] = pr['merge_commit_sha']
        if priority.get(pr.get("status"), 0) > priority.get(record.get("status"), 0):
            for field in ("status", "timestamp", "actor"):
                record[field] = pr.get(field)
        events = pr.get("events")
        if events is None:
            events = ([{"action": pr.get("status", "opened"), "timestamp": pr["timestamp"],
                        **({"actor": pr["actor"]} if pr.get("actor") else {})}]
                      if pr.get("timestamp") else [])
        for event in events:
            if event not in record["events"]:
                record["events"].append(dict(event))
    for record in references.values():
        record["events"].sort(key=lambda event: (timestamp_sort_key(event.get("timestamp")), event["action"], str(event.get("id", ""))))
    return sorted(references.values(), key=lambda pr: (pr.get("repository", ""), str(pr["id"])))


def query_gh_prs(target_date, repos=None, users=None, tz=None, client=None):
    """Use gh-backed REST endpoints, not lossy/quoted search qualifiers."""
    client = client or GitHubAPI()
    tz = tz or get_local_timezone()
    selected = list(dict.fromkeys(github_repo(repo) for repo in (repos or ["."])))
    if not users:
        current = client.get("user")
        users = [current["login"]]
    ours = {user.casefold() for user in users}
    start, end = day_bounds(target_date, tz)
    results = []

    def is_today(value):
        return start <= parse_timestamp(value) < end

    for repository in selected:
        endpoint = f"repos/{repository}/pulls"
        stop = False
        for page in client.pages(endpoint, state="all", sort="updated", direction="desc"):
            for pr in page:
                if (not isinstance(pr.get("number"), int) or not isinstance(pr.get("title"), str)
                        or not isinstance(pr.get("user"), dict) or not pr["user"].get("login")
                        or not isinstance(pr.get("html_url"), str)):
                    raise ValueError("Invalid GitHub PR fields")
                if parse_timestamp(pr["updated_at"]) < start:
                    stop = True
                    break
                author = pr["user"]["login"]
                number = pr["number"]
                reference = {"id": number, "repository": repository, "title": pr["title"],
                             "url": pr["html_url"]}
                events = []
                merge_commit_sha = None
                if author.casefold() in ours and is_today(pr["created_at"]):
                    events.append({"action": "opened", "timestamp": parse_timestamp(pr["created_at"]).astimezone(tz).isoformat(),
                                   "actor": author})
                reviews = list(client.items(f"{endpoint}/{number}/reviews"))
                previously_reviewed = False
                for review in reviews:
                    reviewer = (review.get("user") or {}).get("login")
                    if not reviewer:
                        raise ValueError("Invalid GitHub review author")
                    if reviewer.casefold() not in ours:
                        continue
                    submitted = review.get("submitted_at")
                    if not submitted and review.get("state") == "PENDING":
                        continue
                    if not isinstance(review.get("id"), int):
                        raise ValueError("Invalid GitHub review ID")
                    review_time = parse_timestamp(submitted)
                    merge_time = parse_timestamp(pr["merged_at"]) if pr.get("merged_at") else None
                    previously_reviewed = previously_reviewed or bool(merge_time and review_time <= merge_time)
                    if start <= review_time < end:
                        events.append({"action": "reviewed", "timestamp": review_time.astimezone(tz).isoformat(),
                                       "actor": reviewer, "id": review["id"]})
                if pr.get("merged_at") and is_today(pr["merged_at"]):
                    detail = client.get(f"{endpoint}/{number}")
                    merger = (detail.get("merged_by") or {}).get("login")
                    if author.casefold() in ours or previously_reviewed or (merger and merger.casefold() in ours):
                        merge_commit_sha = detail.get('merge_commit_sha')
                        events.append({"action": "merged", "timestamp": parse_timestamp(pr["merged_at"]).astimezone(tz).isoformat(),
                                       "actor": merger})
                for event in events:
                    results.append({**reference, **({'merge_commit_sha': merge_commit_sha} if merge_commit_sha else {}),
                                    "status": event["action"], "timestamp": event["timestamp"],
                                    "actor": event.get("actor"), "events": [event]})
            if stop:
                break
    return results


def load_fixture(fixture_path, target_date, tz=None):
    tz = tz or get_local_timezone()
    start, end = day_bounds(target_date, tz)
    filtered = []
    for item in load_fixture_records(fixture_path):
        if item.get("id") is None or not isinstance(item.get("title"), str):
            raise ValueError("PR fixture records require id and title")
        if item.get("timestamp") and not start <= parse_timestamp(item["timestamp"]) < end:
            continue
        filtered.append(item)
    return filtered


def collect_pr_activity(target_date, fixture_path=None, repos=None, users=None, tz=None, use_git_credentials=False):
    mode = "fixture" if fixture_path is not None else "live"
    try:
        raw = (load_fixture(fixture_path, target_date, tz) if fixture_path is not None
               else query_gh_prs(target_date, repos, users, tz, GitHubAPI(use_git_credentials)))
        return collection_result("github", mode, "success", deduplicate_prs(raw))
    except SourceUnavailable as exc:
        return collection_result("github", mode, "unavailable", reason=str(exc))
    except GitHubAPIError as exc:
        return collection_result("github", mode, "error", reason=str(exc))
    except Exception as exc:
        return collection_result("github", mode, "error", reason=f"PR collection failed ({type(exc).__name__})")


def main():
    parser = argparse.ArgumentParser(description="Collect scoped, multi-account GitHub PR action events.")
    parser.add_argument("--date", help="Local date YYYY-MM-DD")
    parser.add_argument("--repos", nargs="+", default=None, help="GitHub repos or local repos with GitHub origin")
    parser.add_argument("--fixture", help="Explicit offline/demo PR fixture")
    parser.add_argument("--output", "-o", help="Output JSON envelope")
    add_settings_arguments(parser)
    args = parser.parse_args()
    try:
        selected = settings_from_args(args)
        date = datetime.date.fromisoformat(args.date) if args.date else datetime.datetime.now(selected["timezone"]).date()
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    return emit_result(collect_pr_activity(date, args.fixture, selected["repos"],
                                          selected["identity"]["github_users"], selected["timezone"],
                                          selected["use_git_credentials"]), args.output)


if __name__ == "__main__":
    raise SystemExit(main())
