# Measured Codex summary usage

The optional `run_codex_summary.py` runner calls the installed, authenticated Codex
CLI once. `run_pipeline.py` remains deterministic and never launches an AI itself.
No separate API key is required when the CLI already has working saved login.

## Standalone CLI setup on macOS/Linux

Install a standalone CLI so terminal execution does not depend on a VS Code
extension directory. Version 0.161.0 is the version tested for compact summaries, not a latest-version
claim. Node/npm must already be available for this installation method:

```bash
npm install --global @openai/codex@0.161.0
codex --version
codex login status
```

If signed out, run `codex login` and complete the browser sign-in. An existing
ChatGPT login is reused; do not copy or print auth.json. Check `command -v codex`
from a regular terminal; an IDE can still put its bundled CLI first in PATH.
The summary runner accepts `--codex /absolute/path/to/codex` for an explicit binary.

From the repository root, create the local Python environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-calendar.txt
source .venv/bin/activate
python3 -m unittest discover -s tests
```

Keep the existing configured profile and readonly Calendar OAuth files local.
GitHub must be authenticated through the configured mechanism. The live pipeline
does not substitute fixtures when a source fails. No Claude installation or
transcript is needed for the Codex summary flow below.

Installation and login follow [OpenAI CLI setup](https://developers.openai.com/codex/cli/)
and [OpenAI authentication](https://developers.openai.com/codex/auth/).

## Run a Codex pipeline test

Run these commands from the bundle with the configured Python environment active.
Choose a new RUN directory for every fresh collection or AI invocation:

```bash
RUN="data/audit/codex-$(date +%Y%m%d-%H%M%S)"
# Replace date and morning start with the user's daily values.
python3 scripts/run_pipeline.py --phase prepare --date 2026-10-07 \
  --work-day-start 09:00 \
  --config config/user-config.json --snapshot "$RUN/activity.json" \
  --export-ai-input "$RUN/ai-input.json" --output-dir "$RUN/timesheets"

# Only after prepare exits 0. codex/ must not already exist.
python3 scripts/run_codex_summary.py --snapshot "$RUN/activity.json" \
  --run-dir "$RUN/codex"

# Only after the Codex runner exits 0.
python3 scripts/run_pipeline.py --phase assemble \
  --snapshot "$RUN/activity.json" --ai-output "$RUN/codex/ai-output.json" \
  --usage-run-manifest "$RUN/codex/usage-run.json" \
  --token-csv-path "$RUN/token-usage.csv" --output-dir "$RUN/timesheets"
```

Work-log descriptions are generated in English for NORMAL and OT entries. Both
summary strategies translate non-English evidence while retaining ticket keys
and proper names. Without AI, English templates describe the available evidence
or scheduled calendar activity; original titles/messages remain in `sources`.
Calendar attendance remains unconfirmed. Existing saved logs are not rewritten.

The default `compact` runner sends a text dictionary and summary jobs. Payload v3
uses one job for the pieces of a commit allocation split by lunch/Calendar, combining
their PR titles into shared context. Each piece receives the same topic description
and its own script-generated PR suffix. Different allocations keep separate jobs
even when their text matches. Frozen v1/v2 payloads retain their original semantic
deduplication. The runner requests job IDs and maps the validated response back to
every eligible block; canonical `ai-output.json` keeps block IDs. Assembly also shares
deterministic fallback descriptions within a v3 group and rejects conflicting AI
descriptions for its pieces.

Snapshot v4 assigns the group identity before splitting and before per-piece
timestamp assignment. This keeps a start-minute commit from separating otherwise
shared descriptions. V1-v3 snapshots reproduce their previous allocation behavior.
New pipeline snapshots use v5 to freeze the configured work schedule as well.
explicit `--work-windows` requests use v6 to freeze all confirmed daily windows.
V7 freezes OT observations and the daily decision; a pending decision blocks the
summary invocation before it writes artifacts or calls a model. V8 records the approved commit-hour default and allows summary without a reply;
v7 pending rules remain unchanged. V1–v7 and their recorded usage remain readable. See [schedule policy](work-schedule.md).

It uses a fresh, ephemeral, read-only CLI invocation without user config/rules,
from the isolated run directory. A narrow `model_instructions_file` replaces coding
instructions; project documents and host skill discovery are skipped. Shell,
apps/plugins, browser/computer/image tools and delegation are disabled for this
invocation, using features supported by tested CLI 0.161.0. Web search is disabled.
These overrides do not edit the user's global settings. Strict configuration fails
on unsupported settings rather than silently assuming the same context. CLI context
still contributes to provider input; usage is not the request's byte heuristic.
The runner defaults to reasoning `low`; `--model` and `--reasoning-effort` are explicit
overrides. Model availability depends on the authenticated account.
No eligible blocks means the runner exits 2 without calling AI; use deterministic
assembly without an AI output/usage manifest instead.

`events.jsonl` preserves CLI events; `response.json` preserves the final response;
`ai-output.json` contains validated keyed judgments. The success manifest records
the snapshot run ID, target date, exact thread identity, aware invocation boundaries,
successful process exit, payload fingerprint and hashes of snapshot/output/event log.
New `codex_exec_run_v2` manifests also retain the actual request, prompt, instructions,
schema, raw response, command, CLI version and requested model/reasoning. Attribution
rebuilds the request from the frozen snapshot and verifies the raw job-to-block
mapping against canonical judgments. Existing v1 manifests remain supported.
No session history is scanned. Hashes detect changes; they are not digital signatures.
Keep artifacts private in ignored data/audit; never publish authentication files.

The adapter accepts exactly one fresh thread and one completed turn. Missing counts,
invalid numbers, duplicate completion, extra thread/turn, failure/error, malformed
events, changed evidence or conflicting target/run/output blocks attribution. A
failed/timeout invocation retains diagnostics but publishes no success manifest.
Every invocation also retains a `codex_summary_attempt_v1` receipt in
`usage-attempt.json`. When the event log proves completed usage, request/snapshot
verification records its counts independently of summary acceptance, including
rejected descriptions and nonzero exits with a valid completed turn. A local
`attempt-token-usage.csv` records that invocation; missing or ambiguous usage stays
unknown and creates no count. Attempt receipts cannot replace the validated output
manifest during assembly. Success and attempt receipts share the same CSV identity,
so collecting both upserts one consumption record.
Unsupported schemas need a verified adapter, not fabricated values.

## Before/after benchmark

The benchmark validates both outputs and compares original source intervals,
evidence and metadata. With payload v5/v6, compact output may contain fewer rows
because session grouping is enabled. `output_rows` reports both counts;
`source_intervals_evidence_metadata_unchanged` verifies source equivalence while
`intervals_evidence_metadata_unchanged` indicates whether the final row layouts
also match. Grouping must conserve all original minutes and source evidence.

Use one complete frozen snapshot and pin the same available model for both strategies:

```bash
python3 scripts/benchmark_codex_summary.py --snapshot "$RUN/activity.json" \
  --run-dir "$RUN/benchmark" --model gpt-6.1-sol --codex /absolute/path/to/codex
