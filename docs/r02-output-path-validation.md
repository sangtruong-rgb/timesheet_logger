# R02: Protect AI export destinations

AI input is a separate artifact, for example `audit/run/ai-input.json`. It must
never replace frozen evidence, judgments, private setup, usage records or daily
timesheets. Preflight checks now reject conflicting destinations before collection,
input validation or output writes. The effective DEMO export is checked too.
Standalone snapshot/timesheet storage uses the same guard before acquiring locks
and again when preparing the output bundle.

Protected inputs include the snapshot, AI judgments, profile, PR/Calendar fixtures,
configured/CLI/environment OAuth paths, token CSV paths, usage run manifest and its
explicitly referenced session_file. Paths are canonicalized; existing same-file
aliases are checked. Symlink export destinations are refused.

Daily filename conventions are reserved for evidence, in **any directory**:

- YYYY-MM-DD.json and YYYY-MM-DD.md
- YYYY-MM-DD.collection.json
- YYYY-MM-DD.calendar-context.json
- YYYY-MM-DD.activity-review.json

These names are blocked even if the file is absent or corrupt. Use ai-input.json
instead of a date-only export filename. Existing recognized snapshot, daily-entry,
collection, Calendar-context, activity-review and draft JSON is protected even
under a renamed filename. An ordinary prior AI payload can still be updated.

An invalid destination returns exit 2 with OUTPUT PATH BLOCKED and identifies the
path to change. CLI preflight creates no timesheet/draft/AI output; existing files
remain unchanged. This guard does not claim to resolve R03 writer/rollback races.

Run the isolated filesystem and real-subprocess regressions:

```bash
python3 -m unittest discover -s tests -p 'test_output_path_protection.py'
python3 -m unittest discover -s tests
```

The regressions intentionally use synthetic evidence in temporary directories to
test destructive-looking inputs safely. They check exact original bytes, missing
destinations remaining absent, relative/symlink/hardlink aliases, all daily sidecars,
renamed evidence, configured and actual process-environment paths, prepare/assemble,
standalone storage, valid exports and idempotent reruns. They are not live API proof.
Real-source replay and before/after reproductions are recorded separately in the
workspace R02 result report. R03/R04 and Claude usage acceptance remain open.
