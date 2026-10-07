"""F08: timestamp attribution, evidence conservation and review persistence."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from prepare_ai_input import prepare_activity_input
from save_timesheet import save_timesheet, TimesheetReconciliationError

DATE = '2026-10-07'

def meeting(start='15:00', end='16:00', title='Kickoff'):
    return {'title': title, 'start': f'{DATE}T{start}:00+07:00', 'end': f'{DATE}T{end}:00+07:00'}

def commit(time='20:00', identity='c1'):
    return {'hash': identity, 'timestamp': f'{DATE}T{time}:00+07:00', 'message': 'Fix payment'}

def pr(time='00:02', identity=55):
    return {'id': identity, 'repository': 'test/project', 'title': 'Fix payment', 'status': 'opened',
            'timestamp': f'{DATE}T{time}:00+07:00'}

def model(calendars=None, commits=None, prs=None):
    return {'date': DATE, 'timezone': 'Asia/Ho_Chi_Minh', 'calendar': calendars or [],
            'commits': commits or [], 'pull_requests': prs or []}

def assignment(data):
    review = []
    blocks = build_time_blocks(data, unassigned_activity=review)
    return blocks, review

class TestTimestampAssignment(unittest.TestCase):
    def test_midnight_pr_does_not_contaminate_meeting_summary(self):
        activity = pr()
        blocks, review = assignment(model([meeting()], prs=[activity]))
        self.assertEqual(blocks[0]['prs'], [])
        self.assertEqual(build_entries(blocks)[0]['entry']['description'], 'Kickoff. PRs: None')
        self.assertEqual(review, [{'source': 'github', 'reason': 'outside_blocks', 'activity': activity}])

    def test_commits_do_not_fall_into_first_development_block_or_last_meeting(self):
        for calendars, activities in [([meeting()], [commit()]),
                                     ([meeting()], [commit('10:00', 'supported'), commit()])]:
            with self.subTest(activities=activities):
                blocks, review = assignment(model(calendars, activities))
                self.assertEqual([c['hash'] for b in blocks for c in b['commits']],
                                 ['supported'] if len(activities) == 2 else [])
                self.assertEqual(review[0]['activity']['hash'], 'c1')

    def test_bad_or_wrong_day_timestamps_remain_unassigned_with_reason(self):
        cases = [(None, 'missing_timestamp'), ('', 'missing_timestamp'), ('nonsense', 'invalid_timestamp'),
                 (123, 'invalid_timestamp'), (f'{DATE}T15:30:00', 'naive_timestamp'),
                 ('2026-10-06T15:30:00+07:00', 'outside_target_day'),
                 ('2026-10-08T00:00:00+07:00', 'outside_target_day')]
        for calendar in ([], [meeting()]):
            for timestamp, reason in cases:
                with self.subTest(calendar=calendar, timestamp=timestamp):
                    activity = {**commit(), 'timestamp': timestamp}
                    blocks, review = assignment(model(calendar, [activity]))
                    self.assertFalse(any(b['commits'] for b in blocks))
                    self.assertEqual(review[0]['reason'], reason)
                    self.assertEqual(review[0]['activity'], activity)
                    if not calendar:
                        self.assertEqual(blocks, [])

    def test_equivalent_utc_timestamps_are_assigned_to_correct_blocks(self):
        activities = [{**pr(identity=1), 'timestamp': f'{DATE}T02:30:00Z'},
                      {**pr(identity=2), 'timestamp': f'{DATE}T08:30:00Z'}]
        blocks, review = assignment(model([meeting('09:00','10:00'), meeting()], prs=activities))
        self.assertEqual([[p['id'] for p in b['prs']] for b in blocks], [[1], [2]])
        self.assertEqual(review, [])

    def test_half_open_boundaries_assign_start_and_next_block_not_end(self):
        activities = [commit(t, t) for t in ('09:00', '09:30', '10:00')]
        blocks, review = assignment(model([meeting('09:00','09:30','A'), meeting('09:30','10:00','B')], activities))
        self.assertEqual([[c['hash'] for c in b['commits']] for b in blocks], [['09:00'], ['09:30'], ['10:00']])
        self.assertEqual(review, [])  # 10:00 supports the following estimated gap.
        blocks, review = assignment(model([meeting('23:00','23:59')], [commit('23:59')]))
        self.assertEqual([r['activity']['hash'] for r in review], ['c1'])

    def test_each_pr_action_is_retained_once_in_block_or_review(self):
        events = [{'action': 'opened', 'timestamp': f'{DATE}T00:02:00+07:00'},
                  {'action': 'reviewed', 'timestamp': f'{DATE}T15:30:00+07:00', 'id': 999},
                  {'action': 'merged', 'timestamp': f'{DATE}T20:00:00+07:00'}]
        reference = {**pr(), 'events': events}
        blocks, review = assignment(model([meeting()], prs=[reference]))
        assigned = [e for b in blocks for p in b['prs'] for e in p['events']]
        unmatched = [e for r in review for e in r['activity']['events']]
        self.assertEqual(assigned, [events[1]])
        self.assertEqual(unmatched, [events[0], events[2]])
        self.assertEqual(len(assigned + unmatched), len(events))

    def test_no_calendar_supported_fallback_windows_still_estimated(self):
        cases = [(['10:00'], [('09:00','12:30')]), (['15:00'], [('13:30','17:30')]),
                 (['10:00','15:00'], [('09:00','12:00'),('13:30','17:30')])]
        for times, expected in cases:
            blocks, review = assignment(model(commits=[commit(t,t) for t in times]))
            self.assertEqual([(b['start_time'],b['end_time']) for b in blocks], expected)
            self.assertTrue(all(b['time_basis']=='estimated' for b in blocks))
            self.assertEqual(review, [])

    def test_no_calendar_unmatched_only_has_zero_work_minutes_but_keeps_evidence(self):
        for time in ('00:02', '08:00', '12:30', '17:30', '20:00'):
            with self.subTest(time=time):
                blocks, review = assignment(model(prs=[pr(time)]))
                self.assertEqual(blocks, [])
                self.assertEqual(review[0]['activity'], pr(time))

    def test_unmatched_activity_does_not_land_in_supported_no_calendar_block(self):
        blocks, review = assignment(model(commits=[commit('15:00'),commit('20:00','late')]))
        self.assertEqual([c['hash'] for b in blocks for c in b['commits']], ['c1'])
        self.assertEqual(review[0]['activity']['hash'], 'late')
        self.assertEqual(sum(b['duration_minutes'] for b in blocks), 240)

    def test_short_gap_activity_is_reviewed_not_attached_to_meeting(self):
        blocks, review = assignment(model([meeting('09:00','09:15','A'),meeting('09:25','17:30','B')], [commit('09:20')]))
        self.assertFalse(any(b['commits'] for b in blocks))
        self.assertEqual(review[0]['reason'], 'outside_blocks')

    def test_scheduled_lunch_and_late_meetings_accept_matching_activity(self):
        for start, end, time in [('12:00','13:30','12:30'), ('20:00','21:00','20:30')]:
            blocks, review = assignment(model([meeting(start,end)], [commit(time)]))
            self.assertEqual(blocks[0]['commits'], [commit(time)])
            self.assertEqual(review, [])

    def test_utc_previous_date_is_same_local_day_when_appropriate(self):
        activity = {**commit('00:30'), 'timestamp': '2026-10-06T17:30:00Z'}
        blocks, review = assignment(model([meeting('00:00','01:00')], [activity]))
        self.assertEqual(blocks[0]['commits'], [activity])
        self.assertEqual(review, [])

    def test_model_is_not_mutated(self):
        data = model([meeting()], [commit()], [pr()]); before = copy.deepcopy(data)
        assignment(data)
        self.assertEqual(data, before)

    def test_ai_envelope_excludes_unassigned_evidence_from_block_summaries(self):
        blocks, review = assignment(model([meeting()], [commit()], [pr()]))
        payload = prepare_activity_input(blocks, review)
        self.assertEqual(payload['blocks'], [])
        self.assertEqual(len(payload['unassigned_activity']), 2)
        self.assertEqual(payload['review']['status'], 'required')
        text = json.dumps(payload)
        for field in ('timestamp', 'hash', 'repository', 'actor', 'url'):
            self.assertNotIn('"'+field+'"', text)

class TestReviewPersistence(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.blocks, self.review = assignment(model([meeting()], prs=[pr()]))
        self.entries = build_entries(self.blocks)

    def save(self, entries=None, **kwargs):
        return save_timesheet(self.entries if entries is None else entries, self.directory,
                              target_date=DATE, collection_status='complete', **kwargs)

    def snapshot(self):
        return {p.name:p.read_bytes() for p in self.directory.iterdir() if p.is_file()}

    def test_review_sidecar_and_markdown_do_not_add_duration(self):
        result = self.save(unassigned_activity=self.review)
        self.assertEqual(result['dates'][DATE]['unassigned_activity_count'],1)
        md = (self.directory/f'{DATE}.md').read_text()
        self.assertIn('Total Proposed Time:** 60 mins',md)
        self.assertIn('Unassigned activity',md)
        self.assertIn('PR #55',md)
        record = json.loads((self.directory/f'{DATE}.activity-review.json').read_text())
        self.assertEqual(record['unassigned_activity'],self.review)
        self.assertEqual(record['review']['status'],'required')

    def test_unassigned_only_day_saves_zero_entries_and_all_evidence(self):
        self.save([],unassigned_activity=self.review)
        self.assertEqual(json.loads((self.directory/f'{DATE}.json').read_text()),[])
        self.assertIn('Total Proposed Time:** 0 mins',(self.directory/f'{DATE}.md').read_text())
        self.assertTrue((self.directory/f'{DATE}.activity-review.json').exists())

    def test_exact_review_rerun_preserves_bytes(self):
        self.save(unassigned_activity=self.review); before=self.snapshot()
        self.save(unassigned_activity=self.review)
        self.assertEqual(self.snapshot(),before)

    def test_review_only_changes_rerender_markdown_and_can_clear(self):
        self.save(unassigned_activity=self.review)
        path=self.directory/f'{DATE}.json'; before=path.read_bytes()
        changed=copy.deepcopy(self.review); changed[0]['activity']['title']='New evidence title'
        self.save(unassigned_activity=changed)
        self.assertEqual(path.read_bytes(),before)
        self.assertIn('New evidence title',(self.directory/f'{DATE}.md').read_text())
        self.save(unassigned_activity=[])
        self.assertNotIn('Unassigned activity',(self.directory/f'{DATE}.md').read_text())
        self.assertEqual(json.loads((self.directory/f'{DATE}.activity-review.json').read_text())['review']['status'],'none')

    def test_omitted_review_preserves_previous_sidecar(self):
        self.save(unassigned_activity=self.review); before=self.snapshot()
        self.save()
        self.assertEqual(self.snapshot(),before)

    def test_corrupt_or_invalid_review_blocks_all_final_writes(self):
        for corrupt in ('invalid-json',json.dumps({'date':DATE,'collection_status':'complete','unassigned_activity':[]})):
            self.save(unassigned_activity=self.review)
            path=self.directory/f'{DATE}.activity-review.json'; path.write_text(corrupt)
            before=self.snapshot()
            with self.assertRaises(TimesheetReconciliationError):
                self.save([],unassigned_activity=[])
            self.assertEqual(self.snapshot(),before)
            path.unlink()

    def test_bad_incoming_review_preserves_existing_files(self):
        self.save(unassigned_activity=self.review); before=self.snapshot()
        with self.assertRaises(TimesheetReconciliationError):
            self.save([],unassigned_activity=[{'source':'github','reason':'random','activity':pr()}])
        self.assertEqual(self.snapshot(),before)

    def test_invalid_envelopes_block_standalone_preparation_and_assembly(self):
        source = self.directory/'bad-snapshot.json'; output = self.directory/'protected-output.json'
        for malformed in ({'blocks': []}, {'blocks': [], 'unassigned_activity': None},
                          {'blocks': [], 'unassigned_activity': [{'source': 'git', 'reason': [], 'activity': {}}]}):
            for script, flag in [('prepare_ai_input.py','-i'), ('build_timesheet.py','-b')]:
                with self.subTest(malformed=malformed,script=script):
                    source.write_text(json.dumps(malformed)); output.write_text('OLD OUTPUT')
                    response = subprocess.run([sys.executable,str(ROOT/'scripts'/script),flag,str(source),'-o',str(output)],capture_output=True,text=True,timeout=15)
                    self.assertEqual(response.returncode,2,response.stderr)
                    self.assertEqual(output.read_text(),'OLD OUTPUT')

    def test_wrong_date_review_store_is_rejected_before_writes(self):
        self.save(unassigned_activity=self.review)
        path=self.directory/f'{DATE}.activity-review.json';record=json.loads(path.read_text())
        record['date']='2026-10-06';path.write_text(json.dumps(record));before=self.snapshot()
        with self.assertRaises(TimesheetReconciliationError):self.save([],unassigned_activity=[])
        self.assertEqual(self.snapshot(),before)

    def test_standalone_cli_chain_keeps_review_when_no_blocks_exist(self):
        normalized=self.directory/'normalized.json'; normalized.write_text(json.dumps(model(prs=[pr()])))
        blocks=self.directory/'blocks.json'; ai=self.directory/'ai.json'; entries=self.directory/'entries.json'
        commands=[('build_time_blocks.py',['-i',str(normalized),'-o',str(blocks)]),
                  ('prepare_ai_input.py',['-i',str(blocks),'-o',str(ai)]),
                  ('build_timesheet.py',['-b',str(blocks),'-o',str(entries)]),
                  ('save_timesheet.py',['-i',str(entries),'-d',str(self.directory/'output'),'--date',DATE,'--collection-status','complete'])]
        for script,args in commands:
            response=subprocess.run([sys.executable,str(ROOT/'scripts'/script),*args],capture_output=True,text=True,timeout=15)
            self.assertEqual(response.returncode,0,response.stderr)
        self.assertEqual(json.loads(ai.read_text())['blocks'],[])
        record=json.loads((self.directory/'output'/f'{DATE}.activity-review.json').read_text())
        self.assertEqual(record['unassigned_activity'][0]['activity']['id'],55)
        self.assertEqual(json.loads((self.directory/'output'/f'{DATE}.json').read_text()),[])

if __name__=='__main__':
    unittest.main()
