# Approved default OT and requested overrides

Prepare range requests with `--work-windows "$TS_WORK_WINDOWS" --review-ot`.
Morning-start shorthand uses `--work-day-start HH:MM`, which automatically enables
OT and defines main as start–12:00 plus 13:30–18:30.
Main windows are NORMAL. The user's standing rule approves one estimated hour
before each outside-main commit, using its minute-floored time as the end. Subtract
main coverage, clip to the selected local day, and union overlapping OT intervals.
For example, with main ending 16:00, a commit at 18:00 creates 17:00–18:00;
a commit at 16:20 contributes only 16:00–16:20. Never extend an OT window beyond
its ending commit or fill gaps between separate hours.

New v8 snapshots freeze the 60-minute policy, commit-based end and standing-rule
approval. `defaulted` is approved: proceed without a blocking question, a user
reply or a timeout. Show the estimated intervals and separate NORMAL/OT totals
in the preview. Their approval follows the explicit standing instruction; it is
not a claim that Git measured the duration. PR and Calendar without a commit do
not generate default OT. Calendar attendance stays unconfirmed. No new BREAK
input or work row is introduced. Publishing still requires an explicit request.

When the user requests changed OT hours or no OT, use the supplied answer directly
and write a new snapshot from the same evidence. Do not collect sources again.

```bash
TS_RESOLVED_SNAPSHOT="$TS_RUN/activity-ot-override.json"
TS_RESOLVED_AI_INPUT="$TS_RUN/ai-input-ot-override.json"
"$TS_PYTHON" "$TS_ROOT/scripts/run_pipeline.py" --phase confirm-ot \
  --snapshot "$TS_SNAPSHOT" \
  --resolved-snapshot "$TS_RESOLVED_SNAPSHOT" \
  --ot-windows "$TS_OT_WINDOWS" \
  --export-ai-input "$TS_RESOLVED_AI_INPUT"
```

Replace `--ot-windows "$TS_OT_WINDOWS"` with `--decline-ot` for no OT. On success,
set `TS_SNAPSHOT="$TS_RESOLVED_SNAPSHOT"` and
`TS_AI_INPUT="$TS_RESOLVED_AI_INPUT"`, then summarize/assemble that snapshot.
Explicit overrides must stay outside main and within the target local day.
Ask only for missing or ambiguous hours if the user requested an edit without
supplying enough information. Default hours need no extra confirmation.

Historical v7 snapshots keep their original manual-hour rule. If one is pending,
ask one combined question for actual start/end intervals or no OT; commit/PR
observations there do not infer any hours. Use an already supplied explicit answer
without asking again. Recording the answer creates a new snapshot and preserves
the original. Do not silently apply a v8 default to a historical pending snapshot.

NORMAL/OT boundaries split allocations and preserve shared topics. Short commit
allocations merge with the preceding piece of the same type. Keep estimated
labels and the row's approval basis so default-rule approval and explicit user
hours can be distinguished.
