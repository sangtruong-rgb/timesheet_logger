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
  - If unconfigured, the system automatically falls back to local fixtures (`data/fixtures/sample_prs.json`) or treats PR activity as empty without crashing.
- **Google Calendar (Optional)**:
  - Place OAuth credentials in `credentials.json` or authorized token in `token.json`.
  - Or supply a local `.ics` iCal export.
  - If unconfigured, the system uses calendar fixtures or applies the documented deterministic workday fallback.

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

# Run using realistic fixtures for Calendar & PRs
python3 scripts/run_pipeline.py \
  --date 2026-10-06 \
  --calendar-fixture data/fixtures/sample_calendar.json \
  --prs-fixture data/fixtures/sample_prs.json
```

### C. Running Unit Tests
All deterministic logic is covered by 16 automated tests:
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
   - Solution: Run `gh auth login` or set `GITHUB_TOKEN`. In offline testing, pass `--prs-fixture data/fixtures/sample_prs.json`.
2. **Google Calendar not configured**:
   - Notice: Google Calendar credentials not found.
   - Solution: The system applies the deterministic workday fallback or reads `data/fixtures/sample_calendar.json`. To enable live Google Calendar, place `token.json` or `credentials.json` in the root directory.
3. **No commits detected**:
   - Verify that your commits were made with the same author name or email as `git config user.name` / `user.email`. Use `--author "<name>"` to override.
4. **No Calendar events**:
   - The logger automatically generates morning (`09:00–12:00`) and afternoon (`13:30–17:30`) blocks based on commit timestamps.
5. **Token file not found**:
   - If `~/.claude` has no transcripts yet, `collect_token_usage.py` initializes `data/token-usage.csv` with standard headers without error.
6. **Timezone mismatch**:
   - All timestamps respect local timezone offset (e.g. `+07:00`). Commit timestamps near midnight are correctly attributed to the local calendar day.
