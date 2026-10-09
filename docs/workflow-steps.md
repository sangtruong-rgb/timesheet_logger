# Run and inspect each workflow stage

Use `bin/timesheet-steps` to run the existing pipeline in stages without an outer
Codex conversation. Only `summary` calls AI. Nothing here publishes to Gradion.
The wrapper uses the repository `.venv`; no `jq` or new dependencies are needed.

Run from the project root in one terminal session:

```bash
cd "/Users/sang.truong/timesheet logger"
./bin/personal-timesheet-codex --check
TS_RUN="data/audit/steps-$(date +%Y%m%d-%H%M%S)"
```

The check verifies CLI login, GitHub authentication and Calendar dependencies. It
does not validate the Calendar OAuth token against Google; source errors surface
during prepare. If needed, follow the existing [runtime setup](../README.md) and
Calendar authorization instructions. Existing credentials/configuration are reused.

## 1. Collect sources and build the frozen proposal (no AI)

Replace the date and example hours with your actual date and confirmed hours:

```bash
./bin/timesheet-steps prepare "$TS_RUN" --date 2026-10-09 --start 09:00
./bin/timesheet-steps show "$TS_RUN" sources
./bin/timesheet-steps show "$TS_RUN" normalized
./bin/timesheet-steps show "$TS_RUN" blocks
./bin/timesheet-steps show "$TS_RUN" review
```

`--date` defaults to today in the profile timezone. The current morning-start
policy uses 09:00–12:00 and 13:30–18:30, plus the approved commit-based OT default.
To supply explicit windows instead, use a fresh `TS_RUN` and replace prepare with:

```bash
./bin/timesheet-steps prepare "$TS_RUN" --date 2026-10-09 \
  --windows "09:00-12:00, 13:30-17:30"
```

Explicit windows also use the current approved OT rule. For the older custom
start/end flow without automatic full-day/OT expansion, use `--start 09:00 --end
17:30`. Do not combine `--windows` and start/end. See [schedule policy](work-schedule.md).

Prepare invokes collection, normalization and block building once, saving them
together in `activity.json`. The views expose each part of that same snapshot;
they do not repeat collection. `sources` shows source statuses and normalized
evidence, not raw provider HTTP responses. Failed collection leaves a draft under
`timesheets/drafts/` and a log, and exits nonzero. Stop dependent steps on failure.
Every prepare requires a new directory, so older outputs cannot be overwritten.

## 2. Inspect exactly what the compact AI step needs (no AI)

```bash
./bin/timesheet-steps show "$TS_RUN" ai-input
./bin/timesheet-steps show "$TS_RUN" request
./bin/timesheet-steps show "$TS_RUN" instructions
./bin/timesheet-steps show "$TS_RUN" prompt
```

`ai-input` is the audit envelope. `request` is the compact text dictionary and jobs
sent to the model; `instructions` is its summary instruction text. Before summary,
these views build a preview from the validated snapshot without writing to it.
After summary they show the actual recorded request/instructions. The runner also
sends an output schema, saved at `codex/output-schema.json`. Codex runtime context
can add input tokens beyond these files.
Historical runs without recorded request/instruction files are reported as unavailable;
the viewer never substitutes a current prompt for an old invocation's actual input.

## 3. Run AI and inspect its output and usage

This command consumes model tokens once. The default is the current compact runner;
optionally add `--model MODEL_ID` for a model available to your account.

```bash
./bin/timesheet-steps summary "$TS_RUN"
./bin/timesheet-steps show "$TS_RUN" response
./bin/timesheet-steps show "$TS_RUN" ai-output
./bin/timesheet-steps show "$TS_RUN" grouping
./bin/timesheet-steps show "$TS_RUN" schema
./bin/timesheet-steps show "$TS_RUN" events
./bin/timesheet-steps show "$TS_RUN" usage
```

