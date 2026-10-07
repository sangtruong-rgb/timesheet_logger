"""F09: named timezone precedence, standalone CLIs and historical DST boundaries."""
import contextlib
import csv
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from activity_settings import day_bounds, resolve_timezone, settings, timezone_settings
from normalize_activity import normalize_all
from build_time_blocks import build_time_blocks
from block_identity import BlockIdentityError
from collect_token_usage import parse_session_file
from get_calendar_activity import normalize_calendar_event, fetch_google_calendar_events, collect_calendar_activity
from get_git_activity import filter_commits, normalize_api_commits
from get_pr_activity import query_gh_prs
from test_github_personal_activity import API, pull

NY=ZoneInfo('America/New_York');UTC=datetime.timezone.utc

class TestTimezonePolicy(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name);self.config=self.directory/'profile.json'
        self.config.write_text(json.dumps({'timezone':'America/New_York'}))

    def test_cli_profile_default_precedence(self):
        self.assertEqual(timezone_settings(self.config)[0],'America/New_York')
        self.assertEqual(timezone_settings(self.config,'Asia/Ho_Chi_Minh')[0],'Asia/Ho_Chi_Minh')
        with patch('activity_settings.DEFAULT_CONFIG',self.directory/'missing.json'):
            self.assertEqual(timezone_settings()[0],'Asia/Ho_Chi_Minh')

    def test_invalid_explicit_timezone_does_not_fall_back(self):
        for value in ('',None,7,'wrong/zone','+07:00'):
            config={'timezone':value}
            with self.subTest(value=value),self.assertRaises(ValueError):settings(config)
        with self.assertRaises(ValueError):timezone_settings(self.config,'')

    def test_named_zones_change_offset_for_historical_date(self):
        zone=resolve_timezone('America/New_York')
        self.assertEqual(datetime.datetime(2026,1,1,tzinfo=zone).utcoffset(),datetime.timedelta(hours=-5))
        self.assertEqual(datetime.datetime(2026,7,1,tzinfo=zone).utcoffset(),datetime.timedelta(hours=-4))

    def test_legacy_model_offsets_are_explicitly_supported_without_host_inference(self):
        data=normalize_all('2026-10-07',[],[],[],timezone_str='+07:00')
        self.assertEqual(data['timezone'],'+07:00');self.assertEqual(build_time_blocks(data),[])
        for value in ('+24:00','+07:99',''):
            with self.subTest(value=value),self.assertRaises(ValueError):
                resolve_timezone(value,allow_legacy_offset=True)

    def test_all_compatibility_helpers_use_same_profile_named_zone(self):
        from get_git_activity import get_local_timezone as git_zone
        from get_pr_activity import get_local_timezone as pr_zone
        from get_calendar_activity import get_local_timezone as calendar_zone
        from normalize_activity import get_local_timezone_str
        with patch('activity_settings.DEFAULT_CONFIG',self.config):
            self.assertEqual({fn().key for fn in (git_zone,pr_zone,calendar_zone)},{'America/New_York'})
            self.assertEqual(get_local_timezone_str(),'America/New_York')
            self.assertEqual(normalize_all('2026-01-01',[],[],[])['timezone'],'America/New_York')

    def test_missing_model_zone_uses_profile_not_first_source_offset(self):
        activity={'hash':'c','message':'Fix','timestamp':'2026-01-01T15:00:00Z'}
        data={'date':'2026-01-01','calendar':[],'commits':[activity],'pull_requests':[]}
        with patch('activity_settings.DEFAULT_CONFIG',self.config):blocks=build_time_blocks(data)
        self.assertEqual((blocks[0]['start_time'],blocks[0]['end_time']),('09:00','12:30'))
        self.assertEqual(blocks[0]['commits'],[activity])

    def test_explicit_model_zone_overrides_profile_and_invalid_zone_blocks(self):
        data={'date':'2026-01-01','timezone':'Asia/Ho_Chi_Minh','calendar':[],
              'commits':[{'hash':'c','timestamp':'2026-01-01T08:00:00Z'}],'pull_requests':[]}
        with patch('activity_settings.DEFAULT_CONFIG',self.config):blocks=build_time_blocks(data)
        self.assertEqual(blocks[0]['start_time'],'13:30')
        with self.assertRaises(BlockIdentityError):build_time_blocks({**data,'timezone':''})

    def test_default_dates_are_resolved_in_selected_zone(self):
        from collect_token_usage import get_local_date_str
        real_datetime=datetime.datetime
        class Clock(real_datetime):
            @classmethod
            def now(cls,tz=None):
                instant=real_datetime(2026,10,7,1,0,tzinfo=UTC)
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
        with patch('collect_token_usage.datetime.datetime',Clock):
            self.assertEqual(get_local_date_str(NY),'2026-10-06')
            self.assertEqual(get_local_date_str(ZoneInfo('Asia/Ho_Chi_Minh')),'2026-10-07')

