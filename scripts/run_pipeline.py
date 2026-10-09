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
import os
import subprocess
import sys
from pathlib import Path

from collection_result import collection_result, source_metadata
from activity_settings import add_settings_arguments, settings_from_args
from calendar_settings import add_calendar_arguments, calendar_settings
from output_paths import validate_auxiliary_output, OutputPathError


def protected_input_paths(args):
    """Protect configured input/store paths without requiring valid source setup."""
    root = Path(__file__).resolve().parent.parent
    paths = [root / "token.json", root / "credentials.json", root / "data/token-usage.csv"]
    for name in ("snapshot", "ai_output", "config", "prs_fixture", "calendar_fixture",
                 "calendar_token", "calendar_credentials", "usage_run_manifest", "token_csv_path"):
        value = getattr(args, name, None)
        if value:
            paths.append(Path(value).expanduser() if name in ("calendar_token", "calendar_credentials", "token_csv_path") else value)
    for name in ("GOOGLE_CALENDAR_TOKEN", "GOOGLE_CALENDAR_CREDENTIALS", "TIMESHEET_TOKEN_CSV"):
        if os.environ.get(name):
            paths.append(Path(os.environ[name]).expanduser())
    profile = Path(args.config) if args.config else root / "config/user-config.json"
    paths.append(profile)
    try:
        data = json.loads(profile.read_text(encoding="utf-8"))
        for section, fields in (("calendar", ("token_path", "google_token_path", "credentials_path", "google_credentials_path")),
                                ("token_tracking", ("csv_path",))):
            settings = data.get(section, {})
            if isinstance(settings, dict):
                for field in fields:
                    value = settings.get(field)
                    if isinstance(value, str) and value.strip():
                        path = Path(value).expanduser()
                        paths.append(path if path.is_absolute() else profile.resolve().parent / path)
    except (OSError, ValueError, AttributeError):
        pass  # Assembly may intentionally ignore unavailable source configuration.
    manifest = getattr(args, "usage_run_manifest", None)
    if manifest:
        try:
            metadata = json.loads(Path(manifest).read_text(encoding="utf-8"))
            for key in ("session_file", "snapshot_file", "ai_output_file"):
                value = metadata.get(key)
                if isinstance(value, str) and value:
                    path = Path(value).expanduser()
                    paths.append(path if path.is_absolute() else Path(manifest).resolve().parent / path)
        except (OSError, ValueError, AttributeError):
            pass  # Token attribution validates malformed manifests separately.
    return paths


def check_ai_export(args, path):
    validate_auxiliary_output(path, protected_paths=protected_input_paths(args))


def run_source_collector(command, source, mode):
    """Keep source failures distinct from a successfully collected empty list."""
    try:
        response = subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return collection_result(source, mode, "error", reason=f"Collector could not complete ({type(exc).__name__})")
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


def save_activity_draft(date_str, normalized, collection, output_dir, storage_reason=None, proposed_entries=None,
                        ai_reason=None, ai_payload=None, normalization_issues=None):
    """A blocked run records evidence, never replaces a final timesheet."""
    draft_dir = Path(output_dir) / "drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    payload = {"date": date_str, "collection": collection, "activity": normalized}
    if normalization_issues:
        payload["activity_format"] = "raw"
        payload["normalization"] = {"status": "blocked", "issues": normalization_issues}
    if storage_reason:
        payload["reconciliation"] = {"status": "blocked", "reason": storage_reason}
        payload["proposed_entries"] = proposed_entries
    if ai_reason:
        payload["ai_validation"] = {"status": "error", "reason": ai_reason}
        payload["ai_input"] = ai_payload
    json_path = draft_dir / f"{date_str}.json"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    banner = ("> REVIEW REQUIRED: source normalization was blocked. Final files were preserved."
              if normalization_issues else "> REVIEW REQUIRED: daily reconciliation was blocked. Final files were preserved."
              if storage_reason else "> REVIEW REQUIRED: AI/block identity validation failed. Final files were preserved."
              if ai_reason else "> INCOMPLETE: a source is unavailable or failed. This is not a completed timesheet.")
    lines = [f"# Activity draft — {date_str}", "", banner, ""]
    if normalization_issues:
        lines.extend([json.dumps(normalization_issues, indent=2), ""])
        if collection["status"] == "incomplete":
            lines.extend(["> INCOMPLETE: a source is unavailable or failed.", ""])
    if storage_reason:
        lines.extend([storage_reason, ""])
    if ai_reason:
        lines.extend([ai_reason, ""])
    for name, source in collection["sources"].items():
        lines.append(f"- {name}: {source['status']} ({source['mode']}, {source['count']} items)")
    lines.extend(["", "## Collected evidence", "", "```json",
                  json.dumps(normalized, indent=2), "```", ""])
    (draft_dir / f"{date_str}.md").write_text("\n".join(lines), encoding="utf-8")
    return json_path


