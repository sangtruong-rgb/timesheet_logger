---
name: personal-timesheet
description: Create a proposed daily timesheet from verified Git commits, GitHub PR actions and Google Calendar. Use for "log today's work", "run my timesheet", or "log my work for YYYY-MM-DD". Preserve evidence and mark scheduled attendance unconfirmed.
---

# Personal timesheet

Use scripts for collection, date/time math, matching, validation, suffixes, storage
and token accounting. Use AI only to summarize the provided block text. Read
[workflow.md](workflow.md) for policies and [README.md](README.md) for setup.

Short invocation: `$personal-timesheet 09:00` confirms a 09:00 work start for today
in the configured timezone and requests a live-source preview with `commit_intervals`.
An explicit date overrides today. Use an isolated audit directory. Do not reconfirm
the supplied start or ask for an optional end; without an end, stop at the last
commit. If the start is missing or ambiguous, ask a short question for that fact.
For other blockers, complete independent checks and ask only for the information
or user action needed to continue. Never ask for credential contents. This shorthand
does not authorize publishing. Explicit user instructions override these defaults.

Range invocation: `$personal-timesheet 8:00-12:00, 1h30-4:00` requests the same
preview within 08:00–12:00 and 13:30–16:00. Pass the supplied comma-separated
text as one quoted `--work-windows` argument instead of start/end flags. Python
resolves shorthand clocks in chronological order; padded HH:MM remains 24-hour
and explicit AM/PM is accepted. Show canonical windows. They replace profile
hours/breaks only for this date, exclude gaps, clip Calendar proposals, and include
the confirmed closing tail. Preserve excluded evidence for review and freeze the
windows in the snapshot. Invalid inputs fail before collection; do not guess a
replacement. No extra start/end confirmation or publishing is authorized.

Resolve the bundle through `${CLAUDE_SKILL_DIR}`, never the invoking project's
working directory. Paths below are placeholders, not shell angle-bracket syntax.
Use the configured Python environment with optional Calendar libraries. Never read,
print or commit credentials/token contents. Do not edit Calendar or infer attendance.

1. Resolve target date from the request, or let scripts use today's configured IANA
   timezone. Use an explicit profile with confirmed identities and selected repos.
   Create an isolated run directory under `${CLAUDE_SKILL_DIR}/data/audit/` for audits.
   Mark the skill run's aware start timestamp, session identity and usage message IDs
   when available. Record accurate boundaries; do not guess transcript identities.
2. For the current `commit_intervals` policy, obtain the user's confirmed start
   for the target day and pass `--work-start HH:MM`. Reuse an explicit confirmation
   already supplied for that date; never infer 09:00 or reuse another day's hours.
   Pass `--work-end HH:MM` only if the user confirms a finishing time; otherwise
   stop at the last commit and report that remaining time is not included. Do not
   ask about mid-session breaks. For range invocation, substitute
   `--work-windows "$TS_WORK_WINDOWS"` for the start/end flags. Prepare with quoted absolute paths:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py" --phase prepare \
     --config "${CLAUDE_SKILL_DIR}/config/user-config.json" --date YYYY-MM-DD \
     --work-start "$TS_WORK_START" \
     --snapshot "${CLAUDE_SKILL_DIR}/data/audit/RUN/activity.json" \
     --export-ai-input "${CLAUDE_SKILL_DIR}/data/audit/RUN/ai-input.json" \
     --output-dir "${CLAUDE_SKILL_DIR}/data/audit/RUN/timesheets"
   ```

   Exit 2 means stop and report the source/validation/storage diagnostic and draft
   path. Never use an older export after failure. Explicit fixtures are DEMO and
   use isolated paths printed by scripts; never enable them for a live request.
   PREPARED is not a completed final timesheet. Keep the snapshot's printed run ID.
3. Read only the small AI export. Summarize `blocks`, at most one or two concise
   sentences each. Do not summarize unassigned evidence into a block or invent work
   duration, attendance or topics. Calendar-only blocks need no AI. Return a JSON
   array of `{ "block_id": "...", "description": "..." }`. Omit PR numbers and
   `PRs:`; scripts append the suffix. If no blocks need judgment, skip AI and omit
   --ai-output. The Python CLI never calls an external AI service.
4. Save the judgment array in RUN/ai-output.json, then assemble **the same snapshot**:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/run_pipeline.py" --phase assemble \
     --snapshot "${CLAUDE_SKILL_DIR}/data/audit/RUN/activity.json" \
     --ai-output "${CLAUDE_SKILL_DIR}/data/audit/RUN/ai-output.json" \
     --output-dir "${CLAUDE_SKILL_DIR}/data/audit/RUN/timesheets"
   ```

   Do not collect again between phases. Changed evidence requires a new snapshot
   path and new review. For normal logging use an explicit final output directory
   under the bundle's data/timesheets instead of the audit directory.
5. When actual usage is available, write an explicit manifest with the snapshot
   run ID, session_file (or exact session_id), target_date, started_at, ended_at,
   and optional message_ids. Bounds are [start,end). IDs are required if unrelated
   work occurred inside that window. Pass --usage-run-manifest and --token-csv-path
   during assembly for usage already available. To include later responses, record
   the completed run afterward:

   ```bash
   python3 "${CLAUDE_SKILL_DIR}/scripts/collect_token_usage.py" \
     --config "${CLAUDE_SKILL_DIR}/config/user-config.json" \
     --run-manifest "${CLAUDE_SKILL_DIR}/data/audit/RUN/usage-run.json" \
     --csv-path "${CLAUDE_SKILL_DIR}/data/audit/RUN/token-usage.csv"
   ```

   Use complete snapshots with explicit input, output, cache-read and cache-creation
   counts. Missing/invalid usage blocks recording; do not fill missing counts with
   zero or merge partial snapshots. Raw streaming events require a verified adapter
   and are currently unsupported. See docs/r04-usage-schema-validation.md.
   No transcript/boundary evidence means usage unknown, not zero. Selected-message
   usage is labeled as selected scope; don't claim full-run totals. Manual counts
   are cumulative per run and explicitly self-reported. Daily aggregation follows
   the run's execution-start day; the timesheet date stays separate. Report input,
   output, cache and total (including cache) separately from payload size.
6. Report source states, collection COMPLETE/INCOMPLETE/DEMO, output paths, fallback
   or AI summaries, and any unassigned/attendance review. Keep full-day future
   meetings as proposals: **Theo lịch, chưa xác nhận tham dự**. Scheduled/estimated
   minutes are not measured work. Commit intervals allocate time from confirmed
   start to each closing commit, subtract frozen configured breaks (default lunch
   12:00–13:30) and Calendar coverage,
   and have no 30-minute minimum or 90-minute cap. Split rows may share closing
   commit evidence; this is completion context, not timestamp containment. PRs
   never add duration. Confirmed hours are frozen in the snapshot; changes require
   a new prepare run. An accepted commit-interval policy and confirmed daily hours
   do not require another per-block boundary confirmation. Activity-cluster boundaries are inferred and must
   be confirmed or overridden before publishing. Work schedule settings are frozen
   during prepare; explicit daily hours permit work outside regular/day limits.
   Breaks exclude development time; automatic BREAK/OT labels are unsupported.
   Never silently erase manual edits or migrate ambiguous
   old rows.

No automatic ticket clustering, judgment cache, daily scheduling or attendance
confirmation is implemented. Reusing validated judgments with the same frozen
snapshot is explicit. See data/README.md before inspecting historical demo files.
