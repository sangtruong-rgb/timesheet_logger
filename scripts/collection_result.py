"""Explicit source outcomes shared by the PR and Calendar collectors."""

import json
import sys
from pathlib import Path


class SourceUnavailable(RuntimeError):
    """A source cannot be queried with the current setup."""


def collection_result(source, mode, status, items=None, reason=None):
    result = {"source": source, "mode": mode, "status": status, "items": items or []}
    if reason:
        result["reason"] = reason
    return result


def source_metadata(result):
    return {**{k: v for k, v in result.items() if k != "items"},
            "count": len(result["items"])}


def load_fixture_records(fixture_path):
    """Explicit fixtures must exist and contain a JSON array of objects."""
    data = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError("Fixture must contain a JSON array of objects")
    return data


def emit_result(result, output=None):
    text = json.dumps(result, indent=2)
    try:
        if output and output != "-":
            from atomic_storage import directory_lock, atomic_write
            path = Path(output)
            with directory_lock(path.parent):
                atomic_write(path, text)
        else:
            print(text)
    except (OSError, ValueError) as exc:
        print(f"Collector output blocked ({type(exc).__name__}); review output path. Source evidence was not exported.", file=sys.stderr)
        return 2
    print(f"{result['source']}: {result['status']} ({result['mode']}, "
          f"{len(result['items'])} items)" +
          (f" — {result['reason']}" if result.get("reason") else ""), file=sys.stderr)
    return 0 if result["status"] == "success" else 2
