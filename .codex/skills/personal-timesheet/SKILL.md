---
name: personal-timesheet
description: Build and optionally submit a daily work log from verified GitHub and Google Calendar activity in the timesheet_logger repository. Use when the user asks to check, generate, audit, or log work for a date, including requests with multiple confirmed work windows.
---

# Personal Timesheet

Run the repository's deterministic pipeline and use Codex only to summarize its small AI payload. Treat generated time as proposed unless the source measures attendance or duration.

Use English for all user-facing communication, including clarifying questions,
progress updates, explanations, errors and final reports, even when the request
is written in Vietnamese. Preserve original source evidence and proper names.

## Short invocation

If the user's request includes `OT confirmed` or `attendance confirmed`, read
[the confirmation rules](../personal-timesheet-confirmed/SKILL.md) once and apply
only the declarations supplied. For example, `$personal-timesheet 9:00, OT
confirmed, attendance confirmed` confirms both for the selected date. Separate
the confirmation phrases from the clock/window text before passing hours to
Python. These are user declarations, not automatic permission to publish.
Continue the shared workflow here without recursive skill loading or recollection.

`$personal-timesheet 09:00` is a complete request: the clock is the user's
confirmed morning start for today in the configured timezone. Use
`--work-day-start HH:MM`: Python creates start–12:00 and 13:30–18:30 as the
NORMAL windows and enables the approved commit-hour OT rule. For example, 08:30
means 08:30–12:00 plus five afternoon hours, 13:30–18:30. Show these expanded
windows in the preview. Development blocks require commit or PR evidence; leave
empty windows and unsupported closing tails blank. Never add generic development
or focus-time placeholders. Calendar rows remain separate; attendance confirmation
is independent. Supported development durations are estimates, not measured work.
A supplied date overrides today. Collect live sources, run the measured Codex
summary when eligible, and assemble in a unique audit directory. No Gradion write
is authorized by shorthand. Report measured summary usage, or SKIPPED when no AI
block is eligible. A start at or after noon requires explicit work windows.

`$personal-timesheet 8:00-12:00, 1h30-4:00` is also a complete preview request.
Pass the range text unchanged as one `--work-windows` argument; Python resolves
it to 08:00–12:00 and 13:30–16:00. Colon and `h` clocks and AM/PM are accepted.
Unpadded low hours may mean afternoon when needed to follow the prior boundary;
padded HH:MM is always 24-hour time. Explicit windows replace profile hours and
breaks for this date; gaps contribute no time, and Calendar rows are clipped to
the windows with excluded evidence retained for review. The last end bounds
allocation; include a closing tail only with commit or PR evidence. Show the canonical windows in the preview. Do not
change the profile. Invalid windows fail before collecting sources; ask only for
clarification of the rejected input. The dedicated `$personal-timesheet-windows`
skill supports the same workflow.

Proceed without reconfirming the supplied start, today's date, the configured
sources, or preview mode. With no start, ask only "What time did you start work
today?" (use the target date if supplied). For an invalid or ambiguous clock,
ask for clarification rather than guessing. When only a morning start is supplied,
use the approved noon / five-hour afternoon default; do not ask for an end or
mid-session breaks just to complete the preview.
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
   comma-separated text and
   `TS_HOURS_ARGS=(--work-windows "$TS_WORK_WINDOWS" --review-ot)`.
   Do not also pass start/end flags or ask for a start already supplied by a window.
   Otherwise, use the user's morning start for this target date as `TS_WORK_START`.
   Ask only when absent; never assume 09:00 or reuse another day's start.
   With only a start, set `TS_HOURS_ARGS=(--work-day-start "$TS_WORK_START")`.
   Python expands the main windows and enables OT; do not convert this request to
   plain `--work-start` or perform clock arithmetic in the skill. If the user gives
   an explicit end instead, use `--work-start` and `--work-end` for that custom
   request, or `--work-windows` plus `--review-ot` for explicit main windows with OT.
   Daily confirmations are frozen; changing main hours requires a new prepare run.

## Prepare and summarize

Live collection needs outbound network access and, on macOS, access to the GitHub
credential store and Google OAuth token. These read-only source calls are authorized
by the request. Follow the active environment's execution permissions.

