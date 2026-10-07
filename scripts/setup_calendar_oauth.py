#!/usr/bin/env python3
"""One-time desktop OAuth bootstrap; requests Calendar read-only access only."""
import argparse
import os
import tempfile
from pathlib import Path
from activity_settings import add_timezone_arguments
from calendar_settings import add_calendar_arguments, calendar_settings

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_timezone_arguments(parser)
    add_calendar_arguments(parser)
    parser.add_argument("--replace", action="store_true", help="Explicitly reauthorize an existing token")
    args = parser.parse_args()
    try:
        options = calendar_settings(args.config, args.calendar_token, args.calendar_credentials, args.calendar_ids)
        destination = Path(options["token_path"])
        if destination.exists() and not args.replace:
            print("OAuth token already exists; no credentials were changed.")
            return 0
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(options["credentials_path"], [SCOPE])
        credentials = flow.run_local_server(port=0, authorization_prompt_message="",
            success_message="Read-only Calendar authorization completed. You can close this tab.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".calendar-token-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(credentials.to_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, destination)
        finally:
            Path(name).unlink(missing_ok=True)
        print("Read-only Calendar OAuth token saved with owner-only file permissions.")
        return 0
    except Exception as exc:
        # Provider exceptions can contain client/token details; expose only the category.
        print(f"OAuth setup failed ({type(exc).__name__}); check client path, desktop app setup and Google dependencies.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
