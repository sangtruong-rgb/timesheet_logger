"""Confirmed hours and backward merging preserve evidence and excluded time."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from block_identity import BlockIdentityError, index_blocks
from block_settings import policy_from_model
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from activity_snapshot import read_snapshot, save_snapshot, fingerprint, SnapshotError
from prepare_ai_input import prepare_activity_input
from run_pipeline import run
from save_timesheet import render_markdown
from test_activity_clusters import DATE, commit, event, pr


def model(commits=None, calendar=None, prs=None, start="09:00", end=None):
    return {"date": DATE, "timezone": "Asia/Ho_Chi_Minh", "commits": commits or [],
            "calendar": calendar or [], "pull_requests": prs or [],
            "block_policy": {"strategy": "commit_intervals"},
            "work_confirmation": {"date": DATE, "start": start, **({"end": end} if end is not None else {})}}


def development(blocks):
    return [b for b in blocks if b["block_type"] == "development"]


def intervals(blocks):
    index_blocks(blocks)
    return [(b["start_time"], b["end_time"], b["duration_minutes"]) for b in blocks]


class TestCommitIntervals(unittest.TestCase):
    def test_confirmed_start_and_closing_commit_ownership(self):
        activities = [commit(t, t) for t in ("10:10", "11:40", "14:10", "16:00")]
        blocks = build_time_blocks(model(activities))
        self.assertEqual(intervals(blocks), [("09:00", "10:10", 70), ("10:10", "11:40", 90),
            ("11:40", "12:00", 20), ("13:30", "14:10", 40), ("14:10", "16:00", 110)])
        self.assertEqual([b["commits"][0]["hash"] for b in blocks], ["10:10", "11:40", "14:10", "14:10", "16:00"])
        self.assertEqual(sum(b["duration_minutes"] for b in blocks), 330)

    def test_first_short_and_long_intervals_are_not_padded_or_capped(self):
        blocks = build_time_blocks(model([commit("09:01", "a"), commit("11:59", "b")]))
        self.assertEqual(intervals(blocks), [("09:00", "09:01", 1), ("09:01", "11:59", 178)])

    def test_consecutive_short_commits_merge_backward_with_all_evidence(self):
        activities = [commit(t, name) for t, name in [('10:00', 'a'), ('10:10', 'b'),
                                                      ('10:25', 'c'), ('10:55', 'd')]]
        blocks = build_time_blocks(model(activities, prs=[pr('10:15', 1), pr('10:25', 2)]))
        self.assertEqual(intervals(blocks), [('09:00', '10:25', 85), ('10:25', '10:55', 30)])
        self.assertEqual([[c['hash'] for c in b['commits']] for b in blocks], [['a', 'b', 'c'], ['d']])
        self.assertEqual([[p['id'] for p in b['prs']] for b in blocks], [[1], [2]])
        self.assertEqual(len(blocks[0]['allocation']['merged_intervals']), 3)
        self.assertEqual(blocks[0]['allocation']['short_commit_merge_minutes'], 20)
        payload = prepare_activity_input(blocks, [])
        self.assertEqual(set(payload['blocks'][0]['commit_messages']), {'work a', 'work b', 'work c'})
        entries = build_entries(blocks)
        self.assertEqual(len(entries[0]['sources']['commits']), 3)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 115)
        self.assertEqual(blocks, build_time_blocks(model(list(reversed(activities)), prs=[pr('10:15', 1), pr('10:25', 2)])))

    def test_19_minutes_merges_but_20_29_and_30_stay_separate(self):
        blocks = build_time_blocks(model([commit('10:00', 'a'), commit('10:19', 'b'),
                                         commit('10:39', 'c'), commit('11:08', 'd'), commit('11:38', 'e')]))
        self.assertEqual(intervals(blocks), [('09:00', '10:19', 79), ('10:19', '10:39', 20),
                                           ('10:39', '11:08', 29), ('11:08', '11:38', 30)])
        self.assertEqual([[c['hash'] for c in b['commits']] for b in blocks], [['a', 'b'], ['c'], ['d'], ['e']])

    def test_short_first_interval_remains_and_can_receive_next_short_commit(self):
        blocks = build_time_blocks(model([commit('09:10', 'a'), commit('09:20', 'b'), commit('10:00', 'c')]))
        self.assertEqual(intervals(blocks), [('09:00', '09:20', 20), ('09:20', '10:00', 40)])
        self.assertEqual([c['hash'] for c in blocks[0]['commits']], ['a', 'b'])

    def test_net_work_under_20_merges_across_lunch_without_counting_lunch(self):
        blocks = build_time_blocks(model([commit('11:50', 'a'), commit('13:39', 'b')], start='11:00'))
        self.assertEqual(intervals(blocks), [('11:00', '12:00', 60), ('13:30', '13:39', 9)])
        self.assertEqual([[c['hash'] for c in b['commits']] for b in blocks], [['a', 'b'], ['a', 'b']])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 69)

    def test_exactly_20_net_work_minutes_across_lunch_stays_separate(self):
        blocks = build_time_blocks(model([commit('11:50', 'a'), commit('13:40', 'b')], start='11:00'))
        self.assertEqual(intervals(blocks), [('11:00', '11:50', 50), ('11:50', '12:00', 10), ('13:30', '13:40', 10)])
        self.assertEqual([[c['hash'] for c in b['commits']] for b in blocks], [['a'], ['b'], ['b']])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 70)

    def test_short_split_piece_of_long_commit_allocation_does_not_merge(self):
        blocks = build_time_blocks(model([commit('11:40', 'a'), commit('14:10', 'b')]))
        self.assertEqual(intervals(blocks), [('09:00', '11:40', 160), ('11:40', '12:00', 20), ('13:30', '14:10', 40)])
        self.assertEqual([[c['hash'] for c in b['commits']] for b in blocks], [['a'], ['b'], ['b']])

    def test_merge_across_calendar_keeps_scheduled_row_separate(self):
        blocks = build_time_blocks(model([commit('10:00', 'a'), commit('11:19', 'b')],
                                         [event('10:00', '11:00')]))
        self.assertEqual(intervals(development(blocks)), [('09:00', '10:00', 60), ('11:00', '11:19', 19)])
        self.assertEqual([[c['hash'] for c in b['commits']] for b in development(blocks)], [['a', 'b'], ['a', 'b']])
        scheduled = [b for b in blocks if b['time_basis'] == 'scheduled']
        self.assertEqual(intervals(scheduled), [('10:00', '11:00', 60)])
        self.assertEqual(scheduled[0]['commits'], [])

    def test_zero_work_commit_is_not_absorbed_into_previous_development(self):
        review = []
        blocks = build_time_blocks(model([commit('10:00', 'a'), commit('10:30', 'b'), commit('10:50', 'c')],
                                         [event('10:00', '10:30')]), unassigned_activity=review)
        self.assertEqual(intervals(development(blocks)), [('09:00', '10:00', 60), ('10:30', '10:50', 20)])
        self.assertEqual([{c['hash'] for c in b['commits']} for b in development(blocks)], [{'a'}, {'b', 'c'}])
        self.assertEqual(review, [])

    def test_short_confirmed_end_tail_does_not_borrow_commit_or_merge(self):
        blocks = build_time_blocks(model([commit('10:00', 'a'), commit('10:10', 'b')], end='10:20'))
        self.assertEqual(intervals(blocks), [('09:00', '10:10', 70), ('10:10', '10:20', 10)])
        self.assertEqual(blocks[-1]['commits'], [])
        self.assertEqual(blocks[-1]['allocation']['basis'], 'confirmed_end')

    def test_snapshots_freeze_unmerged_30_and_20_minute_rules(self):
        activity = model([commit('10:00', 'a'), commit('10:29', 'b')])
        with tempfile.TemporaryDirectory() as directory:
            for version in (1, 2, 3, 4):
                review = []
                blocks = build_time_blocks(activity, unassigned_activity=review, merge_short_commits=version >= 2,
                                           short_commit_merge_minutes=30 if version == 2 else 20,
                                           commit_allocation_version=2 if version >= 4 else 1)
                payload = prepare_activity_input(blocks, review)
                path = Path(directory) / f'v{version}.json'
                frozen = save_snapshot(path, activity, {'status': 'complete'}, blocks, review, payload)
                self.assertEqual(frozen['schema_version'], 4)
                if version != 4:
                    frozen['schema_version'] = version
                    frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
                    path.write_text(json.dumps(frozen))
                self.assertEqual(read_snapshot(path)['blocks'], blocks)
                self.assertEqual(len(blocks), 1 if version == 2 else 2)
                if version in (2, 3):
                    frozen['schema_version'] = 3 if version == 2 else 2
                    frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
                    path.write_text(json.dumps(frozen))
                    with self.assertRaises(SnapshotError): read_snapshot(path)

    def test_identical_v1_snapshot_can_be_resaved_without_rewriting_history(self):
        activity = model([commit('10:00')])
        blocks = build_time_blocks(activity, commit_allocation_version=1)
        payload = prepare_activity_input(blocks, [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            collection = {'status': 'complete'}
            frozen = save_snapshot(path, activity, collection, blocks, [], payload)
            frozen['schema_version'] = 1
            frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
            path.write_text(json.dumps(frozen, indent=2))
            before = path.read_bytes()
            self.assertEqual(save_snapshot(path, activity, collection, blocks, [], payload), frozen)
            self.assertEqual(path.read_bytes(), before)

    def test_confirmed_end_adds_tail_without_borrowing_last_commit(self):
        blocks = build_time_blocks(model([commit("10:00")], end="11:00"))
        self.assertEqual(intervals(blocks), [("09:00", "10:00", 60), ("10:00", "11:00", 60)])
        self.assertEqual(blocks[-1]["commits"], [])
        self.assertEqual(blocks[-1]["allocation"]["basis"], "confirmed_end")

    def test_no_commits_requires_end_to_allocate_work(self):
        self.assertEqual(build_time_blocks(model()), [])
        self.assertEqual(intervals(build_time_blocks(model(end="14:00"))),
                         [("09:00", "12:00", 180), ("13:30", "14:00", 30)])

    def test_overlapping_calendar_is_subtracted_once_and_keeps_attendance_review(self):
        blocks = build_time_blocks(model([commit("11:00")], [event("09:30", "10:30", "A"), event("10:00", "10:45", "B")]))
        self.assertEqual(intervals(development(blocks)), [("09:00", "09:30", 30), ("10:45", "11:00", 15)])
        self.assertEqual(sum(b["duration_minutes"] for b in blocks), 120)
        self.assertTrue(any(b.get("calendar_overlap") for b in blocks))
        self.assertEqual([len(b["commits"]) for b in development(blocks)], [1, 1])

    def test_lunch_meeting_is_retained_but_does_not_add_development(self):
        blocks = build_time_blocks(model([commit("14:00")], [event("12:15", "12:45")], start="11:30"))
        self.assertEqual(intervals(blocks), [("11:30", "12:00", 30), ("12:15", "12:45", 30), ("13:30", "14:00", 30)])

    def test_commit_in_lunch_closes_only_work_before_lunch(self):
        blocks = build_time_blocks(model([commit("12:30", "a"), commit("14:00", "b")], start="11:00"))
        self.assertEqual(intervals(blocks), [("11:00", "12:00", 60), ("13:30", "14:00", 30)])
        self.assertEqual([b["commits"][0]["hash"] for b in blocks], ["a", "b"])

    def test_pr_actions_attach_without_creating_work(self):
        review = []
        blocks = build_time_blocks(model([commit("10:00"), commit("11:00", "later")],
                                         prs=[pr("09:45", 1), pr("10:00", 2), pr("11:30", 3)]), unassigned_activity=review)
        self.assertEqual(intervals(blocks), [("09:00", "10:00", 60), ("10:00", "11:00", 60)])
        self.assertEqual([[p["id"] for p in b["prs"]] for b in blocks], [[1], [2]])
        self.assertEqual([r["activity"]["id"] for r in review], [3])

    def test_boundary_merge_links_matching_commit_without_extending_time(self):
        closing = commit('16:07', 'merge')
        closing['timestamp'] = closing['timestamp'].replace('16:07:00', '16:07:19')
        action = {**pr('16:07', 66), 'status': 'merged', 'merge_commit_sha': 'merge'}
        action['timestamp'] = action['timestamp'].replace('16:07:00', '16:07:20')
        review = []
        blocks = build_time_blocks(model([closing], prs=[action]), unassigned_activity=review)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 337)
        self.assertEqual(blocks[-1]['end_time'], '16:07')
        self.assertEqual(blocks[-1]['prs'][0]['timestamp'], action['timestamp'])
        self.assertEqual(blocks[-1]['prs'][0]['assignment']['basis'], 'matching_merge_commit')
        self.assertEqual([len(b['prs']) for b in blocks], [0, 1])
        self.assertEqual(review, [])
        self.assertNotIn('assignment', action)
        historical = []
        build_time_blocks(model([closing], prs=[action]), unassigned_activity=historical, commit_allocation_version=1)
        self.assertEqual(historical[0]['activity'], action)

    def test_merge_link_requires_sha_repository_minute_and_confirmed_hours(self):
        closing = commit('16:07', 'merge')
        closing['timestamp'] = closing['timestamp'].replace('16:07:00', '16:07:19')
        base = {**pr('16:07', 66), 'status': 'merged', 'merge_commit_sha': 'merge'}
        base['timestamp'] = base['timestamp'].replace('16:07:00', '16:07:20')
        for change in ({'merge_commit_sha': 'other'}, {'merge_commit_sha': None},
                       {'repository': 'other/project'}, {'status': 'opened'},
                       {'timestamp': base['timestamp'].replace('16:07', '16:08')}):
            review = []
            build_time_blocks(model([closing], prs=[{**base, **change}]), unassigned_activity=review)
            self.assertEqual(len(review), 1, change)
        review = []
        build_time_blocks(model([closing], prs=[base], end='16:07'), unassigned_activity=review)
        self.assertEqual({r['source'] for r in review}, {'git', 'github'})

    def test_intermediate_merge_uses_closing_group_and_preserves_other_events(self):
        closing = commit('10:00', 'merge')
        closing['timestamp'] = closing['timestamp'].replace('10:00:00', '10:00:19')
        reference = {**pr('10:00', 66), 'status': 'merged', 'merge_commit_sha': 'merge',
                     'events': [{'action': 'opened', 'timestamp': pr('09:45', 66)['timestamp']},
                                {'action': 'merged', 'timestamp': pr('10:00', 66)['timestamp'].replace('10:00:00', '10:00:20')}]}
        blocks = build_time_blocks(model([closing, commit('11:00', 'next')], prs=[reference]))
        self.assertEqual([len(b['prs']) for b in blocks], [1, 0])
        self.assertEqual([e['action'] for e in blocks[0]['prs'][0]['events']], ['opened', 'merged'])
        self.assertEqual(blocks[0]['prs'][0]['events'][1]['assignment']['basis'], 'matching_merge_commit')

    def test_merged_short_allocation_and_lunch_use_last_piece_for_merge(self):
        closing = commit('13:39', 'merge')
        closing['timestamp'] = closing['timestamp'].replace('13:39:00', '13:39:19')
        action = {**pr('13:39', 66), 'status': 'merged', 'merge_commit_sha': 'merge'}
        action['timestamp'] = action['timestamp'].replace('13:39:00', '13:39:20')
        blocks = build_time_blocks(model([commit('11:50', 'before'), closing], prs=[action], start='11:00'))
        self.assertEqual(intervals(blocks), [('11:00', '12:00', 60), ('13:30', '13:39', 9)])
        self.assertEqual([len(b['prs']) for b in blocks], [0, 1])

    def test_same_minute_commits_group_and_raw_seconds_are_preserved(self):
        a, b = commit("10:00", "a"), commit("10:00", "b")
        b["timestamp"] = b["timestamp"].replace(":00+07:00", ":45+07:00")
        blocks = build_time_blocks(model([b, a]))
        self.assertEqual(intervals(blocks), [("09:00", "10:00", 60)])
        self.assertEqual(blocks[0]["commits"], [a, b])
        self.assertEqual(blocks, build_time_blocks(model([a, b])))

    def test_work_outside_legacy_windows_and_midnight_end(self):
        self.assertEqual(intervals(build_time_blocks(model([commit("08:00")], start="07:00"))), [("07:00", "08:00", 60)])
        self.assertEqual(intervals(build_time_blocks(model([commit("23:30")], start="23:00", end="24:00"))),
                         [("23:00", "23:30", 30), ("23:30", "24:00", 30)])

    def test_out_of_range_and_invalid_commits_are_retained(self):
        invalid = {**commit("10:00", "bad"), "timestamp": "invalid"}
        review = []
        blocks = build_time_blocks(model([commit("08:00", "early"), commit("10:00"), commit("17:00", "late"), invalid],
                                         end="11:00"), unassigned_activity=review)
        self.assertEqual(sum(b["duration_minutes"] for b in blocks), 120)
        self.assertEqual([r["activity"]["hash"] for r in review], ["early", "late", "bad"])

    def test_zero_work_interval_does_not_invent_minutes_or_drop_commit(self):
        review = []
        blocks = build_time_blocks(model([commit("13:00")], start="12:00"), unassigned_activity=review)
        self.assertEqual(blocks, [])
        self.assertEqual(len(review), 1)

    def test_calendar_only_is_preserved(self):
        blocks = build_time_blocks(model(calendar=[event("10:00", "11:00")]))
        self.assertEqual(intervals(blocks), [("10:00", "11:00", 60)])
        self.assertEqual(blocks[0]["time_basis"], "scheduled")

    def test_missing_stale_or_invalid_confirmation_rejected(self):
        for value in (None, {}, {"date": "2026-10-06", "start": "09:00"},
                      {"date": DATE, "start": "9:00"}, {"date": DATE, "start": "10:00", "end": "09:00"},
                      {"date": DATE, "start": "09:00", "breaks": []}):
            with self.subTest(value=value), self.assertRaises(BlockIdentityError):
                build_time_blocks({**model(), "work_confirmation": value})

    def test_policy_rejects_cluster_parameters(self):
        with self.assertRaises(ValueError):
            policy_from_model({"block_policy": {"strategy": "commit_intervals", "minimum_block_minutes": 30}})

    def test_metadata_and_estimate_label_survive_assembly(self):
        entries = build_entries(build_time_blocks(model([commit("10:00")])))
        self.assertEqual(entries[0]["work_confirmation"], {"date": DATE, "start": "09:00"})
        self.assertEqual(entries[0]["allocation"]["basis"], "ending_commit")
        self.assertEqual(entries[0]["time_basis"], "estimated")
        self.assertIn("Commit intervals:", render_markdown(DATE, entries))


class TestPipelineCommitIntervals(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile.json"
        self.profile.write_text(json.dumps({"repositories": ["test/project"], "author": {"names": ["Tester"]},
            "github": {"users": ["tester"]}, "timezone": "Asia/Ho_Chi_Minh", "block_policy": {"strategy": "commit_intervals"}}))
        self.snapshot = self.root / "snapshot.json"
        self.output = self.root / "timesheets"
        self.activities = [commit('10:00')]

    def invoke(self, *args):
        def collector(command, source, mode):
            items = [{**activity, "author": "Tester"} for activity in self.activities] if source == "git" else []
            return {"source": source, "mode": mode, "status": "success", "items": items}
        argv = ["run_pipeline.py", "--date", DATE, "--config", str(self.profile), "--output-dir", str(self.output), *args]
        with patch.object(sys, "argv", argv), patch("run_pipeline.run_source_collector", side_effect=collector) as collect, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = run()
            except SystemExit as exc:
                code = exc.code
            return code, collect.call_count

    def test_missing_confirmation_fails_before_collection(self):
        self.assertEqual(self.invoke(), (2, 0))
        self.assertFalse(self.output.exists())

    def test_prepare_assemble_freezes_hours_and_does_not_recollect(self):
        self.assertEqual(self.invoke("--phase", "prepare", "--snapshot", str(self.snapshot), "--work-start", "08:30", "--work-end", "11:00"), (0, 3))
        frozen = read_snapshot(self.snapshot)
        self.assertEqual(frozen["normalized"]["work_confirmation"], {"date": DATE, "start": "08:30", "end": "11:00"})
        self.profile.write_text('{}')
        self.assertEqual(self.invoke("--phase", "assemble", "--snapshot", str(self.snapshot)), (0, 0))
        rows = json.loads((self.output / f"{DATE}.json").read_text())
        self.assertEqual(sum(r["entry"]["duration_minutes"] for r in rows), 150)
        before = (self.output / f"{DATE}.json").read_bytes()
        self.assertEqual(self.invoke("--phase", "assemble", "--snapshot", str(self.snapshot)), (0, 0))
        self.assertEqual((self.output / f"{DATE}.json").read_bytes(), before)
        self.assertEqual(self.invoke("--phase", "assemble", "--snapshot", str(self.snapshot), "--work-start", "09:00"), (2, 0))
        self.assertEqual((self.output / f"{DATE}.json").read_bytes(), before)

    def test_start_flag_selects_new_policy_for_old_profile(self):
        profile = json.loads(self.profile.read_text())
        profile.pop("block_policy")
        self.profile.write_text(json.dumps(profile))
        self.assertEqual(self.invoke("--work-start", "08:30"), (0, 3))
        rows = json.loads((self.output / f"{DATE}.json").read_text())
        self.assertEqual(rows[0]["entry"]["duration_minutes"], 90)
        self.assertEqual(rows[0]["estimation_policy"], {"strategy": "commit_intervals"})

    def test_prepare_and_assemble_use_merged_commits_without_losing_sources(self):
        self.activities = [commit('10:00', 'a'), commit('10:10', 'b'), commit('10:25', 'c')]
        self.assertEqual(self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot), '--work-start', '09:00'), (0, 3))
        frozen = read_snapshot(self.snapshot)
        self.assertEqual(frozen['schema_version'], 4)
        self.assertEqual(intervals(frozen['blocks']), [('09:00', '10:25', 85)])
        self.assertEqual(len(frozen['ai_input']['summary_request']['jobs']), 1)
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        path = self.output / f'{DATE}.json'
        rows = json.loads(path.read_text())
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]['sources']['commits']), 3)
        before = path.read_bytes()
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
