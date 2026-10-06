# Daily Timesheet Workflow

This document defines the complete daily execution sequence for the **Personal Pilot Timesheet Logger**.

---

## 1. Principle of Separation

- **Deterministic Rule → `[Script]`**: Everything that can be defined by code, arithmetic, regex, timestamp comparisons, API query parameters, sorting, sets, or predefined business logic must be implemented in Python scripts.
- **Natural Language Judgment → `[AI]`**: Only invoked when natural language understanding or ambiguous topic synthesis is strictly required.

---

## 2. Ordered Workflow Steps

| Step # | Classification | Step Name | Description | Reason for Classification |
| :---: | :---: | :--- | :--- | :--- |
| **1** | `[Script]` | **Resolve Date & Timezone** | Parse `--date YYYY-MM-DD` or detect local date & timezone offset (e.g. `+07:00`). | Deterministic calendar math. |
| **2** | `[Script]` | **Collect Git Commits** | Query local repos via `git log --all --date=iso-strict` or remote GitHub repos (`owner/repo`, HTTPS/SSH URLs) via GitHub REST API (`gh api` or direct HTTPS). Filter by author and local target date, extracting hashes and commit messages. | Deterministic log filtering, URL slug parsing, and API query execution. |
| **3** | `[Script]` | **Collect PR Activity** | Query GitHub (`gh` / API) or GitLab (`glab` / API) for PRs opened, reviewed, or merged today. | Deterministic API query and status extraction. |
| **4** | `[Script]` | **Collect Calendar Events** | Retrieve Google Calendar events or parse exported `.ics` / local fixture for the day. | Deterministic calendar API/file parsing. |
| **5** | `[Script]` | **Normalize & Deduplicate** | Strip all extraneous API metadata. Deduplicate PRs by ID, merge status conflicts, and eliminate duplicated commits. | Deterministic set/dict operations. |
| **6** | `[Script]` | **Construct Time Blocks** | Interleave calendar events with standard workday intervals (`09:00–12:00`, `13:30–17:30`). If no calendar events exist, apply deterministic morning/afternoon split rule. | Pure scheduling interval segmentation. |
| **7** | `[Script]` | **Associate Activities** | Match commit and PR timestamps against time block intervals (`start <= timestamp < end`). | Deterministic timestamp interval comparison. |
| **8** | `[Script]` | **Pre-AI Ticket Grouping** | Scan commit messages and PR titles for ticket patterns (e.g., `PAY-123`). If detected, pre-cluster activities sharing the same ticket ID. | Deterministic regex matching (reduces AI work). |
| **9** | `[Script]` | **Prepare Minimal AI Payload** | Strip hashes, timestamps, author names, URLs, and file paths. Produce minimal JSON containing only block time, calendar title, messages, and PR titles. | Deterministic data projection. |
| **10** | `[AI]` | **Semantic Topic Grouping & Synthesis** | Determine whether disparate commit messages (e.g., *"fix CSV validation"* and *"handle malformed rows"*) represent one coherent topic. Generate a concise, human-readable sentence. | **Why AI is required**: Natural language variations, developer jargon, and context ambiguity cannot be parsed by regex without writing brittle custom rules. |
| **11** | `[Script]` | **Deterministic Fallback Synthesizer** | If running in headless CI/offline mode without an LLM session, use rule-based sentence generator. | Pure fallback string templating. |
| **12** | `[Script]` | **Format Entries & Append PRs** | Assemble entry object (`Date`, `Start time`, `End time`, `Description`). Deterministically append `PRs: #101, #102` or `PRs: None` at the end. | Strict string formatting rule. |
| **13** | `[Script]` | **Idempotent Upsert & Storage** | Match existing entries by key `(date, start, end)`. Update modified entries or skip duplicates. Write audit JSON (`data/timesheets/YYYY-MM-DD.json`) and Markdown review table (`data/timesheets/YYYY-MM-DD.md`). | Deterministic file I/O and idempotent dictionary merge. |
| **14** | `[Script]` | **Record Token Usage** | Scan Claude Code transcripts under `~/.claude/*.jsonl` or session logs. Extract input/output/cache token metrics and update `data/token-usage.csv`. | Deterministic JSONL parsing and CSV aggregation. |

---

## 3. Token Budget

### Targets
- **Target AI Input Payload**: `< 1,000 tokens` per working day (Typical actual payload: **150 – 350 tokens**).
- **Target AI Output**: `< 200 tokens` (1–2 concise sentences per block).
- **Target Total AI Daily Usage**: `< 600 tokens` total per normal working day.

### How Token Usage is Minimized
1. **Script-Side Filtering**: Raw Git logs (diffs, authors, emails, parent hashes) and full GitHub JSON responses (avatars, URLs, permissions, links) are stripped before AI sees them.
2. **Strict Time Scope**: Only activities for the requested date are passed; previous days' history is never loaded into prompt context.
3. **Deterministic Pre-calculation**: Timestamps, start/end times, durations, and PR ID listings (`PRs: #...`) are calculated entirely in Python. AI is never asked to calculate or repeat these.
4. **Idempotency Guarantee**: Rerunning the skill does not re-query AI for unchanged blocks.
5. **Pre-AI Ticket Grouping**: Commits matching identical issue keys are pre-grouped, avoiding redundant AI reasoning.

---

## 4. Script Reference Map

| Purpose | Script File |
| :--- | :--- |
| Git commit collection | `scripts/get_git_activity.py` |
| PR / MR activity collection | `scripts/get_pr_activity.py` |
| Google Calendar collection | `scripts/get_calendar_activity.py` |
| Data normalization & cleaning | `scripts/normalize_activity.py` |
| Time block generation & activity association | `scripts/build_time_blocks.py` |
| Minimal AI payload preparation | `scripts/prepare_ai_input.py` |
| Timesheet entry assembly | `scripts/build_timesheet.py` |
| Idempotent storage (JSON & Markdown) | `scripts/save_timesheet.py` |
| Claude transcript token tracking | `scripts/collect_token_usage.py` |
| End-to-end pipeline orchestrator | `scripts/run_pipeline.py` |
