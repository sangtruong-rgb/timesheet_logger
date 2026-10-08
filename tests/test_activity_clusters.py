"""Development activity clustering keeps inferred work bounded and reviewable."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from block_identity import BlockIdentityError
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from save_timesheet import render_markdown


DATE = "2026-10-07"
POLICY = {
    "strategy": "activity_clusters",
    "inactivity_gap_minutes": 45,
    "minimum_block_minutes": 30,
    "maximum_block_minutes": 90,
}


def commit(time, identity="c1"):
    return {"hash": identity, "repository": "test/project", "message": f"work {identity}",
            "timestamp": f"{DATE}T{time}:00+07:00"}


def pr(time, identity):
    return {"id": identity, "repository": "test/project", "title": f"PR {identity}",
            "timestamp": f"{DATE}T{time}:00+07:00"}


def event(start, end, title="Meeting"):
    return {"title": title, "start": f"{DATE}T{start}:00+07:00", "end": f"{DATE}T{end}:00+07:00"}


def model(*, commits=None, prs=None, calendar=None, policy=POLICY):
    value = {"date": DATE, "timezone": "Asia/Ho_Chi_Minh", "calendar": calendar or [],
             "commits": commits or [], "pull_requests": prs or []}
    if policy is not None:
        value["block_policy"] = dict(policy)
    return value


class TestActivityClusters(unittest.TestCase):
    def test_single_action_is_thirty_minutes_not_a_half_day(self):
        blocks = build_time_blocks(model(commits=[commit("10:00")]))
        self.assertEqual([(b["start_time"], b["end_time"], b["duration_minutes"]) for b in blocks],
                         [("10:00", "10:30", 30)])
        self.assertEqual(blocks[0]["estimation_reason"], "activity_cluster")
        self.assertEqual(blocks[0]["review"]["reasons"], ["inferred_activity_boundaries"])

    def test_idle_gap_splits_independent_actions(self):
        blocks = build_time_blocks(model(commits=[commit("09:10", "a"), commit("10:10", "b")]))
        self.assertEqual([(b["start_time"], b["end_time"]) for b in blocks],
                         [("09:00", "09:30"), ("10:00", "10:30")])
        self.assertEqual([[c["hash"] for c in b["commits"]] for b in blocks], [["a"], ["b"]])

    def test_maximum_splits_a_continuous_activity_stream(self):
        activities = [commit(time, time) for time in ("09:00", "09:40", "10:20", "11:00")]
        blocks = build_time_blocks(model(commits=activities))
        self.assertEqual([(b["start_time"], b["end_time"]) for b in blocks],
                         [("09:00", "10:30"), ("11:00", "11:30")])
        self.assertTrue(all(b["duration_minutes"] <= 90 for b in blocks))

    def test_dense_pr_merge_batch_is_one_short_reviewable_block(self):
        blocks = build_time_blocks(model(prs=[pr(f"09:4{minute}", number)
                                               for minute, number in enumerate(range(48, 53))]))
        self.assertEqual([(b["start_time"], b["end_time"], len(b["prs"])) for b in blocks],
                         [("09:30", "10:00", 5)])
        entry = build_entries(blocks)[0]
        self.assertEqual(entry["review"]["status"], "required")
        self.assertEqual(entry["estimation_policy"], POLICY)

    def test_calendar_is_unchanged_and_development_is_clustered_inside_gap(self):
        blocks = build_time_blocks(model(calendar=[event("09:00", "09:30")],
                                         commits=[commit("10:00"), commit("15:00", "later")]))
        self.assertEqual([(b["start_time"], b["end_time"], b["time_basis"]) for b in blocks],
                         [("09:00", "09:30", "scheduled"),
                          ("10:00", "10:30", "estimated"),
                          ("15:00", "15:30", "estimated")])

    def test_evening_calendar_does_not_extend_development_windows(self):
        review = []
        blocks = build_time_blocks(model(calendar=[event('20:00', '21:00')],
                                         commits=[commit('15:00', 'daytime'), commit('19:00', 'evening')]),
                                   unassigned_activity=review)
        self.assertEqual([(b['start_time'], b['end_time'], b['time_basis']) for b in blocks],
                         [('15:00', '15:30', 'estimated'), ('20:00', '21:00', 'scheduled')])
        self.assertEqual([c['hash'] for b in blocks for c in b['commits']], ['daytime'])
        self.assertEqual([(r['reason'], r['activity']['hash']) for r in review], [('outside_blocks', 'evening')])

    def test_clusters_never_cross_lunch_and_lunch_evidence_is_unassigned(self):
        review = []
        blocks = build_time_blocks(model(commits=[commit("11:55", "before"), commit("12:30", "lunch"),
                                                   commit("13:35", "after")]),
                                   unassigned_activity=review)
        self.assertEqual([(b["start_time"], b["end_time"]) for b in blocks],
                         [("11:30", "12:00"), ("13:30", "14:00")])
        self.assertEqual([item["activity"]["hash"] for item in review], ["lunch"])

    def test_review_notice_reaches_markdown(self):
        text = render_markdown(DATE, build_entries(build_time_blocks(model(commits=[commit("10:00")]))))
        self.assertIn("development boundaries were inferred", text)
        self.assertIn("boundary review required", text)

    def test_missing_policy_preserves_legacy_snapshot_behavior(self):
        blocks = build_time_blocks(model(commits=[commit("10:00")], policy=None))
        self.assertEqual([(b["start_time"], b["end_time"]) for b in blocks], [("09:00", "12:30")])
        self.assertEqual(blocks[0]["estimation_reason"], "activity_workday_window")

    def test_invalid_policy_is_rejected(self):
        invalid = {**POLICY, "minimum_block_minutes": 60, "maximum_block_minutes": 30}
        with self.assertRaises(BlockIdentityError):
            build_time_blocks(model(commits=[commit("10:00")], policy=invalid))


if __name__ == "__main__":
    unittest.main()
