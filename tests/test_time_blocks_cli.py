"""Real CLI exit statuses with isolated synthetic input and output files."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestTimeBlocksCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.source = self.directory / 'normalized.json'
        self.output = self.directory / 'blocks.json'
        self.model = {'date': '2026-10-08', 'timezone': 'Asia/Ho_Chi_Minh',
                      'calendar': [], 'commits': [], 'pull_requests': []}

    def invoke(self, output=None):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/build_time_blocks.py'),
                               '-i', str(self.source), '-o', str(output or self.output)],
                              capture_output=True, text=True, timeout=15)

    def test_invalid_model_exits_two_and_preserves_existing_output(self):
        for changes in ({'timezone': 'invalid/zone'}, {'date': 'invalid-date'},
                        {'calendar': [{'title': 'Invalid meeting', 'start': 'bad', 'end': 'bad'}]}):
            with self.subTest(changes=changes):
                self.source.write_text(json.dumps({**self.model, **changes}))
                self.output.write_bytes(b'PROTECTED BLOCKS')
                result = self.invoke()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('Output/validation blocked', result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(self.output.read_bytes(), b'PROTECTED BLOCKS')

    def test_malformed_json_exits_two_and_preserves_existing_output(self):
        self.source.write_text('{invalid json')
        self.output.write_bytes(b'PROTECTED BLOCKS')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('JSONDecodeError', result.stderr)
        self.assertEqual(self.output.read_bytes(), b'PROTECTED BLOCKS')

    def test_output_write_failure_exits_two_and_preserves_directory(self):
        self.source.write_text(json.dumps(self.model))
        self.output.mkdir()
        sentinel = self.output / 'sentinel'
        sentinel.write_bytes(b'PROTECTED DIRECTORY')
        result = self.invoke()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('Output/validation blocked', result.stderr)
        self.assertEqual(sentinel.read_bytes(), b'PROTECTED DIRECTORY')

    def test_success_exits_zero_with_blocks_and_review_output(self):
        activity = {'hash': 'synthetic-evening', 'timestamp': '2026-10-08T19:00:00+07:00'}
        self.source.write_text(json.dumps({**self.model, 'commits': [activity]}))
        result = self.invoke()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(self.output.read_text()), {
            'blocks': [], 'unassigned_activity': [
                {'source': 'git', 'reason': 'outside_blocks', 'activity': activity}]})


if __name__ == '__main__':
    unittest.main()
