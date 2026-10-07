# Personal Pilot Timesheet Logger

Automated, deterministic timesheet logging skill for Claude Code that combines Git commits, Pull Requests, and Google Calendar into daily timesheet records.

---

## 1. Architecture

```text
  Git Commits          Pull Requests        Google Calendar
 (git log/REST API)   (GitHub REST API)    (API/explicit fixture)
       │                     │                    │
       └─────────────────────┼────────────────────┘
                             ▼
                [Script] Deterministic Collectors
                             ▼
                [Script] Normalizer & Deduplication
                             ▼
                [Script] Time Block Segmentation
                             ▼
                [Script] Minimal Payload Builder (< 350 tokens)
                             ▼
                [AI] Semantic Topic Grouping & Summary
                             ▼
                [Script] Deterministic Entry Assembly (PRs: #...)
                             ▼
                [Script] Idempotent Storage (JSON & Markdown)
                             ▼
             Timesheet & Audit Evidence + Token Tracking
```

---

## 2. Setup & Requirements

- **Python**: Standard Python 3.9+ (Zero third-party pip dependencies required; operates entirely using Python standard library: `json`, `subprocess`, `datetime`, `urllib`, `argparse`, `unittest`).
- **Git**: Configured locally with author identity (`git config user.name`, `git config user.email`).
- **GitHub**: Use an existing authenticated `gh`, an environment-only `GH_TOKEN` / `GITHUB_TOKEN`, or explicitly opt in to the existing Git credential helper with `github.use_git_credentials: true`. The helper is queried for `github.com` without interactive prompts; credentials remain in memory. Tokens are never part of the JSON profile. Git and PR collectors use the same read-only REST adapter. GitLab PR collection is not implemented.
- **Google Calendar (Optional)**:
  - Install optional Google dependencies with `python3 -m pip install -r requirements-calendar.txt`.
  - For initial desktop OAuth, run `python3 scripts/setup_calendar_oauth.py`; only `calendar.readonly` is requested. Existing tokens are preserved unless `--replace` is explicitly passed.
  - Live collection uses the authorized token; the client credentials file is used only for bootstrap.
  - ICS files and GitLab MR collection are unsupported. No configuration switch enables them.
  - Live collection requires an already-authorized `token.json`, `google-auth`, and `google-api-python-client`. Missing setup is reported as unavailable. The no-calendar workday fallback applies only after successful collection returns no events, or in an explicit demo.

---

## 3. Usage

### A. Via Claude Code Skill
Trigger phrases:
```text
"log today's work"
"log my work today"
"create today's timesheet"
"run my timesheet"
"log my work for 2026-10-06"
```

### B. Direct Command Line Execution
For personal multi-account collection, copy `config/example-github-config.json` to
`config/user-config.json`, then set your confirmed GitHub logins, author names/emails,
repository targets, and IANA timezone. This local profile is ignored by Git and loaded
relative to the scripts, so it also works when invoked from another directory.
An explicit `--config PATH` overrides the default profile. Only identity, repositories,
timezone, and Git credential-helper opt-in are wired in this profile; the legacy example's
workday, Calendar adapter paths, and token options are still separate audit work.

### One timezone for every entry point

Git, PR, Calendar, normalization, date resolution, blocks, and the standalone token
collector share `activity_settings.py`. Selection is **CLI `--timezone` > profile
`timezone` > `Asia/Ho_Chi_Minh`**. The profile is loaded relative to the repository,
not the current directory; the host clock's timezone and first source offset do not
select the day's zone. Calendar, normalizer and token CLIs also accept `--config`.
The normalized model persists that zone for block construction; a builder uses
the model's explicit zone, or the profile for a legacy model missing it.
Use IANA names such as `America/New_York`, so historical dates get their own DST
offset. Invalid explicit zones stop before output writes rather than falling back.

Day boundaries are `[00:00, next-day 00:00)` in that named zone, then converted to
UTC for GitHub and usage filtering. Such a day can be 23 or 25 elapsed hours across
DST. Calendar requests carry the zone name and per-boundary offsets. An aware event
keeps its instant; a Calendar wall time without an offset uses its `timeZone`, or
the selected zone when no source zone is present. Ambiguous/nonexistent DST wall
times fail collection rather than inheriting the host zone or guessing an instant.
Legacy normalized models with explicit `+07:00` offsets remain supported as fixed
offsets; new profiles/CLI input require named zones. Regenerate old exports to
include the selected IANA name; old data is not automatically rewritten.

