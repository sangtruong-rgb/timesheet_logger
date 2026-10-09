# Data provenance and historical files

`fixtures/sample_*.json` contains test inputs, not actual work records. Select
fixtures explicitly; never substitute them for an unavailable live source.

`raw/`, `timesheets/`, `token-usage.csv` and `audit/` are local runtime outputs and
are ignored by Git. The token collector creates its CSV on the first attributed
record. New audits should use an isolated CSV and an explicit marked-run manifest.

Obsolete mixed/demo outputs from 2026-10-06 and the synthetic 405-token
`session-demo-20261006` CSV row were removed from the checkout's default output
locations. Their earlier versions remain in Git history. They combined bootstrap
activity with synthetic meetings/PRs and invalid old allocations; do not use them
as current examples or measured work/token records.

Correct current examples live in `examples/synthetic/`, with explicit DEMO source
provenance, unconfirmed attendance and estimated duration labels. They are generated
by `scripts/build_demo.py`; no real account or external service is involved. The
example usage row is explicitly synthetic and must not be used as a performance
measurement. Correct examples are outside production timesheets/token files.

The retired `improvement-log-legacy.md` is available in Git history. Its historic
3,000–8,000 baseline, <350-token and zero-waste claims had no measurements and are
withdrawn. Ticket extraction was not ticket clustering. The corrected authoritative
log is `improvement-log.md`, which separates observed tests from unmeasured savings.

`audit/` is ignored: real source evidence may be private and is not published in
PRs. OAuth credentials/token and personal profiles remain ignored and never appear
in committed examples. Demo tests and real verification must be reported separately.
