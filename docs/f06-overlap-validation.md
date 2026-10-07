# F06: disjoint scheduled coverage with attendance review

For Calendar A 09:00–10:00 and B 09:30–10:30, the previous implementation
produced two overlapping 60-minute rows and summed them to 120 minutes. It now
produces three disjoint intervals totaling 90 scheduled minutes: A 09:00–09:30,
A+B 09:30–10:00, and B 10:00–10:30. This is scheduled coverage, not confirmed
attendance. The conflicting interval requires human attendance review.

## Implementation and review contract

- Partition Calendar intervals at every start/end boundary, retaining all active
  normalized title/start/end records in `sources.calendar_events`, including their
  original boundaries. Titles remain in the backward-compatible sources.calendar.
- Identical intervals produce one block identity retaining both event sources;
  nested and triple overlaps count coverage once. Touching events are not overlaps.
- Conflicts carry `calendar_overlap: true` and review status required, reason
  calendar_overlap, attendance unconfirmed. Compact AI input includes the conflict
  and unconfirmed attendance, not full Calendar source records.
- Fallback/AI descriptions, Markdown rows/banner, and CLI expose the review notice.
  A supplied AI summary cannot remove the deterministic notice or review fields.
  Totals with overlap say Total Proposed Time, and overlap minutes are explicitly
  a subset of scheduled coverage, not an additional duration.
- Source collection may be COMPLETE while attendance needs review. Saving this
  proposal does not confirm attendance or choose which meeting was attended.
  No attendance-selection UI or automatic confirmation policy is implemented.
- Direct timestamp mapping attaches commit/PR actions once to the correct disjoint
  interval; every actual action and all normalized source evidence are preserved.
- F04 activity-qualified development gaps and F05 lunch subtraction remain in use;
  scheduled meetings overlapping lunch remain intact. F02 reconciles obsolete
  generated overlapping rows on rerun and preserves manual/ambiguous records.
- Parsed Calendar intervals must have aware timestamps and end after start to
  partition safely. Invalid bounds generate a validation-review draft preserving
  final/manifest/AI/token files. This is a partition guard, not complete F10 handling.

## Validation for 2026-10-06 (completed across midnight into 2026-10-07)

**209/209 tests pass**, including 26 new F06 tests: 20 block/assembly/rendering
cases and 6 pipeline regressions. `git diff --check` passes. Coverage includes
partial/nested/identical/triple overlaps, input order, boundary-touching, same
names with different intervals, normalized duplicate records, original source
bounds, equivalent UTC timestamps, 5-minute overlap, lunch, commit/PR action
assignment, AI-independent review labels, partition validation, replacement of
old generated rows, removed conflicts, source failures, and exact reruns. A
100-case pair-interval grid verifies union duration, disjoint output and active
source membership. Calendar overlap cases are synthetic with temporary storage.

Two isolated real-data runs for 2026-10-06 / Asia/Ho_Chi_Minh were COMPLETE / exit 0:
Git success/live 15 default-branch commits, PR success/live 7 references
(#1/#48/#50/#51/#52/#53/#54), and primary Calendar success/live 0 events. Both
produced one 13:30–17:30 estimated 240-minute proposal, with no attendance conflict.
This verifies live integration and unchanged empty-Calendar fallback, not a real
Calendar overlap. No Calendar edits, fixture substitution or external AI API call.
JSON/Markdown/manifest bytes were identical on rerun; ten old data/config files
and both OAuth files unchanged. OAuth contents were neither displayed nor staged.
Token output was isolated through the run working directory.

Ignored evidence: `data/audit/f06-calendar-overlap-20261006-235944/`, with source manifest, live logs, real output,
AI payload, verification.json, and clearly labeled synthetic before/after JSON
and readable synthetic-proposal.md. Baseline is F05 commit `62bbc59`.

## Remaining scope

Attendance decisions remain human review; personal/declined/all-day filtering
and provider event identity remain wider D03/Calendar work. Existing normalization
deduplicates equal title/start/end records before partitioning, so distinct provider
IDs with identical normalized records cannot be distinguished. All-day/cross-midnight
handling remains F07; unmatched/afterhours routing F08, block timezone F09,
malformed timestamp/sub-minute policy F10, and workday policy D02 remain open.
Breaktime/OT classification remains deferred at the user's request. No legacy/manual
migration or prerequisite merge. Issue #7 remains open pending review/merge; the
branch is based on F05 / PR #54.
