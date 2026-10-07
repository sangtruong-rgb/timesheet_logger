"""F02 regressions for changed full-day snapshots and protected human edits."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from save_timesheet import save_timesheet, TimesheetReconciliationError

DATE = "2026-10-06"


def row(start="09:00", end="12:00", minutes=180, description="Development", kind=None):
    result = {"entry": {"date": DATE, "start": start, "end": end,
                        "duration_minutes": minutes, "description": description},
              "sources": {"calendar": [description]}}
    if kind:
        result["provenance"] = {"kind": kind}
        if kind == "generated":
            result["provenance"]["generator"] = "timesheet_logger"
    return result


class TestDailyReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.json = self.directory / f"{DATE}.json"
        self.md = self.directory / f"{DATE}.md"

    def save(self, entries, status="complete"):
        return save_timesheet(entries, str(self.directory), target_date=DATE,
                              collection_status=status)["dates"][DATE]

    def records(self):
        return json.loads(self.json.read_text())

    def seed(self, entries):
        self.json.write_text(json.dumps(entries))
        self.md.write_text("PROTECTED ORIGINAL MARKDOWN")

    def assert_blocked(self, incoming, status="complete"):
        original = {p: p.read_bytes() for p in (self.json, self.md)}
        with self.assertRaises(TimesheetReconciliationError):
            self.save(incoming, status)
        for path, content in original.items():
            self.assertEqual(path.read_bytes(), content)

    def test_split_replaces_old_interval_and_counts_180_not_360_minutes(self):
        self.save([row()])
        incoming = [row("09:00", "09:30", 30, "Standup"), row("09:30", "12:00", 150)]
        before = copy.deepcopy(incoming)
        summary = self.save(incoming)
        self.assertEqual(incoming, before)  # ownership tagging must not mutate caller data
        self.assertEqual([(x["entry"]["start"], x["entry"]["end"]) for x in self.records()],
                         [("09:00", "09:30"), ("09:30", "12:00")])
        self.assertEqual(sum(x["entry"]["duration_minutes"] for x in self.records()), 180)
        self.assertEqual((summary["inserted"], summary["removed"]), (2, 1))
        self.assertIn("**Total Tracked Time:** 180 mins", self.md.read_text())

    def test_resize_removes_previous_boundaries(self):
        self.save([row()])
        summary = self.save([row("10:00", "11:00", 60)])
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(self.records()[0]["entry"]["duration_minutes"], 60)
        self.assertEqual(summary["removed"], 1)

    def test_deleted_event_disappears_from_next_snapshot(self):
        self.save([row(), row("14:00", "15:00", 60, "Meeting")])
        self.save([row()])
        self.assertEqual(len(self.records()), 1)
        self.assertNotIn("Meeting", self.md.read_text())

    def test_successful_empty_day_clears_generated_rows(self):
        self.save([row()])
        summary = self.save([])
        self.assertEqual(self.records(), [])
        self.assertEqual((summary["removed"], summary["total_entries"]), (1, 0))
        self.assertIn("**Total Tracked Time:** 0 mins", self.md.read_text())

    def test_initial_empty_day_has_explicit_empty_store(self):
        self.save([])
        self.assertEqual(self.records(), [])
        self.assertTrue(self.md.exists())

    def test_exact_rerun_preserves_both_file_contents(self):
        self.save([row()])
        original = {p: p.read_bytes() for p in (self.json, self.md)}
        summary = self.save([row()])
        self.assertEqual((summary["inserted"], summary["updated"], summary["removed"]), (0, 0, 0))
        for path, content in original.items():
            self.assertEqual(path.read_bytes(), content)

    def test_matching_generated_key_updates_description_and_sources(self):
        self.save([row()])
        changed = row(description="Corrected summary")
        changed["sources"]["commits"] = [{"hash": "audit-evidence"}]
        summary = self.save([changed])
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(self.records()[0]["sources"]["commits"], changed["sources"]["commits"])

    def test_manual_row_survives_changed_generated_snapshot(self):
        manual = row("16:00", "17:00", 60, "Human edit", "manual")
        self.seed([row(kind="generated"), manual])
        summary = self.save([row("10:00", "11:00", 60)])
        self.assertIn(manual, self.records())
        self.assertEqual(summary["preserved_manual"], 1)
        self.assertEqual(summary["removed"], 1)

    def test_empty_rerun_preserves_manual_and_override_rows(self):
        manual = row("16:00", "17:00", 60, "Human edit", "manual")
        override = row("14:00", "15:00", 60, "Approved correction", "override")
        self.seed([row(kind="generated"), manual, override])
        self.save([])
        self.assertEqual(self.records(), [override, manual])

    def test_exact_interval_override_suppresses_generated_candidate(self):
        override = row(description="Approved human summary", kind="override")
        self.seed([override])
        summary = self.save([row(description="New automatic summary")])
        self.assertEqual(self.records(), [override])
        self.assertEqual((summary["overridden"], summary["total_entries"]), (1, 1))

    def test_changed_override_interval_requires_review(self):
        self.seed([row(kind="override")])
        self.assert_blocked([row("09:00", "09:30", 30), row("09:30", "12:00", 150)])

    def test_overlapping_manual_row_preserves_original_files(self):
        self.seed([row("10:00", "11:00", 60, kind="manual")])
        self.assert_blocked([row()])

    def test_touching_manual_interval_is_not_a_conflict(self):
        manual = row("12:00", "12:30", 30, kind="manual")
        self.seed([manual])
        self.save([row()])
        self.assertEqual(len(self.records()), 2)

    def test_overlapping_protected_rows_require_review(self):
        self.seed([row(kind="manual"), row("10:00", "11:00", 60, kind="override")])
        self.assert_blocked([])

    def test_legacy_rows_are_not_assumed_generated_even_with_collection_metadata(self):
        legacy = row()
        legacy["collection"] = {"status": "complete"}
        self.seed([legacy])
        self.assert_blocked([row("10:00", "11:00", 60)])

    def test_empty_rerun_does_not_erase_legacy_rows(self):
        self.seed([row()])
        self.assert_blocked([])

    def test_corrupt_store_is_not_replaced_by_empty_store(self):
        self.json.write_text("INVALID JSON")
        self.md.write_text("OLD MARKDOWN")
        self.assert_blocked([])

    def test_non_array_store_requires_review(self):
        self.json.write_text("{}")
        self.md.write_text("OLD MARKDOWN")
        self.assert_blocked([row()])

    def test_incomplete_or_unknown_status_cannot_clear_generated_rows(self):
        self.save([row()])
        for status in ("incomplete", "error", None):
            with self.subTest(status=status):
                self.assert_blocked([], status)

    def test_incoming_collection_status_mismatch_is_rejected(self):
        self.save([row()])
        incoming = row()
        incoming["collection"] = {"status": "incomplete"}
        self.assert_blocked([incoming])

    def test_foreign_date_does_not_change_target_or_other_day(self):
        self.save([row()])
        incoming = row()
        incoming["entry"]["date"] = "2026-10-05"
        self.assert_blocked([incoming])
        self.assertFalse((self.directory / "2026-10-05.json").exists())

    def test_unrelated_daily_files_remain_unchanged(self):
        other = self.directory / "2026-10-05.json"
        other.write_text("ANOTHER DAY")
        self.save([row()])
        self.save([])
        self.assertEqual(other.read_text(), "ANOTHER DAY")

    def test_duplicate_incoming_intervals_do_not_overwrite_evidence(self):
        self.save([row()])
        self.assert_blocked([row(), row(description="Different evidence")])

    def test_unsupported_provenance_is_not_silently_discarded(self):
        self.seed([row(kind="another-tool")])
        self.assert_blocked([])

    def test_markdown_without_json_is_preserved(self):
        self.md.write_text("HUMAN DOCUMENT")
        with self.assertRaises(TimesheetReconciliationError):
            self.save([])
        self.assertEqual(self.md.read_text(), "HUMAN DOCUMENT")
        self.assertFalse(self.json.exists())

    def test_standalone_cli_requires_explicit_date_even_for_empty_input(self):
        self.save([row()])
        incoming = self.directory / "incoming.json"
        incoming.write_text("[]")
        response = subprocess.run([sys.executable, str(ROOT / "scripts/save_timesheet.py"),
                                   "-i", str(incoming), "-d", str(self.directory),
                                   "--collection-status", "complete"], capture_output=True, text=True)
        self.assertEqual(response.returncode, 2)
        self.assertEqual(len(self.records()), 1)

    def test_standalone_cli_empty_snapshot_clears_selected_day(self):
        self.save([row()])
        incoming = self.directory / "incoming.json"
        incoming.write_text("[]")
        response = subprocess.run([sys.executable, str(ROOT / "scripts/save_timesheet.py"),
                                   "-i", str(incoming), "-d", str(self.directory), "--date", DATE,
                                   "--collection-status", "complete"], capture_output=True, text=True)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(self.records(), [])

    def test_standalone_demo_does_not_clear_live_store(self):
        self.save([row()])
        original = self.json.read_bytes()
        incoming = self.directory / "incoming.json"
        incoming.write_text("[]")
        response = subprocess.run([sys.executable, str(ROOT / "scripts/save_timesheet.py"),
                                   "-i", str(incoming), "-d", str(self.directory), "--date", DATE,
                                   "--collection-status", "demo"], capture_output=True, text=True)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(self.json.read_bytes(), original)
        self.assertIn("DEMO:", (self.directory / "demo" / f"{DATE}.md").read_text())


if __name__ == "__main__":
    unittest.main()
