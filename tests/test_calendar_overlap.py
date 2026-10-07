"""F06: scheduled coverage is counted once and conflicting attendance needs review."""
import copy
import itertools
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from block_identity import BlockIdentityError
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from normalize_activity import normalize_all
from prepare_ai_input import prepare_all_blocks
from save_timesheet import render_markdown
from test_evidence_backed_blocks import DATE, event, commit, model


def meetings():
    return [event('09:00', '10:00', 'Meeting A'), event('09:30', '10:30', 'Meeting B')]


def intervals(blocks):
    return [(b['start_time'], b['end_time']) for b in blocks]


class TestCalendarOverlap(unittest.TestCase):
    def test_partial_overlap_counts_90_not_120(self):
        blocks = build_time_blocks(model(meetings()))
        self.assertEqual(intervals(blocks), [('09:00', '09:30'), ('09:30', '10:00'), ('10:00', '10:30')])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 90)
        self.assertEqual([b['calendar_titles'] for b in blocks], [['Meeting A'], ['Meeting A', 'Meeting B'], ['Meeting B']])
        self.assertEqual([b.get('calendar_overlap', False) for b in blocks], [False, True, False])

    def test_nested_event_counts_outer_duration_once(self):
        blocks = build_time_blocks(model([event('09:00', '11:00', 'A'), event('09:30', '10:00', 'B')]))
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 120)
        self.assertEqual(intervals(blocks), [('09:00', '09:30'), ('09:30', '10:00'), ('10:00', '11:00')])

    def test_identical_intervals_produce_one_identity_and_keep_both_sources(self):
        events = [event('09:00', '10:00', 'A'), event('09:00', '10:00', 'B')]
        blocks = build_time_blocks(model(events))
        entries = build_entries(blocks)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['entry']['duration_minutes'], 60)
        self.assertEqual(entries[0]['sources']['calendar_events'], events)
        self.assertEqual(entries[0]['block_id'], DATE + '_09:00_10:00')

    def test_triple_overlap_counts_union_with_all_three_sources(self):
        events = [event('09:00', '11:00', 'A'), event('09:30', '10:30', 'B'), event('10:00', '12:00', 'C')]
        blocks = build_time_blocks(model(events))
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 180)
        middle = next(b for b in blocks if b['start_time'] == '10:00')
        self.assertEqual(middle['calendar_titles'], ['A', 'B', 'C'])
        self.assertEqual(len(middle['calendar_events']), 3)

    def test_touching_events_are_not_overlaps(self):
        blocks = build_time_blocks(model([event('09:00', '09:30', 'A'), event('09:30', '10:00', 'B')]))
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 60)
        self.assertFalse(any(b.get('calendar_overlap') for b in blocks))

    def test_disjoint_events_create_no_unsupported_gap(self):
        blocks = build_time_blocks(model([event('09:00', '09:30', 'A'), event('10:00', '10:30', 'B')]))
        self.assertEqual(intervals(blocks), [('09:00', '09:30'), ('10:00', '10:30')])
        self.assertFalse(any(b.get('review') for b in blocks))

    def test_input_order_does_not_change_sources_ids_or_review(self):
        events = meetings() + [event('09:45', '10:15', 'C')]
        expected = build_entries(build_time_blocks(model(events)))
        for order in itertools.permutations(events):
            self.assertEqual(build_entries(build_time_blocks(model(list(order)))), expected)

    def test_source_records_retain_original_boundaries_without_mutation(self):
        data = model(meetings()); original = copy.deepcopy(data)
        entries = build_entries(build_time_blocks(data))
        self.assertEqual(data, original)
        self.assertEqual(entries[1]['sources']['calendar_events'], meetings())
        self.assertEqual(entries[0]['sources']['calendar_events'], [meetings()[0]])

    def test_equal_titles_still_keep_distinct_event_intervals_and_overlap(self):
        events = [event('09:00', '10:00', 'Same title'), event('09:30', '10:30', 'Same title')]
        middle = build_time_blocks(model(events))[1]
        self.assertEqual(middle['calendar_titles'], ['Same title'])
        self.assertEqual(len(middle['calendar_events']), 2)
        self.assertTrue(middle['calendar_overlap'])

    def test_normalizer_duplicate_record_does_not_create_false_overlap(self):
        single = event('09:00', '10:00', 'A')
        normalized = normalize_all(DATE, [], [], [single, single])
        blocks = build_time_blocks(normalized)
        self.assertEqual(len(blocks), 1)
        self.assertFalse(blocks[0].get('calendar_overlap'))

    def test_utc_equivalent_events_partition_in_calendar_timezone(self):
        events = [meetings()[0], {**meetings()[1], 'start': DATE + 'T02:30:00Z', 'end': DATE + 'T03:30:00Z'}]
        blocks = build_time_blocks(model(events))
        self.assertEqual(intervals(blocks), [('09:00', '09:30'), ('09:30', '10:00'), ('10:00', '10:30')])
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 90)
        self.assertEqual(blocks[1]['calendar_events'][1]['start'], DATE + 'T02:30:00Z')

    def test_commits_on_boundaries_attach_once_to_correct_partition(self):
        activities = [commit('09:15', 'a'), commit('09:30', 'b'), commit('10:00', 'c')]
        blocks = build_time_blocks(model(meetings(), activities))
        self.assertEqual([[c['hash'] for c in b['commits']] for b in blocks], [['a'], ['b'], ['c']])

    def test_pr_actions_attach_once_and_preserve_history(self):
        pr = {'id': 101, 'repository': 'test/project', 'title': 'PR', 'events': [
            {'action': a, 'timestamp': f'{DATE}T{t}:00+07:00'} for a, t in
            [('opened', '09:15'), ('reviewed', '09:45'), ('merged', '10:15')]]}
        blocks = build_time_blocks(model(meetings(), prs=[pr]))
        self.assertEqual([e for b in blocks for p in b['prs'] for e in p['events']], pr['events'])

    def test_overlap_metadata_reaches_ai_and_final_entry(self):
        blocks = build_time_blocks(model(meetings(), [commit('09:45')]))
        payload = prepare_all_blocks(blocks)
        self.assertEqual(payload[0]['calendar_overlap'], True)
        self.assertEqual(payload[0]['attendance'], 'unconfirmed')
        self.assertNotIn('calendar_events', payload[0])
        self.assertNotIn('review', payload[0])
        row = build_entries(blocks)[1]
        self.assertEqual(row['review'], {'status': 'required', 'reasons': ['calendar_overlap'], 'attendance': 'unconfirmed'})
        self.assertIn('attendance confirmation required', row['entry']['description'])

    def test_ai_summary_cannot_remove_overlap_notice_or_review_metadata(self):
        blocks = build_time_blocks(model(meetings(), [commit('09:45')]))
        key = prepare_all_blocks(blocks)[0]['block_id']
        row = build_entries(blocks, [{'block_id': key, 'description': 'Discuss payment validation'}])[1]
        self.assertEqual(row['summary_source'], 'ai')
        self.assertTrue(row['calendar_overlap'])
        self.assertEqual(row['review']['attendance'], 'unconfirmed')
        self.assertIn('attendance confirmation required', row['entry']['description'])
        self.assertEqual(row['entry']['description'].count('PRs:'), 1)

    def test_markdown_calls_union_proposed_and_marks_overlap_row(self):
        text = render_markdown(DATE, build_entries(build_time_blocks(model(meetings()))))
        self.assertIn('REVIEW REQUIRED', text)
        self.assertIn('Scheduled coverage is not confirmed meeting time', text)
        self.assertIn('**Total Proposed Time:** 90 mins', text)
        self.assertIn('30m (scheduled) — attendance review required', text)
        self.assertIn('Calendar overlap awaiting attendance confirmation: 30 mins', text)
        self.assertNotIn('Total Tracked Time', text)

    def test_lunch_overlap_retained_whole_without_development_in_lunch(self):
        events = [event('11:30', '13:00', 'A'), event('12:30', '14:00', 'B')]
        blocks = build_time_blocks(model(events, [commit('10:00'), commit('15:00', 'afternoon')]))
        scheduled = [b for b in blocks if b['time_basis'] == 'scheduled']
        self.assertEqual(sum(b['duration_minutes'] for b in scheduled), 150)
        self.assertEqual(next(b for b in scheduled if b.get('calendar_overlap'))['duration_minutes'], 30)
        for b in blocks:
            if b['time_basis'] == 'estimated':
                self.assertTrue(b['end_time'] <= '12:00' or b['start_time'] >= '13:30')

    def test_short_overlap_is_not_filtered_by_development_minimum(self):
        blocks = build_time_blocks(model([event('09:00', '10:00', 'A'), event('09:55', '10:30', 'B')]))
        self.assertEqual(next(b for b in blocks if b.get('calendar_overlap'))['duration_minutes'], 5)
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 90)

    def test_invalid_partition_bounds_fail_instead_of_losing_calendar_evidence(self):
        for start, end in [('09:00', '09:00'), ('10:00', '09:00')]:
            with self.subTest(start=start, end=end), self.assertRaises(BlockIdentityError):
                build_time_blocks(model([event(start, end)]))
        invalid = {**event(), 'start': DATE + 'T09:00:00'}
        with self.assertRaises(BlockIdentityError):
            build_time_blocks(model([invalid]))
        with self.assertRaises(BlockIdentityError):
            build_time_blocks(model([event(), invalid]))

    def test_pair_interval_grid_counts_union_and_has_no_overlapping_blocks(self):
        for a_start, a_end in itertools.combinations(range(5), 2):
            for b_start, b_end in itertools.combinations(range(5), 2):
                def clock(n): return f'{9+n//2:02d}:{(n%2)*30:02d}'
                calendars = [event(clock(a_start), clock(a_end), 'A'), event(clock(b_start), clock(b_end), 'B')]
                blocks = build_time_blocks(model(calendars))
                covered = set(range(a_start, a_end)) | set(range(b_start, b_end))
                self.assertEqual(sum(b['duration_minutes'] for b in blocks), len(covered)*30)
                for previous, following in zip(blocks, blocks[1:]):
                    self.assertLessEqual(previous['end_time'], following['start_time'])
                for slot in covered:
                    matching = [b for b in blocks if b['start_time'] <= clock(slot) < b['end_time']]
                    self.assertEqual(len(matching), 1)
                    expected = (['A'] if a_start <= slot < a_end else []) + (['B'] if b_start <= slot < b_end else [])
                    self.assertCountEqual(matching[0]['calendar_titles'], expected)


if __name__ == '__main__':
    unittest.main()
