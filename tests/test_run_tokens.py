"""Explicit marked-run usage; transcript fixtures here are synthetic, never live proof."""
import copy
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
from collect_token_usage import collect_run, parse_session_file, parse_transcript_line_usage, update_csv, main, daily_totals
from token_settings import token_settings
import test_remaining_storage as storage_fixture
from save_timesheet import TimesheetReconciliationError, save_timesheet
from build_timesheet import build_entries
DATE = storage_fixture.DATE
from atomic_storage import atomic_write

class TestRunTokens(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name); self.transcript=self.directory/'session.jsonl'
        self.manifest=self.directory/'run.json'; self.csv=self.directory/'tokens.csv'
        self.zone=ZoneInfo('Asia/Ho_Chi_Minh')
        self.config={'run_id':'run-a','target_date':'2026-10-06','session_file':self.transcript.name,
                     'started_at':'2026-10-07T09:00:00+07:00','ended_at':'2026-10-07T10:00:00+07:00'}
        self.manifest.write_text(json.dumps(self.config))

    def line(self, id='msg-a', time='09:15', input=100, output=20, cache=5):
        return {'timestamp':f'2026-10-07T{time}:00+07:00', 'message':{'id':id, 'usage':{'input_tokens':input,'output_tokens':output,'cache_read_input_tokens':cache,'cache_creation_input_tokens':0}}}

    def write(self, lines):
        self.transcript.write_text('\n'.join(json.dumps(v) for v in lines)+'\n')

    def collect(self): return collect_run(self.manifest,self.zone,expected_target='2026-10-06',expected_run='run-a')

    def test_repeated_message_latest_snapshot_not_sum(self):
        self.write([self.line(),self.line(),self.line(time='09:16',output=30)])
        r=self.collect(); self.assertEqual((r['input_tokens'],r['output_tokens'],r['cache_tokens'],r['total_tokens']),(100,30,5,135))

    def test_unrelated_usage_outside_run_not_counted(self):
        self.write([self.line(id='before',time='08:59',input=900),self.line(),self.line(id='after',time='10:00',input=900)])
        self.assertEqual(self.collect()['total_tokens'],125)

    def test_message_selection_excludes_unrelated_inside_window(self):
        self.config['message_ids']=['msg-a']; self.manifest.write_text(json.dumps(self.config))
        self.write([self.line(),self.line(id='unrelated',input=999)])
        r=self.collect(); self.assertEqual(r['total_tokens'],125)
        self.assertEqual(json.loads(r['notes'])['scope'],'selected_messages')

    def test_missing_selected_message_not_established_total(self):
        self.config['message_ids']=['msg-a','absent']; self.manifest.write_text(json.dumps(self.config)); self.write([self.line()])
        with self.assertRaises(ValueError): self.collect()

    def test_execution_date_distinct_from_timesheet_target(self):
        self.write([self.line()]); r=self.collect()
        self.assertEqual(r['date'],'2026-10-07'); self.assertEqual(json.loads(r['notes'])['target_date'],'2026-10-06')

    def test_marked_run_across_midnight_counts_once_on_execution_start_day(self):
        self.config.update(started_at='2026-10-06T23:55:00+07:00',ended_at='2026-10-07T00:10:00+07:00')
        self.manifest.write_text(json.dumps(self.config))
        a=self.line(); a['timestamp']='2026-10-06T23:59:00+07:00'
        b=self.line(id='b'); b['timestamp']='2026-10-07T00:01:00+07:00'
        self.write([a,b]); self.assertEqual(self.collect()['date'],'2026-10-06'); self.assertEqual(self.collect()['total_tokens'],250)
        self.assertEqual(parse_session_file(self.transcript,'2026-10-07',self.zone)['total_tokens'],125)

    def test_non_usage_lines_do_not_discard_valid_records(self):
        self.write([self.line(), {'message':'text'}, {'response':[]}, [],self.line(id='strings',input='10',output='2',cache='3')])
        self.assertEqual(self.collect()['total_tokens'],140)

    def test_invalid_in_scope_usage_blocks_total_instead_of_skipping(self):
        self.write([self.line(),self.line(id='bad',input=None)])
        with self.assertRaisesRegex(ValueError,'nonnegative'): self.collect()

    def test_invalid_counts_reject_null_bool_negative_and_float(self):
        for value in (None,True,-1,1.5,'-1','1.5'):
            with self.subTest(value=value),self.assertRaises(ValueError): parse_transcript_line_usage({'usage':{'input_tokens':value}})

    def test_explicit_valid_zero_is_not_missing_usage(self):
        self.write([self.line(input=0,output=0,cache=0)]); self.assertEqual(self.collect()['total_tokens'],0)
        self.write([{'timestamp':'2026-10-07T09:15:00+07:00','usage':{}}])
        with self.assertRaises(ValueError): self.collect()

    def test_idempotent_cumulative_run_totals_and_distinct_runs(self):
        self.write([self.line()]); r=self.collect(); update_csv(self.csv,[r]); before=self.csv.read_bytes()
        update_csv(self.csv,[r]); self.assertEqual(self.csv.read_bytes(),before)
        self.write([self.line(output=30)]); update_csv(self.csv,[self.collect()])
        second=copy.deepcopy(r); second['session_id']='session/run-b'; update_csv(self.csv,[second])
        with self.csv.open() as stream: rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),2)
        self.assertEqual(sum(int(v['total_tokens']) for v in rows),260)
        self.assertEqual(daily_totals(self.csv,'2026-10-07')['by_provenance']['transcript']['total_tokens'],260)

    def test_bad_csv_header_duplicate_invalid_total_preserved(self):
        self.write([self.line()]); r=self.collect()
        for content in ('garbage', ','.join(r)+'\n2026-10-07,bad,-1,2,3,4,bad\n', None):
            if content is None:
                self.csv.unlink(); update_csv(self.csv,[r]); content=self.csv.read_text()+self.csv.read_text().splitlines()[1]+'\n'
            self.csv.write_text(content); before=self.csv.read_bytes()
            with self.assertRaises(ValueError): update_csv(self.csv,[r])
            self.assertEqual(before,self.csv.read_bytes())
        self.csv.unlink(); bad={**r,'total_tokens':999}
        with self.assertRaises(ValueError): update_csv(self.csv,[bad])
        self.assertFalse(self.csv.exists())

    def test_empty_update_does_not_create_or_rewrite(self):
        update_csv(self.csv,[]); self.assertFalse(self.csv.exists())
        self.csv.write_text('corrupt but protected'); update_csv(self.csv,[]); self.assertEqual(self.csv.read_text(),'corrupt but protected')

    def test_csv_replace_failure_preserves_prior_bytes(self):
        self.write([self.line()]); r=self.collect(); update_csv(self.csv,[r]); before=self.csv.read_bytes()
        self.write([self.line(output=30)])
        with patch('atomic_storage.os.replace',side_effect=OSError('synthetic error')):
            with self.assertRaises(OSError): update_csv(self.csv,[self.collect()])
        self.assertEqual(before,self.csv.read_bytes())

    def test_no_implicit_directory_scan(self):
        with patch.object(sys,'argv',['collect_token_usage.py','--claude-dir',str(self.directory),'--csv-path',str(self.csv)]):
            self.assertEqual(main(),2)
        self.assertFalse(self.csv.exists())

    def test_wrong_target_and_run_rejected(self):
        self.write([self.line()])
        for arguments in ({'expected_target':'2026-10-07'},{'expected_run':'wrong'}):
            with self.assertRaises(ValueError): collect_run(self.manifest,self.zone,**arguments)

    def test_path_precedence_cli_environment_profile(self):
        profile=self.directory/'profile.json'; profile.write_text(json.dumps({'token_tracking':{'claude_dir':'profile','csv_path':'profile.csv'}}))
        with patch.dict('os.environ',{'CLAUDE_DIR':str(self.directory/'environment')},clear=True):
            paths=token_settings(profile); self.assertEqual(paths['claude_dir'],self.directory/'environment'); self.assertEqual(paths['csv_path'],self.directory.resolve()/'profile.csv')
            self.assertEqual(token_settings(profile,str(self.directory/'cli'))['claude_dir'],self.directory/'cli')


