# Timesheet improvement log

This log supersedes the unmeasured claims in improvement-log-legacy.md. That file
is a preserved historical artifact; 3,000–8,000 tokens, guaranteed <350 tokens and
zero-waste results are withdrawn. There was no transcript evidence for those claims.

## 2026-10-09 — stabilize allocation groups, record attempt costs and link boundary merges

Problem: a start-minute commit timestamp-assigned to one piece changed its summary
group; rejected AI summaries lost collectible usage despite completed provider
counts; minute-floored closing bounds left same-minute merge events in review.

Change: freeze group identity before splitting/timestamp assignment and union
commit context for shared fallback/AI summaries. Retain qualified merge SHAs through
collection/dedup/normalization; associate proven same-minute merges with the final
piece of their closing group, preserving timestamps/hours. Snapshot v4 freezes the
new behavior while v1-v3 remain reproducible. Separate verified attempt receipts
and per-invocation CSV from summary acceptance; benchmark ledgers count rejected
attempts/retries once, preserve partial-run costs and mark unknown usage explicitly.
Attempt receipts cannot authorize assembly in place of a validated output manifest.

Validation: 565 tests pass. Replayed live Oct8 evidence with a readonly GitHub SHA
check for PR66: 4 rows/337 minutes unchanged, merge event assigned, review 1 -> 0.
Historical 6,966-token provenance still verifies. New benchmark on the same Oct7
source data with current under-20 allocation: 6 rows/5 compact jobs, 300 minutes,
40 assigned commits and 9 review events. Same gpt-6.1-sol/low/CLI 0.161.0: legacy
18,619 input + 390 output = 19,009; compact 5,664 + 518 = 6,182 (-67.48% total,
-69.58% input). Cached input zero. Two successful calls/no retries consumed 25,191
tokens in total; one pair is not a statistical average. Reviewed all 5 compact
descriptions; assembly/rerun and benchmark resume preserve bytes without new AI.
No publish/log work. See docs/followup-benchmark-20261009.md.

## 2026-10-08 — share descriptions across pieces of one commit allocation

Problem: lunch/Calendar can split one allocation into rows with different PR
context. Summarizing each row separately made one work group look like different
tasks.

Change: payload v3 identifies groups by their original allocation and qualified
commit evidence, combines PR titles for one summary job, and expands one topic
description to all pieces. Group identities stay in the audit envelope, outside
the model request. Different allocations retain separate jobs even when their
text matches. Each row preserves its own hours, PR suffix and full evidence.
Assembly shares fallback/partial AI descriptions too and rejects conflicting
descriptions within a group. Frozen v1/v2 payloads and historical usage evidence
retain their original behavior; the under-20-minute merge rule is unchanged.

Validation: all 553 tests pass, including lunch/Calendar splitting, different PR
context, distinct allocations, merged short commits, fallback/partial/conflicting
judgments, legacy payload replay, standalone CLI and measured-run assembly/rerun.
Replaying today's old under-30 snapshot with shared descriptions gives 4 rows / 3
jobs; the current under-20 policy gives 4 rows / 4 distinct allocation jobs. Both
preserve 337 minutes; historical snapshot/6,966-token evidence still validates.
Skill validator and git diff --check pass. No fresh AI invocation or token reduction
measurement; no publish/log work.

## 2026-10-08 — lower short-commit merge threshold to 20 minutes

Request: merge only allocations under 20 net work minutes. 20, 29 and 30 minutes
remain separate; consecutive 1–19-minute allocations still accumulate backward.
Lunch/Calendar subtraction, source retention and confirmed-end tails keep their
existing rules. One shared constant supplies the current threshold, including
merged allocation audit metadata.

New snapshots use schema v3 for the under-20 rule. Existing v2 snapshots keep
under-30 merging; v1 snapshots retain unmerged intervals. Old outputs and usage
evidence are not rewritten. Updated README, workflow and the timesheet skill.

Validation: all 545 tests pass, including 19/20/29/30-minute boundaries, net work
across lunch/Calendar and all three snapshot versions. Skill validator and
git diff --check pass. Rebuilding today's existing live-source evidence in Python
keeps 337 proposed minutes and all assigned commit identities/review events;
the 33-minute pre-lunch row now has one commit and the 29-minute afternoon row
has three separate-group commits, rather than both copying the same four commits.
Historical snapshot/usage validation remains successful. No fresh collection,
AI invocation or publish/log work was performed.

## 2026-10-08 — merge short commit allocations backward

Request: merge a commit's work allocation under 30 minutes with the preceding
commit allocation. Measure net work after lunch/Calendar exclusion; decide before
splitting into rows. Consecutive 1–29-minute allocations accumulate backward,
retaining every commit and timestamp-assigned PR. Preserve the first allocation
without a predecessor, zero-work allocations, exactly 30 minutes and confirmed-end
tails. Never pad duration or fill lunch/meetings. Merged allocation metadata retains
the original interval bounds.

New snapshots use schema v2 to freeze this behavior. Existing v1 snapshots rebuild
without the merge rule, preserving historical AI outputs and token attribution;
identical evidence can be resaved without rewriting its original schema/history.
Updated README, workflow and the repository timesheet skill.

Validation: all 544 tests pass, including 11 new merge/snapshot/pipeline regressions;
skill validator and git diff --check pass. Replaying the previous benchmark's frozen
source data in Python reduces 23 rows to 5 and 23 AI jobs to 4, preserving 300 proposed
minutes (including scheduled Calendar), 40 assigned commit identities and 9 review
events. The historical 6,966-token manifest remains valid. No new AI call or token
reduction measurement was performed; no publish/log work.

## 2026-10-08 — compact semantic summary request and measured Codex benchmark

