# Daily timesheet workflow

The Python CLI performs deterministic work. AI summarizes eligible text and proposes related work-session groups. Python
validates every group and owns time, attendance labels, PR suffixes and storage.

| Step | Owner | Behavior |
| --- | --- | --- |
| Resolve | Script | Target date and named zone; CLI > profile > Asia/Ho_Chi_Minh; confirmed identities and repos |
| Collect | Script | Bounded Git author history, GitHub PR actions, paginated readonly Google Calendar; explicit source states |
| Gate | Script | Failed/unavailable source → INCOMPLETE draft and exit 2; no sample substitution; explicit fixtures → DEMO |
| Normalize | Script | Qualified identities, source schema, local-day conversion, dedup, retained invalid/unmatched timestamps |
| Blocks | Script | Confirmed daily start → closing commits, subtract lunch/Calendar; optional confirmed end; old snapshot policies preserved; unassigned evidence retained |
| Prepare | Script | Deduplicated eligible text, ticket ID extraction only, exact byte limit, immutable snapshot and fingerprint/run ID; no final writes |
| Summarize | AI, optional | Group related adjacent sessions and describe their outcome; omit PR references and unmatched evidence |
| Assemble | Script | Rebuild the same snapshot; validate group boundaries and coverage; retain source IDs/allocations and append one qualified PR suffix |
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

D02: `commit_intervals` requires confirmed daily hours: morning-start shorthand,
explicit windows, or a start with optional end. Allocate start → first commit,
then commit → commit; exclude configured breaks and Calendar coverage. Explicit
windows replace profile hours/breaks; their gaps contribute no time. An explicit
end includes an estimated closing tail; without it, stop at the last commit.
Confirmations and source intervals are frozen and cannot change during assembly.

New runs first group adjacent commit pieces by verified repository-qualified PR
identity (including identical complete PR sets), or by a unique ticket after a
successful empty PR lookup. A failed lookup is not proof of no PR. Demo/incomplete
collections never perform extra live PR association lookups. Short duration alone
does not imply related work. Merge actions provide integration context, not time
or proof that every feature in a PR was implemented in that interval.

Payload v6 proposes related work-session groups in the same isolated summary call.
Implementation, fixes, tests, reports and integration of a shared workflow can
belong together even across PRs. Distinct or uncertain objectives stay separate.
Python rejects groups crossing gaps, Calendar, repositories or NORMAL/OT boundaries,
absorbing confirmed-end tails, changing source coverage, or exceeding four hours.
The final row retains original block IDs, allocations and evidence. Descriptions
state the session outcome; Python appends all source PRs exactly once.

Morning-start shorthand expands to start–12:00 and 13:30–18:30. Explicit windows
with `--review-ot` and shorthand use the approved estimated hour ending at each
outside-main commit. Subtract main coverage, the date boundary and breaks; union
overlaps. Shorthand always excludes 12:00–13:30; range requests use the frozen
profile breaks. Explicit user OT overrides remain possible. Approval of estimated
OT does not confirm Calendar attendance. NORMAL and OT totals remain separate.

Snapshot v9 freezes PR grouping and associations. Older snapshots retain their
original allocation, short-commit merging and OT policies; old payloads and usage
receipts retain their instructions. They are supported audit formats, not current
configuration defaults. See [schedule policy](docs/work-schedule.md) and
[stage-by-stage inspection](docs/workflow-steps.md).

## Token Budget

Report measured usage or unknown. Model tokens include instructions and runtime
context; payload size alone does not establish a model token count or savings.
Claude totals use input + output + cache. Codex provider input already includes
cached input; its total is provider input + output, with cache partitioned for CSV.
Payload size is separate: exact JSON bytes and bytes/4 heuristic, not exact tokens.
The v2+ payload guard bounds the exact compact model request at 12,000 UTF-8 bytes;
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
Those historical payloads do not merge timesheet intervals; v6 uses the session
grouping policy above. No automatic AI cache exists. Validated supplied judgments may be reused explicitly with the same
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
