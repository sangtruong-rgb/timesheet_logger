# Personal timesheet logger

Build a reviewable daily proposal from real Git commits, GitHub PR actions and
Google Calendar. Python performs collection, normalization, interval math, matching,
validation and storage. AI optionally summarizes text; the pipeline CLI does not
call an LLM. The optional [Codex runner](docs/codex-usage.md) calls the installed CLI
and records measured usage for its isolated summary invocation.
GitHub and Google Calendar are supported. GitLab and ICS adapters are not implemented.

## Runtime and setup

Hướng dẫn macOS/Linux trên máy công ty: [company-machine-run.md](docs/company-machine-run.md), gồm nguồn thật, skill và usage acceptance.

Test bằng Codex CLI thay cho Claude: [cài CLI độc lập, venv và chạy pipeline](docs/codex-usage.md).

Supported runtime: Python 3.11+ on macOS/Linux (POSIX file locks), plus Git. Validation
here used Python 3.14.6; the minimum version has not been separately executed.
Core scripts use the standard library. Live Calendar also requires:

```bash
python3 -m pip install -r requirements-calendar.txt
cp config/example-config.json config/user-config.json
```

Set confirmed names/emails, GitHub logins, repositories and IANA timezone in the
ignored profile. Never commit OAuth files, tokens or personal config.
GitHub authentication precedence is GH_TOKEN/GITHUB_TOKEN, authenticated `gh`, then
an existing Git credential helper only when opted in with --use-git-credentials or
profile github.use_git_credentials. REST calls fetch commits, PRs and submitted
reviews; local commits use `git log --all`. A missing source is never replaced by
samples. `gh api` is used when gh authentication is available; direct HTTPS is an
alternative with an environment/helper token.

For Calendar, enable Google Calendar API and create a Desktop OAuth client. Put
credentials.json in the repository root or configure its path. Authorize readonly:

```bash
python3 scripts/setup_calendar_oauth.py --config config/user-config.json
python3 scripts/get_calendar_activity.py --config config/user-config.json --date 2026-10-07
```

For Codex CLI on macOS, use the project launcher when live collection needs the
GitHub credential store and outbound Calendar access:

```bash
./bin/personal-timesheet-codex
```

For a short request with your confirmed start time:

```bash
./bin/personal-timesheet-codex 09:00
```

Multiple confirmed windows for today (preview only):

```text
$personal-timesheet 8:00-12:00, 1h30-4:00
$personal-timesheet-windows 8:00-12:00, 1h30-4:00
```

