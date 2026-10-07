---
name: personal-timesheet
description: Collects daily work activity from Git commits, Pull Requests, and Google Calendar, segments activities into structured time blocks, synthesizes concise topic descriptions with minimal AI, and saves idempotent timesheet entries.
triggers:
  - "log today's work"
  - "log my work today"
  - "create today's timesheet"
  - "run my timesheet"
  - "log my work for YYYY-MM-DD"
---

# Personal Timesheet Logger

## Purpose
Automate personal daily timesheet logging by collecting verified activity from Git repositories, GitHub Pull Requests, and Google Calendar. GitLab PR support remains pending.

Strictly follows the **[Script] vs [AI]** separation:
- All deterministic data fetching, filtering, timezone handling, timestamp interval matching, PR deduplication, duration calculations, and file persistence are executed by Python scripts.
- AI is solely invoked to perform semantic topic grouping and generate concise executive summaries from a minimal payload (< 350 tokens).

## When to Use
Use this skill whenever the user asks to:
- "log today's work"
- "log my work today"
- "create today's timesheet"
- "run my timesheet"
- "log my work for 2026-10-06" (or any specific date)

## Workflow Reference
The full ordered sequence and deterministic breakdown are specified in:
[workflow.md](workflow.md)

## Invocation Steps for Claude Code

1. **Determine Target Date**:
   Extract target date from the user prompt (`YYYY-MM-DD`). If none is specified, use today's date in the profile's IANA timezone. Load `config/user-config.json` when present, or pass an explicit `--config`; use all confirmed account/name/email aliases and the same repository selection for Git and PRs.

2. **Execute Deterministic Pipeline (Phase 1)**:
   Run the orchestrator script to collect and prepare the minimal AI payload:
   ```bash
   python3 scripts/run_pipeline.py --date <YYYY-MM-DD> --export-ai-input data/raw/ai_input_<YYYY-MM-DD>.json
   ```
   If the command returns exit code **2**, read the diagnostics and draft path printed by the pipeline. A failed source creates an **INCOMPLETE** draft; AI/block validation or daily reconciliation failures create a **REVIEW REQUIRED** draft. Report the reason and stop; do not read an older AI payload or claim that a final timesheet was generated. Never enable sample fixtures implicitly. Explicit fixture runs are **DEMO** and use isolated `demo/` output paths printed by the pipeline; use those paths for the remaining steps.

3. **Read Minimal AI Input**:
   Inspect `data/raw/ai_input_<YYYY-MM-DD>.json`.
   Each payload carries a stable `block_id` derived from date/start/end, plus `time_basis`, compact block times, actual calendar titles, commit messages, and PR titles. No git hashes, author info, or raw metadata are present. Copy the exact `block_id` when returning a summary.

4. **Perform AI Topic Synthesis**:
   For each block that has commits or PRs:
   - Group semantically related activities into 1–2 coherent topics.
   - Write a concise, professional summary (e.g., *"Customer import improvements covering CSV validation, malformed-row handling, and tests"*).
   - Return exactly one summary per selected `block_id`; copy IDs from the input without changing them. Output order does not matter. Calendar-only blocks can be omitted and use their own deterministic fallback.
   - Do not append the `PRs:` suffix; the script assembles it from that block's evidence.
   - Describe only supplied evidence. An `estimated` interval is a work-time proposal based on activity timestamps; do not claim continuous work for its whole duration. Calendar-only fallback repeats the event title without inventing discussion topics.
   - `calendar_overlap: true` means conflicting scheduled events, with `attendance: unconfirmed`. Do not infer which event was attended or claim simultaneous attendance. Keep the attendance-review notice; the script also adds it independently of AI text.
   - Return structured JSON in this format:
     ```json
     [
       {
         "block_id": "2026-10-06_09:30_12:00",
         "description": "Customer import improvements covering CSV validation, malformed-row handling, and tests."
       }
     ]
     ```
   *(Save to `data/raw/ai_judgment_<YYYY-MM-DD>.json`)*
   Unknown/stale IDs, duplicate summaries, inconsistent dates/intervals and malformed output are rejected. Position-only summaries are unsupported. Legacy `{date, block: {start, end}, description}` output requires an exact current match; date-less legacy intervals are accepted only for a single target day with unique candidate intervals.

5. **Execute Final Assembly & Idempotent Save (Phase 2)**:
   Pass the AI judgment back to the pipeline:
   ```bash
   python3 scripts/run_pipeline.py --date <YYYY-MM-DD> --ai-output data/raw/ai_judgment_<YYYY-MM-DD>.json
   ```

6. **Confirm to User**:
   Display the generated timesheet summary from `data/timesheets/<YYYY-MM-DD>.md` and point to the audit JSON in `data/timesheets/<YYYY-MM-DD>.json`. Retain the scheduled/estimated labels and proposed-time notice. Scheduled Calendar time does not confirm attendance; estimated time is not measured work time.
   If overlap is marked, report that source collection can be complete while attendance needs review. The saved output is a proposal; do not present it as confirmed meeting time. Attendance selection is a separate human review, not an AI decision.
   All-day context is shown below the Markdown rows and stored in `data/timesheets/<YYYY-MM-DD>.calendar-context.json` when present. It is not work duration or an automatic day-off decision and is excluded from AI block summaries. Timed events crossing midnight are shown only for the requested day, using `24:00` as its midnight end; preserve original source boundaries for audit.
