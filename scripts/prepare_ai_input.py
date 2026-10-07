#!/usr/bin/env python3
"""
prepare_ai_input.py - Deterministic preparation of minimal payload for AI judgment.

Filters out all unnecessary fields:
- No git hashes
- No author names or emails
- No repo URLs
- No raw timestamps or durations
- No duplicated strings

Includes future optimization:
- Deterministic ticket ID extraction (e.g. PROJ-123) to pre-group activities.
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


def prepare_all_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    index_blocks(blocks)
    payloads = []
    for b in blocks:
        if not b.get("commits") and not b.get("prs"):
            continue  # Calendar-only summaries use the event title; no AI judgment needed.
        payload = prepare_ai_payload_for_block(b)
        payloads.append(payload)
    return payloads


def prepare_activity_input(blocks, unassigned_activity, max_bytes=12000):
    payload = {"blocks": prepare_all_blocks(blocks),
            "unassigned_activity": minimal_review(unassigned_activity),
            "review": {"status": "required" if unassigned_activity else "none",
                       "instruction": "Summarize only blocks. Unassigned activity needs human review; do not attach it to a block or infer work duration."}}
    from block_identity import BlockIdentityError
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes < 1:
        raise BlockIdentityError("AI byte limit must be a positive integer")
    payload["payload_measurement"] = {"serialized_bytes": 0,
        "estimated_tokens_heuristic": 0, "token_count_is_exact": False, "max_bytes": max_bytes}
    # Measure the exact exported JSON including this metadata (stable fixed point).
    while True:
        size = len(json.dumps(payload, indent=2).encode("utf-8"))
        measurement = payload["payload_measurement"]
        if measurement["serialized_bytes"] == size and measurement["estimated_tokens_heuristic"] == (size + 3)//4:
            break
        measurement.update(serialized_bytes=size, estimated_tokens_heuristic=(size + 3)//4)
    if size > max_bytes:
        raise BlockIdentityError(f"AI payload is {size} bytes, above limit {max_bytes}; split the activity snapshot before synthesis. No evidence was dropped.")
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
    if args.output and args.output != "-":
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
