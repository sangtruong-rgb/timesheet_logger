"""Configured boundaries, excluded time and historical replay remain deterministic."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from activity_snapshot import read_snapshot, save_snapshot, fingerprint, SnapshotError
from block_identity import BlockIdentityError
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from prepare_ai_input import prepare_activity_input
from save_timesheet import render_markdown
from work_schedule import validate_schedule, DEFAULT_SCHEDULE, schedule_bounds
from test_activity_clusters import model as activity_model, POLICY
from test_commit_intervals import DATE, model, commit, event, intervals, development
import test_commit_intervals as commit_fixture


class TestWorkSchedule(unittest.TestCase):
    def test_new_default_and_legacy_morning_replay_are_distinct(self):
        activity = activity_model(commits=[commit('10:00')], policy=None)
        self.assertEqual(intervals(build_time_blocks(activity)), [('09:00', '12:30', 210)])
        activity['work_schedule'] = validate_schedule({})
        self.assertEqual(intervals(build_time_blocks(activity)), [('09:00', '12:00', 180)])
        activity['commits'] = [commit('12:15')]
        review = []
        self.assertEqual(build_time_blocks(activity, unassigned_activity=review), [])
        self.assertEqual(review[0]['activity']['hash'], activity['commits'][0]['hash'])

    def test_custom_windows_apply_with_and_without_calendar(self):
        schedule = {'start': '08:00', 'end': '16:00', 'breaks': [{'start': '11:45', 'end': '12:45'}]}
        activity = activity_model(commits=[commit('08:15', 'a'), commit('10:00', 'b'), commit('15:00', 'c')], policy=None)
        activity['work_schedule'] = schedule
        self.assertEqual(intervals(build_time_blocks(activity)), [('08:00', '11:45', 225), ('12:45', '16:00', 195)])
        activity['calendar'] = [event('08:30', '09:00')]
        self.assertEqual(intervals(build_time_blocks(activity)),
                         [('08:00', '08:30', 30), ('08:30', '09:00', 30),
                          ('09:00', '11:45', 165), ('12:45', '16:00', 195)])

    def test_multiple_breaks_split_one_commit_group_and_keep_every_minute(self):
        activity = model([commit('14:30')], start='08:30')
        activity['work_schedule'] = {'breaks': [{'start': '10:00', 'end': '10:15'},
                                             {'start': '12:30', 'end': '13:00'}]}
        blocks = build_time_blocks(activity)
        self.assertEqual(intervals(blocks), [('08:30', '10:00', 90), ('10:15', '12:30', 135), ('13:00', '14:30', 90)])
        self.assertEqual(len(prepare_activity_input(blocks, [])['summary_request']['jobs']), 1)
        entries = build_entries(blocks)
        self.assertTrue(all(r['work_schedule']['breaks'] == activity['work_schedule']['breaks'] for r in entries))
        markdown = render_markdown(DATE, entries)
        self.assertIn('10:00', markdown)
        self.assertNotIn('lunch 12:00', markdown)

    def test_breaks_and_calendar_coverage_are_subtracted_as_union(self):
        activity = model([commit('14:00')], [event('11:45', '12:45')], start='11:00')
        activity['work_schedule'] = {'breaks': [{'start': '12:00', 'end': '13:00'}]}
        self.assertEqual(intervals(development(build_time_blocks(activity))),
                         [('11:00', '11:45', 45), ('13:00', '14:00', 60)])

    def test_nonworking_days_retain_meetings_and_review_development_evidence(self):
        for schedule in ({'weekdays': [0]}, {'holidays': [DATE]}, {'weekdays': []}):
            activity = activity_model(commits=[commit('09:30')], calendar=[event('10:00', '11:00')], policy=None)
            activity['work_schedule'] = schedule
            review = []
            blocks = build_time_blocks(activity, unassigned_activity=review)
            self.assertEqual(intervals(blocks), [('10:00', '11:00', 60)])
            self.assertEqual(blocks[0]['time_basis'], 'scheduled')
            self.assertEqual(len(review), 1)

    def test_confirmed_daily_hours_allow_work_on_holiday_and_outside_regular_hours(self):
        activity = model([commit('19:00')], start='18:00')
        activity['work_schedule'] = {'weekdays': [], 'holidays': [DATE]}
        self.assertEqual(intervals(build_time_blocks(activity)), [('18:00', '19:00', 60)])

    def test_overtime_requires_explicit_window_and_keeps_gap_unfilled(self):
        activity = activity_model(commits=[commit('19:15')], policy=None)
        activity['work_schedule'] = {}
        self.assertEqual(build_time_blocks(activity), [])
        activity['work_schedule'] = {'overtime_windows': [{'start': '18:00', 'end': '20:00'}]}
        self.assertEqual(intervals(build_time_blocks(activity)), [('18:00', '20:00', 120)])
        activity['calendar'] = [event('18:30', '19:00')]
        activity['commits'].append(commit('18:15', 'before'))
        self.assertEqual(intervals(build_time_blocks(activity)),
                         [('18:00', '18:30', 30), ('18:30', '19:00', 30), ('19:00', '20:00', 60)])

    def test_midnight_end_is_valid_for_overtime_and_clustered_windows(self):
        for policy in (None, POLICY):
            activity = activity_model(commits=[commit('23:45')], policy=policy)
            activity['work_schedule'] = {'overtime_windows': [{'start': '23:30', 'end': '24:00'}]}
            self.assertEqual(intervals(build_time_blocks(activity)), [('23:30', '24:00', 30)])

    def test_cluster_window_shorter_than_minimum_retains_activity_for_review(self):
        activity = activity_model(commits=[commit('09:05')])
        activity['work_schedule'] = {'end': '09:15', 'breaks': []}
        review = []
        self.assertEqual(build_time_blocks(activity, unassigned_activity=review), [])
        self.assertEqual(len(review), 1)

    def test_empty_break_list_allows_confirmed_work_through_old_lunch(self):
        activity = model([commit('14:00')], start='11:00')
        activity['work_schedule'] = {'breaks': []}
        self.assertEqual(intervals(build_time_blocks(activity)), [('11:00', '14:00', 180)])

    def test_no_inferred_minutes_when_break_covers_entire_work_window(self):
        activity = activity_model(commits=[commit('10:00')], policy=None)
        activity['work_schedule'] = {'breaks': [{'start': '09:00', 'end': '17:30'}]}
        self.assertEqual(build_time_blocks(activity), [])

    def test_schedule_validation_rejects_ambiguous_or_malformed_inputs(self):
        bad = [None, [], {'unknown': 1}, {'start': '9:00'}, {'start': '24:00'}, {'end': '08:00'},
               {'breaks': [{'start': '12:00', 'end': '12:00'}]},
               {'breaks': [{'start': '12:00', 'end': '13:00'}, {'start': '12:30', 'end': '13:30'}]},
               {'breaks': [{'start': '12:00', 'end': '13:00', 'x': 1}]},
               {'overtime_windows': [{'start': '17:00', 'end': '20:00'}]},
               {'weekdays': [True]}, {'weekdays': [7]}, {'weekdays': [0, 0]}, {'weekdays': 'Mon'},
               {'holidays': ['20261007']}, {'holidays': [DATE, DATE]}, {'holidays': None}]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_schedule(value)

    def test_defaults_are_not_shared_with_mutable_profile(self):
        original = copy.deepcopy(DEFAULT_SCHEDULE)
        schedule = validate_schedule({})
        schedule['breaks'][0]['start'] = '11:00'
        schedule['weekdays'].clear()
        self.assertEqual(DEFAULT_SCHEDULE, original)

    def test_nonexistent_dst_boundary_is_rejected(self):
        import datetime
        with self.assertRaisesRegex(ValueError, 'nonexistent'):
            schedule_bounds({'work_schedule': {'start': '02:30', 'end': '10:00', 'breaks': []}},
                            datetime.date(2026, 3, 8), ZoneInfo('America/New_York'))

    def test_scheduled_calendar_outside_regular_hours_stays_unconfirmed(self):
        activity = activity_model(calendar=[event('20:00', '21:00')], policy=None)
        activity['work_schedule'] = {'weekdays': []}
        entries = build_entries(build_time_blocks(activity))
        self.assertEqual(entries[0]['attendance'], 'unconfirmed')
        self.assertEqual(entries[0]['entry']['duration_minutes'], 60)


class TestSchedulePipeline(unittest.TestCase):
    setUp = commit_fixture.TestPipelineCommitIntervals.setUp
    invoke = commit_fixture.TestPipelineCommitIntervals.invoke

    def prepare(self, schedule):
        profile = json.loads(self.profile.read_text())
        profile['work_schedule'] = schedule
        self.profile.write_text(json.dumps(profile))
        self.activities = [commit('14:30')]
        return self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot), '--work-start', '08:30')

    def test_prepare_freezes_schedule_and_assemble_ignores_changed_profile(self):
        self.assertEqual(self.prepare({'breaks': [{'start': '12:30', 'end': '13:00'}]}), (0, 3))
        frozen = read_snapshot(self.snapshot)
        self.assertEqual(frozen['schema_version'], 9)
        self.assertEqual(intervals(frozen['blocks']), [('08:30', '12:30', 240), ('13:00', '14:30', 90)])
        self.profile.write_text('{invalid config')
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        rows = json.loads((self.output / f'{DATE}.json').read_text())
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows), 330)
        before = {p: p.read_bytes() for p in self.output.glob(f'{DATE}.*')}
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_invalid_profile_blocks_before_collection_or_replacing_snapshot(self):
        self.assertEqual(self.prepare({}), (0, 3))
        before = self.snapshot.read_bytes()
        self.assertEqual(self.prepare({'start': '09:00', 'end': '08:00'}), (2, 0))
        self.assertEqual(self.snapshot.read_bytes(), before)

    def test_nonexistent_date_boundary_and_noncanonical_date_fail_before_collection(self):
        profile = json.loads(self.profile.read_text())
        profile.update(timezone='America/New_York', work_schedule={'start': '02:30', 'end': '10:00', 'breaks': []})
        self.profile.write_text(json.dumps(profile))
        self.assertEqual(self.invoke('--date', '2026-03-08', '--work-start', '09:00'), (2, 0))
        self.assertEqual(self.invoke('--date', '20261007', '--work-start', '09:00'), (2, 0))
        profile['work_schedule']['start'] = '09:00'
        self.profile.write_text(json.dumps(profile))
        self.assertEqual(self.invoke('--date', '2026-03-08', '--work-start', '02:30'), (2, 0))

    def test_invalid_schedule_in_direct_writer_preserves_prior_files(self):
        from save_timesheet import save_timesheet, TimesheetReconciliationError
        entries = build_entries(build_time_blocks(model([commit('10:00')])))
        save_timesheet(entries, self.output, target_date=DATE, collection_status='complete')
        before = {p: p.read_bytes() for p in self.output.glob(f'{DATE}.*')}
        entries[0]['work_schedule'] = {'start': '09:00', 'end': '08:00'}
        with self.assertRaisesRegex(TimesheetReconciliationError, 'work schedule'):
            save_timesheet(entries, self.output, target_date=DATE, collection_status='complete')
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_rehashed_schedule_change_and_version_downgrade_are_rejected(self):
        self.assertEqual(self.prepare({}), (0, 3))
        frozen = read_snapshot(self.snapshot)
        for edit in ('schedule', 'version'):
            value = copy.deepcopy(frozen)
            if edit == 'schedule':
                value['normalized']['work_schedule']['breaks'] = []
            else:
                value['schema_version'] = 4
            value['fingerprint'] = fingerprint({k: v for k, v in value.items() if k != 'fingerprint'})
            self.snapshot.write_text(json.dumps(value))
            with self.assertRaises(SnapshotError):
                read_snapshot(self.snapshot)

    def test_normalizer_cli_freezes_configured_schedule(self):
        source = self.root / 'commits.json'
        source.write_text(json.dumps([commit('10:00')]))
        profile = json.loads(self.profile.read_text())
        profile['work_schedule'] = {'breaks': []}
        self.profile.write_text(json.dumps(profile))
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/normalize_activity.py'),
                                  '--date', DATE, '--config', str(self.profile), '--commits-file', str(source)],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['work_schedule']['breaks'], [])

    def test_v5_measured_summary_assembles_with_verified_usage(self):
        from unittest.mock import patch
        from run_codex_summary import run_summary
        import test_summary_request as summary_fixture
        self.assertEqual(self.prepare({}), (0, 3))
        process = summary_fixture.TestSummaryRequest.fake_process.__get__(self)
        with patch('run_codex_summary.subprocess.run', side_effect=process):
            result = run_summary(self.snapshot, self.root / 'measured', model='synthetic-test-model')
        csv_path = self.root / 'tokens.csv'
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot),
                                     '--ai-output', result['ai_output'],
                                     '--usage-run-manifest', result['usage_run_manifest'],
                                     '--token-csv-path', str(csv_path)), (0, 0))
        manifest = json.loads((self.output / f'{DATE}.collection.json').read_text())
        self.assertEqual(manifest['token_usage']['total_tokens'], 165)
        self.assertEqual(manifest['work_schedule'], read_snapshot(self.snapshot)['normalized']['work_schedule'])

    def test_v5_without_frozen_schedule_is_rejected(self):
        self.assertEqual(self.prepare({}), (0, 3))
        frozen = read_snapshot(self.snapshot)
        del frozen['normalized']['work_schedule']
        frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
        self.snapshot.write_text(json.dumps(frozen))
        with self.assertRaises(SnapshotError):
            read_snapshot(self.snapshot)


if __name__ == '__main__':
    unittest.main()