class TestHistoricalDayBoundaries(unittest.TestCase):
    def test_local_day_has_23_or_25_elapsed_hours_across_dst(self):
        for date,hours in [('2026-03-08',23),('2026-11-01',25)]:
            start,end=day_bounds(datetime.date.fromisoformat(date),NY)
            self.assertEqual((end-start).total_seconds()/3600,hours)

    def test_git_and_pr_share_half_open_dst_day_boundaries(self):
        for date in (datetime.date(2026,3,8),datetime.date(2026,11,1)):
            start,end=day_bounds(date,NY)
            times=[start-datetime.timedelta(seconds=1),start,end-datetime.timedelta(seconds=1),end]
            commits=[{'hash':str(i),'author':'Me','timestamp':t.isoformat()} for i,t in enumerate(times)]
            self.assertEqual([c['hash'] for c in filter_commits(commits,date,'Me',NY)],['1','2'])
            pulls=[pull(i+1,author='me',created=t.isoformat(),updated=(end+datetime.timedelta(days=1)).isoformat()) for i,t in enumerate(times)]
            prs=query_gh_prs(date,['test/project'],['me'],NY,API(pulls))
            self.assertEqual([p['id'] for p in prs],[2,3])

    def test_github_aware_timestamps_are_rendered_with_historical_local_offset(self):
        for date,instant,offset in [(datetime.date(2026,1,1),'2026-01-01T15:00:00Z','-05:00'),
                                    (datetime.date(2026,7,1),'2026-07-01T14:00:00Z','-04:00')]:
            raw=[{'sha':'a'*40,'commit':{'author':{'name':'Me','email':'me@test','date':instant},'message':'Fix'}}]
            results=normalize_api_commits(raw,'test/project',date,'Me',NY)
            self.assertTrue(results[0]['timestamp'].endswith(offset))
            self.assertIn('T10:00:00',results[0]['timestamp'])

    def test_github_naive_author_timestamp_is_not_interpreted_in_host_timezone(self):
        raw=[{'sha':'a'*40,'commit':{'author':{'name':'Me','date':'2026-01-01T10:00:00'},'message':'Fix'}}]
        with self.assertRaises(ValueError):
            normalize_api_commits(raw,'test/project',datetime.date(2026,1,1),'Me',NY)

    def test_calendar_query_uses_named_zone_and_historical_midnight_offsets(self):
        modules={name:types.ModuleType(name) for name in ('google','google.oauth2','google.oauth2.credentials','googleapiclient','googleapiclient.discovery')}
        modules['google.oauth2.credentials'].Credentials=Mock()
        for date,start_offset,end_offset in [('2026-03-08','-05:00','-04:00'),('2026-11-01','-04:00','-05:00')]:
            service=Mock();service.events.return_value.list.return_value.execute.return_value={'items':[]}
            modules['googleapiclient.discovery'].build=Mock(return_value=service)
            with patch.dict(sys.modules,modules),patch('get_calendar_activity.os.path.exists',return_value=True):
                self.assertEqual(fetch_google_calendar_events(datetime.date.fromisoformat(date),tz=NY),[])
            kwargs=service.events.return_value.list.call_args.kwargs
            self.assertTrue(kwargs['timeMin'].endswith(start_offset))
            self.assertTrue(kwargs['timeMax'].endswith(end_offset))
            self.assertEqual(kwargs['timeZone'],'America/New_York')

    def test_naive_calendar_uses_event_named_zone_or_selected_zone_not_host(self):
        day=datetime.date(2026,1,1)
        event={'title':'Planning','start':'2026-01-01T09:00:00','end':'2026-01-01T10:00:00'}
        result=normalize_calendar_event(event,day,NY)
        self.assertEqual(result['start'],'2026-01-01T09:00:00-05:00')
        event['start']={'dateTime':'2026-01-01T09:00:00','timeZone':'Asia/Ho_Chi_Minh'}
        event['end']={'dateTime':'2026-01-01T10:00:00','timeZone':'Asia/Ho_Chi_Minh'}
        result=normalize_calendar_event(event,day,ZoneInfo('Europe/London'))
        self.assertEqual(result['start'],'2026-01-01T02:00:00+00:00')

    def test_naive_dst_gap_and_fold_are_errors_not_guessed_instants(self):
        for date,time in [('2026-03-08','02:15'),('2026-11-01','01:15')]:
            event={'title':'Ambiguous','start':date+'T'+time+':00','end':date+'T04:00:00'}
            with self.subTest(date=date),self.assertRaises(ValueError):
                normalize_calendar_event(event,datetime.date.fromisoformat(date),NY)

    def test_explicit_offset_during_repeated_hour_is_preserved(self):
        day=datetime.date(2026,11,1)
        for offset in ('-04:00','-05:00'):
            event={'title':'Call','start':f'2026-11-01T01:15:00{offset}','end':f'2026-11-01T01:45:00{offset}'}
            result=normalize_calendar_event(event,day,NY)
            self.assertTrue(result['start'].endswith(offset))

    def test_daily_calendar_clipping_counts_dst_elapsed_minutes(self):
        for date,next_date,hours in [('2026-03-08','2026-03-09',23),('2026-11-01','2026-11-02',25)]:
            start=datetime.datetime.combine(datetime.date.fromisoformat(date),datetime.time.min,tzinfo=NY)
            end=datetime.datetime.combine(datetime.date.fromisoformat(next_date),datetime.time.min,tzinfo=NY)
            data=normalize_all(date,[],[],[{'title':'Coverage','start':start.isoformat(),'end':end.isoformat()}],'America/New_York')
            blocks=build_time_blocks(data)
            self.assertEqual(blocks[0]['duration_minutes'],hours*60)
            self.assertEqual(blocks[0]['end_time'],'24:00')

