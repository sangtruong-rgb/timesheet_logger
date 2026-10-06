"""Shared identity, repository selection, and half-open local-day boundaries."""

import datetime
import json
import re
import subprocess
from pathlib import Path
from zoneinfo import ZoneInfo

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config/user-config.json"
DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"


def resolve_timezone(value, *, allow_legacy_offset=False):
    """New configuration uses named zones; old normalized models may keep fixed offsets."""
    if not isinstance(value, str) or not value:
        raise ValueError("timezone must be a nonempty IANA timezone name")
    if allow_legacy_offset and re.fullmatch(r"[+-][0-9]{2}:[0-9]{2}", value):
        hours, minutes = int(value[1:3]), int(value[4:6])
        if hours > 23 or minutes > 59:
            raise ValueError("Invalid legacy timezone offset")
        delta = datetime.timedelta(hours=hours, minutes=minutes)
        return datetime.timezone(delta if value[0] == "+" else -delta)
    try:
        return ZoneInfo(value)
    except (KeyError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone name") from exc


def timezone_settings(config_path=None, override=None):
    """CLI override > profile > named project default, never host timezone."""
    config = load_config(config_path)
    name = override if override is not None else config.get("timezone", DEFAULT_TIMEZONE)
    return name, resolve_timezone(name)


def add_timezone_arguments(parser):
    parser.add_argument("--config", help="JSON profile (default: config/user-config.json if present)")
    parser.add_argument("--timezone", help="IANA timezone (CLI override > profile > Asia/Ho_Chi_Minh)")


def string_list(value, field):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x.strip() for x in value):
        raise ValueError(f"{field} must be a list of nonempty strings")
    return list(dict.fromkeys(x.strip() for x in value))


def load_config(path=None):
    location = Path(path) if path else DEFAULT_CONFIG
    if not location.exists() and path is None:
        return {}
    config = json.loads(location.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")
    return config


def settings(config, repos=None, users=None, names=None, emails=None, timezone=None, use_git_credentials=None):
    author = config.get("author", {})
    github = config.get("github", {})
    if not isinstance(author, dict) or not isinstance(github, dict):
        raise ValueError("author and github configuration must be objects")
    tz_name = timezone if timezone is not None else config.get("timezone", DEFAULT_TIMEZONE)
    tz = resolve_timezone(tz_name)
    identity = {
        "github_users": string_list(users if users is not None else github.get("users", []), "github.users"),
        "names": string_list(names if names is not None else author.get("names", [author["name"]] if author.get("name") else []), "author.names"),
        "emails": string_list(emails if emails is not None else author.get("emails", [author["email"]] if author.get("email") else []), "author.emails"),
    }
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", user) for user in identity["github_users"]):
        raise ValueError("github.users must contain explicit GitHub logins, not @me")
    if any(x in ("*", "all") for group in identity.values() for x in group):
        raise ValueError("Personal identity cannot contain wildcard aliases")
    selected = repos if repos is not None else config.get("repositories", github.get("repositories", ["."]))
    selected = string_list(selected, "repositories")
    if not selected:
        raise ValueError("Select at least one repository")
    use_git = github.get("use_git_credentials", False) if use_git_credentials is None else use_git_credentials
    if not isinstance(use_git, bool):
        raise ValueError("github.use_git_credentials must be a boolean")
    return {"identity": identity, "repos": selected, "timezone": tz,
            "timezone_name": tz_name, "use_git_credentials": use_git}


def add_settings_arguments(parser):
    add_timezone_arguments(parser)
    parser.add_argument("--github-users", nargs="+", help="GitHub logins belonging to one person")
    parser.add_argument("--authors", nargs="+", help="Exact confirmed Git author name aliases")
    parser.add_argument("--author-emails", nargs="+", help="Exact confirmed Git author emails")
    parser.add_argument("--use-git-credentials", action="store_true", default=None,
                        help="Opt in to the existing Git credential helper for github.com")


def settings_from_args(args):
    return settings(load_config(args.config), args.repos, args.github_users,
                    args.authors, args.author_emails, args.timezone, args.use_git_credentials)


def parse_timestamp(value):
    if not isinstance(value, str):
        raise ValueError("An aware timestamp is required")
    result = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return result


def day_bounds(date, timezone):
    start = datetime.datetime.combine(date, datetime.time.min, tzinfo=timezone)
    end = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time.min, tzinfo=timezone)
    return start.astimezone(datetime.timezone.utc), end.astimezone(datetime.timezone.utc)


def identity_match(commit, identity):
    """A known foreign GitHub login must not match a same-name fallback alias."""
    folded = {key: {x.casefold() for x in identity.get(key, [])} for key in ("github_users", "names", "emails")}
    login = commit.get("github_author")
    if login and folded["github_users"]:
        return "github_login" if login.casefold() in folded["github_users"] else None
    if commit.get("email", "").casefold() in folded["emails"]:
        return "email"
    if commit.get("author", "").casefold() in folded["names"]:
        return "name"
    return None


def github_repo(target):
    from get_git_activity import parse_github_repo_slug
    slug = parse_github_repo_slug(target)
    if slug:
        return "/".join(slug)
    result = subprocess.run(["git", "-C", str(Path(target).expanduser()), "remote", "get-url", "origin"],
                            capture_output=True, text=True, check=False)
    slug = parse_github_repo_slug(result.stdout.strip()) if result.returncode == 0 else None
    if not slug:
        raise ValueError(f"Cannot resolve a GitHub origin for repository: {target}")
    return "/".join(slug)
