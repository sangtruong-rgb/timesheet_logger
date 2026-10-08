---
name: personal-timesheet
description: Build and optionally submit a daily work log from verified GitHub and Google Calendar activity in the timesheet_logger repository. Use when the user asks to check, generate, audit, or log work for a date.
---

# Personal Timesheet

Run the repository's deterministic pipeline and use Codex only to summarize its small AI payload. Treat generated time as proposed unless the source measures attendance or duration.

## Resolve the run

1. Set `TS_ROOT` to `git rev-parse --show-toplevel` and quote every path because the repository path may contain spaces.
2. Resolve the target date in the configured timezone, defaulting to today only when the request omits a date.
3. Read `config/user-config.json` without printing private configuration. Use its confirmed identities, repositories, timezone, Calendar IDs, and credential paths.
4. Use Python 3.11+ from the repository `.venv` when available. It must have `requirements-calendar.txt` installed.
5. Preserve existing files and edits. Put every new artifact for one run under one unique `data/audit/company-antigravity-<timestamp>/` directory.

## Prepare and summarize

Run prepare with live sources:

```bash
"$TS_PYTHON" "$TS_ROOT/scripts/run_pipeline.py" --phase prepare \
  --config "$TS_ROOT/config/user-config.json" --date "$TS_DATE" \
  --timezone Asia/Ho_Chi_Minh \
  --snapshot "$TS_RUN/activity.json" \
  --export-ai-input "$TS_RUN/ai-input.json" \
  --output-dir "$TS_RUN/timesheets"
```

Require every requested source to report `success/live`. If any live source fails, retain its diagnostic and draft, report `INCOMPLETE`, and stop dependent work. Never substitute a fixture, sample, historical export, or older snapshot.

When `ai-input.json` has eligible blocks, run one isolated Codex summary invocation so usage is measured from `turn.completed.usage`:

```bash
"$TS_PYTHON" "$TS_ROOT/scripts/run_codex_summary.py" \
  --snapshot "$TS_RUN/activity.json" \
  --run-dir "$TS_RUN/codex" \
  --codex "$(command -v codex)"
```

The runner sends only the compact frozen payload, validates every returned `block_id`, and writes `codex/ai-output.json`, `codex/events.jsonl`, and `codex/usage-run.json`. Do not separately summarize the blocks in the outer skill session. If there are no eligible blocks, skip the runner and assemble without AI output or a usage manifest.

Assemble the same immutable snapshot:

```bash
"$TS_PYTHON" "$TS_ROOT/scripts/run_pipeline.py" --phase assemble \
  --config "$TS_ROOT/config/user-config.json" --date "$TS_DATE" \
  --timezone Asia/Ho_Chi_Minh \
  --snapshot "$TS_RUN/activity.json" \
  --ai-output "$TS_RUN/codex/ai-output.json" \
  --usage-run-manifest "$TS_RUN/codex/usage-run.json" \
  --token-csv-path "$TS_RUN/token-usage.csv" \
  --output-dir "$TS_RUN/timesheets"
```

Omit all three AI/usage arguments when no block needs an AI summary. Do not collect sources again between prepare and assemble. The measured scope is the isolated Codex summary invocation, including its CLI context; it does not claim usage for the surrounding interactive skill session or Python pipeline.

## Review and attendance

- Never infer continuous work from isolated commit or PR timestamps. Preserve `estimated` labels.
- Do not attach unassigned activity to a block or invent its duration.
- Calendar status `confirmed` means the event exists, not that the user attended. Treat `self_response_status: needsAction`, `tentative`, or a missing self response as attendance unconfirmed.
- A direct statement from the user that they attended is valid confirmation for the named interval.
- Do not publish future scheduled meetings as attended. Keep them as `Theo lịch, chưa xác nhận tham dự` unless the user later confirms attendance.
- BREAK, overtime, and configurable working-hour policies remain unsupported; report rather than infer them.

## Publish to Gradion

Only publish when the user asks to log, submit, or publish work. A direct request such as “log today's work” authorizes non-conflicting entries supported by the current run; ask only for missing facts such as attendance or classification.

Before publishing, read [references/gradion.md](references/gradion.md). List existing entries for the target date, skip exact existing intervals, and stop on any partial overlap or conflicting entry. Publish one non-overlapping interval at a time, retain sanitized responses in `TS_RUN`, then list the date again and report every resulting entry ID and total duration.

If the user asks only to check, generate, preview, or audit, do not call a Gradion write tool.

## Report

Report the date and timezone, source mode/status/counts, snapshot run ID, proposed or submitted intervals, estimated/scheduled basis, attendance state, unassigned review count, measured Codex input/output/cached/total counts and scope when available, Gradion entry IDs when published, and artifact paths. Never print credentials, OAuth files, bearer tokens, or full private configuration.

For provider-specific count semantics and evidence requirements, follow `docs/codex-usage.md` and `docs/r04-usage-schema-validation.md`; missing usage fields mean usage is pending, never zero.
