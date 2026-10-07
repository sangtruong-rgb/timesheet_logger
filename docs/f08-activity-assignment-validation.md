# F08 validation: timestamp assignment and unassigned evidence

F08 removes arbitrary unmatched commit/PR routing. A real PR opened at
00:02:12 +07:00 had appeared in the 15:00–16:00 Calendar row. The row now contains
only its scheduled event; the PR remains separate review evidence with no duration.
Aware direct matching improved in F04/F07; this change completes unmatched routing.

## Deterministic behavior

- Assign only aware timestamps within the selected local day's half-open blocks.
- Expand PR action history before matching; each action is assigned or reviewed.
- Preserve unmatched normalized evidence and a reason: missing/invalid/naive
  timestamp, outside target day, or outside all blocks. Never pick a fallback block.
- Retain no-Calendar workday proposals only with activity inside them, still marked
  estimated. Unmatched-only days have zero timed entries and full review evidence.
  The existing supported morning 09:00–12:30 policy remains pending D02.
- Export AI input as `{blocks, unassigned_activity, review}`. Only summarize blocks;
  unmatched evidence is compact review context without raw author/hash/time/URL data.
  Keyed AI output remains an array. Standalone CLI envelopes preserve review evidence
  through assembly/save; legacy array input remains accepted.
- Save original evidence in the daily activity-review sidecar and render it separately
  in Markdown, outside durations. Link count/path/review status in the manifest.
  COMPLETE source collection can coexist with required human review.
- Successful reruns replace/clear review evidence. Exact reruns preserve bytes;
  review-only changes re-render Markdown. Invalid incoming/existing review stores
  block final writes. Source and AI-validation failures retain previous review/files.

## Automated verification

`python3 -m unittest discover -s tests`: **279/279 pass**, 34 new F08 tests.
`git diff --check` passes. Covered: actual bug shape, fallback removal, UTC/offset
equivalence, start/end/day boundaries, missing/invalid/naive timestamps, short-gap
activity, scheduled lunch/late meetings, no-Calendar support, action conservation,
AI isolation, standalone envelopes/malformed input, review-only and zero-entry
storage, reconciliation/idempotency/clear/preserve, source/AI failure, corrupt
sidecars, explicit demo isolation, and coexistence with overlap attendance review.
Existing F05 tests now assert unmatched lunch evidence remains outside blocks;
existing AI export tests read the new envelope's `blocks` array.

## Real-data verification on 2026-10-07

Audit folder (ignored, local): `data/audit/f08-unassigned-activity-20261007-004429/`.
Four runs, two per selected date, used authorized live GitHub and primary Google
Calendar, with no fixture substitution or Calendar edits.

| Date | Git commits | Unique PR references | Calendar | Timed proposal | Unassigned events |
|---|---:|---:|---:|---|---:|
| 2026-10-06 | 15 | 7 | 0 | One estimated 240-minute row | 12: 8 commits + 4 PR actions |
| 2026-10-07 | 0 | 2 | 1 | One scheduled 15:00–16:00 / 60-minute row | 2 PR actions: #55 and #56 |

Every source was `success/live`; all four runs returned COMPLETE/exit 0 with
`review.status=required`. Both exact reruns preserved JSON/Markdown/manifest/review
sidecar/AI export bytes. Oct 6 has eight actual PR actions across seven references:
four assigned plus four unmatched. The existing real F07 snapshot's 15 commit
identities and eight action identities exactly equal the new assigned + unmatched
sets, without loss or duplication. Oct 7's PR #55 at 00:02:12 and #56 at 00:20:58
are outside the afternoon meeting. The meeting description is now
`[Intern] Kickoff Meeting. PRs: None`.

Ten pre-existing data/config files and both OAuth files were hash-checked unchanged.
Credentials/token were never displayed or staged. Token output used the audit run
directory. Synthetic before/after evidence is explicitly marked demo and separate
from live output. No external AI API was invoked; live runs used script fallback.

## Remaining limits

Unassigned does not mean irrelevant, unworked, or confirmed overtime. Human review
must decide how to account for it; this fix adds no OT/breaktime classification or
automatic duration. Scheduled Calendar time does not confirm attendance, including
future events. F09/F10 broader validation, D01/D02 policy, F28 frozen snapshots,
F29 multi-file transactions/concurrency, and wider Calendar coverage remain open.
No old production output or ambiguous legacy record was automatically migrated.
This branch depends on unmerged F07 / PR #56; do not merge prerequisites implicitly.
