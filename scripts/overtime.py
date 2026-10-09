"""Approved OT defaults: one hour ending at each outside-main commit, with overrides."""
import copy
import datetime

from activity_settings import resolve_timezone
from block_identity import BlockIdentityError
from work_schedule import local_clock, validate_schedule
from work_windows import validate_work_windows

LEGACY_OT_POLICY = {'default_minutes': 60, 'end_basis': 'commit_minute_floor',
                    'approval': 'standing_user_rule'}
DEFAULT_OT_POLICY = {**LEGACY_OT_POLICY, 'exclude_breaks': 'frozen_work_schedule'}
WORK_DAY_OT_POLICY = {**LEGACY_OT_POLICY, 'exclude_breaks': 'work_day_lunch'}
SUPPORTED_OT_POLICIES = (DEFAULT_OT_POLICY, WORK_DAY_OT_POLICY, LEGACY_OT_POLICY)


def bounds(model, windows):
    date = datetime.date.fromisoformat(model['date'])
    tz = resolve_timezone(model['timezone'], allow_legacy_offset=True)
    return [(local_clock(date, item['start'], tz), local_clock(date, item['end'], tz)) for item in windows]


def main_windows(model):
    confirmation = model.get('work_confirmation', {})
    if confirmation.get('date') != model['date'] or 'windows' not in confirmation:
        raise BlockIdentityError('OT review requires confirmed main --work-windows for this date')
    return validate_work_windows(confirmation['windows'])


def overtime_evidence(model):
    """Find outside activity without inferring the user's OT start or duration."""
    from build_time_blocks import parse_dt
    from commit_intervals import subtract_intervals
    main = bounds(model, main_windows(model))
    date = datetime.date.fromisoformat(model['date'])
    tz = main[0][0].tzinfo
    day_start = datetime.datetime.combine(date, datetime.time(), tzinfo=tz)
    day_end = datetime.datetime.combine(date + datetime.timedelta(days=1), datetime.time(), tzinfo=tz)
    observations = []

    def point(value, source, *, closing=False):
        instant = parse_dt(value)
        if instant is None or instant.tzinfo is None or not day_start <= instant < day_end:
            return
        instant = instant.astimezone(tz)
        if any(left <= instant <= right if closing else left <= instant < right for left, right in main):
            return
        observations.append({'source': source, 'timestamp': instant.isoformat()})

    for commit in model.get('commits', []):
        point(commit.get('timestamp'), 'git', closing=True)
    for pr in model.get('pull_requests', []):
        for action in pr.get('events') or [pr]:
            # A proven merge at a main closing boundary adds context, not OT.
            instant = parse_dt(action.get('timestamp'))
            status = action.get('action', action.get('status'))
            matched = False
            if (status == 'merged' and pr.get('merge_commit_sha') and instant is not None
                    and instant.tzinfo is not None and main[0][0] <= instant <= main[-1][1]):
                for commit in model.get('commits', []):
                    closing = parse_dt(commit.get('timestamp'))
                    if (closing is not None and closing.tzinfo is not None
                            and commit.get('hash') == pr['merge_commit_sha']
                            and commit.get('repository') == pr.get('repository')
                            and any(left < closing <= right for left, right in main)
                            and closing.astimezone(tz).replace(second=0, microsecond=0)
                            == instant.astimezone(tz).replace(second=0, microsecond=0)):
                        matched = True
                        break
            if matched:
                continue
            point(action.get('timestamp'), 'github')
    for event in model.get('calendar', []):
        if event.get('all_day') or len(event.get('start', '')) == 10:
            continue
        left, right = parse_dt(event.get('start')), parse_dt(event.get('end'))
        if left is None or right is None or left.tzinfo is None or right.tzinfo is None or left >= right:
            raise BlockIdentityError('OT Calendar evidence requires valid aware intervals')
        left, right = max(left.astimezone(tz), day_start), min(right.astimezone(tz), day_end)
        if left < right:
            for start, end in subtract_intervals(left, right, main):
                observations.append({'source': 'google_calendar', 'start': start.isoformat(), 'end': end.isoformat()})
    unique = {tuple(sorted(item.items())): item for item in observations}
    return sorted(unique.values(), key=lambda item: (item.get('timestamp', item.get('start')), item['source'], item.get('end', '')))


