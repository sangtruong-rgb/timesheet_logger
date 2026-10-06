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

---

## 2026-10-06 (Remote GitHub Repository Commit Fetching)

Problem:
Users may work on repositories hosted on GitHub that are not cloned locally in the immediate working tree or workspace.

Observed behavior:
Specifying `--repos owner/repo` or a GitHub URL failed with directory not found, requiring manual cloning before logging work.

Root cause:
`get_git_activity.py` previously only executed `git -C <path> log` against local disk directories.

Change made:
1. Implemented `parse_github_repo_slug` to detect GitHub HTTPS URLs, SSH URLs, and bare `owner/repo` slugs.
2. Built `fetch_github_api_commits` with `gh api` and HTTPS `urllib.request` fallback (supporting `GITHUB_TOKEN` / `GH_TOKEN`).
3. Added `normalize_api_commits` to convert GitHub API JSON into normalized commit dicts, strictly filtering by local timezone calendar day.
4. Added 4 new automated unit tests in `test_git_activity.py` (total 22 tests passing).

Script or AI impact:
[Script] handles all remote API querying, token authentication headers, URL parsing, ISO timestamp parsing (including UTC 'Z' handling), and author filtering deterministically. AI prompt size and behavior remain unaffected.

Expected token impact:
0 additional tokens consumed by AI; data is normalized to identical compact representations.

Result:
Developers can log work across arbitrary remote GitHub repositories without cloning them locally.
