# F03: keyed AI summary matching

A partial AI response describing 09:30–12:00 previously also attached its first
summary to the first candidate, a 09:00–09:30 stand-up. The mapper stored each
response under its interval and array index, then used the index as a fallback.
This was especially relevant because SKILL.md asks for summaries only for blocks
with commit/PR activity; calendar-only blocks can legitimately be omitted.

## Resulting behavior

- Shared candidate identity is `YYYY-MM-DD_HH:MM_HH:MM`, emitted as `block_id`
  in minimal AI input and retained in final audit entries.
- Preferred AI output is `[{"block_id": "...", "description": "..."}]`.
  Order does not matter. Partial or empty output is allowed; each unmatched
  block uses its own existing deterministic fallback.
- Entries retain `summary_source: ai|fallback` and all original source evidence.
  Commit hashes still stay out of the compact AI payload.
- Legacy output with explicit date and interval must exactly match a candidate.
  Date-less legacy intervals are accepted only for a single candidate day with
  unique identities. Position-only responses are rejected.
- Duplicate or unknown IDs, inconsistent date/interval metadata, duplicate
  candidates and malformed summary schemas fail before assembly/storage.
- An explicitly requested missing, invalid or non-array AI file fails; it does
  not silently become fallback. The standalone assembler returns exit 2 and
  preserves an existing output. The pipeline saves an AI-validation review draft
  with source evidence and current AI input while leaving final files, collection
  manifest, previous AI export and token records unchanged.
- SKILL.md, README and workflow now describe keyed output and partial-response
  handling. No positional matching remains.

## Validation on 2026-10-06

**137/137 tests pass** (`python3 -m unittest discover -s tests -v`), including
28 new F03 regressions; `git diff --check` passes.

Tests cover the original partial-response reproduction, ID round trips,
reordered blocks/responses, same intervals on different dates, legacy
compatibility/ambiguity, unknown/duplicate/contradictory identities, malformed
files/schemas, preserved commit/PR evidence, fallback ownership, and blocked
pipeline/standalone output preservation. Synthetic cases use temporary storage.

Two isolated pipeline phases read real GitHub and Google Calendar data, each
returning COMPLETE / exit 0: 15 default-branch commits, 4 PR references and zero
primary-calendar events. The first phase exported the real payload and fallback
entry. Codex wrote a keyed summary from that payload's commit messages/PR titles;
the second phase consumed this JSON through `--ai-output`. Its entry used the
exact ID and `summary_source = ai`, preserving every original source record.
The CLI made no external AI API call. Ten old data/config files and both OAuth
files remained unchanged. No fixtures replaced real collection, and no Calendar
event was modified.

## Remaining scope

Block identity does not validate the semantic truth of an AI sentence, freeze
the source snapshot between two phases (F28), or repair block segmentation,
fallback meeting claims, inferred durations, timezone association or overlaps
(F04–F08). The real 240-minute block remains an estimate; its synthetic Calendar
label remains F21. Token attribution/budgets and installed Claude Code skill
invocation are still unverified. The real Calendar day was empty; sparse output
with a meeting was validated synthetically.

Issue #4 remains open as ready for review until audit/merge. This branch is based
on F02 / PR #51; no prerequisite PR is merged by this change.
