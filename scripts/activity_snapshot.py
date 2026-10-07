"""Immutable activity snapshots keep collection and AI assembly on the same evidence."""
import hashlib
import json
from pathlib import Path
import uuid
from atomic_storage import directory_lock, write_bundle, StorageError
from block_identity import BlockIdentityError, index_blocks
from activity_review import validate_unassigned_activity


class SnapshotError(BlockIdentityError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def read_snapshot(path):
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1:
            raise ValueError("Unsupported snapshot")
        expected = snapshot["fingerprint"]
        body = {k: v for k, v in snapshot.items() if k != "fingerprint"}
        if fingerprint(body) != expected:
            raise ValueError("Snapshot fingerprint mismatch")
        if snapshot["collection"]["status"] not in ("complete", "demo") or not isinstance(snapshot["run_id"], str):
            raise ValueError("Unsuccessful or unidentified snapshot")
        index_blocks(snapshot["blocks"])
        validate_unassigned_activity(snapshot["unassigned_activity"])
        if any(b["date"] != snapshot["normalized"]["date"] for b in snapshot["blocks"]):
            raise ValueError("Snapshot dates conflict")
        from build_time_blocks import build_time_blocks
        retained = []
        rebuilt = build_time_blocks(snapshot["normalized"], unassigned_activity=retained)
        if rebuilt != snapshot["blocks"] or retained != snapshot["unassigned_activity"]:
            raise ValueError("Snapshot block/source evidence conflicts")
        from prepare_ai_input import prepare_activity_input
        maximum = snapshot["ai_input"]["payload_measurement"]["max_bytes"]
        if prepare_activity_input(rebuilt, retained, maximum) != snapshot["ai_input"]:
            raise ValueError("Snapshot AI input conflicts")
        return snapshot
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise SnapshotError("Requested snapshot is unreadable, corrupt or inconsistent; collection was not repeated") from exc


def save_snapshot(path, normalized, collection, blocks, unassigned, ai_input, ai_export=None):
    path = Path(path)
    body = {"schema_version": 1, "normalized": normalized, "collection": collection,
            "blocks": blocks, "unassigned_activity": unassigned, "ai_input": ai_input}
    if ai_export and Path(ai_export).resolve() == path.resolve():
        raise SnapshotError("AI export cannot overwrite its activity snapshot")
    extra = [ai_export] if ai_export else []
    try:
        return _save_snapshot(path, body, extra, ai_input, ai_export)
    except (StorageError, OSError) as exc:
        raise SnapshotError("Snapshot output could not be saved; prior output was preserved") from exc


def _save_snapshot(path, body, extra, ai_input, ai_export):
    with directory_lock(path.parent, extra_paths=extra):
        if path.exists():
            existing = read_snapshot(path)
            if {k: v for k, v in existing.items() if k not in ("run_id", "fingerprint")} != body:
                raise SnapshotError("Snapshot is immutable; choose a new snapshot path when source activity changes")
            snapshot = existing
        else:
            body["run_id"] = str(uuid.uuid4())
            snapshot = {**body, "fingerprint": fingerprint(body)}
        contents = {path: json.dumps(snapshot, indent=2)}
        if ai_export:
            contents[Path(ai_export)] = json.dumps(ai_input, indent=2)
        write_bundle(contents, path.parent)
    return snapshot
