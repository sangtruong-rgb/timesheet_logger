"""F10: daily evidence conservation and atomic failure, using synthetic inputs."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from normalize_activity import normalize_all, ActivityNormalizationError
from build_time_blocks import build_time_blocks
from prepare_ai_input import prepare_activity_input
import test_pipeline_evidence_blocks as pipeline_tests

DATE = "2026-10-06"
ZONE = "Asia/Ho_Chi_Minh"


def commit(timestamp="2026-10-06T09:00:00+07:00", identity="c"):
    return {"hash": identity, "timestamp": timestamp, "message": "PROJ-12 implement change"}


def pr(timestamp="2026-10-06T09:00:00+07:00"):
    return {"id": 42, "title": "Change", "status": "opened", "timestamp": timestamp}


def calendar(start="2026-10-06T09:00:00+07:00", end="2026-10-06T10:00:00+07:00"):
    return {"title": "Planning", "start": start, "end": end}


class TestValidatedNormalization(unittest.TestCase):
    def normalize(self, commits=None, prs=None, events=None):
        return normalize_all(DATE, commits or [], prs or [], events or [], ZONE)

    def test_mixed_offsets_sorted_by_instant_and_original_preserved(self):
        data = self.normalize([commit("2026-10-06T04:00:00Z", "late"), commit(identity="early")])
        self.assertEqual([c["hash"] for c in data["commits"]], ["early", "late"])
        self.assertEqual(data["commits"][1]["timestamp"], "2026-10-06T11:00:00+07:00")
        self.assertEqual(data["commits"][1]["original_timestamp"], "2026-10-06T04:00:00Z")

    def test_local_day_half_open_boundaries(self):
        data = self.normalize([commit("2026-10-05T17:00:00Z", "start"),
                               commit("2026-10-06T16:59:59Z", "last"), commit("2026-10-06T17:00:00Z", "end")])
        self.assertEqual([c["hash"] for c in data["commits"]], ["start", "last"])
        self.assertEqual(data["unassigned_activity"][0]["activity"]["hash"], "end")

    def test_missing_timestamp_preserves_commit_for_review(self):
        self.assert_quarantined(None, "missing_timestamp")

    def test_invalid_timestamp_preserves_commit_for_review(self):
        self.assert_quarantined("garbage", "invalid_timestamp")

    def test_nonstring_timestamp_preserves_commit_for_review(self):
        self.assert_quarantined({"broken": 1}, "invalid_timestamp")

    def test_out_of_range_timestamp_preserves_commit_for_review(self):
        self.assert_quarantined("9999-12-31T23:00:00Z", "invalid_timestamp")

    def test_naive_timestamp_preserves_commit_for_review(self):
        self.assert_quarantined("2026-10-06T09:00:00", "naive_timestamp")

    def test_wrong_day_timestamp_preserves_commit_for_review(self):
        self.assert_quarantined("2026-10-07T09:00:00+07:00", "outside_target_day")

    def assert_quarantined(self, timestamp, reason):
        data = self.normalize([commit(timestamp)])
        self.assertEqual(data["commits"], [])
        review = []
        self.assertEqual(build_time_blocks(data, unassigned_activity=review), [])
        self.assertEqual(len(review), 1)
        self.assertEqual(review[0]["reason"], reason)
        self.assertEqual(review[0]["activity"]["timestamp"], timestamp)
        payload = prepare_activity_input([], review)
        self.assertEqual(payload["blocks"], [])
        self.assertNotIn("timestamp", payload["unassigned_activity"][0])

    def test_pr_actions_split_without_losing_invalid_or_other_day_event(self):
        reference = {"id": 42, "title": "Change", "events": [
            {"action": "opened", "timestamp": "2026-10-06T02:00:00Z"},
            {"action": "reviewed", "timestamp": None, "id": 7},
            {"action": "merged", "timestamp": "2026-10-07T09:00:00+07:00"}]}
        data = self.normalize(prs=[reference])
        self.assertEqual(len(data["pull_requests"][0]["events"]), 1)
        self.assertEqual(len(data["unassigned_activity"]), 2)
        self.assertEqual({r["reason"] for r in data["unassigned_activity"]}, {"missing_timestamp", "outside_target_day"})
        self.assertEqual(sum(len(r["activity"]["events"]) for r in data["unassigned_activity"]), 2)

    def test_missing_legacy_pr_timestamp_not_lost_during_dedup(self):
        data = self.normalize(prs=[pr(None), {**pr(), "status": "merged"}])
        self.assertEqual(len(data["unassigned_activity"]), 1)
        self.assertEqual(data["pull_requests"][0]["events"][0]["action"], "merged")

    def test_invalid_pr_timestamps_do_not_crash(self):
        for timestamp in (None, "bad", 123, [], {}, "2026-10-06T09:00:00"):
            with self.subTest(timestamp=timestamp):
                self.assertEqual(len(self.normalize(prs=[pr(timestamp)])["unassigned_activity"]), 1)

    def test_pr_events_sort_by_instant(self):
        data = self.normalize(prs=[{**pr(), "events": [
            {"action": "reviewed", "timestamp": "2026-10-06T04:00:00Z", "id": 8},
            {"action": "opened", "timestamp": "2026-10-06T09:00:00+07:00"}]}])
        self.assertEqual([e["action"] for e in data["pull_requests"][0]["events"]], ["opened", "reviewed"])

    def test_pr_references_sort_by_first_action_instant(self):
        data = self.normalize(prs=[{**pr("2026-10-06T04:00:00Z"), "id": 1},
                                   {**pr("2026-10-06T09:00:00+07:00"), "id": 99}])
        self.assertEqual([p["id"] for p in data["pull_requests"]], [99, 1])

    def test_calendar_conversion_preserves_full_cross_day_extent(self):
        data = self.normalize(events=[calendar("2026-10-05T16:00:00Z", "2026-10-05T18:00:00Z")])
        event = data["calendar"][0]
        self.assertEqual(event["start"], "2026-10-05T23:00:00+07:00")
        self.assertEqual(event["original_start"], "2026-10-05T16:00:00Z")
        self.assertEqual(build_time_blocks(data)[0]["start_time"], "00:00")

    def test_wrong_day_calendar_is_review_evidence_not_duration(self):
        data = self.normalize(events=[calendar("2026-10-07T09:00:00+07:00", "2026-10-07T10:00:00+07:00")])
        review = []
        self.assertEqual(build_time_blocks(data, unassigned_activity=review), [])
        self.assertEqual(review[0]["source"], "google_calendar")
        self.assertEqual(prepare_activity_input([], review)["unassigned_activity"][0]["title"], "Planning")

    def test_all_day_canonical_and_exclusive_dates(self):
        data = self.normalize(events=[{"title": "Deadline", "start": DATE, "end": "2026-10-07", "all_day": True}])
        self.assertEqual(len(data["calendar_context"]), 1)
        self.assertEqual(build_time_blocks(data), [])

    def test_invalid_calendar_intervals_block(self):
        for start, end in (("bad", "bad"), ("2026-10-06T09:00:00", "2026-10-06T10:00:00"),
                           ("2026-10-06T10:00:00Z", "2026-10-06T09:00:00Z"),
                           ("2026-10-06T09:00:00Z", "2026-10-06T09:00:00Z"), (DATE, DATE)):
            with self.subTest(start=start, end=end), self.assertRaises(ActivityNormalizationError):
                self.normalize(events=[calendar(start, end)])

    def test_source_structure_and_field_types_block(self):
        for source, values in (("commits", [[1], [{"hash": 123}], [{"hash": ""}], [{**commit(), "message": 7}]]),
                               ("prs", [[{**pr(), "id": True}], [{**pr(), "id": "42"}], [{**pr(), "events": {}}],
                                        [{**pr(), "events": [{"action": "unknown"}]}]]),
                               ("events", [[{**calendar(), "all_day": "false"}], [{**calendar(), "title": 7}]])):
            for value in values:
                with self.subTest(source=source, value=value), self.assertRaises(ActivityNormalizationError):
                    self.normalize(**{source: value})
        with self.assertRaises(ActivityNormalizationError):
            normalize_all(DATE, {}, [], [], ZONE)

    def test_conflicting_commit_duplicate_blocks_instead_of_first_win(self):
        with self.assertRaises(ActivityNormalizationError):
            self.normalize([commit(), {**commit(), "message": "different"}])

    def test_qualified_commit_identity_does_not_collapse_repositories(self):
        data = self.normalize([{**commit(), "repository": "a"}, {**commit(), "repository": "b"}, {**commit(), "repository": "a"}])
        self.assertEqual(len(data["commits"]), 2)

    def test_valid_model_normalization_is_idempotent_and_does_not_mutate_sources(self):
        raw = ([commit("2026-10-06T02:00:00Z")], [pr("2026-10-06T02:00:00Z")], [calendar("2026-10-06T02:00:00Z", "2026-10-06T03:00:00Z")])
        before = copy.deepcopy(raw)
        first = self.normalize(*raw)
        second = self.normalize(first["commits"], first["pull_requests"], first["calendar"])
        self.assertEqual(raw, before)
        self.assertEqual(first, second)

    def test_dst_fall_back_sorts_same_local_hour_by_utc_instant(self):
        data = normalize_all("2026-11-01", [commit("2026-11-01T01:30:00-05:00", "later"),
            commit("2026-11-01T01:45:00-04:00", "earlier")], [], [], "America/New_York")
        self.assertEqual([c["hash"] for c in data["commits"]], ["earlier", "later"])


class TestNormalizationCLI(unittest.TestCase):
    def invoke(self, directory, records, extra=()):
        source = directory / "source.json"
        source.write_text(json.dumps(records))
        output = directory / "normalized.json"
        output.write_text("OLD OUTPUT")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/normalize_activity.py"), "--date", DATE,
            "--commits-file", str(source), "--output", str(output), *extra], capture_output=True, text=True)
        return result, output

    def test_invalid_structure_preserves_output_and_raw_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            raw = directory / "raw"
            result, output = self.invoke(directory, [{"hash": 123}], ["--raw-dir", str(raw)])
            self.assertEqual(result.returncode, 2)
            self.assertEqual(output.read_text(), "OLD OUTPUT")
            self.assertFalse(raw.exists())
            draft = json.loads((directory / "drafts" / f"{DATE}.normalization.json").read_text())
            self.assertEqual(draft["activity"]["commits"], [{"hash": 123}])

    def test_explicit_missing_file_is_error_not_empty_success(self):
        with tempfile.TemporaryDirectory() as temp:
            result, output = self.invoke(Path(temp), [], ["--prs-file", str(Path(temp) / "missing.json")])
            self.assertEqual(result.returncode, 2)
            self.assertEqual(output.read_text(), "OLD OUTPUT")

    def test_invalid_json_preserves_output(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            bad = directory / "bad.json"
            bad.write_text("{broken")
            result, output = self.invoke(directory, [], ["--prs-file", str(bad)])
            self.assertEqual(result.returncode, 2)
            self.assertEqual(output.read_text(), "OLD OUTPUT")

    def test_success_writes_canonical_timestamp_and_review_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            result, output = self.invoke(Path(temp), [commit("2026-10-06T02:00:00Z"), commit(None, "missing")])
            self.assertEqual(result.returncode, 0, result.stderr)
            model = json.loads(output.read_text())
            self.assertEqual(model["commits"][0]["timestamp"], "2026-10-06T09:00:00+07:00")
            self.assertEqual(len(model["unassigned_activity"]), 1)


class TestF10Pipeline(unittest.TestCase):
    setUp = pipeline_tests.TestPipelineEvidenceBlocks.setUp
    pipeline = pipeline_tests.TestPipelineEvidenceBlocks.pipeline
    snapshot = pipeline_tests.TestPipelineEvidenceBlocks.snapshot
    rows = pipeline_tests.TestPipelineEvidenceBlocks.rows
    def test_structure_error_keeps_all_evidence_and_final_files(self):
        self.assertEqual(self.pipeline([calendar()]), 0)
        before = self.snapshot()
        records = [commit(), {"hash": 123}]
        self.assertEqual(self.pipeline([calendar()], records), 2)
        self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["activity"]["commits"], records)
        self.assertEqual(draft["activity"]["calendar"], [calendar()])
        self.assertEqual(draft["normalization"]["status"], "blocked")

    def test_source_failure_and_invalid_structure_keep_incomplete_git_draft(self):
        self.assertEqual(self.pipeline([], [{"hash": 123}], calendar_status="error"), 2)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["collection"]["status"], "incomplete")
        self.assertEqual(draft["activity"]["commits"], [{"hash": 123}])
        self.assertIn("INCOMPLETE", self.stdout.getvalue())

    def test_naive_and_wrong_day_evidence_create_no_fake_hours_and_rerun_stable(self):
        records = [commit("2026-10-06T09:00:00"), commit("2026-10-07T09:00:00+07:00", "tomorrow")]
        self.assertEqual(self.pipeline([], records), 0)
        self.assertEqual(self.rows(), [])
        path = self.output / f"{DATE}.activity-review.json"
        review = json.loads(path.read_text())
        self.assertEqual(len(review["unassigned_activity"]), 2)
        before = {**self.snapshot(), path: path.read_bytes()}
        self.assertEqual(self.pipeline([], records), 0)
        self.assertTrue(all(p.read_bytes() == content for p, content in before.items()))


if __name__ == "__main__":
    unittest.main()
