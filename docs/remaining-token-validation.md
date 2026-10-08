# Marked-run token usage

F22/F24/F26 and D06 are implemented; F25's parser/dedup correction is implemented
but its actual-Claude-transcript acceptance remains part of V01. No Claude CLI is
installed here, so synthetic JSONL is regression evidence, not measured live usage.
F27's token settings and F32's CSV storage portion are implemented in this group.

The collector requires an explicit run manifest (session file or exact session ID,
run ID, target date, aware start/end). It never automatically aggregates every
transcript. Bounds are [start,end); optional message IDs isolate selected messages
inside the window. A window can only represent the full skill run when the caller
marks that run accurately; concurrent unrelated messages require explicit IDs.
Selected-message totals are labeled accordingly, not claimed full-run totals.

Counts accept nonnegative integers/numeric digit strings. Supported schema is
`complete_usage_snapshot_v1`: input, output, cache-read and cache-creation counts
must all be explicit. Canonical names or the existing aliases are accepted only
when every component is present; conflicting aliases/containers are blocked.
Missing counts are unknown, never zero. A sparse record, unsupported usage object,
invalid count or raw streaming event inside the selected scope blocks recording
instead of silently removing evidence or publishing a partial total. No partial
snapshot merge is inferred. See [R04 schema policy](r04-usage-schema-validation.md).

Repeated message IDs use the latest timestamped complete snapshot, not a sum.
Conflicting snapshots at the same timestamp are blocked. Scope filtering happens
before validating counts, so unrelated usage outside the run/window/selected IDs
does not block an attributed run. Usage without a valid aware timestamp cannot be
scoped and is blocked. Malformed JSON also blocks because its scope is unknown;
non-usage control records are ignored. Old records lacking IDs only deduplicate
exact JSON snapshots; broader identity cannot be inferred. Missing selected IDs or
no attributed usage blocks recording. Explicit zero in all four fields is valid.

The 09/10 follow-up additionally checks conflicting older snapshots in every arrival
order: seeing a newer complete snapshot first cannot hide a same-timestamp conflict
among older records. Identical older duplicates remain valid and use the latest total.

Input/output/cache remain separate; cache combines read and creation. Total is
input + output + cache. This is a token-volume metric, not price-equivalent billing
or a tokenizer count for the payload. The exact payload byte size is reported
separately with an explicitly heuristic estimate.

Each CSV key is execution-start date + session/run ID. All messages in a marked
run, even across midnight, are recorded on its start date; target timesheet date
is retained separately in notes. Distinct runs aggregate; repeating a run replaces
its cumulative total. Manual records require a run ID and are labeled self-reported.
They do not establish measured transcript provenance.

Assemble invokes the collector when --usage-run-manifest is supplied; the run ID
must match the immutable snapshot. No usage manifest yields token_usage: unknown and leaves CSV untouched. An
explicit invalid/incomplete manifest or transcript blocks assembly before final
files/CSV are changed. Collecting after the last skill response is also supported
via the standalone collector; it can include usage unavailable during assembly.

CSV headers/rows/counts/duplicate identities are checked before replacement;
corrupt files remain for review. CSV updates use locks and atomic replacement.
Reporting uses these same CSV checks: duplicate rows or an attributed session/run
identity repeated on two execution dates block both daily totals and updates, rather
than silently doubling costs or retaining a corrupt history.
When usage accompanies assembly, CSV participates in the recoverable output bundle
and rollback, with all relevant directory locks acquired in canonical sorted order.
No-record calls neither initialize nor rewrite a CSV.

Validation: synthetic JSONL regression tests cover explicit attribution, selected
IDs, complete/repeated snapshots, sparse/invalid usage, scope filtering, execution
vs target dates, CSV preservation and pipeline transaction rollback. Real Claude
transcript acceptance remains V01; synthetic usage is not measured live evidence.
