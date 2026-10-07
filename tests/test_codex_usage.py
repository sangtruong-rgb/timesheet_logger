"""Synthetic Codex events for validation; live CLI proof is recorded separately."""
import copy
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from codex_usage import completed_usage, sha256
from collect_token_usage import collect_run, update_csv, daily_totals
from activity_snapshot import fingerprint
from run_codex_summary import run_summary
import test_remaining_storage as fixture


class TestCodexUsage(unittest.TestCase):
    def setUp(self):
        fixture.TestRemainingStorage.setUp(self)
        self.frozen = fixture.TestRemainingStorage.freeze(self)
        self.events = self.directory / 'events.jsonl'
        self.judgments = self.directory / 'ai-output.json'
        self.judgments.write_text(json.dumps([{'block_id': b['block_id'], 'description': 'Validated activity'}
                                             for b in self.frozen['ai_input']['blocks']]))
        self.stream = [{'type': 'thread.started', 'thread_id': 'thread-a'}, {'type': 'turn.started'},
                       {'type': 'item.completed', 'item': {'type': 'agent_message'}},
                       {'type': 'turn.completed', 'usage': {'input_tokens': 100, 'cached_input_tokens': 80,
                                                         'output_tokens': 20, 'reasoning_output_tokens': 5}}]
        self.manifest = self.directory / 'usage.json'
        self.metadata = {'provider': 'codex', 'schema': 'codex_exec_run_v1',
                         'run_id': self.frozen['run_id'], 'target_date': self.frozen['normalized']['date'],
                         'started_at': '2026-10-07T09:00:00+07:00', 'ended_at': '2026-10-07T09:10:00+07:00',
                         'process_exit_code': 0, 'session_id': 'thread-a',
                         'session_file': self.events.name, 'snapshot_file': self.snapshot.name,
                         'ai_output_file': self.judgments.name,
                         'ai_input_fingerprint': fingerprint(self.frozen['ai_input'])}
        self.write()

    def write(self):
        self.events.write_text('\n'.join(json.dumps(v) for v in self.stream) + '\n')
        for k, path in (('session_file', self.events), ('snapshot_file', self.snapshot), ('ai_output_file', self.judgments)):
            self.metadata[k + '_sha256'] = sha256(path)
        self.manifest.write_text(json.dumps(self.metadata))

    def collect(self, **kwargs):
        return collect_run(self.manifest, ZoneInfo('Asia/Ho_Chi_Minh'), **kwargs)

    def test_cache_and_reasoning_not_double_counted(self):
        r = self.collect()
        self.assertEqual([r[k] for k in ('input_tokens', 'output_tokens', 'cache_tokens', 'total_tokens')], [20, 20, 80, 120])
        self.assertEqual(json.loads(r['notes'])['provider_usage']['input_tokens'], 100)
        self.assertEqual(r['date'], '2026-10-07')
        self.assertNotEqual(r['date'], self.metadata['target_date'])

    def test_csv_idempotency_and_provenance(self):
        path = self.directory / 'tokens.csv'; r = self.collect()
        update_csv(path, [r]); before = path.read_bytes(); update_csv(path, [r])
        self.assertEqual(path.read_bytes(), before)
        totals = daily_totals(path, r['date'])['by_provenance']
        self.assertEqual(totals['codex_exec']['total_tokens'], 120)
        self.assertEqual(totals['transcript']['total_tokens'], 0)

    def test_required_counts_missing_block(self):
        for k in ('input_tokens', 'cached_input_tokens', 'output_tokens'):
            with self.subTest(k=k):
                old = self.stream[-1]['usage'].pop(k); self.write()
                with self.assertRaises(ValueError): self.collect()
                self.stream[-1]['usage'][k] = old

    def test_invalid_count_types_block(self):
        for value in (None, True, -1, 1.5, '-2'):
            self.stream[-1]['usage']['input_tokens'] = value; self.write()
            with self.subTest(value=value), self.assertRaises(ValueError): self.collect()

    def test_zero_counts_explicitly_valid(self):
        self.stream[-1]['usage'] = dict(input_tokens=0, cached_input_tokens=0, output_tokens=0)
        self.write(); self.assertEqual(self.collect()['total_tokens'], 0)

    def test_cache_and_reasoning_bounds(self):
        for key in ('cached_input_tokens', 'reasoning_output_tokens'):
            old = self.stream[-1]['usage'][key]; self.stream[-1]['usage'][key] = 101; self.write()
            with self.assertRaises(ValueError): self.collect()
            self.stream[-1]['usage'][key] = old

    def test_failure_after_complete_still_blocks(self):
        self.stream.append({'type': 'error', 'message': 'synthetic'}); self.write()
        with self.assertRaises(ValueError): self.collect()

    def test_truncated_turn_failed_and_duplicate_completion(self):
        original = copy.deepcopy(self.stream)
        for stream in (original[:-1], original + [original[-1]], original[:-1] + [{'type': 'turn.failed'}]):
            self.stream = stream; self.write()
            with self.assertRaises(ValueError): self.collect()

    def test_second_thread_or_turn_rejected(self):
        original = copy.deepcopy(self.stream)
        for event in (original[0], original[1]):
            self.stream = original + [event]; self.write()
            with self.assertRaises(ValueError): self.collect()

    def test_wrong_identity_target_run_provider_schema_and_exit(self):
        for key, value in (('session_id', 'other'), ('run_id', 'other'), ('target_date', '2020-01-01'),
                           ('provider', 'unknown'), ('schema', 'wrong'), ('process_exit_code', 1), ('process_exit_code', False)):
            old = self.metadata[key]; self.metadata[key] = value; self.write()
            with self.subTest(key=key), self.assertRaises(ValueError): self.collect()
            self.metadata[key] = old
        self.write()
        for kwargs in ({'expected_run': 'other'}, {'expected_target': '2020-01-01'}, {'expected_ai_output': self.directory / 'other.json'}):
            with self.assertRaises(ValueError): self.collect(**kwargs)

    def test_missing_boundaries_and_invalid_window(self):
        for key, value in (('started_at', '2026-10-07T09:00:00'), ('ended_at', self.metadata['started_at'])):
            old = self.metadata[key]; self.metadata[key] = value; self.write()
            with self.assertRaises(ValueError): self.collect()
            self.metadata[key] = old

    def test_changed_evidence_digests_block(self):
        for path in (self.snapshot, self.events, self.judgments):
            original = path.read_bytes(); path.write_bytes(original + b' ')
            with self.subTest(path=path.name), self.assertRaises(ValueError): self.collect()
            path.write_bytes(original)

    def test_payload_fingerprint_mismatch(self):
        self.metadata['ai_input_fingerprint'] = 'wrong'; self.write()
        with self.assertRaises(ValueError): self.collect()

    def test_output_missing_duplicate_stale_and_pr_suffix_block(self):
        original = json.loads(self.judgments.read_text())
        for value in ([], original + original, [{'block_id': 'stale', 'description': 'Text'}],
                      [{**original[0], 'description': 'Text PRs: None'}]):
            self.judgments.write_text(json.dumps(value)); self.write()
            with self.assertRaises(ValueError): self.collect()

    def test_malformed_log_blocks(self):
        self.events.write_text('not json\n')
        with self.assertRaises(ValueError): completed_usage(self.events)

    def test_cli_uses_real_csv_environment_and_preserves_on_bad_evidence(self):
        csv_path = self.directory / 'actual-env.csv'
        env = {**os.environ, 'TIMESHEET_TOKEN_CSV': str(csv_path)}
        command = [sys.executable, str(ROOT / 'scripts/collect_token_usage.py'), '--run-manifest', str(self.manifest)]
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        before = csv_path.read_bytes()
        self.events.write_text('broken')
        result = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2); self.assertEqual(csv_path.read_bytes(), before)

    def test_pipeline_attributed_and_rerun_preserves_files(self):
        csv_path = self.directory / 'actual-env.csv'
        env = {**os.environ, 'TIMESHEET_TOKEN_CSV': str(csv_path)}
        command = [sys.executable, str(ROOT / 'scripts/run_pipeline.py'), '--phase', 'assemble',
                   '--snapshot', str(self.snapshot), '--ai-output', str(self.judgments),
                   '--usage-run-manifest', str(self.manifest), '--output-dir', str(self.output)]
        def run(): return subprocess.run(command, env=env, capture_output=True, text=True)
        result = run(); self.assertEqual(result.returncode, 0, result.stderr)
        collection = json.loads((self.output / (self.metadata['target_date'] + '.collection.json')).read_text())
        self.assertEqual(collection['token_usage']['total_tokens'], 120)
        before = {p: p.read_bytes() for p in [*self.output.glob('*'), csv_path] if p.is_file()}
        self.assertEqual(run().returncode, 0)
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        self.events.write_text('broken'); self.assertEqual(run().returncode, 2)
        self.assertEqual({p: p.read_bytes() for p in before}, before)

    def test_runner_existing_directory_refused_without_process(self):
        self.directory.joinpath('prior.txt').write_text('preserved')
        with self.assertRaises(FileExistsError): run_summary(self.snapshot, self.directory, codex='/nonexistent')
        self.assertEqual(self.directory.joinpath('prior.txt').read_text(), 'preserved')

    def test_runner_failed_launch_leaves_no_success_manifest(self):
        output = self.directory / 'codex'
        with self.assertRaises(ValueError): run_summary(self.snapshot, output, codex='/nonexistent')
        self.assertTrue((output / 'failed-run.json').exists())
        self.assertFalse((output / 'usage-run.json').exists())

    def test_completion_before_start_and_unexpected_usage_event(self):
        original = copy.deepcopy(self.stream)
        for stream in ([original[-1]], [original[1], original[0], original[-1]],
                       original + [{'type': 'unknown', 'usage': {}}]):
            self.stream = stream; self.write()
            with self.assertRaises(ValueError): self.collect()

    def test_missing_manifest_digest_identity_and_path(self):
        for key in ('session_file_sha256', 'session_id', 'snapshot_file', 'ai_output_file'):
            value = self.metadata.pop(key)
            self.manifest.write_text(json.dumps(self.metadata))
            with self.subTest(key=key), self.assertRaises(ValueError): self.collect()
            self.metadata[key] = value

    def test_pipeline_rejects_usage_without_output_and_protects_renamed_evidence(self):
        # A renamed output path is still protected through the manifest.
        other = self.directory / 'renamed.json'; other.write_bytes(self.judgments.read_bytes())
        self.metadata['ai_output_file'] = other.name
        self.manifest.write_text(json.dumps(self.metadata))
        before = other.read_bytes()
        command = [sys.executable, str(ROOT / 'scripts/run_pipeline.py'), '--phase', 'assemble',
                   '--snapshot', str(self.snapshot), '--usage-run-manifest', str(self.manifest),
                   '--output-dir', str(self.output), '--token-csv-path', str(self.directory / 'tokens.csv')]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        result = subprocess.run(command + ['--ai-output', str(self.judgments), '--export-ai-input', str(other)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(other.read_bytes(), before); self.assertFalse(self.output.exists())


if __name__ == '__main__': unittest.main()
