You are acting as a senior software engineer helping me complete an internship assignment called:

**Assignment 1 — Personal Pilot Timesheet Logger**

Your job is to inspect my workspace, design the solution, implement it, test it, and leave me with a working Claude Code Skill that I can run every working day.

Do not only explain what I should do. Actually create the files, scripts, configuration, tests, and documentation in the repository.

---

# 1. Project objective

Build a personal automated timesheet logger.

Every day, the system must collect my real work activity from:

1. Git commits authored by me
2. Pull request activity
   - PRs I opened
   - PRs I reviewed
   - PRs merged today
3. Google Calendar events

The system must combine this information into timesheet entries for the current day.

The final deliverable must be packaged as a Claude Code Skill containing at minimum:

```text
<skill-folder>/
├── SKILL.md
└── workflow.md
```

Supporting scripts and data files should also be included.

This is not just a prompt-writing task. The deterministic parts of the workflow must be implemented as real scripts.

---

# 2. Most important design principle

The assignment specifically tests whether I correctly separate:

- deterministic work → `[Script]`
- work requiring judgment → `[AI]`

Use this rule throughout the implementation:

> If the same input should always produce the same answer according to a clearly definable rule, implement it in code as `[Script]`.

> Only use `[AI]` when the task genuinely requires semantic interpretation, ambiguity resolution, topic understanding, or natural-language judgment.

Do NOT use AI to do tasks that can reliably be implemented using Python, shell, APIs, regex, sorting, filtering, arithmetic, JSON parsing, or fixed business rules.

Examples:

```text
[Script] Find today's commits
[Script] Find today's PRs
[Script] Read calendar events
[Script] Parse timestamps
[Script] Sort activities
[Script] Calculate duration
[Script] Remove duplicates
[Script] Format final timesheet structure
[Script] Save files
[Script] Calculate token usage

[AI] Determine whether semantically related commits belong to the same topic
[AI] Write a concise human-readable description of a topic
[AI] Decide how to interpret genuinely ambiguous calendar activity
[AI] Flag a day that appears incomplete when no deterministic rule can decide
```

Before implementing the workflow, explicitly list every workflow step and classify it as `[Script]` or `[AI]`.

If you classify something as `[AI]`, ask yourself:

> Can this reasonably be converted into a deterministic rule?

If yes, implement it as `[Script]` instead.

---

# 3. First step: inspect the existing workspace

Before writing the implementation, inspect the current repository.

Determine:

- repository structure
- programming languages already being used
- whether it is GitHub or GitLab
- whether `gh` or `glab` is installed
- whether authentication already exists
- whether there are existing Claude Skills
- where Skills are stored in this workspace
- existing project conventions
- available MCP/connectors
- whether a Google Calendar integration already exists
- existing `.claude`, `skills`, `scripts`, or automation-related directories
- available package managers
- existing lint/test tooling

Prefer integrating naturally into the existing workspace rather than creating an isolated architecture that ignores repository conventions.

Do not modify unrelated files.

Do not commit directly to `main`.

If Git branching is available, create a focused branch for this task.

Suggested branch name:

```text
feat/personal-timesheet-skill
```

---

# 4. Proposed project structure

Adapt this structure if the repository already has stronger conventions:

```text
personal-timesheet/
├── SKILL.md
├── workflow.md
├── README.md
│
├── scripts/
│   ├── get_git_activity.py
│   ├── get_pr_activity.py
│   ├── get_calendar_activity.py
│   ├── normalize_activity.py
│   ├── build_time_blocks.py
│   ├── prepare_ai_input.py
│   ├── build_timesheet.py
│   ├── save_timesheet.py
│   └── collect_token_usage.py
│
├── data/
│   ├── timesheets/
│   ├── raw/
│   ├── token-usage.csv
│   └── improvement-log.md
│
├── tests/
│   ├── test_git_activity.py
│   ├── test_normalization.py
│   ├── test_time_blocks.py
│   ├── test_deduplication.py
│   └── test_timesheet.py
│
└── config/
    └── example-config.*
```

Do not force this exact structure if a simpler design is cleaner.

The important thing is separation of responsibilities.

---

# 5. Phase 1 — Data collection

Implement deterministic collectors.

## 5.1 Git commits

Create a script that retrieves commits authored by me for a requested date.

Default:

```text
today
```

But support:

```bash
--date YYYY-MM-DD
```

if practical.

The script should capture at least:

```text
repository
commit hash
timestamp
author
commit message
branch if available/reliable
```

The date calculation must respect local timezone.

Do not send the complete raw `git log` to AI.

Normalize the output first.

Example normalized structure:

