"""Workstream proposals cannot change coverage, evidence, boundaries or usage attribution."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from test_commit_groups import grouped, linked
from test_commit_intervals import event, DATE
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from prepare_ai_input import prepare_activity_input
from summary_request import build_summary_request, expand_judgments, commit_group_mapping, serialize_request
from workstream_groups import candidate_segments, block_id
from activity_snapshot import save_snapshot, read_snapshot
from run_codex_summary import run_summary, summary_instructions, SESSION_INSTRUCTIONS, WORKSTREAM_INSTRUCTIONS
from collect_token_usage import collect_run
from workflow_steps import inspect_run
from save_timesheet import save_timesheet
from benchmark_codex_summary import benchmark


def example(**kwargs):
    value = grouped([linked('09:30', 'a', 1, message='Add CSV row validation'),
                    linked('10:00', 'b', 2, message='Test CSV row validation'),
                    linked('10:20', 'c', message='Update setup instructions')], **kwargs)
    value['calendar_context'] = []
    return value


def output_for(blocks, groups):
    payload = prepare_activity_input(blocks, [])
    request, mapping = build_summary_request(payload['blocks'])
    judgments = [{'job_ids': group, 'description': f'Implemented work item {n}.'} for n, group in enumerate(groups)]
    return expand_judgments(request, mapping, judgments)


class TestWorkstreamGroups(unittest.TestCase):
    def test_benchmark_accepts_fewer_rows_with_same_source_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); snapshot = root / 'activity.json'
            m = example(); blocks = build_time_blocks(m)
            save_snapshot(snapshot, m, {'status': 'complete'}, blocks, [], prepare_activity_input(blocks, []))

            def fake(command, **kwargs):
                if command[-1] == '--version':
                    return subprocess.CompletedProcess(command, 0, stdout='codex synthetic')
                path = Path(command[command.index('--output-last-message') + 1])
                request = json.loads((path.parent / 'request.json').read_text())
                if 'merge_candidates' in request:
                    judgments = [{'job_ids': ['j1', 'j2'], 'description': 'Validated CSV imports and tested failures.'},
                                 {'job_ids': ['j3'], 'description': 'Documented environment setup.'}]
                else:
                    judgments = [{'block_id': b['block_id'], 'description': 'Recorded development work.'}
                                 for b in request['blocks']]
                path.write_text(json.dumps({'judgments': judgments}))
                events = [{'type': 'thread.started', 'thread_id': 'synthetic-' + path.parent.name},
                          {'type': 'turn.started'}, {'type': 'turn.completed',
                           'usage': {'input_tokens': 100, 'cached_input_tokens': 0, 'output_tokens': 20}}]
                kwargs['stdout'].write('\n'.join(json.dumps(e) for e in events))
                return subprocess.CompletedProcess(command, 0)

            with patch('run_codex_summary.subprocess.run', side_effect=fake):
                report = benchmark(snapshot, root / 'benchmark', model='synthetic-model')
            self.assertEqual(report['output_rows'], {'legacy': 3, 'compact': 2})
            self.assertTrue(report['source_intervals_evidence_metadata_unchanged'])
            self.assertFalse(report['intervals_evidence_metadata_unchanged'])
            self.assertEqual(report['attempt_usage']['total_known_tokens'], 240)
            with patch('run_codex_summary.subprocess.run', side_effect=AssertionError('No new model call')):
                self.assertEqual(benchmark(snapshot, root / 'benchmark', model='synthetic-model', resume=True), report)

    def test_different_prs_merge_without_losing_minutes_or_evidence(self):
        blocks = build_time_blocks(example())
        before = copy.deepcopy(blocks)
        rows = build_entries(blocks, output_for(blocks, [['j1', 'j2'], ['j3']]))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['entry']['start'], '09:00')
        self.assertEqual(rows[0]['entry']['end'], '10:00')
        self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows), 80)
        self.assertEqual(rows[0]['source_block_ids'], [block_id(b) for b in blocks[:2]])
        self.assertEqual(rows[0]['allocation']['source_allocations'], [b['allocation'] for b in blocks[:2]])
        self.assertEqual(rows[0]['sources']['commits'], blocks[0]['commits'] + blocks[1]['commits'])
        self.assertTrue(rows[0]['entry']['description'].endswith('PRs: #1, #2'))
        self.assertEqual(rows[0]['entry']['description'].count('PRs:'), 1)
        self.assertEqual(blocks, before)

    def test_no_ai_or_singleton_decisions_do_not_merge(self):
        blocks = build_time_blocks(example())
        self.assertEqual(len(build_entries(blocks)), 3)
        self.assertEqual(len(build_entries(blocks, output_for(blocks, [['j1'], ['j2'], ['j3']]))), 3)

    def test_no_pr_commits_can_group_by_content_but_are_not_automatically_grouped(self):
        blocks = build_time_blocks(grouped([linked('09:30', 'a'), linked('10:00', 'b')]))
        self.assertEqual(len(build_entries(blocks)), 2)
        rows = build_entries(blocks, output_for(blocks, [['j1', 'j2']]))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['entry']['description'].endswith('PRs: None'))

    def test_lunch_meeting_and_confirmed_end_tail_are_boundaries(self):
        m = grouped([linked('11:50', 'a', 1), linked('14:00', 'b', 2), linked('15:30', 'c', 3)],
                    calendar=[event('14:30', '15:00')], end='16:00')
        blocks = build_time_blocks(m)
        candidates = candidate_segments(blocks)
        by_id = {block_id(b): b for b in blocks}
        for segment in candidates:
            self.assertTrue(all(by_id[i]['allocation']['basis'] == 'ending_commit' for i in segment))
            for a, b in zip(segment, segment[1:]):
                self.assertEqual(by_id[a]['interval']['end'], by_id[b]['interval']['start'])
        # Forged AI membership across lunch is rejected even when descriptions agree.
        lunch = [b for b in blocks if b['end_time'] == '12:00'][0]
        afternoon = [b for b in blocks if b['start_time'] == '13:30'][0]
        ids = [block_id(lunch), block_id(afternoon)]
        with self.assertRaises(ValueError):
            build_entries(blocks, [{'block_id': i, 'description': 'Related work.', 'workstream_group': ids} for i in ids])
        tail = blocks[-1]
        self.assertFalse(any(block_id(tail) in s for s in candidates))

    def test_repository_work_type_and_calendar_overlap_cannot_merge(self):
        for change in ('repo', 'type', 'calendar'):
            blocks = build_time_blocks(example())[:2]
            if change == 'repo':
                blocks[1]['commits'][0]['repository'] = 'other/repo'
            elif change == 'type':
                blocks[0]['work_type'], blocks[1]['work_type'] = 'NORMAL', 'OT'
            else:
                blocks[1]['calendar_overlap'] = True
            self.assertEqual(candidate_segments(blocks), [], change)

    def test_four_hour_limit_does_not_change_source_intervals(self):
        blocks = build_time_blocks(grouped([linked('14:30', 'a', 1), linked('16:30', 'b', 2),
                                            linked('18:00', 'c', 3)], start='13:30'))
        candidates = candidate_segments(blocks)
        self.assertEqual(candidates, [[block_id(b) for b in blocks[:2]]])
        with self.assertRaises(ValueError):
            output_for(blocks, [['j1', 'j2', 'j3']])

    def test_missing_duplicate_reordered_and_nonconsecutive_jobs_rejected(self):
        blocks = build_time_blocks(example())
        for groups in ([['j1'], ['j2']], [['j1', 'j2'], ['j2'], ['j3']],
                       [['j2'], ['j1'], ['j3']], [['j1', 'j3'], ['j2']], [['j9']]):
            with self.subTest(groups=groups), self.assertRaises(ValueError):
                output_for(blocks, groups)

    def test_forged_membership_and_conflicting_descriptions_rejected(self):
        blocks = build_time_blocks(example())
        good = output_for(blocks, [['j1', 'j2'], ['j3']])
        for change in ('missing', 'description', 'self', 'unknown', 'suffix', 'length'):
            bad = copy.deepcopy(good)
            if change == 'missing': del bad[1]['workstream_group']
            elif change == 'description': bad[1]['description'] = 'Different work.'
            elif change == 'self': bad[0]['workstream_group'] = [block_id(b) for b in blocks[1:]]
            elif change == 'unknown': bad[0]['workstream_group'] = ['stale', 'other']
            elif change == 'suffix': bad[0]['description'] = 'Work. PRs: #99'
            else:
                for b in bad[:2]: b['description'] = 'x' * 601
            with self.subTest(change=change), self.assertRaises(ValueError): build_entries(blocks, bad)

    def test_opaque_candidates_are_in_byte_bound_and_v4_replays_unchanged(self):
        m = example(); blocks = build_time_blocks(m)
        payload = prepare_activity_input(blocks, [])
        request = payload['summary_request']
        self.assertEqual(payload['payload_version'], 6)
        self.assertEqual(request['grouping_policy'], 'related_work_session_v1')
        self.assertEqual(summary_instructions(request), SESSION_INSTRUCTIONS)
        self.assertEqual(request['merge_candidates'], [['j1', 'j2', 'j3']])
        for value in ('09:30', DATE, 'org/repo', 'block_id'):
            self.assertNotIn(value, serialize_request(request))
        size = len(serialize_request(request).encode())
        self.assertEqual(payload['payload_measurement']['model_payload_bytes'], size)
        with self.assertRaises(ValueError): prepare_activity_input(blocks, [], size - 1)
        with tempfile.TemporaryDirectory() as directory:
            old = prepare_activity_input(blocks, [], payload_version=4)
            path = Path(directory) / 'old.json'
            saved = save_snapshot(path, m, {'status': 'complete'}, blocks, [], old)
            self.assertEqual(saved, read_snapshot(path))
            self.assertNotIn('merge_candidates', old['summary_request'])

    def test_v5_snapshot_and_instruction_replay_remain_unchanged(self):
        m = example(); blocks = build_time_blocks(m)
        old = prepare_activity_input(blocks, [], payload_version=5)
        self.assertNotIn('grouping_policy', old['summary_request'])
        self.assertEqual(summary_instructions(old['summary_request']), WORKSTREAM_INSTRUCTIONS)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'v5.json'
            saved = save_snapshot(path, m, {'status': 'complete'}, blocks, [], old)
            self.assertEqual(read_snapshot(path), saved)

    def test_mixed_or_unknown_session_policy_is_rejected(self):
        blocks = build_time_blocks(example())
        payload = prepare_activity_input(blocks, [])
        for policy in (None, 'unknown'):
            bad = copy.deepcopy(payload['blocks'])
            if policy is None: del bad[0]['session_grouping']
            else: bad[0]['session_grouping'] = policy
            with self.subTest(policy=policy), self.assertRaises(ValueError): build_summary_request(bad)
        with self.assertRaises(ValueError):
            summary_instructions({'grouping_policy': 'unknown', 'merge_candidates': []})

    def test_runner_assembly_usage_and_grouping_view_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); snapshot = root / 'activity.json'
            m = example(); blocks = build_time_blocks(m)
            save_snapshot(snapshot, m, {'status': 'complete'}, blocks, [], prepare_activity_input(blocks, []))
            before = snapshot.read_bytes()
            def fake(command, **kwargs):
                if command[-1] == '--version':
                    return subprocess.CompletedProcess(command, 0, stdout='codex synthetic')
                request = json.loads(kwargs['input'])
                self.assertEqual(request['merge_candidates'], [['j1', 'j2', 'j3']])
                self.assertEqual(request['grouping_policy'], 'related_work_session_v1')
                path = Path(command[command.index('--output-last-message') + 1])
                path.write_text(json.dumps({'judgments': [
                    {'job_ids': ['j1', 'j2'], 'description': 'Implemented CSV validation and tests.'},
                    {'job_ids': ['j3'], 'description': 'Updated setup instructions.'}]}))
                events = [{'type': 'thread.started', 'thread_id': 'synthetic-workstream'},
                          {'type': 'turn.started'}, {'type': 'turn.completed',
                           'usage': {'input_tokens': 150, 'cached_input_tokens': 10, 'output_tokens': 20}}]
                kwargs['stdout'].write('\n'.join(json.dumps(e) for e in events))
                return subprocess.CompletedProcess(command, 0)
            with patch('run_codex_summary.subprocess.run', side_effect=fake):
                result = run_summary(snapshot, root / 'codex')
            self.assertEqual((result['source_blocks'], result['output_blocks']), (3, 2))
            usage = collect_run(result['usage_run_manifest'], ZoneInfo('Asia/Ho_Chi_Minh'))
            self.assertEqual(usage['total_tokens'], 170)
            self.assertEqual(json.loads(inspect_run(root, 'grouping'))['output_blocks'], 2)
            self.assertEqual(json.loads(inspect_run(root, 'grouping'))['grouping_policy'], 'related_work_session_v1')
            ai = json.loads(Path(result['ai_output']).read_text())
            rows = build_entries(blocks, ai, summary_groups=commit_group_mapping(read_snapshot(snapshot)['ai_input']['blocks']))
            save_timesheet(rows, root / 'timesheets', target_date=DATE, collection_status='complete')
            saved = json.loads((root / 'timesheets' / (DATE + '.json')).read_text())
            self.assertEqual(len(saved), 2)
            self.assertEqual(saved[0]['source_block_ids'], rows[0]['source_block_ids'])
            config = root / 'config.json'; config.write_text('{}')
            command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/run_pipeline.py'),
                       '--phase', 'assemble', '--snapshot', str(snapshot), '--config', str(config),
                       '--ai-output', result['ai_output'], '--usage-run-manifest', result['usage_run_manifest'],
                       '--token-csv-path', str(root / 'tokens.csv'), '--output-dir', str(root / 'cli-output')]
            assembled = subprocess.run(command, capture_output=True, text=True, timeout=20)
            self.assertEqual(assembled.returncode, 0, assembled.stdout + assembled.stderr)
            cli_rows = json.loads((root / 'cli-output' / (DATE + '.json')).read_text())
            self.assertEqual([r['entry'] for r in cli_rows], [r['entry'] for r in rows])
            self.assertEqual(snapshot.read_bytes(), before)


if __name__ == '__main__': unittest.main()
