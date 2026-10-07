"""Actual temporary Git + explicit fixtures through prepare/AI/assemble/rerun/usage."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from install_skill import install
from build_demo import build_demo
from run_pipeline import run_source_collector


class TestDeliveryFlow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name); self.repo=self.directory/'work repo'; self.repo.mkdir()
        self.git('init','-q')
        self.git('config','user.name','Synthetic Author'); self.git('config','user.email','synthetic@example.invalid')
        (self.repo/'work.txt').write_text('synthetic test work')
        self.git('add','work.txt')
        self.git('commit','-qm','DEMO-1 fix validation',env={**os.environ,'GIT_AUTHOR_DATE':'2026-10-07T10:45:00+07:00','GIT_COMMITTER_DATE':'2026-10-07T10:45:00+07:00'})
        self.calendar=self.directory/'calendar.json'; self.calendar.write_text(json.dumps([{'title':'Synthetic meeting','start':'2026-10-07T09:00:00+07:00','end':'2026-10-07T09:30:00+07:00'}]))
        self.prs=self.directory/'prs.json'; self.prs.write_text(json.dumps([{'id':7,'repository':'demo/work','title':'DEMO-1 validation','events':[{'action':'reviewed','timestamp':'2026-10-07T10:00:00+07:00','actor':'synthetic-user'}]}]))
        self.profile=self.directory/'profile.json'; self.profile.write_text(json.dumps({'author':{'names':['Synthetic Author']},'github':{'users':['synthetic-user']},'repositories':[str(self.repo)],'timezone':'Asia/Ho_Chi_Minh'}))
        self.snapshot=self.directory/'demo/activity.json'; self.ai=self.directory/'demo/ai.json'
        self.output=self.directory/'timesheets'; self.final=self.output/'demo/2026-10-07.json'

    def git(self,*args,env=None):
        return subprocess.run(['git','-C',str(self.repo),*args],env=env,check=True,capture_output=True,text=True)

    def cli(self,script,*args):
        return subprocess.run([sys.executable,str(ROOT/'scripts'/script),*map(str,args)],cwd=self.directory,capture_output=True,text=True,timeout=30)

    def prepare(self):
        return self.cli('run_pipeline.py','--phase','prepare','--date','2026-10-07','--config',self.profile,
            '--calendar-fixture',self.calendar,'--prs-fixture',self.prs,'--snapshot',self.directory/'activity.json',
            '--export-ai-input',self.directory/'ai.json','--output-dir',self.output)

    def test_git_fixture_prepare_keyed_assembly_rerun_and_run_usage(self):
        response=self.prepare(); self.assertEqual(response.returncode,0,response.stderr)
        self.assertFalse(self.final.exists()); frozen=json.loads(self.snapshot.read_text())
        self.assertEqual(frozen['collection']['status'],'demo')
        self.assertEqual(frozen['collection']['sources']['git']['count'],1)
        payload=json.loads(self.ai.read_text()); self.assertEqual(len(payload['blocks']),1)
        judgments=self.directory/'judgments.json'
        judgments.write_text(json.dumps([{'block_id':payload['blocks'][0]['block_id'],'description':'Synthetic validation summary'}]))
        arguments=['--phase','assemble','--snapshot',self.snapshot,'--ai-output',judgments,'--output-dir',self.output]
        response=self.cli('run_pipeline.py',*arguments); self.assertEqual(response.returncode,0,response.stderr)
        rows=json.loads(self.final.read_text()); self.assertEqual([r['summary_source'] for r in rows],['fallback','ai'])
        self.assertEqual(rows[1]['entry']['description'],'Synthetic validation summary. PRs: #7')
        self.assertEqual(sum(len(r['sources']['commits']) for r in rows),1)
        before={p:p.read_bytes() for p in self.final.parent.glob('2026-10-07.*')}
        # Mutate source after prepare: assembly must keep the original frozen meeting.
        self.calendar.write_text('[]')
        response=self.cli('run_pipeline.py',*arguments); self.assertEqual(response.returncode,0,response.stderr)
        self.assertEqual({p:p.read_bytes() for p in before},before)
        transcript=self.directory/'synthetic-session.jsonl'
        usage={'timestamp':'2026-10-07T10:01:00+07:00','message':{'id':'synthetic-msg','usage':{'input_tokens':100,'output_tokens':20,'cache_read_input_tokens':5,'cache_creation_input_tokens':0}}}
        transcript.write_text(json.dumps(usage)+'\n'+json.dumps(usage)+'\n')
        manifest=self.directory/'synthetic-usage.json'; manifest.write_text(json.dumps({'run_id':frozen['run_id'],'target_date':'2026-10-07','session_file':str(transcript),'started_at':'2026-10-07T10:00:00+07:00','ended_at':'2026-10-07T10:02:00+07:00','message_ids':['synthetic-msg']}))
        csv_path=self.directory/'synthetic-tokens.csv'
        for _ in range(2):
            response=self.cli('collect_token_usage.py','--run-manifest',manifest,'--csv-path',csv_path)
            self.assertEqual(response.returncode,0,response.stderr)
        with csv_path.open() as stream: usage_rows=list(csv.DictReader(stream))
        self.assertEqual(len(usage_rows),1); self.assertEqual(usage_rows[0]['total_tokens'],'125')

    def test_install_is_idempotent_and_existing_destination_preserved(self):
        destination=self.directory/'skills/personal-timesheet'; self.assertEqual(install(destination),destination)
        self.assertEqual(install(destination),destination)
        self.assertEqual((destination/'SKILL.md').read_bytes(),(ROOT/'SKILL.md').read_bytes())
        another=self.directory/'existing'; another.mkdir(); (another/'mine').write_text('protected')
        with self.assertRaises(ValueError): install(another)
        self.assertEqual((another/'mine').read_text(),'protected')

    def test_skill_bundle_paths_work_from_other_project(self):
        destination=self.directory/'personal-timesheet'; install(destination)
        response=subprocess.run([sys.executable,str(destination/'scripts/run_pipeline.py'),'--phase','prepare',
            '--date','2026-10-07','--config',str(self.profile),'--snapshot',str(self.directory/'activity.json'),
            '--calendar-fixture',str(self.calendar),'--prs-fixture',str(self.prs),'--output-dir',str(self.output)],
            cwd=self.directory,capture_output=True,text=True,timeout=30)
        self.assertEqual(response.returncode,0,response.stderr); self.assertTrue(self.snapshot.exists())

    def test_demo_regeneration_is_correct_and_explicit_synthetic(self):
        directory=self.directory/'synthetic'; build_demo(directory)
        rows=json.loads((directory/'2026-10-07.json').read_text())
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows),180)
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows if r['time_basis']=='scheduled'),90)
        self.assertTrue(all(r['collection']['status']=='demo' for r in rows))
        self.assertIn('demo-one/work#7, demo-two/work#7',rows[1]['entry']['description'])
        with (directory/'synthetic-token-usage.csv').open() as stream: notes=next(csv.DictReader(stream))['notes']
        self.assertEqual(json.loads(notes)['source'],'synthetic')
        before={p:p.read_bytes() for p in directory.glob('*') if p.is_file()}
        build_demo(directory); self.assertEqual({p:p.read_bytes() for p in before},before)

    def test_bad_export_parent_is_controlled_and_original_preserved(self):
        response=self.prepare(); self.assertEqual(response.returncode,0,response.stderr)
        occupied=self.directory/'occupied'; occupied.write_text('protected')
        blocks=self.directory/'blocks.json'; blocks.write_text(json.dumps(json.loads(self.snapshot.read_text())['blocks']))
        for script in ('prepare_ai_input.py','build_timesheet.py'):
            response=self.cli(script,'--blocks-file',blocks,'--output',occupied/'output.json')
            self.assertEqual(response.returncode,2,response.stderr); self.assertNotIn('Traceback',response.stderr)
            self.assertEqual(occupied.read_text(),'protected')

    def test_collector_timeout_becomes_source_error(self):
        with patch('run_pipeline.subprocess.run',side_effect=subprocess.TimeoutExpired('test',120)):
            result=run_source_collector(['synthetic-command'],'git','live')
        self.assertEqual(result['status'],'error'); self.assertEqual(result['items'],[])

if __name__=='__main__': unittest.main()
