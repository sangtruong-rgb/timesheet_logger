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

Counts accept nonnegative integers/numeric digit strings. Null, negative, boolean
and fractional values are rejected per line without discarding valid lines.
Repeated message IDs use the latest timestamped usage snapshot, not a sum. Old
records lacking IDs only deduplicate exact JSON snapshots; broader identity cannot
be inferred. Missing selected IDs or no attributed usage blocks recording. A valid
explicit zero usage record is different from absence of evidence.

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
must match the immutable snapshot. Missing evidence yields token_usage: unknown
and leaves CSV untouched. Collecting after the last skill response is also supported
via the standalone collector; it can include usage unavailable during assembly.

CSV headers/rows/counts/duplicate identities are checked before replacement;
corrupt files remain for review. CSV updates use locks and atomic replacement.
When usage accompanies assembly, CSV participates in the recoverable output bundle
and rollback, with all relevant directory locks acquired in canonical sorted order.
No-record calls neither initialize nor rewrite a CSV.

Validation: 393 tests pass, including 19 new tests for attribution, selected IDs,
updated/repeated snapshots, malformed lines, cross-midnight execution vs target
attribution, cumulative reruns/multiple runs, CSV validation/atomic failures and
pipeline+CSV transaction rollback. All JSONL in these tests is synthetic.