class TestPipelineRunTokens(unittest.TestCase):
    setUp = storage_fixture.TestRemainingStorage.setUp
    freeze = storage_fixture.TestRemainingStorage.freeze
    invoke = storage_fixture.TestRemainingStorage.invoke
    def test_assemble_collects_marked_usage_with_snapshot_run_id(self):
        snapshot=self.freeze(); transcript=self.directory/'session.jsonl'
        transcript.write_text(json.dumps({'timestamp':'2026-10-07T09:05:00+07:00','message':{'id':'m','usage':{'input_tokens':100,'output_tokens':20,'cache_read_input_tokens':5,'cache_creation_input_tokens':0}}}))
        manifest=self.directory/'usage.json'; manifest.write_text(json.dumps({'run_id':snapshot['run_id'],'target_date':'2026-10-06','session_file':str(transcript),'started_at':'2026-10-07T09:00:00+07:00','ended_at':'2026-10-07T09:10:00+07:00'}))
        token=self.directory/'token-output/tokens.csv'
        arguments=['--phase','assemble','--snapshot',str(self.snapshot),'--output-dir',str(self.output),'--usage-run-manifest',str(manifest),'--token-csv-path',str(token)]
        self.assertEqual(self.invoke(arguments),0,self.stderr.getvalue())
        with token.open() as stream: rows=list(csv.DictReader(stream))
        self.assertEqual(rows[0]['total_tokens'],'125')
        self.assertEqual(rows[0]['date'],'2026-10-07')
        collection=json.loads((self.output/f'{DATE}.collection.json').read_text()); self.assertEqual(collection['token_usage']['status'],'attributed')
        before={p:p.read_bytes() for p in [*self.output.glob(f'{DATE}.*'),token]}
        self.assertEqual(self.invoke(arguments),0,self.stderr.getvalue())
        self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_corrupt_token_csv_blocks_all_final_writes(self):
        token=self.directory/'tokens.csv'; token.write_text('CORRUPT')
        record={'date':'2026-10-07','session_id':'session/run','input_tokens':1,'output_tokens':2,'cache_tokens':3,'total_tokens':6,'notes':'synthetic'}
        with self.assertRaises(TimesheetReconciliationError):
            save_timesheet(build_entries(self.blocks),self.output,target_date=DATE,collection_status='complete',token_records=[record],token_csv=token)
        self.assertFalse((self.output/f'{DATE}.json').exists()); self.assertEqual(token.read_text(),'CORRUPT')

    def test_token_csv_and_timesheet_bundle_roll_back_together(self):
        token=self.directory/'tokens.csv'
        record={'date':'2026-10-07','session_id':'session/run','input_tokens':1,'output_tokens':2,'cache_tokens':3,'total_tokens':6,'notes':'synthetic'}
        failed=False
        def fault(path,content):
            nonlocal failed
            if Path(path)==token and not failed: failed=True; raise OSError('synthetic CSV error')
            return atomic_write(path,content)
        with patch('atomic_storage.atomic_write',side_effect=fault):
            with self.assertRaises(TimesheetReconciliationError):
                save_timesheet(build_entries(self.blocks),self.output,target_date=DATE,collection_status='complete',token_records=[record],token_csv=token)
        self.assertFalse((self.output/f'{DATE}.json').exists()); self.assertFalse(token.exists())

if __name__=='__main__': unittest.main()