Problem: commit_intervals expands timesheet rows and repeats closing evidence;
the former full audit payload can exceed its 12,000-byte guard. Generic coding
instructions/tools add input to a summary-only invocation.

Change: share text in a dictionary, group only identical semantic contexts, map
job summaries to all original blocks, preserve PR formatting and review evidence.
Payload v2 bounds the transmitted compact request and measures the larger audit
export separately. Narrow invocation instructions/context; retain v1 compatibility
and validate v2 request/raw output/mapping hashes for usage attribution. Add a
before/after benchmark with evidence-verified resume, no publishing. No persistent
summary cache was added.

Result: 533 tests pass. A real pair of Codex calls on one historical replay snapshot
(2026-10-07, hypothetical start 09:00, 23 rows/jobs, gpt-6.1-sol, low, CLI 0.161.0)
reported input 18,536 -> 5,953 and output 1,145 -> 1,013, cached input zero for both.
Total 19,681 -> 6,966 (-64.61%); input -67.88%. Times/evidence/metadata unchanged;
all 23 descriptions reviewed and v2 assemble/rerun verified without another AI call.
A CLI configuration rejection was preserved and corrected before the successful
compact retry. One pair is not a statistical average or a fresh workday confirmation.
See docs/token-optimization-benchmark.md and ignored data/audit/token-optimization-20261008-170818.

## 2026-10-08 — synchronize GitHub time-allocation updates

Fast-forwarded the local fix branch to origin/main c235d0e (PRs #65/#66), preserving
the uncommitted fixes in a Git stash before restoring them. Resolved the Calendar
gap helper conflict by keeping the new activity-cluster construction inside the
bounded work windows. Confirmed commit_intervals still follows explicit daily
hours and supports work outside legacy windows. CLI failure status and generated
overlap validation remain applied locally.

Result: all 522 tests pass, including a new activity-cluster regression for an
evening meeting; git diff --check passes. The original local-fix stash is retained
as a backup. No token optimization was implemented.

## 2026-10-08 — CLI failure status and generated interval overlap validation

Problem: build_time_blocks.py discarded main()'s failure status and exited zero
after validation/output errors. Daily reconciliation accepted overlapping generated
intervals, allowing duplicate proposed minutes in direct writer/CLI inputs.

Change: propagate main() via sys.exit(); reject incoming generated overlaps before
override suppression or final writes. Half-open adjacent intervals remain valid.
Existing generated overlap artifacts can still be replaced by a valid snapshot.

Result: all 493 tests pass, including ten new regressions using real CLI processes
and temporary storage. Coverage includes invalid model/JSON/output failures,
successful CLI output, partial/nested/reversed/midnight overlaps, complete/demo
status, adjacency, override validation, and preserved JSON/Markdown/manifest/AI/token
files with rejected proposals retained in the pipeline draft. The historical overlap
fixture now seeds old provenance-tagged JSON directly instead of using the writer.
git diff --check passes. No collection or AI/token optimization was implemented.

## 2026-10-08 — restrict Calendar development gaps to work windows

Problem: a 19:00 commit before a 20:00–21:00 meeting created an estimated
13:30–20:00 block (390 minutes); gaps between evening meetings could also become
estimated work. Calendar gap construction subtracted lunch without clipping to
the workday end.

Change: intersect every Calendar gap with 09:00–12:00 / 13:30–17:30 before the
30-minute minimum and activity checks. Scheduled meetings remain intact; unmatched
evening commits/PR actions remain review evidence with no inferred duration.

Script impact: correct estimated intervals and activity assignment. AI impact:
only supported blocks reach synthesis. Token savings have not been measured.

Result: all 483 tests pass, including seven new block/pipeline regressions for
evening meetings, Git/PR evidence, local/UTC workday boundaries, clipped minimum
duration, JSON/Markdown/AI output, review preservation and byte-stable reruns.
Validation uses synthetic sources and temporary output; no live collection or AI.
No-Calendar fallback and deferred D02 schedule/BREAK/OT policy remain unchanged.

## 2026-10-07 — remaining source, snapshot, token and delivery findings

Problem: source identities/pages/setup were incomplete; documented phases collected
again and wrote premature final output; AI budgets, token attribution, skill paths
and crash recovery lacked evidence.

Observed: the audit reproduced missing Calendar IDs, ambiguous equal PR numbers,
partial/duplicate AI suffixes and unbounded duplicated text. Synthetic tests injected
later-page failures, disk failure, pending journals and repeated/malformed usage
messages. Real GitHub/Calendar collection is checked in separate ignored audit data.

Cause: implicit source assumptions, mutable two-pass collection, unvalidated strings,
direct file writes and session-wide usage aggregation without marked run boundaries.

Change: explicit source/config identities and pagination; readonly OAuth setup;
immutable prepare/assemble; bounded deduplicated eligible payloads; validated duration
and script-owned suffixes; writer locks/atomic replacement/rollback; marked-run usage
with input/output/cache, execution-vs-target dates and defensive dedup; installable
skill-root commands; labeled regenerated synthetic examples and accurate docs.

Script impact: scripts perform deterministic work and preserve original evidence.
AI impact: optional text synthesis only. Ticket extraction is not clustering; no
automatic judgment cache. Validated judgments can be reused with the same snapshot.

Expected token impact: fewer duplicate strings and no AI needed for Calendar-only
rows. Exact payload bytes are measured, token estimates heuristic. No measured
savings/full-run budget success is claimed. Real Claude CLI/usage acceptance remains
V01; missing usage is unknown and does not rewrite old CSV.

Result: validation results and acceptance limits are in docs/remaining-*-validation.md.
D01/D03/D06 follow approved policy; configurable schedule and BREAK/OT remain D02.
