"""One daily OT decision counts only confirmed work outside the main windows."""
import copy
import json
import unittest
from unittest.mock import patch

from test_work_windows import window_model, WINDOWS
from test_commit_intervals import DATE, commit, event, pr, intervals
import test_commit_intervals as fixture
from overtime import initial_review, overtime_evidence, default_overtime_windows, confirmation_question, validate_review, resolve_snapshot
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from prepare_ai_input import prepare_activity_input
from summary_request import commit_group_mapping
from activity_snapshot import read_snapshot, save_snapshot, fingerprint, SnapshotError
from run_codex_summary import run_summary
from save_timesheet import render_markdown, save_timesheet, TimesheetReconciliationError


def model(commits=None, calendar=None, prs=None):
    value = window_model(commits, calendar)
    value['pull_requests'] = prs or []
    value['overtime_review'] = initial_review(value, default_policy=False)
    return value


def confirmed(value, text_windows):
    from work_windows import parse_work_windows
    value = copy.deepcopy(value)
    value['overtime_review'].update(status='confirmed', confirmed_windows=parse_work_windows(text_windows))
    return value


def automatic_model(commits=None, calendar=None, prs=None):
    value = window_model(commits, calendar)
    value['pull_requests'] = prs or []
    value['overtime_review'] = initial_review(value)
    return value


