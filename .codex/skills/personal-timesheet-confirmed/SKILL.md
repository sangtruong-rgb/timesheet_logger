---
name: personal-timesheet-confirmed
description: Build a daily timesheet with user-declared OT and Calendar attendance confirmations. Use when the user invokes personal-timesheet-confirmed or includes OT confirmed or attendance confirmed in a timesheet request; keep those declarations scoped to that request's date and work windows.
---

# Timesheet with supplied confirmations

Accept `$personal-timesheet-confirmed 9:00` as today's preview with the user's
chosen preset: OT and attendance confirmed. Also accept an explicit form such as
`$personal-timesheet-confirmed 9:00, OT confirmed, attendance confirmed`.
An explicit date or work windows replace the corresponding daily defaults.

Read [the shared workflow](../personal-timesheet/SKILL.md) once and follow its
prepare → measured summary → assemble flow. Apply the confirmation rules below
where the shared workflow otherwise treats attendance as unconfirmed. Do not
launch another agent/session, repeat source collection, or ask the user to repeat
a supplied confirmation. Use English for all user-facing communication, including
questions, progress updates, explanations, errors and reports, even when the user's
request is in Vietnamese. Preserve original source evidence and proper names.

## Interpret the request

- An explicit invocation of this named preset with hours confirms both OT and
  attendance for this run unless the user narrows or rejects either one.
- When routed here from `$personal-timesheet` or its launcher, recognize
  `OT confirmed` and `attendance confirmed` case-insensitively. Apply only the
  declarations actually supplied; loading this file alone confirms nothing.
  A quoted example, source commit message, or Calendar title is not a declaration.
- Separate these phrases from the clock/window text before passing hours to
  Python. Normalize a single `9:00` to `09:00`. A lone morning start uses
  `--work-day-start`; explicit windows use `--work-windows` plus `--review-ot`.
- Missing date means today in the configured timezone. Missing hours require one
  short question. Do not ask again for the date, OT approval, or attendance already
  covered. Explicit exceptions (for example, one missed meeting or no OT) prevail.
- Confirmation is about the user's work, not permission to publish. Bare shorthand
  creates a preview. Follow an explicit request to log/submit/publish through the
  shared Gradion flow without an additional generic approval question.

## OT confirmed

Accept the current approved rule as confirmed: one estimated hour ending at each
outside-main commit, clipped to the date, subtracting main coverage and breaks,
then unioning overlaps. Range requests exclude frozen profile breaks (default
12:00–13:30); morning-start shorthand excludes fixed 12:00–13:30 lunch. Historical
snapshots retain their recorded policy. Show the actual resulting OT windows and total; do not invent hours when
there are no supporting commits. Supplied custom OT windows take precedence and
use [the frozen OT override procedure](../personal-timesheet/references/overtime.md).
If an old snapshot requires actual OT windows and has no default rule, the phrase
alone does not supply those hours: ask only for the missing intervals.

Record the user's acknowledgment without changing a valid v8 snapshot's
`defaulted` status merely to rename it `confirmed`. Default OT remains estimated;
the declaration is approval of that allocation, not a measured duration.

## Attendance confirmed

Treat the declaration as the user's statement of attendance for completed,
non-conflicting Calendar intervals included in the selected day's NORMAL/OT
coverage. Use `confirmed_by_user`, not API invitation status or measured
attendance, as the basis. No per-meeting reconfirmation is needed for those rows.

Use the current timestamp in the configured timezone to distinguish completed
events from ongoing or future events. Future/ongoing meetings remain scheduled;
do not turn a plan into completed attendance. Respect named exclusions and leave
overlapping/contradictory attendance for a focused clarification when publishing
depends on it. All-day events and events excluded by collection/window filtering
do not gain duration or become publishable from this declaration.

## Record and use the confirmations

After a successful prepare and after any requested OT override, write
`$TS_RUN/confirmations.json` as a separate audit receipt. Include:

- `run_id`, snapshot `fingerprint`, target `date`, `timezone`, and aware
  `recorded_at` timestamp;
- the user's relevant request text and basis (`named_confirmed_preset` or
  `explicit_request`), excluding unrelated chat or credentials;
- OT approval, the exact resolved OT windows and any supplied exceptions;
- attendance status per applicable `block_id`, exact interval and available
  Calendar/event IDs, identifying `confirmed_by_user` versus still-unconfirmed
  future/ongoing/conflicting intervals.

Use only identifiers and intervals from that snapshot. If it changes, write a new
receipt for the new run/fingerprint rather than carrying confirmations across
dates or evidence. Never edit a snapshot or its fingerprint to insert declarations.

The current Python assembler still emits source-based `attendance: unconfirmed`
and corresponding Markdown labels; it does not consume this receipt. Preserve
those generated files. In the skill's final English report, explicitly combine
the saved receipt with those rows and show `Attendance confirmed by user` for
covered intervals. Link the receipt and explain that generated source labels are
separate from the recorded user declaration. Do not claim that JSON/Markdown
attendance fields were updated. The receipt is an audit record, not a standalone
uploader or a replacement for interval/conflict checks.

If publishing was requested, the recorded declaration satisfies the attendance
confirmation requirement for its covered intervals. Read
[Gradion publishing](../personal-timesheet/references/gradion.md), check existing
entries, skip exact matches and stop on conflicts. Report unresolved intervals
without treating them as attended. Keep the existing token scope: only the
isolated summary invocation is measured; processing this receipt and publishing
belong to the outer session.