```json
{
  "repository": "example-project",
  "hash": "abc123",
  "timestamp": "2026-10-06T10:24:00+07:00",
  "message": "fix customer CSV validation"
}
```

Support multiple repositories if the workspace contains multiple repos that I actively work on.

Avoid scanning irrelevant directories.

---

# 6. Phase 2 — Pull request activity

Determine whether this workspace uses GitHub or GitLab.

Use the appropriate existing authenticated mechanism:

```text
GitHub → gh CLI/API
GitLab → glab CLI/API
```

Prefer an already configured CLI or connector instead of implementing authentication from scratch.

Retrieve PR/MR activity for the selected day:

- opened by me
- reviewed by me
- merged today where relevant to my work

Capture:

```text
number/id
title
repository
URL
status/action:
- opened
- reviewed
- merged
timestamp if available
```

Normalize the result.

Example:

```json
{
  "id": 1182,
  "repository": "frontend",
  "title": "Fix deal board totals",
  "status": "merged",
  "url": "..."
}
```

Deduplicate PRs.

A PR may appear in multiple API responses; the final timesheet should not accidentally contain duplicate PR references.

---

# 7. Phase 3 — Google Calendar

Retrieve my Calendar events for the requested day.

Prefer an available MCP, existing integration, Google API setup, or repository-supported connector.

Do not hardcode credentials.

Do not commit credentials or tokens.

Capture at least:

```text
event title
start time
end time
calendar identifier if useful
attendees optional
```

Ignore irrelevant raw API metadata.

Normalize events into a compact structure.

Example:

```json
{
  "title": "Backend planning",
  "start": "2026-10-06T09:00:00+07:00",
  "end": "2026-10-06T09:30:00+07:00"
}
```

If Calendar integration cannot currently be completed because authentication or configuration is missing:

1. implement the interface/adapter
2. clearly document the missing setup
3. provide the exact setup instructions
4. allow fixture/mock data for testing
5. do not fake successful Calendar retrieval

---

# 8. Phase 4 — Normalize all data

Create a deterministic normalized daily activity model.

Something similar to:

```json
{
  "date": "2026-10-06",
  "calendar": [],
  "commits": [],
  "pull_requests": []
}
```

Only include fields actually needed later.

The normalized output must be much smaller than the original API responses.

Store raw data separately only when useful for debugging/audit.

The AI should never receive:

- full Git logs
- full GitHub/GitLab JSON responses
- full Google Calendar API responses
- previous days of irrelevant activity
- debugging logs

---

# 9. Phase 5 — Build time blocks

The final timesheet requires multiple entries per day rather than one giant entry.

Use deterministic rules wherever possible.

Calendar events should help define time blocks.

For example:

```text
09:00–09:30 Daily stand-up
09:30–12:00 Development
13:30–14:30 Product meeting
14:30–17:00 Development
```

The logger should create reasonable blocks such as:

```text
09:00–09:30
09:30–12:00
13:30–14:30
14:30–17:00
```

Associate Git and PR activity with blocks where reliable timestamps make that possible.

Do NOT ask AI to calculate timestamps or durations.

Those are `[Script]`.

If a day has no Calendar events, still produce at least one timesheet entry based on Git/PR activity.

Use a documented deterministic fallback rule.

---

# 10. Phase 6 — Decide what AI actually receives

Create a `prepare_ai_input` step.

This is very important.

The AI input must be as small as reasonably possible.

Example:

```json
{
  "date": "2026-10-06",
  "block": {
    "start": "09:30",
    "end": "12:00"
  },
  "calendar_titles": [
    "Development"
  ],
  "commit_messages": [
    "fix customer CSV validation",
    "handle malformed import rows",
    "update customer count"
  ],
  "prs": [
    {
      "id": 1182,
      "title": "Fix customer import issues"
    }
  ]
}
```

The AI should NOT be asked to rediscover:

- date
- start/end times
- PR IDs
- repository names
- timestamps
- durations
- duplicates

Scripts already know these.

---

# 11. Phase 7 — AI responsibilities

Keep AI responsibilities deliberately narrow.

Initially, AI may perform approximately these tasks:

### AI task 1: semantic topic grouping

Determine whether activities inside a time block represent:

- one topic
- two topics
- several related topics

Example input:

```text
fix customer CSV validation
handle malformed import rows
update import tests
```

Likely output:

```text
Customer CSV import and validation
```

Example:

```text
fix CSV import
update forecasting formula
fix dashboard totals
```

AI might determine these represent several subtopics.

Do not create one timesheet line per commit.

Group work by meaningful topic.

### AI task 2: concise description

Produce a short human-readable description suitable for a timesheet.

