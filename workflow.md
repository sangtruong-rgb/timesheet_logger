# Daily timesheet workflow

The Python CLI performs deterministic work. AI only summarizes text in eligible
blocks and never computes time, attendance, PR suffixes or storage ownership.

| Step | Owner | Behavior |
| --- | --- | --- |
| Resolve | Script | Target date and named zone; CLI > profile > Asia/Ho_Chi_Minh; confirmed identities and repos |
| Collect | Script | Bounded Git author history, GitHub PR actions, paginated readonly Google Calendar; explicit source states |
| Gate | Script | Failed/unavailable source → INCOMPLETE draft and exit 2; no sample substitution; explicit fixtures → DEMO |
| Normalize | Script | Qualified identities, source schema, local-day conversion, dedup, retained invalid/unmatched timestamps |
| Blocks | Script | Daily Calendar clipping/overlap union, all-day context excluded, bounded activity clusters for estimated development, unassigned evidence retained |
| Prepare | Script | Deduplicated eligible text, ticket ID extraction only, exact byte limit, immutable snapshot and fingerprint/run ID; no final writes |
| Summarize | AI, optional | Keyed concise descriptions for provided blocks; omit PR references; do not attach unmatched evidence |
| Assemble | Script | Validate/rebuild same snapshot without recollection; keyed AI or per-block fallback; exactly one qualified PR suffix |
| Reconcile | Script | Replace generated set; preserve manual/exact overrides; reject conflicts/corrupt legacy files |
| Save | Script | Sorted writer locks, atomic file replacements and recoverable output bundle including attributed CSV when supplied |
| Usage | Script | Explicit run/session/window/IDs; cumulative per-run upsert; input/output/cache separately; actual usage or unknown |
| Audit | Human | Confirm attendance/actual durations and review unmatched evidence before treating proposal as worked time |

Use --phase prepare and --phase assemble with the same --snapshot. Single-pass
--phase run remains available for fallback. Full commands and setup live in
[README.md](README.md); installed invocation lives in [SKILL.md](SKILL.md).

## Policies

D01: keep the entire day's schedule, including future meetings, with **Theo lịch,
chưa xác nhận tham dự**. Scheduled/estimated time is proposed coverage, not measured
work. COMPLETE source collection does not complete attendance/assignment review.

D03: primary Calendar by default; selected IDs configurable; exclude cancelled and
self-declined; keep all-day as context; overlaps require human attendance review.
Calendar event identity/source/bounds survive into final JSON when provided.

D04: selected GitHub repos and confirmed personal accounts; actual authored openings,
submitted personal reviews, merges of authored/personally reviewed/personally merged
PRs. Preserve each actor/action timestamp and owner/repo identity. Pending reviews
and updatedAt do not establish personal work.

D05: generated daily set is replaced on successful rerun. Preserve explicit manual
and override ownership; exact override suppresses an automatic interval, conflicting
intervals block. Legacy rows without provenance require classification, not deletion.

D02 remains deferred. Hardcoded development windows: 09:00–12:00 / 13:30–17:30;
lunch subtraction 12:00–13:30. An explicit activity-cluster policy controls idle,
minimum and maximum development block lengths, but every inferred boundary still
requires review. Scheduled meetings remain whole during lunch/outside hours. No
BREAK/OT classification or configured working schedule.

## Token Budget

Initial aspiration for AI judgment text per normal working day: under 1,000 input
and 200 output tokens. These are targets, not observed results or guaranteed limits.
Actual marked skill-run totals include instructions, tool/context overhead and cache;
no fixed full-run budget is asserted until live Claude measurements establish a
baseline. Report input/output/cache and total input + output + cache under D06.
Payload size is separate: exact JSON bytes and bytes/4 heuristic, not exact tokens.
Default payload guard is 12,000 bytes including metadata. Overflow blocks synthesis
without dropping evidence; review/reduce the selected evidence deliberately or set
an explicit larger bound. Do not claim a daily total below 600 or a payload below 350.

Text is deduplicated, raw API metadata excluded from judgment, Calendar-only blocks
use deterministic titles, and scripts do date math/suffix formatting. Ticket IDs are
extracted; development activity is clustered by time, not automatically by ticket.
No automatic AI
cache exists. Validated supplied judgments may be reused explicitly with the same
frozen snapshot; a changed snapshot needs new judgment/review.

For Codex, [the optional runner and usage adapter](docs/codex-usage.md) measure one
fresh summary invocation from CLI events. Cached input is already included in
provider input and is partitioned into the CSV cache column; it is not added twice.
The original provider counts and measured scope remain in attribution notes. This
is separate from full Claude skill-run acceptance. The pipeline never invokes AI.

The Claude collector requires a marked run manifest, not an implicit ~/.claude scan.
Message IDs isolate relevant usage if other work occurred in the marked window.
Latest complete usage snapshot per identified message replaces repeats;
unidentifiable legacy records only deduplicate exact snapshots. All four counts
(input, output, cache-read, cache-creation) must be explicit. Sparse/invalid usage
in scope and malformed JSON block recording before writes; no missing value is
assumed zero and no partial-update merge is inferred. Raw streaming is unsupported.
See [R04 schema policy](docs/r04-usage-schema-validation.md). Run totals follow execution-start day; historical target
date remains separate. Daily reports sum distinct run records on that execution day.
Manual recording requires a stable run ID and cumulative totals labeled self-reported.
No available evidence means unknown, leaves CSV untouched and does not establish zero.

Usage available at assembly can participate in its output transaction. Complete-run
usage including later responses must be collected afterward; the standalone CLI
updates the same run cumulatively. Never invent markers/counts to make a report pass.

## Validation limits

Synthetic regression tests exercise pagination failures, midnight/DST, overlaps,
AI validation, locks/rollback and token schemas. Real GitHub/Calendar ordinary
empty/nonempty source audits are recorded separately under ignored data/audit/.
An installed bundle alone does not establish Claude skill discovery/execution or
actual transcript compatibility. V01 stays open until that acceptance is run.
