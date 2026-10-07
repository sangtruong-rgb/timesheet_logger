"""R03 uses real processes and fcntl locks; only disk faults are synthetic."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from atomic_storage import directory_lock, atomic_write, write_bundle, StorageError, PENDING, JOURNAL
from save_timesheet import save_timesheet, TimesheetReconciliationError


class TestStorageConcurrency(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='storage race ')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.shared = self.directory / 'shared' / 'ai-input.json'
        self.shared.parent.mkdir()
        self.shared.write_text('original')
        self.processes = []
        self.addCleanup(self.stop_workers)

    def stop_workers(self):
        for worker in self.processes:
            if worker.poll() is None:
                worker.terminate()
            worker.wait(timeout=5)

    def wait_for(self, path):
        deadline = time.monotonic() + 5
        while not path.exists():
            if time.monotonic() >= deadline:
                self.fail(f'Worker did not create {path.name}')
            time.sleep(0.01)

    def launch(self, name, *, mode='timesheet', fault=None, pause=False):
        config = {'shared': str(self.shared), 'output': str(self.directory / name), 'value': name,
            'mode': mode, 'fault': fault, 'pause': pause, 'ready': str(self.directory / f'{name}.ready'),
            'blocked': str(self.directory / f'{name}.blocked'),
            'release': str(self.directory / f'{name}.release'), 'done': str(self.directory / f'{name}.done')}
        path = self.directory / f'{name}.config.json'; path.write_text(json.dumps(config))
        worker = subprocess.Popen([sys.executable, str(ROOT / 'tests/storage_concurrency_worker.py'), str(path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.processes.append(worker)
        return worker

    def assert_clean_metadata(self):
        self.assertEqual(list(self.directory.rglob(PENDING)), [])
        self.assertEqual(list(self.directory.rglob(JOURNAL)), [])

    def test_failed_writer_cannot_rollback_successful_other_writer(self):
        first = self.launch('writer-a', fault='timesheet_failure', pause=True)
        self.wait_for(self.directory / 'writer-a.ready')
        second = self.launch('writer-b')
        self.wait_for(self.directory / 'writer-b.blocked')
        self.assertIsNone(second.poll(), 'Second writer must wait for shared parent lock')
        self.assertFalse((self.directory / 'writer-b.done').exists())
        (self.directory / 'writer-a.release').write_text('release')
        self.assertEqual(first.wait(timeout=5), 2)
        self.assertEqual(second.wait(timeout=5), 0)
        self.assertEqual(self.shared.read_text(), 'writer-b')
        self.assertTrue((self.directory / 'writer-b' / '2026-10-07.json').exists())
        self.assertFalse((self.directory / 'writer-a' / '2026-10-07.json').exists())
        self.assert_clean_metadata()

    def test_failed_snapshot_writer_also_locks_external_export(self):
        first = self.launch('prepare-a', mode='snapshot', fault='snapshot_failure', pause=True)
        self.wait_for(self.directory / 'prepare-a.ready')
        second = self.launch('writer-b')
        self.wait_for(self.directory / 'writer-b.blocked')
        self.assertIsNone(second.poll())
        (self.directory / 'prepare-a.release').write_text('release')
        self.assertEqual(first.wait(timeout=5), 2)
        self.assertEqual(second.wait(timeout=5), 0)
        self.assertEqual(self.shared.read_text(), 'writer-b')
        self.assertFalse((self.directory / 'prepare-a' / 'activity.json').exists())
        self.assert_clean_metadata()

    def test_crash_blocks_other_bundle_until_owner_recovery(self):
        crashed = self.launch('writer-a', fault='crash', pause=True)
        self.wait_for(self.directory / 'writer-a.ready')
        self.assertEqual(crashed.wait(timeout=5), 73)
        partial = self.shared.read_bytes()
        second = self.launch('writer-b')
        self.assertEqual(second.wait(timeout=5), 2)
        self.assertEqual(self.shared.read_bytes(), partial)
        self.assertFalse((self.directory / 'writer-b' / '2026-10-07.json').exists())
        with directory_lock(self.directory / 'writer-a', extra_paths=[self.shared]):
            self.assertEqual(self.shared.read_text(), 'original')
        self.assert_clean_metadata()
        retry = self.launch('writer-b')
        self.assertEqual(retry.wait(timeout=5), 0)
        self.assertEqual(self.shared.read_text(), 'writer-b')
        self.assert_clean_metadata()

    def test_crash_reservation_blocks_single_file_writer_too(self):
        crashed = self.launch('writer-a', fault='crash', pause=True)
        self.wait_for(self.directory / 'writer-a.ready')
        self.assertEqual(crashed.wait(timeout=5), 73)
        partial = self.shared.read_bytes()
        other = self.launch('single-b', mode='single')
        self.assertEqual(other.wait(timeout=5), 2)
        self.assertEqual(self.shared.read_bytes(), partial)
        with directory_lock(self.directory / 'writer-a', extra_paths=[self.shared]):
            pass
        retry = self.launch('single-b', mode='single')
        self.assertEqual(retry.wait(timeout=5), 0)
        self.assertEqual(self.shared.read_text(), 'single-b')

    def test_recovery_waits_for_every_parent_lock(self):
        crashed = self.launch('writer-a', fault='crash', pause=True)
        self.wait_for(self.directory / 'writer-a.ready')
        self.assertEqual(crashed.wait(timeout=5), 73)
        partial = self.shared.read_bytes()
        from atomic_storage import _directory_lock
        with _directory_lock(self.shared.parent, 0):
            with self.assertRaises(StorageError):
                with directory_lock(self.directory / 'writer-a', extra_paths=[self.shared], timeout=0):
                    self.fail('Recovery ran before shared lock')
            self.assertEqual(self.shared.read_bytes(), partial)
        with directory_lock(self.directory / 'writer-a', extra_paths=[self.shared]):
            pass
        self.assertEqual(self.shared.read_text(), 'original')
        self.assert_clean_metadata()

    def test_lock_order_does_not_depend_on_primary_directory(self):
        left = self.directory / 'a'; right = self.directory / 'z'
        left.mkdir(); right.mkdir()
        with directory_lock(left, extra_paths=[right / 'extra.json']):
            with self.assertRaises(StorageError):
                with directory_lock(right, extra_paths=[left / 'extra.json'], timeout=0):
                    self.fail('Opposite primary bypassed shared lock')

    def test_stale_marker_without_journal_does_not_restore_old_data(self):
        owner = self.directory / 'writer-a' / JOURNAL
        marker = self.shared.parent / PENDING
        marker.write_text(json.dumps({'version': 1, 'journal': str(owner)}))
        with directory_lock(self.shared.parent):
            atomic_write(self.shared, 'new successful data')
        self.assertEqual(self.shared.read_text(), 'new successful data')
        self.assertFalse(marker.exists())

    def test_corrupt_pending_marker_blocks_and_is_preserved(self):
        marker = self.shared.parent / PENDING; marker.write_text('{}')
        with self.assertRaises(TimesheetReconciliationError):
            save_timesheet([], self.directory / 'writer-a', target_date='2026-10-07', collection_status='complete', extra_files={self.shared: 'new'})
        self.assertEqual(self.shared.read_text(), 'original')
        self.assertEqual(marker.read_text(), '{}')

    def test_marker_write_failure_never_changes_original_files(self):
        worker = self.launch('writer-a', fault='marker_failure')
        self.assertEqual(worker.wait(timeout=5), 2)
        self.assertEqual(self.shared.read_text(), 'original')
        self.assertFalse((self.directory / 'writer-a' / '2026-10-07.json').exists())
        self.assert_clean_metadata()

    def test_crash_after_commit_does_not_rollback_later_success(self):
        worker = self.launch('writer-a', fault='after_commit_crash')
        self.assertEqual(worker.wait(timeout=5), 74)
        self.assertFalse((self.directory / 'writer-a' / JOURNAL).exists())
        self.assertTrue((self.shared.parent / PENDING).exists())
        second = self.launch('writer-b')
        self.assertEqual(second.wait(timeout=5), 0)
        with directory_lock(self.directory / 'writer-a', extra_paths=[self.shared]):
            self.assertEqual(self.shared.read_text(), 'writer-b')
        self.assert_clean_metadata()

    def test_bundle_rejects_missing_external_lock_declaration(self):
        with directory_lock(self.directory / 'owner'):
            with self.assertRaises(StorageError):
                write_bundle({self.shared: 'new'}, self.directory / 'owner')
        self.assertEqual(self.shared.read_text(), 'original')
        self.assert_clean_metadata()

    def test_token_csv_writer_waits_for_failed_timesheet_bundle(self):
        if not (ROOT / 'scripts/token_settings.py').exists():
            self.skipTest('Run-scoped token CSV integration belongs to dependent PR #62')
        import csv
        from collect_token_usage import FIELDS
        self.shared = self.directory / 'shared' / 'tokens.csv'
        self.shared.write_text(','.join(FIELDS) + '\n')
        first = self.launch('writer-a', mode='timesheet-token', fault='timesheet_failure', pause=True)
        self.wait_for(self.directory / 'writer-a.ready')
        second = self.launch('csv-b', mode='csv')
        self.wait_for(self.directory / 'csv-b.blocked')
        self.assertIsNone(second.poll())
        (self.directory / 'writer-a.release').write_text('release')
        self.assertEqual(first.wait(timeout=5), 2)
        self.assertEqual(second.wait(timeout=5), 0)
        with self.shared.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([r['session_id'] for r in rows], ['csv-b'])
        self.assertEqual(rows[0]['total_tokens'], '15')
        self.assert_clean_metadata()


if __name__ == '__main__':
    unittest.main()
