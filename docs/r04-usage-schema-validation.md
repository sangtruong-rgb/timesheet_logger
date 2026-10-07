# R04 — explicit usage schema and incomplete evidence

The collector accepts `complete_usage_snapshot_v1`: a timestamped JSONL snapshot
with all four counts explicitly present. It does not infer missing values:

| Component | Canonical field | Supported alias |
| --- | --- | --- |
| Input | input_tokens | prompt_tokens |
| Output | output_tokens | completion_tokens |
| Cache read | cache_read_input_tokens | cache_read |
| Cache creation | cache_creation_input_tokens | cache_creation |

Counts can be nonnegative integers or ASCII digit strings. Explicit zero is valid;
missing, null, boolean, negative or fractional counts are not. Simultaneous aliases
must agree. `usage`, `message.usage`, `response.usage`, and a flat `model_usage`
object are supported locations; conflicting containers are rejected. Extra fields
do not contribute to totals. Input/output/cache remain separate in CSV; cache is
read + creation, and total is input + output + cache. Notes record the schema.

Within an explicit run window (and optional selected message IDs), complete
snapshots for the same message use the latest timestamp, not a sum. Equal-time
snapshots must agree. Any incomplete/unsupported/invalid usage record in scope
blocks recording, even if another snapshot for that message is complete. This
conservative policy avoids assuming what a sparse update means.

Anthropic documents cumulative usage in streaming `message_delta` events, plus
`message_start` and `message_stop` lifecycle events. That API contract does not
establish the format of a particular Claude Code transcript. Raw `message_start`,
`message_delta` and `stream_event` records are therefore unsupported here, even
if an initial streaming record includes all counts. A verified stream adapter
would need to associate events with the message and establish final completion.
Use a complete final message snapshot; do not fill missing cache fields with zero.
Source: [Anthropic streaming documentation](https://platform.claude.com/docs/en/build-with-claude/streaming).

Scope filtering precedes count validation. Unrelated records outside the window or
explicit selected IDs do not contaminate the run. Usage with an invalid/missing
timestamp cannot be safely scoped and blocks. Malformed JSON also blocks; ordinary
non-usage control records are ignored. Legacy records without message IDs retain
the exact-record hash fallback; it cannot infer a shared identity between updates.

When explicitly requested evidence fails validation, standalone collection exits
2 before CSV writes; assembly exits 2 before timesheet/manifest/AI-export/CSV
writes. Previously recorded bytes remain unchanged. Without a usage manifest,
assembly can succeed with `token_usage.status = unknown`; this does not establish
zero tokens. No automatic partial-total CSV row is produced.

Regression tests use synthetic JSONL and deliberate incomplete evidence. CLI and
pipeline preservation tests run real Python subprocesses with actual OS
`CLAUDE_DIR` and `TIMESHEET_TOKEN_CSV`, isolated files and no environment/API mocks.
These tests do not establish actual Claude token usage. F25/V01 acceptance still
requires an explicitly attributed real Claude Code run and its transcript.
