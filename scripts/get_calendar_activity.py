#!/usr/bin/env python3
"""
get_calendar_activity.py - Deterministic collector and adapter for Google Calendar events.

Retrieves events for the requested day:
- title
- start (ISO 8601 with timezone)
- end (ISO 8601 with timezone)

Uses an existing authorized-user Google token or an explicitly selected fixture.
Outputs a source-status envelope; never substitutes fixtures for live results.
"""

import argparse
import datetime
import json
import os
import sys
from typing import List, Dict, Any, Optional
from zoneinfo import ZoneInfo

from collection_result import (
    SourceUnavailable, collection_result, emit_result, load_fixture_records,
)


def get_local_timezone() -> datetime.timezone:
    return datetime.datetime.now().astimezone().tzinfo or datetime.timezone.utc


def parse_event_time(val: Any, default_tz: datetime.timezone) -> Optional[datetime.datetime]:
    """Parse Google API or raw string timestamp into timezone-aware datetime."""
    if isinstance(val, dict):
        date_str = val.get("dateTime") or val.get("date")
    else:
        date_str = str(val)

    if not date_str:
        return None

    try:
        if len(date_str) == 10:  # All-day event "YYYY-MM-DD"
            d = datetime.date.fromisoformat(date_str)
            return datetime.datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=default_tz)
        return datetime.datetime.fromisoformat(date_str).astimezone(default_tz)
    except Exception:
        return None


def fetch_google_calendar_events(
    target_date: datetime.date,
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
    tz=None
) -> List[Dict[str, Any]]:
    """
    Attempt to fetch events via Google Calendar API if client libraries and credentials exist.
    Raises SourceUnavailable for missing setup; request failures remain errors.
    """
    if not os.path.exists(token_path):
        raise SourceUnavailable("Authorized token.json is missing; Calendar OAuth setup is required")

    try:
        # Check if google api client is installed
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(token_path, ["https://www.googleapis.com/auth/calendar.readonly"])
        service = build("calendar", "v3", credentials=creds)

        tz = tz or get_local_timezone()
        start_of_day = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=tz).isoformat()
        end_of_day = datetime.datetime.combine(target_date + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz).isoformat()

        events_result = service.events().list(
            calendarId="primary",
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        items = events_result.get("items", [])
        if not isinstance(items, list) or any(not isinstance(it, dict) for it in items):
            raise ValueError("Invalid Calendar events response")
        events = []
        for it in items:
            start_dt = parse_event_time(it.get("start"), tz)
            end_dt = parse_event_time(it.get("end"), tz)
            if not start_dt or not end_dt:
                raise ValueError("Invalid Calendar event times")
            events.append({
                "title": it.get("summary", "Untitled event"),
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat()
            })
        return events
    except ImportError as exc:
        raise SourceUnavailable("Install google-auth and google-api-python-client for live Calendar") from exc


def load_calendar_fixture(fixture_path: str, target_date: datetime.date, tz=None) -> List[Dict[str, Any]]:
    """Load and normalize events from a JSON fixture file."""
    tz = tz or get_local_timezone()
    data = load_fixture_records(fixture_path)
    events = []
    for item in data:
        start_dt = parse_event_time(item.get("start"), tz)
        end_dt = parse_event_time(item.get("end"), tz)
        if not start_dt or not end_dt:
            raise ValueError("Calendar fixture records require valid start and end")
        if start_dt.date() == target_date:
            events.append({
                "title": item.get("title", "Untitled event"),
                "start": start_dt.isoformat(),
                "end": end_dt.isoformat()
            })
    events.sort(key=lambda e: e["start"])
    return events


def collect_calendar_activity(target_date, fixture_path=None, tz=None):
    mode = "fixture" if fixture_path is not None else "live"
    try:
        events = (load_calendar_fixture(fixture_path, target_date, tz) if fixture_path is not None
                  else fetch_google_calendar_events(target_date, tz=tz))
        return collection_result("google_calendar", mode, "success", events)
    except SourceUnavailable as exc:
        return collection_result("google_calendar", mode, "unavailable", reason=str(exc))
    except Exception as exc:
        return collection_result("google_calendar", mode, "error", reason=
                                 f"Calendar collection failed ({type(exc).__name__})")


def main():
    parser = argparse.ArgumentParser(description="Collect Google Calendar events for a specific date.")
    parser.add_argument("--timezone", help="IANA timezone shared with Git and PR collection")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date YYYY-MM-DD (default: today)"
    )
    parser.add_argument(
        "--fixture",
        type=str,
        default=None,
        help="Path to fixture JSON file"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file path (JSON). If omitted, prints to stdout."
    )

    args = parser.parse_args()

    try:
        tz = ZoneInfo(args.timezone) if args.timezone else get_local_timezone()
    except (KeyError, ValueError) as exc:
        parser.error(str(exc))
    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        target_date = datetime.datetime.now(tz).date()

    return emit_result(collect_calendar_activity(target_date, args.fixture, tz), args.output)


if __name__ == "__main__":
    sys.exit(main())