class TestDefaultOvertime(unittest.TestCase):
    def test_hour_ends_at_commit_and_proceeds_without_confirmation(self):
        value = automatic_model([commit('18:00')])
        self.assertEqual(default_overtime_windows(value), [{'start': '17:00', 'end': '18:00'}])
        self.assertEqual(value['overtime_review']['status'], 'defaulted')
        self.assertIsNone(confirmation_question(value))
        blocks = build_time_blocks(value)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks if b['work_type'] == 'OT'), 60)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks if b['work_type'] == 'NORMAL'), 390)
        rows = build_entries(blocks)
        self.assertEqual([r for r in rows if r['work_type'] == 'OT'][0]['overtime_confirmation']['approval_basis'], 'default_commit_hour')

    def test_overlaps_with_main_only_count_outside_minutes(self):
        value = automatic_model([commit('16:20')])
        self.assertEqual(default_overtime_windows(value), [{'start': '16:00', 'end': '16:20'}])
        self.assertEqual(sum(b['duration_minutes'] for b in build_time_blocks(value) if b['work_type'] == 'OT'), 20)

    def test_main_commit_does_not_generate_default_ot(self):
        value = automatic_model([commit('08:30'), commit('12:00'), commit('16:00')])
        self.assertEqual(default_overtime_windows(value), [])
        self.assertEqual(value['overtime_review']['status'], 'not_needed')

    def test_overlapping_duplicate_and_simultaneous_commits_count_union(self):
        activities = [commit('18:00', 'a'), commit('18:30', 'b'), commit('18:30', 'c')]
        value = automatic_model(activities)
        self.assertEqual(default_overtime_windows(value), [{'start': '17:00', 'end': '18:30'}])
        review = []
        ot = [b for b in build_time_blocks(value, unassigned_activity=review) if b['work_type'] == 'OT']
        self.assertEqual(sum(b['duration_minutes'] for b in ot), 90)
        self.assertEqual({c['hash'] for b in ot for c in b['commits']}, {'a', 'b', 'c'})
        self.assertEqual(review, [])
        self.assertEqual(default_overtime_windows(automatic_model(list(reversed(activities)))), default_overtime_windows(value))

    def test_separate_commit_hours_do_not_fill_idle_gap(self):
        value = automatic_model([commit('18:00'), commit('21:00', 'b')])
        self.assertEqual(default_overtime_windows(value), [{'start': '17:00', 'end': '18:00'}, {'start': '20:00', 'end': '21:00'}])
        self.assertEqual(sum(b['duration_minutes'] for b in build_time_blocks(value) if b['work_type'] == 'OT'), 120)

    def test_before_main_and_lunch_default_windows(self):
        value = automatic_model([commit('07:00'), commit('13:00', 'lunch')])
        self.assertEqual(default_overtime_windows(value), [{'start': '06:00', 'end': '07:00'}])

    def test_lunch_commit_is_evidence_without_counted_time(self):
        value = automatic_model([commit('13:09', 'lunch')])
        self.assertEqual(value['overtime_review']['status'], 'not_needed')
        self.assertEqual(len(value['overtime_review']['observations']), 1)
        blocks = build_time_blocks(value)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 390)
        self.assertTrue(all(b['work_type'] == 'NORMAL' for b in blocks))

    def test_breaks_clip_both_sides_of_default_hour(self):
        value = window_model([commit('13:45')], text='08:00-11:00, 14:00-16:00')
        self.assertEqual(default_overtime_windows(value), [{'start': '13:30', 'end': '13:45'}])
        value['commits'] = [commit('12:15')]
        self.assertEqual(default_overtime_windows(value), [{'start': '11:15', 'end': '12:00'}])

    def test_frozen_custom_breaks_and_no_breaks_are_respected(self):
        value = window_model([commit('18:00')])
        value['work_schedule'] = {'breaks': [{'start': '17:15', 'end': '17:45'}]}
        self.assertEqual(default_overtime_windows(value), [
            {'start': '17:00', 'end': '17:15'}, {'start': '17:45', 'end': '18:00'}])
        value['work_schedule'] = {'breaks': []}
        self.assertEqual(default_overtime_windows(value), [{'start': '17:00', 'end': '18:00'}])

    def test_legacy_policy_reproduces_frozen_lunch_windows(self):
        from overtime import LEGACY_OT_POLICY
        value = automatic_model([commit('13:00')])
        value['overtime_review'].update(status='defaulted', policy=copy.deepcopy(LEGACY_OT_POLICY),
                                      confirmed_windows=[{'start': '12:00', 'end': '13:00'}])
        validate_review(value)
        self.assertEqual(sum(b['duration_minutes'] for b in build_time_blocks(value)
                             if b['work_type'] == 'OT'), 60)

    def test_midnight_clips_to_this_day(self):
        value = automatic_model([commit('00:30')])
        self.assertEqual(default_overtime_windows(value), [{'start': '00:00', 'end': '00:30'}])
        self.assertEqual(sum(b['duration_minutes'] for b in build_time_blocks(value) if b['work_type'] == 'OT'), 30)

    def test_two_midnight_commits_union_without_double_counting(self):
        activities = [commit('00:10', 'early'), commit('00:50', 'late')]
        value = automatic_model(activities)
        self.assertEqual(default_overtime_windows(value), [{'start': '00:00', 'end': '00:50'}])
        review = []
        ot = [b for b in build_time_blocks(value, unassigned_activity=review) if b['work_type'] == 'OT']
        self.assertEqual(intervals(ot), [('00:00', '00:10', 10), ('00:10', '00:50', 40)])
        self.assertEqual(sum(b['duration_minutes'] for b in ot), 50)
        self.assertEqual([[c['hash'] for c in b['commits']] for b in ot], [['early'], ['late']])
        self.assertEqual(review, [])
        reversed_blocks = build_time_blocks(automatic_model(list(reversed(activities))))
        self.assertEqual(ot, [b for b in reversed_blocks if b['work_type'] == 'OT'])

    def test_second_precision_keeps_closing_commit_and_matching_merge(self):
        activity = commit('18:00')
        activity['timestamp'] = DATE + 'T18:00:59+07:00'
        merge = {**pr('18:00', 1), 'timestamp': activity['timestamp'], 'status': 'merged', 'merge_commit_sha': 'c1'}
        value = automatic_model([activity], prs=[merge])
        self.assertEqual(default_overtime_windows(value), [{'start': '17:00', 'end': '18:00'}])
        review = []
        ot = [b for b in build_time_blocks(value, unassigned_activity=review) if b['work_type'] == 'OT']
        self.assertEqual({c['hash'] for b in ot for c in b['commits']}, {'c1'})
        self.assertEqual({p['id'] for b in ot for p in b['prs']}, {1})
        self.assertEqual(review, [])

    def test_pr_and_calendar_alone_do_not_invent_commit_hours(self):
        value = automatic_model(calendar=[event('17:00', '18:00')], prs=[pr('18:00', 1)])
        self.assertEqual(default_overtime_windows(value), [])
        self.assertEqual(value['overtime_review']['status'], 'not_needed')
        self.assertIsNone(confirmation_question(value))
        self.assertTrue(all(b['work_type'] == 'NORMAL' for b in build_time_blocks(value)))

    def test_calendar_inside_default_hour_is_counted_once_with_attendance_unconfirmed(self):
        value = automatic_model([commit('18:00')], calendar=[event('17:15', '17:45')])
        ot = [r for r in build_entries(build_time_blocks(value)) if r['work_type'] == 'OT']
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in ot), 60)
        scheduled = [r for r in ot if r['time_basis'] == 'scheduled']
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]['attendance'], 'unconfirmed')

    def test_modified_default_hours_or_policy_are_rejected(self):
        original = automatic_model([commit('18:00')])
        for change in ('hours', 'minutes', 'status'):
            value = copy.deepcopy(original)
            if change == 'hours':
                value['overtime_review']['confirmed_windows'][0]['start'] = '16:00'
            elif change == 'minutes':
                value['overtime_review']['policy']['default_minutes'] = 120
            else:
                value['overtime_review']['status'] = 'not_needed'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_review(value)


