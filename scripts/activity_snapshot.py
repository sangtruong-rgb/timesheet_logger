"""Immutable activity snapshots keep collection and AI assembly on the same evidence."""
import hashlib
import json
from pathlib import Path
import uuid
from atomic_storage import directory_lock, write_bundle, StorageError
from block_identity import BlockIdentityError, index_blocks
from activity_review import validate_unassigned_activity
from output_paths import validate_auxiliary_output, OutputPathError


class SnapshotError(BlockIdentityError):
    pass


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def read_snapshot(path):
    try:
        snapshot = json.loads(Path(path).read_text(encoding="utf-8"))
        if (not isinstance(snapshot, dict) or type(snapshot.get('schema_version')) is not int
                or snapshot['schema_version'] not in (1, 2, 3, 4, 5, 6, 7, 8, 9)):
            raise ValueError("Unsupported snapshot")
        expected = snapshot["fingerprint"]
        body = {k: v for k, v in snapshot.items() if k != "fingerprint"}
        if fingerprint(body) != expected:
            raise ValueError("Snapshot fingerprint mismatch")
        if snapshot["collection"]["status"] not in ("complete", "demo") or not isinstance(snapshot["run_id"], str):
            raise ValueError("Unsuccessful or unidentified snapshot")
        legacy = snapshot['schema_version'] < 9
        if legacy and (snapshot['schema_version'] >= 5) != ('work_schedule' in snapshot['normalized']):
            raise ValueError('Snapshot schedule requires schema v5')
        if legacy and (snapshot['schema_version'] >= 6) != ('windows' in snapshot['normalized'].get('work_confirmation', {})):
            raise ValueError('Snapshot confirmed windows require schema v6')
        if legacy and (snapshot['schema_version'] >= 7) != ('overtime_review' in snapshot['normalized']):
            raise ValueError('Snapshot OT review requires schema v7')
        if legacy and (snapshot['schema_version'] >= 8) != ('policy' in snapshot['normalized'].get('overtime_review', {})):
            raise ValueError('Snapshot default OT policy requires schema v8')
        from commit_groups import SUPPORTED_GROUPING_POLICIES
        if ((snapshot['schema_version'] == 9) != ('commit_grouping' in snapshot['normalized'])
                or (not legacy and snapshot['normalized']['commit_grouping'] not in SUPPORTED_GROUPING_POLICIES)):
            raise ValueError('Snapshot commit grouping requires schema v9')
        if ('overtime_review' in snapshot['normalized'] and snapshot['collection'].get('overtime_review')
                != snapshot['normalized']['overtime_review']):
            raise ValueError('Snapshot OT decision conflicts with its collection metadata')
        index_blocks(snapshot["blocks"])
        validate_unassigned_activity(snapshot["unassigned_activity"])
        if any(b["date"] != snapshot["normalized"]["date"] for b in snapshot["blocks"]):
            raise ValueError("Snapshot dates conflict")
        from build_time_blocks import build_time_blocks
        retained = []
        rebuilt = build_time_blocks(snapshot["normalized"], unassigned_activity=retained,
                                    merge_short_commits=snapshot['schema_version'] >= 2,
                                    short_commit_merge_minutes=30 if snapshot['schema_version'] == 2 else 20,
                                    commit_allocation_version=2 if snapshot['schema_version'] >= 4 else 1)
        if rebuilt != snapshot["blocks"] or retained != snapshot["unassigned_activity"]:
            raise ValueError("Snapshot block/source evidence conflicts")
        from prepare_ai_input import prepare_activity_input
        maximum = snapshot["ai_input"]["payload_measurement"]["max_bytes"]
        if prepare_activity_input(rebuilt, retained, maximum,
                                  payload_version=snapshot['ai_input'].get('payload_version', 1)) != snapshot["ai_input"]:
            raise ValueError("Snapshot AI input conflicts")
        return snapshot
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise SnapshotError("Requested snapshot is unreadable, corrupt or inconsistent; collection was not repeated") from exc


def save_snapshot(path, normalized, collection, blocks, unassigned, ai_input, ai_export=None):
    path = Path(path)
    # v9 freezes PR/ticket grouping; v8 and older retain their allocation rules.
    version = (9 if 'commit_grouping' in normalized else
               8 if 'policy' in normalized.get('overtime_review', {}) else
               7 if 'overtime_review' in normalized else
               6 if 'windows' in normalized.get('work_confirmation', {}) else
               5 if 'work_schedule' in normalized else 4)
    body = {"schema_version": version,
            "normalized": normalized, "collection": collection,
            "blocks": blocks, "unassigned_activity": unassigned, "ai_input": ai_input}
    extra = [ai_export] if ai_export else []
    try:
        if ai_export:
            validate_auxiliary_output(ai_export, protected_paths=[path])
        return _save_snapshot(path, body, extra, ai_input, ai_export)
    except OutputPathError as exc:
        raise SnapshotError(str(exc)) from exc
    except (StorageError, OSError) as exc:
        raise SnapshotError("Snapshot output could not be saved; prior output was preserved") from exc


def _save_snapshot(path, body, extra, ai_input, ai_export):
    with directory_lock(path.parent, extra_paths=extra):
        if ai_export:
            validate_auxiliary_output(ai_export, protected_paths=[path])
        if path.exists():
            existing = read_snapshot(path)
            comparable = {**body, 'schema_version': existing['schema_version']}
            if {k: v for k, v in existing.items() if k not in ("run_id", "fingerprint")} != comparable:
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
