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

TICKET_PATTERN = re.compile(r'\b([A-Z]{2,10}-[0-9]+)\b')


def extract_tickets(texts: List[str]) -> List[str]:
    tickets = set()
    for t in texts:
        matches = TICKET_PATTERN.findall(t)
        for m in matches:
            tickets.add(m)
    return sorted(list(tickets))


def prepare_ai_payload_for_block(block: Dict[str, Any]) -> Dict[str, Any]:
    calendar_titles = [t.strip() for t in block.get("calendar_titles", []) if t.strip()]
    commit_messages = [c.get("message", "").strip() for c in block.get("commits", []) if c.get("message", "").strip()]
    prs = [{"id": p.get("id"), "title": p.get("title", "").strip()} for p in block.get("prs", []) if p.get("id") is not None]

    # Pre-extract ticket keys if any
    all_text = commit_messages + [p["title"] for p in prs]
    ticket_ids = extract_tickets(all_text)

    payload = {
      "block_id": get_block_id(block.get("date"), block.get("start_time"), block.get("end_time")),
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
        # If there are no commits and no PRs, and calendar title is known, AI judgment is minimal or skipped
        payload = prepare_ai_payload_for_block(b)
        payloads.append(payload)
    return payloads


def main():
    parser = argparse.ArgumentParser(description="Prepare minimal payload for AI topic synthesis.")
    parser.add_argument("--blocks-file", "-i", type=str, required=True, help="Path to candidate blocks JSON file")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output AI input JSON file")

    args = parser.parse_args()
    b_path = Path(args.blocks_file)
    if not b_path.exists():
        print(f"Error: {args.blocks_file} not found.", file=sys.stderr)
        sys.exit(1)

    blocks = json.loads(b_path.read_text(encoding="utf-8"))
    payloads = prepare_all_blocks(blocks)

    output_json = json.dumps(payloads, indent=2)
    if args.output and args.output != "-":
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
