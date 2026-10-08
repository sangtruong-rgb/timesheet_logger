---
name: personal-timesheet
description: Build and optionally submit a daily work log from verified GitHub and Google Calendar activity in the timesheet_logger repository. Use when the user asks to check, generate, audit, or log work for a date, including requests with multiple confirmed work windows.
---

# Personal Timesheet

Run the repository's deterministic pipeline and use Codex only to summarize its small AI payload. Treat generated time as proposed unless the source measures attendance or duration.

## Short invocation

`$personal-timesheet 09:00` is a complete request: the clock is the user's
confirmed work start for today in the configured timezone. A supplied target date
overrides today. Select `commit_intervals`, collect live configured GitHub and
Google Calendar sources, run the measured Codex summary when eligible, and assemble
a preview in the unique audit directory. No Gradion write is authorized by this
shorthand. Report measured summary usage, or SKIPPED when no AI block is eligible.

`$personal-timesheet 8:00-12:00, 1h30-4:00` is also a complete preview request.
Pass the range text unchanged as one `--work-windows` argument; Python resolves
it to 08:00–12:00 and 13:30–16:00. Colon and `h` clocks and AM/PM are accepted.
Unpadded low hours may mean afternoon when needed to follow the prior boundary;
padded HH:MM is always 24-hour time. Explicit windows replace profile hours and
breaks for this date; gaps contribute no time, and Calendar rows are clipped to
the windows with excluded evidence retained for review. The last end is confirmed,
so include the closing tail. Show the canonical windows in the preview. Do not
change the profile. Invalid windows fail before collecting sources; ask only for
clarification of the rejected input. The dedicated `$personal-timesheet-windows`
skill supports the same workflow.

Proceed without reconfirming the supplied start, today's date, the configured
sources, or preview mode. With no start, ask only "Hôm nay bạn bắt đầu làm lúc
mấy giờ?" (use the target date if supplied). For an invalid or ambiguous clock,
ask for clarification rather than guessing. An omitted end means stop at the last
commit; do not ask for an end or mid-session breaks just to complete the preview.
Explicit instructions such as another date, a finishing time, or a request to
publish override these defaults and still use the publishing rules below.

If a problem requires user input, finish independent checks first, then ask one
concise question naming the blocker and the missing fact or required action.
Reuse facts already supplied. Diagnose recoverable failures before asking; never
ask for credential/token contents. Source failures still follow the bounded retry
and INCOMPLETE rules below. Attendance questions are needed for publishing, not
for showing a scheduled, unconfirmed preview.

## Resolve the run

Use the active execution environment for source collection. The repository
launcher checks Codex login, GitHub authentication and Calendar dependencies.

1. Set `TS_ROOT` to `git rev-parse --show-toplevel` and quote every path because the repository path may contain spaces.
2. Resolve the target date in the configured timezone, defaulting to today only when the request omits a date.
3. Read `config/user-config.json` without printing private configuration. Use its confirmed identities, repositories, timezone, Calendar IDs, and credential paths.
4. Use Python 3.11+ from the repository `.venv` when available. It must have `requirements-calendar.txt` installed.
5. Preserve existing files and edits. Put every new artifact for one run under one unique `data/audit/company-antigravity-<timestamp>/` directory.
6. When the request supplies windows, set `TS_WORK_WINDOWS` to the supplied
   comma-separated text and `TS_HOURS_ARGS=(--work-windows "$TS_WORK_WINDOWS")`.
   Do not also pass start/end flags or ask for a start already supplied by a window.
   Otherwise, for `commit_intervals`, use the user's confirmed start for this target date as
   `TS_WORK_START`. Ask for it only when absent; never assume 09:00 or reuse another
   day's hours. Pass `--work-start "$TS_WORK_START"` when preparing. If the user
   supplies a confirmed finishing time, also pass `--work-end HH:MM` (or `24:00`);
   otherwise stop at the last commit and report the uncounted tail. Do not ask about
   mid-session breaks. Daily confirmations are frozen in the snapshot; changing
   them requires a new prepare run, not assemble flags. Set
   `TS_HOURS_ARGS=(--work-start "$TS_WORK_START")` and append
   `TS_HOURS_ARGS+=(--work-end "$TS_WORK_END")` only when supplied.

## Prepare and summarize

