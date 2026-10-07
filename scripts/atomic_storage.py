"""POSIX writer locks, atomic files and recoverable multi-file daily updates."""
import base64
import contextlib
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time


class StorageError(ValueError):
    pass


def atomic_write(path, content):
    path = Path(path)
    if path.is_symlink() or path.name in ("token.json", "credentials.json"):
        raise StorageError("Refusing to replace a symlink or OAuth output")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".timesheet-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8") if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def recover_bundle(directory, extra_paths=()):
    directory = Path(directory).resolve()
    journal = directory / ".timesheet-transaction.json"
    if not journal.exists():
        return
    allowed_extra = {Path(p).resolve() for p in extra_paths}
    try:
        record = json.loads(journal.read_text(encoding="utf-8"))
        if record.get("version") != 1 or not isinstance(record.get("files"), list):
            raise ValueError("Invalid journal")
        restored = []
        for item in record["files"]:
            path = Path(item["path"])
            if not path.is_absolute() or path.is_symlink() or path.name in ("token.json", "credentials.json", ".timesheet.lock", ".timesheet-transaction.json"):
                raise ValueError("Unsafe journal path")
            if path.resolve().parent != directory and path.resolve() not in allowed_extra:
                raise ValueError("Journal target is outside the authorized output bundle")
            previous = item["previous"]
            restored.append((path, None if previous is None else base64.b64decode(previous, validate=True)))
        # Validate the whole journal before restoring anything.
        for path, previous in restored:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, previous)
        journal.unlink()
    except Exception as exc:
        raise StorageError("Pending storage transaction cannot be recovered; preserve journal and review output") from exc


@contextlib.contextmanager
def directory_lock(directory, *, timeout=15, extra_paths=()):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".timesheet.lock").open("a+b") as lock:
        until = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= until:
                    raise StorageError("Another timesheet writer holds the output lock; retry after it finishes")
                time.sleep(0.05)
        try:
            recover_bundle(directory, extra_paths)
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def write_bundle(contents, directory):
    """Caller holds directory_lock through reading, validation and writing."""
    files = {Path(path).absolute(): content.encode("utf-8") if isinstance(content, str) else content
             for path, content in contents.items()}
    files = {path: content for path, content in files.items() if not path.exists() or path.read_bytes() != content}
    if not files:
        return
    for path in files:
        if path.is_symlink() or path.name in ("token.json", "credentials.json", ".timesheet.lock", ".timesheet-transaction.json"):
            raise StorageError("Unsafe timesheet output path")
    directory = Path(directory)
    journal = directory / ".timesheet-transaction.json"
    record = {"version": 1, "files": [{"path": str(path), "previous": base64.b64encode(path.read_bytes()).decode("ascii")
                                     if path.exists() else None} for path in files]}
    atomic_write(journal, json.dumps(record))
    try:
        for path, content in files.items():
            atomic_write(path, content)
        journal.unlink()
    except Exception as exc:
        recover_bundle(directory, files)
        raise StorageError("Output update failed and was rolled back; prior files were preserved") from exc
