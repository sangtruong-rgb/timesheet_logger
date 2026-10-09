"""Stepwise execution preserves snapshots, failures and AI usage scope."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
from workflow_steps import main, inspect_run, run_logged
from run_codex_summary import summary_input
from cli_fixture import write_python_cli
import test_remaining_storage as fixture


class TestWorkflowSteps(unittest.TestCase):
    def setUp(self):
        fixture.TestRemainingStorage.setUp(self)
        self.snapshot = self.directory / 'activity.json'
        self.frozen = fixture.TestRemainingStorage.freeze(self)

    def invoke(self, *args):
        self.out, self.err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.err):
            return main(list(args))

    def test_views_reuse_validated_snapshot_without_mutation_or_collection(self):
        before = self.snapshot.read_bytes()
        with patch('subprocess.Popen', side_effect=AssertionError('inspection must not start processes')):
            self.assertEqual(json.loads(inspect_run(self.directory, 'blocks')), self.frozen['blocks'])
            request = json.loads(inspect_run(self.directory, 'request'))
            self.assertEqual(request, summary_input(self.frozen, 'compact')[0])
            self.assertEqual(json.loads(inspect_run(self.directory, 'sources'))['commits'], self.normalized['commits'])
            self.assertEqual(json.loads(inspect_run(self.directory, 'usage'))['status'], 'UNKNOWN')
        self.assertEqual(self.snapshot.read_bytes(), before)
        self.assertFalse((self.directory / 'codex').exists())

    def test_corrupt_snapshot_prevents_summary_or_assembly(self):
        self.snapshot.write_text('{}')
        with patch('workflow_steps.run_logged') as execute:
            self.assertEqual(self.invoke('summary', str(self.directory)), 2)
            self.assertEqual(self.invoke('assemble', str(self.directory)), 2)
            execute.assert_not_called()

    def test_old_invocation_without_request_is_not_misrepresented_as_current_prompt(self):
        (self.directory / 'codex').mkdir()
        (self.directory / 'codex/prompt.txt').write_text('historical model input')
        self.assertEqual(inspect_run(self.directory, 'prompt'), 'historical model input')
        with self.assertRaisesRegex(ValueError, 'historical input'):
            inspect_run(self.directory, 'request')

    def test_existing_prepare_directory_is_preserved(self):
        before = self.snapshot.read_bytes()
        with patch('workflow_steps.run_logged') as execute:
            self.assertEqual(self.invoke('prepare', str(self.directory), '--start', '09:00'), 2)
            execute.assert_not_called()
        self.assertEqual(self.snapshot.read_bytes(), before)

    def test_invalid_hours_fail_before_creating_directory(self):
        destination = self.directory / 'new'
        with patch('workflow_steps.run_logged') as execute:
            self.assertEqual(self.invoke('prepare', str(destination), '--windows', 'bad'), 2)
            self.assertFalse(destination.exists())
            execute.assert_not_called()

    def test_prepare_passes_confirmed_windows_and_returns_failure(self):
        destination = self.directory / 'new run with spaces'
        with patch('workflow_steps.run_logged', return_value=2) as execute:
            result = self.invoke('prepare', str(destination), '--date', '2026-10-09',
                                 '--windows', '09:00-12:00, 13:30-17:30')
        self.assertEqual(result, 2)
        command = execute.call_args.args[2]
        self.assertEqual(command[command.index('--work-windows') + 1], '09:00-12:00, 13:30-17:30')
        self.assertIn('--review-ot', command)
        self.assertNotIn('--work-day-start', command)
        self.assertFalse((destination / 'codex').exists())

    def test_missing_ai_does_not_silently_assemble_fallback(self):
        with patch('workflow_steps.run_logged') as execute:
            self.assertEqual(self.invoke('assemble', str(self.directory)), 2)
            execute.assert_not_called()
        self.assertIn('--without-ai', self.err.getvalue())

    def test_explicit_fallback_assembles_without_ai_or_usage(self):
        self.assertEqual(self.invoke('assemble', str(self.directory), '--without-ai'), 0)
        self.assertIn('Total Proposed Time', inspect_run(self.directory, 'timesheet'))
        self.assertFalse((self.directory / 'codex').exists())
        self.assertFalse((self.directory / 'token-usage.csv').exists())
        self.assertEqual(len(list((self.directory / 'logs').glob('assemble-*.log'))), 1)

    def test_empty_day_skips_summary_without_claiming_zero(self):
        snapshot = {**self.frozen, 'ai_input': {'blocks': []}}
        with patch('workflow_steps.snapshot_for', return_value=snapshot), patch('workflow_steps.run_logged') as execute:
            self.assertEqual(self.invoke('summary', str(self.directory)), 0)
            self.assertEqual(json.loads(inspect_run(self.directory, 'usage'))['status'], 'SKIPPED')
            execute.assert_not_called()

    def test_logs_preserve_nonzero_exit_and_separate_attempts(self):
        command = [sys.executable, '-c', 'import sys; print("synthetic diagnostic"); sys.exit(7)']
        with contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                self.assertEqual(run_logged(self.directory, 'prepare', command), 7)
        logs = list((self.directory / 'logs').glob('prepare-*.log'))
        self.assertEqual(len(logs), 2)
        self.assertTrue(all('Process exit code: 7' in p.read_text() for p in logs))

    def test_summary_and_assembly_roundtrip_uses_fake_model_only(self):
        fake = self.directory / 'fake-codex'
        write_python_cli(fake, '''import sys, json
from pathlib import Path
if '--version' in sys.argv:
    print('codex synthetic test'); sys.exit(0)
request = json.load(sys.stdin)
output = Path(sys.argv[sys.argv.index('--output-last-message') + 1])
output.write_text(json.dumps({'judgments': [{'id': job['id'], 'description': 'Implemented synthetic test work.'} for job in request['jobs']]}))
for event in [{'type':'thread.started','thread_id':'synthetic-workflow'}, {'type':'turn.started'}, {'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':40,'output_tokens':20}}]:
    print(json.dumps(event))
''')
        before = self.snapshot.read_bytes()
        self.assertEqual(self.invoke('summary', str(self.directory), '--codex', str(fake)), 0)
        usage = json.loads(inspect_run(self.directory, 'usage'))
        self.assertEqual(usage['csv_counts'], {'input_tokens': 60, 'cache_tokens': 40, 'output_tokens': 20, 'total_tokens': 120})
        self.assertEqual(usage['scope'], 'codex_summary_invocation')
        self.assertEqual(self.invoke('assemble', str(self.directory)), 0)
        self.assertIn('Implemented synthetic test work.', inspect_run(self.directory, 'timesheet'))
        self.assertTrue((self.directory / 'token-usage.csv').exists())
        self.assertEqual(self.snapshot.read_bytes(), before)
        # A second summary must not spend tokens by silently replacing the first.
        self.assertEqual(self.invoke('summary', str(self.directory), '--codex', str(fake)), 2)
        self.assertEqual(json.loads(inspect_run(self.directory, 'usage'))['csv_counts']['total_tokens'], 120)


if __name__ == '__main__':
    unittest.main()
