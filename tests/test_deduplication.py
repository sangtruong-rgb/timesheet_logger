#!/usr/bin/env python3
"""
test_deduplication.py - Unit tests for PR and activity deduplication.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from get_pr_activity import deduplicate_prs


class TestDeduplication(unittest.TestCase):
    def test_duplicate_pr_merged_status(self):
        # PR 101 appears both as reviewed and as merged
        raw_prs = [
            {
                "id": 101,
                "repository": "billing",
                "title": "Payment fixes",
                "status": "reviewed",
                "timestamp": "2026-10-06T10:00:00+07:00"
            },
            {
                "id": 101,
                "repository": "billing",
                "title": "Payment fixes",
                "status": "merged",
                "timestamp": "2026-10-06T11:30:00+07:00"
            }
        ]

        deduped = deduplicate_prs(raw_prs)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], 101)
        # Merged takes precedence over reviewed
        self.assertEqual(deduped[0]["status"], "merged")

    def test_multiple_unique_prs(self):
        raw_prs = [
            {"id": 200, "repository": "core", "title": "A", "status": "opened"},
            {"id": 150, "repository": "core", "title": "B", "status": "merged"},
            {"id": 200, "repository": "core", "title": "A", "status": "opened"}
        ]
        deduped = deduplicate_prs(raw_prs)
        self.assertEqual(len(deduped), 2)
        ids = [p["id"] for p in deduped]
        self.assertIn(150, ids)
        self.assertIn(200, ids)


if __name__ == "__main__":
    unittest.main()
