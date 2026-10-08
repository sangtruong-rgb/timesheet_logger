"""F05: Calendar development gaps exclude lunch before qualifying evidence."""
import datetime
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from test_evidence_backed_blocks import DATE, commit, event, model


def estimates(blocks):
    return [(b['start_time'], b['end_time'], b['duration_minutes'])
            for b in blocks if b['time_basis'] == 'estimated']


class TestCalendarGapLunch(unittest.TestCase):
    def test_original_final_gap_is_split_and_total_is_420_not_510(self):
        blocks = build_time_blocks(model([event()], [commit('10:00'), commit('15:00', 'afternoon')]))
        self.assertEqual(estimates(blocks), [('09:30', '12:00', 150), ('13:30', '17:30', 240)])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 420)
        self.assertEqual([[c['hash'] for c in b['commits']] for b in blocks], [[], ['test-commit'], ['afternoon']])

    def test_only_morning_support_keeps_only_morning_segment(self):
        blocks = build_time_blocks(model([event()], [commit('10:00')]))
        self.assertEqual(estimates(blocks), [('09:30', '12:00', 150)])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 180)

    def test_only_afternoon_support_keeps_only_afternoon_segment(self):
        blocks = build_time_blocks(model([event()], [commit('15:00')]))
        self.assertEqual(estimates(blocks), [('13:30', '17:30', 240)])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 270)

    def test_final_event_ending_at_lunch_start_skips_lunch(self):
        blocks = build_time_blocks(model([event('09:00', '12:00', 'Focus')], [commit('15:00')]))
        self.assertEqual(estimates(blocks), [('13:30', '17:30', 240)])

    def test_final_event_ending_inside_lunch_skips_remaining_lunch(self):
        blocks = build_time_blocks(model([event('11:00', '12:30', 'Planning')], [commit('15:00')]))
        self.assertEqual(estimates(blocks), [('13:30', '17:30', 240)])
        self.assertEqual(next(b for b in blocks if b['time_basis'] == 'scheduled')['duration_minutes'], 90)

    def test_final_event_ending_at_lunch_end_keeps_afternoon(self):
        blocks = build_time_blocks(model([event('12:00', '13:30', 'Lunch meeting')], [commit('15:00')]))
        self.assertEqual(estimates(blocks), [('13:30', '17:30', 240)])

    def test_gap_before_first_event_uses_same_lunch_subtraction(self):
        blocks = build_time_blocks(model([event('14:00', '14:30', 'Planning')], [commit('10:00'), commit('13:45', 'afternoon')]))
        self.assertEqual(estimates(blocks), [('09:00', '12:00', 180), ('13:30', '14:00', 30)])

    def test_gap_between_events_uses_same_lunch_subtraction(self):
        blocks = build_time_blocks(model([event(), event('17:30', '18:00', 'Wrap-up')], [commit('10:00'), commit('15:00', 'afternoon')]))
        self.assertEqual(estimates(blocks), [('09:30', '12:00', 150), ('13:30', '17:30', 240)])

    def test_evening_activity_before_evening_meeting_creates_no_development(self):
        activity = commit('19:00')
        meeting = event('20:00', '21:00', 'Evening meeting')
        unassigned = []
        blocks = build_time_blocks(model([meeting], [activity]), unassigned_activity=unassigned)
        self.assertEqual(estimates(blocks), [])
        self.assertEqual([(b['start_time'], b['end_time'], b['duration_minutes'], b['time_basis'])
                          for b in blocks], [('20:00', '21:00', 60, 'scheduled')])
        self.assertEqual(blocks[0]['calendar_events'], [meeting])
        self.assertEqual(unassigned, [{'source': 'git', 'reason': 'outside_blocks', 'activity': activity}])

    def test_supported_gap_before_evening_meeting_ends_at_workday_end(self):
        daytime, evening = commit('15:00', 'daytime'), commit('19:00', 'evening')
        unassigned = []
        blocks = build_time_blocks(model([event(), event('20:00', '21:00')], [daytime, evening]),
                                   unassigned_activity=unassigned)
        self.assertEqual(estimates(blocks), [('13:30', '17:30', 240)])
        self.assertEqual([c for b in blocks for c in b['commits']], [daytime])
        self.assertEqual(unassigned, [{'source': 'git', 'reason': 'outside_blocks', 'activity': evening}])

    def test_gap_between_evening_meetings_does_not_create_development_from_pr(self):
        pr = {'id': 101, 'repository': 'test/project', 'title': 'Payment', 'events': [
            {'action': 'reviewed', 'timestamp': f'{DATE}T19:00:00+07:00', 'id': 1}]}
        unassigned = []
        blocks = build_time_blocks(model([event('18:00', '18:30'), event('20:00', '21:00')], prs=[pr]),
                                   unassigned_activity=unassigned)
        self.assertEqual(estimates(blocks), [])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 90)
        self.assertEqual([e for record in unassigned for e in record['activity']['events']], pr['events'])
        self.assertEqual(unassigned[0]['reason'], 'outside_blocks')

    def test_workday_end_is_exclusive_with_local_and_utc_activity(self):
        for timestamp, supported in ((f'{DATE}T17:29:00+07:00', True),
                                     (f'{DATE}T17:30:00+07:00', False),
                                     (f'{DATE}T10:29:00Z', True), (f'{DATE}T10:30:00Z', False)):
            with self.subTest(timestamp=timestamp):
                activity = {**commit(), 'timestamp': timestamp}
                unassigned = []
                blocks = build_time_blocks(model([event('20:00', '21:00')], [activity]),
                                           unassigned_activity=unassigned)
                self.assertEqual(estimates(blocks), [('13:30', '17:30', 240)] if supported else [])
                self.assertEqual([c for b in blocks for c in b['commits']], [activity] if supported else [])
                self.assertEqual(len(unassigned), 0 if supported else 1)

    def test_minimum_gap_duration_applies_after_workday_clipping(self):
        for end, expected in (('17:00', [('17:00', '17:30', 30)]), ('17:15', [])):
            with self.subTest(end=end):
                activity = commit('17:20')
                unassigned = []
                blocks = build_time_blocks(model([event('13:30', end), event('20:00', '21:00')], [activity]),
                                           unassigned_activity=unassigned)
                self.assertEqual(estimates(blocks), expected)
                self.assertEqual(len(unassigned), 0 if expected else 1)

    def test_gap_entirely_inside_lunch_creates_no_development(self):
        calendars = [event('09:00', '12:00', 'Focus'), event('13:00', '17:30', 'Workshop')]
        unassigned = []
        blocks = build_time_blocks(model(calendars, [commit('12:30')]), unassigned_activity=unassigned)
        self.assertEqual(estimates(blocks), [])
        self.assertEqual(sum(len(b['commits']) for b in blocks), 0)
        self.assertEqual(unassigned[0]['activity'], commit('12:30'))

    def test_lunch_boundaries_are_half_open_for_activity_support(self):
        for time, expected in [('11:59', [('09:30', '12:00', 150)]), ('12:00', []),
                               ('13:29', []), ('13:30', [('13:30', '17:30', 240)])]:
            with self.subTest(time=time):
                unassigned = []
                blocks = build_time_blocks(model([event()], [commit(time)]), unassigned_activity=unassigned)
                self.assertEqual(estimates(blocks), expected)
                self.assertEqual(sum(len(b['commits']) for b in blocks) + len(unassigned), 1)
                self.assertEqual(len(unassigned), 0 if expected else 1)

    def test_minimum_duration_applies_after_lunch_subtraction(self):
        for end, expected in [('13:50', []), ('14:00', [('13:30', '14:00', 30)])]:
            with self.subTest(end=end):
                unassigned = []
                blocks = build_time_blocks(model([event('09:00', '11:50', 'Focus'), event(end, '17:30', 'Workshop')],
                                                [commit('11:55'), commit('13:40', 'afternoon')]), unassigned_activity=unassigned)
                self.assertEqual(estimates(blocks), expected)
                self.assertEqual(sum(len(b['commits']) for b in blocks) + len(unassigned), 2)
                self.assertEqual(len(unassigned), 1 if expected else 2)

    def test_calendar_lunch_meeting_is_retained_whole_with_faithful_title(self):
        blocks = build_time_blocks(model([event('12:00', '13:30', 'Client lunch')]))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]['time_basis'], 'scheduled')
        self.assertEqual(blocks[0]['duration_minutes'], 90)
        self.assertEqual(build_entries(blocks)[0]['entry']['description'], 'Client lunch. PRs: None')

    def test_lunch_only_pr_creates_no_gap_and_evidence_is_preserved(self):
        pr = {'id': 101, 'repository': 'test/project', 'title': 'Payment', 'events': [
            {'action': 'opened', 'timestamp': f'{DATE}T12:30:00+07:00'}]}
        unassigned = []
        blocks = build_time_blocks(model([event()], prs=[pr]), unassigned_activity=unassigned)
        self.assertEqual(estimates(blocks), [])
        self.assertEqual([p for b in blocks for p in b['prs']], [])
        self.assertEqual([e for record in unassigned for e in record['activity']['events']], pr['events'])

    def test_pr_actions_independently_support_both_segments(self):
        pr = {'id': 101, 'repository': 'test/project', 'title': 'Payment', 'events': [
            {'action': 'opened', 'timestamp': f'{DATE}T10:00:00+07:00'},
            {'action': 'merged', 'timestamp': f'{DATE}T15:00:00+07:00'}]}
        blocks = build_time_blocks(model([event()], prs=[pr]))
        self.assertEqual(estimates(blocks), [('09:30', '12:00', 150), ('13:30', '17:30', 240)])
        self.assertEqual([e for b in blocks for p in b['prs'] for e in p['events']], pr['events'])

    def test_equivalent_utc_activity_at_lunch_end_supports_afternoon(self):
        activity = {**commit(), 'timestamp': f'{DATE}T06:30:00Z'}
        blocks = build_time_blocks(model([event()], [activity]))
        self.assertEqual(estimates(blocks), [('13:30', '17:30', 240)])
        self.assertEqual(blocks[-1]['commits'], [activity])

    def test_range_of_calendar_positions_never_produces_lunch_overlap(self):
        tz = datetime.timezone(datetime.timedelta(hours=7))
        activities = [commit(f'{h:02d}:{m:02d}', f'{h}-{m}') for h in range(9, 18) for m in (0, 30)]
        for start in ('09:00', '11:30', '12:00', '12:30', '13:00', '13:30', '16:30'):
            dt = datetime.datetime.fromisoformat(f'{DATE}T{start}:00+07:00')
            end = (dt + datetime.timedelta(minutes=30)).strftime('%H:%M')
            with self.subTest(start=start):
                blocks = build_time_blocks(model([event(start, end)], activities))
                for block in blocks:
                    if block['time_basis'] != 'estimated':
                        continue
                    self.assertTrue(block['end_time'] <= '12:00' or block['start_time'] >= '13:30')
                    self.assertGreaterEqual(block['duration_minutes'], 30)
                    self.assertEqual(block['calendar_titles'], [])
                    bounds = [datetime.datetime.combine(datetime.date.fromisoformat(DATE), datetime.time.fromisoformat(block[key]), tzinfo=tz)
                              for key in ('start_time', 'end_time')]
                    self.assertTrue(any(bounds[0] <= datetime.datetime.fromisoformat(c['timestamp']) < bounds[1] for c in activities))

    def test_no_calendar_workday_policy_is_unchanged_pending_d02(self):
        blocks = build_time_blocks(model(commits=[commit('10:00')]))
        self.assertEqual(estimates(blocks), [('09:00', '12:30', 210)])
        self.assertEqual(blocks[0]['estimation_reason'], 'activity_workday_window')

    def test_unsupported_segments_are_not_created(self):
        blocks = build_time_blocks(model([event()]))
        self.assertEqual(estimates(blocks), [])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 30)


if __name__ == '__main__':
    unittest.main()
