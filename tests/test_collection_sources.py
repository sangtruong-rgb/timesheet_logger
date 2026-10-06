"""F01 regressions: empty live sources are not failures or demo fixtures."""

import datetime
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from get_pr_activity import collect_pr_activity
from get_calendar_activity import collect_calendar_activity
from run_pipeline import run_source_collector

DATE = datetime.date(2026, 10, 6)
TZ = datetime.timezone(datetime.timedelta(hours=7))


class TestCollectionSources(unittest.TestCase):
    def test_empty_live_prs_do_not_load_fixture(self):
        with patch("get_pr_activity.check_gh_cli", return_value=True), \
                patch("get_pr_activity.subprocess.run", return_value=Mock(returncode=0, stdout="[]")) as query, \
                patch("get_pr_activity.load_fixture") as fixture:
            result = collect_pr_activity(DATE)
        self.assertEqual(result, {"source": "github", "mode": "live", "status": "success", "items": []})
        self.assertEqual(query.call_count, 3)
        fixture.assert_not_called()

    def test_missing_gh_is_unavailable_without_fixture(self):
        with patch("get_pr_activity.shutil.which", return_value=None), \
                patch("get_pr_activity.load_fixture") as fixture:
            result = collect_pr_activity(DATE)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["items"], [])
        fixture.assert_not_called()

    def test_unauthenticated_gh_is_unavailable(self):
        with patch("get_pr_activity.shutil.which", return_value="gh"), \
                patch("get_pr_activity.subprocess.run", return_value=Mock(returncode=1)) as cli:
            result = collect_pr_activity(DATE)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(cli.call_count, 1)

    def test_partial_pr_query_failure_is_not_success(self):
        opened = Mock(returncode=0, stdout=json.dumps([{"number": 7, "title": "Real PR"}]))
        failed = Mock(returncode=1, stdout="", stderr="query failed")
        with patch("get_pr_activity.check_gh_cli", return_value=True), \
                patch("get_pr_activity.subprocess.run", side_effect=[opened, failed]), \
                patch("get_pr_activity.load_fixture") as fixture:
            result = collect_pr_activity(DATE)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["items"], [])
        fixture.assert_not_called()

    def test_invalid_live_pr_response_is_error(self):
        for response in ("not json", "{}", "[null]", "[{}]", ""):
            with self.subTest(response=response), \
                    patch("get_pr_activity.check_gh_cli", return_value=True), \
                    patch("get_pr_activity.subprocess.run", return_value=Mock(returncode=0, stdout=response)):
                self.assertEqual(collect_pr_activity(DATE)["status"], "error")

    def test_explicit_pr_fixture_is_labelled_and_does_not_query_live(self):
        with patch("get_pr_activity.get_local_timezone", return_value=TZ), \
                patch("get_pr_activity.check_gh_cli") as auth:
            result = collect_pr_activity(DATE, str(ROOT / "data/fixtures/sample_prs.json"))
        self.assertEqual(result["mode"], "fixture")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["items"]), 2)
        auth.assert_not_called()

    def test_empty_live_calendar_does_not_load_fixture(self):
        with patch("get_calendar_activity.fetch_google_calendar_events", return_value=[]), \
                patch("get_calendar_activity.load_calendar_fixture") as fixture:
            result = collect_calendar_activity(DATE)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["mode"], "live")
        self.assertEqual(result["items"], [])
        fixture.assert_not_called()

    def test_missing_calendar_token_is_unavailable(self):
        with patch("get_calendar_activity.os.path.exists", return_value=False), \
                patch("get_calendar_activity.load_calendar_fixture") as fixture:
            result = collect_calendar_activity(DATE)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["items"], [])
        fixture.assert_not_called()

    def test_missing_calendar_library_is_unavailable(self):
        import builtins
        original_import = builtins.__import__

        def import_without_google(name, *args, **kwargs):
            if name.startswith("google"):
                raise ImportError("not installed")
            return original_import(name, *args, **kwargs)

        with patch("get_calendar_activity.os.path.exists", return_value=True), \
                patch("builtins.__import__", side_effect=import_without_google):
            result = collect_calendar_activity(DATE)
        self.assertEqual(result["status"], "unavailable")

    def test_calendar_request_failure_is_error_without_fixture(self):
        with patch("get_calendar_activity.fetch_google_calendar_events", side_effect=RuntimeError("API failed")), \
                patch("get_calendar_activity.load_calendar_fixture") as fixture:
            result = collect_calendar_activity(DATE)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["items"], [])
        fixture.assert_not_called()

    def test_explicit_calendar_fixture_is_labelled_and_does_not_query_live(self):
        with patch("get_calendar_activity.get_local_timezone", return_value=TZ), \
                patch("get_calendar_activity.fetch_google_calendar_events") as live:
            result = collect_calendar_activity(DATE, str(ROOT / "data/fixtures/sample_calendar.json"))
        self.assertEqual(result["mode"], "fixture")
        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["items"]), 4)
        live.assert_not_called()

    def test_missing_or_malformed_explicit_fixtures_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fixture.json"
            for collector in (collect_pr_activity, collect_calendar_activity):
                with self.subTest(collector=collector.__name__, data="missing"):
                    self.assertEqual(collector(DATE, str(path))["status"], "error")
                for content in ("invalid", "{}", "[null]", "[{}]"):
                    path.write_text(content)
                    with self.subTest(collector=collector.__name__, data=content):
                        result = collector(DATE, str(path))
                        self.assertEqual(result["status"], "error")
                        self.assertEqual(result["mode"], "fixture")
                        self.assertEqual(result["items"], [])
                path.unlink()

    def test_explicit_empty_fixture_is_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text("[]")
            for collector in (collect_pr_activity, collect_calendar_activity):
                with self.subTest(collector=collector.__name__):
                    result = collector(DATE, str(path))
                    self.assertEqual(result["status"], "success")
                    self.assertEqual(result["mode"], "fixture")
                    self.assertEqual(result["items"], [])

    def test_pipeline_rejects_failed_process_even_if_it_claims_success(self):
        response = Mock(returncode=1, stderr="failure details", stdout=json.dumps(
            {"source": "github", "mode": "live", "status": "success", "items": []}))
        with patch("run_pipeline.subprocess.run", return_value=response), \
                patch("sys.stderr") as stderr:
            result = run_source_collector(["collector"], "github", "live")
        self.assertEqual(result["status"], "error")
        self.assertTrue(stderr.write.called)

    def test_pipeline_rejects_legacy_list_instead_of_guessing_source(self):
        with patch("run_pipeline.subprocess.run", return_value=Mock(returncode=0, stderr="", stdout="[]")):
            self.assertEqual(run_source_collector(["collector"], "github", "live")["status"], "error")


if __name__ == "__main__":
    unittest.main()
