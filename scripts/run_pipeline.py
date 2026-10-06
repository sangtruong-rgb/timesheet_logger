#!/usr/bin/env python3
"""
run_pipeline.py - Orchestrator executing the deterministic personal timesheet pipeline.

Flow:
1. [Script] Determine date & timezone
2. [Script] Collect Git commits
3. [Script] Collect PR activity
4. [Script] Collect Calendar events
5. [Script] Normalize all sources & eliminate duplicates
6. [Script] Build candidate time blocks & associate activities
7. [Script] Prepare minimal AI payload
8. [AI / Script fallback] Synthesize topic summaries
9. [Script] Deterministically build timesheet entries & append PRs
10. [Script] Idempotently save entries (JSON + Markdown)
11. [Script] Record token usage
"""

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path


def run():
    parser = argparse.ArgumentParser(description="Run the end-to-end timesheet pipeline.")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--repos", nargs="+", default=["."], help="Repositories to scan for Git activity")
    parser.add_argument("--calendar-fixture", type=str, default=None, help="Calendar fixture path if credentials absent")
    parser.add_argument("--prs-fixture", type=str, default=None, help="PR fixture path if CLI/token absent")
    parser.add_argument("--ai-output", type=str, default=None, help="Pre-computed AI topic judgments JSON")
    parser.add_argument("--export-ai-input", type=str, default=None, help="Path to write the minimal AI payload")
    parser.add_argument("--output-dir", type=str, default="data/timesheets", help="Timesheet output directory")

    args = parser.parse_args()

    date_str = args.date or datetime.datetime.now().astimezone().date().isoformat()
    scripts_dir = Path(__file__).resolve().parent

    # Step 1: Collect Git commits
    print(f">> [1/6] Collecting Git commits for {date_str}...")
    git_cmd = [sys.executable, str(scripts_dir / "get_git_activity.py"), "--date", date_str, "--repos"] + args.repos
    res_git = subprocess.run(git_cmd, capture_output=True, text=True, check=True)
    commits_data = json.loads(res_git.stdout)

    # Step 2: Collect PRs
    print(f">> [2/6] Collecting PR activity for {date_str}...")
    pr_cmd = [sys.executable, str(scripts_dir / "get_pr_activity.py"), "--date", date_str]
    if args.prs_fixture:
        pr_cmd += ["--fixture", args.prs_fixture]
    res_pr = subprocess.run(pr_cmd, capture_output=True, text=True, check=True)
    prs_data = json.loads(res_pr.stdout)

    # Step 3: Collect Calendar events
    print(f">> [3/6] Collecting Calendar events for {date_str}...")
    cal_cmd = [sys.executable, str(scripts_dir / "get_calendar_activity.py"), "--date", date_str]
    if args.calendar_fixture:
        cal_cmd += ["--fixture", args.calendar_fixture]
    res_cal = subprocess.run(cal_cmd, capture_output=True, text=True, check=True)
    cal_data = json.loads(res_cal.stdout)

    # Step 4: Normalize
    print(">> [4/6] Normalizing data and eliminating redundancy...")
    from normalize_activity import normalize_all
    normalized = normalize_all(date_str, commits_data, prs_data, cal_data)

    # Step 5: Build time blocks
    from build_time_blocks import build_time_blocks
    blocks = build_time_blocks(normalized)

    # Step 6: Prepare minimal AI input
    from prepare_ai_input import prepare_all_blocks
    ai_payload = prepare_all_blocks(blocks)

    ai_payload_json = json.dumps(ai_payload, indent=2)
    if args.export_ai_input:
        Path(args.export_ai_input).write_text(ai_payload_json, encoding="utf-8")
        print(f"   -> AI payload written to {args.export_ai_input}")

    # Step 7: Build entries
    from build_timesheet import build_entries
    ai_judgments = None
    if args.ai_output and Path(args.ai_output).exists():
        ai_judgments = json.loads(Path(args.ai_output).read_text(encoding="utf-8"))

    entries = build_entries(blocks, ai_judgments)

    # Step 8: Save idempotently
    print(">> [5/6] Saving timesheet idempotently...")
    from save_timesheet import save_timesheet
    save_result = save_timesheet(entries, args.output_dir)

    # Step 9: Token usage tracking
    print(">> [6/6] Checking token tracking...")
    from collect_token_usage import update_csv
    update_csv(Path("data/token-usage.csv"), [])

    print("\n Pipeline run successfully completed!")
    if "dates" in save_result and date_str in save_result["dates"]:
        info = save_result["dates"][date_str]
        print(f" Timesheet JSON: {info['json_path']}")
        print(f" Timesheet Markdown: {info['md_path']}")
        print(f" Total Entries: {info['total_entries']} (Inserted: {info['inserted']}, Updated: {info['updated']})")


if __name__ == "__main__":
    run()