def default_overtime_windows(model, observations=None, *, policy=None):
    """Union prior commit hours outside NORMAL and breaks; replay old policies exactly."""
    from build_time_blocks import parse_dt
    from commit_intervals import subtract_intervals
    main = bounds(model, main_windows(model))
    policy = DEFAULT_OT_POLICY if policy is None else policy
    if policy not in SUPPORTED_OT_POLICIES:
        raise BlockIdentityError('Unsupported default OT policy')
    excluded = list(main)
    if policy == DEFAULT_OT_POLICY:
        excluded.extend(bounds(model, validate_schedule(model.get('work_schedule', {}))['breaks']))
    elif policy == WORK_DAY_OT_POLICY:
        excluded.extend(bounds(model, [{'start': '12:00', 'end': '13:30'}]))
    date, tz = datetime.date.fromisoformat(model['date']), main[0][0].tzinfo
    midnight = datetime.datetime.combine(date, datetime.time(), tzinfo=tz)
    pieces = []
    for item in overtime_evidence(model) if observations is None else observations:
        if item['source'] != 'git':
            continue
        end = parse_dt(item['timestamp']).astimezone(tz).replace(second=0, microsecond=0)
        start = max(midnight, (end.astimezone(datetime.timezone.utc)
                              - datetime.timedelta(minutes=60)).astimezone(tz))
        for left, right in subtract_intervals(start, end, excluded):
            # HH:MM cannot represent an ambiguous repeated clock differently
            # from local_clock's fold=0; reject rather than silently changing time.
            for boundary in (left, right):
                rebuilt = local_clock(date, boundary.strftime('%H:%M'), tz)
                if rebuilt.astimezone(datetime.timezone.utc) != boundary.astimezone(datetime.timezone.utc):
                    raise BlockIdentityError('Default OT crosses an ambiguous local clock; supply explicit daily hours')
            pieces.append((left, right))
    merged = []
    for left, right in sorted(pieces):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    windows = [{'start': left.strftime('%H:%M'), 'end': right.strftime('%H:%M')} for left, right in merged]
    return validate_work_windows(windows) if windows else []


def initial_review(model, *, default_policy=True, work_day=False):
    observations = overtime_evidence(model)
    if default_policy:
        policy = WORK_DAY_OT_POLICY if work_day else DEFAULT_OT_POLICY
        windows = default_overtime_windows(model, observations, policy=policy)
        return {'status': 'defaulted' if windows else 'not_needed', 'observations': observations,
                'confirmed_windows': windows, 'policy': copy.deepcopy(policy)}
    return {'status': 'pending' if observations else 'not_needed',
            'observations': observations, 'confirmed_windows': []}


def validate_review(model):
    review = model.get('overtime_review')
    fields = {'status', 'observations', 'confirmed_windows'}
    if isinstance(review, dict) and 'policy' in review:
        fields.add('policy')
    if not isinstance(review, dict) or set(review) != fields:
        raise BlockIdentityError('OT review requires status, observations and confirmed_windows')
    automatic = 'policy' in review
    if automatic and review['policy'] not in SUPPORTED_OT_POLICIES:
        raise BlockIdentityError('Unsupported default OT policy')
    states = ('defaulted', 'not_needed', 'declined', 'confirmed') if automatic else ('pending', 'not_needed', 'declined', 'confirmed')
    if review['status'] not in states:
        raise BlockIdentityError('Unsupported OT confirmation status')
    if review['observations'] != overtime_evidence(model):
        raise BlockIdentityError('OT observations conflict with frozen source evidence')
    if (review['status'] == 'pending' and not review['observations']
            or review['status'] == 'not_needed' and not automatic and review['observations']):
        raise BlockIdentityError('OT confirmation status conflicts with outside activity')
    if automatic and review['status'] in ('defaulted', 'not_needed'):
        expected = default_overtime_windows(model, review['observations'], policy=review['policy'])
        if (review['confirmed_windows'] != expected
                or (review['status'] == 'defaulted') != bool(expected)):
            raise BlockIdentityError('Default OT windows conflict with the frozen commit-hour policy')
    if review['status'] in ('confirmed', 'defaulted'):
        windows = validate_work_windows(review['confirmed_windows'])
        main = bounds(model, main_windows(model))
        if any(left < main_end and main_start < right
               for left, right in bounds(model, windows) for main_start, main_end in main):
            raise BlockIdentityError('Confirmed OT must be outside the main windows')
    elif review['confirmed_windows'] != []:
        raise BlockIdentityError('Unconfirmed OT cannot contain counted windows')
    return review


def build_overtime_blocks(model, unassigned, **options):
    from build_time_blocks import build_time_blocks
    from commit_intervals import build_commit_intervals, work_confirmation
    review = validate_review(model)
    base = {key: value for key, value in model.items() if key != 'overtime_review'}
    main = main_windows(model)
    if review['status'] not in ('confirmed', 'defaulted'):
        blocks = build_time_blocks(base, unassigned_activity=unassigned, **options)
        for block in blocks:
            block['work_type'] = 'NORMAL'
            block['main_work_windows'] = copy.deepcopy(main)
        return blocks
    combined = sorted([*main, *review['confirmed_windows']], key=lambda item: item['start'])
    if unassigned is not None:
        from activity_review import validate_unassigned_activity
        retained = model.get('unassigned_activity', [])
        validate_unassigned_activity(retained)
        unassigned.extend(copy.deepcopy(retained))
    base['work_confirmation'] = work_confirmation(model['date'], combined[0]['start'], combined[-1]['end'], windows=combined)
    typed = [(left, right, 'NORMAL') for left, right in bounds(model, main)]
    typed += [(left, right, 'OT') for left, right in bounds(model, review['confirmed_windows'])]
    tz = typed[0][0].tzinfo
    blocks = build_commit_intervals(base, datetime.date.fromisoformat(model['date']), tz, unassigned,
                                   allocation_version=options.pop('commit_allocation_version', 2),
                                   allow_minute_end_commits=review['status'] == 'defaulted',
                                   work_types=typed, **options)
    for block in blocks:
        block['main_work_windows'] = copy.deepcopy(main)
        block['overtime_confirmation'] = {'date': model['date'], 'status': 'confirmed',
                                          'windows': copy.deepcopy(review['confirmed_windows'])}
        if 'policy' in review:
            block['overtime_confirmation']['approval_basis'] = ('default_commit_hour'
                if review['status'] == 'defaulted' else 'user_override')
            block['overtime_confirmation']['policy'] = copy.deepcopy(review['policy'])
    return blocks