Avoid:

```text
I did X. Then I did Y. Then I did Z.
```

Prefer:

```text
Customer import improvements covering CSV validation,
malformed-row handling, and related tests.
```

### AI task 3: ambiguity only when needed

Example:

Calendar says:

```text
Focus time
```

but the associated commits clearly concern the payments feature.

AI may infer that the block should be described based on the actual work activity.

However, avoid letting AI invent work unsupported by Git, PR, or Calendar evidence.

---

# 12. Phase 8 — Deterministically build final entry

After AI returns only the judgment component, scripts should construct the actual timesheet record.

Each entry must contain at minimum:

```text
Date
Start time
End time
Description
```

The description should contain:

1. grouped topic summary
2. one inline PR list at the end

Example:

```text
Date: 2026-10-06
Start time: 09:30
End time: 12:00
Description: Customer import improvements covering CSV validation,
malformed-row handling, and tests. PRs: #1182, #1190
```

Do NOT scatter PR numbers throughout the text.

Use exactly one `PRs:` section per timesheet entry.

If no PR exists, choose a consistent representation, for example:

```text
PRs: None
```

or omit the suffix.

Document whichever rule you choose.

---

# 13. Keep source evidence

For auditability, preserve the underlying source information associated with each generated entry.

For example, internally store:

```json
{
  "entry": {
    "date": "...",
    "start": "...",
    "end": "...",
    "description": "..."
  },
  "sources": {
    "calendar": [],
    "commits": [],
    "pull_requests": []
  }
}
```

The user-facing entry can remain concise.

The source information must make it possible for someone reviewing the log to verify how the entry was created.

---

# 14. Prevent duplicate daily entries

The assignment specifically requires reruns not to create duplicate entries.

Implement idempotency.

If I run:

```text
log today's work
```

three times on the same day, it must not blindly append the same block three times.

Create a stable identifier such as:

```text
date + start_time + end_time
```

or another suitable deterministic entry key.

On rerun:

- update existing entry if needed
- or safely skip unchanged entries

Do not duplicate them.

---

# 15. Timesheet storage

Choose a simple storage mechanism.

Prefer something easy to inspect and version/control safely.

Possible choices:

```text
CSV
JSON
JSONL
Markdown
SQLite
```

Use the simplest option that supports:

- multiple entries/day
- updating entries
- audit/source metadata
- deduplication
- easy review

If one format is best for machine storage and another for human review, it is acceptable to generate both.

For example:

```text
data/timesheets/2026-10-06.json
data/timesheets/2026-10-06.md
```

Avoid overengineering.

A polished UI is NOT required.

---

# 16. SKILL.md

Create a valid `SKILL.md`.

It should clearly explain:

- skill name
- purpose
- when Claude should use it
- trigger phrases
- invocation behavior
- inputs
- outputs
- important constraints
- location of `workflow.md`

Possible trigger phrases:

```text
log today's work
log my work today
create today's timesheet
run my timesheet
```

The Skill should also support a specified date if practical:

```text
log my work for 2026-10-06
```

Do not put the entire implementation into `SKILL.md`.

Keep it concise enough for Claude to identify and invoke correctly.

---

# 17. workflow.md

This file is one of the most important deliverables.

Write the complete daily workflow as an ordered sequence.

Every step MUST be labelled either:

```text
[Script]
```

or:

```text
[AI]
```

Example structure:

```text
1. [Script] Determine requested date.
2. [Script] Retrieve Git commits.
3. [Script] Retrieve PR activity.
4. [Script] Retrieve Calendar events.
5. [Script] Normalize all sources.
6. [Script] Create candidate time blocks.
7. [Script] Associate activities with blocks where deterministically possible.
8. [AI] Group semantically related activity inside each block.
9. [AI] Write one concise topic-based description.
10. [Script] Append PR list.
11. [Script] Validate required fields.
12. [Script] Upsert entries into the timesheet store.
13. [Script] Record source evidence.
14. [Script] Record token usage.
```

For every `[AI]` step, explain briefly why deterministic rules are currently insufficient.

---

# 18. Token budget

The assignment requires a target daily AI token budget.

Add a section to `workflow.md` called:

```text
## Token Budget
```

Set an initial realistic target.

For example:

```text
Target AI input:
< 1,000 tokens per normal working day

Target total AI usage:
keep as low as reasonably possible while maintaining useful summaries
```

Do not blindly choose these exact numbers if implementation evidence suggests a better target.

Explain how token usage is minimized:

- script filters raw data
- only today's data is considered
- only relevant fields are passed to AI
- raw API responses are excluded
- deterministic formatting stays in scripts
- previous days are excluded unless explicitly required