Live collection needs outbound network access and, on macOS, access to the GitHub
credential store and Google OAuth token. These read-only source calls are authorized
by the request. Follow the active environment's execution permissions.

Run prepare with live sources:

```bash
"$TS_PYTHON" "$TS_ROOT/scripts/run_pipeline.py" --phase prepare \
  --config "$TS_ROOT/config/user-config.json" --date "$TS_DATE" \
  "${TS_HOURS_ARGS[@]}" \
  --timezone Asia/Ho_Chi_Minh \
  --snapshot "$TS_RUN/activity.json" \
  --export-ai-input "$TS_RUN/ai-input.json" \
  --output-dir "$TS_RUN/timesheets"
```

Require every requested source to report `success/live`. Diagnose a recoverable
transport or credential-store failure, preserve the failed run directory, and
retry at most once in a new unique directory after addressing its cause within
available permissions. If any live source still fails, retain its diagnostic and
draft, report `INCOMPLETE`, and stop dependent work. Never substitute a fixture,
sample, historical export, or older snapshot.

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

- Never present commit/PR allocations as measured continuous work. Preserve `estimated` labels.
- Under the accepted `commit_intervals` policy, allocate confirmed start → first
  commit, then commit → commit, subtracting frozen configured breaks (default
  12:00–13:30) and Calendar coverage. With explicit daily windows, exclude gaps
  outside those windows instead of profile breaks, and clip Calendar to the windows.
  This explicitly assumes continuous work between boundaries; it does not measure
  task duration. A commit allocation with 1–19 work minutes after exclusions merges
  into the previous commit allocation, preserving all commit/PR evidence; consecutive
  short allocations accumulate backward. Keep the first allocation when no predecessor
  exists, zero-work allocations, 20 minutes or more and confirmed-end tails separate.
  Decide merging before splitting around lunch/Calendar; never fill excluded time or
  pad a short allocation to 20 minutes. New snapshots freeze this rule; existing
  snapshots retain their original intervals. There is no 90-minute cap or mid-session break.
  The closing commit describes all split pieces of that interval and may occur
  outside a piece. New payloads use one shared topic description for pieces of the
  same allocation, combining PR context while preserving each row's own PR suffix,
  evidence and hours. Different allocations keep separate descriptions; frozen
  older payloads retain their original behavior. PR actions add context without
  adding time. An accepted policy
  plus confirmed daily hours does not require another per-block boundary approval.
- Treat `inferred_activity_boundaries` as review-required. Report the clustered intervals and do not publish them until the user confirms or overrides their start/end times.
- Do not attach unassigned activity to a block or invent its duration.
- Calendar status `confirmed` means the event exists, not that the user attended. Treat `self_response_status: needsAction`, `tentative`, or a missing self response as attendance unconfirmed.
- A direct statement from the user that they attended is valid confirmation for the named interval.
- Do not publish future scheduled meetings as attended. Keep them as `Theo lịch, chưa xác nhận tham dự` unless the user later confirms attendance.
- Configurable profile hours, breaks, weekdays, holidays and overtime windows
  are supported; see `docs/work-schedule.md`. Explicit daily windows override
  profile hours/breaks for that date. Automatic BREAK/OT billing labels remain
  unsupported; do not infer those classifications.

## Publish to Gradion

Only publish when the user asks to log, submit, or publish work. A direct request such as “log today's work” authorizes non-conflicting entries supported by the current run; ask only for missing facts such as attendance or classification.

Before publishing, read [references/gradion.md](references/gradion.md). List existing entries for the target date, skip exact existing intervals, and stop on any partial overlap or conflicting entry. Publish one non-overlapping interval at a time, retain sanitized responses in `TS_RUN`, then list the date again and report every resulting entry ID and total duration.

If the user asks only to check, generate, preview, or audit, do not call a Gradion write tool.

## Report

Report the date and timezone, source mode/status/counts, snapshot run ID, proposed or submitted intervals, estimated/scheduled basis, attendance state, unassigned review count, measured Codex input/output/cached/total counts and scope when available, Gradion entry IDs when published, and artifact paths. Never print credentials, OAuth files, bearer tokens, or full private configuration.

For provider-specific count semantics and evidence requirements, follow `docs/codex-usage.md` and `docs/r04-usage-schema-validation.md`; missing usage fields mean usage is pending, never zero.
