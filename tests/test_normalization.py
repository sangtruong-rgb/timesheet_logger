#!/usr/bin/env python3
"""
test_normalization.py - Unit tests for normalization of daily activity.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from normalize_activity import normalize_all


class TestNormalization(unittest.TestCase):
    def test_normalize_payload_structure(self):
        date_str = "2026-10-06"
        raw_commits = [
            {
                "repository": "repo-a",
                "hash": "1234567890abcdef",
                "short_hash": "1234567",
                "timestamp": "2026-10-06T10:00:00+07:00",
                "author": "Sang Truong",
                "message": "fix validation",
                "raw_api_junk": "should be stripped"
            }
        ]
        raw_prs = [
            {
                "id": 42,
                "repository": "repo-a",
                "title": "Fix validation bug",
                "status": "opened",
                "timestamp": "2026-10-06T10:00:00+07:00",
                "url": "https://github.com/org/repo-a/pull/42",
                "user_avatar": "strip me"
            }
        ]
        raw_calendar = [
            {
                "title": "Standup",
                "start": "2026-10-06T09:00:00+07:00",
                "end": "2026-10-06T09:30:00+07:00",
                "etag": "strip me"
            }
        ]

        normalized = normalize_all(date_str, raw_commits, raw_prs, raw_calendar, timezone_str="+07:00")

        self.assertEqual(normalized["date"], date_str)
        self.assertEqual(normalized["timezone"], "+07:00")
        self.assertEqual(len(normalized["commits"]), 1)
        self.assertEqual(len(normalized["pull_requests"]), 1)
        self.assertEqual(len(normalized["calendar"]), 1)

        # Check raw junk is stripped
        self.assertNotIn("raw_api_junk", normalized["commits"][0])
        self.assertNotIn("user_avatar", normalized["pull_requests"][0])
        self.assertNotIn("etag", normalized["calendar"][0])

    def test_empty_day_normalization(self):
        normalized = normalize_all("2026-10-06", [], [], [])
        self.assertEqual(normalized["date"], "2026-10-06")
        self.assertEqual(normalized["commits"], [])
        self.assertEqual(normalized["pull_requests"], [])
        self.assertEqual(normalized["calendar"], [])


if __name__ == "__main__":
    unittest.main()
