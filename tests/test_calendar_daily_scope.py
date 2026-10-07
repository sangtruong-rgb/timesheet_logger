"""F07: all-day context and daily portions of timed Calendar events."""
import copy
import datetime
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from get_calendar_activity import normalize_calendar_event, load_calendar_fixture, fetch_google_calendar_events, collect_calendar_activity
from normalize_activity import normalize_all
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from prepare_ai_input import prepare_all_blocks
from save_timesheet import save_timesheet, TimesheetReconciliationError

DATE = '2026-10-07'
DAY = datetime.date.fromisoformat(DATE)
TZ = ZoneInfo('Asia/Ho_Chi_Minh')


def all_day(start=DATE, end='2026-10-08', title='Project deadline'):
    return {'title': title, 'start': start, 'end': end, 'all_day': True}


def timed(start='2026-10-07T22:00:00+07:00', end='2026-10-08T02:00:00+07:00', title='Late support'):
    return {'title': title, 'start': start, 'end': end}


def daily(events, date=DATE, timezone='Asia/Ho_Chi_Minh', commits=None):
    return normalize_all(date, commits or [], [], events, timezone)


class TestCalendarDailyScope(unittest.TestCase):
    def test_google_date_objects_preserve_all_day_and_exclusive_end(self):
        item = {'summary': 'Deadline', 'start': {'date': DATE}, 'end': {'date': '2026-10-08'}}
        self.assertEqual(normalize_calendar_event(item, DAY, TZ), all_day(title='Deadline'))

    def test_date_string_fixtures_are_inferred_as_all_day(self):
        raw = {'title': 'Deadline', 'start': DATE, 'end': '2026-10-08'}
        self.assertEqual(normalize_calendar_event(raw, DAY, TZ), all_day(title='Deadline'))

    def test_multi_day_all_day_membership_uses_exclusive_end(self):
        item = all_day('2026-10-06', '2026-10-09')
        for date, expected in [('2026-10-05', False), ('2026-10-06', True), ('2026-10-07', True),
                               ('2026-10-08', True), ('2026-10-09', False)]:
            with self.subTest(date=date):
                self.assertEqual(normalize_calendar_event(item, datetime.date.fromisoformat(date), TZ) is not None, expected)

    def test_explicit_midnight_datetime_is_timed_not_inferred_all_day(self):
        item = timed(DATE+'T00:00:00+07:00', '2026-10-08T00:00:00+07:00')
        self.assertNotIn('all_day', normalize_calendar_event(item, DAY, TZ))
        blocks = build_time_blocks(daily([item]))
        self.assertEqual((blocks[0]['start_time'], blocks[0]['end_time'], blocks[0]['duration_minutes']), ('00:00', '24:00', 1440))

    def test_mixed_date_datetime_or_contradictory_flag_is_error(self):
        for item in [timed(DATE, DATE+'T12:00:00+07:00'), {**all_day(), 'all_day': False}, {**timed(), 'all_day': True}]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                normalize_calendar_event(item, DAY, TZ)

    def test_invalid_or_reversed_calendar_dates_do_not_succeed(self):
        for item in [all_day(DATE, DATE), all_day('bad-date', '2026-10-08'), timed('2026-10-07T12:00:00+07:00', DATE+'T11:00:00+07:00')]:
            with self.subTest(item=item), self.assertRaises(ValueError):
                normalize_calendar_event(item, DAY, TZ)

    def test_fixture_includes_previous_night_event_and_keeps_original_extent(self):
        item = timed('2026-10-06T22:00:00+07:00', DATE+'T02:00:00+07:00')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'events.json';path.write_text(json.dumps([item]))
            self.assertEqual(load_calendar_fixture(str(path), DAY, TZ), [item])

    def test_timed_collector_half_open_day_overlap_boundaries(self):
        cases = [(timed('2026-10-06T22:00:00+07:00', DATE+'T00:00:00+07:00'), False),
                 (timed('2026-10-08T00:00:00+07:00', '2026-10-08T01:00:00+07:00'), False),
                 (timed(DATE+'T00:00:00+07:00', DATE+'T00:01:00+07:00'), True),
                 (timed(DATE+'T23:59:00+07:00', '2026-10-08T00:00:00+07:00'), True)]
        for item, expected in cases:
            with self.subTest(item=item):
                self.assertEqual(normalize_calendar_event(item, DAY, TZ) is not None, expected)

    def test_mocked_google_adapter_and_fixture_have_same_scope_and_event_types(self):
        records = [all_day(), timed(), timed('2026-10-06T22:00:00+07:00', DATE+'T02:00:00+07:00')]
        api_items = [{'summary': r['title'], 'start': {'date' if r.get('all_day') else 'dateTime': r['start']},
                      'end': {'date' if r.get('all_day') else 'dateTime': r['end']}} for r in records]
        service = Mock();service.events.return_value.list.return_value.execute.return_value = {'items': api_items}
        credentials = Mock();build = Mock(return_value=service)
        modules = {name: types.ModuleType(name) for name in ['google', 'google.oauth2', 'google.oauth2.credentials', 'googleapiclient', 'googleapiclient.discovery']}
        modules['google.oauth2.credentials'].Credentials = credentials
        modules['googleapiclient.discovery'].build = build
        with patch.dict(sys.modules, modules), patch('get_calendar_activity.os.path.exists', return_value=True):
            live = fetch_google_calendar_events(DAY, tz=TZ)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.json';path.write_text(json.dumps(records));fixture=load_calendar_fixture(str(path),DAY,TZ)
        self.assertCountEqual(live, [{**item, 'calendar_id':'primary', 'source':'google_calendar'} for item in fixture])
        kwargs=service.events.return_value.list.call_args.kwargs
        self.assertEqual(kwargs['timeMin'], DATE+'T00:00:00+07:00')
        self.assertEqual(kwargs['timeMax'], '2026-10-08T00:00:00+07:00')

    def test_invalid_fixture_is_error_envelope_without_sample_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'events.json';path.write_text(json.dumps([all_day(DATE,DATE)]))
            result=collect_calendar_activity(DAY,str(path),TZ)
        self.assertEqual(result['status'],'error');self.assertEqual(result['items'],[])

    def test_normalizer_separates_all_day_context_and_deduplicates(self):
        data=daily([all_day(),all_day(),timed()])
        self.assertEqual(data['calendar_context'],[all_day()])
        self.assertEqual(data['calendar'],[timed()])

    def test_all_day_only_has_no_time_blocks_or_ai_payload(self):
        data=daily([all_day()]);blocks=build_time_blocks(data)
        self.assertEqual(blocks,[]);self.assertEqual(prepare_all_blocks(blocks),[])
        self.assertEqual(data['calendar_context'],[all_day()])

    def test_all_day_does_not_block_git_fallback_or_decide_day_off(self):
        activity={'hash':'test','message':'Fix','timestamp':DATE+'T10:00:00+07:00'}
        blocks=build_time_blocks(daily([all_day(title='Holiday')],commits=[activity]))
        self.assertEqual(len(blocks),1);self.assertEqual(blocks[0]['time_basis'],'estimated')
        self.assertEqual(len(blocks[0]['commits']),1);self.assertEqual(blocks[0]['calendar_titles'],[])

    def test_first_day_of_overnight_event_has_24_hour_end_and_120_minutes(self):
        blocks=build_time_blocks(daily([timed()]))
        self.assertEqual((blocks[0]['start_time'],blocks[0]['end_time'],blocks[0]['duration_minutes']),('22:00','24:00',120))
        self.assertEqual(blocks[0]['calendar_events'],[timed()])
        self.assertEqual(build_entries(blocks)[0]['block_id'],DATE+'_22:00_24:00')

    def test_second_day_of_overnight_event_has_120_minutes(self):
        blocks=build_time_blocks(daily([timed()],date='2026-10-08'))
        self.assertEqual((blocks[0]['start_time'],blocks[0]['end_time'],blocks[0]['duration_minutes']),('00:00','02:00',120))
        self.assertEqual(blocks[0]['calendar_events'],[timed()])

    def test_event_spanning_whole_day_is_clipped_to_daily_bounds(self):
        item=timed('2026-10-06T22:00:00+07:00','2026-10-08T02:00:00+07:00')
        blocks=build_time_blocks(daily([item]))
        self.assertEqual((blocks[0]['start_time'],blocks[0]['end_time'],blocks[0]['duration_minutes']),('00:00','24:00',1440))

    def test_foreign_day_event_is_not_a_target_calendar_block(self):
        item=timed('2026-10-06T09:00:00+07:00','2026-10-06T10:00:00+07:00')
        self.assertEqual(build_time_blocks(daily([item])),[])

    def test_selected_timezone_controls_clipping_not_original_offset(self):
        item=timed('2026-10-07T15:00:00Z','2026-10-07T19:00:00Z')
        blocks=build_time_blocks(daily([item]))
        self.assertEqual((blocks[0]['start_time'],blocks[0]['end_time'],blocks[0]['duration_minutes']),('22:00','24:00',120))
        self.assertEqual(blocks[0]['calendar_events'],[{**item,
            'start':'2026-10-07T22:00:00+07:00', 'end':'2026-10-08T02:00:00+07:00',
            'original_start':item['start'], 'original_end':item['end']}])
        self.assertEqual(build_time_blocks(daily([item],timezone='+07:00')),blocks)

    def test_cross_midnight_overlap_remains_disjoint_and_requires_review(self):
        second=timed(DATE+'T23:00:00+07:00','2026-10-08T01:00:00+07:00','Other')
        blocks=build_time_blocks(daily([timed(),second]))
        self.assertEqual(sum(b['duration_minutes'] for b in blocks),120)
        self.assertEqual(blocks[-1]['end_time'],'24:00');self.assertTrue(blocks[-1]['calendar_overlap'])
        self.assertEqual(len(blocks[-1]['calendar_events']),2)

    def test_late_commit_attaches_to_clipped_calendar_event_once(self):
        activity={'hash':'test','message':'Support','timestamp':DATE+'T23:15:00+07:00'}
        blocks=build_time_blocks(daily([timed()],commits=[activity]))
        self.assertEqual(sum(len(b['commits']) for b in blocks),1)
        self.assertEqual(blocks[-1]['commits'][0]['hash'],'test')
        self.assertEqual(blocks[-1]['end_time'],'24:00')

    def test_no_source_mutation_during_clipping_or_context_projection(self):
        data=daily([all_day(),timed()]);before=copy.deepcopy(data)
        build_entries(build_time_blocks(data));self.assertEqual(data,before)

    def test_dst_overnight_duration_uses_elapsed_minutes(self):
        item=timed('2026-03-07T22:00:00-05:00','2026-03-08T04:00:00-04:00')
        first=build_time_blocks(daily([item],date='2026-03-07',timezone='America/New_York'))
        second=build_time_blocks(daily([item],date='2026-03-08',timezone='America/New_York'))
        self.assertEqual(sum(b['duration_minutes'] for b in first),120)
        self.assertEqual(sum(b['duration_minutes'] for b in second),180)
        self.assertEqual(sum(b['duration_minutes'] for b in first+second),300)

    def test_context_only_storage_is_zero_minutes_with_separate_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            result=save_timesheet([],directory,target_date=DATE,collection_status='complete',calendar_context=[all_day()])
            info=result['dates'][DATE]
            self.assertEqual(json.loads(Path(info['json_path']).read_text()),[])
            self.assertEqual(json.loads(Path(info['calendar_context_path']).read_text())['calendar_context'],[all_day()])
            md=Path(info['md_path']).read_text();self.assertIn('0 mins',md);self.assertIn('not counted as work time',md)
            self.assertIn('Project deadline',md)

    def test_context_change_and_deletion_update_markdown_without_changing_entry_json(self):
        with tempfile.TemporaryDirectory() as directory:
            args={'target_date':DATE,'collection_status':'complete'}
            save_timesheet([],directory,calendar_context=[all_day()],**args)
            json_path=Path(directory)/f'{DATE}.json';original=json_path.read_bytes()
            save_timesheet([],directory,calendar_context=[all_day(title='Changed deadline')],**args)
            self.assertIn('Changed deadline',(Path(directory)/f'{DATE}.md').read_text())
            self.assertEqual(json_path.read_bytes(),original)
            save_timesheet([],directory,calendar_context=[],**args)
            self.assertNotIn('Calendar context',(Path(directory)/f'{DATE}.md').read_text())
            self.assertEqual(json.loads((Path(directory)/f'{DATE}.calendar-context.json').read_text())['calendar_context'],[])

    def test_standalone_omitted_context_preserves_it_and_exact_rerun_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            args={'target_date':DATE,'collection_status':'complete'}
            save_timesheet([],directory,calendar_context=[all_day()],**args)
            before={p:p.read_bytes() for p in Path(directory).iterdir()}
            save_timesheet([],directory,**args)
            for p,contents in before.items():self.assertEqual(p.read_bytes(),contents)

    def test_invalid_new_context_preserves_every_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            args={'target_date':DATE,'collection_status':'complete'}
            save_timesheet([],directory,calendar_context=[all_day()],**args)
            before={p:p.read_bytes() for p in Path(directory).iterdir()}
            with self.assertRaises(TimesheetReconciliationError):
                save_timesheet([],directory,calendar_context=[all_day('2026-10-08','2026-10-09')],**args)
            for p,contents in before.items():self.assertEqual(p.read_bytes(),contents)

    def test_corrupt_existing_context_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            args={'target_date':DATE,'collection_status':'complete'}
            save_timesheet([],directory,calendar_context=[all_day()],**args)
            (Path(directory)/f'{DATE}.calendar-context.json').write_text('{broken')
            before={p:p.read_bytes() for p in Path(directory).iterdir()}
            with self.assertRaises(TimesheetReconciliationError):save_timesheet([],directory,calendar_context=[],**args)
            for p,contents in before.items():self.assertEqual(p.read_bytes(),contents)


if __name__=='__main__':unittest.main()