No eligible blocks means `SKIPPED`; proceed directly to assemble and skip
`ai-output`/`events`. Missing usage is UNKNOWN, not zero. If a model invocation
fails, `show usage` can still show verified usage from the attempt receipt. Do not
erase its `codex/` directory to retry: it contains cost and diagnostic evidence.
The existing runner rejects reuse of that directory.

New prepare runs omit development blocks without commit or PR evidence, including
empty confirmed windows and unsupported time after the last commit. Calendar
entries remain separate. This rule is frozen in snapshot v10; use a fresh run
directory to apply it, since existing snapshots retain their historical output.

New commit-based runs use payload v6: the same AI call groups related work sessions
and writes a short outcome-focused description per session. Related implementation,
fixes, tests, reports and integration of one workflow can group across feature/PR
boundaries. Merge-only jobs join adjacent related work; a different objective or
uncertain relationship stays separate. Repository or short duration alone is not
enough to establish a shared session. Python supplies
`merge_candidates` and validates exact membership, unchanged minutes and source
PRs. Groups cannot cross breaks, meetings, repositories or NORMAL/OT boundaries;
confirmed-end tails remain separate. A new group cannot exceed Gradion's four-hour
entry limit. Uncertain or unrelated jobs stay separate, even if short or without PRs.
There is no target number of rows.

`show grouping` displays before/after counts, intervals, descriptions and
`source_block_ids`. Compare it with `show blocks` to inspect the original frozen
intervals. Final JSON retains the source allocations and evidence. Group selection
is an AI judgment: review the descriptions before publishing. Invalid proposals
stop assembly and retain their measured usage; they never silently fall back to a
different grouping. Old snapshots (including v5's narrower task-level rule) retain
their payload, instructions and summary behavior;
start a new prepare run to test the new behavior. `--without-ai` keeps only the
deterministic PR/ticket grouping.

Usage covers the isolated AI summary invocation, including its runtime context,
and excludes outer chats. Total = provider input + output; cached input is already
included. `show usage` validates the receipt against its snapshot and recorded files.
The success and attempt records refer to the same invocation; do not sum both.

## 4. Assemble and inspect the timesheet (no AI)

```bash
./bin/timesheet-steps assemble "$TS_RUN"
./bin/timesheet-steps show "$TS_RUN" timesheet
./bin/timesheet-steps show "$TS_RUN" usage
./bin/timesheet-steps show "$TS_RUN" logs
```

Assembly uses the frozen snapshot and validated AI output. If blocks need AI but
summary has not succeeded, it stops. For an explicit Python-only test, skip step 3
and use `assemble "$TS_RUN" --without-ai`; this uses fallback descriptions and
does not fabricate usage or overwrite existing usage files.

## Output map

| Output | Location under `TS_RUN` |
| --- | --- |
| Collection status, normalized evidence, blocks, review | `activity.json` |
| Audit AI payload | `ai-input.json` |
| Compact request and instructions | `codex/request.json`, `codex/instructions.txt` |
| Actual prompt and expected response schema | `codex/prompt.txt`, `codex/output-schema.json` |
| Raw model response / validated block descriptions | `codex/response.json`, `codex/ai-output.json` |
| Session grouping and original block IDs (v5/v6) | `codex/grouping.json` |
| Model events and invocation diagnostics | `codex/events.jsonl`, `codex/stderr.log` |
| Successful usage / attempt receipt | `codex/usage-run.json`, `codex/usage-attempt.json` |
| Attempt token CSV / assembled run token CSV | `codex/attempt-token-usage.csv`, `token-usage.csv` |
| Final local preview | `timesheets/YYYY-MM-DD.md`, `timesheets/YYYY-MM-DD.json` |
| Console output and process exit code for every stage | `logs/prepare-*.log`, `logs/summary-*.log`, `logs/assemble-*.log` |

To view an existing run, set `TS_RUN` to its directory and use `show`; this makes no
network/model calls and does not modify the run. Output may contain private work
evidence, so keep audit directories local and ignored by Git.