From the terminal, run `./bin/personal-timesheet-codex "8:00-12:00, 1h30-4:00"`.
Both skill names use the same pipeline: 08:00–12:00 and 13:30–16:00 are the
NORMAL main windows. Each outside-main commit defaults to an approved estimated
hour ending at its minute-floored timestamp, counting only the portion outside
main and merging overlaps. No confirmation reply is required. The preview shows
the default intervals; requested edits or no OT use the same frozen evidence,
without recollection. NORMAL and OT totals are separate. Add a date to apply the windows to that date. These windows replace
profile hours/breaks only for this run. See [daily work windows](docs/work-schedule.md#confirmed-daily-windows).

Or type `$personal-timesheet 09:00` inside an existing Codex CLI session opened
in this repository. This requests today's live-source preview with measured Codex
summary usage when eligible. The skill asks for a missing start or other blocking
information, without reconfirming supplied facts. An omitted end stops allocation
at the last commit. Specify another date or an end in plain language when needed;
publishing to Gradion requires an explicit request.

The launcher starts a fresh Codex session in this repository with network access
enabled and approval policy `on-request`. It uses `danger-full-access` because the
standard workspace sandbox cannot read the host GitHub credential store. Review
commands shown by Codex and use this launcher only for this trusted checkout.

The bootstrap refuses to replace an existing token unless --replace is explicit.
Collector calls use the authorized token and refresh it when needed. Every live
pipeline preparation queries current events; it does not subscribe or run daily by
itself. Primary is the default. Calendar pagination is exhausted and later-page
errors fail the source instead of reporting truncated success. Desktop OAuth
instructions follow the [Google quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python).

## Configuration and paths

CLI overrides exported environment overrides profile values overrides defaults for
repository selection and Calendar/token paths. Identity/timezone use CLI > profile
> default. Export individual variables; .env is not automatically loaded.

| Setting | CLI | Environment | Profile / default |
| --- | --- | --- | --- |
| Repositories | --repos | TIMESHEET_REPOS (comma separated) | repositories / current local repo |
| Calendar token | --calendar-token | GOOGLE_CALENDAR_TOKEN | calendar.token_path / bundle token.json |
| OAuth client | --calendar-credentials | GOOGLE_CALENDAR_CREDENTIALS | calendar.credentials_path / bundle credentials.json |
| Calendars | --calendar-ids | — | calendar.calendar_ids / primary |
| Claude transcripts | --claude-dir | CLAUDE_DIR | token_tracking.claude_dir / ~/.claude |
| Usage output | pipeline --token-csv-path, collector --csv-path | TIMESHEET_TOKEN_CSV | token_tracking.csv_path / bundle data/token-usage.csv |
| Zone | --timezone | — | timezone / Asia/Ho_Chi_Minh |

Profile-relative paths use the profile's parent directory; CLI/env paths use the
invoking directory. Bundle defaults are rooted beside scripts. Use quoted absolute
output/profile/repository paths when invoked from another project. Invalid explicit
settings fail; they never fall back to a guessed identity or host timezone.

## Prepare, summarize, assemble

```bash
python3 scripts/run_pipeline.py --phase prepare --date 2026-10-07 \
  --config config/user-config.json --work-start 09:00 \
  --snapshot data/audit/my-run/activity.json \
  --export-ai-input data/audit/my-run/ai-input.json \
  --output-dir data/audit/my-run/timesheets

# Read AI input; create [{"block_id":"...", "description":"Concise summary"}].
# Omit --ai-output to use deterministic fallback instead.
python3 scripts/run_pipeline.py --phase assemble \
  --snapshot data/audit/my-run/activity.json --ai-output data/audit/my-run/ai-output.json \
  --output-dir data/audit/my-run/timesheets
```

Prepare writes an immutable snapshot and optional AI export, not final timesheets
or tokens. Assemble validates/rebuilds frozen evidence without recollecting. The
snapshot includes a run ID and SHA-256 fingerprint; it is not a digital signature.
Different sources require a new snapshot. Default --phase run offers single-pass
collection plus deterministic fallback (or explicitly supplied validated judgments).
Use frozen phases for AI synthesis to avoid stale source descriptions.

Unknown/duplicate/stale block IDs, conflicting metadata, malformed requested AI,
PR references in AI descriptions and inconsistent durations block writes. Partial
keyed summaries use each unmatched block's own fallback. Scripts own exactly one
PRs suffix, with owner/repo qualification for colliding PR numbers.

## Evidence and policy

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

### Commit intervals (current profile)

Set `block_policy` to `{"strategy": "commit_intervals"}`. Each run requires
`--work-start HH:MM`, explicitly confirmed by the user for the selected date in the
configured timezone. The example above uses an illustrative 09:00; never assume it.
Passing `--work-start` also selects this strategy for older profiles. Optionally
pass `--work-end HH:MM` (or `24:00`) to include work after the last commit. Without
an end, allocation stops at the final commit. Neither clock is a reusable profile
default. Prepare freezes the daily confirmation in the snapshot; assemble rejects
clock overrides. Changed hours require a new snapshot.

- Allocate confirmed start → first commit, then previous commit → next commit.
- Subtract configured breaks (default **12:00–13:30**) and the union of scheduled Calendar intervals.
  A crossing interval becomes separate rows. Calendar rows remain scheduled,
  attendance-unconfirmed proposals, including lunch/future events.
- If a commit allocation has **1–19 work minutes after these exclusions**, merge
  it into the previous commit allocation, retaining every commit and PR. Consecutive
  short allocations merge backward into the same group. The first allocation stays
  separate when there is no predecessor; 20 minutes or more stays separate. A
  zero-work allocation stays separate for Calendar/review assignment. A confirmed-end
  tail is not a commit allocation and does not merge. Apply this rule before splitting
  at lunch/Calendar: a short piece of a longer allocation does not trigger a merge.
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
- With no commits and no confirmed end, generate only Calendar rows. With both
  confirmed hours, allocate that window minus lunch/Calendar, using generic text
  when there is no activity. A tail after the last commit does not borrow its task.

Example: start 09:00, commits 10:10 / 11:40 / 14:10 / 16:00, no Calendar:
09:00–10:10 (70m), 10:10–11:40 (90m), 11:40–12:00 (20m),
13:30–14:10 (40m), 14:10–16:00 (110m). Total: **330m proposed**.
Confirmed hours and allocation metadata survive into the final JSON. Development
remains `estimated`: commit boundaries allocate time, not measure task duration.
For example, commits at 10:00 / 10:10 / 10:25 become one 09:00–10:25 row (85m),
containing all three commits. New pipeline snapshots use schema v5 to freeze the work
schedule as well as stable allocation groups and merge-commit associations. V4 retains
the default schedule and its previous allocation behavior. V3 retains the previous under-20-minute rule;
v2 retains under-30-minute merging and v1 retains unmerged intervals. Changed allocations require
a new prepare snapshot.

### Configurable work schedule

`work_schedule` in the profile controls regular hours, breaks and additional overtime
windows. Its default is **09:00–12:00 / 13:30–17:30**. See
[the schedule policy and examples](docs/work-schedule.md). For example:

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

### Previous policies and source scope

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

Work-log descriptions are generated in English for NORMAL and OT entries. Both
summary strategies translate non-English evidence while retaining ticket keys
and proper names. Without AI, English templates describe the available evidence
or scheduled calendar activity; original titles/messages remain in `sources`.
Calendar attendance remains unconfirmed. Existing saved logs are not rewritten.

## Token usage

Payload v3 exports an audit envelope plus a compact `summary_request`. Text is stored
once and referenced by summary jobs. Pieces of one commit allocation split by
lunch/Calendar share one job and description, using the combined PR context of
those pieces. Different commit allocations keep separate jobs even when their text
matches. Python maps jobs back to the original block IDs and appends each block's
own PR references. Frozen v1/v2 payloads retain their original summary behavior.
New allocation IDs are fixed before assigning per-piece evidence, so a commit in
the first minute of the confirmed start cannot accidentally split a summary group.
Times, source evidence
and unassigned review stay in the snapshot. Calendar-only rows use deterministic
descriptions. No persistent judgment cache is implemented.

The runner writes `usage-attempt.json` independently of summary acceptance and a
per-invocation `attempt-token-usage.csv` when provider usage is verifiable. Invalid
summaries still retain their token cost; missing usage is unknown. Successful output
keeps a separate `usage-run.json` for assembly. Both receipts identify the same
invocation, so collecting them does not count its tokens twice. Benchmarks retain
an `attempts.json` ledger for failures/retries as well as successful comparisons.

`serialized_bytes` measures the full audit export; `model_payload_bytes` measures
the exact compact UTF-8 request. The bytes/4 estimate is a heuristic for the request,
not an exact tokenizer count. The default 12000-byte guard bounds this request,
overridable with --max-ai-input-bytes. Overflow blocks without dropping evidence.
Legacy snapshots retain their original full-export guard and remain readable.
Supplied judgments can be reused explicitly with the same snapshot.
See [workflow.md](workflow.md) for token targets.

For measured Codex usage, use the [Codex runner instructions](docs/codex-usage.md).
It records one isolated summary invocation. CSV input excludes cached input so
input + output + cache equals the provider total, without counting cache twice.
Original Codex input/output/cache counts are preserved in attribution notes.

For Claude, record actual usage with a run manifest; no implicit whole-directory aggregation:

```json
{"run_id":"SNAPSHOT-RUN-ID","target_date":"2026-10-07","session_file":"/path/session.jsonl",
 "started_at":"2026-10-07T09:00:00+07:00","ended_at":"2026-10-07T09:05:00+07:00",
 "message_ids":["EXACT-USAGE-MESSAGE-ID"]}
```

```bash
python3 scripts/collect_token_usage.py --run-manifest data/audit/my-run/usage-run.json \
  --config config/user-config.json --csv-path data/audit/my-run/token-usage.csv
```

Pass --usage-run-manifest and --token-csv-path to assemble to record already available
usage together with timesheets. To include later final responses, record afterward.
A marked window must accurately isolate the skill; use explicit IDs when unrelated
messages share it. Selected-message scope is labeled accordingly. Repeated message
snapshots use the latest complete usage snapshot; exact unidentifiable snapshots
are deduplicated. Input, output, cache-read and cache-creation must all be explicit;
missing counts never become zero. In-scope incomplete/invalid usage, conflicting
snapshots or malformed JSON block recording and preserve existing files. Raw
streaming events are unsupported; no partial-update merge is inferred. See the
[R04 schema policy](docs/r04-usage-schema-validation.md). Real transcript
compatibility still needs V01 acceptance on an installed Claude Code environment.

CSV retains input/output/cache and total including cache (D06). Usage follows execution
start day, with target timesheet day separately recorded; same run cumulative totals
replace, distinct runs aggregate. Manual --record-usage requires --run-id and is labeled
self-reported. Missing usage is unknown and leaves CSV unchanged. Corrupt CSV blocks
updates rather than discarding prior records.

## Claude Code installation and validation

```bash
python3 scripts/install_skill.py --scope project
# Optional personal use across projects:
python3 scripts/install_skill.py --scope personal
python3 -m unittest discover -s tests
```

Installer symlinks the bundle and preserves any different existing destination;
it copies no credentials. Project discovery uses .claude/skills/personal-timesheet;
personal discovery uses ~/.claude/skills/personal-timesheet. Commands in SKILL.md use
${CLAUDE_SKILL_DIR} and quoted absolute paths, per the
[Claude Code skills documentation](https://code.claude.com/docs/en/skills).
Installation does not establish that the CLI discovered or executed the skill.

See [data/README.md](data/README.md) before using historical tracked examples and
[docs](docs/) for issue validation. Synthetic tests/demos and real-source audits
are separate. No measured savings or live Claude usage are claimed without evidence.
