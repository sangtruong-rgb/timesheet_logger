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

from collection_result import collection_result, source_metadata
from activity_settings import add_settings_arguments, settings_from_args


def run_source_collector(command, source, mode):
    """Keep source failures distinct from a successfully collected empty list."""
    response = subprocess.run(command, capture_output=True, text=True, check=False)
    if response.stderr:
        print(response.stderr.rstrip(), file=sys.stderr)
    try:
        result = json.loads(response.stdout)
        if (not isinstance(result, dict) or result.get("source") != source
                or result.get("mode") != mode
                or result.get("status") not in ("success", "unavailable", "error")
                or not isinstance(result.get("items"), list)
                or any(not isinstance(item, dict) for item in result["items"])
                or (result["status"] == "success" and response.returncode != 0)
                or (result["status"] != "success" and result["items"])):
            raise ValueError("Invalid collector outcome")
        return result
    except (ValueError, TypeError):
        return collection_result(source, mode, "error", reason="Collector returned an invalid result")


def save_activity_draft(date_str, normalized, collection, output_dir):
    """An incomplete run records evidence, never replaces a final timesheet."""
    draft_dir = Path(output_dir) / "drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    payload = {"date": date_str, "collection": collection, "activity": normalized}
    json_path = draft_dir / f"{date_str}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [f"# Activity draft — {date_str}", "",
             "> INCOMPLETE: a source is unavailable or failed. This is not a completed timesheet.", ""]
    for name, source in collection["sources"].items():
        lines.append(f"- {name}: {source['status']} ({source['mode']}, {source['count']} items)")
    lines.extend(["", "## Collected evidence", "", "```json",
                  json.dumps(normalized, indent=2), "```", ""])
    (draft_dir / f"{date_str}.md").write_text("\n".join(lines), encoding="utf-8")
    return json_path


