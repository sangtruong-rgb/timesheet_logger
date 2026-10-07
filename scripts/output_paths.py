"""Reject auxiliary output paths that would replace inputs or managed evidence."""
import json
from pathlib import Path
import re


class OutputPathError(ValueError):
    pass


DAILY_FILE = re.compile(r"\d{4}-\d{2}-\d{2}(?:\.(?:collection|calendar-context|activity-review))?\.(?:json|md)$")
RESERVED_NAMES = {"token.json", "credentials.json", ".timesheet.lock", ".timesheet-transaction.json"}


def same_location(first, second):
    first, second = Path(first), Path(second)
    if first.resolve() == second.resolve():
        return True
    return first.exists() and second.exists() and first.samefile(second)


def stored_evidence(path):
    """Recognize renamed JSON evidence too; never include its contents in errors."""
    if not path.is_file() or path.suffix.lower() != ".json":
        return False
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        return False  # Corrupt daily stores are protected by their reserved names.
    if isinstance(value, list):
        return any(isinstance(row, dict) and isinstance(row.get("entry"), dict) for row in value)
    if not isinstance(value, dict):
        return False
    return any(keys <= value.keys() for keys in (
        {"schema_version", "fingerprint", "normalized", "blocks"},
        {"date", "collection", "activity"},
        {"date", "collection_status", "calendar_context"},
        {"date", "collection_status", "unassigned_activity"},
        {"date", "sources", "status"},
    ))


def validate_auxiliary_output(path, *, protected_paths=(), role="AI export"):
    """No output mutation, directory creation, lock recovery or network calls."""
    path = Path(path)
    for protected in protected_paths:
        if protected is not None and same_location(path, protected):
            raise OutputPathError(f"{role} cannot overwrite protected input/output '{path}'; choose a different output path")
    names = {path.name, path.resolve().name}
    if path.suffix.lower() == ".jsonl" or any(DAILY_FILE.fullmatch(name) or name in RESERVED_NAMES for name in names):
        raise OutputPathError(f"{role} cannot overwrite a timesheet, audit sidecar or reserved file '{path}'; choose a different output path")
    if path.is_symlink() or path.is_dir() or stored_evidence(path):
        raise OutputPathError(f"{role} cannot replace stored evidence, a symlink or directory '{path}'; choose a different output path")
