"""Real process execution with spaced paths; no live-service claim."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from cli_fixture import write_python_cli


class TestCLIFixture(unittest.TestCase):
    def test_spaced_interpreter_script_and_literal_arguments(self):
        with tempfile.TemporaryDirectory(prefix='cli fixture ') as temp:
            directory = Path(temp)
            python = directory / 'python with spaces'
            python.symlink_to(sys.executable)
            cli = directory / 'fake cli'
            write_python_cli(cli, 'import json, sys\nprint(json.dumps(sys.argv[1:]))\n', interpreter=str(python))
            args = ['arg with spaces', '$(not-a-command)', '`literal`', 'single\'quote']
            result = subprocess.run([str(cli), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), args)

    def test_fixture_exit_and_stderr_preserved(self):
        with tempfile.TemporaryDirectory(prefix='cli fixture ') as temp:
            cli = Path(temp) / 'fake cli'
            write_python_cli(cli, "import sys\nprint('synthetic failure', file=sys.stderr)\nsys.exit(7)\n")
            result = subprocess.run([str(cli)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 7)
            self.assertEqual(result.stderr.strip(), 'synthetic failure')


if __name__ == '__main__': unittest.main()
