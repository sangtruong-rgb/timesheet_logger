# Remaining delivery and acceptance validation — 2026-10-07

Final deterministic suite: **400/400 pass** on Python 3.14.6; 61 added since main's
339-test baseline. Diff check passes. Source, snapshot, AI, storage and usage group
reports describe their individual scope and limitations. The final suite includes
actual temporary Git + explicit fixtures through prepare, keyed AI assembly,
changed-source frozen rerun and idempotent marked-run synthetic usage recording.
It also verifies bundle installation/path independence, regenerated demo output,
controlled export/timeout errors and suffix/source consistency.

F33: project .claude/skills/personal-timesheet and personal
~/.claude/skills/personal-timesheet symlink to the bundle. Installation is idempotent,
refuses another existing destination, and copies no secrets. SKILL.md uses
${CLAUDE_SKILL_DIR} with quoted absolute profile/output paths and real frozen phases.
These packaging rules follow [Claude Code's documented discovery and symlink support](https://code.claude.com/docs/en/skills).
Claude CLI is absent on this machine: actual discovery/invocation remains V01.

F34: old timesheet, raw input/judgment, sample fixtures, private profile and old token
CSV are unchanged. The unsupported empirical improvement claims are withdrawn from
current improvement-log.md; its original bytes are preserved as the explicitly
historical improvement-log-legacy.md (now retained in Git history). data/README.md documents retired mixed legacy data
and labels the old demo token row. examples/synthetic is rebuilt with the current
scripts and explicit DEMO provenance; its 180 proposed minutes comprise 90 scheduled
and 90 estimated, with overlap coverage counted once. Synthetic token numbers are
labeled fabricated examples, not measured performance.

F36: docs now state Python 3.11+ macOS/Linux, optional Google dependencies, effective
settings, hardcoded schedules/D02, bounded payload policy, supported providers and
usage scopes. No automatic ticket clustering/cache, guaranteed token budget, ICS,
GitLab, daily scheduler or attendance confirmation is claimed. The minimum Python
version itself was not live tested here.

D01/D03/D06 follow user-approved decisions. D04/D05 document the existing adopted
account/repository/action relevance and generated/manual reconciliation policy.
D02 configurable schedule and BREAK/OT remain explicitly deferred.

## Real source audit

Separate ignored directory: data/audit/remaining-20261007-100128/combined.
Preparation was invoked from that directory with host TZ=UTC and the configured
Asia/Ho_Chi_Minh profile, not a CLI timezone override. No fixtures, Calendar writes
or external AI service were used. Codex wrote summaries from the actual compact
payload; this is not an actual installed-Claude skill invocation.

| Target day | Git commits | PR references | Calendar | Final proposal | Review |
| --- | --- | --- | --- | --- | --- |
| 2026-10-06 | 21 | 7 (8 actions) | 0 | 1 estimated row, 240 minutes | 16 unassigned |
| 2026-10-07 | 16 | 11 (16 actions) | 1 | 180 estimated + 60 scheduled minutes | 8 unassigned; attendance unconfirmed |

Both preparations returned success with no final timesheets or token CSV. Each
immutable snapshot assembled twice: four COMPLETE / exit 0 results, unchanged
snapshot and rerun output bytes, all commits and PR actions preserved exactly once
across rows and unassigned evidence. The real Calendar event retains provider IDs
and the future scheduled meeting states "Theo lịch, chưa xác nhận tham dự". No
scheduled time is claimed worked. Token usage is unknown; no audit CSV was created.

Measured payloads are 4482/5243 bytes, with heuristic estimates 1121/1311 tokens.
These estimates exceed the aspirational 1000-input target; that target is not
reported achieved and is not a measured full-run total. They are below the 12000-byte
guard. No actual savings are claimed.

An explicit missing Calendar-token-path probe (not a network API failure) queried
real GitHub evidence and returned INCOMPLETE / exit 2: Git 16 and PR 11 preserved in
draft, Calendar unavailable, all prior final/snapshot/export bytes unchanged. It
used no sample data. Existing OAuth credentials/token and old timesheet/token CSV
remain unchanged. Nine of the ten baseline files are unchanged at original paths;
the corrected improvement log's original bytes match its archived copy.

## Acceptance still open

F25 code correction is regression-tested, but actual Claude transcript/schema
acceptance remains pending. V01 is incomplete: Claude CLI discovery/invocation and
actual marked-run usage, plus real all-day/overnight/paginated Calendar cases, were
not exercised. Synthetic tests cover these branches without claiming live proof.
D02 stays deferred. New PRs are drafts for audit and are not merged or auto-closed.
