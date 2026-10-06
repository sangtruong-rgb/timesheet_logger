#!/usr/bin/env python3
"""
test_git_activity.py - Unit tests for Git activity parsing and filtering.
"""

import datetime
import unittest
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from get_git_activity import (
    parse_iso_datetime,
    filter_commits,
    parse_github_repo_slug,
    normalize_api_commits
)
from normalize_activity import clean_commits


class TestGitActivity(unittest.TestCase):
    def setUp(self):
        self.tz = datetime.timezone(datetime.timedelta(hours=7))

    def test_parse_iso_datetime(self):
        dt = parse_iso_datetime("2026-10-06T10:24:00+07:00")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 10)
        self.assertEqual(dt.day, 6)
        self.assertEqual(dt.hour, 10)
        self.assertEqual(dt.minute, 24)

        # Test Z UTC format common in GitHub API
        dt_z = parse_iso_datetime("2026-10-06T03:00:00Z")
        self.assertIsNotNone(dt_z)
        self.assertEqual(dt_z.hour, 3)
        self.assertEqual(dt_z.tzinfo, datetime.timezone.utc)

    def test_midnight_timezone_boundary(self):
        # 23:59:00 on Oct 6 in UTC+7
        dt1 = parse_iso_datetime("2026-10-06T23:59:00+07:00")
        # 00:01:00 on Oct 7 in UTC+7 (which is 17:01 UTC on Oct 6)
        dt2 = parse_iso_datetime("2026-10-07T00:01:00+07:00")

        self.assertEqual(dt1.astimezone(self.tz).date(), datetime.date(2026, 10, 6))
        self.assertEqual(dt2.astimezone(self.tz).date(), datetime.date(2026, 10, 7))

    def test_clean_commits_and_deduplication(self):
        raw = [
            {
                "hash": "commit1",
                "timestamp": "2026-10-06T11:00:00+07:00",
                "author": "Sang",
                "message": "second commit"
            },
            {
                "hash": "commit1",  # duplicate
                "timestamp": "2026-10-06T11:00:00+07:00",
                "author": "Sang",
                "message": "duplicate commit"
            },
            {
                "hash": "commit0",
                "timestamp": "2026-10-06T09:30:00+07:00",
                "author": "Sang",
                "message": "first commit"
            }
        ]

        cleaned = clean_commits(raw)
        self.assertEqual(len(cleaned), 2)
        # Verify deterministic sorting by timestamp ascending
        self.assertEqual(cleaned[0]["hash"], "commit0")
        self.assertEqual(cleaned[1]["hash"], "commit1")

    def test_filter_commits_by_author_and_date(self):
        target = datetime.date(2026, 10, 6)
        commits = [
            # Wrong author, right date
            {"hash": "c1", "timestamp": "2026-10-06T10:00:00+07:00", "author": "Alice", "email": "alice@corp.com", "message": "msg1"},
            # Right author, wrong date (yesterday)
            {"hash": "c2", "timestamp": "2026-10-05T18:00:00+07:00", "author": "Sang", "email": "sang@corp.com", "message": "msg2"},
            # Right author, right date
            {"hash": "c3", "timestamp": "2026-10-06T09:15:00+07:00", "author": "Sang", "email": "sang@corp.com", "message": "msg3"},
            # Right author, right date, later
            {"hash": "c4", "timestamp": "2026-10-06T15:30:00+07:00", "author": "Sang Truong", "email": "sang@corp.com", "message": "msg4"}
        ]

        filtered = filter_commits(commits, target, author="Sang", tz=self.tz)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["hash"], "c3")

    def test_parse_github_repo_slug_urls(self):
        # HTTPS URLs with variations
        self.assertEqual(
            parse_github_repo_slug("https://github.com/octocat/Hello-World"),
            ("octocat", "Hello-World")
        )
        self.assertEqual(
            parse_github_repo_slug("https://github.com/octocat/Hello-World.git"),
            ("octocat", "Hello-World")
        )
        self.assertEqual(
            parse_github_repo_slug("https://github.com/facebook/react/"),
            ("facebook", "react")
        )
        self.assertEqual(
            parse_github_repo_slug("https://github.com/facebook/react/tree/main"),
            ("facebook", "react")
        )
        # SSH URLs
        self.assertEqual(
            parse_github_repo_slug("git@github.com:torvalds/linux.git"),
            ("torvalds", "linux")
        )
        self.assertEqual(
            parse_github_repo_slug("git@github.com:torvalds/linux"),
            ("torvalds", "linux")
        )

    def test_parse_github_repo_slug_bare_and_local(self):
        # Bare slug (non-existing local path)
        self.assertEqual(
            parse_github_repo_slug("octocat/Spoon-Knife"),
            ("octocat", "Spoon-Knife")
        )
        # Local paths should return None
        self.assertIsNone(parse_github_repo_slug("."))
        self.assertIsNone(parse_github_repo_slug("./scripts"))
        self.assertIsNone(parse_github_repo_slug("tests"))
        self.assertIsNone(parse_github_repo_slug("/tmp/nonexistent"))
        self.assertIsNone(parse_github_repo_slug(""))

    def test_normalize_api_commits(self):
        target = datetime.date(2026, 10, 6)
        raw_api_items = [
            {
                "sha": "1234567890abcdef1234567890abcdef12345678",
                "commit": {
                    "author": {
                        "name": "Sang Truong",
                        "email": "sang@corp.com",
                        # 03:00 UTC = 10:00 UTC+7 on 2026-10-06
                        "date": "2026-10-06T03:00:00Z"
                    },
                    "message": "feat: integrate github api commit fetching\n\nDetailed explanation."
                }
            },
            {
                # Other author on same day
                "sha": "abcdef1234567890abcdef1234567890abcdef12",
                "commit": {
                    "author": {
                        "name": "Alice Bob",
                        "email": "alice@corp.com",
                        "date": "2026-10-06T04:00:00Z"
                    },
                    "message": "fix: update docs"
                }
            },
            {
                # Same author, yesterday
                "sha": "9999999990abcdef1234567890abcdef12345678",
                "commit": {
                    "author": {
                        "name": "Sang Truong",
                        "email": "sang@corp.com",
                        "date": "2026-10-05T03:00:00Z"
                    },
                    "message": "chore: old commit"
                }
            }
        ]

        normalized = normalize_api_commits(
            raw_api_items,
            repo_name="react",
            target_date=target,
            author="Sang Truong",
            tz=self.tz
        )

        self.assertEqual(len(normalized), 1)
        c = normalized[0]
        self.assertEqual(c["repository"], "react")
        self.assertEqual(c["hash"], "1234567890abcdef1234567890abcdef12345678")
        self.assertEqual(c["short_hash"], "1234567")
        self.assertEqual(c["author"], "Sang Truong")
        self.assertEqual(c["email"], "sang@corp.com")
        self.assertEqual(c["message"], "feat: integrate github api commit fetching")
        self.assertTrue(c["timestamp"].startswith("2026-10-06T10:00:00"))

    def test_normalize_api_commits_all_authors(self):
        target = datetime.date(2026, 10, 6)
        raw_api_items = [
            {
                "sha": "commit1",
                "commit": {
                    "author": {"name": "Alice", "email": "alice@test.com", "date": "2026-10-06T02:00:00Z"},
                    "message": "Alice commit"
                }
            },
            {
                "sha": "commit2",
                "commit": {
                    "author": {"name": "Bob", "email": "bob@test.com", "date": "2026-10-06T03:00:00Z"},
                    "message": "Bob commit"
                }
            }
        ]

        # Author filter "*" should return commits from all authors on target date
        normalized = normalize_api_commits(
            raw_api_items,
            repo_name="sample-repo",
            target_date=target,
            author="*",
            tz=self.tz
        )
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[0]["hash"], "commit1")
        self.assertEqual(normalized[1]["hash"], "commit2")


if __name__ == "__main__":
    unittest.main()
