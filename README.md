# Personal timesheet logger

Build a reviewable daily proposal from real Git commits, GitHub PR actions and
Google Calendar. Python performs collection, normalization, interval math, matching,
validation and storage. AI optionally summarizes text; the pipeline CLI does not
call an LLM. The optional [Codex runner](docs/codex-usage.md) calls the installed CLI
and records measured usage for its isolated summary invocation.
GitHub and Google Calendar are supported. GitLab and ICS adapters are not implemented.

## Runtime and setup

Hướng dẫn macOS/Linux trên máy công ty: [company-machine-run.md](docs/company-machine-run.md), gồm nguồn thật, skill và usage acceptance.

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
  --config config/user-config.json --snapshot data/audit/my-run/activity.json \
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

A commit or PR action attaches only to its [start,end) interval. Unassigned evidence
is retained separately and adds no duration. Estimated gaps require an activity
inside them; timestamps do not prove continuous work. Current development windows
are 09:00–12:00 / 13:30–17:30, lunch 12:00–13:30, minimum gap 30 minutes. Empty-Calendar
fallback still uses 09:00–12:30 / 13:30–17:30, gated by activity per window. **D02 is
deferred:** these rules are hardcoded; configurable schedules and BREAK/OT labeling
are not implemented. Scheduled meetings during lunch or outside work hours remain
proposals. Totals are Total Proposed Time when scheduled/estimated rows exist.

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

## Token usage

Payload export reports exact serialized bytes and a bytes/4 heuristic, not an exact
tokenizer count. Default maximum is 12000 bytes including metadata, overridable with
--max-ai-input-bytes. Overflow blocks without dropping evidence. Duplicate text is
removed, Calendar-only blocks omit AI judgment, ticket IDs are extracted. Automatic
ticket clustering and a judgment cache do not exist. Supplied judgments can be reused
explicitly with the same snapshot. See [workflow.md](workflow.md) for token targets.

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
