# GitHub collection batch — validation for review

Branch: `fix/github-personal-activity`, based on `fix/f01-explicit-collection-sources`.
This batch depends on F01 / draft PR #48. It does not merge either change into `main`.

## Behavior and review status

| Approved item | Before | After | Status |
|---|---|---|---|
| PR query and authentication | Search qualifiers were combined into a quoted author value; gh was missing | Read-only REST lists, review endpoints, and merge details; authenticated gh, environment token, or opt-in existing Git helper | Implemented; pending review |
| Personal identities — F15 / #16 | One current Git name, substring filtering; user's default returned 0 commits | Multiple explicit GitHub logins, exact confirmed name/email aliases, identity-match provenance; no implicit all-author mode | Implemented; pending review |
| Shared scope — F13 / #14 | Git-only `--repos`, account-wide PR search via `@me` | Same repo/profile/CLI selection reaches Git and PR; all confirmed accounts are included | Implemented; pending review |
| PR event times — F11 / #12 | `updatedAt` used as all action times; historical reviews qualified as today's | Actual creation, submitted review, and merge timestamps; distinct events retained through normalization and per-block references | Implemented; pending review |
| Local-day boundaries — F12 / #13 | Bare PR dates, differing collector rules | IANA timezone; half-open local midnight boundaries; final timestamp filtering | Implemented; pending review |

Related improvements preserve PR action history (F17), qualify remote repository identifiers
and per-repo commit associations (part of F16), paginate Git/PR results (part of F18),
and include remote Git/API errors in the pipeline source gate (part of F37).
These do not resolve the remaining portions of F16/F18/F37 or the broader configuration F09.

## Automated validation

`python3 -m unittest discover tests`: **75 tests passed**, including **31 new regressions**.
Existing author-filter assertions were updated to require exact matching rather than
the old substring behavior. Existing F01 source/output protection tests still pass.
`git diff --check` passes.

Coverage includes both personal accounts; confirmed unlinked author aliases; a foreign
linked account with the same author name; substring near matches; actual local Git history;
missing identity; actual action times despite later PR updates; old/pending reviews;
multiple reviews; opening/review/merge on one reference; per-action block association;
relevant merges; timezone midnight boundaries and DST; multi-page API responses;
invalid response shape; partial source failure; explicit credential-helper opt-in;
and subprocess profile propagation from another working directory, including UTC host timezone.

## Live results — 2026-10-06, Vietnam timezone

Repository: `sangtruong-rgb/timesheet_logger`. This snapshot was collected before opening
the review PR for this batch. A later run can include that new PR as additional real activity.

- **Git: success, 15 commits on default branch `main`.** Fourteen match the `Sang Truong`
  alias explicitly confirmed by the user; one links to the confirmed GitHub account
  `sangtruong-rgb`. No all-author override was used.
- **PR: success, 2 references, 3 events.** Both user-confirmed accounts are included.

| Local time (+07:00) | PR | Action | Actor |
|---|---|---|---|
| 14:24:31 | #1 | opened | sangtruong-rgb |
| 14:44:42 | #1 | merged | sangtruong-rgb |
| 16:11:23 | #48 | opened | XuanSang2005 |

- **Empty live day 2026-10-05:** Git and PR both return `success`, zero items, exit 0;
  no fixture substitution.
- **Pipeline:** Git 15 / PR 2 collected successfully; Google Calendar unavailable because
  its authorized token is absent. Run correctly returns **INCOMPLETE / exit 2**, with
  normalized evidence in a separate draft. No AI input or final timesheet is written.
- SHA-256 fingerprints of five existing raw/timesheet/token files remain unchanged.

## Local setup and reproducibility

The ignored local `config/user-config.json` contains the user-confirmed accounts
`XuanSang2005` and `sangtruong-rgb`, confirmed names `Sang Truong` and `Xuan Sang`, the
selected repo, `Asia/Ho_Chi_Minh`, and `github.use_git_credentials: true`. It contains no token.
The tracked `config/example-github-config.json` documents this profile structure.

Official GitHub CLI 2.102.0 is installed through Homebrew. The existing Git credential can
read the repository but lacks `read:org`, which `gh auth login` requires. The live collector
therefore uses explicit reuse of the existing Git credential helper. Credentials remain in
memory; no token is copied to a project file. A conventional gh login or environment token
also works through the same REST adapter.

```bash
python3 scripts/get_git_activity.py --date 2026-10-06 --envelope --output data/audit/github-fix/commits.json
python3 scripts/get_pr_activity.py --date 2026-10-06 --output data/audit/github-fix/prs.json
python3 scripts/run_pipeline.py --date 2026-10-06 --output-dir data/audit/github-fix/pipeline
```

Audit artifacts on this machine (ignored by Git):

- `data/audit/github-fix/2026-10-06-activity.md`: human-readable commit/PR evidence.
- `data/audit/github-fix/commits.json`, `prs.json`: live collector envelopes.
- `data/audit/github-fix/pipeline/drafts/2026-10-06.json`: normalized pipeline draft.
- `data/audit/github-fix/validation.json`: counts, events, protected-file fingerprints,
  empty-live-day results, and verification limitations.

## Remaining limits

Google Calendar and a complete live timesheet are not verified. The repo has no real
submitted review to exercise; review logic is covered by regression tests rather than a
manufactured live review. Remote commits still follow the default branch/API chronology
(F39). Local invalid paths/Git failures still need F37. Name aliases are user-confirmed
fallbacks, not proof from GitHub's account mapping. General time-block estimation, overlap,
legacy timestamp inputs, AI assembly, and changed-block reruns remain their existing audit
items. This report confirms GitHub collection, not completed daily timesheet correctness.

Implementation references: [GitHub PR API](https://docs.github.com/en/rest/pulls/pulls),
[review API](https://docs.github.com/en/rest/pulls/reviews),
[commit API](https://docs.github.com/en/rest/commits/commits),
[gh api](https://cli.github.com/manual/gh_api).
