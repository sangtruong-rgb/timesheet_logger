"""Parse shorthand daily windows before source collection, without AI date math."""
import re

from work_schedule import ranges


def _hhmm(minutes):
    return f'{minutes // 60:02d}:{minutes % 60:02d}'


def _clock_candidates(text, *, end=False):
    match = re.fullmatch(r'([0-9]{1,2})(?:[:h]([0-9]{2}))?\s*(am|pm)?', text.strip(), re.I)
    if not match:
        raise ValueError('Work window clocks require H:MM, HH:MM or HhMM; optional AM/PM')
    hour_text, minute_text, meridiem = match.groups()
    hour, minute = int(hour_text), int(minute_text or 0)
    if minute > 59 or hour > 24 or hour == 24 and (minute or not end or meridiem):
        raise ValueError('Invalid work window clock; only an end may be 24:00')
    if meridiem:
        if not 1 <= hour <= 12:
            raise ValueError('AM/PM hours must be between 1 and 12')
        hour = hour % 12 + (12 if meridiem.lower() == 'pm' else 0)
        return [hour * 60 + minute]
    candidates = [hour * 60 + minute]
    # Unpadded 1..11 can be afternoon when needed to follow the prior boundary.
    # Two-digit HH:MM is always an explicit 24-hour clock, never reinterpreted.
    if ((len(hour_text) == 1 and 1 <= hour <= 9)
            or ('h' in text.lower() and not hour_text.startswith('0') and 1 <= hour <= 11)):
        candidates.append((hour + 12) * 60 + minute)
    return candidates


def parse_work_windows(text):
    """Resolve windows in supplied chronological order; never wrap to tomorrow."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError('--work-windows requires at least one interval')
    result, previous_end = [], 0
    for part in text.split(','):
        pair = re.split(r'\s*[-–—]\s*', part.strip())
        if len(pair) != 2:
            raise ValueError('Use comma-separated work windows, e.g. 8:00-12:00, 1h30-4:00')
        starts = _clock_candidates(pair[0])
        ends = _clock_candidates(pair[1], end=True)
        # Equal shorthand clocks are not an implicit twelve-hour shift.
        if starts == ends:
            raise ValueError('Work window end must follow start')
        choices = [(left, right) for left in starts for right in ends
                   if previous_end <= left < right <= 1440]
        if not choices:
            raise ValueError('Work windows must be chronological, non-overlapping and within one day; use HH:MM or AM/PM to clarify')
        left, right = min(choices)
        result.append({'start': _hhmm(left), 'end': _hhmm(right)})
        previous_end = right
    return validate_work_windows(result)


def default_work_day_windows(start):
    """User-approved shorthand: morning until noon, then five afternoon hours."""
    if not isinstance(start, str):
        raise ValueError('--work-day-start requires a morning clock before 12:00')
    candidates = [value for value in _clock_candidates(start) if value < 12 * 60]
    if not candidates:
        raise ValueError('--work-day-start must be before 12:00; use --work-windows for other hours')
    return validate_work_windows([
        {'start': _hhmm(min(candidates)), 'end': '12:00'},
        {'start': '13:30', 'end': '18:30'},
    ])


def validate_work_windows(windows):
    checked = ranges(windows, 'confirmed_windows')
    if not checked or checked != windows:
        raise ValueError('Confirmed work windows must be nonempty and in chronological order')
    return checked