class TestOvertime(unittest.TestCase):
    def test_late_commit_does_not_fill_two_hour_gap(self):
        value = model([commit('18:00')])
        self.assertEqual(overtime_evidence(value), [{'source': 'git', 'timestamp': DATE + 'T18:00:00+07:00'}])
        self.assertFalse(any('start' in item for item in overtime_evidence(value)))
        self.assertEqual(sum(b['duration_minutes'] for b in build_time_blocks(value)), 390)
        self.assertTrue(all(b['work_type'] == 'NORMAL' for b in build_time_blocks(value)))
        self.assertIn('commit lúc 18:00', confirmation_question(value))
        self.assertIn('bắt đầu–kết thúc thực tế', confirmation_question(value))
        self.assertNotIn('16:00–18:00', confirmation_question(value))

    def test_all_candidates_use_one_question(self):
        value = model([commit('07:45'), commit('18:00')], prs=[pr('20:00', 1)])
        question = confirmation_question(value)
        self.assertEqual(question.count('?'), 1)
        for text in ('commit lúc 07:45', 'commit lúc 18:00', 'PR lúc 20:00', DATE):
            self.assertIn(text, question)

    def test_main_boundary_commit_and_main_activity_do_not_propose_ot(self):
        value = model([commit('08:00'), commit('12:00'), commit('16:00')], prs=[pr('14:00', 1)])
        self.assertEqual(value['overtime_review']['status'], 'not_needed')
        self.assertIsNone(confirmation_question(value))

    def test_proven_merge_at_main_boundary_does_not_ask_spurious_ot(self):
        action = {**pr('16:00', 1), 'status': 'merged', 'merge_commit_sha': 'closing'}
        value = model([commit('16:00', 'closing')], prs=[action])
        self.assertEqual(overtime_evidence(value), [])
        self.assertIsNone(confirmation_question(value))
        action['merge_commit_sha'] = 'other'
        self.assertEqual(overtime_evidence(model([commit('16:00', 'closing')], prs=[action])),
                         [{'source': 'github', 'timestamp': DATE + 'T16:00:00+07:00'}])

    def test_lunch_gap_is_not_filled_without_evidence_and_confirmation(self):
        value = model([commit('13:00')])
        self.assertEqual(overtime_evidence(value), [{'source': 'git', 'timestamp': DATE + 'T13:00:00+07:00'}])
        self.assertEqual(sum(b['duration_minutes'] for b in build_time_blocks(value)), 390)
        value = confirmed(value, '13:00-13:15')
        blocks = build_time_blocks(value)
        self.assertEqual([(b['start_time'], b['end_time']) for b in blocks if b['work_type'] == 'OT'], [('13:00', '13:15')])

    def test_confirmed_ot_adds_exact_windows_with_gap_unfilled(self):
        value = confirmed(model([commit('18:00')]), '18:00-20:00')
        blocks = build_time_blocks(value)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks if b['work_type'] == 'NORMAL'), 390)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks if b['work_type'] == 'OT'), 120)
        self.assertFalse(any(b['start_time'] == '16:00' for b in blocks))
        entries = build_entries(blocks)
        self.assertTrue(all(e['overtime_confirmation']['status'] == 'confirmed' for e in entries if e['work_type'] == 'OT'))
        markdown = render_markdown(DATE, entries)
        self.assertIn('NORMAL: 390 mins; OT (confirmed): 120 mins', markdown)

    def test_user_supplies_start_and_end_instead_of_commit_inference(self):
        value = confirmed(model([commit('18:00')]), '17:00-18:40')
        ot = [b for b in build_time_blocks(value) if b['work_type'] == 'OT']
        self.assertEqual(ot[0]['start_time'], '17:00')
        self.assertEqual(ot[-1]['end_time'], '18:40')
        self.assertEqual(sum(b['duration_minutes'] for b in ot), 100)
        self.assertFalse(any(b['start_time'] == '16:00' for b in ot))

    def test_explicit_ot_confirmation_can_have_no_source_activity(self):
        value = model()
        self.assertEqual(value['overtime_review']['status'], 'not_needed')
        self.assertIsNone(confirmation_question(value))
        value = confirmed(value, '17:00-18:00')
        ot = [b for b in build_time_blocks(value) if b['work_type'] == 'OT']
        self.assertEqual(intervals(ot), [('17:00', '18:00', 60)])

    def test_retained_evidence_is_not_duplicated_by_ot_building(self):
        for status in ('pending', 'confirmed'):
            value = model([commit('18:00')])
            retained = {'source': 'git', 'reason': 'missing_timestamp', 'activity': {'hash': 'missing'}}
            value['unassigned_activity'] = [retained]
            if status == 'confirmed':
                value = confirmed(value, '17:00-18:00')
            review = []
            build_time_blocks(value, unassigned_activity=review)
            self.assertEqual(review.count(retained), 1)

    def test_declining_ot_keeps_main_and_outside_evidence(self):
        value = model([commit('18:00')])
        value['overtime_review']['status'] = 'declined'
        review = []
        blocks = build_time_blocks(value, unassigned_activity=review)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 390)
        self.assertEqual(review[0]['activity']['hash'], 'c1')
        self.assertIsNone(confirmation_question(value))

    def test_calendar_candidate_and_confirmation_preserve_unconfirmed_attendance(self):
        value = model(calendar=[event('15:30', '17:00')])
        self.assertEqual(overtime_evidence(value), [{'source': 'google_calendar', 'start': DATE + 'T16:00:00+07:00', 'end': DATE + 'T17:00:00+07:00'}])
        value = confirmed(value, '16:00-17:00')
        entries = build_entries(build_time_blocks(value))
        ot = [e for e in entries if e['work_type'] == 'OT']
        self.assertEqual(len(ot), 1)
        self.assertEqual(ot[0]['attendance'], 'unconfirmed')
        self.assertEqual(ot[0]['entry']['duration_minutes'], 60)
        self.assertEqual(sum(e['entry']['duration_minutes'] for e in entries), 450)

    def test_crossing_normal_ot_splits_rows_and_shares_description(self):
        value = confirmed(model([commit('18:00')]), '16:00-18:00')
        blocks = build_time_blocks(value)
        self.assertEqual(intervals(blocks), [('08:00', '12:00', 240), ('13:30', '16:00', 150), ('16:00', '18:00', 120)])
        self.assertEqual([b['work_type'] for b in blocks], ['NORMAL', 'NORMAL', 'OT'])
        payload = prepare_activity_input(blocks, [])
        self.assertEqual(len(payload['summary_request']['jobs']), 1)
        judgments = [{'block_id': b['block_id'], 'description': 'Shared topic.'} for b in payload['blocks']]
        entries = build_entries(blocks, judgments, summary_groups=commit_group_mapping(payload['blocks']))
        self.assertEqual(len({e['entry']['description'] for e in entries}), 1)

    def test_short_ot_does_not_merge_backward_into_normal(self):
        value = confirmed(model([commit('16:00', 'normal'), commit('16:10', 'ot')]), '16:00-16:30')
        blocks = build_time_blocks(value)
        normal = [b for b in blocks if b['work_type'] == 'NORMAL']
        ot = [b for b in blocks if b['work_type'] == 'OT']
        self.assertEqual({c['hash'] for b in normal for c in b['commits']}, {'normal'})
        self.assertEqual({c['hash'] for b in ot for c in b['commits']}, {'ot'})
        self.assertNotEqual(normal[0]['allocation']['summary_group_id'], ot[0]['allocation']['summary_group_id'])

    def test_short_ot_still_merges_with_previous_ot(self):
        value = confirmed(model([commit('18:30', 'first'), commit('18:40', 'short')]), '18:00-19:00')
        ot = [b for b in build_time_blocks(value) if b['work_type'] == 'OT']
        self.assertEqual(intervals(ot), [('18:00', '18:40', 40), ('18:40', '19:00', 20)])
        self.assertEqual({c['hash'] for c in ot[0]['commits']}, {'first', 'short'})

    def test_unknown_naive_and_other_day_timestamps_do_not_create_ot(self):
        commits = [commit('18:00', name) for name in ('missing', 'bad', 'naive', 'other')]
        for activity, stamp in zip(commits, (None, 'bad', DATE + 'T18:00:00', '2026-10-08T18:00:00+07:00')):
            activity['timestamp'] = stamp
        self.assertEqual(overtime_evidence(model(commits)), [])

    def test_all_day_calendar_is_context_not_ot(self):
        calendar = [{'title': 'Holiday', 'start': DATE, 'end': '2026-10-08', 'all_day': True}]
        self.assertEqual(overtime_evidence(model(calendar=calendar)), [])

    def test_midnight_ot_and_clock_precision(self):
        value = confirmed(model([commit('23:55')]), '23:45-24:00')
        ot = [b for b in build_time_blocks(value) if b['work_type'] == 'OT']
        self.assertEqual(sum(b['duration_minutes'] for b in ot), 15)
        self.assertEqual(ot[-1]['end_time'], '24:00')

    def test_review_rejects_overlapping_unconfirmed_and_tampered_windows(self):
        original = model([commit('18:00')])
        for change in ('overlap', 'unconfirmed', 'candidates', 'status'):
            value = copy.deepcopy(original)
            if change == 'overlap':
                value = confirmed(value, '15:00-18:00')
            elif change == 'unconfirmed':
                value['overtime_review']['confirmed_windows'] = [{'start': '18:00', 'end': '19:00'}]
            elif change == 'candidates':
                value['overtime_review']['observations'] = []
            else:
                value['overtime_review']['status'] = 'not_needed'
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_review(value)