Set `TS_SNAPSHOT="$TS_RUN/activity.json"` and
`TS_AI_INPUT="$TS_RUN/ai-input.json"`. Run prepare with live sources:

```bash
"$TS_PYTHON" "$TS_ROOT/scripts/run_pipeline.py" --phase prepare \
  --config "$TS_ROOT/config/user-config.json" --date "$TS_DATE" \
  "${TS_HOURS_ARGS[@]}" \
  --timezone Asia/Ho_Chi_Minh \
  --snapshot "$TS_SNAPSHOT" \
  --export-ai-input "$TS_AI_INPUT" \
  --output-dir "$TS_RUN/timesheets"
```

Require every requested source to report `success/live`. Diagnose a recoverable
transport or credential-store failure, preserve the failed run directory, and
retry at most once in a new unique directory after addressing its cause within
available permissions. If any live source still fails, retain its diagnostic and
draft, report `INCOMPLETE`, and stop dependent work. Never substitute a fixture,
sample, historical export, or older snapshot.

For explicit windows, `--review-ot` applies the approved default;
`--work-day-start` enables it automatically: 60 minutes
ending at each outside-main commit (minute precision), subtracting main coverage
and breaks, then merging overlapping OT windows. New range runs exclude the frozen
profile breaks (default 12:00–13:30); morning-start shorthand always excludes
12:00–13:30. Historical snapshots replay their recorded policy unchanged. Snapshot v8 freezes the rule and approval
basis; `defaulted` counts as approved by the standing user rule. Continue to
summary/assembly without asking for approval or waiting for a reply. Show the
estimated default OT intervals in the preview so the user can request changes.
PR/Calendar activity alone does not invent a commit-based hour. Calendar
attendance remains unconfirmed.

If the user explicitly requests changed OT hours or no OT, read
[the OT override procedure](references/overtime.md) and resolve a new snapshot
from the same frozen sources, updating `TS_SNAPSHOT`/`TS_AI_INPUT`. Never collect
again to record an override. If replaying an old v7 `pending` snapshot, follow
its original manual-hour rule; do not silently retrofit the new default.

When `TS_AI_INPUT` has eligible blocks, run one isolated Codex summary invocation so usage is measured from `turn.completed.usage`:

```bash
"$TS_PYTHON" "$TS_ROOT/scripts/run_codex_summary.py" \
  --snapshot "$TS_SNAPSHOT" \
  --run-dir "$TS_RUN/codex" \
  --codex "$(command -v codex)"
```

The runner sends only the compact frozen payload, validates every returned `block_id` and proposed group, and writes `codex/ai-output.json`, `codex/events.jsonl`, and `codex/usage-run.json`. Do not separately summarize the blocks in the outer skill session. If there are no eligible blocks, skip the runner and assemble without AI output or a usage manifest.

Assemble the same immutable snapshot:

```bash
"$TS_PYTHON" "$TS_ROOT/scripts/run_pipeline.py" --phase assemble \
  --config "$TS_ROOT/config/user-config.json" --date "$TS_DATE" \
  --timezone Asia/Ho_Chi_Minh \
  --snapshot "$TS_SNAPSHOT" \
  --ai-output "$TS_RUN/codex/ai-output.json" \
  --usage-run-manifest "$TS_RUN/codex/usage-run.json" \
  --token-csv-path "$TS_RUN/token-usage.csv" \
  --output-dir "$TS_RUN/timesheets"
```

Omit all three AI/usage arguments when no block needs an AI summary. Do not collect sources again between prepare and assemble. The measured scope is the isolated Codex summary invocation, including its CLI context; it does not claim usage for the surrounding interactive skill session or Python pipeline.

Write all work-log descriptions in English, including NORMAL and OT rows, even
when the user or source evidence uses Vietnamese. Preserve ticket keys and proper
names. Keep original source text for audit; do not translate or rewrite evidence.
The script fallback uses English evidence-based templates, not title translation.
Timesheet previews and final reports must also be in English, including table
headings, attendance/status labels, totals, review notes and token-usage notes.
Clarifying questions and discussion outside the report must also be in English.

## Review and attendance