```bash
python3 scripts/get_calendar_activity.py --config config/user-config.json --date 2026-10-06
python3 scripts/normalize_activity.py --config config/user-config.json --date 2026-10-06 \
  --commits-file commits.json --prs-file prs.json --calendar-file calendar.json
python3 scripts/collect_token_usage.py --config config/user-config.json --date 2026-10-06 \
  --session-file /path/to/session.jsonl --csv-path data/audit/session-tokens.csv
```

Token parsing uses each usage line's aware `timestamp` and the same local-day bounds,
not file mtime or all-session totals relabeled as the requested day. Missing/invalid
or timezone-less timestamps are skipped with diagnostics and do not establish zero
usage; CSV notes retain the selected zone. This fixes daily timezone attribution,
not run/session attribution: the pipeline still does not automatically collect a
run's actual AI usage (F22), and deduplication/schema hardening remains F25/F26.
Existing token CSV rows are not automatically migrated; use a separate audit CSV
when checking historical records.

Known GitHub author logins take priority. A foreign linked login cannot match your name
alias. Unlinked/local commits match exact configured email or name aliases, and retain
`identity_match` provenance. Name aliases are less conclusive than account/email identity;
configure them only for authors you have confirmed. Missing identities never select all
authors automatically. The standalone Git collector's explicit `--author '*'` is a diagnostic.

To run the end-to-end pipeline deterministically:
```bash
# Log today's work using local Git and default sources
python3 scripts/run_pipeline.py

# Log for a specific date
python3 scripts/run_pipeline.py --date 2026-10-06

# Override the shared Git/PR scope and personal account set
python3 scripts/run_pipeline.py --date 2026-10-06 \
  --repos owner/repository --github-users first-login second-login \
  --authors "Confirmed Author" "Other Confirmed Author" --timezone Asia/Ho_Chi_Minh

# Inspect live GitHub evidence without creating a timesheet
python3 scripts/get_git_activity.py --date 2026-10-06 --envelope --output data/audit/commits.json
python3 scripts/get_pr_activity.py --date 2026-10-06 --output data/audit/prs.json

# Query specific local repositories or remote GitHub repositories
python3 scripts/run_pipeline.py --date 2026-10-06 --repos octocat/Hello-World https://github.com/facebook/react .

# Explicit demo: outputs go under data/timesheets/demo/
python3 scripts/run_pipeline.py \
  --date 2026-10-06 \
  --calendar-fixture data/fixtures/sample_calendar.json \
  --prs-fixture data/fixtures/sample_prs.json
```

### Collection status and output safety

PR and Calendar collectors return a JSON envelope rather than a bare activity list.
Git supports the same envelope with `--envelope`; successful standalone legacy Git calls
still return a list. Pipeline runs always request envelopes from all three sources:

```json
{"source":"github","mode":"live","status":"success","items":[]}
```

