# Measured Codex summary usage

The optional `run_codex_summary.py` runner calls the installed, authenticated Codex
CLI once. `run_pipeline.py` remains deterministic and never launches an AI itself.
No separate API key is required when the CLI already has working saved login.
Run these commands from the bundle with the configured Python environment active.
Choose a new RUN directory for every fresh collection or AI invocation:

```bash
RUN="data/audit/codex-$(date +%Y%m%d-%H%M%S)"
python3 scripts/run_pipeline.py --phase prepare --date 2026-10-07 \
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

The runner sends only the frozen compact payload plus summary instructions, requests
schema-conforming output and validates every eligible block. It uses a fresh,
ephemeral, read-only CLI invocation without loading user config/rules. The prompt
asks the agent not to use tools. CLI instructions and tool definitions still add
context overhead; usage is not the payload's byte-derived token estimate.
No eligible blocks means the runner exits 2 without calling AI; use deterministic
assembly without an AI output/usage manifest instead.

`events.jsonl` preserves CLI events; `response.json` preserves the final response;
`ai-output.json` contains validated keyed judgments. The success manifest records
the snapshot run ID, target date, exact thread identity, aware invocation boundaries,
successful process exit, payload fingerprint and hashes of snapshot/output/event log.
No session history is scanned. Hashes detect changes; they are not digital signatures.
Keep artifacts private in ignored data/audit; never publish authentication files.

The adapter accepts exactly one fresh thread and one completed turn. Missing counts,
invalid numbers, duplicate completion, extra thread/turn, failure/error, malformed
events, changed evidence or conflicting target/run/output blocks attribution. A
failed/timeout invocation retains diagnostics but publishes no success manifest.
Usage can still have been consumed on a failed request; it is not recorded as zero.
Unsupported schemas need a verified adapter, not fabricated values.

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

Notes preserve the original provider counts and explain the conversion. No separate
cache-creation count is exposed here and none is invented. Daily totals separate
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
