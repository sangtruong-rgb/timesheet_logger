#!/usr/bin/env python3
"""
test_timesheet.py - Unit tests for timesheet entry assembly and idempotent persistence.
"""

import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from build_timesheet import build_entries, format_pr_suffix
from save_timesheet import save_timesheet, upsert_entries


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

    def test_idempotent_upsert(self):
        entry_a = {
            "entry": {"date": "2026-10-06", "start": "09:00", "end": "09:30", "duration_minutes": 30, "description": "Standup. PRs: None"},
            "sources": {}
        }
        entry_b = {
            "entry": {"date": "2026-10-06", "start": "09:30", "end": "12:00", "duration_minutes": 150, "description": "Dev work. PRs: #101"},
            "sources": {}
        }

        # First run: insert 2 entries
        merged1, ins1, upd1 = upsert_entries([], [entry_a, entry_b])
        self.assertEqual(len(merged1), 2)
        self.assertEqual(ins1, 2)
        self.assertEqual(upd1, 0)

        # Second run with exact same data: 0 inserted, 0 updated
        merged2, ins2, upd2 = upsert_entries(merged1, [entry_a, entry_b])
        self.assertEqual(len(merged2), 2)
        self.assertEqual(ins2, 0)
        self.assertEqual(upd2, 0)

        # Third run with updated description for entry_b
        updated_b = dict(entry_b)
        updated_b["entry"] = dict(entry_b["entry"])
        updated_b["entry"]["description"] = "Updated Dev work. PRs: #101"

        merged3, ins3, upd3 = upsert_entries(merged2, [entry_a, updated_b])
        self.assertEqual(len(merged3), 2)
        self.assertEqual(ins3, 0)
        self.assertEqual(upd3, 1)
        self.assertEqual(merged3[1]["entry"]["description"], "Updated Dev work. PRs: #101")

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
