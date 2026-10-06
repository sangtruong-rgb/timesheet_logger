"""F08 end-to-end assembly using synthetic source responses, no external calls."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'scripts'))
from run_pipeline import run
from test_unassigned_activity import DATE, meeting, pr, commit

class TestPipelineActivityReview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name);self.output=self.directory/'timesheets'
        self.ai=self.directory/'ai-input.json';self.config=self.directory/'profile.json'
        self.config.write_text(json.dumps({'repositories':['test/project'],'author':{'names':['Test User']},
            'github':{'users':['test-user']},'timezone':'Asia/Ho_Chi_Minh'}))

    def pipeline(self,calendars=None,commits=None,prs=None,status='success',demo=False,ai_output=None):
        def collector(command,source,mode):
            items={'git':commits or [],'github':prs or [],'google_calendar':calendars or []}[source]
            state=status if source=='google_calendar' else 'success'
            return {'source':source,'mode':mode,'status':state,'items':items if state=='success' else []}
        args=['run_pipeline.py','--date',DATE,'--config',str(self.config),'--output-dir',str(self.output),'--export-ai-input',str(self.ai)]
        if demo: args+=['--calendar-fixture','EXPLICIT SYNTHETIC TEST FIXTURE']
        if ai_output: args+=['--ai-output',str(ai_output)]
        previous=Path.cwd();self.stdout,self.stderr=io.StringIO(),io.StringIO()
        try:
            os.chdir(self.directory)
            with patch.object(sys,'argv',args),patch('run_pipeline.run_source_collector',side_effect=collector), \
                    contextlib.redirect_stdout(self.stdout),contextlib.redirect_stderr(self.stderr):
                return run()
        finally:os.chdir(previous)

    def read(self,suffix):return json.loads((self.output/f'{DATE}{suffix}.json').read_text())
    def snapshot(self):
        paths=[*self.output.glob(f'{DATE}.*'),self.ai,self.directory/'data/token-usage.csv']
        return {p:p.read_bytes() for p in paths if p.is_file()}

    def test_live_complete_with_review_keeps_pr_out_of_meeting_and_ai_block(self):
        self.assertEqual(self.pipeline([meeting()],prs=[pr()]),0,self.stderr.getvalue())
        row=self.read('')[0]
        self.assertEqual(row['entry']['description'],'Kickoff. PRs: None')
        self.assertEqual(row['sources']['pull_requests'],[])
        review=self.read('.activity-review')
        self.assertEqual(review['unassigned_activity'][0]['activity']['id'],55)
        manifest=self.read('.collection')
        self.assertEqual(manifest['status'],'complete')
        self.assertEqual(manifest['review']['status'],'required')
        self.assertEqual(manifest['unassigned_activity_count'],1)
        self.assertEqual(manifest['activity_review_file'],f'{DATE}.activity-review.json')
        payload=json.loads(self.ai.read_text())
        self.assertEqual(payload['blocks'][0]['prs'],[])
        self.assertEqual(payload['unassigned_activity'][0]['id'],55)
        self.assertIn('REVIEW REQUIRED',self.stdout.getvalue())

    def test_no_calendar_only_unmatched_saves_zero_hours_and_full_evidence(self):
        self.assertEqual(self.pipeline(commits=[commit()],prs=[pr()]),0)
        self.assertEqual(self.read(''),[])
        self.assertEqual(len(self.read('.activity-review')['unassigned_activity']),2)
        self.assertEqual(json.loads(self.ai.read_text())['blocks'],[])
        md=(self.output/f'{DATE}.md').read_text()
        self.assertIn('Total Proposed Time:** 0 mins',md)
        self.assertIn('PR #55',md)
        self.assertIn('Commit c1',md)

    def test_mixed_assigned_and_unassigned_pr_actions_are_all_accounted_for(self):
        reference={**pr(),'events':[{'action':'opened','timestamp':f'{DATE}T00:02:00+07:00'},
                                   {'action':'reviewed','timestamp':f'{DATE}T15:30:00+07:00','id':99}]}
        self.assertEqual(self.pipeline([meeting()],prs=[reference]),0)
        self.assertEqual(self.read('')[0]['sources']['pull_requests'][0]['events'],[reference['events'][1]])
        self.assertEqual(self.read('.activity-review')['unassigned_activity'][0]['activity']['events'],[reference['events'][0]])

    def test_review_rerun_is_idempotent(self):
        self.assertEqual(self.pipeline([meeting()],prs=[pr()]),0);before=self.snapshot()
        self.assertEqual(self.pipeline([meeting()],prs=[pr()]),0)
        self.assertEqual(self.snapshot(),before)

    def test_successful_rerun_clears_previous_review_when_timestamp_matches(self):
        self.assertEqual(self.pipeline([meeting()],prs=[pr()]),0)
        self.assertEqual(self.pipeline([meeting()],prs=[pr('15:30')]),0)
        self.assertEqual(self.read('.activity-review')['unassigned_activity'],[])
        self.assertEqual(self.read('.collection')['review']['status'],'none')
        self.assertNotIn('Unassigned activity',(self.output/f'{DATE}.md').read_text())
        self.assertEqual(self.read('')[0]['sources']['pull_requests'][0]['id'],55)

    def test_calendar_failure_preserves_review_and_puts_github_in_incomplete_draft(self):
        self.assertEqual(self.pipeline([meeting()],prs=[pr()]),0);before=self.snapshot()
        self.assertEqual(self.pipeline(prs=[pr()],status='error'),2)
        self.assertEqual(self.snapshot(),before)
        draft=json.loads((self.output/'drafts'/f'{DATE}.json').read_text())
        self.assertEqual(draft['collection']['status'],'incomplete')
        self.assertEqual(draft['activity']['pull_requests'][0]['id'],55)

    def test_invalid_review_store_blocks_final_manifest_ai_and_token_writes(self):
        self.assertEqual(self.pipeline([meeting()],prs=[pr()]),0)
        (self.output/f'{DATE}.activity-review.json').write_text('corrupt')
        before=self.snapshot()
        self.assertEqual(self.pipeline([meeting()],prs=[pr('15:30')]),2)
        self.assertEqual(self.snapshot(),before)
        self.assertIn('RECONCILIATION BLOCKED',self.stderr.getvalue())

    def test_ai_validation_failure_preserves_review_and_exports_draft_evidence(self):
        self.assertEqual(self.pipeline([meeting()],prs=[pr()]),0);before=self.snapshot()
        output=self.directory/'bad-ai.json';output.write_text(json.dumps([{'block_id':'stale','description':'Wrong'}]))
        self.assertEqual(self.pipeline([meeting()],prs=[pr()],ai_output=output),2)
        self.assertEqual(self.snapshot(),before)
        draft=json.loads((self.output/'drafts'/f'{DATE}.json').read_text())
        self.assertEqual(draft['ai_input']['unassigned_activity'][0]['id'],55)

    def test_demo_review_is_isolated_and_labelled(self):
        self.assertEqual(self.pipeline([meeting()],prs=[pr()]),0);before=self.snapshot()
        self.assertEqual(self.pipeline(prs=[pr()],demo=True),0)
        self.assertEqual(self.snapshot(),before)
        review=json.loads((self.output/'demo'/f'{DATE}.activity-review.json').read_text())
        self.assertEqual(review['collection_status'],'demo')
        self.assertIn('DEMO:',(self.output/'demo'/f'{DATE}.md').read_text())
        self.assertEqual(json.loads((self.ai.parent/'demo'/self.ai.name).read_text())['unassigned_activity'][0]['id'],55)

    def test_calendar_overlap_and_unassigned_activity_both_keep_review(self):
        self.assertEqual(self.pipeline([meeting('15:00','16:00','A'),meeting('15:30','16:30','B')],prs=[pr()]),0)
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in self.read('')),90)
        self.assertEqual(self.read('.collection')['review']['status'],'required')
        md=(self.output/f'{DATE}.md').read_text()
        self.assertIn('attendance confirmation',md)
        self.assertIn('Unassigned activity',md)

if __name__=='__main__':unittest.main()
