# F04: evidence-backed work proposals

A Calendar-only 09:00–09:30 stand-up previously created both the scheduled
30-minute event and an unsupported 09:30–17:30 development interval, totaling
510 minutes. The deterministic summary also invented discussion of sprint goals
and blockers. The same input now yields one scheduled 30-minute row whose
fallback description is `Daily stand-up. PRs: None`.

## Resulting behavior

- Calendar events retain supplied titles and `time_basis: scheduled`. Scheduled
  duration does not establish attendance. Calendar-only fallback invents no topics.
- A development gap is kept only if a commit or actual PR action has an aware
  timestamp inside its half-open interval `[start, end)`. Gap qualification and
  direct association use the same aware datetime bounds.
- Development rows carry `time_basis: estimated` and `estimation_reason`:
  `calendar_gap_with_activity` or `activity_workday_window`. A timestamp proves
  activity at that time, not continuous work throughout a proposed interval.
- Existing no-Calendar workday-window proposals remain, explicitly estimated.
  Entirely empty days still create no rows. Estimated rows carry no invented
  Calendar titles in either candidates or final source evidence.
- AI payload includes time_basis; keyed summary assembly preserves estimate
  metadata and source evidence. Semantic truth of AI text remains outside this fix.
- Markdown labels scheduled/estimated intervals, includes the proposal notice,
  separates category totals, and uses Total Proposed Time if estimates exist.
- F02 reconciliation removes an earlier generated gap when its supporting
  activity disappears; failed sources preserve old final/manifest/AI/token files.

## Validation on 2026-10-06

**161/161 tests pass**, including 24 new F04 regressions. `git diff --check` passes.
Tests cover unsupported before/between/after gaps, commit/PR-only support, action
history, interval boundaries, equivalent UTC timestamps, explicit Calendar focus,
faithful titles, metadata/evidence round trips, Markdown categories, reconciliation,
idempotency, source-failure preservation, and demo isolation. Calendar changes in
these cases are synthetic tests in temporary storage, not real Calendar edits.

Two isolated real-data pipeline runs both returned COMPLETE / exit 0:
Git 15 default-branch commits, PR 5 references (#1/#48/#50/#51/#52), and primary
Calendar 0 events, all success/live. Each produced one 13:30–17:30 estimated
240-minute proposal with all 15 commits and 5 PR references and no Calendar
source labels. JSON/Markdown/collection bytes were identical on rerun. Ten old
data/config files and both OAuth files remained unchanged; OAuth contents were
neither displayed nor staged. Token output was isolated through the run cwd.
No fixtures substituted for live data and no external AI API call occurred.

Local audit evidence is under ignored
`data/audit/f04-evidence-blocks-20261006-233153/`, with live logs, source manifest,
timesheets, compact AI input, verification.json, and clearly labeled synthetic
before/after evidence. Real non-empty Calendar behavior remains unverified.

## Remaining scope

Workday estimation policy (D02), final-gap lunch splitting (F05), overlaps (F06),
all-day/cross-midnight handling (F07), unmatched/afterhours activity fallback
(F08), authoritative block timezone (F09), malformed timestamp handling (F10),
frozen AI snapshots (F28), and transactional storage (F29) remain open. Direct
aware matching improves part of F08 but does not complete it. Removing synthetic
Calendar labels improves new output related to F21; old files are not migrated.
No prerequisite PR is merged. Issue #5 stays open pending review/merge.
