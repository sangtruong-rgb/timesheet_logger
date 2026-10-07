# Frozen snapshots and storage validation

Group B covers F28–F31 and the timesheet portion of F32/F37; CSV protection is
completed in group C. Prepare collects and validates sources, stores immutable
normalized evidence, blocks, review evidence, AI payload, run ID and SHA-256
fingerprint. It never saves final timesheets or token records. Assemble validates
the fingerprint and rebuilds blocks/payload from frozen evidence without contacting
sources. Fingerprints detect inconsistencies, not adversarial authenticity.

AI payloads deduplicate text and qualified PR references, omit Calendar-only blocks,
and enforce a 12,000-byte default on exact exported JSON including metadata. A
bytes/4 token estimate is explicitly heuristic; no guaranteed token count or
350-token claim. Overflow blocks synthesis and retains evidence in a draft. Ticket
IDs are extracted by a shared helper; no ticket clustering or automatic judgment
cache exists. Validated supplied judgments can be reused with the same snapshot.

AI descriptions must omit PR references. Scripts own the suffix. Positive durations
must agree with exact aware intervals, including DST, or legacy clock boundaries.
Stored/incoming source arrays, ownership, sidecars and manual conflicts are checked
before mutation. Export cannot replace a daily store or audit sidecar.

POSIX directory locks serialize writers. Files use same-directory fsync + atomic
replace. A journal records prior bytes so a failed bundle rolls back and an
interrupted update is recovered under the next writer's lock. Readers that ignore
locks may see a bundle between individual replacements; this is recoverable
multi-file storage, not an instantaneous atomic database transaction. Corrupt
journals block writes and remain available for review. An external AI export must
be supplied again to authorize recovery of a journal referencing that path.

Validation: 374 tests pass on Python 3.14.6, including 17 new regressions for phases,
immutability/tampering, bounded Unicode payloads, suffix injection, inconsistent
duration/source arrays, DST saving, injected write rollback, crash recovery, lock
contention and corrupt journal preservation. Source subprocesses have 120-second
timeouts and controlled failure envelopes. No external AI service was invoked.
