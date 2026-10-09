---
name: personal-timesheet-windows
description: Preview a daily timesheet within one or more user-confirmed work windows, such as 8:00-12:00, 1h30-4:00, using verified GitHub and Google Calendar activity in timesheet_logger.
---

# Timesheet by work windows

Accept `$personal-timesheet-windows 8:00-12:00, 1h30-4:00` as a complete request
for today's live-source preview in the configured timezone. An explicit date
selects that date. The original `$personal-timesheet` skill also accepts this form.

Read [the shared timesheet workflow](../personal-timesheet/SKILL.md) and use its
prepare → measured summary → assemble flow, source validation, evidence rules and
publication boundary. Pass the user's interval text as one quoted `--work-windows`
argument together with `--review-ot` during prepare, replacing `--work-start` and `--work-end`. Do not invoke
another interactive skill session or repeat collection.

The Python parser resolves the example to 08:00–12:00 and 13:30–16:00. It accepts
colon or `h` clocks, AM/PM, and comma-separated windows in chronological order.
An unpadded low hour may mean afternoon when needed to follow the prior boundary;
padded HH:MM is always 24-hour time. Show the canonical windows in the result.
Use explicit 24-hour hours or AM/PM when the user's intent cannot be determined;
do not alter rejected windows merely to make validation pass.

Write all work-log descriptions in English, including NORMAL and OT rows, even
when the user or source evidence uses Vietnamese. Preserve ticket keys and proper
names. Keep original source text for audit; do not translate or rewrite evidence.
The script fallback uses English evidence-based templates, not title translation.
Timesheet previews and final reports must also be in English, including table
headings, attendance/status labels, totals, review notes and token-usage notes.
All user-facing communication must be in English, including clarifying questions,
progress updates, explanations and errors, even when the request is in Vietnamese.

These daily windows replace profile hours and breaks for this date, including on
holidays. These are the day's main NORMAL windows. For each commit outside
main, use the approved default of 60 minutes ending at the commit's minute-floored
time; only the part outside main, outside frozen profile breaks (default
12:00–13:30) and inside the target day counts. Historical snapshots retain
their recorded break policy. Union overlapping
OT windows instead of double-counting. New v8 snapshots record this policy and
`defaulted` approval, and proceed without a confirmation question or waiting.
Show default OT as an estimate in the preview. PR or Calendar alone cannot create
a commit-based hour, and OT approval does not confirm Calendar attendance.

Read [the OT override procedure](../personal-timesheet/references/overtime.md)
only if the user requests changed OT hours or no OT, or an old v7 snapshot has a
pending manual decision. Use the same frozen evidence and a new snapshot for an
override. Gaps between main and confirmed OT windows
are excluded, and Calendar rows are clipped to their union. Preserve excluded
activity for review; scheduled attendance
remains unconfirmed. The final end is supplied by the user, so include the closing
tail as an estimated allocation. Group adjacent pieces only by a verified common PR or unique ticket after an
empty successful PR lookup, within the same work type. Do not merge by duration. All windows are frozen in
the snapshot; changed main hours require a new prepare run. Requested OT edits use
the dedicated frozen decision phase. Do not change the profile or publish from shorthand.
