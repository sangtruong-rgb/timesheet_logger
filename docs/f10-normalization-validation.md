# F10 — validated daily activity

The normalizer previously retained raw timestamp strings, sorted lexically and
accepted other-day evidence. Mixed offsets gave incorrect ordering; naive commit
times could crash block construction. Invalid Calendar intervals reached later
stages without a defined normalization policy.

## Implemented policy

- Validate source arrays/objects, string fields, positive PR/event identities,
  commit identities and supported action types. Conflicting records for the same
  qualified commit identity block the run instead of silently picking the first.
- Parse aware timestamps, convert to the selected timezone, retain changed
  original representations and sort by UTC instant, including repeated DST hours.
- Use the selected local day's half-open UTC bounds. Only in-day commit/PR
  actions participate in blocks. Each invalid, missing, naive or other-day action
  remains separate review evidence and contributes no duration.
- Timed Calendar events require aware timestamps and positive elapsed intervals.
  All-day events require canonical dates with exclusive end after start.
  Intersecting events keep full extent until block clipping. Other-day Calendar
  events remain review evidence rather than context/work time for this day.
- Structural/Calendar validation failure produces a raw-evidence draft, exit 2
  and preserves existing final timesheets, manifest, AI payload and token records.
  Source failure remains INCOMPLETE even when normalization is also blocked.
- Explicit unreadable standalone input files fail instead of silently becoming
  empty successful inputs. Optional omitted sources remain backward compatible.

## Validation

339/339 unit/integration tests pass, including 29 new F10 tests. Tests cover mixed
offset ordering, local-day boundaries, DST repeated hours, source immutability,
active-model idempotency, qualified duplicates, action conservation, malformed
structure, raw-evidence drafts, final-file preservation and standalone CLI errors.
Five earlier tests now assert the new explicit policy rather than old behavior.

Four isolated real-data pipeline runs (two dates, each repeated) collected all
three sources successfully, with COMPLETE collection and required activity review:

| Day | Git | PR references | Primary Calendar | Proposed duration | Review events |
| --- | ---: | ---: | ---: | --- | ---: |
| 2026-10-06 | 15 | 7 (8 actions) | 0 | 240 estimated minutes | 12 |
| 2026-10-07 | 0 | 4 | 1 | 60 scheduled minutes | 4 |

Exact rerun outputs, ten protected old data/config files and both OAuth files
remained unchanged. Host TZ was UTC; selected zone came from the Vietnam profile.
No source fixtures were substituted, Calendar was not edited, and no external AI
API call was made. Synthetic comparison changes active order from
`late, naive, early, tomorrow` to `early, late`, retaining naive/tomorrow separately.

Collection COMPLETE does not confirm actual attendance, estimated work duration,
or completion of human review. Full storage schema validation/concurrency,
run-scoped actual AI token collection and breaktime/OT policy remain separate.