```

`legacy` reproduces the former full audit prompt and coding context; `compact` uses
the new request and narrow context. Both use reasoning `low`. Each invokes AI once;
these are real token-consuming calls. Results include provider input/cached/output,
total input + output, prompt bytes and wall time. Structural checks preserve times,
source evidence and metadata; review descriptions for meaning. One pair does not
establish a statistical average. Cached input stays inside provider input when
reporting token reduction. `--resume` verifies completed evidence before reusing it
and creates a new retry directory for unfinished strategies, preserving failures.
An `attempts.json` ledger and the benchmark CSV include verified rejected/retry
invocations, even if a strategy aborts before the comparison completes. The report
separates successful comparison counts from all known attempt costs and lists
unknown attempts explicitly. Unknown costs are never claimed to be zero.
No timesheet is published by the benchmark. Its own usage CSV stays in its run directory.

Configuration reference: [Codex configuration](https://developers.openai.com/codex/config-reference/).

## Counts and scope

Codex `turn.completed.usage` reports input, cached input and output tokens. Cached
input is already part of input; reasoning is already part of output. To preserve
the existing CSV's non-overlapping columns:

| CSV field | Meaning for Codex |
| --- | --- |
| input_tokens | provider input_tokens minus cached_input_tokens |
| cache_tokens | provider cached_input_tokens |
| output_tokens | provider output_tokens, including reasoning |
| total_tokens | provider input_tokens plus provider output_tokens |

Notes preserve supported provider counts and explain the conversion. CLI 0.160.1
also emitted `cache_write_input_tokens` in actual tests (zero); the raw event log
retains it, but this adapter currently omits it from normalized provider_usage.
Nonzero cache-write semantics are not validated; do not claim full coverage of
that case or derive an exact bill. Daily totals separate
`codex_exec`, Claude `transcript`, and `self_reported` provenance. Execution-start
day is distinct from the timesheet target date. Reassembling the same snapshot,
output and manifest upserts one record without rerunning AI or duplicating totals.
A fresh Codex invocation has a different thread and is a separate consumption record.

The measured scope is **the Codex summary invocation**, including its CLI context,
not the surrounding chat, shell/Python pipeline, or a full Claude skill session.
These are provider-reported token counts, not proof of the final bill. This feature
does not complete the pending real-Claude F25/V01 acceptance.

Sources: [Codex non-interactive JSON events](https://developers.openai.com/codex/noninteractive/)
and [OpenAI usage category definitions](https://developers.openai.com/api/docs/guides/agents-api/observability/#understand-token-usage).
