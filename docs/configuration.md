# Configuration

Profile, credentials and path resolution for live collection. Start from
`config/example-config.json` and keep the copy (`config/user-config.json`) local.

## Identity and GitHub authentication

Set confirmed names/emails, GitHub logins, repositories and IANA timezone in the
ignored profile. Never commit OAuth files, tokens or personal config.
GitHub authentication precedence is GH_TOKEN/GITHUB_TOKEN, authenticated `gh`, then
an existing Git credential helper only when opted in with --use-git-credentials or
profile github.use_git_credentials. REST calls fetch commits, PRs and submitted
reviews; local commits use `git log --all`. A missing source is never replaced by
samples. `gh api` is used when gh authentication is available; direct HTTPS is an
alternative with an environment/helper token.

## Google Calendar

For Calendar, enable Google Calendar API and create a Desktop OAuth client. Put
credentials.json in the repository root or configure its path. Authorize readonly:

```bash
python3 scripts/setup_calendar_oauth.py --config config/user-config.json
python3 scripts/get_calendar_activity.py --config config/user-config.json --date 2026-10-07
```

The bootstrap refuses to replace an existing token unless --replace is explicit.
Collector calls use the authorized token and refresh it when needed. Every live
pipeline preparation queries current events; it does not subscribe or run daily by
itself. Primary is the default. Calendar pagination is exhausted and later-page
errors fail the source instead of reporting truncated success. Desktop OAuth
instructions follow the [Google quickstart](https://developers.google.com/workspace/calendar/api/quickstart/python).

## Precedence and paths

CLI overrides exported environment overrides profile values overrides defaults for
repository selection and Calendar/token paths. Identity/timezone use CLI > profile > default. Export individual variables; .env is not automatically loaded.

| Setting | CLI | Environment | Profile / default |
| --- | --- | --- | --- |
| Repositories | --repos | TIMESHEET_REPOS (comma separated) | repositories / current local repo |
| Calendar token | --calendar-token | GOOGLE_CALENDAR_TOKEN | calendar.token_path / bundle token.json |
| OAuth client | --calendar-credentials | GOOGLE_CALENDAR_CREDENTIALS | calendar.credentials_path / bundle credentials.json |
| Calendars | --calendar-ids | — | calendar.calendar_ids / primary |
| Claude transcripts | --claude-dir | CLAUDE_DIR | token_tracking.claude_dir / ~/.claude |
| Usage output | pipeline --token-csv-path, collector --csv-path | TIMESHEET_TOKEN_CSV | token_tracking.csv_path / bundle data/token-usage.csv |
| Zone | --timezone | — | timezone / Asia/Ho_Chi_Minh |

Profile-relative paths use the profile's parent directory; CLI/env paths use the
invoking directory. Bundle defaults are rooted beside scripts. Use quoted absolute
output/profile/repository paths when invoked from another project. Invalid explicit
