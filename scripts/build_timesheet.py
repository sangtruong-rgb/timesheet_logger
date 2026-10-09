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
from activity_review import unpack_activity_snapshot


import re

from activity_text import extract_tickets


def format_pr_suffix(prs: List[Dict[str, Any]]) -> str:
    """Deterministically format PR suffix: 'PRs: #101, #102' or 'PRs: None'."""
    if not prs:
        return "PRs: None"
    references = sorted({(p.get("repository", ""), p["id"]) for p in prs if p.get("id") is not None},
                        key=lambda value: (int(value[1]), value[0]))
    if not references:
        return "PRs: None"
    ambiguous = {pid for _, pid in references if sum(other == pid for _, other in references) > 1}
    pr_tags = [f"{repo or '(unknown repository)'}#{pid}" if pid in ambiguous else f"#{pid}" for repo, pid in references]
    return f"PRs: {', '.join(pr_tags)}"


def synthesize_deterministic_summary(block: Dict[str, Any]) -> str:
    """English fallback without guessing translations of untrusted source titles.

    Detailed translated summaries belong to the AI stage. Original titles/messages
    remain in sources; this path reports only the available evidence and schedule.
    """
    cal_titles = block.get("calendar_titles", [])
    commits = block.get("commits", [])
    prs = block.get("prs", [])

    if block.get("calendar_overlap"):
        return "Overlapping calendar events; attendance confirmation required."
    if not commits and not prs and (cal_titles or block.get("time_basis") == "scheduled"):
        return "Scheduled calendar activity; attendance unconfirmed."

    texts = [c.get("message", "") for c in commits] + [p.get("title", "") for p in prs]
    tickets = extract_tickets(texts)
    ticket_prefix = f"[{', '.join(tickets)}] " if tickets else ""
    evidence = []
    if commits:
        evidence.append(f"{len(commits)} recorded commit{'s' if len(commits) != 1 else ''}")
    # Multiple PR actions may reference the same PR. Count distinct references.
    references = {(p.get("repository", ""), p["id"]) for p in prs if p.get("id") is not None}
    if references:
        evidence.append(f"{len(references)} pull request{'s' if len(references) != 1 else ''}")
    if evidence:
        return f"{ticket_prefix}Development activity based on {' and '.join(evidence)}."
    return f"{ticket_prefix}Project development and focus tasks."


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
        if re.search(r"\bPRs\s*:|#[0-9]+\b", item["description"], re.IGNORECASE):
            raise AIJudgmentError("AI summaries must omit PR references and the script-owned PRs suffix")
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


def shared_group_descriptions(block_by_id, ai_by_key, groups):
    """Reuse one topic per allocation; keep each row's source lists and PR suffix."""
    from summary_request import commit_summary_group_id
    if groups is None:
        return {}
    if not isinstance(groups, dict):
        raise AIJudgmentError('Summary groups must be a keyed mapping')
    shared = {}
    for group, keys in groups.items():
        if not isinstance(keys, list) or not keys:
            raise AIJudgmentError('Summary group requires block IDs')
        seen = set()
        for key in keys:
            if (not isinstance(key, str) or key not in block_by_id or key in shared
                    or key in seen
                    or commit_summary_group_id(block_by_id[key]) != group):
                raise AIJudgmentError('Summary group conflicts with candidate allocations')
            seen.add(key)
        matches = [ai_by_key[key] for key in keys if key in ai_by_key]
        if matches:
            descriptions = {m['description'].strip().rstrip('.') for m in matches}
            if len(descriptions) != 1:
                raise AIJudgmentError('Pieces of one commit allocation require one shared AI description')
            description, from_ai = matches[0]['description'].strip(), True
        else:
            commits = []
            for key in keys:
                for commit in block_by_id[key].get('commits', []):
                    if commit not in commits:
                        commits.append(commit)
            combined = {**block_by_id[keys[0]],
                        'commits': commits,
                        'prs': [p for key in keys for p in block_by_id[key].get('prs', [])]}
            description, from_ai = synthesize_deterministic_summary(combined), False
        for key in keys:
            shared[key] = (description, from_ai)
    return shared


