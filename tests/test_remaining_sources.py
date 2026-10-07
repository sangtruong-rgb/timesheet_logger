"""Source pagination, qualified evidence, config precedence and rendering regressions."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from get_calendar_activity import fetch_google_calendar_events
from get_git_activity import get_commits_for_repo, fetch_github_api_commits
from normalize_activity import normalize_all
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries, format_pr_suffix
from prepare_ai_input import prepare_ai_payload_for_block
from save_timesheet import render_markdown

DAY = datetime.date(2026, 10, 7)
ZONE = ZoneInfo("Asia/Ho_Chi_Minh")


def raw_event(identity="a", title="Planning"):
    return {"id": identity, "summary": title, "start": {"dateTime": "2026-10-07T09:00:00+07:00"},
            "end": {"dateTime": "2026-10-07T10:00:00+07:00"}}


class TestRemainingSources(unittest.TestCase):
    def configuration_in_subprocess(self, config, *, environment=None, calendar_args=None, repos=None, cwd=None):
        """Exercise os.environ in a fresh interpreter, without patching settings."""
        env = dict(os.environ)
        for name in ("GOOGLE_CALENDAR_TOKEN", "GOOGLE_CALENDAR_CREDENTIALS", "TIMESHEET_REPOS", "PYTHONPATH"):
            env.pop(name, None)
        env.update(environment or {})
        script = (
            "import json,sys;sys.path.insert(0,sys.argv[1]);"
            "from calendar_settings import calendar_settings;"
            "from activity_settings import load_config,settings;"
            "args=json.load(sys.stdin);"
            "print(json.dumps({'calendar':calendar_settings(args['config'],**args['calendar']),"
            "'repositories':settings(load_config(args['config']),repos=args['repos'])['repos']}))"
        )
        result = subprocess.run([sys.executable, "-c", script, str(ROOT / "scripts")],
            input=json.dumps({"config": str(config), "calendar": calendar_args or {}, "repos": repos}),
            env=env, cwd=cwd, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def fake_google(self, responses):
        service = Mock()
        service.events.return_value.list.return_value.execute.side_effect = responses
        modules = {name: types.ModuleType(name) for name in
                   ("google", "google.oauth2", "google.oauth2.credentials", "googleapiclient", "googleapiclient.discovery")}
        modules["google.oauth2.credentials"].Credentials = Mock()
        modules["googleapiclient.discovery"].build = Mock(return_value=service)
        return modules, service

    def fetch(self, responses, calendars=None):
        modules, service = self.fake_google(responses)
        with patch.dict(sys.modules, modules), patch("get_calendar_activity.os.path.exists", return_value=True):
            result = fetch_google_calendar_events(DAY, tz=ZONE, calendar_ids=calendars)
        return result, service

    def test_calendar_fetches_later_pages_with_same_query(self):
        result, service = self.fetch([{"items": [raw_event()], "nextPageToken": "two"}, {"items": [raw_event("b")]}])
        self.assertEqual([r["event_id"] for r in result], ["a", "b"])
        calls = service.events.return_value.list.call_args_list
        self.assertEqual(calls[1].kwargs, {**calls[0].kwargs, "pageToken": "two"})

    def test_empty_first_page_with_token_still_fetches_next(self):
        result, _ = self.fetch([{"items": [], "nextPageToken": "two"}, {"items": [raw_event()]}])
        self.assertEqual(len(result), 1)

    def test_repeated_page_token_reports_failure(self):
        with self.assertRaises(ValueError):
            self.fetch([{"items": [], "nextPageToken": "same"}, {"items": [], "nextPageToken": "same"}])

    def test_failed_later_page_does_not_return_partial_success(self):
        with self.assertRaises(RuntimeError):
            self.fetch([{"items": [raw_event()], "nextPageToken": "two"}, RuntimeError("API failed")])

    def test_multiple_calendars_keep_qualified_event_identity(self):
        result, _ = self.fetch([{"items": [raw_event()]}, {"items": [raw_event()]}], ["primary", "project"])
        self.assertEqual({(r["calendar_id"], r["event_id"]) for r in result}, {("primary", "a"), ("project", "a")})
        model = normalize_all(str(DAY), [], [], result, ZONE.key)
        self.assertEqual(len(model["calendar"]), 2)

    def test_same_looking_different_event_ids_survive_to_saved_evidence(self):
        events, _ = self.fetch([{"items": [raw_event("a"), raw_event("b")]}])
        model = normalize_all(str(DAY), [], [], events, ZONE.key)
        rows = build_entries(build_time_blocks(model))
        self.assertEqual({e["event_id"] for e in rows[0]["sources"]["calendar_events"]}, {"a", "b"})
        self.assertTrue(rows[0]["calendar_overlap"])

    def test_cancelled_calendar_event_without_bounds_is_excluded(self):
        result, _ = self.fetch([{"items": [{"id": "cancelled", "status": "cancelled"}]}])
        self.assertEqual(result, [])

    def test_self_declined_excluded_but_other_attendee_declined_kept(self):
        mine = {**raw_event("mine"), "attendees": [{"self": True, "responseStatus": "declined"}]}
        other = {**raw_event("other"), "attendees": [{"self": False, "responseStatus": "declined"}]}
        result, _ = self.fetch([{"items": [mine, other]}])
        self.assertEqual([r["event_id"] for r in result], ["other"])

    def test_acceptance_is_source_evidence_not_attendance_confirmation(self):
        accepted = {**raw_event(), "attendees": [{"self": True, "responseStatus": "accepted"}]}
        result, _ = self.fetch([{"items": [accepted]}])
        model = normalize_all(str(DAY), [], [], result, ZONE.key)
        self.assertEqual(model["calendar"][0]["self_response_status"], "accepted")
        rows = build_entries(build_time_blocks(model))
        self.assertEqual(rows[0]["attendance"], "unconfirmed")
        text = render_markdown(str(DAY), rows)
        self.assertIn("Theo lịch, chưa xác nhận tham dự", text)
        self.assertIn("Total Proposed Time", text)

    def test_ambiguous_pr_suffix_qualifies_both_repositories(self):
        prs = [{"id": 1, "repository": "alice/shared"}, {"id": 1, "repository": "bob/shared"}]
        self.assertEqual(format_pr_suffix(prs), "PRs: alice/shared#1, bob/shared#1")
        payload = prepare_ai_payload_for_block({"date": str(DAY), "start_time": "09:00", "end_time": "10:00", "prs": prs})
        self.assertEqual({p["repository"] for p in payload["prs"]}, {"alice/shared", "bob/shared"})

    def test_unambiguous_suffix_remains_short_and_deduplicated(self):
        self.assertEqual(format_pr_suffix([{"id": 1, "repository": "a/repo"}]*2), "PRs: #1")

    def test_markdown_calendar_pipe_and_newline_do_not_add_cells_or_rows(self):
        event = {"title": "A | B\nC\rD", "start": "2026-10-07T09:00:00+07:00", "end": "2026-10-07T10:00:00+07:00"}
        rows = build_entries(build_time_blocks(normalize_all(str(DAY), [], [], [event], ZONE.key)))
        table = [line for line in render_markdown(str(DAY), rows).splitlines() if line.startswith("| 09:")]
        self.assertEqual(len(table), 1)
        self.assertIn("Cal: A \\| B C D", table[0])

    def test_calendar_paths_cli_environment_profile_default_precedence(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp)/"profile.json"
            config.write_text(json.dumps({"calendar": {"token_path": "profile-token.json", "credentials_path": "profile-client.json"}}))
            paths = self.configuration_in_subprocess(config)["calendar"]
            self.assertEqual(paths["token_path"], str((Path(temp)/"profile-token.json").resolve()))
            self.assertEqual(paths["credentials_path"], str((Path(temp)/"profile-client.json").resolve()))
            environment = {"GOOGLE_CALENDAR_TOKEN": str(Path(temp)/"env.json"),
                           "GOOGLE_CALENDAR_CREDENTIALS": str(Path(temp)/"env-client.json")}
            paths = self.configuration_in_subprocess(config, environment=environment)["calendar"]
            self.assertEqual(paths["token_path"], environment["GOOGLE_CALENDAR_TOKEN"])
            self.assertEqual(paths["credentials_path"], environment["GOOGLE_CALENDAR_CREDENTIALS"])
            paths = self.configuration_in_subprocess(config, environment=environment,
                calendar_args={"token": str(Path(temp)/"cli.json"), "credentials": str(Path(temp)/"cli-client.json")})["calendar"]
            self.assertEqual(paths["token_path"], str(Path(temp)/"cli.json"))
            self.assertEqual(paths["credentials_path"], str(Path(temp)/"cli-client.json"))
            config.write_text("{}")
            paths = self.configuration_in_subprocess(config, cwd=temp)["calendar"]
            self.assertEqual(paths["token_path"], str(ROOT/"token.json"))
            self.assertEqual(paths["credentials_path"], str(ROOT/"credentials.json"))

    def test_repository_environment_override_below_cli_above_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp)/"profile.json"
            config.write_text(json.dumps({"repositories": ["profile/repo"]}))
            environment = {"TIMESHEET_REPOS": "alice/repo,bob/repo"}
            self.assertEqual(self.configuration_in_subprocess(config)["repositories"], ["profile/repo"])
            self.assertEqual(self.configuration_in_subprocess(config, environment=environment)["repositories"], ["alice/repo", "bob/repo"])
            self.assertEqual(self.configuration_in_subprocess(config, environment=environment, repos=["cli/repo"])["repositories"], ["cli/repo"])

    def test_calendar_relative_environment_paths_use_invoking_directory(self):
        with tempfile.TemporaryDirectory(prefix="calendar env ") as temp:
            profile_dir = Path(temp)/"profile"; profile_dir.mkdir()
            invoking_dir = Path(temp)/"invoking project"; invoking_dir.mkdir()
            config = profile_dir/"config.json"; config.write_text("{}")
            environment = {"GOOGLE_CALENDAR_TOKEN": "secret folder/token.json",
                           "GOOGLE_CALENDAR_CREDENTIALS": "secret folder/client.json"}
            paths = self.configuration_in_subprocess(config, environment=environment, cwd=invoking_dir)["calendar"]
            self.assertEqual(paths["token_path"], str((invoking_dir/"secret folder/token.json").resolve()))
            self.assertEqual(paths["credentials_path"], str((invoking_dir/"secret folder/client.json").resolve()))

    def test_collector_missing_environment_token_does_not_fall_back_to_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp)/"profile.json"
            config.write_text(json.dumps({"calendar": {"token_path": "profile-token.json"}}))
            (Path(temp)/"profile-token.json").write_text("{}")
            env = dict(os.environ, GOOGLE_CALENDAR_TOKEN=str(Path(temp)/"missing-env-token.json"))
            env.pop("PYTHONPATH", None)
            response = subprocess.run([sys.executable, str(ROOT/"scripts/get_calendar_activity.py"),
                "--config", str(config), "--date", str(DAY)], env=env, cwd=temp,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(response.returncode, 2, response.stderr)
            envelope = json.loads(response.stdout)
            self.assertEqual((envelope["mode"], envelope["status"], envelope["items"]), ("live", "unavailable", []))

    def test_collector_empty_environment_token_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp)/"profile.json"; config.write_text("{}")
            env = dict(os.environ, GOOGLE_CALENDAR_TOKEN="")
            env.pop("PYTHONPATH", None)
            response = subprocess.run([sys.executable, str(ROOT/"scripts/get_calendar_activity.py"),
                "--config", str(config), "--date", str(DAY)], env=env, cwd=temp,
                capture_output=True, text=True, timeout=30)
            self.assertEqual(response.returncode, 2)
            self.assertIn("must be a nonempty path", response.stderr)
            self.assertEqual(response.stdout, "")

    def test_distinct_local_same_basename_has_distinct_identity_and_bound_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            repos = [Path(temp)/name/"same" for name in ("alice", "bob")]
            for repo in repos:
                repo.mkdir(parents=True)
                subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
                env = {**os.environ, "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com", "GIT_COMMITTER_NAME": "Test",
                       "GIT_COMMITTER_EMAIL": "test@example.com", "GIT_AUTHOR_DATE": "2026-10-07T09:00:00+07:00", "GIT_COMMITTER_DATE": "2026-10-07T09:00:00+07:00"}
                subprocess.run(["git", "-C", str(repo), "commit", "--allow-empty", "-qm", "work"], env=env, check=True)
            collected = [get_commits_for_repo(str(repo), DAY, "Test", ZONE)[0] for repo in repos]
            self.assertNotEqual(collected[0]["repository"], collected[1]["repository"])
            subprocess.run(["git", "-C", str(repos[0]), "commit", "--allow-empty", "-qm", "more"], env=env, check=True)
            with self.assertRaises(ValueError):
                get_commits_for_repo(str(repos[0]), DAY, "Test", ZONE, max_commits=1)

    def test_oauth_bootstrap_does_not_replace_existing_token(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/"token.json";path.write_text("private test placeholder")
            result = subprocess.run([sys.executable, str(ROOT/"scripts/setup_calendar_oauth.py"), "--calendar-token", str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_text(), "private test placeholder")
            self.assertNotIn("private test placeholder", result.stdout+result.stderr)

    def test_remote_history_uses_author_date_not_api_committer_window(self):
        api = Mock()
        api.items.return_value = iter([{"sha": "a"*40, "commit": {"author": {"name": "Test", "date": "2026-10-07T09:00:00+07:00"},
            "committer": {"date": "2026-10-06T00:00:00Z"}, "message": "backdated"}}])
        with patch("get_git_activity.GitHubAPI", return_value=api):
            records = fetch_github_api_commits("owner", "repo", DAY, "Test", ZONE)
        api.items.assert_called_once_with("repos/owner/repo/commits")
        self.assertEqual(len(records), 1)

    def test_remote_bound_exceeded_is_error_not_truncated_success(self):
        api = Mock();api.items.return_value = iter([{}, {}])
        with patch("get_git_activity.GitHubAPI", return_value=api), self.assertRaises(ValueError):
            fetch_github_api_commits("owner", "repo", DAY, tz=ZONE, max_commits=1)


if __name__ == "__main__":
    unittest.main()
