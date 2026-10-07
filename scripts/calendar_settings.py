"""Calendar paths are explicit; secrets are read only by Google's credential library."""
import os
from pathlib import Path
from activity_settings import DEFAULT_CONFIG, load_config, string_list

ROOT = Path(__file__).resolve().parent.parent


def add_calendar_arguments(parser):
    parser.add_argument("--calendar-token", help="Authorized-user OAuth JSON path")
    parser.add_argument("--calendar-credentials", help="Desktop OAuth client JSON path (bootstrap only)")
    parser.add_argument("--calendar-ids", nargs="+", help="Calendar IDs (default primary)")


def calendar_settings(config_path=None, token=None, credentials=None, calendars=None):
    config = load_config(config_path).get("calendar", {})
    if not isinstance(config, dict):
        raise ValueError("calendar configuration must be an object")
    if config.get("provider", "google") not in ("google", "google_calendar"):
        raise ValueError("Only Google Calendar is supported; select fixtures explicitly with --calendar-fixture")
    profile_dir = Path(config_path).expanduser().resolve().parent if config_path else DEFAULT_CONFIG.parent

    def path(override, environment, field, legacy, default):
        value = override if override is not None else os.environ.get(environment)
        base = Path.cwd()
        if value is None:
            value = config.get(field, config.get(legacy))
            base = profile_dir
        if value is None:
            return str(ROOT / default)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"calendar.{field} must be a nonempty path")
        location = Path(value).expanduser()
        return str((base / location).resolve() if not location.is_absolute() else location)

    ids = calendars if calendars is not None else config.get("calendar_ids", [config.get("calendar_id", "primary")])
    ids = string_list(ids, "calendar.calendar_ids")
    if not ids:
        raise ValueError("At least one Calendar must be selected")
    return {"token_path": path(token, "GOOGLE_CALENDAR_TOKEN", "token_path", "google_token_path", "token.json"),
            "credentials_path": path(credentials, "GOOGLE_CALENDAR_CREDENTIALS", "credentials_path", "google_credentials_path", "credentials.json"),
            "calendar_ids": ids}
