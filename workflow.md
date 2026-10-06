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
| **4** | `[Script]` | **Collect Calendar Events** | Use an authorized Google token or explicit fixture; both preserve all_day dates and select events overlapping the requested local day, including previous-night events. Missing setup/request failures never become sample data. | Deterministic interval filtering, event typing and source status extraction. |
| **5** | `[Script]` | **Normalize & Deduplicate** | Keep qualified repo/PR references, distinct action events and commit identity provenance. Separate all-day Calendar context from timed events; never infer work duration or a day off from context. | Deterministic projection and set/dict operations. |
| **6** | `[Script]` | **Construct Time Blocks** | Clip timed events to the selected local day, using 24:00 for its midnight end and elapsed UTC minutes. Partition at event boundaries, retaining original active sources; overlap requires attendance confirmation. Scheduled lunch meetings stay. Development gaps subtract 12:00–13:30, then require 30 minutes and activity evidence per interval. All-day context adds no time; empty-Calendar workday fallback remains D02. | Deterministic daily clipping, interval partitioning and evidence checks. |

| **7** | `[Script]` | **Associate Activities** | Match commit and PR timestamps against time block intervals (`start <= timestamp < end`). | Deterministic timestamp interval comparison. |
| **8** | `[Script]` | **Pre-AI Ticket Grouping** | Scan commit messages and PR titles for ticket patterns (e.g., `PAY-123`). If detected, pre-cluster activities sharing the same ticket ID. | Deterministic regex matching (reduces AI work). |
| **9** | `[Script]` | **Prepare Minimal AI Payload** | Strip hashes, raw timestamps, author names, URLs, and file paths. Produce compact JSON with a stable date/start/end block_id, time_basis, block times, actual calendar titles, messages, and PR titles. Reject duplicate candidate identities. | Deterministic data projection and block identity. |
| **10** | `[AI]` | **Semantic Topic Grouping & Synthesis** | Determine whether disparate commit messages (e.g., *"fix CSV validation"* and *"handle malformed rows"*) represent one coherent topic. Generate a concise, human-readable sentence. | **Why AI is required**: Natural language variations, developer jargon, and context ambiguity cannot be parsed by regex without writing brittle custom rules. |
| **11** | `[Script]` | **Deterministic Fallback Synthesizer** | If running in headless CI/offline mode without an LLM session, use rule-based sentence generator. | Pure fallback string templating. |
| **12** | `[Script]` | **Match Summaries, Format Entries & Append PRs** | Match AI output by exact block_id, never array position. Allow partial output with each unmatched block's own fallback; reject unknown/duplicate/inconsistent identities before saving. Retain block_id and ai/fallback provenance alongside source evidence. Append the block's PR suffix. | Deterministic keyed matching, validation, and formatting. |
| **13** | `[Script]` | **Daily Reconciliation & Storage** | Reconcile the full generated daily set while preserving manual rows/overrides and refusing ownership conflicts. Save all-day context in a separate daily sidecar and Markdown context section; it contributes no duration. Context changes/deletions update on successful snapshots; validation/source failures preserve existing final/context/AI/token files. Exact reruns preserve bytes. | Deterministic daily reconciliation, context validation and successful-collection gate. |
| **14** | `[Script]` | **Record Token Usage** | Scan Claude Code transcripts under `~/.claude/*.jsonl` or session logs. Extract input/output/cache token metrics and update `data/token-usage.csv`. | Deterministic JSONL parsing and CSV aggregation. |

All entry points share timezone precedence: CLI override, then profile, then the
named default `Asia/Ho_Chi_Minh`. Day/date resolution never uses host-zone or
first-source inference. Calendar/normalizer/token standalone CLIs accept the same
configuration; historical bounds use IANA DST rules. Old normalized fixed offsets
remain compatible but are not guessed to be named zones. Ambiguous/nonexistent
Calendar wall times without an offset fail rather than being guessed.

Step 14 is available through the standalone token CLI: usage lines are filtered by
their aware timestamps within the same UTC-converted local-day bounds; missing or
invalid timestamps are reported and skipped. The orchestrator currently initializes
the usage CSV without collecting actual run usage. Automatic run/session attribution
remains F22, and run isolation remains F24 and deduplication/schema validation remain F25/F26.

Activity association uses aware timestamps within the selected day's `[start,end)`
intervals. Unmatched commits and individual PR actions are retained separately with
reasons; no arbitrary fallback block is selected. No-Calendar candidate windows
require timestamp evidence inside them, and remain estimated proposals. An
unmatched-only day has zero timed entries plus review evidence. No OT/breaktime
classification is inferred.

AI exports contain `{blocks, unassigned_activity, review}`; synthesize only `blocks`
and return the existing keyed-summary array. The compact unmatched list is for
review, never a source for assigning an unrelated block. Storage preserves original
evidence in the daily activity-review sidecar, displays it outside Markdown totals,
and links counts/status in the collection manifest. COMPLETE source status and
required human review are separate. Successful reruns reconcile/clear review;
failures preserve previous outputs, and explicit demo output stays isolated.

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