class TestDefaultOTPipeline(unittest.TestCase):
    setUp = fixture.TestPipelineCommitIntervals.setUp
    invoke = fixture.TestPipelineCommitIntervals.invoke

    def prepare(self):
        self.activities = [commit('18:00')]
        return self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot),
                           '--work-windows', '08:00-12:00, 13:30-16:00', '--review-ot')

    def resolve(self, *decision):
        return self.invoke('--phase', 'confirm-ot', '--snapshot', str(self.snapshot),
                           '--resolved-snapshot', str(self.root / 'resolved.json'), *decision)

    def test_v8_default_is_approved_and_assembles_without_question_or_collection(self):
        self.assertEqual(self.prepare(), (0, 3))
        frozen = read_snapshot(self.snapshot)
        self.assertEqual(frozen['schema_version'], 10)
        self.assertEqual(frozen['normalized']['overtime_review']['status'], 'defaulted')
        self.profile.write_text('{invalid')
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        path = self.output / f'{DATE}.json'
        rows = json.loads(path.read_text())
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows if r['work_type'] == 'OT'), 60)
        before = path.read_bytes()
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        self.assertEqual(path.read_bytes(), before)

    def test_requested_override_preserves_default_source(self):
        self.assertEqual(self.prepare(), (0, 3))
        before = self.snapshot.read_bytes()
        self.assertEqual(self.resolve('--ot-windows', '17:30-18:00'), (0, 0))
        frozen = read_snapshot(self.root / 'resolved.json')
        review = frozen['normalized']['overtime_review']
        self.assertEqual(review['status'], 'confirmed')
        self.assertEqual(review['confirmed_windows'], [{'start': '17:30', 'end': '18:00'}])
        self.assertEqual(self.snapshot.read_bytes(), before)
        self.assertEqual(sum(b['duration_minutes'] for b in frozen['blocks'] if b['work_type'] == 'OT'), 30)

    def test_two_midnight_commits_preserve_fifty_minutes_in_snapshot_and_output(self):
        self.activities = [commit('00:10', 'early'), commit('00:50', 'late')]
        self.assertEqual(self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot),
                                     '--work-windows', '08:00-12:00, 13:30-16:00', '--review-ot'), (0, 3))
        frozen = read_snapshot(self.snapshot)
        self.assertEqual(frozen['normalized']['overtime_review']['confirmed_windows'],
                         [{'start': '00:00', 'end': '00:50'}])
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        manifest = json.loads((self.output / f'{DATE}.collection.json').read_text())
        self.assertEqual(manifest['work_type_totals'], {'NORMAL': 0, 'OT': 50, 'unclassified': 0})
        path = self.output / f'{DATE}.json'
        before = path.read_bytes()
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (0, 0))
        self.assertEqual(path.read_bytes(), before)

    def test_requested_decline_removes_ot(self):
        self.assertEqual(self.prepare(), (0, 3))
        self.assertEqual(self.resolve('--decline-ot'), (0, 0))
        frozen = read_snapshot(self.root / 'resolved.json')
        self.assertEqual(frozen['normalized']['overtime_review']['status'], 'declined')
        self.assertTrue(all(b['work_type'] == 'NORMAL' for b in frozen['blocks']))

    def test_rehashed_default_change_and_v7_downgrade_are_rejected(self):
        self.assertEqual(self.prepare(), (0, 3))
        original = read_snapshot(self.snapshot)
        for change in ('version', 'hours'):
            frozen = copy.deepcopy(original)
            if change == 'version':
                frozen['schema_version'] = 7
            else:
                for target in (frozen['normalized'], frozen['collection']):
                    target['overtime_review']['confirmed_windows'][0]['start'] = '16:00'
            frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
            self.snapshot.write_text(json.dumps(frozen))
            with self.assertRaises(SnapshotError):
                read_snapshot(self.snapshot)

    def test_default_runs_measured_summary_without_manual_confirmation(self):
        import test_summary_request as summary_fixture
        self.assertEqual(self.prepare(), (0, 3))
        process = summary_fixture.TestSummaryRequest.fake_process.__get__(self)
        with patch('run_codex_summary.subprocess.run', side_effect=process):
            result = run_summary(self.snapshot, self.root / 'codex', model='synthetic-test-model')
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot),
                                     '--ai-output', result['ai_output'],
                                     '--usage-run-manifest', result['usage_run_manifest'],
                                     '--token-csv-path', str(self.root / 'tokens.csv')), (0, 0))
        manifest = json.loads((self.output / f'{DATE}.collection.json').read_text())
        self.assertEqual(manifest['token_usage']['total_tokens'], 165)
        self.assertEqual(manifest['work_type_totals'], {'NORMAL': 390, 'OT': 60, 'unclassified': 0})


