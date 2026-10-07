# R01: Calendar test environment isolation

The empty-source regression created a token under its temporary working directory,
but the collector's default path is beside the bundle scripts. An unrelated root
token therefore masked the missing test configuration. Clean checkouts failed.

Each pipeline-source test now supplies its own `GOOGLE_CALENDAR_TOKEN` and
`GOOGLE_CALENDAR_CREDENTIALS` in the real child-process environment. The token is
absent for missing-source tests and created for the empty-source regression.
Inherited authentication, Calendar, repository and usage-path overrides are removed
from that test's child environment. No production configuration behavior changed.

Configuration precedence tests launch a fresh Python interpreter with an actual
process environment; they do not patch `os.environ` or the settings functions.
They check both Calendar paths, CLI > environment > profile > bundle defaults,
profile-relative and environment-relative paths, spaces in invoking paths,
repository selection, missing tokens and explicitly empty environment values.

The deterministic empty-source test still uses Google/GitHub service stand-ins.
It verifies successful empty-list behavior, not OAuth/API integration. The live
verification below uses the installed Google SDK, existing readonly OAuth token,
real network requests and no fixtures or service mocks.

## Validation on 2026-10-07

- Source branch: 360/360 tests passed in a checkout without OAuth files or private
  config. Previously the same head's suite failed 1 of 357 tests.
- Pipeline-source and source-configuration suites: 28/28 passed with intentionally
  wrong inherited Calendar/repository/usage environment variables.
- Actual Calendar API, Asia/Ho_Chi_Minh, 2026-10-07: environment token override
  returned `live/success`, 1 event, despite a missing token in the explicit profile.
- A missing environment token returned `live/unavailable`, exit 2.
- A CLI token override above that missing environment token returned `live/success`,
  1 event. No OAuth file was replaced or written.

Run the deterministic regressions without personal credentials:

```bash
python3 -m unittest discover -s tests -p 'test_pipeline_sources.py'
python3 -m unittest discover -s tests -p 'test_remaining_sources.py'
python3 -m unittest discover -s tests
```

For live verification, use a Python environment with `requirements-calendar.txt`
installed. Supply real authorized paths through the shell environment and use an
audit output directory. Paths are not token contents:

```bash
export GOOGLE_CALENDAR_TOKEN='/absolute/path/to/token.json'
export GOOGLE_CALENDAR_CREDENTIALS='/absolute/path/to/credentials.json'
python3 scripts/get_calendar_activity.py --config '/absolute/path/to/profile.json' \
  --date 2026-10-07 --output '/absolute/path/to/audit/calendar.json'
```

Live tests depend on current credentials/network and are reported separately from
the reproducible test suite. A live failure must remain unavailable/error; no
sample data is used to make it pass. Private live artifacts belong in ignored
`data/audit/`, never committed. R02–R04 and Claude live usage acceptance remain
separate unresolved audit items.
