# F09 validation: one authoritative named timezone

The pipeline's GitHub fixes already wired timezone into Git/PR collection, and F07
made block construction respect the normalized zone. Remaining entry points used
host offsets, first-source inference, or relabeled entire token sessions as a day.
F09 completes the named-zone configuration path without merging prerequisite PRs.

## Behavior

- CLI `--timezone` overrides profile `timezone`, which overrides the named default
  `Asia/Ho_Chi_Minh`. Shared resolution lives in `activity_settings.py`; invalid
  explicit zones stop rather than falling back. The default profile is repo-relative.
- Calendar, normalizer and token CLIs accept `--config`/`--timezone`, like Git/PR and
  the orchestrator. Default dates use the selected zone, independent of host `TZ`.
- New normalized models persist the named zone; the builder respects that model.
  Missing legacy zone uses the profile, never the first event/commit or host offset.
  Explicit legacy normalized offsets remain fixed-offset compatible; new profiles
  and CLIs require IANA names. No old model/export/data is automatically rewritten.
- Historical local midnights are converted independently to UTC. GitHub/PR and
  token filtering share half-open boundaries; DST days can last 23 or 25 elapsed hours.
  Calendar requests include the zone name and the correct per-boundary offsets.
- Aware source timestamps retain their instant. GitHub naive author timestamps fail;
  local Git does not convert naive timestamps through the host zone. Wider invalid
  record handling remains F10/F18. Naive Calendar wall times use their source
  `timeZone`, or the selected zone. Ambiguous/nonexistent wall times during DST fail
  rather than guessing. Complex repeated-clock representation remains wider review work.
- Token transcript usage is filtered by each line's aware `timestamp`, not file mtime
  or a session-wide total assigned to the requested date. Missing/invalid/naive
  timestamps are reported and skipped; this is not evidence of zero usage. CSV notes
  retain the selected zone. Existing CSV rows are not automatically migrated.

## Verification

**310/310 tests pass**, 31 new F09 tests (including the related F23 reproduction); `git diff --check` passes. Covered precedence,
explicit invalid-zone rejection, named historical offsets, repo-relative default
helpers, legacy offsets, model/profile authority, date boundaries, Git/PR filtering,
Calendar query bounds/source-zone/naive-DST handling, elapsed daily clipping, token
per-line local-day filtering including both repeated-hour instants, missing/invalid
timestamps, mtime independence, standalone CLIs under three host zones, overrides,
preserved outputs on errors, and pipeline propagation through manifest/AI/storage.

Synthetic reproduction under host `TZ=UTC`, target `America/New_York`:

| Input | Before F09 | After F09 |
|---|---|---|
| Calendar 2026-01-01 09:00 wall time, no offset | 04:00 -05:00 (host interpreted as UTC) | 09:00 -05:00 in selected zone |
| Transcript: 10 tokens before local midnight, 20 after | Both requested days receive all 30 | Previous day 10, next day 20 |

Synthetic records are explicitly separate from live output. No real private Claude
transcripts or actual AI usage were used for these tests.

Four real-data pipeline runs on 2026-10-07 used the existing Vietnam profile and
host `TZ=UTC`, with **no `--timezone` override and no source fixtures**:

| Selected day | Git | PR references | Primary Calendar | Result |
|---|---:|---:|---:|---|
| 2026-10-06 (two runs) | 15 | 7 | 0 | COMPLETE / exit 0, one estimated 240-minute row, 12 unassigned events |
| 2026-10-07 (two runs) | 0 | 3 | 1 | COMPLETE / exit 0, scheduled 15:00–16:00 / 60 minutes, 3 PR actions unassigned |

All sources were `success/live`; every manifest used `Asia/Ho_Chi_Minh`. Both exact
reruns preserved JSON/Markdown/manifest/review-sidecar/AI-export bytes. Source
completion remains separate from assignment/attendance review. The three Oct 7 PRs
are #55/#56/#57, opened before the afternoon meeting; they remain separate review
evidence. Ten old data/config files and both OAuth files were hash-checked unchanged;
no credentials/token were displayed or staged. Token initialization ran in the
isolated audit working directory, preserving the old production CSV.

Local ignored artifacts: `data/audit/f09-authoritative-timezone-20261007-010513/`
contains `verification.json`, `synthetic-before-after.json`, live day directories,
AI exports and logs. Google/NY historical DST behavior is covered by mocks/synthetic
tests, not a live Calendar in New York. Live Calendar verification used the
existing Vietnam account with its real event. No Calendar edits or external AI API calls.

## Remaining scope

F22 still owns automatic integration of actual AI usage; the orchestrator currently
initializes CSV with no collected usage records. The related F23 cross-day totals
bug is corrected by per-line day filtering. F24 run isolation, F25 deduplication
and F26 schema/numeric validation remain open. F10 broader source
validation, F19 Calendar setup/paths, F27 workday/configuration, D01/D02/OT policy,
F28 frozen snapshots, and F29 transactions/concurrency remain separate. This fix
does not introduce OT/breaktime classification or migrate old production data.
The branch depends on unmerged F08 / PR #57.