class TestOTPipeline(unittest.TestCase):
    setUp = fixture.TestPipelineCommitIntervals.setUp
    invoke = fixture.TestPipelineCommitIntervals.invoke

    def prepare(self):
        self.activities = [commit('18:00')]
        with patch('overtime.initial_review', side_effect=lambda value: initial_review(value, default_policy=False)):
            return self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot),
                               '--work-windows', '08:00-12:00, 13:30-16:00', '--review-ot')

    def resolve(self, *decision):
        return self.invoke('--phase', 'confirm-ot', '--snapshot', str(self.snapshot),
                           '--resolved-snapshot', str(self.root / 'resolved.json'), *decision)

    def test_pending_stops_assembly_and_model_call(self):
        self.assertEqual(self.prepare(), (0, 3))
        self.assertEqual(read_snapshot(self.snapshot)['schema_version'], 10)
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(self.snapshot)), (2, 0))
        self.assertFalse((self.output / f'{DATE}.json').exists())
        with patch('run_codex_summary.subprocess.run') as call, self.assertRaisesRegex(ValueError, 'pending'):
            run_summary(self.snapshot, self.root / 'codex')
        call.assert_not_called()
        self.assertFalse((self.root / 'codex').exists())

    def test_confirm_uses_frozen_sources_and_preserves_original_then_assembles(self):
        self.assertEqual(self.prepare(), (0, 3))
        before = self.snapshot.read_bytes()
        self.profile.write_text('{invalid profile')
        self.assertEqual(self.resolve('--ot-windows', '16:00-18:00'), (0, 0))
        path = self.root / 'resolved.json'
        frozen = read_snapshot(path)
        self.assertNotEqual(frozen['run_id'], read_snapshot(self.snapshot)['run_id'])
        self.assertEqual(self.snapshot.read_bytes(), before)
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(path)), (0, 0))
        output = self.output / f'{DATE}.json'
        rows = json.loads(output.read_text())
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows if r['work_type'] == 'OT'), 120)
        previous = output.read_bytes()
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(path)), (0, 0))
        self.assertEqual(output.read_bytes(), previous)

    def test_decline_counts_no_ot_and_does_not_recollect(self):
        self.assertEqual(self.prepare(), (0, 3))
        self.assertEqual(self.resolve('--decline-ot'), (0, 0))
        path = self.root / 'resolved.json'
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(path)), (0, 0))
        rows = json.loads((self.output / f'{DATE}.json').read_text())
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows), 0)
        self.assertTrue(all(r['work_type'] == 'NORMAL' for r in rows))

    def test_invalid_decisions_preserve_source_and_output(self):
        self.assertEqual(self.prepare(), (0, 3))
        before = self.snapshot.read_bytes()
        for args in ((), ('--ot-windows', '16:00-18:00', '--decline-ot'),
                     ('--ot-windows', '15:00-18:00'), ('--ot-windows', '23:00-01:00')):
            self.assertEqual(self.resolve(*args), (2, 0))
            self.assertEqual(self.snapshot.read_bytes(), before)
            self.assertFalse((self.root / 'resolved.json').exists())
        self.assertEqual(self.invoke('--phase', 'confirm-ot', '--snapshot', str(self.snapshot),
                                     '--resolved-snapshot', str(self.snapshot), '--decline-ot'), (2, 0))
        self.assertEqual(self.invoke('--ot-windows', '18:00-19:00'), (2, 0))
        self.assertEqual(self.invoke('--review-ot', '--work-start', '09:00'), (2, 0))

    def test_resolved_run_cannot_request_confirmation_again(self):
        self.assertEqual(self.prepare(), (0, 3))
        self.assertEqual(self.resolve('--decline-ot'), (0, 0))
        with self.assertRaisesRegex(ValueError, 'already resolved'):
            resolve_snapshot(self.root / 'resolved.json', self.root / 'again.json', decline=True)

    def test_rehashed_review_change_and_downgrade_are_rejected(self):
        self.activities = [commit('10:00', 'normal'), commit('18:00', 'late')]
        with patch('overtime.initial_review', side_effect=lambda value: initial_review(value, default_policy=False)):
            self.assertEqual(self.invoke('--phase', 'prepare', '--snapshot', str(self.snapshot),
                                         '--work-windows', '08:00-12:00, 13:30-16:00', '--review-ot'), (0, 3))
        original = read_snapshot(self.snapshot)
        for edit in ('candidate', 'version', 'row'):
            frozen = copy.deepcopy(original)
            if edit == 'candidate':
                frozen['normalized']['overtime_review']['observations'] = []
            elif edit == 'version':
                frozen['schema_version'] = 6
            else:
                frozen['blocks'][0]['work_type'] = 'OT'
            frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
            self.snapshot.write_text(json.dumps(frozen))
            with self.assertRaises(SnapshotError):
                read_snapshot(self.snapshot)

    def test_writer_rejects_unconfirmed_ot_and_preserves_files(self):
        rows = build_entries(build_time_blocks(confirmed(model([commit('18:00')]), '16:00-18:00')))
        save_timesheet(rows, self.output, target_date=DATE, collection_status='complete')
        before = {p: p.read_bytes() for p in self.output.glob(f'{DATE}.*')}
        bad = copy.deepcopy(rows)
        for row in bad:
            if row['work_type'] == 'OT':
                row['overtime_confirmation']['status'] = 'pending'
        with self.assertRaises(TimesheetReconciliationError):
            save_timesheet(bad, self.output, target_date=DATE, collection_status='complete')
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_resolved_v7_runs_measured_summary_with_verified_usage(self):
        import test_summary_request as summary_fixture
        self.assertEqual(self.prepare(), (0, 3))
        self.assertEqual(self.resolve('--ot-windows', '16:00-18:00'), (0, 0))
        path = self.root / 'resolved.json'
        process = summary_fixture.TestSummaryRequest.fake_process.__get__(self)
        with patch('run_codex_summary.subprocess.run', side_effect=process):
            result = run_summary(path, self.root / 'codex', model='synthetic-test-model')
        self.assertEqual(self.invoke('--phase', 'assemble', '--snapshot', str(path),
                                     '--ai-output', result['ai_output'],
                                     '--usage-run-manifest', result['usage_run_manifest'],
                                     '--token-csv-path', str(self.root / 'tokens.csv')), (0, 0))
        manifest = json.loads((self.output / f'{DATE}.collection.json').read_text())
        self.assertEqual(manifest['token_usage']['total_tokens'], 165)
        self.assertEqual(manifest['overtime_review']['status'], 'confirmed')
        self.assertEqual(manifest['work_type_totals'], {'NORMAL': 390, 'OT': 120, 'unclassified': 0})


if __name__ == '__main__':
    unittest.main()
