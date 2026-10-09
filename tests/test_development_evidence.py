"""New runs leave unsupported development blank; frozen history remains replayable."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from test_commit_intervals import model, commit, pr, event, intervals
from activity_snapshot import save_snapshot, read_snapshot, fingerprint, SnapshotError
from block_settings import DEVELOPMENT_EVIDENCE_POLICY
from commit_groups import GROUPING_POLICY
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from prepare_ai_input import prepare_activity_input


def current_model(**kwargs):
    return {**model(end='17:30', **kwargs), 'commit_grouping': GROUPING_POLICY,
            'development_evidence_policy': DEVELOPMENT_EVIDENCE_POLICY}


class TestDevelopmentEvidence(unittest.TestCase):
    def test_empty_windows_produce_no_blocks_ai_jobs_or_entries(self):
        blocks = build_time_blocks(current_model())
        self.assertEqual(blocks, [])
        self.assertEqual(prepare_activity_input(blocks, [])['blocks'], [])
        self.assertEqual(build_entries(blocks), [])

    def test_last_commit_does_not_fill_the_rest_of_the_day(self):
        blocks = build_time_blocks(current_model(commits=[commit('10:00')]))
        self.assertEqual(intervals(blocks), [('09:00', '10:00', 60)])
        rows = build_entries(blocks)
        self.assertEqual(len(rows), 1)
        self.assertNotIn('Project development and focus tasks.', rows[0]['entry']['description'])

    def test_calendar_survives_without_development_evidence(self):
        blocks = build_time_blocks(current_model(calendar=[event('11:00', '11:45')]))
        self.assertEqual(intervals(blocks), [('11:00', '11:45', 45)])
        self.assertEqual(blocks[0]['block_type'], 'calendar')

    def test_pr_only_piece_survives_but_empty_afternoon_does_not(self):
        blocks = build_time_blocks(current_model(prs=[pr('10:15', 42)]))
        self.assertEqual(intervals(blocks), [('09:00', '12:00', 180)])
        self.assertEqual([p['id'] for p in blocks[0]['prs']], [42])

    def test_closing_commit_evidence_survives_lunch_and_meeting_splits(self):
        blocks = build_time_blocks(current_model(commits=[commit('14:30')],
                                                calendar=[event('11:00', '11:30')]))
        self.assertEqual(intervals(blocks), [('09:00', '11:00', 120), ('11:00', '11:30', 30),
                                           ('11:30', '12:00', 30), ('13:30', '14:30', 60)])
        self.assertTrue(all(b['commits'] for b in blocks if b['block_type'] == 'development'))

    def test_outside_window_activity_is_review_only(self):
        retained = []
        blocks = build_time_blocks(current_model(commits=[commit('18:00')], prs=[pr('08:00', 1)]),
                                   unassigned_activity=retained)
        self.assertEqual(blocks, [])
        self.assertEqual({r['source'] for r in retained}, {'git', 'github'})

    def test_old_snapshot_replays_placeholders_new_snapshot_rejects_policy_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            for current in (False, True):
                value = current_model()
                if not current:
                    del value['development_evidence_policy']
                blocks = build_time_blocks(value)
                path = Path(directory) / f'{current}.json'
                save_snapshot(path, value, {'status': 'complete'}, blocks, [], prepare_activity_input(blocks, []))
                frozen = read_snapshot(path)
                self.assertEqual(frozen['schema_version'], 10 if current else 9)
                self.assertEqual(len(frozen['blocks']), 0 if current else 2)
                if current:
                    for change in ('version', 'missing_policy', 'unknown_policy'):
                        broken = copy.deepcopy(frozen)
                        if change == 'version':
                            broken['schema_version'] = 9
                        elif change == 'missing_policy':
                            del broken['normalized']['development_evidence_policy']
                        else:
                            broken['normalized']['development_evidence_policy'] = 'unknown'
                        broken['fingerprint'] = fingerprint({k: v for k, v in broken.items() if k != 'fingerprint'})
                        path.write_text(json.dumps(broken))
                        with self.subTest(change=change), self.assertRaises(SnapshotError):
                            read_snapshot(path)
