"""Frozen evidence, bounded AI input and recoverable storage (synthetic sources)."""
import base64
import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from activity_snapshot import read_snapshot, save_snapshot, SnapshotError, fingerprint
from atomic_storage import directory_lock, write_bundle, atomic_write, StorageError
from build_time_blocks import build_time_blocks
from build_timesheet import build_entries
from block_identity import BlockIdentityError
from normalize_activity import normalize_all
from prepare_ai_input import prepare_activity_input
from run_pipeline import run
from save_timesheet import save_timesheet, TimesheetReconciliationError
from test_evidence_backed_blocks import DATE, event, commit


class TestRemainingStorage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.snapshot = self.directory / 'snapshot.json'
        self.output = self.directory / 'timesheets'
        self.normalized = normalize_all(DATE, [commit()], [], [event()])
        self.review = []
        self.blocks = build_time_blocks(self.normalized, unassigned_activity=self.review)
        self.ai = prepare_activity_input(self.blocks, self.review)
        self.collection = {'status': 'complete', 'sources': {}}

    def freeze(self):
        return save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, self.ai)

    def invoke(self, arguments):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['run_pipeline.py', *arguments]), contextlib.redirect_stdout(self.stdout), contextlib.redirect_stderr(self.stderr):
            return run()

    def test_prepare_writes_snapshot_and_ai_only(self):
        config = self.directory / 'profile.json'
        config.write_text(json.dumps({'repositories': ['test/project']}))
        def collect(command, source, mode):
            items = [commit()] if source == 'git' else [event()] if source == 'google_calendar' else []
            return {'source': source, 'mode': mode, 'status': 'success', 'items': items}
        with patch('run_pipeline.run_source_collector', side_effect=collect):
            result = self.invoke(['--phase', 'prepare', '--date', DATE, '--config', str(config), '--snapshot', str(self.snapshot), '--output-dir', str(self.output), '--export-ai-input', str(self.directory/'ai.json')])
        self.assertEqual(result, 0, self.stderr.getvalue())
        read_snapshot(self.snapshot)
        self.assertFalse(self.output.exists())
        self.assertEqual(json.loads((self.directory/'ai.json').read_text()), self.ai)

    def test_assemble_never_recollects_and_ignores_changed_source_config(self):
        saved = self.freeze()
        with patch('run_pipeline.run_source_collector', side_effect=AssertionError('must not collect')):
            result = self.invoke(['--phase', 'assemble', '--snapshot', str(self.snapshot), '--config', '/missing/config', '--output-dir', str(self.output)])
        self.assertEqual(result, 0, self.stderr.getvalue())
        rows = json.loads((self.output/f'{DATE}.json').read_text())
        self.assertEqual([c['hash'] for r in rows for c in r['sources']['commits']], ['test-commit'])
        self.assertEqual(read_snapshot(self.snapshot)['run_id'], saved['run_id'])

    def test_snapshot_rerun_preserves_bytes_and_rejects_changed_evidence(self):
        self.freeze(); before = self.snapshot.read_bytes()
        self.freeze(); self.assertEqual(before, self.snapshot.read_bytes())
        altered = copy.deepcopy(self.normalized); altered['commits'][0]['message'] = 'changed'
        with self.assertRaises(SnapshotError):
            save_snapshot(self.snapshot, altered, self.collection, self.blocks, self.review, self.ai)
        self.assertEqual(before, self.snapshot.read_bytes())

    def test_assemble_rejects_date_mismatch_before_final_write(self):
        self.freeze()
        self.assertEqual(self.invoke(['--phase', 'assemble', '--snapshot', str(self.snapshot), '--date', '2026-10-07', '--output-dir', str(self.output)]), 2)
        self.assertFalse(self.output.exists())

    def test_digest_and_rebuilt_evidence_both_validated(self):
        original = self.freeze()
        for refresh_digest in (False, True):
            altered = copy.deepcopy(original); altered['blocks'][0]['calendar_titles'] = ['invented']
            if refresh_digest:
                altered['fingerprint'] = fingerprint({k:v for k,v in altered.items() if k != 'fingerprint'})
            self.snapshot.write_text(json.dumps(altered))
            with self.assertRaises(SnapshotError): read_snapshot(self.snapshot)

    def test_nested_corrupt_snapshot_is_controlled(self):
        altered = self.freeze(); altered['normalized'] = None
        altered['fingerprint'] = fingerprint({k:v for k,v in altered.items() if k != 'fingerprint'})
        self.snapshot.write_text(json.dumps(altered))
        with self.assertRaises(SnapshotError): read_snapshot(self.snapshot)

    def test_snapshot_export_cannot_replace_snapshot(self):
        with self.assertRaises(SnapshotError):
            save_snapshot(self.snapshot, self.normalized, self.collection, self.blocks, self.review, self.ai, self.snapshot)
        self.assertFalse(self.snapshot.exists())

    def test_exact_byte_budget_unicode_and_calendar_only_omission(self):
        blocks = copy.deepcopy(self.blocks); blocks[-1]['commits'][0]['message'] = 'Sửa lỗi dữ liệu'
        payload = prepare_activity_input(blocks, self.review)
        size = len(json.dumps(payload, indent=2).encode('utf-8'))
        self.assertEqual(payload['payload_measurement']['serialized_bytes'], size)
        self.assertEqual(len(payload['blocks']), 1)
        model_size = payload['payload_measurement']['model_payload_bytes']
        with self.assertRaises(BlockIdentityError): prepare_activity_input(blocks, self.review, model_size-1)
        self.assertFalse(payload['payload_measurement']['token_count_is_exact'])

    def test_ai_cannot_duplicate_or_scatter_pr_references(self):
        key = self.ai['blocks'][0]['block_id']
        for summary in ('Completed. PRs: #1', 'Reviewed #12', 'PRs : None'):
            with self.subTest(summary=summary), self.assertRaises(BlockIdentityError):
                build_entries(self.blocks, [{'block_id': key, 'description': summary}])
        blocks = copy.deepcopy(self.blocks); blocks[-1]['commits'][0]['message'] = 'Merge #12. PRs: #12'
        row = build_entries(blocks)[-1]
        self.assertEqual(row['entry']['description'].count('PRs:'), 1)
        self.assertNotIn('#12', row['entry']['description'])
        self.assertIn('#12', row['sources']['commits'][0]['message'])

    def test_inconsistent_duration_reversed_and_bad_sources_rejected(self):
        for changes in ({'duration_minutes': 999}, {'end_time': '08:00'}, {'commits': {}}, {'duration_minutes': True}):
            with self.subTest(changes=changes), self.assertRaises(BlockIdentityError):
                build_entries([{**self.blocks[0], **changes}])

    def test_dst_elapsed_duration_survives_save(self):
        normalized = normalize_all('2026-03-08', [], [], [{'title': 'DST', 'start': '2026-03-08T00:00:00-05:00', 'end': '2026-03-09T00:00:00-04:00'}], 'America/New_York')
        rows = build_entries(build_time_blocks(normalized))
        self.assertEqual(rows[0]['entry']['duration_minutes'], 1380)
        save_timesheet(rows, self.output, target_date='2026-03-08', collection_status='complete')

    def test_bundle_failure_restores_all_files(self):
        first, second = self.directory/'first', self.directory/'second'
        first.write_text('old first'); second.write_text('old second')
        failed = False
        def fault(path, value):
            nonlocal failed
            if Path(path) == second and not failed:
                failed = True; raise OSError('synthetic disk error')
            return atomic_write(path, value)
        with directory_lock(self.directory), patch('atomic_storage.atomic_write', side_effect=fault):
            with self.assertRaises(StorageError): write_bundle({first:'new first', second:'new second'}, self.directory)
        self.assertEqual(first.read_text(), 'old first'); self.assertEqual(second.read_text(), 'old second')
        self.assertFalse((self.directory/'.timesheet-transaction.json').exists())

    def test_interrupted_bundle_is_recovered_before_next_read(self):
        target = self.directory/'old.json'; target.write_text('partial write')
        journal = self.directory/'.timesheet-transaction.json'
        journal.write_text(json.dumps({'version':1, 'files':[{'path':str(target), 'previous':base64.b64encode(b'original').decode()}]}))
        with directory_lock(self.directory): self.assertEqual(target.read_text(), 'original')
        self.assertFalse(journal.exists())

    def test_corrupt_journal_blocks_writer_and_preserves_files(self):
        journal = self.directory/'.timesheet-transaction.json'; journal.write_text('{}')
        with self.assertRaises(StorageError):
            with directory_lock(self.directory): self.fail('must not enter')
        self.assertEqual(journal.read_text(), '{}')

    def test_second_writer_cannot_enter_locked_directory(self):
        with directory_lock(self.directory):
            with self.assertRaises(StorageError):
                with directory_lock(self.directory, timeout=0): self.fail('unlocked')

    def test_bad_existing_source_array_blocks_and_preserves_store(self):
        rows = build_entries(self.blocks)
        save_timesheet(rows, self.output, target_date=DATE, collection_status='complete')
        path = self.output/f'{DATE}.json'; bad=json.loads(path.read_text()); bad[0]['sources']['commits'] = None
        path.write_text(json.dumps(bad)); before = path.read_bytes()
        with self.assertRaises(TimesheetReconciliationError): save_timesheet(rows, self.output, target_date=DATE, collection_status='complete')
        self.assertEqual(path.read_bytes(), before)

    def test_export_cannot_overwrite_final_json(self):
        with self.assertRaises(TimesheetReconciliationError):
            save_timesheet(build_entries(self.blocks), self.output, target_date=DATE, collection_status='complete', extra_files={self.output/f'{DATE}.json':'wrong'})
        self.assertFalse((self.output/f'{DATE}.json').exists())

    def test_suffix_must_match_generated_source_references(self):
        row = build_entries(self.blocks)[0]
        row["entry"]["description"] = "Invalid summary. PRs: #999"
        with self.assertRaises(TimesheetReconciliationError):
            save_timesheet([row], self.output, target_date=DATE, collection_status="complete")
        self.assertFalse((self.output/f"{DATE}.json").exists())


if __name__ == '__main__': unittest.main()
