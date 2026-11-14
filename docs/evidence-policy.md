# Evidence and allocation policy

How sources become proposed time, what counts as complete, and how output is stored.

## Completeness and Calendar

COMPLETE means every required source returned success, including valid empty lists.
It does not confirm attendance, continuous work or completion of human review.
Failed/unavailable sources produce an INCOMPLETE draft with all collected evidence
and exit 2. Invalid normalization/AI/storage produces a review draft or controlled
error and preserves old final files. Explicit fixtures produce isolated DEMO output.
No source failure silently enables fixtures.

Keep the full day's schedule, including future meetings. Scheduled rows state
**Theo lịch, chưa xác nhận tham dự** and attendance: unconfirmed. Cancelled and
self-declined events are excluded. Other invitees declining does not exclude your
meeting. All-day events are context only, never durations. Timed events are clipped
to the selected local day and partitioned at overlaps, counting scheduled coverage
once; overlaps require attendance review. Original event/calendar IDs, source,
response status and bounds remain audit evidence when available.

## Commit intervals (current profile)

Set `block_policy` to `{"strategy": "commit_intervals"}`. Each run requires daily
hours: `--work-day-start HH:MM` for the approved morning / five-hour afternoon
shorthand with OT, or explicit `--work-windows` for custom main windows. Direct
Python `--work-start HH:MM` retains the legacy start-only behavior below. The start
is supplied by the user for the selected date in the configured timezone. The example above uses an illustrative 09:00; never assume it.
Passing `--work-start` also selects this strategy for older profiles. Optionally
pass `--work-end HH:MM` (or `24:00`) to include work after the last commit. Without
an end, allocation stops at the final commit. Neither clock is a reusable profile
default. Prepare freezes the daily confirmation in the snapshot; assemble rejects
clock overrides. Changed hours require a new snapshot.

- Allocate confirmed start → first commit, then previous commit → next commit.
- Subtract configured breaks (default **12:00–13:30**) and the union of scheduled Calendar intervals.
  A crossing interval becomes separate rows. Calendar rows remain scheduled,
  attendance-unconfirmed proposals, including lunch/future events.
- New pipeline runs resolve each commit's GitHub PR associations and merge only
  adjacent development pieces with exactly one common repository-qualified PR.
  With a successful empty PR lookup, one shared ticket in the same repository
  also permits merging. Unknown lookups, multiple PRs/tickets and unlabelled
  commits remain separate; short duration alone never permits merging.
- Group after splitting around breaks, Calendar and NORMAL/OT boundaries. Keep
  confirmed-end tails separate. Same-minute commits still share a timing boundary;
  conflicting work identities in that minute are not guessed or subdivided.
- Snapshot v9 freezes `adjacent_pr_or_ticket_v1` and the lookup results. V1–v8
  replay their previous rules, including historical short-allocation merging.
- Additional breaks can be configured; no idle-gap splitting, padding to 20 minutes or 90-minute cap.
  The confirmed start can be outside the old 09:00–17:30 work windows; no OT label
  is inferred. This strategy assumes continuous work between commit boundaries.
- Floor commit boundaries to the minute; retain original source timestamps.
  Same-minute commits share an interval. The closing commits describe every split
  piece, including a piece ending before lunch/a meeting. JSON `allocation` records
  this relationship; the commit need not lie inside each piece. Do not count these
  repeated source references as extra commits or extra time.
- PR actions normally attach by [start,end) timestamp and never create more time.
  A merge event in the same minute as a closing commit can instead attach to that
  allocation's last work piece when its merge SHA and repository match. Keep the
  original event timestamp and record the association; never extend confirmed hours.
  Events outside available intervals remain in review. Commits outside confirmed
  hours do not extend development time. A commit exactly at start adds no time.
- Development blocks require an assigned commit or PR. Confirmed hours alone do
  not create generic development/focus entries; unsupported windows and closing
  tails stay blank. Calendar rows remain independently eligible. New snapshots
  freeze this rule in schema v10; older snapshots replay their original behavior.

