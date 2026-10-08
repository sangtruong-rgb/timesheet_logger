"""POSIX launchers for explicitly synthetic service fixtures in subprocess tests."""
from pathlib import Path
import shlex
import sys


def write_python_cli(path, source, *, interpreter=None):
    path = Path(path)
    script = path.with_name(path.name + '-fixture.py')
    script.write_text(source, encoding='utf-8')
    # Kernel shebang parsing does not support interpreter paths containing spaces.
    path.write_text('#!/bin/sh\nexec ' + shlex.quote(interpreter or sys.executable)
                    + ' ' + shlex.quote(str(script)) + ' "$@"\n', encoding='utf-8')
    path.chmod(0o755)
