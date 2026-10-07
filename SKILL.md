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
   If the command returns exit code **2**, read the source-status diagnostics and the **INCOMPLETE** activity draft under `data/timesheets/drafts/`. Report missing setup/errors and stop; do not read an older AI payload or claim that a final timesheet was generated. Never enable sample fixtures implicitly. Explicit fixture runs are **DEMO** and use isolated `demo/` output paths printed by the pipeline; use those paths for the remaining steps.

3. **Read Minimal AI Input**:
   Inspect `data/raw/ai_input_<YYYY-MM-DD>.json`.
   Notice that it contains only compact block times, calendar titles, commit messages, and PR titles. No git hashes, author info, or raw metadata are present.

4. **Perform AI Topic Synthesis**:
   For each block that has commits or PRs:
   - Group semantically related activities into 1–2 coherent topics.
   - Write a concise, professional summary (e.g., *"Customer import improvements covering CSV validation, malformed-row handling, and tests"*).
   - Return structured JSON in this format:
     ```json
     [
       {
         "block": {"start": "09:30", "end": "12:00"},
         "description": "Customer import improvements covering CSV validation, malformed-row handling, and tests."
       }
     ]
     ```
   *(Save to `data/raw/ai_judgment_<YYYY-MM-DD>.json`)*

5. **Execute Final Assembly & Idempotent Save (Phase 2)**:
   Pass the AI judgment back to the pipeline:
   ```bash
   python3 scripts/run_pipeline.py --date <YYYY-MM-DD> --ai-output data/raw/ai_judgment_<YYYY-MM-DD>.json
   ```

6. **Confirm to User**:
   Display the generated timesheet summary from `data/timesheets/<YYYY-MM-DD>.md` and point to the audit JSON in `data/timesheets/<YYYY-MM-DD>.json`.
