# F05: exclude lunch from Calendar development gaps

With a stand-up at 09:00–09:30 and commits at 10:00 and 15:00, the final
09:30–17:30 estimated development gap previously included all 90 lunch minutes.
It now produces 09:30–12:00 (150 estimated minutes) and 13:30–17:30 (240 estimated
minutes), plus the 30-minute scheduled stand-up: **510 → 420 minutes**.

## Implementation

One helper subtracts the existing hardcoded lunch interval 12:00–13:30 from
all gaps before, between and after Calendar events. The 30-minute minimum is
applied to each remaining interval, followed by F04's independent commit/actual
PR-action evidence check. Evidence in one interval cannot qualify the other.
Morning-only support produces 180 total minutes including the stand-up;
afternoon-only support produces 270. All development gap durations remain estimates.

Scheduled Calendar events during lunch are preserved whole. Lunch-only commit
or PR evidence is not discarded, but its existing unmatched-activity routing
remains F08. No new overtime policy is introduced. No-Calendar workday fallback
is unchanged, including the morning-only 09:00–12:30 proposal; harmonizing that
rule and configurable schedules remains D02/F27. F06 overlaps, F07 all-day and
cross-midnight, F09 authoritative block timezone and F10 malformed timestamps
remain separate. Old ambiguous/manual records are not automatically migrated.

## Validation on 2026-10-06

**183/183 tests pass**, including 22 new F05 tests (18 block-level and 4 pipeline
regressions). `git diff --check` passes. Tests cover final/before/between gaps,
partial and full lunch overlaps, exact lunch boundaries, the minimum after
subtraction, UTC-equivalent activity timestamps, independently qualifying PR
actions, preservation of lunch-only evidence and actual lunch meetings, empty
support, JSON/Markdown/AI identities, replacement of a generated cross-lunch row,
idempotency, and failed-source output preservation. Calendar cases are synthetic
inputs with temporary storage; no real Calendar event was modified.

Two isolated real pipeline runs for 2026-10-06 / Asia/Ho_Chi_Minh both returned
COMPLETE / exit 0: Git success/live 15 commits; PR success/live 6 references
(#1/#48/#50/#51/#52/#53); primary Calendar success/live 0 events. Each produced one
13:30–17:30 estimated 240-minute proposal and preserved all source evidence.
This empty-Calendar result exercises the unchanged fallback, not the Calendar-gap
fix. Real non-empty Calendar cases remain unverified. No fixtures substituted for
live data; no external AI API call occurred.

JSON/Markdown/collection bytes were unchanged on rerun. Ten old data/config files
and both OAuth files remained unchanged; credentials/token were neither displayed
nor staged. Token output was isolated using the run working directory.

Ignored local evidence: `data/audit/f05-calendar-gap-lunch-20261006-234212/`, including live logs, source manifests,
timesheets, AI payload, verification.json, and a clearly marked synthetic before/
after comparison against F04 commit `81b23a6`.

Issue #6 stays open pending review/merge. The F05 branch is stacked on F04 / PR #53;
no prerequisite PR is merged.
