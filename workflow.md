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
| **1** | `[Script]` | **Resolve Date & Timezone** | Load the local identity/repository profile or CLI overrides; resolve `--date` in the selected IANA timezone. | Deterministic calendar math and configuration. |
| **2** | `[Script]` | **Collect Git Commits** | Query local repos via `git log --all --date=iso-strict` or remote GitHub repos (`owner/repo`, HTTPS/SSH URLs) via GitHub REST API (`gh api` or direct HTTPS). Filter by author and local target date, extracting hashes and commit messages. | Deterministic log filtering, URL slug parsing, and API query execution. |
| **3** | `[Script]` | **Collect PR Activity** | Use read-only GitHub REST via gh, an environment token, or opt-in Git credential helper. Scope to selected repos and all confirmed accounts. Fetch actual creation, review submission, and merge times. Fixtures require explicit selection; failed subrequests make the source unsuccessful. | Deterministic API query and source status extraction. |
| **4** | `[Script]` | **Collect Calendar Events** | Use an authorized Google token or explicitly selected fixture. Emit source status; missing setup and request failures never turn into sample data. | Deterministic calendar API/file parsing and source status extraction. |
| **5** | `[Script]` | **Normalize & Deduplicate** | Keep qualified repo/PR references and their distinct action events. Preserve commit identity-match provenance; deduplicate commits within their repository association. | Deterministic set/dict operations. |
| **6** | `[Script]` | **Construct Time Blocks** | Keep Calendar events as scheduled intervals. Retain a development gap only with a timestamped commit/PR inside it; mark its duration estimated. With successful empty Calendar and activity, retain the existing estimated workday-window fallback. An entirely empty day has no blocks. | Deterministic evidence checks and interval segmentation. |
| **7** | `[Script]` | **Associate Activities** | Match commit and PR timestamps against time block intervals (`start <= timestamp < end`). | Deterministic timestamp interval comparison. |
| **8** | `[Script]` | **Pre-AI Ticket Grouping** | Scan commit messages and PR titles for ticket patterns (e.g., `PAY-123`). If detected, pre-cluster activities sharing the same ticket ID. | Deterministic regex matching (reduces AI work). |
| **9** | `[Script]` | **Prepare Minimal AI Payload** | Strip hashes, raw timestamps, author names, URLs, and file paths. Produce compact JSON with a stable date/start/end block_id, time_basis, block times, actual calendar titles, messages, and PR titles. Reject duplicate candidate identities. | Deterministic data projection and block identity. |
| **10** | `[AI]` | **Semantic Topic Grouping & Synthesis** | Determine whether disparate commit messages (e.g., *"fix CSV validation"* and *"handle malformed rows"*) represent one coherent topic. Generate a concise, human-readable sentence. | **Why AI is required**: Natural language variations, developer jargon, and context ambiguity cannot be parsed by regex without writing brittle custom rules. |
| **11** | `[Script]` | **Deterministic Fallback Synthesizer** | If running in headless CI/offline mode without an LLM session, use rule-based sentence generator. | Pure fallback string templating. |
| **12** | `[Script]` | **Match Summaries, Format Entries & Append PRs** | Match AI output by exact block_id, never array position. Allow partial output with each unmatched block's own fallback; reject unknown/duplicate/inconsistent identities before saving. Retain block_id and ai/fallback provenance alongside source evidence. Append the block's PR suffix. | Deterministic keyed matching, validation, and formatting. |
| **13** | `[Script]` | **Daily Reconciliation & Storage** | Replace the complete generated set for the explicit date; remove obsolete intervals, including on successful empty days. Preserve marked manual rows and exact-key overrides. Refuse legacy ownership ambiguity or human-row overlaps; save a review draft without changing final/AI/token files. Write audit JSON and Markdown; exact reruns leave their bytes unchanged. | Deterministic daily-set reconciliation with explicit ownership and successful-collection gate. |
| **14** | `[Script]` | **Record Token Usage** | Scan Claude Code transcripts under `~/.claude/*.jsonl` or session logs. Extract input/output/cache token metrics and update `data/token-usage.csv`. | Deterministic JSONL parsing and CSV aggregation. |

---

## Collection Outcome Gate

Before time blocking or AI, `[Script]` checks Git/PR/Calendar envelopes. A successful empty list remains empty. If a source is unavailable or failed, save only collected evidence as an **INCOMPLETE** draft under `data/timesheets/drafts/`, return exit code 2, and stop. Final timesheets, AI exports, and token records are untouched. Remote Git/API failures are explicit; legacy local Git invalid-path/failure handling remains separate audit work.

If all sources succeed but any fixture was explicitly selected, mark the run **DEMO**, isolate timesheet/manifests under `data/timesheets/demo/`, isolate AI exports under a sibling `demo/` directory, and skip production token updates. Successful live runs retain source metadata and the selected identity/repositories/timezone in their entry JSON and daily collection manifest.

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