class TestTokenLocalDay(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'session.jsonl'

    def write(self,items):self.path.write_text('\n'.join(json.dumps(item) for item in items))

    def test_same_transcript_is_split_by_actual_local_day_not_relabelled(self):
        self.write([{'timestamp':'2026-10-07T03:59:59Z','usage':{'input_tokens':10}},
                    {'timestamp':'2026-10-07T04:00:00Z','usage':{'input_tokens':20}},
                    {'timestamp':'2026-10-08T04:00:00Z','usage':{'input_tokens':30}}])
        self.assertEqual(parse_session_file(self.path,'2026-10-06',NY)['input_tokens'],10)
        self.assertEqual(parse_session_file(self.path,'2026-10-07',NY)['input_tokens'],20)
        self.assertIn('America/New_York',parse_session_file(self.path,'2026-10-07',NY)['notes'])

    def test_f23_original_cross_day_reproduction_is_22_not_132_tokens(self):
        self.write([{'timestamp':'2026-10-05T03:00:00Z','usage':{'input_tokens':100,'output_tokens':10}},
                    {'timestamp':'2026-10-06T03:00:00Z','usage':{'input_tokens':20,'output_tokens':2}}])
        result=parse_session_file(self.path,'2026-10-06',ZoneInfo('Asia/Ho_Chi_Minh'))
        self.assertEqual(result['total_tokens'],22)
        self.assertEqual(result['input_tokens'],20)
        self.assertEqual(result['output_tokens'],2)

    def test_dst_fall_day_includes_both_instances_of_repeated_hour(self):
        self.write([{'timestamp':'2026-11-01T01:30:00-04:00','usage':{'input_tokens':10}},
                    {'timestamp':'2026-11-01T01:30:00-05:00','usage':{'input_tokens':20}},
                    {'timestamp':'2026-11-02T00:00:00-05:00','usage':{'input_tokens':30}}])
        self.assertEqual(parse_session_file(self.path,'2026-11-01',NY)['input_tokens'],30)

    def test_missing_invalid_naive_timestamps_are_not_assigned_to_requested_date(self):
        self.write([{'usage':{'input_tokens':10}}, {'timestamp':'bad','usage':{'input_tokens':20}},
                    {'timestamp':'2026-10-07T12:00:00','usage':{'input_tokens':30}}])
        diagnostics=io.StringIO()
        with contextlib.redirect_stderr(diagnostics):self.assertIsNone(parse_session_file(self.path,'2026-10-07',NY))
        self.assertIn('skipped 3',diagnostics.getvalue())

    def test_file_mtime_does_not_determine_usage_date(self):
        self.write([{'timestamp':'2026-01-01T15:00:00Z','usage':{'input_tokens':10}}])
        os.utime(self.path,(0,0))
        self.assertEqual(parse_session_file(self.path,'2026-01-01',NY)['input_tokens'],10)
        self.assertIsNone(parse_session_file(self.path,'2026-01-02',NY))

class TestStandaloneTimezoneCLI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name);self.config=self.directory/'profile.json'
        self.config.write_text(json.dumps({'timezone':'America/New_York'}))
        self.fixture=self.directory/'calendar.json'
        self.fixture.write_text(json.dumps([{'title':'Planning','start':'2026-01-01T09:00:00','end':'2026-01-01T10:00:00'}]))

    def invoke(self,script,*args,host='UTC'):
        return subprocess.run([sys.executable,str(ROOT/'scripts'/script),'--config',str(self.config),'--date','2026-01-01',*args],cwd=self.directory,env={**os.environ,'TZ':host},capture_output=True,text=True,timeout=20)

    def test_calendar_and_normalizer_are_independent_of_host_timezone(self):
        for host in ('UTC','Asia/Ho_Chi_Minh','America/Los_Angeles'):
            response=self.invoke('get_calendar_activity.py','--fixture',str(self.fixture),host=host)
            self.assertEqual(response.returncode,0,response.stderr)
            self.assertEqual(json.loads(response.stdout)['items'][0]['start'],'2026-01-01T09:00:00-05:00')
            response=self.invoke('normalize_activity.py',host=host)
            self.assertEqual(response.returncode,0,response.stderr)
            self.assertEqual(json.loads(response.stdout)['timezone'],'America/New_York')

    def test_cli_timezone_override_is_shared_by_calendar_normalizer_and_tokens(self):
        override=['--timezone','Asia/Ho_Chi_Minh']
        calendar=self.invoke('get_calendar_activity.py','--fixture',str(self.fixture),*override)
        self.assertEqual(json.loads(calendar.stdout)['items'][0]['start'],'2026-01-01T09:00:00+07:00')
        normalized=self.invoke('normalize_activity.py',*override)
        self.assertEqual(json.loads(normalized.stdout)['timezone'],'Asia/Ho_Chi_Minh')
        csv_path=self.directory/'tokens.csv'
        response=self.invoke('collect_token_usage.py','--record-usage','synthetic-run','1','2','3','--csv-path',str(csv_path),*override)
        self.assertEqual(response.returncode,0,response.stderr)
        with csv_path.open() as handle:row=next(csv.DictReader(handle))
        self.assertEqual(row['date'],'2026-01-01');self.assertIn('Asia/Ho_Chi_Minh',row['notes'])

    def test_invalid_timezone_stops_before_output_mutation(self):
        output=self.directory/'protected.json';output.write_text('OLD')
        commands=[('get_calendar_activity.py',['--fixture',str(self.fixture),'--output',str(output)]),
                  ('normalize_activity.py',['--output',str(output)]),
                  ('collect_token_usage.py',['--record-usage','synthetic','1','2','0','--csv-path',str(output)])]
        for script,args in commands:
            response=self.invoke(script,*args,'--timezone','invalid/zone')
            self.assertEqual(response.returncode,2,response.stderr)
            self.assertEqual(output.read_text(),'OLD')

    def test_token_cli_filters_internal_timestamps_using_profile(self):
        transcript=self.directory/'synthetic.jsonl'
        transcript.write_text('\n'.join(json.dumps({'timestamp':timestamp,'usage':{'input_tokens':tokens}}) for timestamp,tokens in [('2026-01-01T04:59:59Z',10),('2026-01-01T05:00:00Z',20),('2026-01-02T05:00:00Z',30)]))
        output=self.directory/'tokens.csv'
        response=self.invoke('collect_token_usage.py','--session-file',str(transcript),'--csv-path',str(output))
        self.assertEqual(response.returncode,0,response.stderr)
        with output.open() as handle:row=next(csv.DictReader(handle))
        self.assertEqual(row['input_tokens'],'20');self.assertIn('America/New_York',row['notes'])

if __name__=='__main__':unittest.main()
