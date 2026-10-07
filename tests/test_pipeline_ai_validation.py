"""F03 pipeline tests with explicitly synthetic source/block inputs in temp storage."""

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
from test_ai_block_matching import DATE, WORK_ID, MEETING_ID, candidate_blocks


class TestPipelineAIValidation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.output = self.directory / "timesheets"
        self.output.mkdir()
        self.final = self.output / f"{DATE}.json"
        self.md = self.output / f"{DATE}.md"
        self.manifest = self.output / f"{DATE}.collection.json"
        self.export = self.directory / "ai-input.json"
        self.token = self.directory / "data/token-usage.csv"
        self.token.parent.mkdir()
        self.token.write_text("OLD TOKEN RECORDS")
        for path in (self.final, self.md, self.manifest, self.export):
            path.write_text("PROTECTED OLD CONTENT")
        self.original = {p: p.read_bytes() for p in (self.final, self.md, self.manifest, self.export, self.token)}
        self.ai = self.directory / "judgments.json"
        self.config = self.directory / "profile.json"
        self.config.write_text(json.dumps({"repositories": ["test/project"], "author": {"names": ["Test User"]},
            "github": {"users": ["test-user"]}, "timezone": "Asia/Ho_Chi_Minh"}))

    def pipeline(self, blocks=None):
        def collector(command, source, mode):
            return {"source": source, "mode": mode, "status": "success", "items": []}
        args = ["run_pipeline.py", "--date", DATE, "--config", str(self.config),
                "--output-dir", str(self.output), "--export-ai-input", str(self.export), "--ai-output", str(self.ai)]
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        previous = Path.cwd()
        try:
            os.chdir(self.directory)
            with patch.object(sys, "argv", args), patch("run_pipeline.run_source_collector", side_effect=collector), \
                    patch("build_time_blocks.build_time_blocks", return_value=blocks if blocks is not None else candidate_blocks()), \
                    contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
                return run()
        finally:
            os.chdir(previous)

    def assert_blocked(self):
        self.assertEqual(self.pipeline(), 2)
        for path, before in self.original.items():
            self.assertEqual(path.read_bytes(), before, str(path))
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["collection"]["status"], "complete")
        self.assertEqual(draft["ai_validation"]["status"], "error")
        self.assertEqual([p["block_id"] for p in draft["ai_input"]["blocks"]], [WORK_ID])
        self.assertIn("AI VALIDATION BLOCKED", self.stderr.getvalue())
        self.assertNotIn("successfully completed", self.stdout.getvalue())

    def test_unknown_id_preserves_timesheet_manifest_export_and_token(self):
        self.ai.write_text(json.dumps([{"block_id": "unknown", "description": "Wrong"}]))
        self.assert_blocked()

    def test_duplicate_summary_preserves_previous_files(self):
        self.ai.write_text(json.dumps([{"block_id": WORK_ID, "description": "One"}, {"block_id": WORK_ID, "description": "Two"}]))
        self.assert_blocked()

    def test_wrong_day_preserves_previous_files(self):
        self.ai.write_text(json.dumps([{"date": "2026-10-05", "block": {"start": "09:30", "end": "12:00"}, "description": "Stale"}]))
        self.assert_blocked()

    def test_missing_requested_ai_file_preserves_previous_files(self):
        self.assert_blocked()

    def test_invalid_json_preserves_previous_files(self):
        self.ai.write_text("INVALID JSON")
        self.assert_blocked()

    def test_json_null_does_not_silently_become_fallback(self):
        self.ai.write_text("null")
        self.assert_blocked()

    def test_partial_keyed_response_saves_correct_own_descriptions_and_ids(self):
        self.final.unlink(); self.md.unlink(); self.token.unlink()
        self.ai.write_text(json.dumps([{"block_id": WORK_ID, "description": "AI payment summary"}]))
        self.assertEqual(self.pipeline(), 0, self.stderr.getvalue())
        entries = json.loads(self.final.read_text())
        self.assertEqual([e["summary_source"] for e in entries], ["fallback", "ai"])
        self.assertNotIn("AI payment summary", entries[0]["entry"]["description"])
        self.assertIn("AI payment summary", entries[1]["entry"]["description"])
        self.assertEqual([p["block_id"] for p in json.loads(self.export.read_text())["blocks"]], [entries[1]["block_id"]])
        self.assertEqual(entries[1]["sources"]["commits"][0]["hash"], "audit-sha")

    def test_duplicate_candidates_block_before_any_final_write(self):
        self.ai.write_text("[]")
        self.assertEqual(self.pipeline([candidate_blocks()[0]] * 2), 2)
        for path, before in self.original.items():
            self.assertEqual(path.read_bytes(), before)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["ai_validation"]["status"], "error")


if __name__ == "__main__":
    unittest.main()
