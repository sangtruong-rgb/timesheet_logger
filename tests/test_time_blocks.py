#!/usr/bin/env python3
"""
test_time_blocks.py - Unit tests for time block construction and activity association.
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_time_blocks import build_time_blocks


class TestTimeBlocks(unittest.TestCase):
    def test_calendar_blocks_and_activity_association(self):
        normalized = {
            "date": "2026-10-06",
            "calendar": [
                {
                    "title": "Daily stand-up",
                    "start": "2026-10-06T09:00:00+07:00",
                    "end": "2026-10-06T09:30:00+07:00"
                },
                {
                    "title": "Product meeting",
                    "start": "2026-10-06T13:30:00+07:00",
                    "end": "2026-10-06T14:30:00+07:00"
                }
            ],
            "commits": [
                {
                    "hash": "c1",
                    "timestamp": "2026-10-06T10:15:00+07:00",
                    "message": "fix customer CSV validation"
                },
                {
                    "hash": "c2",
                    "timestamp": "2026-10-06T15:20:00+07:00",
                    "message": "fix dashboard totals"
                }
            ],
            "pull_requests": [
                {
                    "id": 101,
                    "title": "Payment fixes",
                    "timestamp": "2026-10-06T11:50:00+07:00"
                }
            ]
        }

        blocks = build_time_blocks(normalized)
        # Should have standup, morning dev gap (09:30-12:00), meeting (13:30-14:30), afternoon dev gap (14:30-17:30)
        self.assertGreaterEqual(len(blocks), 4)

        # Check morning block
        morning_block = next((b for b in blocks if b["start_time"] == "09:30" and b["end_time"] == "12:00"), None)
        self.assertIsNotNone(morning_block)
        self.assertEqual(len(morning_block["commits"]), 1)
        self.assertEqual(morning_block["commits"][0]["hash"], "c1")
        self.assertEqual(len(morning_block["prs"]), 1)
        self.assertEqual(morning_block["prs"][0]["id"], 101)

        # Check afternoon block
        afternoon_block = next((b for b in blocks if b["start_time"] == "14:30"), None)
        self.assertIsNotNone(afternoon_block)
        self.assertEqual(len(afternoon_block["commits"]), 1)
        self.assertEqual(afternoon_block["commits"][0]["hash"], "c2")

    def test_no_calendar_day_fallback(self):
        normalized = {
            "date": "2026-10-06",
            "calendar": [],
            "commits": [
                {
                    "hash": "c1",
                    "timestamp": "2026-10-06T10:00:00+07:00",
                    "message": "morning work"
                },
                {
                    "hash": "c2",
                    "timestamp": "2026-10-06T14:30:00+07:00",
                    "message": "afternoon work"
                }
            ],
            "pull_requests": []
        }

        blocks = build_time_blocks(normalized)
        # Spanning morning and afternoon -> 2 blocks
        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["start_time"], "09:00")
        self.assertEqual(blocks[0]["end_time"], "12:00")
        self.assertEqual(blocks[1]["start_time"], "13:30")
        self.assertEqual(blocks[1]["end_time"], "17:30")
        self.assertEqual(len(blocks[0]["commits"]), 1)
        self.assertEqual(len(blocks[1]["commits"]), 1)

    def test_empty_day_produces_no_invented_blocks(self):
        normalized = {
            "date": "2026-10-06",
            "calendar": [],
            "commits": [],
            "pull_requests": []
        }
        blocks = build_time_blocks(normalized)
        self.assertEqual(len(blocks), 0)


if __name__ == "__main__":
    unittest.main()
