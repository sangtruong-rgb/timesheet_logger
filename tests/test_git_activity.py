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

from get_git_activity import parse_iso_datetime, filter_commits
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
        self.assertEqual(len(filtered), 2)
        self.assertEqual(filtered[0]["hash"], "c3")
        self.assertEqual(filtered[1]["hash"], "c4")


if __name__ == "__main__":
    unittest.main()
