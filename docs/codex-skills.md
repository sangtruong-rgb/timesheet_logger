# Codex launcher and skills

Short commands for requesting a daily preview from Codex CLI. All of them run the
same Python pipeline; the skills never compute time windows themselves.

For Codex CLI on macOS, use the project launcher when live collection needs the
GitHub credential store and outbound Calendar access:

```bash
./bin/personal-timesheet-codex
```

For a short request with your confirmed start time:

```bash
./bin/personal-timesheet-codex 09:00
```

A morning start alone now creates NORMAL windows from that start to 12:00 and
13:30–18:30 (five afternoon hours), with approved estimated OT outside them.
For example, `08:30` means 08:30–12:00 and 13:30–18:30. Development blocks
require commit or PR evidence; empty windows and unsupported closing tails stay blank.
Calendar entries remain separate, with attendance unconfirmed unless declared.
The skill uses Python's `--work-day-start HH:MM`; it does not compute the windows
itself. A start at or after noon needs explicit windows.

Multiple confirmed windows for today (preview only):

```text
$personal-timesheet 8:00-12:00, 1h30-4:00
$personal-timesheet-windows 8:00-12:00, 1h30-4:00
```

From the terminal, run `./bin/personal-timesheet-codex "8:00-12:00, 1h30-4:00"`.
Both skill names use the same pipeline: 08:00–12:00 and 13:30–16:00 are the
NORMAL main windows. Each outside-main commit defaults to an approved estimated
hour ending at its minute-floored timestamp, counting only the portion outside
main and merging overlaps. No confirmation reply is required. The preview shows
the default intervals; requested edits or no OT use the same frozen evidence,
without recollection. NORMAL and OT totals are separate. Add a date to apply the windows to that date. These windows replace
profile hours/breaks only for this run. See [daily work windows](work-schedule.md#confirmed-daily-windows).

Or type `$personal-timesheet 09:00` inside an existing Codex CLI session opened
in this repository. This requests today's live-source preview with measured Codex
summary usage when eligible. The skill asks for a missing start or other blocking
information, without reconfirming supplied facts. A morning start without an end
uses the noon / five-hour afternoon default with OT. Specify another date or
custom hours in plain language when needed;
publishing to Gradion requires an explicit request.

For supplied OT and attendance confirmations, use
`$personal-timesheet-confirmed 9:00` inside Codex, or launch:

```bash
./bin/personal-timesheet-codex "9:00, OT confirmed, attendance confirmed"
```

The [confirmed timesheet skill](../.codex/skills/personal-timesheet-confirmed/SKILL.md)
records the declarations for that date/run in `confirmations.json` and uses them
in its report and any explicitly requested publishing. It does not reconfirm
covered completed meetings or approved OT. Future meetings remain scheduled;
conflicts still need resolution. Generated Python attendance labels stay unchanged
because the assembler does not yet consume this separate receipt. Bare shorthand
still requests a preview.

The launcher starts a fresh Codex session in this repository with network access
enabled and approval policy `on-request`. It uses `danger-full-access` because the
standard workspace sandbox cannot read the host GitHub credential store. Review
commands shown by Codex and use this launcher only for this trusted checkout.
