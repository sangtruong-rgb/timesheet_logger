# Personal Pilot Timesheet Logger

Automated, deterministic timesheet logging skill for Claude Code that combines Git commits, Pull Requests, and Google Calendar into daily timesheet records.

---

## 1. Architecture

```text
  Git Commits          Pull Requests        Google Calendar
 (git log CLI)        (gh/glab/API/mock)   (API/ICS/mock)
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
- **GitHub / GitLab (Optional)**:
  - GitHub: Install and authenticate `gh auth login`, or set `GITHUB_TOKEN`.
  - GitLab: Install and authenticate `glab auth login`, or set `GITLAB_TOKEN`.
  - PR collection currently uses authenticated `gh`. Missing setup or query failures are reported explicitly; there is no automatic fixture fallback. Other advertised PR adapters remain pending.
- **Google Calendar (Optional)**:
  - Place OAuth credentials in `credentials.json` or authorized token in `token.json`.
  - Or supply a local `.ics` iCal export.
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
To run the end-to-end pipeline deterministically:
```bash
# Log today's work using local Git and default sources
python3 scripts/run_pipeline.py

# Log for a specific date
python3 scripts/run_pipeline.py --date 2026-10-06

# Query specific local repositories or remote GitHub repositories
python3 scripts/run_pipeline.py --date 2026-10-06 --repos octocat/Hello-World https://github.com/facebook/react .

# Explicit demo: outputs go under data/timesheets/demo/
python3 scripts/run_pipeline.py \
  --date 2026-10-06 \
  --calendar-fixture data/fixtures/sample_calendar.json \
  --prs-fixture data/fixtures/sample_prs.json
```

### Collection status and output safety

PR and Calendar collectors return a JSON envelope rather than a bare activity list:

```json
{"source":"github","mode":"live","status":"success","items":[]}
```

- `status: success` with `items: []` means the source was queried successfully and has no activity for the selected day.
- `status: unavailable` means authentication, libraries, or configuration are missing; `status: error` means collection failed. Both include a `reason`, return exit code **2**, and never substitute sample data. Diagnostics go to stderr; JSON goes to stdout.
- Fixtures are used only through `--prs-fixture` / `--calendar-fixture` (or a collector's `--fixture`). Missing/malformed fixture files are errors.
- A run with any unavailable/failed PR or Calendar source returns **2** and writes only collected evidence under `<output-dir>/drafts/YYYY-MM-DD.json` and `.md`, marked **INCOMPLETE**. It does not assemble timesheet entries, export AI input, or change final timesheets/token records.
- A successful run using any explicit fixture is marked **DEMO**. Its timesheet/collection manifest goes under `<output-dir>/demo/`; requested AI exports go into a `demo/` subdirectory beside the requested path. It does not update the production token CSV.
- Successful live collection writes to `<output-dir>` and records PR/Calendar source metadata in `YYYY-MM-DD.collection.json`, even when both sources are empty. Generated entry JSON also retains collection metadata; demo Markdown has a visible banner.
- `normalize_activity.py --prs-file ... --calendar-file ...` accepts successful collector envelopes and legacy list fixtures, preserving envelope metadata. It rejects unsuccessful envelopes rather than treating them as empty sources.

The default output directory is `data/timesheets`. Draft/demo isolation does not repair existing contaminated logs or changed-block rerun behavior; those remain separate audit items. Git collector failure reporting and live integration verification are also still pending.

#### Remote GitHub Repositories
The Git collector (`scripts/get_git_activity.py`) supports uncloned remote GitHub repositories in addition to local directories:
- **Bare slug**: `--repos owner/repo`
- **HTTPS URL**: `--repos https://github.com/owner/repo` (or `.git` / subpath variants)
- **SSH URL**: `--repos git@github.com:owner/repo.git`

Remote commits for the target date are fetched via `gh api` (if authenticated) or HTTPS GitHub REST API using `GITHUB_TOKEN` / `GH_TOKEN` environment variables, and filtered with strict local timezone boundaries.

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
   - Solution: Install `gh` and run `gh auth login` for live PR collection. For offline demos, explicitly pass both fixture arguments as shown above. An unavailable source produces an incomplete draft, not a successful empty source.
2. **Google Calendar not configured**:
   - Notice: Google Calendar credentials not found.
   - Solution: Live collection needs the optional Google libraries and an already-authorized root-level `token.json`; `credentials.json` alone does not authorize collection. OAuth bootstrap instructions remain a separate setup task. Use `--calendar-fixture` explicitly for a demo; there is no automatic sample retrieval.
3. **No commits detected**:
   - Verify that your commits were made with the same author name or email as `git config user.name` / `user.email`. Use `--author "<name>"` to override.
4. **No Calendar events**:
   - The logger automatically generates morning (`09:00–12:00`) and afternoon (`13:30–17:30`) blocks based on commit timestamps.
5. **Token file not found**:
   - If `~/.claude` has no transcripts yet, `collect_token_usage.py` initializes `data/token-usage.csv` with standard headers without error.
6. **Timezone mismatch**:
   - All timestamps respect local timezone offset (e.g. `+07:00`). Commit timestamps near midnight are correctly attributed to the local calendar day.