---

# 19. Token usage collector

Implement a script that reads Claude Code session transcripts under:

```text
~/.claude
```

Claude sessions are stored as `.jsonl`.

The script should identify the relevant session/run and extract usage information such as:

```text
input tokens
output tokens
cache-related tokens if available
session id
date
```

Calculate:

```text
daily total tokens used by this Skill
```

If the Skill runs more than once during the day, aggregate those runs.

Store results in something like:

```text
data/token-usage.csv
```

Suggested fields:

```text
date
session_id
input_tokens
output_tokens
cache_tokens
total_tokens
notes
```

Make parsing defensive because transcript structure may vary.

If exact session matching cannot be made fully automatic, implement the best reliable mechanism and clearly document any remaining manual input.

Do not fabricate usage numbers.

---

# 20. Improvement log

Create:

```text
data/improvement-log.md
```

The intended development process is:

```text
log
→ identify problems
→ improve workflow/scripts
→ log again
```

Add a lightweight format:

```text
## YYYY-MM-DD

Problem:
...

Observed behavior:
...

Root cause:
...

Change made:
...

Script or AI impact:
...

Expected token impact:
...

Result:
...
```

This should be quick enough to maintain daily.

---

# 21. Important future optimization

Design the system so AI decisions can gradually become Script rules.

Example:

At first:

```text
[AI] Decide whether commits belong to the same topic.
```

Later, if most commits contain ticket IDs:

```text
PAY-123 fix validation
PAY-123 add tests
PAY-123 update endpoint
```

then implement:

```text
[Script] Group commits sharing the same ticket ID.
```

and only send unresolved commits to AI.

Support this philosophy in the architecture.

Do not hard-code unnecessary AI dependency.

---

# 22. Testing requirements

Add automated tests for deterministic logic.

At minimum test:

### Git filtering

Given commits from different days/authors:

```text
only include mine for the requested day
```

### Time ordering

Activities must sort correctly.

### Time blocks

Calendar blocks should produce expected start/end values.

### Deduplication

Same PR returned twice should appear once.

### Idempotency

Running the logger twice must not duplicate timesheet entries.

### No-calendar day

The system must still produce an entry using Git/PR activity.

### Empty day

Handle days with no useful work data gracefully.

Do not invent work.

### Description assembly

Ensure:

```text
PRs: #123, #456
```

appears only once.

### Date/timezone edge cases

At minimum consider activity near midnight.

---

# 23. Security and configuration

Never commit:

```text
Google credentials
API tokens
GitHub tokens
GitLab tokens
OAuth secrets
private calendar data unnecessarily
```

Use environment variables or existing credential stores.

Update `.gitignore` where appropriate.

Provide:

```text
.env.example
```

only if necessary.

Do not put real credentials in it.

---

# 24. README

Create a concise README covering:

## Setup

Dependencies and required authentication.

## Usage

Example:

```text
"log today's work"
```

or direct script execution if needed.

## Architecture

Explain:

```text
Git / PR / Calendar
        ↓
deterministic collectors
        ↓
normalized compact data
        ↓
minimal AI judgment
        ↓
deterministic output writer
        ↓
timesheet
```

## Troubleshooting

Cover likely problems:

- GitHub/GitLab CLI not authenticated
- Google Calendar not configured
- no commits detected
- no Calendar events
- token file cannot be found
- duplicate rerun
- wrong timezone

---

# 25. Git discipline

Follow the assignment's engineering rules during implementation:

```text
one task = focused branch = focused PR
```

Use meaningful commits.

Bad:

```text
update
wip
stuff
fix
```

Good:

```text
feat: collect daily git activity
feat: normalize calendar events
feat: build deterministic time blocks
feat: add token usage tracking
docs: define script-ai workflow split
```

Do not directly commit unrelated changes.

---

# 26. What not to build

Do NOT spend time on:

- polished UI
- complicated frontend
- teammate timesheets
- perfect classification taxonomy
- unnecessary database infrastructure
- large AI agents
- vector databases
- embeddings unless there is a proven requirement
- complex orchestration frameworks unless already used by the workspace

Keep this a small, robust personal automation tool.

---

# 27. Required behavior example

Assume the source data is:

```text
Calendar:

09:00-09:30 Daily stand-up
09:30-12:00 Focus block
13:30-14:30 Product meeting
14:30-17:00 Focus block
```

Git:

```text
09:45 fix invoice validation
10:32 add payment status filter
11:48 update payment tests

15:02 fix CSV import
15:45 update forecast calculation
16:20 fix dashboard totals
```

PRs:

