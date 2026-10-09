#!/usr/bin/env python3
"""
get_calendar_activity.py - Deterministic collector and adapter for Google Calendar events.

Retrieves events for the requested day:
- title
- timed start/end (ISO 8601 with timezone), retaining original event extent
- all-day start/end dates (exclusive end), marked all_day and kept as context

Uses an existing authorized-user Google token or an explicitly selected fixture.
Outputs a source-status envelope; never substitutes fixtures for live results.
"""

import argparse
import datetime
import os
import sys
from typing import List, Dict, Any, Optional
from activity_settings import add_timezone_arguments, timezone_settings, resolve_timezone
from calendar_settings import add_calendar_arguments, calendar_settings

from collection_result import (
    SourceUnavailable, collection_result, emit_result, load_fixture_records,
)


def get_local_timezone() -> datetime.tzinfo:
    return timezone_settings()[1]


def parse_event_time(val: Any, default_tz: datetime.tzinfo) -> Optional[datetime.datetime]:
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
        timestamp = datetime.datetime.fromisoformat(date_str)
        if timestamp.tzinfo is None:
            source_tz = resolve_timezone(val["timeZone"]) if isinstance(val, dict) and val.get("timeZone") else default_tz
            # A local wall time during a DST gap/fold cannot safely imply an instant.
            candidates = [timestamp.replace(tzinfo=source_tz, fold=fold) for fold in (0, 1)]
            valid = [candidate for candidate in candidates
                     if candidate.astimezone(datetime.timezone.utc).astimezone(source_tz).replace(tzinfo=None) == timestamp]
            if not valid or len({candidate.utcoffset() for candidate in valid}) > 1:
                raise ValueError("Calendar wall time requires an explicit offset at a DST transition")
            timestamp = valid[0]
        return timestamp.astimezone(default_tz)
    except Exception:
        return None


def fetch_google_calendar_events(
    target_date: datetime.date,
    credentials_path: str = "credentials.json",
    token_path: str = "token.json",
    tz=None, calendar_ids=None
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

        parameters = dict(
            timeMin=start_of_day,
            timeMax=end_of_day,
            **({"timeZone": tz.key} if hasattr(tz, "key") else {}),
            singleEvents=True,
            orderBy="startTime"
        )
        events = []
        for calendar_id in calendar_ids or ["primary"]:
            page_token, seen = None, set()
            while True:
                response = service.events().list(calendarId=calendar_id, **parameters,
                    **({"pageToken": page_token} if page_token else {})).execute()
                if not isinstance(response, dict):
                    raise ValueError("Invalid Calendar response")
                items = response.get("items", [])
                if not isinstance(items, list) or any(not isinstance(it, dict) for it in items):
                    raise ValueError("Invalid Calendar events response")
                for it in items:
                    event = normalize_calendar_event(it, target_date, tz)
                    if event is not None:
                        event.update({"calendar_id": calendar_id, "source": "google_calendar"})
                        events.append(event)
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
                if not isinstance(page_token, str) or page_token in seen:
                    raise ValueError("Invalid/repeated Calendar page token; collection cannot be complete")
                seen.add(page_token)
        return events
    except ImportError as exc:
        raise SourceUnavailable("Install google-auth and google-api-python-client for live Calendar") from exc


def normalize_calendar_event(item, target_date, tz):
    """Keep all-day dates distinct; select both adapters by half-open day overlap."""
    def is_date(value):
        return (isinstance(value, dict) and "date" in value and "dateTime" not in value
                or isinstance(value, str) and len(value) == 10)

    if item.get("status") == "cancelled":
        return None
    attendees = item.get("attendees", [])
    if not isinstance(attendees, list) or any(not isinstance(person, dict) for person in attendees):
        raise ValueError("Invalid Calendar attendee metadata")
    if any(person.get("self") is True and person.get("responseStatus") == "declined" for person in attendees):
        return None
    start, end = item.get("start"), item.get("end")
    all_day = is_date(start)
    if is_date(end) != all_day or item.get("all_day", all_day) != all_day:
        raise ValueError("Calendar dates/times and all_day flag must agree")
    s, e = parse_event_time(start, tz), parse_event_time(end, tz)
    if not s or not e or e.astimezone(datetime.timezone.utc) <= s.astimezone(datetime.timezone.utc):
        raise ValueError("Calendar requires valid start and end after start")
    title = item.get("summary", item.get("title", "Untitled event"))
    if all_day:
        if not s.date() <= target_date < e.date():
            return None
        record = {"title": title, "start": s.date().isoformat(), "end": e.date().isoformat(), "all_day": True}
        return calendar_evidence(item, record)
    day_start = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=tz)
    day_end = datetime.datetime.combine(target_date + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
    if s >= day_end or e <= day_start:
        return None
    # Original event extent is retained; daily clipping happens in block construction.
    return calendar_evidence(item, {"title": title, "start": s.isoformat(), "end": e.isoformat()})


def calendar_evidence(item, record):
    for original, field in (("id", "event_id"), ("event_id", "event_id"), ("calendar_id", "calendar_id"),
                            ("source", "source"), ("status", "status"), ("recurringEventId", "recurring_event_id")):
        if item.get(original) is not None:
            if not isinstance(item[original], str):
                raise ValueError("Calendar evidence identity must be a string")
            record[field] = item[original]
    for person in item.get("attendees", []):
        if person.get("self") is True and isinstance(person.get("responseStatus"), str):
            record["self_response_status"] = person["responseStatus"]
    return record


def load_calendar_fixture(fixture_path: str, target_date: datetime.date, tz=None) -> List[Dict[str, Any]]:
    """Load and normalize events from a JSON fixture file."""
    tz = tz or get_local_timezone()
    data = load_fixture_records(fixture_path)
    events = []
    for item in data:
        event = normalize_calendar_event(item, target_date, tz)
        if event is not None:
            events.append(event)
    events.sort(key=lambda e: e["start"])
    return events


def collect_calendar_activity(target_date, fixture_path=None, tz=None, calendar_options=None):
    mode = "fixture" if fixture_path is not None else "live"
    try:
        events = (load_calendar_fixture(fixture_path, target_date, tz) if fixture_path is not None
                  else fetch_google_calendar_events(target_date, tz=tz, **(calendar_options or {})))
        return collection_result("google_calendar", mode, "success", events)
    except SourceUnavailable as exc:
        return collection_result("google_calendar", mode, "unavailable", reason=str(exc))
    except Exception as exc:
        return collection_result("google_calendar", mode, "error", reason=
                                 f"Calendar collection failed ({type(exc).__name__})")


def main():
    parser = argparse.ArgumentParser(description="Collect Google Calendar events for a specific date.")
    add_timezone_arguments(parser)
    add_calendar_arguments(parser)
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
        _, tz = timezone_settings(args.config, args.timezone)
        options = calendar_settings(args.config, args.calendar_token, args.calendar_credentials, args.calendar_ids)
    except (KeyError, ValueError, OSError) as exc:
        parser.error(str(exc))
    if args.date:
        try:
            target_date = datetime.date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: Invalid date format '{args.date}'. Expected YYYY-MM-DD.", file=sys.stderr)
            sys.exit(1)
    else:
        target_date = datetime.datetime.now(tz).date()

    return emit_result(collect_calendar_activity(target_date, args.fixture, tz, options), args.output)


if __name__ == "__main__":
    sys.exit(main())
