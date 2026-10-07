"""POSIX writer locks, atomic files and recoverable multi-file daily updates."""
import base64
import contextlib
import contextvars
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time

PENDING = ".timesheet-pending.json"
JOURNAL = ".timesheet-transaction.json"
LOCKED_DIRECTORIES = contextvars.ContextVar("timesheet_locked_directories", default=frozenset())


def pending_owner(directory):
    marker = Path(directory) / PENDING
    if not marker.exists() and not marker.is_symlink():
        return None
    try:
        if marker.is_symlink():
            raise ValueError("Symlink marker")
        record = json.loads(marker.read_text(encoding="utf-8"))
        journal = Path(record["journal"])
        if record.get("version") != 1 or not journal.is_absolute() or journal.name != JOURNAL:
            raise ValueError("Invalid transaction marker")
        return journal
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise StorageError("Pending transaction marker is corrupt; preserve it and review output") from exc


def clear_pending(directories, journal):
    # After the journal is gone these are harmless stale reservations. Cleanup
    # failures must not turn an already committed update into a reported rollback.
    for directory in directories:
        try:
            if pending_owner(directory) == journal:
                (Path(directory) / PENDING).unlink(missing_ok=True)
        except (StorageError, OSError):
            pass


class StorageError(ValueError):
    pass


def atomic_write(path, content):
    path = Path(path)
    if path.is_symlink():
        raise StorageError("Refusing to replace a symlink output")
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
    """Caller holds all target-parent locks before restoring any prior bytes."""
    directory = Path(directory).resolve()
    journal = directory / JOURNAL
    if not journal.exists():
        return
    allowed_extra = {Path(p).resolve() for p in extra_paths}
    try:
        if journal.is_symlink():
            raise ValueError("Symlink journal")
        record = json.loads(journal.read_text(encoding="utf-8"))
        if record.get("version") != 1 or not isinstance(record.get("files"), list):
            raise ValueError("Invalid journal")
        restored = []
        for item in record["files"]:
            path = Path(item["path"])
            if not path.is_absolute() or path.is_symlink() or path.name in ("token.json", "credentials.json", ".timesheet.lock", JOURNAL, PENDING):
                raise ValueError("Unsafe journal path")
            if path.resolve().parent != directory and path.resolve() not in allowed_extra:
                raise ValueError("Journal target is outside the authorized output bundle")
            previous = item["previous"]
            restored.append((path, None if previous is None else base64.b64decode(previous, validate=True)))
        # Validate the whole journal before restoring anything.
        parents = {directory, *(path.resolve().parent for path, _ in restored)}
        if not parents <= LOCKED_DIRECTORIES.get():
            raise ValueError("Recovery requires all target-parent locks")
        for path, previous in restored:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, previous)
        journal.unlink()
        clear_pending(parents, journal)
    except Exception as exc:
        raise StorageError("Pending storage transaction cannot be recovered; preserve journal and review output") from exc


@contextlib.contextmanager
def _directory_lock(directory, timeout):
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
            token = LOCKED_DIRECTORIES.set(LOCKED_DIRECTORIES.get() | {directory.resolve()})
            try:
                yield
            finally:
                LOCKED_DIRECTORIES.reset(token)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


@contextlib.contextmanager
def directory_lock(directory, *, timeout=15, extra_paths=()):
    """Lock every participating parent, then recover only the authorized owner."""
    directory = Path(directory).resolve()
    extra = tuple(Path(path).resolve() for path in extra_paths)
    directories = {directory, *(path.parent for path in extra)}
    journal = directory / JOURNAL
    until = time.monotonic() + timeout
    with contextlib.ExitStack() as stack:
        for parent in sorted(directories, key=str):
            stack.enter_context(_directory_lock(parent, max(0, until - time.monotonic())))
        for parent in directories:
            owner = pending_owner(parent)
            if owner is not None and owner != journal and owner.exists():
                raise StorageError("Another output bundle has a pending transaction here; recover its original output directory before retrying")
            if owner is not None and not owner.exists():
                (parent / PENDING).unlink()
        # Recovery runs after every lock has been acquired, never under a partial set.
        recover_bundle(directory, extra)
        yield


def write_bundle(contents, directory):
    """Caller holds directory_lock(extra_paths=...) through the whole transaction."""
    files = {Path(path).absolute(): content.encode("utf-8") if isinstance(content, str) else content
             for path, content in contents.items()}
    directory = Path(directory).resolve()
    parents = {directory, *(path.resolve().parent for path in files)}
    if not parents <= LOCKED_DIRECTORIES.get():
        raise StorageError("Every output parent must be locked; include external files in directory_lock(extra_paths=...)")
    files = {path: content for path, content in files.items() if not path.exists() or path.read_bytes() != content}
    if not files:
        return
    for path in files:
        if path.is_symlink() or path.name in ("token.json", "credentials.json", ".timesheet.lock", JOURNAL, PENDING):
            raise StorageError("Unsafe timesheet output path")
    journal = directory / JOURNAL
    record = {"version": 1, "files": [{"path": str(path), "previous": base64.b64encode(path.read_bytes()).decode("ascii")
                                     if path.exists() else None} for path in files]}
    try:
        # Reserve all participants before making a recoverable journal. A crash
        # before journal creation cannot have changed data; markers are then stale.
        for parent in sorted(parents, key=str):
            atomic_write(parent / PENDING, json.dumps({"version": 1, "journal": str(journal)}))
        atomic_write(journal, json.dumps(record))
        for path, content in files.items():
            atomic_write(path, content)
        journal.unlink()
    except Exception as exc:
        if journal.exists():
            recover_bundle(directory, files)
        else:
            clear_pending(parents, journal)
        raise StorageError("Output update failed and was rolled back; prior files were preserved") from exc
    clear_pending(parents, journal)
