"""F09 orchestration: authoritative profile/override through final daily output."""
import contextlib
import datetime
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from run_pipeline import run

class TestPipelineTimezone(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        token = self.directory / "data/token-usage.csv"
        token.parent.mkdir(); token.write_text("PROTECTED TOKEN RECORDS");self.output=self.directory/'timesheets';self.ai=self.directory/'ai.json'
        self.config=self.directory/'profile.json';self.config.write_text(json.dumps({'timezone':'America/New_York',
            'repositories':['test/project'],'author':{'names':['Me']},'github':{'users':['me']}}))
        self.calls=[]

    def pipeline(self,day='2026-01-01',override=None,calendar=None,default_date=False):
        def collector(command,source,mode):
            self.calls.append((source,command))
            if source=='google_calendar':
                items=calendar if calendar is not None else [{'title':'Call','start':'2026-01-01T15:00:00Z','end':'2026-01-01T16:00:00Z'}]
            elif source=='git':
                items=[] if calendar is not None else [{'hash':'real-shaped-synthetic','timestamp':'2026-01-01T15:15:00Z','message':'Fix','author':'Me'}]
            else:items=[]
            return {'source':source,'mode':mode,'status':'success','items':items}
        args=['run_pipeline.py','--config',str(self.config),'--output-dir',str(self.output),'--export-ai-input',str(self.ai)]
        if not default_date:args+=['--date',day]
        if override is not None:args+=['--timezone',override]
        previous=Path.cwd();self.stdout,self.stderr=io.StringIO(),io.StringIO()
        try:
            os.chdir(self.directory)
            with patch.object(sys,'argv',args),patch('run_pipeline.run_source_collector',side_effect=collector),contextlib.redirect_stdout(self.stdout),contextlib.redirect_stderr(self.stderr):
                return run()
        finally:os.chdir(previous)

    def test_profile_timezone_reaches_all_collectors_normalizer_blocks_and_manifest(self):
        self.assertEqual(self.pipeline(),0,self.stderr.getvalue())
        rows=json.loads((self.output/'2026-01-01.json').read_text())
        self.assertEqual((rows[0]['entry']['start'],rows[0]['entry']['end']),('10:00','11:00'))
        self.assertEqual(len(rows[0]['sources']['commits']),1)
        self.assertEqual(rows[0]['collection']['timezone'],'America/New_York')
        manifest=json.loads((self.output/'2026-01-01.collection.json').read_text())
        self.assertEqual(manifest['timezone'],'America/New_York')
        self.assertEqual(manifest['review']['status'],'required')
        self.assertEqual(json.loads(self.ai.read_text())['blocks'][0]['block']['start'],'10:00')
        for source,command in self.calls:
            self.assertEqual(command[command.index('--timezone')+1],'America/New_York')
            self.assertEqual(command[command.index('--config')+1],str(self.config))

    def test_cli_override_changes_all_outputs_and_collectors_consistently(self):
        self.assertEqual(self.pipeline(override='Asia/Ho_Chi_Minh'),0)
        rows=json.loads((self.output/'2026-01-01.json').read_text())
        self.assertEqual((rows[0]['entry']['start'],rows[0]['entry']['end']),('22:00','23:00'))
        self.assertEqual(rows[0]['collection']['timezone'],'Asia/Ho_Chi_Minh')
        self.assertEqual(len(rows[0]['sources']['commits']),1)
        for source,command in self.calls:self.assertEqual(command[command.index('--timezone')+1],'Asia/Ho_Chi_Minh')

    def test_historical_dst_days_propagate_elapsed_duration_to_storage(self):
        for day,next_day,minutes in [('2026-03-08','2026-03-09',1380),('2026-11-01','2026-11-02',1500)]:
            zone=ZoneInfo('America/New_York')
            start=datetime.datetime.combine(datetime.date.fromisoformat(day),datetime.time.min,tzinfo=zone)
            end=datetime.datetime.combine(datetime.date.fromisoformat(next_day),datetime.time.min,tzinfo=zone)
            self.assertEqual(self.pipeline(day,calendar=[{'title':'Synthetic coverage','start':start.isoformat(),'end':end.isoformat()}]),0)
            row=json.loads((self.output/f'{day}.json').read_text())[0]
            self.assertEqual(row['entry']['duration_minutes'],minutes)
            self.assertEqual(row['entry']['end'],'24:00')
            self.assertEqual(row['collection']['timezone'],'America/New_York')

    def test_today_in_profile_zone_differs_from_utc_date_and_is_used_everywhere(self):
        original=datetime.datetime
        class Clock(original):
            @classmethod
            def now(cls,tz=None):
                instant=original(2026,1,2,0,30,tzinfo=datetime.timezone.utc)
                return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)
        with patch('run_pipeline.datetime.datetime',Clock):
            self.assertEqual(self.pipeline(default_date=True),0)
        self.assertTrue((self.output/'2026-01-01.json').exists())
        self.assertFalse((self.output/'2026-01-02.json').exists())
        for source,command in self.calls:self.assertEqual(command[command.index('--date')+1],'2026-01-01')

    def test_invalid_zone_aborts_before_collection_or_old_output_writes(self):
        self.assertEqual(self.pipeline(),0)
        before={p:p.read_bytes() for p in [*self.output.iterdir(),self.ai,self.directory/'data/token-usage.csv']}
        self.calls=[]
        with self.assertRaises(SystemExit) as result:self.pipeline(override='bad/zone')
        self.assertEqual(result.exception.code,2)
        self.assertEqual(self.calls,[])
        for path,content in before.items():self.assertEqual(path.read_bytes(),content)

if __name__=='__main__':unittest.main()
