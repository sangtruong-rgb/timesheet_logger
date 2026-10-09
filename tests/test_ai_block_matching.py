"""F03: partial and reordered AI summaries must never depend on list position."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from block_identity import BlockIdentityError
from build_timesheet import build_entries, load_ai_judgments
from prepare_ai_input import prepare_all_blocks

DATE = "2026-10-06"
MEETING_ID = "2026-10-06_09:00_09:30"
WORK_ID = "2026-10-06_09:30_12:00"


def candidate_blocks():
    return [{"date": DATE, "start_time": "09:00", "end_time": "09:30", "duration_minutes": 30,
             "calendar_titles": ["Daily stand-up"], "commits": [], "prs": []},
            {"date": DATE, "start_time": "09:30", "end_time": "12:00", "duration_minutes": 150,
             "calendar_titles": ["Focus"],
             "commits": [{"hash": "audit-sha", "timestamp": "2026-10-06T10:15:00+07:00", "message": "PAY-123 fix invoices"}],
             "prs": [{"id": 101, "title": "PAY-123 Payment fixes", "events": [{"action": "opened", "timestamp": "2026-10-06T11:00:00+07:00"}]}]}]


class TestAIBlockMatching(unittest.TestCase):
    def setUp(self):
        self.blocks = candidate_blocks()

    def assert_sparse_correct(self, judgments):
        original = copy.deepcopy(self.blocks)
        entries = build_entries(self.blocks, judgments)
        self.assertNotIn("AI payment summary", entries[0]["entry"]["description"])
        self.assertIn("attendance unconfirmed", entries[0]["entry"]["description"])
        self.assertEqual(entries[0]["sources"]["calendar"], ["Daily stand-up"])
        self.assertEqual(entries[0]["summary_source"], "fallback")
        self.assertEqual(entries[1]["entry"]["description"], "AI payment summary. PRs: #101")
        self.assertEqual(entries[1]["summary_source"], "ai")
        self.assertEqual(entries[1]["sources"]["commits"], self.blocks[1]["commits"])
        self.assertEqual(entries[1]["sources"]["pull_requests"], self.blocks[1]["prs"])
        self.assertEqual(self.blocks, original)

    def test_partial_id_output_does_not_attach_work_summary_to_meeting(self):
        self.assert_sparse_correct([{"block_id": WORK_ID, "description": "AI payment summary"}])

    def test_original_partial_legacy_reproduction_now_matches_only_its_interval(self):
        self.assert_sparse_correct([{"block": {"start": "09:30", "end": "12:00"}, "description": "AI payment summary"}])

    def test_reordered_outputs_and_blocks_preserve_correspondence(self):
        judgments = [{"block_id": WORK_ID, "description": "Payment"}, {"block_id": MEETING_ID, "description": "Standup"}]
        for blocks in (self.blocks, list(reversed(self.blocks))):
            for items in (judgments, list(reversed(judgments))):
                entries = {item["block_id"]: item for item in build_entries(blocks, items)}
                self.assertEqual(entries[MEETING_ID]["entry"]["description"], "Standup. PRs: None")
                self.assertEqual(entries[WORK_ID]["entry"]["description"], "Payment. PRs: #101")

    def test_payload_id_round_trip_preserves_evidence_without_sending_commit_hashes(self):
        payload = prepare_all_blocks(self.blocks)
        self.assertEqual([p["block_id"] for p in payload], [WORK_ID])
        self.assertNotIn("audit-sha", json.dumps(payload))
        self.assert_sparse_correct([{"block_id": payload[0]["block_id"], "description": "AI payment summary"}])

    def test_same_clock_interval_on_two_days_has_distinct_id_matches(self):
        tomorrow = copy.deepcopy(self.blocks[1]); tomorrow["date"] = "2026-10-07"
        entries = build_entries([self.blocks[1], tomorrow],
                                [{"block_id": "2026-10-07_09:30_12:00", "description": "Tomorrow only"}])
        self.assertEqual(entries[0]["summary_source"], "fallback")
        self.assertIn("Tomorrow only", entries[1]["entry"]["description"])

    def test_explicit_legacy_date_disambiguates_equal_intervals(self):
        tomorrow = copy.deepcopy(self.blocks[1]); tomorrow["date"] = "2026-10-07"
        entries = build_entries([self.blocks[1], tomorrow], [{"date": "2026-10-07",
            "block": {"start": "09:30", "end": "12:00"}, "description": "Tomorrow only"}])
        self.assertEqual([e["summary_source"] for e in entries], ["fallback", "ai"])

    def test_dateless_legacy_output_is_rejected_for_multi_day_candidates(self):
        tomorrow = copy.deepcopy(self.blocks[1]); tomorrow["date"] = "2026-10-07"
        with self.assertRaises(BlockIdentityError):
            build_entries([self.blocks[1], tomorrow], [{"block": {"start": "09:30", "end": "12:00"}, "description": "Ambiguous"}])

    def test_duplicate_id_and_legacy_alias_do_not_silently_overwrite(self):
        with self.assertRaises(BlockIdentityError):
            build_entries(self.blocks, [{"block_id": WORK_ID, "description": "First"},
                {"block": {"start": "09:30", "end": "12:00"}, "description": "Second"}])

    def test_unknown_id_does_not_fall_back_to_matching_clock_metadata(self):
        with self.assertRaises(BlockIdentityError):
            build_entries(self.blocks, [{"block_id": "2026-10-05_09:30_12:00",
                "block": {"start": "09:30", "end": "12:00"}, "description": "Stale"}])

    def test_wrong_day_legacy_output_is_not_attached_to_equal_clock_interval(self):
        with self.assertRaises(BlockIdentityError):
            build_entries(self.blocks, [{"date": "2026-10-05", "block": {"start": "09:30", "end": "12:00"}, "description": "Stale"}])

    def test_unknown_legacy_interval_is_rejected(self):
        with self.assertRaises(BlockIdentityError):
            build_entries(self.blocks, [{"block": {"start": "10:00", "end": "11:00"}, "description": "Unknown"}])

    def test_redundant_metadata_must_agree_with_id(self):
        for metadata in ({"date": "2026-10-05"}, {"date": None},
                         {"block": {"start": "09:00", "end": "09:30"}}, {"block": None}, {"block": {}}):
            with self.subTest(metadata=metadata), self.assertRaises(BlockIdentityError):
                build_entries(self.blocks, [{"block_id": WORK_ID, "description": "Conflicting", **metadata}])

    def test_consistent_redundant_metadata_is_accepted(self):
        self.assert_sparse_correct([{"block_id": WORK_ID, "date": DATE,
            "block": {"start": "09:30", "end": "12:00"}, "description": "AI payment summary"}])

    def test_positional_only_summary_is_rejected(self):
        with self.assertRaises(BlockIdentityError):
            build_entries(self.blocks, [{"description": "No identity"}])

    def test_malformed_summary_shapes_are_rejected(self):
        for value in ({}, "text", [None], [{"block_id": WORK_ID, "description": None}],
                      [{"block_id": WORK_ID, "description": "   "}], [{"block_id": [], "description": "Bad ID"}]):
            with self.subTest(value=value), self.assertRaises(BlockIdentityError):
                build_entries(self.blocks, value)

    def test_no_ai_or_explicit_empty_output_uses_fallback_for_each_own_block(self):
        for value in (None, []):
            entries = build_entries(self.blocks, value)
            self.assertEqual([e["summary_source"] for e in entries], ["fallback", "fallback"])
            self.assertIn("attendance unconfirmed", entries[0]["entry"]["description"])
            self.assertEqual(entries[0]["sources"]["calendar"], ["Daily stand-up"])
            self.assertEqual(entries[1]["sources"]["commits"], self.blocks[1]["commits"])

    def test_duplicate_candidate_identity_is_rejected_before_ai_preparation_or_assembly(self):
        duplicate = [self.blocks[0], copy.deepcopy(self.blocks[0])]
        for operation in (prepare_all_blocks, build_entries):
            with self.subTest(operation=operation.__name__), self.assertRaises(BlockIdentityError):
                operation(duplicate)

    def test_invalid_candidate_date_and_conflicting_candidate_id_are_rejected(self):
        for changes in ({"date": "2026-10-6"}, {"date": None}, {"start_time": "9:00"}, {"block_id": WORK_ID}):
            with self.subTest(changes=changes), self.assertRaises(BlockIdentityError):
                prepare_all_blocks([{**self.blocks[0], **changes}])

    def test_requested_missing_malformed_or_non_array_ai_file_is_not_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai.json"
            with self.assertRaises(BlockIdentityError):
                load_ai_judgments(path)
            for content in ("INVALID JSON", "null", "{}", '"text"'):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(BlockIdentityError):
                    load_ai_judgments(path)
            path.write_text("[]")
            self.assertEqual(load_ai_judgments(path), [])

    def test_standalone_invalid_ai_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            blocks, judgments, output = (directory / name for name in ("blocks.json", "ai.json", "entries.json"))
            blocks.write_text(json.dumps(self.blocks))
            judgments.write_text(json.dumps([{"block_id": "unknown", "description": "Wrong"}]))
            output.write_text("PROTECTED OUTPUT")
            response = subprocess.run([sys.executable, str(ROOT / "scripts/build_timesheet.py"),
                "--blocks-file", str(blocks), "--ai-output", str(judgments), "--output", str(output)],
                capture_output=True, text=True, timeout=15)
            self.assertEqual(response.returncode, 2)
            self.assertEqual(output.read_text(), "PROTECTED OUTPUT")
            self.assertEqual(response.stdout, "")


if __name__ == "__main__":
    unittest.main()
