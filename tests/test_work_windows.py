"""Daily shorthand windows bound all proposals and survive frozen replay."""
import copy
import json
import unittest

from test_commit_intervals import DATE, model, commit, event, intervals, development
import test_commit_intervals as fixture
from work_windows import parse_work_windows
from commit_intervals import work_confirmation
from activity_snapshot import read_snapshot, fingerprint, SnapshotError
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from prepare_ai_input import prepare_activity_input
from save_timesheet import render_markdown


WINDOWS = [{'start': '08:00', 'end': '12:00'}, {'start': '13:30', 'end': '16:00'}]


def window_model(commits=None, calendar=None, text='8:00-12:00, 1h30-4:00'):
    activity = model(commits, calendar)
    windows = parse_work_windows(text)
    activity['work_confirmation'] = work_confirmation(DATE, windows[0]['start'], windows[-1]['end'], windows=windows)
    activity['work_schedule'] = {}
    return activity


class TestWorkWindows(unittest.TestCase):
    def test_shorthand_and_canonical_formats_agree(self):
        for text in ('8:00-12:00 , 1h30-4:00', '08:00–12:00, 13:30–16:00',
                     '8am-12pm, 1:30pm-4pm', '8h00-12h00, 13h30-16h00'):
            self.assertEqual(parse_work_windows(text), WINDOWS)

    def test_single_window_and_midnight(self):
        self.assertEqual(parse_work_windows('8:00-4:40'), [{'start': '08:00', 'end': '16:40'}])
        self.assertEqual(parse_work_windows('23:00-24:00'), [{'start': '23:00', 'end': '24:00'}])
        self.assertEqual(parse_work_windows('12am-1am'), [{'start': '00:00', 'end': '01:00'}])

    def test_invalid_and_overlapping_explicit_clocks_are_rejected(self):
        for text in ('', '8:00', '8:00-8:00', '25:00-26:00', '8:60-12:00', '1h3-4:00',
                     '08:00-12:00, 11:00-13:00', '14:00-13:00', '23:00-01:00',
                     '8:00-12:00,', '24:00-24:00', '0pm-1pm', '08:00-12:00, 01:30-04:00'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_work_windows(text)

    def test_exact_windows_cover_confirmed_end_without_filling_gap(self):
        blocks = build_time_blocks(window_model([commit('12:00')]))
        self.assertEqual(intervals(blocks), [('08:00', '12:00', 240), ('13:30', '16:00', 150)])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 390)
        self.assertTrue(all(b['work_confirmation']['windows'] == WINDOWS for b in blocks))
        markdown = render_markdown(DATE, build_entries(blocks))
        self.assertIn('Confirmed daily work windows: 08:00–12:00, 13:30–16:00', markdown)
        self.assertNotIn('configured breaks still apply', markdown)

    def test_explicit_windows_replace_profile_breaks_and_allow_holidays(self):
        activity = window_model([commit('13:00')], text='11:00-14:00')
        activity['work_schedule'] = {'weekdays': [], 'holidays': [DATE]}
        self.assertEqual(intervals(build_time_blocks(activity)), [('11:00', '13:00', 120), ('13:00', '14:00', 60)])

    def test_more_than_two_windows_keep_all_gaps(self):
        blocks = build_time_blocks(window_model(text='08:00-09:00, 10:00-11:00, 14:00-15:00'))
        self.assertEqual(intervals(blocks), [('08:00', '09:00', 60), ('10:00', '11:00', 60), ('14:00', '15:00', 60)])

    def test_gap_and_after_end_commits_are_review_only(self):
        activity = window_model([commit('12:00', 'inside'), commit('13:00', 'gap'), commit('17:00', 'after')])
        review = []
        blocks = build_time_blocks(activity, unassigned_activity=review)
        self.assertEqual({r['activity']['hash'] for r in review}, {'gap', 'after'})
        self.assertEqual({c['hash'] for b in blocks for c in b['commits']}, {'inside'})
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 390)

    def test_calendar_is_clipped_and_excluded_evidence_is_retained(self):
        activity = window_model(calendar=[event('07:30', '08:30'), event('11:30', '14:00'), event('17:00', '18:00')])
        review = []
        blocks = build_time_blocks(activity, unassigned_activity=review)
        scheduled = [b for b in blocks if b['time_basis'] == 'scheduled']
        self.assertEqual(intervals(scheduled), [('08:00', '08:30', 30), ('11:30', '12:00', 30), ('13:30', '14:00', 30)])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 390)
        self.assertEqual(len(review), 3)
        self.assertTrue(all(r['source'] == 'google_calendar' for r in review))
        self.assertTrue(all(e['attendance'] == 'unconfirmed' for e in build_entries(scheduled)))

    def test_short_merge_across_gap_preserves_shared_description_and_minutes(self):
        blocks = build_time_blocks(window_model([commit('12:00', 'first'), commit('13:40', 'short')]))
        self.assertEqual(intervals(development(blocks)), [('08:00', '12:00', 240), ('13:30', '13:40', 10), ('13:40', '16:00', 140)])
        self.assertEqual(blocks[0]['allocation']['summary_group_id'], blocks[1]['allocation']['summary_group_id'])
        self.assertEqual(len(prepare_activity_input(blocks, [])['summary_request']['jobs']), 1)

    def test_confirmation_rejects_conflicting_or_invalid_windows(self):
        activity = window_model()
        for value in (None, [], list(reversed(WINDOWS)), [{'start': '09:00', 'end': '16:00'}]):
            broken = copy.deepcopy(activity)
            broken['work_confirmation']['windows'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_time_blocks(broken)


class TestWindowPipeline(unittest.TestCase):
    setUp = fixture.TestPipelineCommitIntervals.setUp
    invoke = fixture.TestPipelineCommitIntervals.invoke

    def prepare(self, text='8:00-12:00, 1h30-4:00'):
        return self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot), '--work-windows', text)

    def test_v6_freezes_windows_and_replays_without_profile_or_collection(self):
        self.assertEqual(self.prepare(), (0, 3))
        snapshot = read_snapshot(self.snapshot)
        self.assertEqual(snapshot['schema_version'], 10)
        self.assertEqual(snapshot['normalized']['work_confirmation']['windows'], WINDOWS)
        self.profile.write_text('{broken')
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        path = self.output / f'{DATE}.json'
        rows = json.loads(path.read_text())
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows), 120)
        before = path.read_bytes()
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        self.assertEqual(path.read_bytes(), before)

    def test_bad_windows_fail_before_collection_and_preserve_snapshot(self):
        self.assertEqual(self.prepare(), (0, 3))
        before = self.snapshot.read_bytes()
        self.assertEqual(self.prepare('08:00-12:00, 11:00-13:00'), (2, 0))
        self.assertEqual(self.snapshot.read_bytes(), before)
        self.assertEqual(self.invoke('--work-windows', '08:00-12:00', '--work-start', '08:00'), (2, 0))

    def test_assembly_cannot_change_windows(self):
        self.assertEqual(self.prepare(), (0, 3))
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot),
                                     '--work-windows', '08:00-12:00'), (2, 0))

    def test_rehashed_edit_and_schema_downgrade_are_rejected(self):
        self.assertEqual(self.prepare(), (0, 3))
        original = read_snapshot(self.snapshot)
        for edit in ('window', 'version', 'missing'):
            snapshot = copy.deepcopy(original)
            if edit == 'window':
                snapshot['normalized']['work_confirmation']['windows'][0]['end'] = '11:30'
            elif edit == 'version':
                snapshot['schema_version'] = 5
            else:
                del snapshot['normalized']['work_confirmation']['windows']
            snapshot['fingerprint'] = fingerprint({k: v for k, v in snapshot.items() if k != 'fingerprint'})
            self.snapshot.write_text(json.dumps(snapshot))
            with self.assertRaises(SnapshotError):
                read_snapshot(self.snapshot)

    def test_dst_window_boundary_fails_before_collection(self):
        profile = json.loads(self.profile.read_text())
        profile['timezone'] = 'America/New_York'
        self.profile.write_text(json.dumps(profile))
        self.assertEqual(self.invoke('--date', '2026-03-08', '--work-windows', '02:30-04:00'), (2, 0))

    def test_v6_measured_summary_assembles_with_verified_usage(self):
        from unittest.mock import patch
        from run_codex_summary import run_summary
        import test_summary_request as summary_fixture
        self.assertEqual(self.prepare(), (0, 3))
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
        self.assertEqual(sum(b['duration_minutes'] for b in read_snapshot(self.snapshot)['blocks']), 120)


if __name__ == '__main__':
    unittest.main()
