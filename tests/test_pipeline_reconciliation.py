"""F02 pipeline boundary tests; synthetic collectors are confined to temporary storage."""
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
from test_daily_reconciliation import DATE, row


class TestPipelineReconciliation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.output = self.directory / "timesheets"
        self.output.mkdir()
        self.json = self.output / f"{DATE}.json"
        self.md = self.output / f"{DATE}.md"
        self.manifest = self.output / f"{DATE}.collection.json"
        self.ai = self.directory / "ai.json"
        self.ai.write_text("ORIGINAL AI")
        self.config = self.directory / "profile.json"
        self.config.write_text(json.dumps({"repositories": ["test/project"],
            "author": {"names": ["Test Author"]}, "github": {"users": ["test-user"]},
            "timezone": "Asia/Ho_Chi_Minh"}))

    def pipeline(self, blocks=None, calendar_status="success", demo=False):
        def collector(command, source, mode):
            return {"source": source, "mode": mode,
                    "status": calendar_status if source == "google_calendar" else "success", "items": []}
        args = ["run_pipeline.py", "--date", DATE, "--config", str(self.config),
                "--output-dir", str(self.output), "--export-ai-input", str(self.ai)]
        if demo:
            args += ["--calendar-fixture", "EXPLICIT SYNTHETIC TEST FIXTURE"]
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        cwd = Path.cwd()
        try:
            os.chdir(self.directory)
            with patch.object(sys, "argv", args), patch("run_pipeline.run_source_collector", side_effect=collector), \
                    patch("build_time_blocks.build_time_blocks", return_value=blocks or []), \
                    contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
                return run()
        finally:
            os.chdir(cwd)

    def block(self, start, end, minutes):
        return {"date": DATE, "start_time": start, "end_time": end,
                "duration_minutes": minutes, "calendar_titles": ["Test meeting"], "commits": [], "prs": []}

    def protected(self):
        return {p: p.read_bytes() for p in (self.json, self.md, self.manifest, self.ai,
                                            self.directory / "data/token-usage.csv")}

    def assert_preserved(self, original):
        for path, content in original.items():
            self.assertEqual(path.read_bytes(), content, str(path))

    def test_complete_pipeline_split_reconciles_and_reports_removed_row(self):
        self.assertEqual(self.pipeline([self.block("09:00", "12:00", 180)]), 0)
        self.assertEqual(self.pipeline([self.block("09:00", "09:30", 30), self.block("09:30", "12:00", 150)]), 0)
        records = json.loads(self.json.read_text())
        self.assertEqual(len(records), 2)
        self.assertEqual(sum(x["entry"]["duration_minutes"] for x in records), 180)
        self.assertTrue(all(x["provenance"]["kind"] == "generated" for x in records))
        self.assertIn("Removed: 1", self.stdout.getvalue())

    def test_complete_empty_pipeline_clears_prior_generated_rows_and_records_success(self):
        self.assertEqual(self.pipeline([self.block("09:00", "12:00", 180)]), 0)
        self.assertEqual(self.pipeline(), 0)
        self.assertEqual(json.loads(self.json.read_text()), [])
        self.assertEqual(json.loads(self.manifest.read_text())["status"], "complete")
        self.assertEqual(json.loads(self.ai.read_text())["blocks"], [])

    def test_source_failure_does_not_clear_previously_generated_rows(self):
        self.assertEqual(self.pipeline([self.block("09:00", "12:00", 180)]), 0)
        original = self.protected()
        self.assertEqual(self.pipeline(calendar_status="error"), 2)
        self.assert_preserved(original)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["collection"]["status"], "incomplete")

    def test_legacy_conflict_preserves_final_manifest_ai_and_token_files(self):
        self.assertEqual(self.pipeline([self.block("09:00", "12:00", 180)]), 0)
        self.json.write_text(json.dumps([row()]))
        original = self.protected()
        self.assertEqual(self.pipeline(), 2)
        self.assert_preserved(original)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["collection"]["status"], "complete")  # sources succeeded; storage did not
        self.assertEqual(draft["reconciliation"]["status"], "blocked")
        self.assertEqual(draft["proposed_entries"], [])
        self.assertIn("RECONCILIATION BLOCKED", self.stderr.getvalue())
        self.assertNotIn("successfully completed", self.stdout.getvalue())

    def test_manual_overlap_writes_review_draft_without_replacing_files(self):
        self.assertEqual(self.pipeline([self.block("09:00", "12:00", 180)]), 0)
        self.json.write_text(json.dumps([row("10:00", "11:00", 60, kind="manual")]))
        original = self.protected()
        self.assertEqual(self.pipeline([self.block("09:00", "12:00", 180)]), 2)
        self.assert_preserved(original)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(len(draft["proposed_entries"]), 1)
        self.assertIn("overlaps", draft["reconciliation"]["reason"])

    def test_demo_empty_rerun_only_clears_demo_generated_rows(self):
        self.assertEqual(self.pipeline([self.block("09:00", "12:00", 180)]), 0)
        original = self.protected()
        self.assertEqual(self.pipeline([self.block("09:00", "12:00", 180)], demo=True), 0)
        self.assertEqual(self.pipeline(demo=True), 0)
        self.assertEqual(json.loads((self.output / "demo" / f"{DATE}.json").read_text()), [])
        self.assert_preserved(original)


if __name__ == "__main__":
    unittest.main()
