"""F04 end-to-end assembly with synthetic collector responses, real block/storage code."""
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
            self.output / f"{DATE}.collection.json", self.ai, self.directory / "data/token-usage.csv")}

    def test_calendar_only_pipeline_outputs_one_faithful_scheduled_row(self):
        self.assertEqual(self.pipeline([event()]), 0, self.stderr.getvalue())
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["entry"]["duration_minutes"], 30)
        self.assertEqual(rows[0]["entry"]["description"], "Daily stand-up. PRs: None")
        self.assertEqual(rows[0]["time_basis"], "scheduled")
        self.assertEqual(json.loads(self.ai.read_text())[0]["time_basis"], "scheduled")

    def test_supported_gap_is_explicit_estimate_in_json_markdown_and_ai_input(self):
        self.assertEqual(self.pipeline([event(), event("13:30", "14:00", "Planning")], [commit()]), 0)
        estimates = [r for r in self.rows() if r["time_basis"] == "estimated"]
        self.assertEqual(len(estimates), 1)
        self.assertEqual(estimates[0]["sources"]["calendar"], [])
        self.assertEqual(estimates[0]["sources"]["commits"][0]["hash"], "test-commit")
        self.assertIn("(estimated)", (self.output / f"{DATE}.md").read_text())
        self.assertEqual(sum(p["time_basis"] == "estimated" for p in json.loads(self.ai.read_text())), 1)

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


if __name__ == "__main__":
    unittest.main()
