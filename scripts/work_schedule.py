"""Validated daily work windows; frozen models never consult host configuration."""
import copy
import datetime
import re

from activity_settings import load_config

DEFAULT_SCHEDULE = {
    'start': '09:00', 'end': '17:30',
    'breaks': [{'start': '12:00', 'end': '13:30'}],
    # Preserve the existing all-days behavior; a profile can restrict weekdays.
    'weekdays': list(range(7)), 'holidays': [], 'overtime_windows': [],
}
CLOCK = re.compile(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]')


def clock(value, *, end=False):
    if not isinstance(value, str) or not (CLOCK.fullmatch(value) or end and value == '24:00'):
        raise ValueError('work_schedule clocks must be HH:MM; only ends may be 24:00')
    return value


def ranges(values, label):
    if not isinstance(values, list):
        raise ValueError(f'work_schedule.{label} must be an array')
    result = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {'start', 'end'}:
            raise ValueError(f'work_schedule.{label} requires start/end objects')
        left, right = clock(value['start']), clock(value['end'], end=True)
        if left >= right:
            raise ValueError(f'work_schedule.{label} end must follow start on the same day')
        result.append({'start': left, 'end': right})
    result.sort(key=lambda value: (value['start'], value['end']))
    if any(left['end'] > right['start'] for left, right in zip(result, result[1:])):
        raise ValueError(f'work_schedule.{label} intervals cannot overlap')
    return result


def validate_schedule(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULT_SCHEDULE):
        raise ValueError('work_schedule must be an object with supported fields')
    schedule = {**copy.deepcopy(DEFAULT_SCHEDULE), **copy.deepcopy(value)}
    regular = ranges([{'start': schedule['start'], 'end': schedule['end']}], 'hours')[0]
    schedule.update(regular)
    schedule['breaks'] = ranges(schedule['breaks'], 'breaks')
    overtime = ranges(schedule['overtime_windows'], 'overtime_windows')
    if any(item['start'] < regular['end'] and item['end'] > regular['start'] for item in overtime):
        raise ValueError('work_schedule.overtime_windows cannot overlap regular hours')
    schedule['overtime_windows'] = overtime
    weekdays = schedule['weekdays']
    if (not isinstance(weekdays, list) or any(type(day) is not int or not 0 <= day <= 6 for day in weekdays)
            or len(set(weekdays)) != len(weekdays)):
        raise ValueError('work_schedule.weekdays requires unique integers 0 (Monday) to 6 (Sunday)')
    schedule['weekdays'] = sorted(weekdays)
    holidays = schedule['holidays']
    if not isinstance(holidays, list):
        raise ValueError('work_schedule.holidays must be an array of YYYY-MM-DD dates')
    for day in holidays:
        if not isinstance(day, str) or datetime.date.fromisoformat(day).isoformat() != day:
            raise ValueError('work_schedule.holidays requires canonical YYYY-MM-DD dates')
    if len(set(holidays)) != len(holidays):
        raise ValueError('work_schedule.holidays cannot contain duplicate dates')
    schedule['holidays'] = sorted(holidays)
    return schedule


def schedule_settings(config_path=None):
    config = load_config(config_path)
    return validate_schedule(config.get('work_schedule', {}))


def local_clock(date, value, tz):
    if value == '24:00':
        return datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(), tzinfo=tz)
    result = datetime.datetime.combine(date, datetime.time.fromisoformat(value), tzinfo=tz)
    if result.astimezone(datetime.timezone.utc).astimezone(tz).replace(tzinfo=None) != result.replace(tzinfo=None):
        raise ValueError('work_schedule boundary is a nonexistent local time on the selected date')
    return result


def schedule_bounds(model, date, tz):
    schedule = validate_schedule(model.get('work_schedule', {}))
    breaks = [(local_clock(date, item['start'], tz), local_clock(date, item['end'], tz))
              for item in schedule['breaks']]
    windows = []
    if date.weekday() in schedule['weekdays'] and date.isoformat() not in schedule['holidays']:
        from commit_intervals import subtract_intervals
        for item in sorted([{'start': schedule['start'], 'end': schedule['end']},
                            *schedule['overtime_windows']], key=lambda item: item['start']):
            windows.extend(subtract_intervals(local_clock(date, item['start'], tz),
                                              local_clock(date, item['end'], tz), breaks))
    return schedule, windows, breaks
