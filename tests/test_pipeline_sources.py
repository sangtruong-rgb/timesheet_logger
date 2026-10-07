"""Subprocess regressions for F01 source provenance and protected final outputs."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATE = "2026-10-06"


class TestPipelineSources(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.output = self.cwd / "data/timesheets"
        self.output.mkdir(parents=True)
        self.ai_path = self.cwd / "data/raw/ai_input.json"
        self.ai_path.parent.mkdir(parents=True)
        self.ai_path.write_text("EXISTING AI INPUT")
        self.token_path = self.cwd / "data/token-usage.csv"
        self.token_path.write_text("EXISTING TOKEN RECORDS")
        self.final_json = self.output / f"{DATE}.json"
        self.final_md = self.output / f"{DATE}.md"
        self.final_json.write_text('[{"entry":{"description":"Existing final record"}}]')
        self.final_md.write_text("EXISTING FINAL MARKDOWN")
        self.protected = {p: p.read_bytes() for p in (self.ai_path, self.token_path, self.final_json, self.final_md)}
        fixtures = self.cwd / "data/fixtures"
        fixtures.mkdir()
        for name in ("sample_prs.json", "sample_calendar.json"):
            shutil.copyfile(ROOT / "data/fixtures" / name, fixtures / name)
        self.config = self.cwd / "config.json"
        self.config.write_text(json.dumps({"author": {"names": ["Test User"]}, "timezone": "Asia/Ho_Chi_Minh"}))
        self.env = dict(os.environ, TZ="Asia/Ho_Chi_Minh", PATH="/usr/bin:/bin")
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITLAB_TOKEN", "PYTHONPATH"):
            self.env.pop(name, None)

    def run_pipeline(self, *extra, export=True):
        command = [sys.executable, str(ROOT / "scripts/run_pipeline.py"),
                   "--config", str(self.config), "--date", DATE, "--repos", str(self.cwd / "missing-repo"),
                   "--output-dir", str(self.output)]
        if export:
            command.extend(["--export-ai-input", str(self.ai_path)])
        return subprocess.run(command + list(extra), cwd=self.cwd, env=self.env,
                              capture_output=True, text=True, timeout=30)

    def assert_final_outputs_unchanged(self):
        for path, original in self.protected.items():
            self.assertEqual(path.read_bytes(), original, str(path))

    def test_default_unavailable_sources_create_only_incomplete_activity_draft(self):
        response = self.run_pipeline()
        self.assertEqual(response.returncode, 2, response.stderr)
        self.assertIn("INCOMPLETE", response.stdout)
        self.assertIn("unavailable", response.stderr)
        self.assertNotIn("successfully completed", response.stdout)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["collection"]["status"], "incomplete")
        self.assertEqual(draft["activity"]["pull_requests"], [])
        self.assertEqual(draft["activity"]["calendar"], [])
        self.assertIn("INCOMPLETE", (self.output / "drafts" / f"{DATE}.md").read_text())
        self.assert_final_outputs_unchanged()

    def test_fixture_demo_is_isolated_labelled_and_exact_rerun_is_idempotent(self):
        args = ["--prs-fixture", str(ROOT / "data/fixtures/sample_prs.json"),
                "--calendar-fixture", str(ROOT / "data/fixtures/sample_calendar.json")]
        first = self.run_pipeline(*args)
        second = self.run_pipeline(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("DEMO completed", second.stdout)
        self.assertIn("Inserted: 0, Updated: 0", second.stdout)
        records = json.loads((self.output / "demo" / f"{DATE}.json").read_text())
        self.assertTrue(records)
        self.assertTrue(all(record["collection"]["status"] == "demo" for record in records))
        self.assertEqual(records[0]["collection"]["sources"]["pull_requests"]["mode"], "fixture")
        self.assertIn("DEMO:", (self.output / "demo" / f"{DATE}.md").read_text())
        self.assertTrue((self.ai_path.parent / "demo" / self.ai_path.name).exists())
        self.assert_final_outputs_unchanged()

    def test_one_fixture_does_not_fill_missing_other_source(self):
        response = self.run_pipeline("--prs-fixture", str(ROOT / "data/fixtures/sample_prs.json"))
        self.assertEqual(response.returncode, 2, response.stderr)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(len(draft["activity"]["pull_requests"]), 2)
        self.assertEqual(draft["activity"]["calendar"], [])
        self.assertEqual(draft["collection"]["sources"]["calendar"]["status"], "unavailable")
        self.assert_final_outputs_unchanged()

    def test_missing_explicit_fixture_produces_error_not_demo_data(self):
        response = self.run_pipeline("--prs-fixture", str(self.cwd / "missing.json"),
                                     "--calendar-fixture", str(ROOT / "data/fixtures/sample_calendar.json"))
        self.assertEqual(response.returncode, 2, response.stderr)
        draft = json.loads((self.output / "drafts" / f"{DATE}.json").read_text())
        self.assertEqual(draft["collection"]["sources"]["pull_requests"]["status"], "error")
        self.assertEqual(draft["activity"]["pull_requests"], [])
        self.assertFalse((self.output / "demo").exists())
        self.assert_final_outputs_unchanged()

    def test_genuine_empty_live_sources_are_success_without_sample_data(self):
        # Local API/CLI stand-ins exercise the real collectors and orchestrator.
        binary = self.cwd / "bin"
        binary.mkdir()
        gh = binary / "gh"
        gh.write_text(f"#!{sys.executable}\nimport sys\nif sys.argv[1] == 'api': print('[]')\n")
        gh.chmod(0o755)
        # Set an explicit remote slug only for this empty-live-source test.
        self.config.write_text(json.dumps({"author": {"names": ["Test User"]}, "github": {"users": ["test-user"]}, "timezone": "Asia/Ho_Chi_Minh"}))
        self.env["PATH"] = str(binary) + os.pathsep + self.env["PATH"]
        packages = self.cwd / "packages"
        for package in ("google", "google/oauth2", "googleapiclient"):
            directory = packages / package
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "__init__.py").write_text("")
        (packages / "google/oauth2/credentials.py").write_text(
            "class Credentials:\n    @classmethod\n    def from_authorized_user_file(cls, *args): return cls()\n")
        (packages / "googleapiclient/discovery.py").write_text(
            "class Service:\n    def events(self): return self\n    def list(self, **kwargs): return self\n"
            "    def execute(self): return {'items': []}\ndef build(*args, **kwargs): return Service()\n")
        self.env["PYTHONPATH"] = str(packages)
        (self.cwd / "token.json").write_text("{}")
        # No existing record on this day: test empty-source semantics, not F02.
        self.final_json.unlink()
        self.final_md.unlink()
        self.token_path.unlink()
        response = self.run_pipeline("--repos", "example/empty", export=False)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertIn("successfully completed", response.stdout)
        manifest = json.loads((self.output / f"{DATE}.collection.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        for source in manifest["sources"].values():
            self.assertEqual((source["mode"], source["status"], source["count"]), ("live", "success", 0))
        self.assertEqual(json.loads(self.final_json.read_text()), [])
        self.assertIn("**Total Tracked Time:** 0 mins", self.final_md.read_text())
        self.assertFalse((self.output / "demo").exists())
        self.assertFalse((self.output / "drafts").exists())

    def test_standalone_collector_envelope_normalizes_with_provenance(self):
        collector = subprocess.run(
            [sys.executable, str(ROOT / "scripts/get_pr_activity.py"), "--date", DATE,
             "--fixture", str(ROOT / "data/fixtures/sample_prs.json")],
            cwd=self.cwd, env=self.env, capture_output=True, text=True, timeout=30)
        self.assertEqual(collector.returncode, 0, collector.stderr)
        path = self.cwd / "prs.json"
        path.write_text(collector.stdout)
        normalized = subprocess.run(
            [sys.executable, str(ROOT / "scripts/normalize_activity.py"), "--date", DATE,
             "--prs-file", str(path)], cwd=self.cwd, env=self.env,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(normalized.returncode, 0, normalized.stderr)
        data = json.loads(normalized.stdout)
        self.assertEqual(len(data["pull_requests"]), 2)
        self.assertEqual(data["collection_sources"]["pull_requests"]["mode"], "fixture")

    def test_standalone_normalizer_rejects_unavailable_source(self):
        path = self.cwd / "prs.json"
        path.write_text(json.dumps({"source": "github", "mode": "live",
                                    "status": "unavailable", "items": []}))
        response = subprocess.run(
            [sys.executable, str(ROOT / "scripts/normalize_activity.py"), "--date", DATE,
             "--prs-file", str(path)], cwd=self.cwd, env=self.env,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(response.returncode, 2)
        self.assertIn("not successful", response.stderr)
        self.assertEqual(response.stdout, "")


if __name__ == "__main__":
    unittest.main()