def _run():
    parser = argparse.ArgumentParser(description="Run the end-to-end timesheet pipeline.")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--phase", choices=("run", "prepare", "confirm-ot", "assemble"), default="run")
    parser.add_argument("--snapshot", help="Immutable snapshot output for prepare, input for assemble")
    parser.add_argument("--max-ai-input-bytes", type=int, default=12000)
    parser.add_argument("--repos", nargs="+", default=None, help="Repositories shared by Git and PR collection")
    parser.add_argument("--max-local-commits", type=int, default=10000)
    parser.add_argument("--max-remote-commits", type=int, default=10000)
    parser.add_argument("--work-start", help="Confirmed start HH:MM for the target day; selects commit_intervals")
    parser.add_argument("--work-end", help="Optional confirmed end HH:MM (or 24:00); requires --work-start")
    parser.add_argument('--work-day-start', help='Morning start; auto NORMAL until 12:00 and 13:30-18:30, with default OT')
    parser.add_argument('--work-windows', help='Confirmed daily intervals, e.g. "8:00-12:00, 1h30-4:00"; replaces profile breaks')
    parser.add_argument('--review-ot', action='store_true', help='Apply approved 60-minute OT windows ending at outside-main commits')
    parser.add_argument('--ot-windows', help='User-confirmed OT intervals; only with --phase confirm-ot')
    parser.add_argument('--decline-ot', action='store_true', help='User declined OT; only with --phase confirm-ot')
    parser.add_argument('--resolved-snapshot', help='New snapshot path for the OT answer; original evidence is preserved')
    add_settings_arguments(parser)
    add_calendar_arguments(parser)
    parser.add_argument("--calendar-fixture", type=str, default=None, help="Explicit Calendar demo/test fixture")
    parser.add_argument("--prs-fixture", type=str, default=None, help="Explicit PR demo/test fixture")
    parser.add_argument("--ai-output", type=str, default=None, help="Pre-computed AI topic judgments JSON")
    parser.add_argument("--export-ai-input", type=str, default=None, help="Path to write the minimal AI payload")
    parser.add_argument("--output-dir", type=str, default=str(Path(__file__).resolve().parent.parent / "data/timesheets"), help="Timesheet output directory")

    parser.add_argument("--usage-run-manifest", help="Explicit Claude transcript or Codex invocation evidence")
    parser.add_argument("--token-csv-path", help="Isolated token output; default from profile/environment/repo root")
    parser.add_argument("--claude-dir", help="Exact session lookup root (no global usage aggregation)")
    args = parser.parse_args()
    if args.work_day_start is not None:
        if (args.phase not in ('run', 'prepare') or args.work_start is not None
                or args.work_end is not None or args.work_windows is not None):
            parser.error('--work-day-start requires run/prepare without other work-hour arguments')
        try:
            from work_windows import default_work_day_windows
            windows = default_work_day_windows(args.work_day_start)
            args.work_windows = ', '.join(f"{window['start']}-{window['end']}" for window in windows)
            args.review_ot = True
        except ValueError as exc:
            parser.error(str(exc))
    if args.phase == 'confirm-ot':
        if (not args.snapshot or not args.resolved_snapshot or args.review_ot
                or args.work_windows is not None or args.work_start is not None or args.work_end is not None
                or args.ai_output or args.usage_run_manifest):
            parser.error('confirm-ot requires source/new snapshot paths and one OT decision, without fresh hours or AI output')
        try:
            check_ai_export(args, args.resolved_snapshot)
            if args.export_ai_input:
                check_ai_export(args, args.export_ai_input)
            from overtime import resolve_snapshot
            from work_windows import parse_work_windows
            if args.date is not None:
                from activity_snapshot import read_snapshot
                if args.date != read_snapshot(args.snapshot)['normalized']['date']:
                    raise ValueError('Requested date conflicts with the frozen snapshot')
            snapshot = resolve_snapshot(args.snapshot, args.resolved_snapshot,
                                        windows=parse_work_windows(args.ot_windows) if args.ot_windows is not None else None,
                                        decline=args.decline_ot, ai_export=args.export_ai_input)
            print(f" OT RESOLVED: {snapshot['normalized']['overtime_review']['status']}")
            print(f" PREPARED immutable snapshot: {args.resolved_snapshot}; Run ID: {snapshot['run_id']}")
            return 0
        except (ValueError, OSError) as exc:
            print(f' OT CONFIRMATION BLOCKED: {exc}', file=sys.stderr)
            return 2
    if args.ot_windows is not None or args.decline_ot or args.resolved_snapshot:
        parser.error('OT decision arguments require --phase confirm-ot')
    if args.review_ot and (args.phase == 'assemble' or args.work_windows is None):
        parser.error('--review-ot requires main --work-windows during prepare/run')
    if args.export_ai_input:
        try:
            check_ai_export(args, args.export_ai_input)
        except (OutputPathError, OSError) as exc:
            print(f" OUTPUT PATH BLOCKED: {exc}; final files were not written.", file=sys.stderr)
            return 2
    if args.phase == "assemble":
        if args.work_start is not None or args.work_end is not None or args.work_windows is not None:
            parser.error("assemble uses frozen confirmed hours; prepare a new snapshot to change them")
        if not args.snapshot:
            parser.error("assemble requires --snapshot; source collection is never repeated")
        try:
            from activity_snapshot import read_snapshot
            frozen = read_snapshot(args.snapshot)
            normalized, collection = frozen["normalized"], frozen["collection"]
            date_str = normalized["date"]
            if args.date is not None and args.date != date_str:
                raise ValueError("Requested date conflicts with the frozen snapshot")
            output = Path(args.output_dir) / "demo" if collection["status"] == "demo" else Path(args.output_dir)
            return assemble_activity(args, date_str, normalized, collection, output, frozen=frozen)
        except (ValueError, OSError) as exc:
            print(f" SNAPSHOT BLOCKED: {exc}", file=sys.stderr)
            return 2
    if args.phase == "prepare" and args.usage_run_manifest:
        parser.error("Record usage after synthesis with assemble or the token collector")
    if args.phase == "prepare" and args.ai_output:
        parser.error("prepare does not assemble AI output; use --phase assemble with the prepared snapshot")
    try:
        selected = settings_from_args(args)
        calendar_options = calendar_settings(args.config, args.calendar_token, args.calendar_credentials, args.calendar_ids)
        from block_settings import block_policy_settings, COMMIT_STRATEGY
        block_policy = block_policy_settings(args.config)
        from work_schedule import schedule_settings, schedule_bounds, local_clock
        work_schedule = schedule_settings(args.config)
        date_str = args.date or datetime.datetime.now(selected["timezone"]).date().isoformat()
        target_date = datetime.date.fromisoformat(date_str)
        if target_date.isoformat() != date_str:
            raise ValueError('Target date must be canonical YYYY-MM-DD')
        schedule_bounds({'work_schedule': work_schedule}, target_date, selected['timezone'])
        confirmation = None
        if args.work_windows is not None:
            if args.work_start is not None or args.work_end is not None:
                raise ValueError('--work-windows cannot be combined with --work-start or --work-end')
            from work_windows import parse_work_windows
            from commit_intervals import work_confirmation
            windows = parse_work_windows(args.work_windows)
            for window in windows:
                for value in window.values():
                    local_clock(target_date, value, selected['timezone'])
            confirmation = work_confirmation(date_str, windows[0]['start'], windows[-1]['end'], windows=windows)
            block_policy = {'strategy': COMMIT_STRATEGY}
        elif args.work_start is not None or args.work_end is not None or (block_policy or {}).get("strategy") == COMMIT_STRATEGY:
            from commit_intervals import work_confirmation
            confirmation = work_confirmation(date_str, args.work_start, args.work_end)
            for field in ('start', 'end'):
                if field in confirmation:
                    local_clock(target_date, confirmation[field], selected['timezone'])
            block_policy = {"strategy": COMMIT_STRATEGY}
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
    git_cmd += ["--max-local-commits", str(args.max_local_commits)]
    git_cmd += ["--max-remote-commits", str(args.max_remote_commits)]
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
    if args.config:
        cal_cmd += ["--config", args.config]
    cal_cmd += ["--calendar-token", calendar_options["token_path"], "--calendar-credentials", calendar_options["credentials_path"],
                "--calendar-ids", *calendar_options["calendar_ids"]]
    if args.calendar_fixture:
        cal_cmd += ["--fixture", args.calendar_fixture]
    cal_result = run_source_collector(cal_cmd, "google_calendar", "fixture" if args.calendar_fixture is not None else "live")

    # Step 4: Normalize
    print(">> [4/6] Normalizing data and eliminating redundancy...")
    source_results = {"git": git_result, "pull_requests": pr_result, "calendar": cal_result}
    incomplete = any(result["status"] != "success" for result in source_results.values())
    demo = any(result["mode"] == "fixture" for result in source_results.values())
    collection = {
        "status": "incomplete" if incomplete else "demo" if demo else "complete",
        "sources": {name: source_metadata(result) for name, result in source_results.items()},
        "identity": selected["identity"],
        "repositories": selected["repos"],
        "timezone": selected["timezone_name"],
        "work_schedule": work_schedule,
    }
    for name, source in collection["sources"].items():
        print(f"   {name}: {source['status']} ({source['mode']}, {source['count']} items)")
    output_dir = Path(args.output_dir) / "demo" if demo and not incomplete else Path(args.output_dir)
    from normalize_activity import normalize_all, ActivityNormalizationError
    try:
        normalized = normalize_all(date_str, commits_data, pr_result["items"], cal_result["items"], selected["timezone_name"])
        normalized['work_schedule'] = work_schedule
        if block_policy is not None:
            # Freeze the policy with the evidence so later assembly never depends
            # on mutable host configuration.
            normalized["block_policy"] = block_policy
        if confirmation is not None:
            normalized["work_confirmation"] = confirmation
        if args.review_ot:
            from overtime import initial_review
            normalized['overtime_review'] = initial_review(normalized)
            collection['overtime_review'] = normalized['overtime_review']
    except ActivityNormalizationError as exc:
        raw = {"date": date_str, "timezone": selected["timezone_name"], "commits": commits_data,
               "pull_requests": pr_result["items"], "calendar": cal_result["items"]}
        draft = save_activity_draft(date_str, raw, collection, output_dir, normalization_issues=exc.issues)
        print(f"\n NORMALIZATION BLOCKED: {exc}", file=sys.stderr)
        if incomplete:
            print(" INCOMPLETE: a source is unavailable or failed.")
        print(f" Raw evidence draft: {draft}")
        print(" Final timesheets, collection manifest, AI input, and token records were not written.")
        return 2
    if incomplete:
        draft = save_activity_draft(date_str, normalized, collection, args.output_dir)
        print(f"\n INCOMPLETE: review source setup/errors. Activity draft: {draft}")
        print(" Final timesheets, AI input, and token records were not written.")
        return 2

    return assemble_activity(args, date_str, normalized, collection, output_dir)


