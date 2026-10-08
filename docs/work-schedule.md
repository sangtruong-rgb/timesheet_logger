# Work schedule and functional follow-up — 09/10/2026

D02 was resumed at the user's request. The chosen default is 09:00–12:00 and
13:30–17:30. Regular start/end, multiple breaks, weekdays, explicit holiday dates
and optional overtime windows can be configured in `work_schedule`.

## Policy and configuration

```json
{
  "work_schedule": {
    "start": "09:00",
    "end": "17:30",
    "breaks": [{"start": "12:00", "end": "13:30"}],
    "weekdays": [0, 1, 2, 3, 4, 5, 6],
    "holidays": [],
    "overtime_windows": []
  }
}
```

- Missing fields use the default above. Empty `breaks` means no excluded breaks;
  empty `weekdays` disables inferred development on every day. Weekdays use 0 for
  Monday through 6 for Sunday. All seven days remain enabled by default, preserving
  prior behavior; no holiday calendar is inferred.
- Hours are local HH:MM in the authoritative timezone. Only end may be `24:00`.
  Each interval must end after start on the same day. Overnight work is represented
  in separate local-day snapshots. Nonexistent local clock boundaries during a DST
  transition are rejected.
- Breaks and overtime lists are sorted, copied and checked for overlap. Overtime
  windows must be outside regular hours. Breaks subtract from both regular and
  overtime windows, even when a break extends outside regular hours. A break inside
  a meeting does not remove the scheduled meeting; their excluded development
  coverage is subtracted once as a union.
- Legacy/cluster development requires timestamped commit/PR evidence inside an
  enabled work window. It does not infer work on disabled weekdays/holidays, during
  breaks, or between regular and overtime windows. Cluster windows shorter than
  the configured minimum contribute no inferred work and keep evidence in review.
- `commit_intervals` continues to require confirmed daily start and optional end.
  That explicit per-day confirmation permits work outside regular hours or on a
  nonworking date. It does not imply a reusable profile start, confirmed attendance
  or extra work after the final commit. Configured breaks and Calendar coverage are
  still excluded. The under-20-minute merge rule and shared allocation descriptions
  remain unchanged.
- Calendar proposals are kept on all days, including outside regular/confirmed
  hours, with attendance unconfirmed. Breaks do not produce work rows. Overtime
  windows permit evidence-based proposals but do not apply an automatic OT billing
  category or BREAK label.

Example: confirmed start 08:30, closing commit 14:30, breaks 10:00–10:15 and
12:30–13:00. The script emits 08:30–10:00 (90m), 10:15–12:30 (135m) and
13:00–14:30 (90m): **315 proposed minutes** and one summary group. Original commit
evidence and row-specific PR suffixes remain intact.

## Confirmed daily windows

Use either `$personal-timesheet 8:00-12:00, 1h30-4:00` or the dedicated
`$personal-timesheet-windows 8:00-12:00, 1h30-4:00`. The launcher accepts
`./bin/personal-timesheet-codex "8:00-12:00, 1h30-4:00"`.
Without a date, the skill selects today in the configured timezone. An explicit
date selects that day. These are preview requests; they do not authorize publishing.

During prepare, pass the text as one argument:

```bash
python3 scripts/run_pipeline.py --phase prepare --date 2026-10-10 \
  --config config/user-config.json \
  --work-windows "8:00-12:00, 1h30-4:00" \
  --snapshot data/audit/my-run/activity.json
```

The deterministic parser resolves this example to **08:00–12:00, 13:30–16:00**,
or **390 minutes (6h30)** before Calendar separates scheduled and estimated work.
It accepts `H:MM`, `HH:MM`, `HhMM`, hour-only clocks and optional AM/PM. Unpadded
1–9 or `h` hours up to 11 can shift to afternoon when needed to follow the prior
boundary. Padded `HH:MM` is always 24-hour time. Use canonical
`08:00-12:00, 13:30-16:00` or AM/PM to remove ambiguity. Intervals are supplied in
chronological order, must not overlap, and cannot wrap to the next day. Invalid
clocks and nonexistent local DST boundaries fail before source collection.

- Do not combine `--work-windows` with `--work-start` or `--work-end`.
- Explicit daily windows replace profile regular hours, weekdays, holidays and
  breaks for this date; the profile itself is unchanged. Only their union counts.
  Thus `11:00-14:00` includes the usual lunch; to exclude lunch, supply two windows.
- Calendar rows are clipped to these windows. Excluded or partially excluded
  Calendar evidence is retained for review without adding time; attendance stays
  unconfirmed. Commits/PRs outside the windows are review-only. Commits exactly
  at a window end can close the work leading to that boundary.
- The last supplied end is confirmed: include the remaining tail even after the
  final commit, using estimated duration. The under-20-minute merge operates on
  work minutes after gaps/Calendar exclusions; shared descriptions remain intact.
- Snapshots with explicit windows use **v6** and freeze the canonical windows
  inside `work_confirmation`. Assembly cannot change them, does not collect again,
  and replays them even if the profile changes. V1–v5 retain their prior behavior.

## Frozen evidence and output

`run_pipeline.py` validates configuration before collecting sources. The normalize
CLI also embeds the validated schedule. New pipeline snapshots use schema **v5**;
each row and the collection manifest retain schedule metadata. Markdown states the
configured hours/breaks instead of incorrectly claiming fixed 12:00–13:30 lunch.
Assembly uses frozen values even if the profile has changed or become unreadable.
Changing the schedule requires a new snapshot.

V1–v4 snapshots and models without `work_schedule` retain their original rules and
token evidence. In particular, the old legacy morning-only fallback ending at 12:30
is preserved for historical replay; new scheduled models end at the configured
morning boundary, normally 12:00. A schedule field cannot be backdated into a v1–v4
snapshot, and a rehashed schedule edit that conflicts with frozen rows is rejected.

## Token correctness fixes

Two remaining F25-related cases were reproduced and fixed:

1. A newer snapshot arriving first hid conflicting older records with the same
   message ID/timestamp. Conflict detection now covers every scoped timestamp,
   independently of arrival order, while selecting the latest complete counts.
2. `daily_totals()` counted duplicate CSV rows twice (120 became 240). Reads and
   writes now share strict validation of headers, counts, duplicate rows and an
   attributed run identity repeated on different execution dates. Rejected inputs
   preserve existing CSV bytes; unknown counts are never reported as zero.

## Validation and acceptance limits

The full suite passes **593 tests**. Historical measured manifests still validate
**6,182** and **6,966** tokens. The active 08/10 CSV is unchanged and its daily total
remains **4,986**; these are separate historical invocations, not a new benchmark.

Regression coverage includes custom/no/multiple breaks, meeting overlap, default
and historic morning fallback, overtime gaps, midnight, weekdays/holidays, DST clock
rejection, short cluster windows, snapshot v5, profile changes, schedule tampering,
failure before collection and byte-stable assembly. Token regressions cover every
arrival order of conflicting/identical snapshots and corrupt CSV reports/updates.

F25's code is hardened; its actual-Claude-transcript acceptance and V01's installed
Claude invocation remain pending. This environment has neither a Claude CLI nor a
Claude project transcript directory. Synthetic transcripts do not satisfy those
live acceptance criteria. Existing Codex and source evidence can be revalidated
without new model calls. No external issue was closed or timesheet published.
