"""F04–F07 assembly with synthetic collector responses, real block/storage code."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from run_pipeline import run
from test_evidence_backed_blocks import DATE, commit, event


class TestPipelineEvidenceBlocks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.output = self.directory / "timesheets"
        self.ai = self.directory / "ai-input.json"
        self.config = self.directory / "profile.json"
        self.config.write_text(json.dumps({"repositories": ["test/project"], "author": {"names": ["Test User"]},
            "github": {"users": ["test-user"]}, "timezone": "Asia/Ho_Chi_Minh"}))

    def pipeline(self, calendars, commits=None, calendar_status="success", demo=False):
        def collector(command, source, mode):
            items = []
            if source == "git":
                items = commits or []
            elif source == "google_calendar" and calendar_status == "success":
                items = calendars
            return {"source": source, "mode": mode, "status": calendar_status if source == "google_calendar" else "success", "items": items}
        args = ["run_pipeline.py", "--date", DATE, "--config", str(self.config), "--output-dir", str(self.output), "--export-ai-input", str(self.ai)]
        if demo:
            args += ["--calendar-fixture", "EXPLICIT SYNTHETIC TEST FIXTURE"]
        previous = Path.cwd()
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        try:
            os.chdir(self.directory)
            with patch.object(sys, "argv", args), patch("run_pipeline.run_source_collector", side_effect=collector), \
                    contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
                return run()
        finally:
            os.chdir(previous)

    def rows(self):
        return json.loads((self.output / f"{DATE}.json").read_text())

    def snapshot(self):
        return {p: p.read_bytes() for p in (self.output / f"{DATE}.json", self.output / f"{DATE}.md",
            self.output / f"{DATE}.collection.json", self.ai)}

    def test_calendar_only_pipeline_outputs_one_faithful_scheduled_row(self):
        self.assertEqual(self.pipeline([event()]), 0, self.stderr.getvalue())
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry"]["duration_minutes"], 30)
        self.assertEqual(rows[0]["entry"]["description"], "Daily stand-up. PRs: None")
        self.assertEqual(rows[0]["time_basis"], "scheduled")
        self.assertEqual(json.loads(self.ai.read_text())["blocks"], [])

    def test_supported_gap_is_explicit_estimate_in_json_markdown_and_ai_input(self):
        self.assertEqual(self.pipeline([event(), event("13:30", "14:00", "Planning")], [commit()]), 0)
        estimates = [r for r in self.rows() if r["time_basis"] == "estimated"]
        self.assertEqual(len(estimates), 1)
        self.assertEqual(estimates[0]["sources"]["calendar"], [])
        self.assertEqual(estimates[0]["sources"]["commits"][0]["hash"], "test-commit")
        self.assertIn("(estimated)", (self.output / f"{DATE}.md").read_text())
        self.assertEqual(sum(p["time_basis"] == "estimated" for p in json.loads(self.ai.read_text())["blocks"]), 1)

    def test_rerun_without_activity_removes_previously_supported_generated_gap(self):
        events = [event(), event("13:30", "14:00", "Planning")]
        self.assertEqual(self.pipeline(events, [commit()]), 0)
        self.assertEqual(len(self.rows()), 3)
        self.assertEqual(self.pipeline(events), 0)
        self.assertEqual(len(self.rows()), 2)
        self.assertTrue(all(r["time_basis"] == "scheduled" for r in self.rows()))
        self.assertIn("Removed: 1", self.stdout.getvalue())

    def test_failed_calendar_keeps_all_final_outputs_unchanged(self):
        self.assertEqual(self.pipeline([event()]), 0)
        before = self.snapshot()
        self.assertEqual(self.pipeline([], calendar_status="error"), 2)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_exact_rerun_keeps_timesheet_bytes_unchanged(self):
        self.assertEqual(self.pipeline([event()]), 0)
        before = self.snapshot()
        self.assertEqual(self.pipeline([event()]), 0)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_demo_estimate_output_is_isolated_from_live_files(self):
        self.assertEqual(self.pipeline([event()]), 0)
        before = self.snapshot()
        self.assertEqual(self.pipeline([], [commit()], demo=True), 0)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        demo = json.loads((self.output / "demo" / f"{DATE}.json").read_text())
        self.assertTrue(all(r["time_basis"] == "estimated" for r in demo))
        self.assertIn("DEMO:", (self.output / "demo" / f"{DATE}.md").read_text())

    def test_final_gap_lunch_split_reaches_json_markdown_and_ai_input(self):
        activities = [commit("10:00"), commit("15:00", "afternoon")]
        self.assertEqual(self.pipeline([event()], activities), 0)
        rows = self.rows()
        self.assertEqual([(r["entry"]["start"], r["entry"]["end"]) for r in rows],
                         [("09:00", "09:30"), ("09:30", "12:00"), ("13:30", "17:30")])
        self.assertEqual(sum(r["entry"]["duration_minutes"] for r in rows), 420)
        collected = [c for r in rows for c in r["sources"]["commits"]]
        self.assertEqual([{key: c[key] for key in activities[0]} for c in collected], activities)
        self.assertEqual([r["block_id"] for r in rows if r["sources"]["commits"] or r["sources"]["pull_requests"]], [b["block_id"] for b in json.loads(self.ai.read_text())["blocks"]])
        self.assertIn("**Total Proposed Time:** 420 mins", (self.output / f"{DATE}.md").read_text())

    def test_existing_generated_cross_lunch_row_is_replaced_by_two_segments(self):
        from save_timesheet import save_timesheet
        old = {"entry": {"date": DATE, "start": "09:30", "end": "17:30",
                        "duration_minutes": 480, "description": "Old estimated work. PRs: None"},
               "time_basis": "estimated", "sources": {"calendar": [], "commits": [], "pull_requests": []}}
        save_timesheet([old], self.output, target_date=DATE, collection_status="complete")
        self.assertEqual(self.pipeline([event()], [commit("10:00"), commit("15:00", "afternoon")]), 0)
        self.assertEqual(len(self.rows()), 3)
        self.assertNotIn(("09:30", "17:30"), [(r["entry"]["start"], r["entry"]["end"]) for r in self.rows()])
        self.assertIn("Removed: 1", self.stdout.getvalue())

    def test_split_lunch_snapshot_is_idempotent(self):
        activities = [commit("10:00"), commit("15:00", "afternoon")]
        self.assertEqual(self.pipeline([event()], activities), 0)
        before = self.snapshot()
        self.assertEqual(self.pipeline([event()], activities), 0)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_calendar_failure_preserves_existing_split_lunch_snapshot(self):
        self.assertEqual(self.pipeline([event()], [commit("10:00"), commit("15:00", "afternoon")]), 0)
        before = self.snapshot()
        self.assertEqual(self.pipeline([], calendar_status="error"), 2)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_overlap_pipeline_exports_disjoint_proposal_with_attendance_review(self):
        events = [event("09:00", "10:00", "A"), event("09:30", "10:30", "B")]
        self.assertEqual(self.pipeline(events, [commit("09:45")]), 0)
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual(sum(r["entry"]["duration_minutes"] for r in rows), 90)
        self.assertTrue(rows[1]["calendar_overlap"])
        self.assertEqual(rows[1]["review"]["attendance"], "unconfirmed")
        self.assertEqual(rows[1]["sources"]["calendar_events"], events)
        self.assertEqual(len(rows[1]["sources"]["commits"]), 1)
        self.assertTrue(json.loads(self.ai.read_text())["blocks"][0]["calendar_overlap"])
        self.assertIn("**Total Proposed Time:** 90 mins", (self.output / f"{DATE}.md").read_text())
        self.assertIn("REVIEW REQUIRED", self.stdout.getvalue())
        manifest = json.loads((self.output / f"{DATE}.collection.json").read_text())
        self.assertEqual(manifest["status"], "complete")

    def test_identical_calendar_intervals_are_not_duplicate_identity_failure(self):
        events = [event("09:00", "10:00", "A"), event("09:00", "10:00", "B")]
        self.assertEqual(self.pipeline(events), 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["sources"]["calendar_events"], events)
        self.assertEqual(self.rows()[0]["entry"]["duration_minutes"], 60)

    def test_rerun_replaces_old_overlapping_generated_rows(self):
        from save_timesheet import save_timesheet
        old = [{"entry": {"date": DATE, "start": start, "end": end, "duration_minutes": 60,
                         "description": "Old scheduled meeting. PRs: None"}, "sources": {}}
               for start, end in [("09:00", "10:00"), ("09:30", "10:30")]]
        save_timesheet(old, self.output, target_date=DATE, collection_status="complete")
        self.assertEqual(self.pipeline([event("09:00", "10:00", "A"), event("09:30", "10:30", "B")]), 0)
        self.assertEqual(len(self.rows()), 3)
        self.assertIn("Removed: 2", self.stdout.getvalue())
        self.assertEqual(sum(r["entry"]["duration_minutes"] for r in self.rows()), 90)

    def test_overlap_exact_rerun_preserves_files_and_removing_event_clears_review(self):
        events = [event("09:00", "10:00", "A"), event("09:30", "10:30", "B")]
        self.assertEqual(self.pipeline(events), 0)
        before = self.snapshot()
        self.assertEqual(self.pipeline(list(reversed(events))), 0)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.pipeline([events[0]]), 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertFalse(self.rows()[0].get("calendar_overlap"))
        self.assertNotIn("REVIEW REQUIRED", (self.output / f"{DATE}.md").read_text())

    def test_calendar_failure_preserves_overlap_review_proposal(self):
        self.assertEqual(self.pipeline([event("09:00", "10:00", "A"), event("09:30", "10:30", "B")]), 0)
        before = self.snapshot()
        self.assertEqual(self.pipeline([], calendar_status="error"), 2)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_invalid_partition_bounds_create_review_draft_and_preserve_final_files(self):
        self.assertEqual(self.pipeline([event()]), 0)
        before = self.snapshot()
        self.assertEqual(self.pipeline([event("10:00", "09:00", "Invalid bounds")]), 2)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["activity"]["calendar"][0]["title"], "Invalid bounds")
        self.assertEqual(draft["normalization"]["status"], "blocked")

    def test_all_day_only_pipeline_saves_context_and_zero_work_time(self):
        context = {"title": "Deadline", "start": DATE, "end": "2026-10-07", "all_day": True}
        self.assertEqual(self.pipeline([context]), 0)
        self.assertEqual(self.rows(), [])
        self.assertEqual(json.loads(self.ai.read_text())["blocks"], [])
        path = self.output / f"{DATE}.calendar-context.json"
        self.assertEqual(json.loads(path.read_text())["calendar_context"], [context])
        manifest = json.loads((self.output / f"{DATE}.collection.json").read_text())
        self.assertEqual(manifest["calendar_context_count"], 1)
        self.assertEqual(manifest["calendar_context_file"], path.name)
        text = (self.output / f"{DATE}.md").read_text()
        self.assertIn("0 mins", text)
        self.assertIn("Deadline", text)
        self.assertIn("not counted as work time", text)

    def test_all_day_context_does_not_prevent_git_work_proposal(self):
        context = {"title": "Holiday", "start": DATE, "end": "2026-10-07", "all_day": True}
        self.assertEqual(self.pipeline([context], [commit()]), 0)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["time_basis"], "estimated")
        self.assertEqual(self.rows()[0]["sources"]["calendar"], [])
        self.assertEqual(len(self.rows()[0]["sources"]["commits"]), 1)
        self.assertNotIn("Holiday", self.ai.read_text())

    def test_cross_midnight_pipeline_saves_24_hour_end_with_original_evidence(self):
        calendar = {"title": "Late support", "start": DATE+"T22:00:00+07:00", "end": "2026-10-07T02:00:00+07:00"}
        self.assertEqual(self.pipeline([calendar], [commit("23:15")]), 0)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["entry"]["start"], rows[0]["entry"]["end"], rows[0]["entry"]["duration_minutes"]),
                         ("22:00", "24:00", 120))
        self.assertEqual(rows[0]["sources"]["calendar_events"], [calendar])
        self.assertEqual(json.loads(self.ai.read_text())["blocks"][0]["block"]["end"], "24:00")

    def test_previous_night_pipeline_saves_only_target_day_portion(self):
        calendar = {"title": "Night support", "start": "2026-10-05T22:00:00+07:00", "end": DATE+"T02:00:00+07:00"}
        self.assertEqual(self.pipeline([calendar]), 0)
        self.assertEqual((self.rows()[0]["entry"]["start"], self.rows()[0]["entry"]["end"],
                          self.rows()[0]["entry"]["duration_minutes"]), ("00:00", "02:00", 120))

    def test_context_snapshot_rerun_is_stable_and_deleted_context_disappears(self):
        context = {"title": "Deadline", "start": DATE, "end": "2026-10-07", "all_day": True}
        self.assertEqual(self.pipeline([context]), 0)
        before = self.snapshot()
        context_path = self.output / f"{DATE}.calendar-context.json"
        before[context_path] = context_path.read_bytes()
        self.assertEqual(self.pipeline([context]), 0)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.pipeline([]), 0)
        self.assertEqual(json.loads(context_path.read_text())["calendar_context"], [])
        self.assertNotIn("Deadline", (self.output / f"{DATE}.md").read_text())

    def test_calendar_failure_preserves_context_sidecar_and_every_final_file(self):
        context = {"title": "Deadline", "start": DATE, "end": "2026-10-07", "all_day": True}
        self.assertEqual(self.pipeline([context]), 0)
        before = self.snapshot()
        path = self.output / f"{DATE}.calendar-context.json"
        before[path] = path.read_bytes()
        self.assertEqual(self.pipeline([], calendar_status="error"), 2)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_context_demo_stays_separate_from_live_context(self):
        context = {"title": "Live context", "start": DATE, "end": "2026-10-07", "all_day": True}
        self.assertEqual(self.pipeline([context]), 0)
        before = self.snapshot()
        path = self.output / f"{DATE}.calendar-context.json"
        before[path] = path.read_bytes()
        self.assertEqual(self.pipeline([{**context, "title": "Demo context"}], demo=True), 0)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        demo = json.loads((self.output / "demo" / f"{DATE}.calendar-context.json").read_text())
        self.assertEqual(demo["collection_status"], "demo")
        self.assertEqual(demo["calendar_context"][0]["title"], "Demo context")

    def test_corrupt_context_blocks_pipeline_without_overwriting_any_final_file(self):
        context = {"title": "Deadline", "start": DATE, "end": "2026-10-07", "all_day": True}
        self.assertEqual(self.pipeline([context]), 0)
        path = self.output / f"{DATE}.calendar-context.json"
        path.write_text("{invalid")
        before = self.snapshot()
        before[path] = path.read_bytes()
        self.assertEqual(self.pipeline([]), 2)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_wrong_day_context_is_quarantined_and_removed_from_current_context(self):
        context = {"title": "Deadline", "start": DATE, "end": "2026-10-07", "all_day": True}
        self.assertEqual(self.pipeline([context]), 0)
        path = self.output / f"{DATE}.calendar-context.json"
        self.assertEqual(self.pipeline([{**context, "start": "2026-10-07", "end": "2026-10-08"}]), 0)
        self.assertEqual(json.loads(path.read_text())["calendar_context"], [])
        review = json.loads((self.output / f"{DATE}.activity-review.json").read_text())
        self.assertEqual(review["unassigned_activity"][0]["source"], "google_calendar")
        self.assertEqual(review["unassigned_activity"][0]["reason"], "outside_target_day")


if __name__ == "__main__":
    unittest.main()