def assemble_activity(args, date_str, normalized, collection, output_dir, *, frozen=None):
    demo = collection["status"] == "demo"
    # Step 5: Build time blocks
    from build_time_blocks import build_time_blocks

    # Step 6: Prepare minimal AI input
    from prepare_ai_input import prepare_activity_input
    from block_identity import BlockIdentityError
    # Step 7: Build entries
    from build_timesheet import build_entries, load_ai_judgments
    ai_payload = frozen["ai_input"] if frozen else None
    unassigned_activity = frozen["unassigned_activity"] if frozen else []
    try:
        blocks = frozen["blocks"] if frozen else build_time_blocks(normalized, unassigned_activity=unassigned_activity)
        if not frozen:
            ai_payload = prepare_activity_input(blocks, unassigned_activity, args.max_ai_input_bytes)
        if args.phase == "prepare":
            from activity_snapshot import save_snapshot
            snapshot_path = Path(args.snapshot) if args.snapshot else Path(args.output_dir).parent / "runs" / f"{date_str}-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json"
            if demo:
                snapshot_path = snapshot_path.parent / "demo" / snapshot_path.name
            ai_export = Path(args.export_ai_input) if args.export_ai_input else None
            if ai_export and demo:
                ai_export = ai_export.parent / "demo" / ai_export.name
            if ai_export:
                check_ai_export(args, ai_export)
            snapshot = save_snapshot(snapshot_path, normalized, collection, blocks, unassigned_activity, ai_payload, ai_export)
            print(f" PREPARED immutable snapshot: {snapshot_path}")
            print(f" Run ID: {snapshot['run_id']}; no final timesheet or token file written.")
            if 'overtime_review' in normalized:
                from overtime import confirmation_question
                question = confirmation_question(normalized)
                if question:
                    print(f' OT_CONFIRMATION_REQUIRED: {question}')
                elif normalized['overtime_review']['status'] == 'defaulted':
                    hours = ', '.join(f"{item['start']}–{item['end']}" for item in normalized['overtime_review']['confirmed_windows'])
                    print(f' OT_DEFAULT_APPLIED: {hours}; estimated, approved by the standing 60-minute commit rule; no reply required')
            return 0
        from overtime import require_resolved
        require_resolved(normalized)
        from summary_request import commit_group_mapping
        entries = build_entries(blocks, load_ai_judgments(args.ai_output),
                                summary_groups=commit_group_mapping(ai_payload['blocks']))
    except BlockIdentityError as exc:
        draft = save_activity_draft(date_str, normalized, collection, output_dir,
                                    ai_reason=str(exc), ai_payload=ai_payload)
        print(f"\n AI VALIDATION BLOCKED: {exc}", file=sys.stderr)
        print(f" Activity/AI-input draft: {draft}")
        print(" Final timesheets, collection manifest, AI input, and token records were not written.")
        return 2
    token_records, token_csv = [], None
    collection = dict(collection)
    collection["token_usage"] = {"status": "unknown", "reason": "No explicit attributed usage supplied"}
    if args.usage_run_manifest:
        try:
            if demo: raise ValueError("DEMO usage is recorded separately, never into a live token store")
            from collect_token_usage import collect_run
            from token_settings import token_settings
            from activity_settings import resolve_timezone
            paths = token_settings(args.config, args.claude_dir, args.token_csv_path)
            usage_manifest = json.loads(Path(args.usage_run_manifest).read_text(encoding="utf-8"))
            if isinstance(usage_manifest, dict) and usage_manifest.get("provider") == "codex" and (not frozen or not args.ai_output):
                raise ValueError("Codex attribution requires assemble with a frozen snapshot and explicit AI output")
            record = collect_run(args.usage_run_manifest, resolve_timezone(normalized["timezone"], allow_legacy_offset=True),
                expected_target=date_str, expected_run=frozen["run_id"] if frozen else None,
                claude_dir=paths["claude_dir"], expected_ai_output=args.ai_output)
            token_records, token_csv = [record], paths["csv_path"]
            collection["token_usage"] = {"status": "attributed", "execution_date": record["date"],
                "run_identity": record["session_id"], **{key: record[key] for key in ("input_tokens", "output_tokens", "cache_tokens", "total_tokens")},
                "attribution": json.loads(record["notes"])}
        except (ValueError, OSError, TypeError) as exc:
            print(f" TOKEN ATTRIBUTION BLOCKED: {exc}; final files and token records preserved.", file=sys.stderr)
            return 2
    ai_payload_json = json.dumps(ai_payload, indent=2)
    for entry in entries:
        entry["collection"] = collection

    # Step 8: Save idempotently
    print(">> [5/6] Saving timesheet idempotently...")
    from save_timesheet import save_timesheet, TimesheetReconciliationError
    extra_files = {}
    if args.export_ai_input:
        ai_path = Path(args.export_ai_input)
        if demo:
            ai_path = ai_path.parent / "demo" / ai_path.name
        try:
            check_ai_export(args, ai_path)
        except (OutputPathError, OSError) as exc:
            print(f" OUTPUT PATH BLOCKED: {exc}; final files were not written.", file=sys.stderr)
            return 2
        extra_files[ai_path] = ai_payload_json
    try:
        save_result = save_timesheet(entries, str(output_dir), target_date=date_str,
                                     collection_status=collection["status"], calendar_context=normalized["calendar_context"],
                                     unassigned_activity=unassigned_activity, collection_manifest=collection, extra_files=extra_files,
                                     token_records=token_records, token_csv=token_csv)
    except TimesheetReconciliationError as exc:
        draft = save_activity_draft(date_str, normalized, collection, output_dir, str(exc), entries)
        print(f"\n RECONCILIATION BLOCKED: {exc}", file=sys.stderr)
        print(f" Activity/proposed-entry draft: {draft}")
        print(" Final timesheets, collection manifest, AI input, and token records were not written.")
        return 2
    manifest_path = output_dir / f"{date_str}.collection.json"
    # Step 9: Token usage tracking
    print(f">> [6/6] Checking token tracking for {date_str} ({normalized['timezone']})...")
    if token_records:
        r = token_records[0]
        print(f" Attributed usage: input={r['input_tokens']}, output={r['output_tokens']}, cache={r['cache_tokens']}, total={r['total_tokens']}; CSV: {token_csv}")
    else:
        print(" Token usage unknown: no explicit run usage supplied; token records preserved.")

    print("\n DEMO completed — explicitly selected fixtures; output isolated under demo/."
          if demo else "\n Pipeline run successfully completed!")
    print(f" Collection manifest: {manifest_path}")
    overlap_count = sum(bool(entry.get("calendar_overlap")) for entry in entries)
    if unassigned_activity:
        print(f" REVIEW REQUIRED: {len(unassigned_activity)} activity event(s) could not be assigned by timestamp; no duration inferred.")
    if overlap_count:
        print(f" REVIEW REQUIRED: {overlap_count} Calendar overlap interval(s) need attendance confirmation. Output is a proposal.")
    if "dates" in save_result and date_str in save_result["dates"]:
        info = save_result["dates"][date_str]
        print(f" Timesheet JSON: {info['json_path']}")
        print(f" Timesheet Markdown: {info['md_path']}")
        if "calendar_context_path" in info:
            print(f" Calendar context (not counted as work time): {info['calendar_context_path']}")
        if "activity_review_path" in info:
            print(f" Unassigned activity audit: {info['activity_review_path']}")
        print(f" Total Entries: {info['total_entries']} (Inserted: {info['inserted']}, Updated: {info['updated']}, "
              f"Removed: {info['removed']}, Manual preserved: {info['preserved_manual']}, Overridden: {info['overridden']})")
    return 0


def run():
    try:
        return _run()
    except (OSError, ValueError) as exc:
        print(f" Pipeline blocked ({type(exc).__name__}): {exc}. Review output/draft paths; no successful completion claimed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(run())
