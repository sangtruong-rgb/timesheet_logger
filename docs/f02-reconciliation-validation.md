# F02: daily timesheet reconciliation

When a generated 09:00–12:00 interval was regenerated as 09:00–09:30 and
09:30–12:00, storage previously kept all three rows and counted 360 minutes.
Storage now replaces the complete generated daily set, leaving two rows and
180 minutes. Deleted intervals disappear, and an explicitly successful empty
day clears old generated rows while preserving human-owned rows.

## Contract

- `save_timesheet(..., target_date="YYYY-MM-DD", collection_status="complete")`
  receives a complete daily snapshot, not a partial batch. `demo` is also allowed
  in the separately isolated demo directory. Missing dates/statuses and unsuccessful
  statuses cannot clear a store.
- Saved automatic rows have `provenance.kind = generated` and
  `provenance.generator = timesheet_logger`.
- Existing `manual` rows are retained verbatim. Existing `override` rows replace
  candidates with an exact matching date/start/end. A human-owned row overlapping
  any other proposed row requires review; no final file is changed.
- Rows without ownership metadata, unknown ownership, malformed JSON, duplicate
  intervals, and mismatched dates are rejected before writes. Old collection
  metadata is not treated as proof that a human never edited a row.
- Successful empty input writes an explicit empty JSON array and a zero-total
  Markdown table. Identical reruns preserve both file contents.
- The pipeline still stops at its F01 gate when any source fails. Reconciliation
  failures return exit 2 and retain evidence plus proposed entries in a review
  draft; final JSON/Markdown, manifest, AI export, and token file stay unchanged.
  AI export is deferred until reconciliation succeeds.
- Standalone CLI requires `--date` and `--collection-status complete|demo`.
  Standalone demo output is isolated under `<output-dir>/demo/`.

## Validation on 2026-10-06

`python3 -m unittest discover -s tests -v`: **109 tests pass** (75 existing +
34 new F02 regressions). `git diff --check` passes.

The new tests exercise changed/split/resized/deleted intervals, an empty rerun,
exact-rerun byte preservation, source evidence updates, manual and override
preservation/conflicts, ambiguous legacy rows, invalid existing stores, date
isolation, standalone CLI empty-day handling, and demo isolation. Pipeline tests
check final/manifest/AI/token preservation when collection or reconciliation
fails. Synthetic tests use temporary storage; they are not live verification.

Two real pipeline runs in a new ignored audit directory both returned
**COMPLETE / exit 0**, with 15 default-branch Git commits, 3 PR references, and
zero primary-calendar events. Both produced the same single generated interval;
the second run left timesheet JSON and Markdown bytes unchanged. No fixtures or
external AI model call were used. Ten preexisting data/config files and both
OAuth files remained unchanged.

## Limits and review

The real calendar day was empty. Split/deleted-event behavior was verified with
synthetic regression inputs, not by editing the user's Google Calendar.

This change does not migrate or alter legacy logs automatically. Back up and
classify reviewed JSON rows as generated/manual/override before using an old
directory; use a fresh audit directory until that review is complete. JSON is
the audit source of truth; Markdown is rendered output. Manual changes must be
explicitly marked before rerunning.

Generated-calendar overlaps, inferred work durations, all-day/cross-midnight
normalization, sparse AI matching, source scope, and run-scoped token tracking
remain separate findings. The live 240-minute fallback is an estimate, not proof
of four hours worked. File writes are not a transaction across all output files;
concurrent-write/interruption hardening remains F29 in this historical audit.
The unused legacy partial-upsert helper was subsequently removed; daily
persistence uses complete-snapshot reconciliation.

F02 / issue #3 stays open as ready for review until its change is reviewed and
merged. Its branch is based on `fix/github-personal-activity` / PR #50, which
itself depends on F01 / PR #48. No upstream PR is merged by this change.
