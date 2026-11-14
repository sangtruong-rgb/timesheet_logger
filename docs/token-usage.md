# AI payload and token usage

How the compact AI request is built, bounded and measured.

New commit-based runs use AI payload v6 to group related adjacent work sessions in the
same measured summary call. Python first groups verified PR/ticket intervals,
then provides opaque `merge_candidates` to AI. The model may combine different
PRs or commits without PRs when their content supports a shared workflow or
deliverable. Related implementation, tests, reporting and integration can share a
session; merge-only jobs join related adjacent work. Unrelated objectives stay
separate. Python rejects gaps, meetings, different repositories/work types, altered
coverage and new groups over four hours. Confirmed-end tails remain separate.
Each accepted group gets a concise description and a script-generated union of
PR references; final JSON retains `source_block_ids` and original allocations.
Run `./bin/timesheet-steps show "$TS_RUN" grouping` after summary to review the
before/after rows. Start a fresh prepare run to use v6; older snapshots (including
v5's task-level grouping) retain their frozen payload and instructions. Without AI,
only deterministic PR/ticket grouping applies.

Payload v3 exports an audit envelope plus a compact `summary_request`. Text is stored
once and referenced by summary jobs. Pieces of one commit allocation split by
lunch/Calendar share one job and description, using the combined PR context of
those pieces. Different commit allocations keep separate jobs even when their text
matches. Python maps jobs back to the original block IDs and appends each block's
own PR references. Frozen v1/v2 payloads retain their original summary behavior.
New allocation IDs are fixed before assigning per-piece evidence, so a commit in
the first minute of the confirmed start cannot accidentally split a summary group.
Times, source evidence
and unassigned review stay in the snapshot. Calendar-only rows use deterministic
descriptions. No persistent judgment cache is implemented.

The runner writes `usage-attempt.json` independently of summary acceptance and a
per-invocation `attempt-token-usage.csv` when provider usage is verifiable. Invalid
summaries still retain their token cost; missing usage is unknown. Successful output
keeps a separate `usage-run.json` for assembly. Both receipts identify the same
invocation, so collecting them does not count its tokens twice. Benchmarks retain
an `attempts.json` ledger for failures/retries as well as successful comparisons.

`serialized_bytes` measures the full audit export; `model_payload_bytes` measures
the exact compact UTF-8 request. The bytes/4 estimate is a heuristic for the request,
not an exact tokenizer count. The default 12000-byte guard bounds this request,
overridable with --max-ai-input-bytes. Overflow blocks without dropping evidence.
Legacy snapshots retain their original full-export guard and remain readable.
Supplied judgments can be reused explicitly with the same snapshot.
See [workflow.md](../workflow.md) for token targets.

For measured Codex usage, use the [Codex runner instructions](codex-usage.md).
It records one isolated summary invocation. CSV input excludes cached input so
input + output + cache equals the provider total, without counting cache twice.
Original Codex input/output/cache counts are preserved in attribution notes.

For Claude, record actual usage with a run manifest; no implicit whole-directory aggregation:

```json
{"run_id":"SNAPSHOT-RUN-ID","target_date":"2026-10-07","session_file":"/path/session.jsonl",
 "started_at":"2026-10-07T09:00:00+07:00","ended_at":"2026-10-07T09:05:00+07:00",
 "message_ids":["EXACT-USAGE-MESSAGE-ID"]}
```

```bash
python3 scripts/collect_token_usage.py --run-manifest data/audit/my-run/usage-run.json \
  --config config/user-config.json --csv-path data/audit/my-run/token-usage.csv
```

Pass --usage-run-manifest and --token-csv-path to assemble to record already available
usage together with timesheets. To include later final responses, record afterward.
A marked window must accurately isolate the skill; use explicit IDs when unrelated
messages share it. Selected-message scope is labeled accordingly. Repeated message
snapshots use the latest complete usage snapshot; exact unidentifiable snapshots
are deduplicated. Input, output, cache-read and cache-creation must all be explicit;
missing counts never become zero. In-scope incomplete/invalid usage, conflicting
snapshots or malformed JSON block recording and preserve existing files. Raw
streaming events are unsupported; no partial-update merge is inferred. See the
[R04 schema policy](r04-usage-schema-validation.md). Real transcript
compatibility still needs V01 acceptance on an installed Claude Code environment.

CSV retains input/output/cache and total including cache (D06). Usage follows execution
start day, with target timesheet day separately recorded; same run cumulative totals
replace, distinct runs aggregate. Manual --record-usage requires --run-id and is labeled
self-reported. Missing usage is unknown and leaves CSV unchanged. Corrupt CSV blocks
updates rather than discarding prior records.
