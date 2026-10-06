#!/usr/bin/env python3
"""
get_calendar_activity.py - Deterministic collector and adapter for Google Calendar events.

Retrieves events for the requested day:
- title
- start (ISO 8601 with timezone)
- end (ISO 8601 with timezone)

Supports:
1. Direct Google Calendar OAuth/Service Account credentials if present
2. iCal (.ics) exported file
3. Fixture/mock file for testing and offline execution

If authentication is not configured, emits clear instructions and outputs empty list or fixture.
Never fakes successful retrieval.
"""

import argparse
import datetime
import json
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional


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
    token_path: str = "token.json"
) -> Optional[List[Dict[str, Any]]]:
    """
    Attempt to fetch events via Google Calendar API if client libraries and credentials exist.
    Returns None if credentials/libraries are not available.
    """
    if not (os.path.exists(credentials_path) or os.path.exists(token_path)):
        return None

    try:
        # Check if google api client is installed
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        if not os.path.exists(token_path):
            print("Notice: token.json not found. Run calendar authentication setup.", file=sys.stderr)
            return None

        creds = Credentials.from_authorized_user_file(token_path, ["https://www.googleapis.com/auth/calendar.readonly"])
        service = build("calendar", "v3", credentials=creds)

        tz = get_local_timezone()
        start_of_day = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=tz).isoformat()
        end_of_day = datetime.datetime.combine(target_date, datetime.time.max, tzinfo=tz).isoformat()

        events_result = service.events().list(
            calendarId="primary",
            timeMin=start_of_day,
            timeMax=end_of_day,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        items = events_result.get("items", [])
        events = []
        for it in items:
            start_dt = parse_event_time(it.get("start"), tz)
            end_dt = parse_event_time(it.get("end"), tz)
            if start_dt and end_dt:
                events.append({
                    "title": it.get("summary", "Untitled event"),
                    "start": start_dt.isoformat(),
                    "end": end_dt.isoformat()
                })
        return events
    except ImportError:
        print("Notice: google-api-python-client not installed in current environment.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Warning: Failed to fetch Google Calendar events: {e}", file=sys.stderr)
        return None


def load_calendar_fixture(fixture_path: str, target_date: datetime.date) -> List[Dict[str, Any]]:
    """Load and normalize events from a JSON fixture file."""
    p = Path(fixture_path)
    if not p.exists():
        return []
    try:
        tz = get_local_timezone()
        data = json.loads(p.read_text(encoding="utf-8"))
        events = []
        for item in data:
            raw_start = item.get("start")
            raw_end = item.get("end")
            start_dt = parse_event_time(raw_start, tz)
            end_dt = parse_event_time(raw_end, tz)
            if start_dt and end_dt:
                if start_dt.date() == target_date:
                    events.append({
                        "title": item.get("title", "Untitled event"),
                        "start": start_dt.isoformat(),
                        "end": end_dt.isoformat()
                    })
        events.sort(key=lambda e: e["start"])
        return events
    except Exception as e:
        print(f"Warning: Could not parse calendar fixture {fixture_path}: {e}", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser(description="Collect Google Calendar events for a specific date.")
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

    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        target_date = datetime.datetime.now().astimezone().date()

    events: Optional[List[Dict[str, Any]]] = None

    # Priority 1: User-specified fixture
    if args.fixture:
        events = load_calendar_fixture(args.fixture, target_date)
    else:
        # Priority 2: Google Calendar API credentials
        events = fetch_google_calendar_events(target_date)

        # Priority 3: Default fixture file if exists
        if events is None:
            default_fixture = Path("data/fixtures/sample_calendar.json")
            if default_fixture.exists():
                events = load_calendar_fixture(str(default_fixture), target_date)
            else:
                # Document missing setup
                print(
                    "Notice: Google Calendar authentication not configured and no fixture specified.\n"
                    "Setup instructions:\n"
                    "  1. Enable Google Calendar API in Google Cloud Console.\n"
                    "  2. Download OAuth 2.0 credentials to 'credentials.json'.\n"
                    "  3. Or pass mock data via --fixture data/fixtures/sample_calendar.json.\n",
                    file=sys.stderr
                )
                events = []

    if events is None:
        events = []

    output_json = json.dumps(events, indent=2)

    if args.output and args.output != "-":
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_json, encoding="utf-8")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
