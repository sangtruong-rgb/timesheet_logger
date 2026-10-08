#!/usr/bin/env python3
"""
prepare_ai_input.py - Deterministic preparation of minimal payload for AI judgment.

Filters out all unnecessary fields:
- No git hashes
- No author names or emails
- No repo URLs
- No raw timestamps or durations
- No duplicated strings

The audit envelope retains block identities, PR references and review evidence.
The model request shares text across semantic jobs without changing intervals.
Payload v3 shares descriptions across pieces of one commit allocation.
Only the compact request is byte-bounded in v2/v3; older snapshots remain reproducible.
Token estimates are heuristic. No persistent judgment cache is implemented.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from block_identity import get_block_id, index_blocks
from activity_review import minimal_review, unpack_activity_snapshot

from activity_text import extract_tickets


def prepare_ai_payload_for_block(block: Dict[str, Any]) -> Dict[str, Any]:
    calendar_titles = list(dict.fromkeys(t.strip() for t in block.get("calendar_titles", []) if t.strip()))
    commit_messages = list(dict.fromkeys(c.get("message", "").strip() for c in block.get("commits", []) if c.get("message", "").strip()))
    prs = [{"id": p.get("id"), "title": p.get("title", "").strip(),
            **({"repository": p["repository"]} if p.get("repository") else {})}
           for p in block.get("prs", []) if p.get("id") is not None]
    prs = list({(p.get("repository", ""), p["id"]): p for p in prs}.values())

    # Pre-extract ticket keys if any
    all_text = commit_messages + [p["title"] for p in prs]
    ticket_ids = extract_tickets(all_text)

    payload = {
      "block_id": get_block_id(block.get("date"), block.get("start_time"), block.get("end_time")),
      **({"time_basis": block["time_basis"]} if "time_basis" in block else {}),
      **({"calendar_overlap": True, "attendance": "unconfirmed"} if block.get("calendar_overlap") else {}),
      "date": block.get("date", ""),
      "block": {
        "start": block.get("start_time", ""),
        "end": block.get("end_time", "")
      },
      "calendar_titles": calendar_titles,
      "commit_messages": commit_messages,
      "prs": prs
    }

    if ticket_ids:
        payload["detected_ticket_ids"] = ticket_ids

    return payload


def prepare_all_blocks(blocks: List[Dict[str, Any]], *, include_summary_groups=False) -> List[Dict[str, Any]]:
    index_blocks(blocks)
    payloads = []
    for b in blocks:
        if not b.get("commits") and not b.get("prs"):
            continue  # Calendar-only summaries use the event title; no AI judgment needed.
        payload = prepare_ai_payload_for_block(b)
        if include_summary_groups:
            from summary_request import commit_summary_group_id
            group = commit_summary_group_id(b)
            if group is not None:
                payload['summary_group_id'] = group
        payloads.append(payload)
    return payloads


def prepare_activity_input(blocks, unassigned_activity, max_bytes=12000, *, payload_version=3):
    from block_identity import BlockIdentityError
    if type(payload_version) is not int or payload_version not in (1, 2, 3):
        raise BlockIdentityError("Unsupported AI payload version")
    payload = {"blocks": prepare_all_blocks(blocks, include_summary_groups=payload_version >= 3),
            "unassigned_activity": minimal_review(unassigned_activity),
            "review": {"status": "required" if unassigned_activity else "none",
                       "instruction": "Summarize only blocks. Unassigned activity needs human review; do not attach it to a block or infer work duration."}}
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise BlockIdentityError("AI byte limit must be a positive integer")
    if payload_version >= 2:
        from summary_request import build_summary_request, serialize_request
        request, _ = build_summary_request(payload['blocks'])
        payload.update(payload_version=payload_version, summary_request=request)
        model_size = len(serialize_request(request).encode('utf-8'))
    payload["payload_measurement"] = {"serialized_bytes": 0,
        "estimated_tokens_heuristic": 0, "token_count_is_exact": False, "max_bytes": max_bytes}
    if payload_version >= 2:
        payload['payload_measurement'].update(model_payload_bytes=model_size,
                                              byte_limit_scope='summary_request')
    # Measure the exact exported JSON including this metadata (stable fixed point).
    while True:
        size = len(json.dumps(payload, indent=2).encode("utf-8"))
        measurement = payload["payload_measurement"]
        estimated = ((model_size if payload_version >= 2 else size) + 3)//4
        if measurement["serialized_bytes"] == size and measurement["estimated_tokens_heuristic"] == estimated:
            break
        measurement.update(serialized_bytes=size, estimated_tokens_heuristic=estimated)
    bounded_size = model_size if payload_version >= 2 else size
    if bounded_size > max_bytes:
        raise BlockIdentityError(f"AI payload is {bounded_size} bytes, above limit {max_bytes}; select a smaller scope or set an explicit larger byte bound before synthesis. No evidence was dropped.")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Prepare minimal payload for AI topic synthesis.")
    parser.add_argument("--blocks-file", "-i", type=str, required=True, help="Path to candidate blocks JSON file")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output AI input JSON file")
    parser.add_argument("--max-bytes", type=int, default=12000)

    args = parser.parse_args()
    b_path = Path(args.blocks_file)
    if not b_path.exists():
        print(f"Error: {args.blocks_file} not found.", file=sys.stderr)
        sys.exit(1)

    try:
        blocks, unassigned = unpack_activity_snapshot(json.loads(b_path.read_text(encoding="utf-8")), "blocks")
        payloads = prepare_activity_input(blocks, unassigned or [], args.max_bytes)
    except (ValueError, OSError) as exc:
        print(f"Activity/AI-input validation failed: {exc}", file=sys.stderr)
        return 2

    output_json = json.dumps(payloads, indent=2)
    try:
        if args.output and args.output != "-":
            from atomic_storage import directory_lock, atomic_write
            out_p = Path(args.output)
            with directory_lock(out_p.parent):
                atomic_write(out_p, output_json)
        else:
            print(output_json)
    except (ValueError, OSError) as exc:
        print(f"Output blocked: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
