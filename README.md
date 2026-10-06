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
  - Place OAuth credentials in `credentials.json` or authorized token in `token.json`.
  - ICS collection remains pending.
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

AI input carries `block_id`, for example `2026-10-06_09:30_12:00`. Return that exact
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
references are deduplicated within each block. Existing general block/time estimation bugs
remain under F02–F08.

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

1. **GitHub/GitLab CLI not authenticated**:
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
