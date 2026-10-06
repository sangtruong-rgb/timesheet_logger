# Timesheet Skill Improvement Log

## 2026-10-06

Problem:
Risk of passing unbounded raw Git logs, full GitHub API payloads, and full calendar metadata directly to LLM, causing token bloat and non-deterministic formatting.

Observed behavior:
Raw Git logs contain author lines, commit hashes, diff stats, and merge commits. GitHub JSON contains user avatars, links, node IDs, and API URLs. Passing these into an AI prompt consumes 3,000–8,000 tokens daily and occasionally causes AI to miscalculate start/end times.

Root cause:
Lack of a deterministic normalization layer prior to prompt assembly.

Change made:
Built `normalize_activity.py` and `prepare_ai_input.py` to strip all non-essential fields (hashes, emails, raw API links) and deterministically compute time blocks (`build_time_blocks.py`). Added ticket ID extraction (`extract_tickets`) to group ticket work prior to AI invocation.

Script or AI impact:
[Script] now performs 100% of the date math, timestamp interval mapping, PR deduplication, duration calculation, and final markdown table formatting. [AI] only receives clean commit messages and PR titles to perform semantic topic grouping and concise description writing.

Expected token impact:
Reduced daily AI prompt payload to < 350 tokens per run, well under the 1,000 token budget.

Result:
Clean, repeatable, and idempotent timesheets generated in seconds with zero token waste.
