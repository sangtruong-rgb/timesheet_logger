"""PR grouping preserves exact coverage and never guesses work identity."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from test_commit_intervals import model, commit, event, intervals
from build_time_blocks import build_time_blocks
from activity_snapshot import read_snapshot, save_snapshot
from prepare_ai_input import prepare_activity_input
from commit_groups import GROUPING_POLICY, LEGACY_GROUPING_POLICY, enrich_commit_prs, group_adjacent_blocks


def linked(time, sha, number=None, *, status='resolved', repo='org/repo', message=None):
    c = commit(time, sha)
    c.update(repository=repo, pr_association={'status': status, 'prs': []})
    if number is not None:
        numbers = number if isinstance(number, list) else [number]
        c['pr_association']['prs'] = [{'repository': repo, 'id': n, 'title': f'PR scope {n}'} for n in numbers]
    if message:
        c['message'] = message
    return c


def grouped(commits, **kwargs):
    m = model(commits, **kwargs)
    m['commit_grouping'] = GROUPING_POLICY
    return m


class CommitGroupsTest(unittest.TestCase):
    def test_identical_verified_pr_batches_merge_but_partial_overlap_does_not(self):
        m = grouped([linked('09:30','a',1), linked('09:30','b',2),
                     linked('09:40','c',1), linked('09:40','d',2),
                     linked('09:50','e',2), linked('09:50','f',3)])
        blocks = build_time_blocks(m)
        self.assertEqual(intervals(blocks), [('09:00','09:40',40), ('09:40','09:50',10)])
        self.assertEqual(len(blocks[0]['commits']), 4)
        self.assertEqual([p['id'] for p in blocks[0]['prs']], [1,2])
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'snapshot.json'
            saved=save_snapshot(path,m,{'status':'complete'},blocks,[],prepare_activity_input(blocks,[]))
            self.assertEqual(read_snapshot(path),saved)

    def test_frozen_v1_pr_batches_replay_separately(self):
        m = grouped([linked('09:30','a',1), linked('09:30','b',2),
                     linked('09:40','c',1), linked('09:40','d',2)])
        m['commit_grouping'] = LEGACY_GROUPING_POLICY
        blocks = build_time_blocks(m)
        self.assertEqual(len(blocks),2)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'snapshot.json'
            saved=save_snapshot(path,m,{'status':'complete'},blocks,[],prepare_activity_input(blocks,[]))
            self.assertEqual(read_snapshot(path),saved)

    def test_same_pr_merges_long_and_short_return_to_pr_stays_separate(self):
        blocks = build_time_blocks(grouped([linked('09:30','a',1), linked('10:00','b',1),
                                            linked('10:10','c',2), linked('11:00','d',1)]))
        self.assertEqual(intervals(blocks), [('09:00','10:00',60),('10:00','10:10',10),('10:10','11:00',50)])
        self.assertEqual([c['hash'] for c in blocks[0]['commits']], ['a','b'])
        self.assertEqual([p['id'] for p in blocks[0]['prs']], [1])

    def test_none_unknown_ambiguous_different_repo_stay_separate(self):
        cases = [(None,'resolved'),(1,'unknown'),([1,2],'resolved')]
        for number,status in cases:
            blocks=build_time_blocks(grouped([linked('09:10','a',number,status=status,message='ABC-1'),
                                               linked('09:20','b',number,status=status,message='ABC-1')]))
            self.assertEqual(len(blocks), 1 if number is None and status=='resolved' else 2)
        self.assertEqual(len(build_time_blocks(grouped([linked('09:10','a'),linked('09:20','b')]))),2)
        self.assertEqual(len(build_time_blocks(grouped([linked('09:10','a',1),linked('09:20','b',1,repo='other/repo')]))),2)

    def test_same_minute_conflicting_prs_not_arbitrarily_assigned(self):
        blocks=build_time_blocks(grouped([linked('09:10','a',1),linked('09:10','b',2),linked('09:20','c',1)]))
        self.assertEqual(len(blocks),2)
        self.assertEqual(len(blocks[0]['commits']),2)

    def test_lunch_calendar_and_tail_preserve_coverage(self):
        m=grouped([linked('11:40','a',1),linked('14:10','b',1),linked('15:10','c',1)],
                  calendar=[event('14:30','15:00')],end='15:30')
        blocks=build_time_blocks(m)
        self.assertEqual(intervals(blocks), [('09:00','12:00',180),('13:30','14:30',60),
                                             ('14:30','15:00',30),('15:00','15:10',10),('15:10','15:30',20)])
        self.assertEqual(blocks[-1]['allocation']['basis'],'confirmed_end')
        self.assertEqual(sum(b['duration_minutes'] for b in blocks),300)

    def test_ot_boundary_is_not_merged(self):
        m=grouped([linked('09:30','a',1),linked('10:00','b',1)])
        del m['commit_grouping']
        blocks=build_time_blocks(m,merge_short_commits=False)
        blocks[0]['work_type']='NORMAL'; blocks[1]['work_type']='OT'
        self.assertEqual(len(group_adjacent_blocks(blocks)),2)

    def test_lookup_distinguishes_empty_error_ambiguous_and_caches(self):
        client=Mock()
        client.items.side_effect=[[], RuntimeError('secret must not leak'),
                                 [{'number':1,'title':'one'},{'number':2,'title':'two'}]]
        commits=[linked('09:10','a'*40),linked('09:20','b'*40),linked('09:30','c'*40),linked('09:40','a'*40)]
        counts=enrich_commit_prs(commits,client=client)
        self.assertEqual(counts,{'resolved':3,'unknown':1})
        self.assertEqual(client.items.call_count,3)
        self.assertEqual(commits[0]['pr_association']['prs'],[])
        self.assertEqual(commits[1]['pr_association'],{'status':'unknown','prs':[],'reason':'RuntimeError'})
        self.assertEqual(len(commits[2]['pr_association']['prs']),2)

    def test_snapshot_roundtrip_and_action_context(self):
        m=grouped([linked('09:30','a',1),linked('10:00','b',1)])
        blocks=build_time_blocks(m)
        payload=prepare_activity_input(blocks,[])
        self.assertEqual(payload['payload_version'],6)
        self.assertIn('title is context', str(payload['summary_request']))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'activity.json'
            saved=save_snapshot(path,m,{'status':'complete'},blocks,[],payload)
            self.assertEqual(saved['schema_version'],9)
            self.assertEqual(read_snapshot(path),saved)
        # Old models still reproduce the old under-20 rule.
        old=copy.deepcopy(m); del old['commit_grouping']
        self.assertEqual(len(build_time_blocks(old)),2)

if __name__=='__main__': unittest.main()
