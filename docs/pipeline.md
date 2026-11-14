# Pipeline phases

Prepare, summarize, assemble: how a run is split into frozen phases.

For short commands that run each stage and display its output, use
[`bin/timesheet-steps`](workflow-steps.md). It exposes source evidence, blocks,
the actual compact AI request, summary output, usage and final Markdown, with a
separate console log per stage. Only its `summary` command calls AI.

```bash
python3 scripts/run_pipeline.py --phase prepare --date 2026-10-07 \
  --config config/user-config.json --work-start 09:00 \
  --snapshot data/audit/my-run/activity.json \
  --export-ai-input data/audit/my-run/ai-input.json \
  --output-dir data/audit/my-run/timesheets

# Read AI input; create [{"block_id":"...", "description":"Concise summary"}].
# Omit --ai-output to use deterministic fallback instead.
python3 scripts/run_pipeline.py --phase assemble \
  --snapshot data/audit/my-run/activity.json --ai-output data/audit/my-run/ai-output.json \
  --output-dir data/audit/my-run/timesheets
```

Prepare writes an immutable snapshot and optional AI export, not final timesheets
or tokens. Assemble validates/rebuilds frozen evidence without recollecting. The
snapshot includes a run ID and SHA-256 fingerprint; it is not a digital signature.
Different sources require a new snapshot. Default --phase run offers single-pass
collection plus deterministic fallback (or explicitly supplied validated judgments).
Use frozen phases for AI synthesis to avoid stale source descriptions.

Unknown/duplicate/stale block IDs, conflicting metadata, malformed requested AI,
PR references in AI descriptions and inconsistent durations block writes. Partial
keyed summaries use each unmatched block's own fallback. Scripts own exactly one
PRs suffix, with owner/repo qualification for colliding PR numbers.
