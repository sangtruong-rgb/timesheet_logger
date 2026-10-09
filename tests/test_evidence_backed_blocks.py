"""F04: unsupported calendar gaps are not work; inferred time is explicit."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from prepare_ai_input import prepare_all_blocks
from save_timesheet import render_markdown

DATE = "2026-10-06"


def event(start="09:00", end="09:30", title="Daily stand-up"):
    return {"title": title, "start": f"{DATE}T{start}:00+07:00", "end": f"{DATE}T{end}:00+07:00"}


def commit(time="10:15", sha="test-commit"):
    return {"hash": sha, "repository": "test/project", "message": "fix invoice validation",
            "timestamp": f"{DATE}T{time}:00+07:00"}


def model(calendar=None, commits=None, prs=None):
    return {"date": DATE, "timezone": "Asia/Ho_Chi_Minh", "calendar": calendar or [],
            "commits": commits or [], "pull_requests": prs or []}


class TestEvidenceBackedBlocks(unittest.TestCase):
    def test_standup_only_is_30_minutes_not_510(self):
        blocks = build_time_blocks(model([event()]))
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0]["start_time"], blocks[0]["end_time"], blocks[0]["duration_minutes"]), ("09:00", "09:30", 30))
        self.assertEqual(blocks[0]["time_basis"], "scheduled")
        entries = build_entries(blocks)
        self.assertEqual(entries[0]["entry"]["description"], "Scheduled calendar activity; attendance unconfirmed. PRs: None")

    def test_empty_gaps_before_between_and_after_events_disappear(self):
        events = [event("10:00", "10:30", "Planning"), event("14:00", "14:30", "Review meeting")]
        blocks = build_time_blocks(model(events))
        self.assertEqual(len(blocks), 2)
        self.assertEqual(sum(b["duration_minutes"] for b in blocks), 60)
        self.assertTrue(all(b["time_basis"] == "scheduled" for b in blocks))

    def test_only_gap_with_a_commit_survives(self):
        events = [event("10:00", "10:30"), event("14:00", "14:30", "Review")]
        blocks = build_time_blocks(model(events, [commit("11:00")]))
        estimated = [b for b in blocks if b["time_basis"] == "estimated"]
        self.assertEqual(len(estimated), 1)
        self.assertEqual((estimated[0]["start_time"], estimated[0]["end_time"]), ("10:30", "12:00"))
        self.assertEqual(estimated[0]["estimation_reason"], "calendar_gap_with_activity")
        self.assertEqual(estimated[0]["calendar_titles"], [])
        self.assertEqual(estimated[0]["commits"][0]["hash"], "test-commit")

    def test_pr_only_gap_is_supported_and_preserves_reference(self):
        pr = {"id": 101, "repository": "test/project", "title": "Payment fixes", "timestamp": f"{DATE}T11:00:00+07:00"}
        blocks = build_time_blocks(model([event(), event("13:30", "14:00", "Planning")], prs=[pr]))
        estimated = [b for b in blocks if b["time_basis"] == "estimated"]
        self.assertEqual(len(estimated), 1)
        self.assertEqual(estimated[0]["prs"][0]["id"], 101)

    def test_each_pr_action_can_support_its_own_gap_without_losing_history(self):
        pr = {"id": 101, "repository": "test/project", "title": "Payment", "events": [
            {"action": "opened", "timestamp": f"{DATE}T10:15:00+07:00"},
            {"action": "reviewed", "timestamp": f"{DATE}T11:00:00+07:00", "id": 1},
            {"action": "merged", "timestamp": f"{DATE}T15:00:00+07:00"}]}
        blocks = build_time_blocks(model([event("09:30", "10:00"), event("14:00", "14:30", "Review")], prs=[pr]))
        estimated = [b for b in blocks if b["time_basis"] == "estimated"]
        self.assertEqual(len(estimated), 2)
        actions = [e["action"] for b in estimated for p in b["prs"] for e in p["events"]]
        self.assertEqual(actions, ["opened", "reviewed", "merged"])

    def test_activity_inside_calendar_event_does_not_support_empty_gap(self):
        blocks = build_time_blocks(model([event()], [commit("09:15")]))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["time_basis"], "scheduled")
        self.assertEqual(len(blocks[0]["commits"]), 1)

    def test_explicit_calendar_focus_without_git_is_retained_as_scheduled(self):
        blocks = build_time_blocks(model([event("09:00", "12:00", "Focus time")]))
        self.assertEqual(len(blocks), 1)
        self.assertEqual((blocks[0]["duration_minutes"], blocks[0]["time_basis"]), (180, "scheduled"))

    def test_short_calendar_event_is_not_filtered_by_gap_threshold(self):
        blocks = build_time_blocks(model([event("10:00", "10:10", "Brief call")]))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["duration_minutes"], 10)

    def test_gap_start_is_inclusive_and_meeting_end_is_exclusive(self):
        blocks = build_time_blocks(model([event(), event("13:30", "14:00", "Planning")], [commit("09:30")]))
        meeting = next(b for b in blocks if b["start_time"] == "09:00")
        gap = next(b for b in blocks if b["time_basis"] == "estimated")
        self.assertEqual(meeting["commits"], [])
        self.assertEqual(gap["commits"][0]["timestamp"], f"{DATE}T09:30:00+07:00")

    def test_activity_at_next_event_start_does_not_support_preceding_gap(self):
        blocks = build_time_blocks(model([event(), event("12:00", "12:30", "Scheduled lunch call")], [commit("12:00")]))
        self.assertTrue(all(b["time_basis"] == "scheduled" for b in blocks))

    def test_bad_or_other_day_timestamp_does_not_create_development_gap(self):
        for timestamp in ("not-a-time", "2026-10-05T10:15:00+07:00", "2026-10-06T10:15:00"):
            activity = {**commit(), "timestamp": timestamp}
            with self.subTest(timestamp=timestamp):
                blocks = build_time_blocks(model([event()], [activity]))
                self.assertTrue(all(b["time_basis"] == "scheduled" for b in blocks))

    def test_equivalent_utc_timestamp_qualifies_and_attaches_to_correct_gap(self):
        activity = {**commit(), "timestamp": "2026-10-06T03:15:00Z"}
        blocks = build_time_blocks(model([event(), event("13:30", "14:00", "Planning")], [activity]))
        gap = next(b for b in blocks if b["time_basis"] == "estimated")
        self.assertEqual((gap["start_time"], gap["end_time"]), ("09:30", "12:00"))
        self.assertEqual(gap["commits"], [activity])

    def test_git_only_windows_are_estimated_and_never_calendar_evidence(self):
        for activities in ([commit("10:00")], [commit("15:00")], [commit("10:00"), commit("15:00", "other-sha")]):
            with self.subTest(activities=activities):
                blocks = build_time_blocks(model(commits=activities))
                self.assertTrue(blocks)
                self.assertTrue(all(b["time_basis"] == "estimated" and b["calendar_titles"] == [] for b in blocks))
                self.assertTrue(all(b["estimation_reason"] == "activity_workday_window" for b in blocks))
                self.assertEqual(sum(len(b["commits"]) for b in blocks), len(activities))

    def test_pr_only_fallback_is_explicitly_estimated(self):
        pr = {"id": 101, "title": "Payment", "timestamp": f"{DATE}T15:00:00+07:00"}
        blocks = build_time_blocks(model(prs=[pr]))
        self.assertTrue(all(b["time_basis"] == "estimated" for b in blocks))
        self.assertEqual(sum(len(b["prs"]) for b in blocks), 1)

    def test_empty_day_stays_empty(self):
        self.assertEqual(build_time_blocks(model()), [])

    def test_meeting_titles_do_not_invent_discussion_details(self):
        for title in ("Daily stand-up", "Planning", "Design review meeting", "Sprint goals?", "Focus time"):
            with self.subTest(title=title):
                entries = build_entries(build_time_blocks(model([event(title=title)])))
                expected = "Scheduled calendar activity; attendance unconfirmed."
                self.assertEqual(entries[0]["sources"]["calendar"], [title])
                self.assertEqual(entries[0]["entry"]["description"], expected + " PRs: None")

    def test_estimate_metadata_survives_payload_and_ai_summary_assembly(self):
        blocks = build_time_blocks(model(commits=[commit()]))
        original = copy.deepcopy(blocks)
        payload = prepare_all_blocks(blocks)
        self.assertEqual(payload[0]["time_basis"], "estimated")
        entries = build_entries(blocks, [{"block_id": payload[0]["block_id"], "description": "Improve invoice validation"}])
        self.assertEqual(entries[0]["time_basis"], "estimated")
        self.assertEqual(entries[0]["summary_source"], "ai")
        self.assertEqual(entries[0]["sources"]["commits"], blocks[0]["commits"])
        self.assertEqual(entries[0]["sources"]["calendar"], [])
        self.assertEqual(blocks, original)

    def test_markdown_separates_scheduled_estimated_and_manual_minutes(self):
        blocks = build_time_blocks(model([event(), event("13:30", "14:00", "Planning")], [commit()]))
        entries = build_entries(blocks)
        text = render_markdown(DATE, entries)
        self.assertIn("150m (estimated)", text)
        self.assertIn("30m (scheduled)", text)
        self.assertIn("**Total Proposed Time:** 210 mins", text)
        self.assertIn("Scheduled Calendar: 60 mins; estimated development: 150 mins", text)
        self.assertIn("not measured work time", text)
        self.assertNotIn("Cal: Development", text)
        manual = {"entry": {"start": "18:00", "end": "18:15", "duration_minutes": 15, "description": "Manual"}, "sources": {}}
        self.assertIn("manual/unclassified: 15 mins", render_markdown(DATE, [*entries, manual]))


if __name__ == "__main__":
    unittest.main()
