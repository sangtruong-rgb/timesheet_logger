# Data provenance and historical files

The tracked `fixtures/sample_*.json`, `raw/ai_*_2026-10-06.json`,
`timesheets/2026-10-06.json` and `.md` are **legacy mixed/demo artifacts**. They
predate the fixes, combine real bootstrap activity and synthetic meetings/PRs,
and contain invalid old interval/AI results. They are preserved for comparison,
not an authoritative worked-timesheet or current output example. Do not assemble
from them, merge them into a live run, or claim their totals as actual hours.

`token-usage.csv` contains the historical manually recorded
`session-demo-20261006` row. Its 405 tokens are **synthetic/self-reported demo data**,
not transcript-measured live usage. The original CSV is preserved, not migrated.
New audits must use a separate CSV and an explicit marked-run manifest.

Correct current examples live in `examples/synthetic/`, with explicit DEMO source
provenance, unconfirmed attendance and estimated duration labels. They are generated
by `scripts/build_demo.py`; no real account or external service is involved. The
example usage row is explicitly synthetic and must not be used as a performance
measurement. Correct examples are outside production timesheets/token files.

`improvement-log-legacy.md` preserves the old improvement log verbatim. Its historic
3,000–8,000 baseline, <350-token and zero-waste claims had no measurements and are
withdrawn. Ticket extraction was not ticket clustering. The corrected authoritative
log is `improvement-log.md`, which separates observed tests from unmeasured savings.

`audit/` is ignored: real source evidence may be private and is not published in
PRs. OAuth credentials/token and personal profiles remain ignored and never appear
in committed examples. Demo tests and real verification must be reported separately.
