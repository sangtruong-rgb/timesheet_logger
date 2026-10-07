"""R02 regressions: actual subprocesses/files, isolated synthetic evidence only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from activity_snapshot import save_snapshot, read_snapshot, SnapshotError
from build_time_blocks import build_time_blocks
from normalize_activity import normalize_all
from prepare_ai_input import prepare_activity_input
from run_pipeline import check_ai_export
from output_paths import OutputPathError
from save_timesheet import save_timesheet, TimesheetReconciliationError


class TestOutputPathProtection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="output path audit ")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.output = self.directory / "timesheets"
        self.snapshot = self.directory / "activity.json"
        self.model = normalize_all("2026-10-07", [], [], [], "Asia/Ho_Chi_Minh")
        self.review = []
        self.blocks = build_time_blocks(self.model, unassigned_activity=self.review)
        self.payload = prepare_activity_input(self.blocks, self.review)
        self.collection = {"status": "complete", "sources": {}}
        save_snapshot(self.snapshot, self.model, self.collection, self.blocks, self.review, self.payload)
        self.env = dict(os.environ)
        for name in ("GOOGLE_CALENDAR_TOKEN", "GOOGLE_CALENDAR_CREDENTIALS", "TIMESHEET_TOKEN_CSV", "PYTHONPATH"):
            self.env.pop(name, None)

    def file_bytes(self):
        return {str(p.relative_to(self.directory)): p.read_bytes()
                for p in self.directory.rglob("*") if p.is_file()}

    def invoke(self, export, *extra, phase="assemble", env=None):
        return subprocess.run([sys.executable, str(ROOT / "scripts/run_pipeline.py"),
            "--phase", phase, "--snapshot", str(self.snapshot), "--output-dir", str(self.output),
            "--export-ai-input", str(export), *extra], cwd=self.directory, env=env or self.env,
            capture_output=True, text=True, timeout=30)

    def assert_blocked(self, export, *extra, **kwargs):
        before = self.file_bytes()
        response = self.invoke(export, *extra, **kwargs)
        self.assertEqual(response.returncode, 2, response.stderr)
        self.assertIn("OUTPUT PATH BLOCKED", response.stderr)
        self.assertIn("choose a different output path", response.stderr)
        self.assertNotIn("Collecting", response.stdout)
        self.assertEqual(self.file_bytes(), before)
        self.assertFalse((self.output / ".timesheet-transaction.json").exists())
        read_snapshot(self.snapshot)

    def test_assemble_export_cannot_replace_snapshot(self):
        self.assert_blocked(self.snapshot)

    def test_relative_alias_cannot_replace_snapshot(self):
        (self.directory / "subdirectory").mkdir()
        self.assert_blocked(Path("subdirectory") / ".." / self.snapshot.name)

    def test_symlink_alias_cannot_replace_snapshot(self):
        alias = self.directory / "alias.json"; alias.symlink_to(self.snapshot)
        self.assert_blocked(alias)
        self.assertTrue(alias.is_symlink())

    def test_hardlink_alias_cannot_replace_snapshot(self):
        alias = self.directory / "hardlink.json"; os.link(self.snapshot, alias)
        self.assert_blocked(alias)

    def test_any_date_store_and_sidecar_preserved_in_another_directory(self):
        old = self.directory / "other project"; old.mkdir()
        for date in ("2026-10-06", "2026-10-08"):
            for suffix in ("json", "md", "collection.json", "calendar-context.json", "activity-review.json"):
                with self.subTest(date=date, suffix=suffix):
                    target = old / f"{date}.{suffix}"; target.write_text("corrupt original still must be preserved")
                    self.assert_blocked(target)

    def test_new_daily_store_name_is_reserved_before_it_exists(self):
        target = self.output / "2026-10-06.json"
        self.assert_blocked(target)
        self.assertFalse(target.exists())
        self.assertFalse(self.output.exists())

    def test_ai_judgments_and_profile_inputs_preserved(self):
        for flag, name in (("--ai-output", "judgments.json"), ("--config", "profile.json"),
                           ("--prs-fixture", "prs.json"), ("--calendar-fixture", "calendar.json")):
            with self.subTest(flag=flag):
                target = self.directory / name; target.write_text("[]" if flag == "--ai-output" else "{}")
                self.assert_blocked(target, flag, str(target))

    def test_configured_oauth_and_usage_paths_preserved(self):
        profile = self.directory / "profile.json"
        for section, field in (("calendar", "token_path"), ("calendar", "credentials_path"), ("token_tracking", "csv_path")):
            with self.subTest(section=section, field=field):
                target = self.directory / "custom-file.json"; target.write_text("{}")
                profile.write_text(json.dumps({section: {field: target.name}}))
                self.assert_blocked(target, "--config", str(profile))
        for flag in ("--calendar-token", "--calendar-credentials"):
            target = self.directory / "custom-oauth.json"; target.write_text("{}")
            tilde_path = "~/" + os.path.relpath(target, Path.home())
            self.assert_blocked(target, flag, tilde_path)

    def test_actual_environment_oauth_and_usage_paths_preserved(self):
        for name in ("GOOGLE_CALENDAR_TOKEN", "GOOGLE_CALENDAR_CREDENTIALS", "TIMESHEET_TOKEN_CSV"):
            with self.subTest(environment=name):
                target = self.directory / "environment-input.json"; target.write_text("{}")
                env = dict(self.env, **{name: str(target)})
                self.assert_blocked(target, env=env)

    def test_renamed_snapshot_not_current_input_is_preserved(self):
        older = self.directory / "older-evidence.json"; older.write_bytes(self.snapshot.read_bytes())
        self.assert_blocked(older)

    def test_renamed_daily_store_is_preserved(self):
        target = self.directory / "backup.json"
        target.write_text(json.dumps([{"entry": {"date": "2026-10-06", "description": "manual"}}]))
        self.assert_blocked(target)

    def test_prepare_collision_blocks_before_invalid_source_config(self):
        self.assert_blocked(self.snapshot, "--config", str(self.directory / "missing-profile.json"), phase="prepare")

    def test_prepare_export_cannot_replace_other_day_store(self):
        target = self.directory / "2026-10-06.md"; target.write_text("original")
        self.assert_blocked(target, phase="prepare")

    def test_standalone_timesheet_writer_blocks_other_day_before_lock_or_write(self):
        target = self.directory / "2026-10-06.json"; target.write_text("[]")
        before = self.file_bytes()
        with self.assertRaises(TimesheetReconciliationError):
            save_timesheet([], self.output, target_date="2026-10-07", collection_status="complete", extra_files={target: "wrong"})
        self.assertEqual(self.file_bytes(), before)
        self.assertFalse(self.output.exists())

    def test_standalone_snapshot_writer_blocks_other_day_export(self):
        target = self.directory / "2026-10-06.json"; target.write_text("[]")
        before = self.file_bytes()
        with self.assertRaises(SnapshotError):
            save_snapshot(self.directory / "new" / "snapshot.json", self.model, self.collection,
                self.blocks, self.review, self.payload, target)
        self.assertEqual(self.file_bytes(), before)
        self.assertFalse((self.directory / "new").exists())

    def test_usage_manifest_and_referenced_transcript_are_protected(self):
        transcript = self.directory / "usage.jsonl"; transcript.write_text("synthetic usage")
        manifest = self.directory / "usage-manifest.json"
        manifest.write_text(json.dumps({"session_file": transcript.name}))
        args = SimpleNamespace(config=None, usage_run_manifest=str(manifest))
        before = self.file_bytes()
        for path in (manifest, transcript):
            with self.subTest(path=path.name), self.assertRaises(OutputPathError):
                check_ai_export(args, path)
            if (ROOT / "scripts/token_settings.py").exists():
                self.assert_blocked(path, "--usage-run-manifest", str(manifest))
        self.assert_blocked(transcript)  # Session-ID lookup transcripts are JSONL too.
        self.assertEqual(self.file_bytes(), before)

    def test_valid_export_and_exact_rerun_still_succeed(self):
        export = self.directory / "AI folder" / "ai-input.json"
        first = self.invoke(export)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(json.loads(export.read_text()), self.payload)
        before = self.file_bytes()
        again = self.invoke(export)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.file_bytes(), before)
        read_snapshot(self.snapshot)


if __name__ == "__main__":
    unittest.main()
