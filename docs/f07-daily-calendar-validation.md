# F07: all-day context and daily timed Calendar portions

All-day records previously lost their event type and became a 00:00–00:00 block
with 1,440 minutes, which F02 storage rejected. Timed 22:00–02:00 events also
produced invalid daily clock intervals. Fixture selection missed events beginning
the previous night. These cases now produce valid daily output with source evidence.

## Contract

Live Google and explicit fixture adapters share event typing and local-day overlap
selection. All-day Google date objects and fixture date strings retain all_day=true,
start date and exclusive end date. Mixed date/dateTime or contradictory type flags
are source errors. All-day context is separate from normalized timed Calendar events;
it contributes no blocks, duration or AI payload and does not establish a day off.
Git/PR work proposals remain possible on a day with all-day context.

Timed sources keep their original normalized extent. Blocks are clipped to the
requested timezone's half-open local day; midnight end is 24:00, supported by existing
block identity/storage. A 22:00–02:00 event yields first-day 22:00–24:00 (120 minutes)
and second-day 00:00–02:00 (120 minutes). Previous-night events are selected by both
adapters. Explicit dateTime midnight-to-midnight remains timed; it is not guessed to
be all-day. UTC elapsed minutes handle overnight offset changes. Block scope honors
the normalized IANA timezone or UTC offset; broader timezone scope remains F09.

All-day evidence is saved in YYYY-MM-DD.calendar-context.json with target date and
complete/demo collection provenance, linked from the source manifest, and displayed
in a Markdown context section. A context-only day has [] timed entries and zero minutes.
Changed/deleted context updates Markdown and the sidecar even if timed entries are
unchanged. Exact reruns preserve bytes. Source/validation/reconciliation failures
preserve the existing sidecar with final/manifest/AI/token files. Corrupt context
stores require review instead of replacement. Standalone saving accepts an optional
--calendar-context-file JSON array; omission preserves prior context, [] clears it.
Demo context remains isolated. Multi-file transactional/concurrent persistence is
still F29; existing ownership rules remain, with no automatic legacy migration.

## Validation on 2026-10-07

**245/245 tests pass**, including 36 new F07 tests (27 adapter/normalization/block/
storage and 9 pipeline cases); git diff --check passes. Tests cover Google/fixture
parity, all-day exclusive ends and multi-day context, type errors, day overlap
boundaries, previous-night selection, both overnight portions, source extent retention,
selected timezone, overnight DST elapsed duration, F06 midnight overlap review,
commit assignment, context-only output, Git fallback, context updates/deletions,
idempotency, failure preservation, corrupt stores and demo isolation.

Two isolated live runs each for 2026-10-06 and 2026-10-07 all returned COMPLETE / exit 0:

| Target day | Git | PR references | Primary Calendar | Output |
|---|---:|---:|---:|---|
| 2026-10-06 | 15 | 7 (#1/#48/#50/#51/#52/#53/#54) | 0 | One 240-minute estimated proposal |
| 2026-10-07 | 0 | 1 (#55) | 1 timed event | One 15:00–16:00 scheduled 60-minute proposal |

Each source was success/live. Both days' exact reruns preserved JSON/Markdown/manifest
bytes. Ten old data/config files and both OAuth files remained unchanged; OAuth
contents were neither displayed nor staged. Token output used an isolated working
directory. No fixtures replaced real data, no Calendar event was modified, and no
external AI API call occurred. The real Calendar event is an ordinary same-day event;
all-day and cross-midnight behavior was verified synthetically, not with real events.

The live 2026-10-07 run exposes the remaining F08 fallback: PR #55 at 00:02:12 is
attached to the 15:00–16:00 Calendar block despite not overlapping it. Evidence retains
the true action timestamp, but routing is not fixed here. The future scheduled event
is not attendance confirmation. Breaktime/OT classification remains deferred by user;
D01/D02 future-time/workday policy and broader D03 filters remain separate.

Ignored local evidence: data/audit/f07-calendar-daily-scope-20261007-001614/, including live logs/output for both dates,
verification.json, AI payloads, and clearly labeled synthetic before/after evidence
and DEMO outputs for context-only, overnight and previous-night cases. Baseline is
F06 commit a6bc67d. Issue #8 remains open pending review/merge; this branch is based
on F06 / PR #55. No prerequisite PR is merged.
