"""R04: synthetic usage evidence; real subprocess/environment preservation checks."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from collect_token_usage import collect_run, parse_transcript_line_usage
from activity_snapshot import save_snapshot
from normalize_activity import normalize_all
from build_time_blocks import build_time_blocks
from prepare_ai_input import prepare_activity_input

COUNTS = dict(input_tokens=100, output_tokens=20,
              cache_read_input_tokens=5, cache_creation_input_tokens=0)


class TestUsageCompleteness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.transcript = self.directory / 'claude/synthetic-session.jsonl'
        self.transcript.parent.mkdir()
        self.manifest = self.directory / 'usage.json'
        self.config = dict(run_id='synthetic-run', target_date='2026-10-07',
                           session_file=str(self.transcript),
                           started_at='2026-10-07T09:00:00+07:00',
                           ended_at='2026-10-07T10:00:00+07:00')
        self.zone = ZoneInfo('Asia/Ho_Chi_Minh')
        self.write([self.line()])

    def line(self, counts=None, minute='15', identity='m'):
        return {'timestamp':f'2026-10-07T09:{minute}:00+07:00',
                'message':{'id':identity, 'usage':dict(COUNTS if counts is None else counts)}}

    def write(self, lines):
        self.transcript.write_text('\n'.join(json.dumps(v) for v in lines)+'\n')
        self.manifest.write_text(json.dumps(self.config))

    def collect(self):
        return collect_run(self.manifest, self.zone)

    def test_each_missing_component_blocks_without_inventing_zero(self):
        for missing in COUNTS:
            with self.subTest(missing=missing):
                sparse = dict(COUNTS); del sparse[missing]
                with self.assertRaisesRegex(ValueError, 'missing '+missing):
                    parse_transcript_line_usage(self.line(sparse))

    def test_reported_full_then_output_only_update_blocks(self):
        self.write([self.line(),self.line({'output_tokens':30},minute='16')])
        with self.assertRaisesRegex(ValueError,'Incomplete usage snapshot'): self.collect()

    def test_sparse_before_complete_also_blocks_unknown_update_semantics(self):
        self.write([self.line({'output_tokens':10}),self.line(minute='16')])
        with self.assertRaisesRegex(ValueError,'Incomplete usage snapshot'): self.collect()

    def test_full_update_keeps_latest_counts_without_summing_snapshots(self):
        self.write([self.line(),self.line({**COUNTS,'output_tokens':30},minute='16')])
        record = self.collect()
        self.assertEqual(record['total_tokens'],135)
        self.assertEqual(json.loads(record['notes'])['usage_schema'],'complete_usage_snapshot_v1')

    def test_out_of_order_complete_snapshots_use_latest_timestamp(self):
        self.write([self.line({**COUNTS,'output_tokens':30},minute='16'),self.line()])
        self.assertEqual(self.collect()['total_tokens'],135)

    def test_all_four_explicit_zeros_are_valid(self):
        self.write([self.line(dict.fromkeys(COUNTS,0))])
        self.assertEqual(self.collect()['total_tokens'],0)

    def test_complete_aliases_and_locations(self):
        aliases=dict(prompt_tokens='100',completion_tokens='20',cache_read='5',cache_creation='0')
        for obj in ({'usage':aliases},{'message':{'usage':aliases}},
                    {'response':{'usage':aliases}},{'model_usage':aliases}):
            with self.subTest(location=list(obj)):
                self.assertEqual(parse_transcript_line_usage(obj),(100,20,5))

    def test_conflicting_alias_or_container_blocks(self):
        for obj in ({'usage':{**COUNTS,'prompt_tokens':999}},
                    {'usage':COUNTS,'message':{'usage':{**COUNTS,'output_tokens':99}}}):
            with self.subTest(obj=obj),self.assertRaisesRegex(ValueError,'Conflicting'):
                parse_transcript_line_usage(obj)

    def test_invalid_component_with_other_valid_messages_blocks_total(self):
        for invalid in (None,True,-1,1.5,'-1','1.5'):
            with self.subTest(invalid=invalid):
                self.write([self.line(),self.line({**COUNTS,'output_tokens':invalid},identity='bad')])
                with self.assertRaises(ValueError): self.collect()

    def test_empty_unknown_null_and_nested_aggregate_usage_blocks(self):
        for usage in ({},{'total_tokens':125},None,[],{'model':COUNTS}):
            obj=self.line(); obj['message']['usage']=usage
            with self.subTest(usage=usage):
                self.write([self.line(),obj])
                with self.assertRaises(ValueError): self.collect()

    def test_scope_filters_before_rejecting_unrelated_sparse_usage(self):
        outside=self.line({'output_tokens':30}); outside['timestamp']='2026-10-07T10:00:00+07:00'
        self.write([self.line(),outside]); self.assertEqual(self.collect()['total_tokens'],125)
        self.config['message_ids']=['m']
        unrelated=self.line({'output_tokens':30},identity='unrelated'); unrelated['timestamp']='bad'
        self.write([self.line(),unrelated]); self.assertEqual(self.collect()['total_tokens'],125)

    def test_missing_or_naive_timestamp_with_usage_blocks(self):
        for timestamp in (None,'bad','2026-10-07T09:15:00'):
            obj=self.line(identity='bad'); obj['timestamp']=timestamp
            with self.subTest(timestamp=timestamp):
                self.write([self.line(),obj])
                with self.assertRaisesRegex(ValueError,'valid timestamp'): self.collect()

    def test_malformed_json_cannot_be_silently_dropped_from_run(self):
        self.transcript.write_text(self.transcript.read_text()+'{broken\n')
        with self.assertRaisesRegex(ValueError,'scope cannot be established'): self.collect()

    def test_equal_timestamp_conflict_blocks_but_exact_duplicates_count_once(self):
        self.write([self.line(),self.line()]); self.assertEqual(self.collect()['total_tokens'],125)
        self.write([self.line(),self.line({**COUNTS,'output_tokens':30})])
        with self.assertRaisesRegex(ValueError,'same timestamp'): self.collect()

    def test_older_timestamp_conflict_is_rejected_in_every_arrival_order(self):
        from itertools import permutations
        lines = [self.line(), self.line({**COUNTS, 'output_tokens': 99}),
                 self.line({**COUNTS, 'output_tokens': 30}, minute='16')]
        for order in permutations(lines):
            with self.subTest(order=[v['timestamp'] for v in order]):
                self.write(order)
                with self.assertRaisesRegex(ValueError, 'same timestamp'):
                    self.collect()

    def test_older_exact_duplicates_do_not_block_latest_complete_snapshot(self):
        from itertools import permutations
        for order in permutations([self.line(), self.line(),
                                   self.line({**COUNTS, 'output_tokens': 30}, minute='16')]):
            self.write(order)
            self.assertEqual(self.collect()['total_tokens'], 135)

    def test_raw_streaming_records_are_not_final_usage_snapshots(self):
        for event_type in ('message_start','message_delta','stream_event'):
            obj=self.line(); obj['type']=event_type
            with self.subTest(event_type=event_type):
                self.write([obj])
                with self.assertRaisesRegex(ValueError,'streaming usage'): self.collect()

    def test_nested_stream_event_is_not_silently_skipped(self):
        obj={'type':'stream_event','timestamp':'2026-10-07T09:16:00+07:00',
             'event':{'type':'message_delta','usage':{'output_tokens':30}}}
        self.write([self.line(),obj])
        with self.assertRaisesRegex(ValueError,'streaming usage'): self.collect()

    def cli(self, script, *args):
        # Actual process environment, no patch.dict/mock. All paths are isolated.
        env={**os.environ,'CLAUDE_DIR':str(self.transcript.parent),
             'TIMESHEET_TOKEN_CSV':str(self.directory/'csv/tokens.csv')}
        return subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],
                              cwd=self.directory,env=env,capture_output=True,text=True,timeout=30)

    def test_cli_real_environment_session_lookup_and_csv_preservation(self):
        del self.config['session_file']; self.config['session_id']=self.transcript.stem
        self.write([self.line()])
        arguments=('--run-manifest',self.manifest,'--timezone','Asia/Ho_Chi_Minh')
        response=self.cli('collect_token_usage.py',*arguments)
        self.assertEqual(response.returncode,0,response.stderr)
        csv_path=self.directory/'csv/tokens.csv'; before=csv_path.read_bytes()
        self.assertEqual(json.loads(response.stdout)['record']['total_tokens'],125)
        self.write([self.line(),self.line({'output_tokens':30},minute='16')])
        response=self.cli('collect_token_usage.py',*arguments)
        self.assertEqual(response.returncode,2,response.stderr)
        self.assertIn('token total is not established',response.stderr)
        self.assertNotIn('Traceback',response.stderr)
        self.assertEqual(csv_path.read_bytes(),before)

    def test_cli_incomplete_usage_never_creates_csv(self):
        self.write([self.line({'output_tokens':30})])
        response=self.cli('collect_token_usage.py','--run-manifest',self.manifest,'--timezone','Asia/Ho_Chi_Minh')
        self.assertEqual(response.returncode,2,response.stderr)
        self.assertFalse((self.directory/'csv/tokens.csv').exists())

    def test_pipeline_requested_sparse_usage_preserves_all_final_files(self):
        normalized=normalize_all('2026-10-07',[],[],[],timezone_str='Asia/Ho_Chi_Minh')
        review=[]; blocks=build_time_blocks(normalized,unassigned_activity=review)
        snapshot_path=self.directory/'snapshot/activity.json'
        snapshot=save_snapshot(snapshot_path,normalized,{'status':'complete','sources':{}},
                               blocks,review,prepare_activity_input(blocks,review))
        # Synthetic frozen sources, never live integration evidence.
        self.config['run_id']=snapshot['run_id']; self.write([self.line()])
        output=self.directory/'timesheets'; export=self.directory/'export/ai.json'
        args=('--phase','assemble','--snapshot',snapshot_path,'--output-dir',output,
              '--export-ai-input',export,'--usage-run-manifest',self.manifest)
        response=self.cli('run_pipeline.py',*args)
        self.assertEqual(response.returncode,0,response.stderr)
        csv_path=self.directory/'csv/tokens.csv'
        files=[snapshot_path,export,csv_path,*output.glob('2026-10-07.*')]
        before={p:p.read_bytes() for p in files}
        self.write([self.line(),self.line({'output_tokens':30},minute='16')])
        response=self.cli('run_pipeline.py',*args)
        self.assertEqual(response.returncode,2,response.stderr)
        self.assertIn('TOKEN ATTRIBUTION BLOCKED',response.stderr)
        self.assertNotIn('Traceback',response.stderr)
        self.assertEqual({p:p.read_bytes() for p in files},before)


if __name__=='__main__': unittest.main()
