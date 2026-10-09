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
  still excluded. During prepare, new pipeline runs group adjacent pieces by verified
  PR or a unique ticket after a successful empty PR lookup. Payload v6 then permits
  AI to group related implementation, fixes, tests and integration into a shared
  work session during summary, even across feature/PR boundaries;
  Python revalidates boundaries and preserves all minutes and evidence. See
  [the grouping review](workflow-steps.md). Older snapshots retain their rules.
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
  final commit, using estimated duration. PR/ticket grouping happens after
  gaps/Calendar exclusions and never absorbs the confirmed-end tail.
- Snapshots with explicit windows use **v6** and freeze the canonical windows
  inside `work_confirmation`. Assembly cannot change them, does not collect again,
  and replays them even if the profile changes. V1–v5 retain their prior behavior.

## OT outside the main windows

Codex range skills prepare with `--review-ot`. Main windows define NORMAL,
including an earlier/custom shift. Under the user's approved standing rule,
each outside-main commit creates an estimated **60 minutes ending at that commit**
(at minute precision). New v8 snapshots use `defaulted` approval and proceed to
summary/assembly without a question, reply or waiting period. The preview shows
the default estimate and allows user-requested changes. PR/Calendar activity alone
does not create a default commit hour; Calendar attendance remains unconfirmed.

Only the part outside main, outside breaks and within the target local day counts.
New range runs exclude the frozen profile's configured breaks (default
12:00–13:30). Morning-start shorthand always excludes its fixed 12:00–13:30 lunch,
even if profile breaks differ. A lunchtime commit remains evidence for review;
it does not establish that lunch was worked. Explicit user-supplied OT windows
remain overrides. Historical snapshots retain their recorded policy and totals;
prepare a new run to apply the corrected default.
Overlapping,
duplicate and adjacent OT windows are united before allocation, preserving all
commit evidence without duplicate minutes. With main ending 16:00:

- Commit 18:00 → OT 17:00–18:00 (60m), leaving 16:00–17:00 excluded.
- Commit 16:20 → OT 16:00–16:20 (20m); 15:20–16:00 is already NORMAL.
- Commits 18:00 and 18:30 → OT union 17:00–18:30 (90m).
- Commits 18:00 and 21:00 → 17:00–18:00 / 20:00–21:00 (120m), keeping the gap.
- Commit 00:30 → 00:00–00:30 (30m) on the selected date; no minutes are moved to
  the previous day's snapshot. Ambiguous DST clocks that cannot be represented
  faithfully in HH:MM are rejected rather than silently changing duration.

When the user requests an override, preserve the original and derive a new
snapshot from its frozen sources:

```bash
python3 scripts/run_pipeline.py --phase confirm-ot \
  --snapshot data/audit/my-run/activity.json \
  --resolved-snapshot data/audit/my-run/activity-ot-override.json \
  --ot-windows "17:30-18:00" \
  --export-ai-input data/audit/my-run/ai-input-ot-override.json
```

For no OT, replace `--ot-windows` with `--decline-ot`. Then summarize and assemble
the new snapshot. It records an explicit override, a new run ID and parent linkage;
no source collection is repeated. New rows distinguish `default_commit_hour`
from `user_override` in `overtime_confirmation.approval_basis`. Hours remain
estimated, not measured attendance. NORMAL/OT boundaries split rows with shared
allocation topics, adjacent allocations with the same verified PR/ticket merge only within the
same type, and the writer rejects incorrect classifications. Markdown and the
collection manifest include separate NORMAL/OT totals.

No BREAK input or work row is added. Morning-start skill requests now use
`--work-day-start`, which includes OT. Direct Python requests without `--review-ot`
or `--work-day-start` retain their existing behavior. V1–v7 snapshots
replay their frozen rules; an old v7 pending decision still needs actual user hours,
and is not silently upgraded to the new default. V8 freezes the policy, default
windows, approval basis and overrides.

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

## Morning-start shorthand

`$personal-timesheet 08:30` and the launcher now use `--work-day-start 08:30`.
This expands the user-approved default to 08:30–12:00 and 13:30–18:30, with five
hours in the afternoon. The fixed lunch gap replaces profile breaks for this date;
profile settings are preserved. `--work-day-start` automatically enables default
OT for commits outside the two NORMAL windows, including early-morning commits.
Main windows and OT policy are frozen in snapshot v8. Full main coverage, including
the 18:30 closing tail without a commit, remains an estimate, not measured work.

```bash
.venv/bin/python scripts/run_pipeline.py --phase prepare \
  --config config/user-config.json --date 2026-10-09 \
  --work-day-start 08:30 \
  --snapshot data/audit/my-new-run/activity.json \
  --export-ai-input data/audit/my-new-run/ai-input.json \
  --output-dir data/audit/my-new-run/timesheets
```

Only a morning start before 12:00 is valid in this mode. Use explicit
`--work-windows` for afternoon starts or other hours. The default cannot be mixed
with `--work-start`, `--work-end` or `--work-windows`, nor passed to assemble or
confirm-ot. The latter phases use the existing frozen hours. Direct Python
`--work-start` still keeps its earlier semantics; new skill shorthand uses the
new flag. Explicit user-supplied ranges override the default rather than expanding
or extending them.

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