- Never present commit/PR allocations as measured continuous work. Preserve `estimated` labels.
- Under the accepted `commit_intervals` policy, allocate confirmed start → first
  commit, then commit → commit, subtracting frozen configured breaks (default
  12:00–13:30) and Calendar coverage. With explicit daily windows, exclude gaps
  outside those windows instead of profile breaks, and clip Calendar to the windows.
  This explicitly assumes continuous work between boundaries; it does not measure
  task duration. During prepare, group adjacent development pieces by verified
  repository-qualified PR/ticket identity. Failed or ambiguous lookups do not
  establish shared PR identity. Snapshot v9 freezes this stage and its evidence.
  New AI payload v6 uses the same isolated summary call to group related work
  sessions, broader than an individual feature or PR. Prefer grouping related
  implementation, fixes, tests, reports and integration of a shared workflow or
  deliverable. Merge-only jobs join adjacent related work; do not split merely
  because PRs, components or commit types differ. Short duration, a common repo
  or PR absence alone is insufficient. Keep distinct objectives or uncertain work
  separate, without a
  target row count. The script accepts only consecutive groups inside supplied
  candidates: no crossing gaps, Calendar, repo or NORMAL/OT boundaries, no absorbing
  confirmed-end tails, and no new group over four hours. It preserves total minutes,
  source evidence and the union of PR references, appending the PR suffix itself.
  Use one short outcome-focused English sentence per session; add a second only
  if needed. Do not list every commit or merge as a separate task.
  Review `codex/grouping.json` or `timesheet-steps show "$TS_RUN" grouping` for
  before/after counts and source block IDs. Final JSON retains source allocations.
  Invalid grouping stops the run with usage retained. Without AI, keep deterministic
  PR/ticket grouping. Older payloads retain their original description/grouping
  behavior and instructions; a fresh prepare run is required to adopt v6. PR actions provide context
  without adding time. The closing commit may occur outside a split piece; it does
  not prove attendance. An accepted policy
  plus confirmed daily hours does not require another per-block boundary approval.
- Treat `inferred_activity_boundaries` as review-required. Report the clustered intervals and do not publish them until the user confirms or overrides their start/end times.
- Do not attach unassigned activity to a block or invent its duration.
- Calendar status `confirmed` means the event exists, not that the user attended. Treat `self_response_status: needsAction`, `tentative`, or a missing self response as attendance unconfirmed.
- A direct statement from the user that they attended is valid confirmation for the named interval.
- Do not publish future scheduled meetings as attended. Keep them as `Scheduled; attendance unconfirmed` unless the user later confirms attendance.
- Configurable profile hours, breaks, weekdays, holidays and overtime windows
  are supported; see `docs/work-schedule.md`. Explicit daily windows override
  profile hours/breaks for that date. Window requests label main rows NORMAL and
  approved default or user-overridden outside intervals OT, with separate totals. Calendar
  attendance is a separate fact. No BREAK rows or automatic billing mapping are
  added. Morning-start shorthand expands via `--work-day-start`; older snapshots
  and direct Python `--work-start` requests retain their previous flow.

## Publish to Gradion

Only publish when the user asks to log, submit, or publish work. A direct request such as “log today's work” authorizes non-conflicting entries supported by the current run; ask only for missing facts such as attendance or classification.

Before publishing, read [references/gradion.md](references/gradion.md). List existing entries for the target date, skip exact existing intervals, and stop on any partial overlap or conflicting entry. Publish one non-overlapping interval at a time, retain sanitized responses in `TS_RUN`, then list the date again and report every resulting entry ID and total duration.

If the user asks only to check, generate, preview, or audit, do not call a Gradion write tool.

## Report

Write the complete preview or submission report in English; do not translate its
attendance labels, table headings or usage notes into Vietnamese.

Report the date and timezone, source mode/status/counts, snapshot run ID, proposed or submitted intervals, estimated/scheduled basis, attendance state, unassigned review count, measured Codex input/output/cached/total counts and scope when available, Gradion entry IDs when published, and artifact paths. Never print credentials, OAuth files, bearer tokens, or full private configuration.

For provider-specific count semantics and evidence requirements, follow `docs/codex-usage.md` and `docs/r04-usage-schema-validation.md`; missing usage fields mean usage is pending, never zero.
