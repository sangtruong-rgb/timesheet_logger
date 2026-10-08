# Daily timesheet workflow

The Python CLI performs deterministic work. AI only summarizes text in eligible
blocks and never computes time, attendance, PR suffixes or storage ownership.

| Step | Owner | Behavior |
| --- | --- | --- |
| Resolve | Script | Target date and named zone; CLI > profile > Asia/Ho_Chi_Minh; confirmed identities and repos |
| Collect | Script | Bounded Git author history, GitHub PR actions, paginated readonly Google Calendar; explicit source states |
| Gate | Script | Failed/unavailable source → INCOMPLETE draft and exit 2; no sample substitution; explicit fixtures → DEMO |
| Normalize | Script | Qualified identities, source schema, local-day conversion, dedup, retained invalid/unmatched timestamps |
| Blocks | Script | Confirmed daily start → closing commits, subtract lunch/Calendar; optional confirmed end; old snapshot policies preserved; unassigned evidence retained |
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

D02: `commit_intervals` requires a per-day confirmed `--work-start`, with optional
`--work-end`. Allocate start → first commit, then commit → commit; subtract configured
breaks (default 12:00–13:30) and scheduled Calendar coverage. No idle split,
padding to a minimum or maximum duration. Commit allocations with 1–19 net work
minutes merge into the previous allocation before lunch/Calendar splitting; preserve
all evidence and original allocation bounds. The first allocation, zero-work
allocations, 20 minutes or more and confirmed-end tails remain separate. No end confirmation means stop at the last
commit. Confirmations are frozen with the evidence and cannot be changed in assemble.
Commit boundaries are minute-floored; simultaneous commits share an interval. Each
closing commit provides completion context for all split pieces of its interval.
PRs attach by timestamp without creating time. A same-minute merge with a matching
qualified commit SHA attaches to its closing allocation, preserving the event time.
Development remains estimated;
continuous work between boundaries is an explicit allocation assumption. Scheduled
meetings remain whole during lunch/outside hours, attendance unconfirmed.
Snapshot v5 freezes work_schedule; v4 freezes allocation group IDs before piece-specific evidence assignment
and permits proven merge-commit associations. V3 freezes the previous under-20-minute
behavior; v2 retains under-30-minute merging
and v1 retains unmerged intervals.
Older activity-cluster/legacy snapshots retain their original behavior. Work schedule
configuration now supports regular hours, multiple breaks, weekdays, explicit holiday
dates and overtime windows. The default keeps 09:00–12:00 / 13:30–17:30 and all days;
no locale/holiday calendar is guessed. Evidence is required for inferred development
windows. Explicit daily confirmation permits work on nonworking days/outside regular
hours, still excluding configured breaks and Calendar. Breaks are excluded minutes,
not worked rows; automatic BREAK/OT classification is unsupported. See
[the policy and validation](docs/work-schedule.md).

## Token Budget

Initial aspiration for AI judgment text per normal working day: under 1,000 input
and 200 output tokens. These are targets, not observed results or guaranteed limits.
Actual marked skill-run totals include instructions, tool/context overhead and cache;
no fixed full-run budget is asserted until live Claude measurements establish a
baseline. Report input/output/cache and total input + output + cache under D06.
Payload size is separate: exact JSON bytes and bytes/4 heuristic, not exact tokens.
The v2/v3 payload guard bounds the exact compact model request at 12,000 UTF-8 bytes;
the larger audit envelope is measured separately. Legacy snapshots retain their
original full-export guard. Overflow blocks synthesis
without dropping evidence; review/reduce the selected evidence deliberately or set
an explicit larger bound. Do not claim a daily total below 600 or a payload below 350.

Text is deduplicated, raw API metadata excluded from judgment, Calendar-only blocks
use deterministic titles, and scripts do date math/suffix formatting. Ticket IDs are
extracted. Payload v3 gives pieces of one commit allocation split by lunch/Calendar
one summary job, combining their PR context. The topic stays the same across pieces;
each row retains its own PR suffix and source evidence. Different allocations keep
separate jobs. Frozen v1/v2 payloads retain their original semantic deduplication.
New allocation groups combine commit evidence across pieces even when a commit
in the start minute is timestamp-assigned to just one row.
This does not merge timesheet intervals or automatically cluster work by ticket.
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
