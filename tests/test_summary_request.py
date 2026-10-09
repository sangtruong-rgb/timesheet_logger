"""Verify evidence sharing, complete mapping and measured invocation provenance."""
import json
import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from activity_snapshot import read_snapshot, save_snapshot, fingerprint, SnapshotError
from codex_usage import sha256
from collect_token_usage import collect_run
from prepare_ai_input import prepare_activity_input
from run_codex_summary import run_summary
from summary_request import build_summary_request, expand_judgments, serialize_request, commit_group_mapping
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries, AIJudgmentError
from test_commit_intervals import model, commit, pr, event
from benchmark_codex_summary import benchmark
import test_remaining_storage as fixture


class TestSummaryRequest(unittest.TestCase):
    def setUp(self):
        fixture.TestRemainingStorage.setUp(self)

    def block(self, start, end, message='Fix CSV import', prs=None, calendar=None):
        return {'date': '2026-10-07', 'start_time': start, 'end_time': end,
                'commits': [{'message': message}], 'prs': prs or [], 'calendar_titles': calendar or []}

    def test_lunch_pieces_share_job_and_expand_to_both_intervals(self):
        payload = prepare_activity_input([self.block('11:40', '12:00'), self.block('13:30', '14:10')], [])
        request, mapping = build_summary_request(payload['blocks'])
        self.assertEqual(len(request['jobs']), 1)
        self.assertEqual(list(request['texts'].values()), ['Fix CSV import'])
        rows = expand_judgments(request, mapping, [{'id': 'j1', 'description': 'Sửa nhập CSV'}])
        self.assertEqual([r['block_id'] for r in rows], [b['block_id'] for b in payload['blocks']])

    def split_group(self, *, calendar=False):
        reference = {**pr('10:45' if calendar else '13:45', 101), 'title': 'Add CSV tests'}
        activity = (model([commit('11:00', 'csv')], [event('09:30', '10:30')], prs=[reference])
                    if calendar else model([commit('14:10', 'csv')], prs=[reference], start='11:40'))
        blocks = build_time_blocks(activity)
        payload = prepare_activity_input(blocks, [])
        return activity, blocks, payload

    def test_same_allocation_different_pr_context_uses_one_description_and_row_owned_suffix(self):
        _, blocks, payload = self.split_group()
        original = copy.deepcopy(blocks)
        request, mapping = build_summary_request(payload['blocks'])
        self.assertEqual(payload['payload_version'], 3)
        self.assertEqual(len(request['jobs']), 1)
        self.assertEqual([payload['blocks'][0]['summary_group_id']], [payload['blocks'][1]['summary_group_id']])
        self.assertEqual([request['texts'][t] for t in request['jobs'][0]['prs']], ['Add CSV tests'])
        self.assertNotIn('summary_group_id', serialize_request(request))
        judgments = expand_judgments(request, mapping, [{'id': 'j1', 'description': 'Sửa CSV và thêm kiểm thử'}])
        entries = build_entries(blocks, judgments, summary_groups=commit_group_mapping(payload['blocks']))
        self.assertEqual([e['entry']['description'] for e in entries],
                         ['Sửa CSV và thêm kiểm thử. PRs: None', 'Sửa CSV và thêm kiểm thử. PRs: #101'])
        self.assertEqual([len(e['sources']['pull_requests']) for e in entries], [0, 1])
        self.assertEqual(sum(e['entry']['duration_minutes'] for e in entries), 60)
        self.assertEqual(blocks, original)

    def test_commit_in_start_minute_does_not_split_summary_group(self):
        early = commit('09:00', 'early')
        early['timestamp'] = early['timestamp'].replace('09:00:00', '09:00:30')
        for calendar in ([], [event('10:00', '11:00')]):
            blocks = build_time_blocks(model([early, commit('14:10', 'closing')], calendar))
            payload = prepare_activity_input(blocks, [])
            request, mapping = build_summary_request(payload['blocks'])
            self.assertEqual(len(request['jobs']), 1)
            self.assertEqual({request['texts'][t] for t in request['jobs'][0]['commits']}, {'work early', 'work closing'})
            rows = build_entries(blocks, summary_groups=commit_group_mapping(payload['blocks']))
            work = [r for r in rows if r['time_basis'] == 'estimated']
            self.assertEqual(len({r['entry']['description'] for r in work}), 1)
            self.assertEqual([len(r['sources']['commits']) for r in work], [2] + [1] * (len(work) - 1))
            self.assertEqual(sum(r['entry']['duration_minutes'] for r in rows), 220)

    def test_historical_v3_group_and_allocation_replay_are_preserved(self):
        early = commit('09:00', 'early')
        early['timestamp'] = early['timestamp'].replace('09:00:00', '09:00:30')
        activity = model([early, commit('14:10', 'closing')])
        blocks = build_time_blocks(activity, commit_allocation_version=1)
        payload = prepare_activity_input(blocks, [])
        frozen = save_snapshot(self.snapshot, activity, self.collection, blocks, [], payload)
        frozen['schema_version'] = 3
        frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
        self.snapshot.write_text(json.dumps(frozen))
        self.assertEqual(read_snapshot(self.snapshot)['blocks'], blocks)
        self.assertEqual(len(payload['summary_request']['jobs']), 2)
        frozen['schema_version'] = 4
        frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
        self.snapshot.write_text(json.dumps(frozen))
        with self.assertRaises(SnapshotError): read_snapshot(self.snapshot)

    def test_calendar_split_uses_one_commit_description_and_preserves_meeting(self):
        _, blocks, payload = self.split_group(calendar=True)
        request, mapping = build_summary_request(payload['blocks'])
        self.assertEqual(len(request['jobs']), 1)
        judgments = expand_judgments(request, mapping, [{'id': 'j1', 'description': 'Sửa CSV và kiểm thử'}])
        entries = build_entries(blocks, judgments, summary_groups=commit_group_mapping(payload['blocks']))
        work = [e for e in entries if e['time_basis'] == 'estimated']
        self.assertEqual([e['entry']['description'].split(' PRs:')[0] for e in work], ['Sửa CSV và kiểm thử.'] * 2)
        meeting = [e for e in entries if e['time_basis'] == 'scheduled'][0]
        self.assertEqual(meeting['entry']['description'], 'Scheduled calendar activity; attendance unconfirmed. PRs: None')
        self.assertEqual(meeting['attendance'], 'unconfirmed')
        self.assertEqual(meeting['summary_source'], 'fallback')

    def test_different_commit_groups_keep_separate_jobs_even_with_identical_text(self):
        activities = [commit('10:00', 'a'), commit('10:30', 'b')]
        for c in activities:
            c['message'] = 'Fix CSV import'
        blocks = build_time_blocks(model(activities))
        payload = prepare_activity_input(blocks, [])
        request, mapping = build_summary_request(payload['blocks'])
        self.assertEqual(len(request['texts']), 1)
        self.assertEqual(len(request['jobs']), 2)
        self.assertNotEqual(payload['blocks'][0]['summary_group_id'], payload['blocks'][1]['summary_group_id'])
        self.assertEqual([len(v) for v in mapping.values()], [1, 1])

    def test_under_20_merge_group_keeps_own_description_across_lunch(self):
        activity = model([commit('11:50', 'a'), commit('13:39', 'b'), commit('14:09', 'c')],
                         prs=[{**pr('13:35', 101), 'title': 'Add CSV tests'}], start='11:00')
        blocks = build_time_blocks(activity)
        payload = prepare_activity_input(blocks, [])
        request, mapping = build_summary_request(payload['blocks'])
        self.assertEqual(len(request['jobs']), 2)
        self.assertEqual([len(v) for v in mapping.values()], [2, 1])
        self.assertEqual([request['texts'][t] for t in request['jobs'][0]['commits']], ['work a', 'work b'])
        self.assertEqual([b['duration_minutes'] for b in blocks], [60, 9, 30])

    def test_fallback_and_partial_ai_share_topic_and_conflicting_ai_is_rejected(self):
        _, blocks, payload = self.split_group()
        groups = commit_group_mapping(payload['blocks'])
        entries = build_entries(blocks, summary_groups=groups)
        self.assertEqual(len({e['entry']['description'].split(' PRs:')[0] for e in entries}), 1)
        key = payload['blocks'][0]['block_id']
        entries = build_entries(blocks, [{'block_id': key, 'description': 'Sửa CSV'}], summary_groups=groups)
        self.assertEqual([e['summary_source'] for e in entries], ['ai', 'ai'])
        self.assertEqual(len({e['entry']['description'].split(' PRs:')[0] for e in entries}), 1)
        conflicts = [{'block_id': b['block_id'], 'description': f'Different task {i}'}
                     for i, b in enumerate(payload['blocks'])]
        with self.assertRaises(AIJudgmentError): build_entries(blocks, conflicts, summary_groups=groups)

    def test_old_v2_payload_keeps_separate_jobs_and_snapshot_readable(self):
        activity, blocks, _ = self.split_group()
        old = prepare_activity_input(blocks, [], payload_version=2)
        self.assertEqual(len(old['summary_request']['jobs']), 2)
        self.assertTrue(all('summary_group_id' not in b for b in old['blocks']))
        save_snapshot(self.snapshot, activity, self.collection, blocks, [], old)
        self.assertEqual(read_snapshot(self.snapshot)['ai_input'], old)

    def test_grouped_runner_pipeline_usage_and_idempotent_assembly(self):
        self.normalized, self.blocks, self.ai = self.split_group()
        self.normalized['calendar_context'] = []
        self.review = []
        result = self.run_fake()
        self.assertEqual(result['eligible_blocks'], 2)
        self.assertEqual(result['summary_jobs'], 1)
        output = json.loads(Path(result['ai_output']).read_text())
        self.assertEqual(len({v['description'] for v in output}), 1)
        command = [sys.executable, str(ROOT / 'scripts/run_pipeline.py'), '--phase', 'assemble',
                   '--snapshot', str(self.snapshot), '--ai-output', result['ai_output'],
                   '--usage-run-manifest', result['usage_run_manifest'],
                   '--token-csv-path', str(self.directory / 'tokens.csv'), '--output-dir', str(self.output)]
        process = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = json.loads((self.output / '2026-10-07.json').read_text())
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['entry']['description'] for r in rows],
                         ['Update features. PRs: None', 'Update features. PRs: #101'])
        files = [*self.output.glob('*'), self.directory / 'tokens.csv']
        original = {p: p.read_bytes() for p in files if p.is_file()}
        process = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual({p: p.read_bytes() for p in original}, original)
        output[-1]['description'] = 'Unrelated second task'
        Path(result['ai_output']).write_text(json.dumps(output))
        process = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(process.returncode, 2)
        self.assertEqual({p: p.read_bytes() for p in original}, original)

    def test_standalone_builder_uses_shared_fallback_for_plain_blocks(self):
        _, blocks, payload = self.split_group()
        path = self.directory / 'blocks.json'
        path.write_text(json.dumps(blocks))
        process = subprocess.run([sys.executable, str(ROOT / 'scripts/build_timesheet.py'),
                                  '--blocks-file', str(path)], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        rows = json.loads(process.stdout)
        self.assertEqual(len({r['entry']['description'].split(' PRs:')[0] for r in rows}), 1)
        self.assertEqual([len(r['sources']['pull_requests']) for r in rows], [0, 1])

    def test_different_pr_calendar_or_attendance_keeps_separate_job(self):
        base = self.block('09:00', '10:00')
        variants = [self.block('10:00', '11:00', prs=[{'id': 1, 'title': 'Add tests'}]),
                    self.block('11:00', '12:00', calendar=['Team sync']),
                    {**self.block('13:30', '14:00'), 'calendar_overlap': True}]
        request, _ = build_summary_request(prepare_activity_input([base, *variants], [])['blocks'])
        self.assertEqual(len(request['jobs']), 4)
        self.assertEqual(list(request['texts'].values()).count('Fix CSV import'), 1)

    def test_same_text_in_commit_and_pr_retains_roles(self):
        blocks = [self.block('09:00', '10:00', prs=[{'id': 1, 'title': 'Fix CSV import'}]),
                  self.block('10:00', '11:00')]
        request, _ = build_summary_request(prepare_activity_input(blocks, [])['blocks'])
        self.assertEqual(len(request['texts']), 1)
        self.assertEqual(len(request['jobs']), 2)
        self.assertEqual(request['jobs'][0]['commits'], request['jobs'][0]['prs'])

    def test_pr_numbers_and_times_stay_in_audit_not_model_request(self):
        blocks = [self.block('09:00', '10:00', prs=[{'id': 123, 'title': 'Add tests', 'repository': 'owner/repo'}]),
                  self.block('10:00', '11:00', prs=[{'id': 456, 'title': 'Add tests', 'repository': 'other/repo'}])]
        payload = prepare_activity_input(blocks, [])
        text = serialize_request(payload['summary_request'])
        for value in ('09:00', '2026-10-07', 'owner/repo', '123', '456', 'block_id', 'unassigned_activity'):
            self.assertNotIn(value, text)
        self.assertEqual(len(payload['summary_request']['jobs']), 1)
        self.assertEqual(payload['blocks'][0]['prs'][0]['id'], 123)

    def test_missing_duplicate_unknown_or_empty_job_output_rejected(self):
        request, mapping = build_summary_request(prepare_activity_input([self.block('09:00', '10:00')], [])['blocks'])
        good = {'id': 'j1', 'description': 'Sửa CSV'}
        for value in ([], [good, good], [{**good, 'id': 'j9'}], [{**good, 'description': ''}],
                      [{**good, 'block_id': 'unexpected'}], None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                expand_judgments(request, mapping, value)

    def test_byte_guard_bounds_exact_unicode_request_without_evidence_drop(self):
        blocks = [self.block('09:00', '10:00', message='Sửa lỗi dữ liệu')]
        payload = prepare_activity_input(blocks, [])
        size = len(serialize_request(payload['summary_request']).encode('utf-8'))
        self.assertEqual(size, payload['payload_measurement']['model_payload_bytes'])
        self.assertEqual(prepare_activity_input(blocks, [], size)['blocks'], payload['blocks'])
        with self.assertRaises(ValueError): prepare_activity_input(blocks, [], size-1)

    def test_legacy_snapshot_remains_readable_and_new_request_tampering_rejected(self):
        legacy = prepare_activity_input(self.blocks, self.review, payload_version=1)
        save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, legacy)
        self.assertEqual(read_snapshot(self.snapshot)['ai_input'], legacy)
        new_path = self.directory / 'new.json'
        frozen = save_snapshot(new_path, self.normalized, self.collection, self.blocks, self.review, self.ai)
        frozen['ai_input']['summary_request']['texts']['t1'] = 'unrelated'
        frozen['fingerprint'] = fingerprint({k: v for k, v in frozen.items() if k != 'fingerprint'})
        new_path.write_text(json.dumps(frozen))
        with self.assertRaises(SnapshotError): read_snapshot(new_path)

    def fake_process(self, command, **kwargs):
        if command[-1] == '--version':
            return subprocess.CompletedProcess(command, 0, stdout='codex-cli synthetic\n')
        directory = Path(command[command.index('--output-last-message') + 1]).parent
        request = json.loads((directory / 'request.json').read_text())
        if 'jobs' in request:
            judgments = [{'id': j['id'], 'description': 'Update features'} for j in request['jobs']]
        else:
            judgments = [{'block_id': b['block_id'], 'description': 'Update features'} for b in request['blocks']]
        (directory / 'response.json').write_text(json.dumps({'judgments': judgments}))
        events = [{'type': 'thread.started', 'thread_id': 'synthetic-' + directory.name}, {'type': 'turn.started'},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 150, 'cached_input_tokens': 10, 'output_tokens': 15}}]
        kwargs['stdout'].write('\n'.join(json.dumps(v) for v in events))
        self.command, self.process_kwargs = command, kwargs
        return subprocess.CompletedProcess(command, 0)

    def run_fake(self, strategy='compact'):
        save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, self.ai)
        with patch('run_codex_summary.subprocess.run', side_effect=self.fake_process):
            result = run_summary(self.snapshot, self.directory / strategy, model='test-model', strategy=strategy)
        return result

    def test_runner_compact_output_is_attributed_with_request_evidence(self):
        result = self.run_fake()
        record = collect_run(result['usage_run_manifest'], ZoneInfo('Asia/Ho_Chi_Minh'))
        self.assertEqual(record['total_tokens'], 165)
        self.assertEqual(json.loads(record['notes'])['model_requested'], 'test-model')
        instructions = (self.directory / 'compact' / 'instructions.txt').read_text()
        self.assertIn('English timesheet descriptions', instructions)
        self.assertIn('Translate non-English evidence', instructions)
        self.assertEqual(json.loads(Path(result['ai_output']).read_text())[0]['description'], 'Update features')
        self.assertIn('shell_tool', self.command)
        self.assertIn('features.skip_host_skill_discovery=true', self.command)
        self.assertEqual(self.process_kwargs['cwd'], (self.directory / 'compact').resolve())
        manifest = json.loads(Path(result['usage_run_manifest']).read_text())
        raw_path = self.directory / 'compact' / 'response.json'
        raw = json.loads(raw_path.read_text()); raw['judgments'][0]['description'] = 'Different text'
        raw_path.write_text(json.dumps(raw)); manifest['response_file_sha256'] = sha256(raw_path)
        Path(result['usage_run_manifest']).write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): collect_run(result['usage_run_manifest'], ZoneInfo('Asia/Ho_Chi_Minh'))

    def test_rehashed_request_cannot_claim_different_frozen_input(self):
        result = self.run_fake()
        manifest_path = Path(result['usage_run_manifest']); manifest = json.loads(manifest_path.read_text())
        request_path = self.directory / 'compact' / 'request.json'
        request = json.loads(request_path.read_text()); request['texts']['t1'] = 'Invented task'
        request_path.write_text(serialize_request(request))
        manifest.update(request_file_sha256=sha256(request_path), request_fingerprint=fingerprint(request))
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError): collect_run(manifest_path, ZoneInfo('Asia/Ho_Chi_Minh'))

    def test_legacy_benchmark_output_also_has_valid_attribution(self):
        result = self.run_fake('legacy')
        self.assertEqual(collect_run(result['usage_run_manifest'], ZoneInfo('Asia/Ho_Chi_Minh'))['total_tokens'], 165)
        self.assertNotIn('--strict-config', self.command)
        self.assertIn('timesheet blocks in English', self.process_kwargs['input'])
        self.assertIn('translating non-English evidence', self.process_kwargs['input'])

    def test_benchmark_resume_verifies_evidence_without_new_ai_or_duplicate_usage(self):
        save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, self.ai)
        directory = self.directory / 'benchmark'
        with patch('run_codex_summary.subprocess.run', side_effect=self.fake_process) as process:
            first = benchmark(self.snapshot, directory, model='test-model')
            self.assertEqual(process.call_count, 4)  # version + invocation per strategy
        original_csv = (directory / 'token-usage.csv').read_bytes()
        with patch('run_codex_summary.subprocess.run', side_effect=AssertionError('must reuse')):
            resumed = benchmark(self.snapshot, directory, model='test-model', resume=True)
        self.assertEqual(first, resumed)
        self.assertEqual((directory / 'token-usage.csv').read_bytes(), original_csv)
        with self.assertRaises(ValueError):
            benchmark(self.snapshot, directory, model='different-model', resume=True)

    def invalid_process(self, command, **kwargs):
        result = self.fake_process(command, **kwargs)
        if command[-1] != '--version':
            directory = Path(command[command.index('--output-last-message') + 1]).parent
            if directory.name == 'compact':
                response = json.loads((directory / 'response.json').read_text())
                response['judgments'][0]['description'] = 'Invalid PRs: #42'
                (directory / 'response.json').write_text(json.dumps(response))
        return result

    def test_invalid_summary_preserves_measured_cost_and_blocks_assembly_receipt(self):
        save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, self.ai)
        directory = self.directory / 'compact'
        with patch('run_codex_summary.subprocess.run', side_effect=self.invalid_process), self.assertRaises(ValueError):
            run_summary(self.snapshot, directory, model='test-model')
        path = directory / 'usage-attempt.json'
        receipt = json.loads(path.read_text())
        self.assertEqual(receipt['summary_status'], 'summary_invalid')
        self.assertFalse((directory / 'usage-run.json').exists())
        record = collect_run(path, ZoneInfo('Asia/Ho_Chi_Minh'))
        self.assertEqual(record['total_tokens'], 165)
        self.assertEqual(len((directory / 'attempt-token-usage.csv').read_text().splitlines()), 2)
        with self.assertRaises(ValueError):
            collect_run(path, ZoneInfo('Asia/Ho_Chi_Minh'), expected_ai_output=directory / 'ai-output.json')
        receipt['provider_usage']['input_tokens'] += 1
        path.write_text(json.dumps(receipt))
        with self.assertRaises(ValueError): collect_run(path, ZoneInfo('Asia/Ho_Chi_Minh'))

    def test_benchmark_retry_includes_rejected_summary_cost_without_double_counting(self):
        save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, self.ai)
        directory = self.directory / 'benchmark'
        with patch('run_codex_summary.subprocess.run', side_effect=self.invalid_process), self.assertRaises(ValueError):
            benchmark(self.snapshot, directory, model='test-model')
        ledger = json.loads((directory / 'attempts.json').read_text())
        self.assertEqual(ledger['total_known_tokens'], 330)
        self.assertEqual(ledger['attempts'][0]['summary_status'], 'summary_invalid')
        with patch('run_codex_summary.subprocess.run', side_effect=self.fake_process) as process:
            report = benchmark(self.snapshot, directory, model='test-model', resume=True)
            self.assertEqual(process.call_count, 2)
        self.assertEqual(report['attempt_usage']['total_known_tokens'], 495)
        self.assertEqual(report['attempt_usage']['strategies']['compact']['known_tokens'], 330)
        self.assertEqual(report['results']['compact']['total_tokens'], 165)
        csv = (directory / 'token-usage.csv').read_bytes()
        self.assertEqual(len(csv.decode().splitlines()), 4)
        with patch('run_codex_summary.subprocess.run', side_effect=AssertionError('must reuse')):
            self.assertEqual(benchmark(self.snapshot, directory, model='test-model', resume=True), report)
        self.assertEqual((directory / 'token-usage.csv').read_bytes(), csv)

    def test_unknown_attempt_is_not_reported_as_zero(self):
        save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, self.ai)
        directory = self.directory / 'benchmark'
        def missing_usage(command, **kwargs):
            result = self.fake_process(command, **kwargs)
            if command[-1] != '--version':
                path = Path(command[command.index('--output-last-message') + 1]).parent
                if path.name == 'compact':
                    kwargs['stdout'].seek(0); kwargs['stdout'].truncate()
                    kwargs['stdout'].write(json.dumps({'type': 'thread.started', 'thread_id': 'unknown'}))
            return result
        with patch('run_codex_summary.subprocess.run', side_effect=missing_usage), self.assertRaises(ValueError):
            benchmark(self.snapshot, directory, model='test-model')
        ledger = json.loads((directory / 'attempts.json').read_text())
        self.assertFalse(ledger['all_attempts_measured'])
        self.assertEqual(ledger['strategies']['compact']['unknown_attempts'], 1)
        self.assertIsNone(ledger['attempts'][0]['total_tokens'])
        with self.assertRaises(ValueError):
            collect_run(directory / 'compact/usage-attempt.json', ZoneInfo('Asia/Ho_Chi_Minh'))

    def test_nonzero_process_with_completed_usage_still_records_attempt(self):
        save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, self.ai)
        def failure(command, **kwargs):
            result = self.fake_process(command, **kwargs)
            return result if command[-1] == '--version' else subprocess.CompletedProcess(command, 1)
        directory = self.directory / 'process-failure'
        with patch('run_codex_summary.subprocess.run', side_effect=failure), self.assertRaises(ValueError):
            run_summary(self.snapshot, directory, model='test-model')
        path = directory / 'usage-attempt.json'
        self.assertEqual(json.loads(path.read_text())['summary_status'], 'process_failed')
        self.assertEqual(collect_run(path, ZoneInfo('Asia/Ho_Chi_Minh'))['total_tokens'], 165)

    def test_success_and_attempt_receipts_upsert_same_invocation(self):
        from collect_token_usage import update_csv
        result = self.run_fake()
        output = self.directory / 'all-tokens.csv'
        for key in ('usage_run_manifest', 'usage_attempt_manifest'):
            record = collect_run(result[key], ZoneInfo('Asia/Ho_Chi_Minh'))
            update_csv(output, [record])
        import csv
        with output.open() as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]['total_tokens']), 165)


if __name__ == '__main__': unittest.main()