def run():
    parser = argparse.ArgumentParser(description="Run the end-to-end timesheet pipeline.")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--repos", nargs="+", default=None, help="Repositories shared by Git and PR collection")
    add_settings_arguments(parser)
    parser.add_argument("--calendar-fixture", type=str, default=None, help="Explicit Calendar demo/test fixture")
    parser.add_argument("--prs-fixture", type=str, default=None, help="Explicit PR demo/test fixture")
    parser.add_argument("--ai-output", type=str, default=None, help="Pre-computed AI topic judgments JSON")
    parser.add_argument("--export-ai-input", type=str, default=None, help="Path to write the minimal AI payload")
    parser.add_argument("--output-dir", type=str, default="data/timesheets", help="Timesheet output directory")

    args = parser.parse_args()
    try:
        selected = settings_from_args(args)
        date_str = args.date or datetime.datetime.now(selected["timezone"]).date().isoformat()
        datetime.date.fromisoformat(date_str)
    except (ValueError, OSError, KeyError) as exc:
        parser.error(str(exc))
    scripts_dir = Path(__file__).resolve().parent
    common = ["--timezone", selected["timezone_name"], "--repos", *selected["repos"]]
    if args.config:
        common += ["--config", args.config]
    for key, flag in (("github_users", "--github-users"), ("names", "--authors"), ("emails", "--author-emails")):
        if selected["identity"][key]:
            common += [flag, *selected["identity"][key]]
    if selected["use_git_credentials"]:
        common.append("--use-git-credentials")

    # Step 1: Collect Git commits
    print(f">> [1/6] Collecting Git commits for {date_str}...")
    git_cmd = [sys.executable, str(scripts_dir / "get_git_activity.py"), "--date", date_str, "--envelope", *common]
    git_result = run_source_collector(git_cmd, "git", "live")
    commits_data = git_result["items"]

    # Step 2: Collect PRs
    print(f">> [2/6] Collecting PR activity for {date_str}...")
    pr_cmd = [sys.executable, str(scripts_dir / "get_pr_activity.py"), "--date", date_str, *common]
    if args.prs_fixture:
        pr_cmd += ["--fixture", args.prs_fixture]
    pr_result = run_source_collector(pr_cmd, "github", "fixture" if args.prs_fixture is not None else "live")

    # Step 3: Collect Calendar events
    print(f">> [3/6] Collecting Calendar events for {date_str}...")
    cal_cmd = [sys.executable, str(scripts_dir / "get_calendar_activity.py"), "--date", date_str,
               "--timezone", selected["timezone_name"]]
    if args.calendar_fixture:
        cal_cmd += ["--fixture", args.calendar_fixture]
    cal_result = run_source_collector(cal_cmd, "google_calendar", "fixture" if args.calendar_fixture is not None else "live")

    # Step 4: Normalize
    print(">> [4/6] Normalizing data and eliminating redundancy...")
    from normalize_activity import normalize_all
    normalized = normalize_all(date_str, commits_data, pr_result["items"], cal_result["items"], selected["timezone_name"])
    source_results = {"git": git_result, "pull_requests": pr_result, "calendar": cal_result}
    incomplete = any(result["status"] != "success" for result in source_results.values())
    demo = any(result["mode"] == "fixture" for result in source_results.values())
    collection = {
        "status": "incomplete" if incomplete else "demo" if demo else "complete",
        "sources": {name: source_metadata(result) for name, result in source_results.items()},
        "identity": selected["identity"],
        "repositories": selected["repos"],
        "timezone": selected["timezone_name"],
    }
    for name, source in collection["sources"].items():
        print(f"   {name}: {source['status']} ({source['mode']}, {source['count']} items)")
    if incomplete:
        draft = save_activity_draft(date_str, normalized, collection, args.output_dir)
        print(f"\n INCOMPLETE: review source setup/errors. Activity draft: {draft}")
        print(" Final timesheets, AI input, and token records were not written.")
        return 2

    output_dir = Path(args.output_dir) / "demo" if demo else Path(args.output_dir)

    # Step 5: Build time blocks
    from build_time_blocks import build_time_blocks
    blocks = build_time_blocks(normalized)

    # Step 6: Prepare minimal AI input
    from prepare_ai_input import prepare_all_blocks
    ai_payload = prepare_all_blocks(blocks)

    ai_payload_json = json.dumps(ai_payload, indent=2)
    if args.export_ai_input:
        ai_path = Path(args.export_ai_input)
        if demo:
            ai_path = ai_path.parent / "demo" / ai_path.name
        ai_path.parent.mkdir(parents=True, exist_ok=True)
        ai_path.write_text(ai_payload_json, encoding="utf-8")
        print(f"   -> AI payload written to {ai_path}")

    # Step 7: Build entries
    from build_timesheet import build_entries
    ai_judgments = None
    if args.ai_output and Path(args.ai_output).exists():
        ai_judgments = json.loads(Path(args.ai_output).read_text(encoding="utf-8"))

    entries = build_entries(blocks, ai_judgments)
    for entry in entries:
        entry["collection"] = collection

    # Step 8: Save idempotently
    print(">> [5/6] Saving timesheet idempotently...")
    from save_timesheet import save_timesheet
    save_result = save_timesheet(entries, str(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"{date_str}.collection.json"
    manifest_path.write_text(json.dumps({"date": date_str, **collection}, indent=2), encoding="utf-8")

    # Step 9: Token usage tracking
    print(">> [6/6] Checking token tracking...")
    from collect_token_usage import update_csv
    if not demo:
        update_csv(Path("data/token-usage.csv"), [])

    print("\n DEMO completed — explicitly selected fixtures; output isolated under demo/."
          if demo else "\n Pipeline run successfully completed!")
    print(f" Collection manifest: {manifest_path}")
    if "dates" in save_result and date_str in save_result["dates"]:
        info = save_result["dates"][date_str]
        print(f" Timesheet JSON: {info['json_path']}")
        print(f" Timesheet Markdown: {info['md_path']}")
        print(f" Total Entries: {info['total_entries']} (Inserted: {info['inserted']}, Updated: {info['updated']})")
    return 0


if __name__ == "__main__":
    sys.exit(run())