def require_resolved(model):
    if 'overtime_review' in model and validate_review(model)['status'] == 'pending':
        raise BlockIdentityError('OT confirmation is pending; answer the single OT question before summary/assembly')


def validate_classification(item):
    """The writer also rejects unconfirmed or misclassified OT from direct callers."""
    if 'work_type' not in item:
        return
    from build_time_blocks import parse_dt
    from commit_intervals import subtract_intervals
    kind = item['work_type']
    if kind not in ('NORMAL', 'OT'):
        raise BlockIdentityError('Work type must be NORMAL or OT')
    date = item.get('date') or item.get('entry', {}).get('date')
    model = {'date': date, 'timezone': item.get('timezone')}
    main = bounds(model, validate_work_windows(item.get('main_work_windows')))
    left, right = (parse_dt(item.get('interval', {}).get(field)) for field in ('start', 'end'))
    if left is None or right is None or left.tzinfo is None or right.tzinfo is None or left >= right:
        raise BlockIdentityError('Classified work requires aware interval boundaries')
    if kind == 'NORMAL':
        if any(subtract_intervals(left, right, main)):
            raise BlockIdentityError('NORMAL row must be within main windows')
    else:
        confirmation = item.get('overtime_confirmation', {})
        if confirmation.get('date') != date or confirmation.get('status') != 'confirmed':
            raise BlockIdentityError('OT row requires confirmation for this date')
        windows = bounds(model, validate_work_windows(confirmation.get('windows')))
        if (any(subtract_intervals(left, right, windows))
                or any(left < end and start < right for start, end in main)):
            raise BlockIdentityError('OT row must be within confirmed OT and outside main windows')


def confirmation_question(model):
    review = validate_review(model)
    if review['status'] != 'pending':
        return None
    from build_time_blocks import parse_dt
    evidence = []
    for item in review['observations']:
        if item['source'] == 'google_calendar':
            evidence.append(f"Calendar {parse_dt(item['start']).strftime('%H:%M')}–{parse_dt(item['end']).strftime('%H:%M')} (chưa xác nhận tham dự)")
        else:
            source = 'commit' if item['source'] == 'git' else 'PR'
            evidence.append(f"{source} lúc {parse_dt(item['timestamp']).strftime('%H:%M')}")
    return (f"Ngày {model['date']}, ngoài các block main có {', '.join(evidence)}; "
            "bạn có làm OT không — nếu có, cho biết các khoảng bắt đầu–kết thúc thực tế, nếu không trả lời 'không OT'? "
            "Mốc commit/PR không xác định giờ bắt đầu hay thời lượng OT.")


def resolve_snapshot(source_path, target_path, *, windows=None, decline=False, ai_export=None):
    """Freeze one OT answer using existing evidence; never collect sources again."""
    from pathlib import Path
    from activity_snapshot import read_snapshot, save_snapshot
    from build_time_blocks import build_time_blocks
    from prepare_ai_input import prepare_activity_input
    from output_paths import validate_auxiliary_output
    if (windows is None) == (not decline):
        raise BlockIdentityError('Supply confirmed OT windows or decline OT, exactly one decision')
    source_path, target_path = Path(source_path), Path(target_path)
    if source_path.resolve() == target_path.resolve():
        raise BlockIdentityError('The OT decision requires a new snapshot path; the source is immutable')
    if ai_export:
        validate_auxiliary_output(ai_export, protected_paths=[source_path, target_path])
    frozen = read_snapshot(source_path)
    model = copy.deepcopy(frozen['normalized'])
    review = validate_review(model)
    if 'policy' not in review and review['status'] not in ('pending', 'not_needed'):
        raise BlockIdentityError('OT already resolved; do not ask the same confirmation again')
    model['overtime_review'] = {**review, 'status': 'declined' if decline else 'confirmed',
                                'confirmed_windows': [] if decline else validate_work_windows(windows)}
    validate_review(model)
    retained = []
    blocks = build_time_blocks(model, unassigned_activity=retained)
    payload = prepare_activity_input(blocks, retained, frozen['ai_input']['payload_measurement']['max_bytes'])
    collection = {**frozen['collection'], 'overtime_parent_run_id': frozen['run_id'],
                  'overtime_review': copy.deepcopy(model['overtime_review'])}
    return save_snapshot(target_path, model, collection, blocks, retained, payload, ai_export)
