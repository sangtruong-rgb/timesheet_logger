#!/usr/bin/env python3
"""
test_timesheet.py - Unit tests for timesheet entry assembly and idempotent persistence.
"""

import copy
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_timesheet import build_entries, format_pr_suffix
from save_timesheet import save_timesheet


class TestTimesheet(unittest.TestCase):
    def test_pr_suffix_formatting(self):
        # Empty PRs
        self.assertEqual(format_pr_suffix([]), "PRs: None")

        # Single PR
        self.assertEqual(format_pr_suffix([{"id": 101}]), "PRs: #101")

        # Multiple PRs sorted
        prs = [{"id": 104}, {"id": 101}, {"id": 104}]
        self.assertEqual(format_pr_suffix(prs), "PRs: #101, #104")

    def test_description_assembly_has_exactly_one_pr_section(self):
        blocks = [
            {
                "date": "2026-10-06",
                "start_time": "09:30",
                "end_time": "12:00",
                "duration_minutes": 150,
                "calendar_titles": ["Focus block"],
                "commits": [{"message": "fix invoice validation"}],
                "prs": [{"id": 101, "title": "Payment fixes"}]
            }
        ]

        ai_judgments = [
            {
                "block": {"start": "09:30", "end": "12:00"},
                "description": "Payment workflow improvements covering invoice validation."
            }
        ]

        entries = build_entries(blocks, ai_judgments)
        self.assertEqual(len(entries), 1)
        desc = entries[0]["entry"]["description"]

        # Check PRs suffix
        self.assertTrue(desc.endswith("PRs: #101"))
        self.assertEqual(desc.count("PRs:"), 1)
        self.assertIn("Payment workflow improvements", desc)

        # Check sources evidence preserved
        self.assertEqual(len(entries[0]["sources"]["commits"]), 1)
        self.assertEqual(len(entries[0]["sources"]["pull_requests"]), 1)

    def test_deterministic_ticket_prefix(self):
        blocks = [
            {
                "date": "2026-10-06",
                "start_time": "14:00",
                "end_time": "16:00",
                "duration_minutes": 120,
                "calendar_titles": [],
                "commits": [
                    {"message": "PAY-123 fix invoice validation"},
                    {"message": "PAY-123 add invoice unit tests"}
                ],
                "prs": []
            }
        ]
        entries = build_entries(blocks, ai_judgments=None)
        self.assertEqual(len(entries), 1)
        desc = entries[0]["entry"]["description"]
        self.assertIn("[PAY-123]", desc)
        self.assertTrue(desc.endswith("PRs: None"))

    def test_fallback_english_with_non_english_evidence_preserves_sources(self):
        block = {
            "date": "2026-10-09", "start_time": "09:00", "end_time": "10:00",
            "duration_minutes": 60, "calendar_titles": ["Tập trung phát triển"],
            "commits": [{"message": "PAY-123 sửa lỗi hóa đơn"}],
            "prs": [{"id": 7, "title": "Thêm kiểm thử"},
                    {"id": 7, "title": "Thêm kiểm thử", "status": "merged"}],
        }
        original = copy.deepcopy(block)
        row = build_entries([block])[0]
        self.assertEqual(row["entry"]["description"],
                         "[PAY-123] Development activity based on 1 recorded commit and 1 pull request. PRs: #7")
        self.assertEqual(row["sources"]["commits"], block["commits"])
        self.assertEqual(row["sources"]["pull_requests"], block["prs"])
        self.assertEqual(row["sources"]["calendar"], block["calendar_titles"])
        self.assertEqual(block, original)

    def test_calendar_fallback_english_does_not_claim_attendance(self):
        for title in ("Họp kế hoạch", "项目会议", "hop ke hoach", "Planning"):
            block = {"date": "2026-10-09", "start_time": "09:00", "end_time": "10:00",
                     "duration_minutes": 60, "time_basis": "scheduled",
                     "calendar_titles": [title], "commits": [], "prs": []}
            with self.subTest(title=title):
                row = build_entries([block])[0]
                self.assertEqual(row["entry"]["description"],
                                 "Scheduled calendar activity; attendance unconfirmed. PRs: None")
                self.assertEqual(row["sources"]["calendar"], [title])
                self.assertEqual(row["attendance"], "unconfirmed")

    def test_save_timesheet_files_creation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            entries = [
                {
                    "entry": {"date": "2026-10-06", "start": "09:00", "end": "09:30", "duration_minutes": 30, "description": "Standup. PRs: None"},
                    "sources": {"calendar": ["Daily stand-up"]}
                }
            ]
            res = save_timesheet(entries, output_dir=tmpdir, target_date="2026-10-06", collection_status="complete")
            json_file = Path(tmpdir) / "2026-10-06.json"
            md_file = Path(tmpdir) / "2026-10-06.md"

            self.assertTrue(json_file.exists())
            self.assertTrue(md_file.exists())
            md_text = md_file.read_text(encoding="utf-8")
            self.assertIn("09:00 – 09:30", md_text)
            self.assertIn("Standup. PRs: None", md_text)


if __name__ == "__main__":
    unittest.main()