def build_entries(
    blocks: List[Dict[str, Any]],
    ai_judgments: Optional[List[Dict[str, Any]]] = None,
    *, summary_groups=None
) -> List[Dict[str, Any]]:
    entries = []

    block_by_id = index_blocks(blocks)
    ai_by_key = map_ai_judgments(block_by_id, ai_judgments)
    shared = shared_group_descriptions(block_by_id, ai_by_key, summary_groups)

    for key, b in block_by_id.items():
        date_str = b.get("date", "")
        start_time = b.get("start_time", "")
        end_time = b.get("end_time", "")
        if "duration_minutes" not in b:
            raise AIJudgmentError("Candidate blocks require an explicit duration")
        for field in ("commits", "prs", "calendar_events", "calendar_titles"):
            values = b.get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str if field == "calendar_titles" else dict) for v in values):
                raise AIJudgmentError("Candidate source fields must contain correctly typed arrays")
        if 'work_schedule' in b:
            from work_schedule import validate_schedule
            validate_schedule(b['work_schedule'])
        from overtime import validate_classification
        validate_classification(b)

        # Resolve topic summary
        topic_summary = ""
        ai_match = ai_by_key.get(key)
        if key in shared and shared[key][1]:
            ai_match = {'description': shared[key][0]}
        if ai_match and ai_match.get("description"):
            topic_summary = ai_match["description"].strip()
            if not topic_summary.endswith("."):
                topic_summary += "."
            if b.get("calendar_overlap"):
                topic_summary = "Calendar overlap — attendance confirmation required. " + topic_summary
        else:
            topic_summary = shared[key][0] if key in shared else synthesize_deterministic_summary(b)
            topic_summary = re.sub(r"\bPRs\s*:.*", "", topic_summary, flags=re.IGNORECASE).strip()
            topic_summary = re.sub(r"#[0-9]+\b", "", topic_summary)
            topic_summary = " ".join(topic_summary.split()).strip() or "Activity recorded."

        # Append inline PR list exactly once at the end
        pr_suffix = format_pr_suffix(b.get("prs", []))
        full_description = f"{topic_summary} {pr_suffix}"

        entry_record = {
            "block_id": key,
            "summary_source": "ai" if ai_match else "fallback",
            **({"interval": b["interval"]} if "interval" in b else {}),
            **({"timezone": b["timezone"]} if "timezone" in b else {}),
            **({"time_basis": b["time_basis"]} if "time_basis" in b else {}),
            **({"attendance": "unconfirmed"} if b.get("time_basis") == "scheduled" else {}),
            **({"estimation_reason": b["estimation_reason"]} if "estimation_reason" in b else {}),
            **({"estimation_policy": b["estimation_policy"]} if "estimation_policy" in b else {}),
            **({"work_confirmation": b["work_confirmation"]} if "work_confirmation" in b else {}),
            **({"work_schedule": b["work_schedule"]} if "work_schedule" in b else {}),
            **({"work_type": b["work_type"], 'main_work_windows': b['main_work_windows']} if 'work_type' in b else {}),
            **({'overtime_confirmation': b['overtime_confirmation']} if 'overtime_confirmation' in b else {}),
            **({"allocation": b["allocation"]} if "allocation" in b else {}),
            **({"calendar_overlap": True} if b.get("calendar_overlap") else {}),
            **({"review": b["review"]} if b.get("review") else {}),
            "entry": {
                "date": date_str,
                "start": start_time,
                "end": end_time,
                "duration_minutes": b.get("duration_minutes", 0),
                "description": full_description
            },
            "sources": {
                "calendar": b.get("calendar_titles", []),
                **({"calendar_events": b["calendar_events"]} if "calendar_events" in b else {}),
                "commits": b.get("commits", []),
                "pull_requests": b.get("prs", [])
            }
        }
        entries.append(entry_record)

    from workstream_groups import merge_entries
    return merge_entries(blocks, entries, ai_by_key)


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
        data = json.loads(b_path.read_text(encoding="utf-8"))
        blocks, unassigned = unpack_activity_snapshot(data, "blocks")
        from prepare_ai_input import prepare_all_blocks
        from summary_request import commit_group_mapping
        version = 3
        if isinstance(data, dict) and 'ai_input' in data:
            if not isinstance(data['ai_input'], dict):
                raise AIJudgmentError('Invalid frozen AI input')
            version = data['ai_input'].get('payload_version', 1)
            if type(version) is not int or version not in (1, 2, 3, 4, 5, 6):
                raise AIJudgmentError('Unsupported frozen AI payload version')
        payloads = prepare_all_blocks(blocks, include_summary_groups=version in (3, 4))
        entries = build_entries(blocks, load_ai_judgments(args.ai_output),
                                summary_groups=commit_group_mapping(payloads))
    except (ValueError, OSError) as exc:
        print(f"AI/block validation failed: {exc}", file=sys.stderr)
        return 2
    out_json = json.dumps({"entries": entries, "unassigned_activity": unassigned}
                          if unassigned is not None else entries, indent=2)

    try:
        if args.output and args.output != "-":
            from atomic_storage import directory_lock, atomic_write
            out_p = Path(args.output)
            with directory_lock(out_p.parent):
                atomic_write(out_p, out_json)
        else:
            print(out_json)
    except (ValueError, OSError) as exc:
        print(f"Output blocked: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