Example: start 09:00, commits 10:10 / 11:40 / 14:10 / 16:00, no Calendar:
09:00–10:10 (70m), 10:10–11:40 (90m), 11:40–12:00 (20m),
13:30–14:10 (40m), 14:10–16:00 (110m). Total: **330m proposed**.
Confirmed hours and allocation metadata survive into the final JSON. Development
remains `estimated`: commit boundaries allocate time, not measure task duration.
For example, commits at 10:00 / 10:10 / 10:25 that resolve to the same PR become
one 09:00–10:25 row (85m), containing all three commits. New pipeline snapshots use
schema v9 to freeze PR associations and grouping, with payload v6 for session
summaries. Earlier schemas retain their original rules: v8 default OT, v7 manual
OT review, v6 daily windows, v5 profile schedules and older allocation/short-commit
merging policies. Changed allocations or grouping requests require a new prepare.

## Configurable work schedule

`work_schedule` in the profile controls regular hours, breaks and additional overtime
windows. Its default is **09:00–12:00 / 13:30–17:30**. See
[the schedule policy and examples](work-schedule.md). For example:

```json
{
  "work_schedule": {
    "start": "08:30",
    "end": "17:00",
    "breaks": [{"start": "12:00", "end": "13:00"}],
    "weekdays": [0, 1, 2, 3, 4],
    "holidays": ["2026-12-25"],
    "overtime_windows": [{"start": "18:00", "end": "20:00"}]
  }
}
```

Weekdays use 0 = Monday through 6 = Sunday; the default keeps all seven days to
preserve existing behavior. Holidays are explicit dates, not inferred from a locale.
Without confirmed daily hours, development requires evidence inside an enabled
window and cannot fill breaks, nonworking days or the gap before overtime. A daily
`--work-start` explicitly permits work outside regular/day limits; configured breaks
and Calendar still subtract from commit intervals. Calendar proposals are retained
on all days. Breaks are exclusions, not worked rows; no automatic BREAK/OT label is
assigned. Prepare/normalize freeze the schedule; assemble never reloads it from a
changed profile. Invalid or overlapping intervals block before source collection.

## Previous policies and source scope

Older strategies and frozen snapshots remain reproducible. In those strategies,
a commit or PR action attaches only to its [start,end) interval. Unassigned evidence
is retained separately and adds no duration. With `block_policy.strategy` set to
`activity_clusters`, development timestamps are grouped until the configured idle
gap or maximum block length is reached. Boundaries are rounded to 15 minutes, kept
within configured work windows and marked for human review. A dense batch of PR
merges therefore supports one short administrative block rather than an entire
half-day or one invented duration per PR. Profiles without an explicit policy retain
the legacy strategy, bounded by the frozen schedule in new pipeline runs. Old models
without a schedule retain their historical half-day behavior, including the former
12:30 morning-only end. Timestamps do not prove continuous work. Automatic BREAK/OT
labeling remains unsupported. Scheduled meetings during lunch or outside work hours
remain proposals. Totals are Total Proposed Time when scheduled/estimated rows exist.

PR scope (D04): selected GitHub repositories and confirmed accounts, with actual
opened/reviewed/merged timestamps. Authored opening, submitted personal reviews and
merges of authored/personally reviewed/personally merged PRs are relevant. Pending
reviews are excluded; updatedAt is not work time. Every action retains actor and
qualified repository reference.

Local Git scans all refs and author dates with --max-local-commits (default 10000)
and 60-second timeout. Remote Git scans the default branch's history, then filters
author dates, bounded by --max-remote-commits (default 10000). A bound exceeded is
an error, not a truncated successful day. Increase it explicitly for large repos.
Remote collection does not claim all-branch coverage. Use owner/repo or a checkout;
branch/file GitHub URLs are rejected. Local paths without GitHub origin have
canonical path identities to avoid basename collisions.

## Storage and reruns

Daily JSON/Markdown, collection manifest, optional context and unassigned-review
sidecars form the auditable output. Successful snapshots replace the entire generated
set (D05), preserving explicit manual/override rows. Exact overrides suppress an
automatic interval. Overlap conflicts and legacy rows without ownership block for
review; no automatic migration. Exact reruns preserve bytes. Corrupt stores remain
for review. POSIX writer locks and atomic per-file replacements protect updates;
a recovery journal rolls back failed/interrupted bundles. Readers ignoring locks
may see intermediate files; this is recoverable multi-file storage.

Work-log descriptions, timesheet previews and final reports are generated in English
for NORMAL and OT entries. Clarifying conversation may use the user's language. Both
summary strategies translate non-English evidence while retaining ticket keys
and proper names. Without AI, English templates describe the available evidence
or scheduled calendar activity; original titles/messages remain in `sources`.
Calendar attendance remains unconfirmed. Existing saved logs are not rewritten.
