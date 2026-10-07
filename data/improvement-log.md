# Timesheet improvement log

This log supersedes the unmeasured claims in improvement-log-legacy.md. That file
is a preserved historical artifact; 3,000–8,000 tokens, guaranteed <350 tokens and
zero-waste results are withdrawn. There was no transcript evidence for those claims.

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
