#!/usr/bin/env python3
"""
collect_token_usage.py - Deterministic parser for Claude Code session transcripts.

Reads session transcripts (JSONL) from ~/.claude or specified directory.
Extracts:
- input_tokens
- output_tokens
- cache_tokens (cache_read + cache_creation)
- total_tokens
- session_id
- date

Aggregates daily runs and records them idempotently into data/token-usage.csv.
"""

import argparse
import csv
import datetime
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple


def get_local_date_str() -> str:
    return datetime.datetime.now().astimezone().date().isoformat()


def parse_transcript_line_usage(line_obj: Dict[str, Any]) -> Tuple[int, int, int]:
    """
    Defensively extract (input_tokens, output_tokens, cache_tokens) from a json object.
    Supports various Claude transcript schemas.
    """
    inp, out, cache = 0, 0, 0

    # Pattern A: nested in message/response usage
    usage = (
        line_obj.get("usage")
        or line_obj.get("message", {}).get("usage")
        or line_obj.get("response", {}).get("usage")
        or line_obj.get("model_usage")
    )

    if isinstance(usage, dict):
        inp += usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
        out += usage.get("output_tokens", 0) or usage.get("completion_tokens", 0)
        c_read = usage.get("cache_read_input_tokens", 0) or usage.get("cache_read", 0)
        c_create = usage.get("cache_creation_input_tokens", 0) or usage.get("cache_creation", 0)
        cache += (c_read + c_create)

    return inp, out, cache


def parse_session_file(file_path: Path, target_date_str: str) -> Optional[Dict[str, Any]]:
    """Parse a single JSONL session file."""
    try:
        mtime = datetime.datetime.fromtimestamp(file_path.stat().st_mtime).astimezone().date().isoformat()
        if mtime != target_date_str:
            # Check if internal timestamp matches date
            pass

        session_id = file_path.stem
        total_inp, total_out, total_cache = 0, 0, 0
        has_usage = False

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    obj = json.loads(line_str)
                    i, o, c = parse_transcript_line_usage(obj)
                    if i or o or c:
                        total_inp += i
                        total_out += o
                        total_cache += c
                        has_usage = True
                except json.JSONDecodeError:
                    continue

        if has_usage:
            return {
                "date": target_date_str,
                "session_id": session_id,
                "input_tokens": total_inp,
                "output_tokens": total_out,
                "cache_tokens": total_cache,
                "total_tokens": total_inp + total_out + total_cache,
                "notes": f"Scanned from {file_path.name}"
            }
    except Exception as e:
        print(f"Warning: Failed reading {file_path}: {e}", file=sys.stderr)
    return None


def find_transcripts(base_dir: Path) -> List[Path]:
    """Recursively search for .jsonl session files."""
    if not base_dir.exists():
        return []
    return list(base_dir.rglob("*.jsonl"))


def update_csv(csv_path: Path, new_records: List[Dict[str, Any]]):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "session_id", "input_tokens", "output_tokens", "cache_tokens", "total_tokens", "notes"]

    existing_rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_rows[(row.get("date", ""), row.get("session_id", ""))] = row

    for r in new_records:
        key = (r["date"], r["session_id"])
        existing_rows[key] = {
            "date": r["date"],
            "session_id": r["session_id"],
            "input_tokens": r["input_tokens"],
            "output_tokens": r["output_tokens"],
            "cache_tokens": r["cache_tokens"],
            "total_tokens": r["total_tokens"],
            "notes": r.get("notes", "")
        }

    # Write sorted by date and session_id
    sorted_rows = sorted(existing_rows.values(), key=lambda x: (x["date"], x["session_id"]))
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sorted_rows)


def main():
    parser = argparse.ArgumentParser(description="Collect and record Claude token usage.")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--claude-dir", type=str, default=os.path.expanduser("~/.claude"), help="Path to Claude root dir")
    parser.add_argument("--session-file", type=str, default=None, help="Direct path to session JSONL file")
    parser.add_argument("--csv-path", type=str, default="data/token-usage.csv", help="Target CSV output path")
    parser.add_argument("--record-usage", nargs=4, metavar=("SESSION_ID", "INPUT", "OUTPUT", "CACHE"),
                        help="Manually record usage from an execution run")

    args = parser.parse_args()

    target_date = args.date or get_local_date_str()
    csv_file = Path(args.csv_path)

    records = []

    # Case 1: Manual / Direct record argument
    if args.record_usage:
        sid, inp, out, cache = args.record_usage
        i_val = int(inp)
        o_val = int(out)
        c_val = int(cache)
        records.append({
            "date": target_date,
            "session_id": sid,
            "input_tokens": i_val,
            "output_tokens": o_val,
            "cache_tokens": c_val,
            "total_tokens": i_val + o_val + c_val,
            "notes": "Direct run recording"
        })
    # Case 2: Specific session file
    elif args.session_file:
        res = parse_session_file(Path(args.session_file), target_date)
        if res:
            records.append(res)
    # Case 3: Scan claude directory
    else:
        claude_path = Path(args.claude_dir)
        files = find_transcripts(claude_path)
        for f in files:
            res = parse_session_file(f, target_date)
            if res:
                records.append(res)

    if records:
        update_csv(csv_file, records)
        total_day_tokens = sum(r["total_tokens"] for r in records)
        print(f"Recorded {len(records)} session(s) to {csv_file}. Daily total tokens: {total_day_tokens}")
    else:
        # Check if CSV exists, if not initialize it with header
        if not csv_file.exists():
            update_csv(csv_file, [])
        print(f"No active session transcript found under {args.claude_dir} for date {target_date}. CSV initialized.")


if __name__ == "__main__":
    main()
