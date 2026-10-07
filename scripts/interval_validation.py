"""Validate clock presentation against exact aware bounds, including DST durations."""
import datetime
from activity_settings import parse_timestamp
from block_identity import BlockIdentityError


def validate_interval(date, start, end, duration, interval=None):
    if not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0:
        raise BlockIdentityError("Duration must be a positive integer number of minutes")
    if interval is not None:
        if not isinstance(interval, dict):
            raise BlockIdentityError("Exact interval must be an object")
        try:
            s, e = parse_timestamp(interval["start"]), parse_timestamp(interval["end"])
            day = datetime.date.fromisoformat(date)
            expected_end = "24:00" if e.date() == day + datetime.timedelta(days=1) and e.time().replace(tzinfo=None) == datetime.time() else e.strftime("%H:%M")
            if (e.date() != day and expected_end != "24:00" or s.date() != day
                    or s.strftime("%H:%M") != start or expected_end != end):
                raise ValueError("Inconsistent clock presentation")
            expected = int((e.astimezone(datetime.timezone.utc) - s.astimezone(datetime.timezone.utc)).total_seconds() / 60)
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            raise BlockIdentityError("Invalid exact interval or inconsistent date/clock presentation") from exc
    else:
        def minutes(value):
            h, m = value.split(":")
            return int(h)*60 + int(m)
        expected = minutes(end) - minutes(start)
    if duration != expected or expected <= 0:
        raise BlockIdentityError("Duration is inconsistent with the block interval")
