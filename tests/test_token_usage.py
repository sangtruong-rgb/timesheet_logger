#!/usr/bin/env python3
"""
test_token_usage.py - Unit tests for Claude transcript parsing and token aggregation.
"""

import csv
import json
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from collect_token_usage import parse_transcript_line_usage, parse_session_file, update_csv


class TestTokenUsage(unittest.TestCase):
    def test_parse_transcript_line_usage_variants(self):
        # Format 1: direct usage
        obj1 = {"usage": {"input_tokens": 150, "output_tokens": 40, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 0}}
        i1, o1, c1 = parse_transcript_line_usage(obj1)
        self.assertEqual(i1, 150)
        self.assertEqual(o1, 40)
        self.assertEqual(c1, 20)

        # Format 2: message.usage
        obj2 = {"message": {"usage": {"prompt_tokens": 120, "completion_tokens": 30, "cache_read": 0, "cache_creation": 0}}}
        i2, o2, c2 = parse_transcript_line_usage(obj2)
        self.assertEqual(i2, 120)
        self.assertEqual(o2, 30)
        self.assertEqual(c2, 0)

        # Format 3: empty / no usage
        obj3 = {"event": "start"}
        self.assertIsNone(parse_transcript_line_usage(obj3))

    def test_update_csv_idempotency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = Path(tmpdir) / "token-usage.csv"
            rec1 = {
                "date": "2026-10-06",
                "session_id": "sess-001",
                "input_tokens": 300,
                "output_tokens": 80,
                "cache_tokens": 50,
                "total_tokens": 430,
                "notes": "run 1"
            }

            # First update
            update_csv(csv_path, [rec1])
            with open(csv_path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["total_tokens"], "430")

            # Second update with same session ID should update in place, not duplicate
            rec1_updated = dict(rec1)
            rec1_updated["input_tokens"] = 370
            rec1_updated["total_tokens"] = 500
            update_csv(csv_path, [rec1_updated])

            with open(csv_path, "r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["total_tokens"], "500")


if __name__ == "__main__":
    unittest.main()
