#!/usr/bin/env python3
"""
build_timesheet.py - Deterministically assemble final timesheet entries from blocks and AI judgment.

Requirements:
1. Each entry contains:
   - Date
   - Start time
   - End time
   - Description
2. Description format:
   "<Topic summary>. PRs: #<id1>, #<id2>"
   or "<Topic summary>. PRs: None" if no PRs exist.
   PRs appear exactly once at the end of the description.
3. Preserves full source evidence (commits, PRs, calendar) for auditability.
4. Provides deterministic rule-based fallback if AI judgment is not supplied.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from block_identity import BlockIdentityError, get_block_id, index_blocks


import re

TICKET_PATTERN = re.compile(r'\b([A-Z]{2,10}-[0-9]+)\b')


def extract_tickets(texts: List[str]) -> List[str]:
    """Extract unique Jira/linear ticket identifiers such as PAY-123 or PROJ-456."""
    tickets = set()
    for t in texts:
        matches = TICKET_PATTERN.findall(t)
        for m in matches:
            tickets.add(m)
    return sorted(list(tickets))


def format_pr_suffix(prs: List[Dict[str, Any]]) -> str:
    """Deterministically format PR suffix: 'PRs: #101, #102' or 'PRs: None'."""
    if not prs:
        return "PRs: None"
    pr_ids = sorted(list(set(str(p.get("id")) for p in prs if p.get("id") is not None)), key=lambda x: int(x) if x.isdigit() else x)
    if not pr_ids:
        return "PRs: None"
    pr_tags = [f"#{pid}" for pid in pr_ids]
    return f"PRs: {', '.join(pr_tags)}"


def synthesize_deterministic_summary(block: Dict[str, Any]) -> str:
    """Fallback deterministic summary when AI judgment is not provided."""
    cal_titles = block.get("calendar_titles", [])
    commits = block.get("commits", [])
    prs = block.get("prs", [])

    # Pure meeting block
    if not commits and not prs and (cal_titles or block.get("time_basis") == "scheduled"):
        text = "; ".join(cal_titles).strip() or "Calendar event"
        return text if text.endswith((".", "!", "?")) else f"{text}."

    # Block with commits / PRs
    summary_parts = []
    if cal_titles and cal_titles[0] not in ("Development", "Focus"):
        summary_parts.append(cal_titles[0])

    commit_msgs = [c.get("message", "").strip() for c in commits if c.get("message", "").strip()]
    pr_titles = [p.get("title", "").strip() for p in prs if p.get("title", "").strip()]

    combined = commit_msgs + pr_titles
    tickets = extract_tickets(combined)
    ticket_prefix = f"[{', '.join(tickets)}] " if tickets else ""

    if combined:
        first = combined[0]
        # Clean prefix if any (e.g. feat: fix: chore:)
        cleaned = first
        for prefix in ["feat:", "fix:", "chore:", "docs:", "refactor:", "test:"]:
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
        cleaned = cleaned.capitalize()
        if len(combined) > 1:
            summary_parts.append(f"{ticket_prefix}{cleaned} and related improvements")
        else:
            summary_parts.append(f"{ticket_prefix}{cleaned}")
    else:
        summary_parts.append(f"{ticket_prefix}Project development and focus tasks".strip())

    text = ". ".join(summary_parts)
    if not text.endswith("."):
        text += "."
    return text


class AIJudgmentError(BlockIdentityError):
    """Requested AI output cannot be safely mapped to the current candidate blocks."""


def load_ai_judgments(path):
    """An explicitly requested missing/invalid file must not silently become fallback."""
    if path is None:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AIJudgmentError("Cannot read requested AI output as valid JSON") from exc
    if not isinstance(data, list):
        raise AIJudgmentError("Requested AI output must be a JSON array")
    return data


def map_ai_judgments(block_by_id, judgments):
    """Prefer explicit IDs; support only exact, unambiguous legacy interval matches."""
    if judgments is None:
        return {}
    if not isinstance(judgments, list):
        raise AIJudgmentError("AI output must be a JSON array of keyed summaries")
    mapped = {}
    dates = {block["date"] for block in block_by_id.values()}
    for item in judgments:
        if not isinstance(item, dict) or not isinstance(item.get("description"), str) or not item["description"].strip():
            raise AIJudgmentError("Each AI summary requires an object with a nonempty description")
        if "block_id" in item:
            key = item["block_id"]
            if not isinstance(key, str) or key not in block_by_id:
                raise AIJudgmentError("Unknown or stale AI block_id")
        else:
            interval = item.get("block")
            if not isinstance(interval, dict) or "start" not in interval or "end" not in interval:
                raise AIJudgmentError("AI summaries require block_id or explicit legacy block boundaries; positional output is unsupported")
            if "date" in item:
                date = item["date"]
            elif len(dates) == 1:
                date = next(iter(dates))
            else:
                raise AIJudgmentError("Date-less legacy summaries require a single target day")
            key = get_block_id(date, interval["start"], interval["end"])
            if key not in block_by_id:
                raise AIJudgmentError("Legacy AI interval does not match a current block")
        block = block_by_id[key]
        if "date" in item and item["date"] != block["date"]:
            raise AIJudgmentError("AI date conflicts with its block_id")
        if "block" in item:
            interval = item["block"]
            if (not isinstance(interval, dict) or interval.get("start") != block["start_time"]
                    or interval.get("end") != block["end_time"]):
                raise AIJudgmentError("AI boundaries conflict with their block_id")
        if key in mapped:
            raise AIJudgmentError("Duplicate AI summary for the same block")
        mapped[key] = item
    return mapped


def build_entries(
    blocks: List[Dict[str, Any]],
    ai_judgments: Optional[List[Dict[str, Any]]] = None
) -> List[Dict[str, Any]]:
    entries = []

    block_by_id = index_blocks(blocks)
    ai_by_key = map_ai_judgments(block_by_id, ai_judgments)

    for key, b in block_by_id.items():
        date_str = b.get("date", "")
        start_time = b.get("start_time", "")
        end_time = b.get("end_time", "")

        # Resolve topic summary
        topic_summary = ""
        ai_match = ai_by_key.get(key)
        if ai_match and ai_match.get("description"):
            topic_summary = ai_match["description"].strip()
            if not topic_summary.endswith("."):
                topic_summary += "."
        else:
            topic_summary = synthesize_deterministic_summary(b)

        # Append inline PR list exactly once at the end
        pr_suffix = format_pr_suffix(b.get("prs", []))
        full_description = f"{topic_summary} {pr_suffix}"

        entry_record = {
            "block_id": key,
            "summary_source": "ai" if ai_match else "fallback",
            **({"time_basis": b["time_basis"]} if "time_basis" in b else {}),
            **({"estimation_reason": b["estimation_reason"]} if "estimation_reason" in b else {}),
            "entry": {
                "date": date_str,
                "start": start_time,
                "end": end_time,
                "duration_minutes": b.get("duration_minutes", 0),
                "description": full_description
            },
            "sources": {
                "calendar": b.get("calendar_titles", []),
                "commits": b.get("commits", []),
                "pull_requests": b.get("prs", [])
            }
        }
        entries.append(entry_record)

    return entries


def main():
    parser = argparse.ArgumentParser(description="Deterministically build final timesheet entries.")
    parser.add_argument("--blocks-file", "-b", type=str, required=True, help="Path to blocks JSON file")
    parser.add_argument("--ai-output", "-a", type=str, default=None, help="Optional path to AI judgment JSON file")
    parser.add_argument("--output", "-o", type=str, default=None, help="Output entries JSON file")

    args = parser.parse_args()

    b_path = Path(args.blocks_file)
    if not b_path.exists():
        print(f"Error: {args.blocks_file} not found.", file=sys.stderr)
        sys.exit(1)

    try:
        blocks = json.loads(b_path.read_text(encoding="utf-8"))
        entries = build_entries(blocks, load_ai_judgments(args.ai_output))
    except (BlockIdentityError, OSError, json.JSONDecodeError) as exc:
        print(f"AI/block validation failed: {exc}", file=sys.stderr)
        return 2
    out_json = json.dumps(entries, indent=2)

    if args.output and args.output != "-":
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(out_json, encoding="utf-8")
    else:
        print(out_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
