# Remaining group A — source collection and evidence

Implemented F14/F16/F18/F19/F20/F21/F38/F39, Calendar/repository configuration
portion of F27, and user-approved D01/D03 policies. GitHub only; GitLab/ICS switches
removed. Optional Google dependency file and owner-only read-only OAuth bootstrap
provided; existing OAuth never reauthorized by default.

Calendar follows all page tokens, fails a repeated/malformed token or failed page,
keeps event/calendar/source IDs and self response status, excludes cancelled and
self-declined. All-day is context; overlaps remain attendance review. Same-looking
Google event IDs remain distinct. Qualified repo/PR suffixes and AI references avoid
multi-repository number collisions; local no-origin identity uses canonical path.
All Markdown table text is escaped.

CLI > exported environment > profile > defaults for Calendar paths and repo
selection; profile paths resolve relative to profile. `.env` is not loaded implicitly.
Local all-ref and remote default-branch histories are bounded (default 10000 each),
then filtered by author date. Remote collection avoids the committer-date since
filter. Bound overflow is an error, never complete truncated collection. Branch URLs
are rejected and history limits have explicit CLI overrides.

D01/D03 were approved by the user on 2026-10-07: retain full-day proposals, with
scheduled attendance unconfirmed and an explicit Markdown notice; default primary,
exclude cancelled/self-declined, all-day context only and overlaps require review.
Estimated/scheduled durations never assert measured work or actual attendance.

357/357 tests pass, including 18 new source regressions: pagination failures,
multiple calendars, event IDs, qualified PRs, Markdown, precedence, actual temporary
Git repos, bounds/backdated authors and OAuth preservation. Four isolated real
runs (two dates repeated) used successful live sources: Oct6 Git21/PR7/Calendar0;
Oct7 Git16/PR11/Calendar1. Exact reruns, ten old files and both OAuth files unchanged;
real Calendar event/calendar IDs and attendance unconfirmed survive into saved rows.
The remote-history bound was finalized after these four source runs; the final
combined live verification also exercises that collector version. Bootstrap consent,
large real histories and real paginated Calendar are not claimed live-verified;
those edge paths have deterministic mocked/temporary-repo coverage.

Token path/env config is completed in the subsequent token group; do not close
F27 on this partial checkpoint. Final combined validation is recorded separately.