- `status: success` with `items: []` means the source was queried successfully and has no activity for the selected day.
- `status: unavailable` means authentication, libraries, or configuration are missing; `status: error` means collection failed. Both include a `reason`, return exit code **2**, and never substitute sample data. Diagnostics go to stderr; JSON goes to stdout.
- Fixtures are used only through `--prs-fixture` / `--calendar-fixture` (or a collector's `--fixture`). Missing/malformed fixture files are errors.
- A run with any unavailable/failed source returns **2** and writes only collected evidence under `<output-dir>/drafts/YYYY-MM-DD.json` and `.md`, marked **INCOMPLETE**. It does not assemble timesheet entries, export AI input, or change final timesheets/token records.
- A successful run using any explicit fixture is marked **DEMO**. Its timesheet/collection manifest goes under `<output-dir>/demo/`; requested AI exports go into a `demo/` subdirectory beside the requested path. It does not update the production token CSV.
- Successful live collection writes to `<output-dir>` and records all source metadata, identity aliases, repository selection, and timezone in `YYYY-MM-DD.collection.json`, even when sources are empty. Generated entry JSON also retains collection metadata; demo Markdown has a visible banner.
- `normalize_activity.py --prs-file ... --calendar-file ...` accepts successful collector envelopes and legacy list fixtures, preserving envelope metadata. It rejects unsuccessful envelopes rather than treating them as empty sources.

The default output directory is `data/timesheets`. Remote Git/API failures are explicit;
local Git failure/invalid-path handling remains separate audit work. Primary Calendar
read-only access has been verified on the configured machine for an empty day; packaged
OAuth setup and real nonempty-event verification remain open.

### Daily reruns and manual edits

Each successful run replaces the **complete generated set for its target date**. Changed
or deleted intervals disappear; an empty successful day writes `[]` and a zero-total
Markdown table. Identical reruns leave JSON and Markdown bytes unchanged. Summary counts
include inserted, updated, removed, preserved manual rows, and overridden candidates.

Stored automatic rows carry `"provenance": {"kind": "generated", "generator": "timesheet_logger"}`.
Before editing an automatic row by hand, explicitly change its provenance:

- `{"kind": "manual"}`: keep this independent human row. Overlap with regenerated rows
  blocks saving and requires review.
- `{"kind": "override"}`: keep this human replacement and suppress the generated row
  with the exact same `(date, start, end)`. If regenerated intervals change and overlap
  it, saving is blocked until the conflict is reviewed.

Legacy JSON without provenance is **not automatically migrated or erased**, even if it
contains collection metadata. Back up the JSON/Markdown pair and classify a reviewed copy
of every old row as generated/manual/override before rerunning against that directory.
Use a fresh audit output directory while reviewing legacy logs; existing contaminated
examples remain unchanged. Markdown is a rendered view; make edits in the audit JSON and
mark their ownership explicitly.

Legacy, invalid-store, and manual-overlap conflicts return exit **2**, preserve the previous
timesheet, collection manifest, AI export, and token file, and write current evidence plus
proposed entries under `drafts/`. Source metadata in such a draft can still be `complete`:
collection succeeded, while `reconciliation.status` is `blocked`.

Standalone saving now requires an explicit date and assertion of successful full-day
collection, including when the input is empty:

```bash
python3 scripts/save_timesheet.py --entries-file entries.json \
  --date 2026-10-06 --collection-status complete --output-dir data/audit/my-run
```

`--collection-status demo` isolates standalone output under `<output-dir>/demo/`.
Do not pass a partial entry batch as a full-day snapshot. Source failures must remain
INCOMPLETE drafts and never reach daily reconciliation. This storage fix does not repair
overlapping generated events or estimated work-duration rules; those have separate audit items.

### Matching AI summaries to blocks

Exported AI input is an object with `blocks`, `unassigned_activity`, and `review`.
Each item in `blocks` carries `block_id`, for example `2026-10-06_09:30_12:00`. Return that exact
ID with the summary, independently of output order:

```json
[
  {"block_id": "2026-10-06_09:30_12:00", "description": "Improve payment validation."}
]
```

Partial output is allowed: blocks without AI summaries use their own deterministic
fallback, never another block's summary. Entry audit JSON retains `block_id` and
`summary_source: ai|fallback`, plus all original commit/PR/calendar evidence. The
input still omits commit hashes and raw author/API metadata.

Legacy `{date, block: {start, end}, description}` summaries must exactly match a
current candidate. Date-less legacy intervals are accepted only within one target
day with unique intervals. Position-only output, wrong/stale IDs, duplicate IDs,
contradictory metadata, and malformed or missing explicitly requested AI files
return exit 2 before final writes; the pipeline saves evidence and current AI input
in a review draft while preserving previous final/manifest/export/token files.

This validates block identity, not whether an AI sentence is factually correct or
whether the underlying sources changed since an earlier payload. A frozen snapshot
between preparation and final assembly remains F28. The CLI reads supplied AI JSON;
it does not invoke an external model itself.

### Scheduled and estimated intervals

Calendar events retain their actual titles and carry `time_basis: scheduled`.
This records scheduled time, not confirmed attendance. Calendar-only fallback
descriptions repeat supplied titles without inventing meeting topics.

A development gap is retained only when a commit or PR action has an aware
timestamp inside `[start, end)`. These rows carry `time_basis: estimated` and
`estimation_reason: calendar_gap_with_activity`; timestamps establish activity,
not continuous work throughout the interval. Successful empty Calendar results
with Git/PR activity still use the existing workday-window proposal, marked
`activity_workday_window`. An entirely empty day creates no rows.

Estimated rows have no synthetic Calendar titles. AI input includes `time_basis`,
and Markdown labels each interval, separates scheduled/estimated totals, and
calls a total containing estimates **Total Proposed Time**.

All development gaps before, between, and after Calendar events subtract the
current lunch interval `12:00–13:30` before applying the 30-minute minimum and
checking activity independently in each remaining interval. Scheduled Calendar
events overlapping lunch are retained whole. Lunch-only commit/PR evidence is
preserved separately for review, without attaching it to an unrelated interval.
Lunch times are currently hardcoded; reading configurable workday settings remains
D02. The no-Calendar morning-only `09:00–12:30` proposal remains D02; candidate
windows are now retained only when an aware timestamp actually falls inside them.

### Validated daily normalization

Normalization validates source arrays, record types, commit/PR identities and
Calendar intervals before producing a daily model. Aware timestamps are converted
to the selected timezone and sorted by their UTC instant. Changed representations
retain `original_timestamp`, `original_start` or `original_end` for audit.
The local day uses `[midnight, next midnight)`; intersecting Calendar events keep
their full extent until block construction clips it.

Missing, invalid, naive or other-day commit/PR timestamps go to
`unassigned_activity`, retaining each action without adding work duration.
Other-day Calendar events also remain review evidence. Malformed structure,
conflicting qualified commit records, or invalid/nonpositive Calendar intervals
block normalization: exit 2, raw evidence in `drafts/`, and no final timesheet,
manifest, AI input or token writes. Successful source collection can coexist with
blocked normalization; it does not imply a completed timesheet.
Standalone normalization rejects unreadable explicitly supplied files and preserves
existing output. Omitted optional source files retain the legacy empty-list behavior.
This validation is scoped to incoming activity; full storage schema hardening and
concurrent multi-file transactions remain separate findings.

### Activity without a matching interval

Commits and each PR action are assigned only by aware timestamp within `[start,end)`
on the selected local day. Unmatched evidence is never moved into the first work
block or an unrelated meeting. Missing/invalid timestamps, timestamps without a
timezone, wrong-day events, and timestamps outside all blocks have explicit reasons.
A scheduled event during lunch or outside the workday still accepts activity inside
its own interval; this fix does not classify breaktime or OT.

Unassigned events contribute no work duration. Their original normalized evidence
is stored in `YYYY-MM-DD.activity-review.json`, and Markdown shows them separately
under **Unassigned activity — review required**. The collection manifest links the
file, reports its count and `review.status`. COMPLETE means successful source
collection; it can coexist with required assignment/attendance review. A day with
only unmatched activity saves zero timed entries plus evidence, rather than inventing
a workday window. Supported no-Calendar proposals remain explicitly estimated.

AI input includes a compact, separate `unassigned_activity` list and an instruction
to summarize only `blocks`. Do not infer a block or work duration from unassigned
evidence. AI output remains a JSON array of keyed summaries. Old AI exports are
historical artifacts; regenerate the input with the current CLI before synthesis.

The standalone block CLI emits `{blocks, unassigned_activity}`. Preparation and
entry assembly accept this envelope or legacy arrays; assembly preserves review
evidence in `{entries, unassigned_activity}` for the save CLI. The save CLI also
accepts `--unassigned-activity-file review-array.json`: omission preserves an
existing review sidecar; an explicit `[]` clears it. Successful pipeline reruns
replace the complete review list, re-render review-only changes, and preserve bytes
on exact reruns. Invalid existing/incoming review stores stop final writes; source
failure preserves review alongside other outputs. Demo review stays under demo/.
Multi-file transaction/concurrency work remains F29; no automatic legacy migration.

### All-day context and daily Calendar scope

All-day events preserve `all_day: true` and their start/exclusive-end dates.
They are separated into `calendar_context`, never added to work durations or AI
time-block payloads. A deadline/holiday label alone does not establish hours worked
or make the logger discard Git/PR activity. An all-day-only day has zero entries
and zero minutes, with context shown below the Markdown timesheet and saved in
`YYYY-MM-DD.calendar-context.json`. The source manifest links that file and reports
the context count. Source Calendar count includes timed and all-day records.

Live and explicit fixture adapters select events overlapping the requested day,
including events beginning the previous night. Timed blocks are clipped to the
selected timezone's half-open local day, retaining original normalized event
boundaries in source evidence. An event 22:00–02:00 yields 22:00–24:00 on the first
day and 00:00–02:00 on the next day, each 120 scheduled minutes. An explicit timed
00:00–24:00 event remains timed; it is not guessed to be all-day. UTC elapsed minutes
are used for durations across offset changes. Scheduled time does not confirm attendance.

Context changes/deletions update the sidecar and Markdown on successful reruns.
Source or validation failures preserve context alongside other final outputs.
Standalone saving accepts `--calendar-context-file context-array.json`; omission
preserves existing context and a supplied `[]` clears it. Demo context is isolated
under demo/. Existing untyped midnight legacy files are not automatically migrated.
Breaktime/OT classification, workday policy, wider Calendar filters/pagination,
and transactional multi-file persistence remain separate audit work.

### Overlapping Calendar events

Events are partitioned at every start/end boundary, retaining each active event's
original title/start/end under `sources.calendar_events`. For A 09:00–10:00 and
B 09:30–10:30, the proposal is A 09:00–09:30, A+B 09:30–10:00, and B 10:00–10:30:
90 scheduled minutes rather than 120. Identical intervals share one block ID and
retain both sources. Touching intervals are not overlaps. Calendar source records
are normalized title/start/end records; provider event IDs remain unavailable.

Conflicting intervals carry `calendar_overlap: true` and
`review: {status: required, reasons: [calendar_overlap], attendance: unconfirmed}`.
AI input includes the conflict and unconfirmed attendance. JSON, descriptions,
Markdown and CLI preserve the review notice even with supplied AI summaries.
Totals containing conflicts are **Total Proposed Time**, never a claim of confirmed
attendance. Source collection may be COMPLETE while attendance still needs review.
The overlap is counted once in scheduled coverage, not added again as another total.
Automatic attendance selection or confirmation is not implemented. A reviewer must
decide which event was attended and for how long before treating the proposal as
actual meeting time. Exact duplicate normalized records are already deduplicated.

#### Remote GitHub Repositories
The Git collector (`scripts/get_git_activity.py`) supports uncloned remote GitHub repositories in addition to local directories:
- **Bare slug**: `--repos owner/repo`
- **HTTPS URL**: `--repos https://github.com/owner/repo` (or `.git` / subpath variants)
- **SSH URL**: `--repos git@github.com:owner/repo.git`

Remote commits use the repository's **default branch** and fetch all result pages. The API
date filter follows GitHub's commit chronology; the collector then filters author timestamps
against the selected local day. Complete all-branch/backdated-author coverage remains F39.

PR collection resolves the same selected GitHub repositories, lists updated PR candidates,
and retrieves submitted reviews and merge details through REST endpoints. It does not use
`updatedAt` as an action timestamp. A merge is relevant when you authored the PR, merged it,
or submitted a review before that merge. Pending reviews are excluded. References retain
full `owner/repo`; each reference has an `events` array with action, actor, and local timestamp.
Opening/review/merge actions survive normalization and are associated with their own blocks;
references are deduplicated within each block. Remaining block/time issues are
tracked under F05–F08 and D02.

Collectors use a half-open local day `[00:00, next-day 00:00)` in the configured IANA timezone.
For `2026-10-06` in Vietnam, that is `2026-10-05T17:00:00Z` through, but excluding,
`2026-10-06T17:00:00Z`.

### C. Running Unit Tests
Run the deterministic unit tests and F01 source/pipeline regressions:
```bash
python3 -m unittest discover tests
```

---

## 4. Script vs AI Split

| Responsibility | Type | Handled By |
| :--- | :---: | :--- |
| Date & timezone calculation | `[Script]` | `normalize_activity.py` |
| Commit extraction & author filtering | `[Script]` | `get_git_activity.py` |
| PR retrieval & deduplication | `[Script]` | `get_pr_activity.py` |
| Calendar retrieval | `[Script]` | `get_calendar_activity.py` |
| Workday interval & time blocking | `[Script]` | `build_time_blocks.py` |
| Duration computation | `[Script]` | `build_time_blocks.py` |
| Stripping raw metadata & ticket extraction | `[Script]` | `prepare_ai_input.py` |
| Semantic topic grouping & summary | `[AI]` | LLM with minimal input |
| Formatting `PRs: #...` suffix | `[Script]` | `build_timesheet.py` |
| Idempotent storage (JSON + Markdown) | `[Script]` | `save_timesheet.py` |
| Token usage tracking | `[Script]` | `collect_token_usage.py` |

---

## 5. Idempotency & Storage

- **Audit JSON**: `data/timesheets/YYYY-MM-DD.json` contains full source evidence (commit hashes, calendar event titles, PR numbers).
- **Human Review**: `data/timesheets/YYYY-MM-DD.md` contains a clean GitHub Flavored Markdown table.
- **Idempotency**: Entries are keyed by `(date, start_time, end_time)`. Running the skill multiple times safely updates or preserves existing rows without creating duplicates.

---

## 6. Troubleshooting

1. **GitHub authentication unavailable**:
   - Error: `gh: command not found` or not logged in.
   - Solution: Use one of the GitHub authentication mechanisms described above. A credential that can read a repository may lack the extra `read:org` scope required by `gh auth login`; opt-in reuse through the existing Git helper or an environment token can still access the REST endpoints. For demos, explicitly select both fixtures. An unavailable source produces an incomplete draft.
2. **Google Calendar not configured**:
   - Notice: Google Calendar credentials not found.
   - Solution: Live collection needs the optional Google libraries and an already-authorized root-level `token.json`; `credentials.json` alone does not authorize collection. OAuth bootstrap instructions remain a separate setup task. Use `--calendar-fixture` explicitly for a demo; there is no automatic sample retrieval.
3. **No commits detected**:
   - Configure all confirmed logins and exact name/email aliases in your profile. Use pipeline `--authors "<name>"` or standalone Git `--author "<name>"` to override. Unlinked GitHub commits require a confirmed name/email alias. Remote queries cover the default branch.
4. **No Calendar events**:
   - The logger automatically generates morning (`09:00–12:00`) and afternoon (`13:30–17:30`) blocks based on commit timestamps.
5. **Token file not found**:
   - If `~/.claude` has no transcripts yet, `collect_token_usage.py` initializes `data/token-usage.csv` with standard headers without error.
6. **Timezone mismatch**:
   - All timestamps respect local timezone offset (e.g. `+07:00`). Commit timestamps near midnight are correctly attributed to the local calendar day.

### Source configuration and audit identities

GitHub is the supported Git/PR provider. GitLab and ICS adapters are not implemented
and unused configuration switches have been removed. Calendar supports CLI
`--calendar-token`, `--calendar-credentials`, `--calendar-ids`; exported
`GOOGLE_CALENDAR_TOKEN`/`GOOGLE_CALENDAR_CREDENTIALS` override profile paths.
Profile-relative paths resolve against the profile directory; CLI/env paths resolve
against the invoking working directory, and defaults use the repository root.
`TIMESHEET_REPOS` is comma-separated, below CLI and above profile. `.env` is not
automatically loaded: export individual variables in your shell.

Google Calendar pages are exhausted using `nextPageToken`; malformed/repeated tokens
or a failed later page report source error rather than complete partial data.
Calendar evidence keeps event ID, calendar ID and source alongside original bounds;
identical-looking events with different IDs remain distinct for overlap review.
See [Google pagination](https://developers.google.com/workspace/calendar/api/guides/pagination).

Commit identities use owner/repository when a GitHub origin exists; otherwise a
canonical absolute local-path identity prevents basename collisions. Equal PR numbers
from different repositories are qualified as `owner/repo#N` in ambiguous suffixes
and kept distinct in AI input. Calendar evidence is escaped in Markdown table cells.

Local Git covers all refs, filters author dates and is bounded by
`--max-local-commits` (default 10000) and a 60-second query timeout. Exceeding the
bound is an error requiring an explicit larger bound, never a successful truncated
result. Remote Git scans default-branch history with `--max-remote-commits` (default
10000), then filters author dates. It deliberately avoids the API's committer-date
since/until filter, which can exclude backdated author events. Exceeding a bound
reports error, so large repositories need an explicit larger bound. Branch/file GitHub URLs are rejected: supply owner/repo
or use a local checkout when all-ref author-date coverage is required.

Calendar policy approved on 2026-10-07: default primary; cancelled and self-declined
events are excluded. All-day events are context only. Overlaps require attendance
review. Keep the entire day's schedule, including future meetings, as proposals.
JSON scheduled rows have `attendance: unconfirmed`; Markdown explicitly states
“Theo lịch, chưa xác nhận tham dự”. Accepting an invitation does not establish
attendance, and scheduled/estimated totals are not measured working hours.
