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
argument during prepare, replacing `--work-start` and `--work-end`. Do not invoke
another interactive skill session or repeat collection.

The Python parser resolves the example to 08:00–12:00 and 13:30–16:00. It accepts
colon or `h` clocks, AM/PM, and comma-separated windows in chronological order.
An unpadded low hour may mean afternoon when needed to follow the prior boundary;
padded HH:MM is always 24-hour time. Show the canonical windows in the result.
Use explicit 24-hour hours or AM/PM when the user's intent cannot be determined;
do not alter rejected windows merely to make validation pass.

These daily windows replace profile hours and breaks for this date, including on
holidays. Only the windows contribute time: gaps are excluded and Calendar rows
are clipped to them. Preserve excluded activity for review; scheduled attendance
remains unconfirmed. The final end is supplied by the user, so include the closing
tail as an estimated allocation. Keep the under-20-minute commit merge and shared
allocation descriptions. All windows are frozen in the snapshot; changed hours
require a new prepare run. Do not change the profile or publish from shorthand.
