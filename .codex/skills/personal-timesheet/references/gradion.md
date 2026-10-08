# Gradion publishing

Use this reference only when the user explicitly asks to submit or log work to Gradion.

## Defaults

- Base URL: `https://workspace.gradion.com`
- App slug: `timesheet`
- Classification: `INTGRADI2610` (`Gradion Intern Academy 2026`, `Internal Project`)
- Task: `#SE`
- Bundle version header: use `GRADION_SKILL_VERSION` when set, otherwise `1.9.0`

If the requested classification or task differs, resolve it before writing. Do not silently use these defaults for unrelated work.

## Authentication

Read `GRADION_API_TOKEN` from the process environment. On macOS, if it is absent, read the existing Keychain item without displaying it:

```bash
GRADION_API_TOKEN="$(security find-generic-password -a "$USER" -s GRADION_API_TOKEN -w)"
GRADION_SKILL_VERSION="${GRADION_SKILL_VERSION:-1.9.0}"
```

Never pass the token as a command-line argument, print it, persist it in an artifact, or commit it. Unset it after the request sequence.

Every request uses:

```text
Authorization: Bearer <runtime token>
X-Gradion-Skill-Bundle-Version: <version>
X-Requested-With: XMLHttpRequest
Content-Type: application/json
```

## Read before write

Call:

```text
POST /api/me/apps/timesheet/tools/list_my_entries/call
```

with:

```json
{"arguments":{"dateFrom":"YYYY-MM-DD","dateTo":"YYYY-MM-DD","limit":50,"offset":0}}
```

Save the response inside the current run directory. Treat `isError: true`, malformed content, or an incomplete page as a failure. Parse all returned intervals before writing.

Skip an interval that already exists with the intended classification and task. Do not create a new entry that overlaps an existing entry. If an existing row conflicts with the proposal, report the conflict; do not delete or replace it without a separate user request and a supported tool.

## Write one interval

Call:

```text
POST /api/me/apps/timesheet/tools/log_time/call
```

with:

```json
{
  "arguments": {
    "classification": "INTGRADI2610",
    "date": "YYYY-MM-DD",
    "startTime": "HH:MM",
    "endTime": "HH:MM",
    "description": "Evidence-backed description",
    "task": "#SE"
  }
}
```

The user must explicitly confirm attendance before a Calendar-only or attendance-unconfirmed meeting is submitted. Git or PR activity inside a scheduled meeting does not prove meeting attendance.

After every successful write, retain the response and its resource ID. Stop the remaining writes if any call reports an error. Finally call `list_my_entries` again, verify all intended intervals exactly once, and report the submitted total.