```text
#101 Payment fixes — merged
#104 Dashboard fixes — opened
```

A reasonable generated result would be:

```text
Date: 2026-10-06
Start time: 09:30
End time: 12:00
Description: Payment workflow improvements covering invoice validation,
payment status filtering, and tests. PRs: #101
```

and:

```text
Date: 2026-10-06
Start time: 14:30
End time: 17:00
Description: Dashboard data and forecasting fixes covering CSV import,
forecast calculations, and totals. PRs: #104
```

The exact wording may differ.

What matters is:

- multiple blocks
- topic grouping
- concise description
- PRs grouped inline
- traceable source evidence

---

# 28. Execution process

Do this work in the following phases.

Do not skip directly to writing a huge implementation.

## Phase A — Inspect

Inspect repository and environment.

Output a short implementation plan based on what actually exists.

Identify blockers only if they genuinely prevent implementation.

Do not ask me questions that can be answered by inspecting the repository.

---

## Phase B — Design Script vs AI split

Create a table containing:

```text
Step
Script or AI
Reason
Implementation
```

Be strict.

Challenge every proposed AI step.

---

## Phase C — Implement deterministic core

Implement:

- Git collector
- PR collector
- Calendar adapter
- normalization
- time blocks
- deduplication
- data persistence
- validation

Run tests.

---

## Phase D — Implement minimal AI layer

Create the smallest possible AI interaction.

AI should receive normalized compact data only.

Define strict output schema if practical.

For example:

```json
{
  "topics": [
    "Payment workflow improvements"
  ],
  "description": "Payment workflow improvements covering validation and tests."
}
```

Validate AI output before storing it.

---

## Phase E — Build Skill packaging

Create:

```text
SKILL.md
workflow.md
```

Ensure `workflow.md` accurately reflects the actual scripts.

Do not document imaginary functionality.

---

## Phase F — Token tracking

Implement Claude JSONL token usage parsing and storage.

Test it against existing sessions if available.

---

## Phase G — End-to-end test

Run the complete workflow using:

1. real data if integrations work
2. otherwise realistic local fixtures for any unavailable external source

Verify the entire flow:

```text
collect
→ normalize
→ block
→ AI judgment
→ assemble
→ save
→ rerun
→ no duplicates
```

---

## Phase H — Review

After implementation, inspect your own work critically.

Look specifically for:

- tasks unnecessarily delegated to AI
- large prompts
- raw JSON being passed to AI
- duplicate logic
- unsafe credential handling
- excessive architecture
- missing error handling
- broken idempotency
- timezone problems
- undocumented assumptions

Fix these before considering the work complete.

---

# 29. Final response to me

When finished, give me a concise report containing:

## 1. What you created

List files/directories.

## 2. Architecture

Show:

```text
Git + PR + Calendar
       ↓
Scripts
       ↓
small normalized payload
       ↓
AI judgment
       ↓
Scripts
       ↓
Timesheet
```

## 3. Script vs AI split

Clearly state which steps are deterministic and which still require AI.

## 4. How to run it

Give exact commands/instructions.

## 5. What I need to configure

Only list things that genuinely require my credentials or account access.

## 6. Tests

State what was tested and whether tests passed.

## 7. Remaining limitations

Be explicit.

## 8. Demo instructions

Give me a simple sequence I can perform during my Friday review.

Example:

```text
1. Show today's Git commits.
2. Show today's Calendar events.
3. Run the Skill.
4. Show normalized payload.
5. Show how small the AI input is.
6. Show generated timesheet.
7. Run it again and demonstrate no duplicate.
8. Show token-usage CSV.
9. Explain one [Script] vs [AI] design choice.
```

## 9. Suggested next optimization

Identify one AI decision that could potentially become deterministic during Weeks 2–4.

---

# 30. Definition of done

Do not consider this complete until:

- `SKILL.md` exists
- `workflow.md` exists
- every workflow step is marked `[Script]` or `[AI]`
- every `[Script]` step is backed by actual executable code
- commits are automatically retrieved
- PR activity is automatically retrieved or integration is clearly implemented pending authentication
- Calendar activity is automatically retrieved or integration is clearly implemented pending authentication
- output contains multiple daily entries where appropriate
- topics are grouped rather than one item per commit
- PRs are listed together
- source data is preserved
- rerunning does not produce duplicate entries
- AI receives compact structured data
- a daily token budget exists
- token usage tracking exists
- an improvement log exists
- tests cover major deterministic logic
- README explains setup and usage
- no secrets are committed
- the end-to-end workflow has been tested
- the implementation follows existing repository conventions

Prioritize correctness, simplicity, traceability, and low AI/token usage over cleverness.
