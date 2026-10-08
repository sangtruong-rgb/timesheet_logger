#!/usr/bin/env python3
"""Attributed Claude/Codex run usage; never implicitly charge unrelated sessions."""
import argparse
import csv
import datetime
import hashlib
import io
import json
import sys
from pathlib import Path
from activity_settings import add_timezone_arguments, timezone_settings, day_bounds, parse_timestamp
from atomic_storage import directory_lock, atomic_write
from token_settings import token_settings

FIELDS = ['date', 'session_id', 'input_tokens', 'output_tokens', 'cache_tokens', 'total_tokens', 'notes']


def get_local_date_str(tz=None):
    return datetime.datetime.now(tz or timezone_settings()[1]).date().isoformat()


def nonnegative(value):
    if isinstance(value, bool): raise ValueError('Token counts must be nonnegative integers')
    if isinstance(value, str) and value.isascii() and value.isdigit(): value = int(value)
    if not isinstance(value, int) or value < 0: raise ValueError('Token counts must be nonnegative integers')
    return value


COUNT_FIELDS = (
    ('input_tokens', 'prompt_tokens'),
    ('output_tokens', 'completion_tokens'),
    ('cache_read_input_tokens', 'cache_read'),
    ('cache_creation_input_tokens', 'cache_creation'),
)
USAGE_SCHEMA = 'complete_usage_snapshot_v1'


def usage_containers(obj):
    if not isinstance(obj, dict): return []
    return [container for container in (obj, obj.get('message'), obj.get('response'))
            if isinstance(container, dict) and 'usage' in container]


def has_usage(obj):
    return bool(usage_containers(obj)) or (isinstance(obj, dict) and
        ('model_usage' in obj or obj.get('type') == 'stream_event'))


def usage_object(obj):
    candidates = [container['usage'] for container in usage_containers(obj)]
    if isinstance(obj, dict) and 'model_usage' in obj: candidates.append(obj['model_usage'])
    if not candidates: return None
    if any(not isinstance(value, dict) for value in candidates):
        raise ValueError('Unsupported usage object; token total is not established')
    if any(value != candidates[0] for value in candidates[1:]):
        raise ValueError('Conflicting usage containers; token total is not established')
    return candidates[0]


def parse_transcript_line_usage(obj):
    """Complete snapshots only. Missing counts are unknown, including cache counts."""
    if isinstance(obj, dict) and obj.get('type') in ('message_start', 'message_delta', 'stream_event'):
        raise ValueError('Raw streaming usage requires a verified adapter; token total is not established')
    usage = usage_object(obj)
    if usage is None: return None
    counts = []
    for primary, alias in COUNT_FIELDS:
        present = [nonnegative(usage[key]) for key in (primary, alias) if key in usage]
        if not present:
            raise ValueError(f'Incomplete usage snapshot: missing {primary}; token total is not established')
        if len(set(present)) != 1:
            raise ValueError(f'Conflicting usage aliases for {primary}; token total is not established')
        counts.append(present[0])
    return counts[0], counts[1], counts[2] + counts[3]


def usage_identity(obj):
    for container in (obj.get('message'), obj.get('response')):
        if isinstance(container, dict) and isinstance(container.get('id'), str) and container['id']: return container['id']
    for name in ('message_id', 'requestId', 'request_id', 'id', 'uuid'):
        value = obj.get(name)
        if isinstance(value, str) and value: return value
    # Legacy records without IDs can only be deduplicated as exact snapshots.
    return 'legacy:' + hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def usage_records(path, start, end, message_ids=None):
    """Latest complete snapshot per message; never silently drop in-scope bad usage."""
    selected, snapshots, skipped = {}, {}, 0
    try:
        with Path(path).open(encoding='utf-8') as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip(): continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise ValueError(f'Transcript line {line_number} is malformed; usage scope cannot be established') from exc
                if not has_usage(obj):
                    if not isinstance(obj, dict): skipped += 1
                    continue
                key = usage_identity(obj)
                if message_ids is not None and key not in message_ids: continue
                try:
                    timestamp = parse_timestamp(obj.get('timestamp')).astimezone(datetime.timezone.utc)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise ValueError(f'Usage line {line_number} has no valid timestamp; token total is not established') from exc
                if not start <= timestamp < end: continue
                try:
                    counts = parse_transcript_line_usage(obj)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise ValueError(f'Usage line {line_number}: {exc}') from exc
                snapshot_key = (key, timestamp)
                if snapshot_key in snapshots and counts != snapshots[snapshot_key]:
                    raise ValueError('Conflicting usage snapshots at the same timestamp; token total is not established')
                snapshots[snapshot_key] = counts
                if key not in selected or timestamp > selected[key][0]: selected[key] = (timestamp, counts)
    except (OSError, UnicodeError) as exc:
        raise ValueError('Requested transcript is unreadable; token records were preserved') from exc
    if message_ids is not None and set(selected) != set(message_ids):
        raise ValueError('Selected usage message IDs are missing within run boundaries; token total is not established')
    return selected, skipped


def make_record(date, key, counts, notes):
    return dict(zip(FIELDS, [date, key, *counts, sum(counts), notes]))


def parse_session_file(file_path, target_date_str, tz=None):
    """Legacy explicit session/day diagnostic; not a skill-run attribution method."""
    tz = tz or timezone_settings()[1]
    start, end = day_bounds(datetime.date.fromisoformat(target_date_str), tz)
    selected, skipped = usage_records(file_path, start, end)
    if not selected: return None
    counts = tuple(sum(v[1][i] for v in selected.values()) for i in range(3))
    return make_record(target_date_str, Path(file_path).stem, counts,
                       f'Session-day diagnostic; timezone={getattr(tz,"key",str(tz))}; skipped={skipped}')


def find_transcripts(base_dir):
    return sorted(Path(base_dir).rglob('*.jsonl')) if Path(base_dir).exists() else []


def collect_run(manifest_path, tz, *, expected_target=None, expected_run=None, claude_dir=None, expected_ai_output=None):
    location = Path(manifest_path)
    try:
        manifest = json.loads(location.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict): raise ValueError('Run manifest must be an object')
        provider = manifest.get('provider', 'claude')
        if provider == 'codex':
            from codex_usage import collect_codex_run
            return collect_codex_run(location, manifest, tz, expected_target=expected_target,
                expected_run=expected_run, expected_ai_output=expected_ai_output)
        if provider != 'claude': raise ValueError('Unsupported token provider')
        run_id = manifest.get('run_id'); target = manifest.get('target_date')
        if not isinstance(run_id, str) or not run_id.strip() or '/' in run_id: raise ValueError('run_id must be a nonempty identifier without /')
        if datetime.date.fromisoformat(target).isoformat() != target: raise ValueError('Invalid target_date')
        if expected_target is not None and target != expected_target: raise ValueError('Usage target conflicts with the timesheet date')
        if expected_run is not None and run_id != expected_run: raise ValueError('Usage run_id conflicts with the frozen snapshot')
        start, end = (parse_timestamp(manifest[k]).astimezone(datetime.timezone.utc) for k in ('started_at', 'ended_at'))
        if end <= start: raise ValueError('Usage requires a positive marked run window [start,end)')
        ids = manifest.get('message_ids')
        if ids is not None and (not isinstance(ids,list) or not ids or any(not isinstance(v,str) or not v for v in ids) or len(set(ids)) != len(ids)):
            raise ValueError('message_ids must be unique nonempty strings')
        session = manifest.get('session_file')
        if session is not None:
            if not isinstance(session,str) or not session: raise ValueError('Invalid session_file')
            transcript = Path(session).expanduser()
            if not transcript.is_absolute(): transcript = location.resolve().parent/transcript
        else:
            session_id = manifest.get('session_id')
            if not isinstance(session_id,str) or not session_id: raise ValueError('Supply session_file or an exact session_id')
            matches = [p for p in find_transcripts(claude_dir or Path.home()/'.claude') if p.stem == session_id]
            if len(matches) != 1: raise ValueError('Exact session_id did not resolve to one transcript')
            transcript = matches[0]
    except (OSError, TypeError, KeyError) as exc:
        raise ValueError('Run manifest is unreadable or malformed') from exc
    selected, skipped = usage_records(transcript, start, end, ids)
    if not selected: raise ValueError('No attributed usage found; this does not establish zero tokens')
    counts = tuple(sum(v[1][i] for v in selected.values()) for i in range(3))
    execution_date = start.astimezone(tz).date().isoformat()
    notes = json.dumps({'source':'transcript', 'run_id':run_id, 'session_id':transcript.stem,
        'target_date':target, 'execution_date':execution_date,
        'started_at':manifest['started_at'], 'ended_at':manifest['ended_at'],
        'scope':'selected_messages' if ids else 'marked_run_window', 'messages':len(selected),
        'usage_schema':USAGE_SCHEMA, 'missing_counts':'blocked',
        'skipped_lines':skipped, 'timezone':getattr(tz,'key',str(tz)),
        'total_definition':'input + output + cache_read + cache_creation'}, sort_keys=True)
    return make_record(execution_date, f'{transcript.stem}/{run_id}', counts, notes)


def validated_record(record):
    if not isinstance(record, dict) or set(record) != set(FIELDS): raise ValueError('Token CSV row has invalid fields')
    date = record['date']; key=record['session_id']
    if not isinstance(date,str) or datetime.date.fromisoformat(date).isoformat() != date: raise ValueError('Invalid token date')
    if not isinstance(key,str) or not key.strip() or not isinstance(record['notes'],str): raise ValueError('Invalid token identity/notes')
    counts = [nonnegative(record[k]) for k in FIELDS[2:6]]
    if sum(counts[:3]) != counts[3]: raise ValueError('Token total does not equal input + output + cache')
    return dict(zip(FIELDS, [date,key,*counts,record['notes']]))


def read_csv_records(csv_path):
    """Apply the same identity checks to reporting and writes."""
    existing, attributed_dates = {}, {}
    with Path(csv_path).open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != FIELDS:
            raise ValueError('Token CSV header is corrupt or unsupported; preserved for review')
        for row in reader:
            valid = validated_record(row)
            date, identity = valid['date'], valid['session_id']
            key = (date, identity)
            if key in existing:
                raise ValueError('Duplicate token CSV run identities; preserved for review')
            if '/' in identity:
                if identity in attributed_dates and attributed_dates[identity] != date:
                    raise ValueError('Attributed run identity cannot move between execution dates')
                attributed_dates[identity] = date
            existing[key] = valid
    return existing


def csv_contents(csv_path, new_records):
    path = Path(csv_path)
    existing = read_csv_records(path) if path.exists() else {}
    for record in new_records:
        valid=validated_record(record)
        if '/' in valid['session_id'] and any(key[1] == valid['session_id'] and key[0] != valid['date'] for key in existing):
            raise ValueError('Attributed run identity cannot move between execution dates')
        existing[(valid['date'],valid['session_id'])]=valid
    stream=io.StringIO(newline=''); writer=csv.DictWriter(stream,fieldnames=FIELDS,lineterminator="\n")
    writer.writeheader(); writer.writerows(existing[k] for k in sorted(existing))
    return stream.getvalue(), sum(r['total_tokens'] for r in existing.values())


def update_csv(csv_path, new_records):
    if not new_records: return  # Absence of usage is not a reason to rewrite/initialize a store.
    path=Path(csv_path)
    with directory_lock(path.parent):
        content,total=csv_contents(path,new_records)
        if not path.exists() or path.read_bytes() != content.encode('utf-8'): atomic_write(path,content)
    return total


def daily_totals(csv_path, date):
    """Separate measured transcripts from self-reported totals; exclude legacy/synthetic rows."""
    categories = {name: {key: 0 for key in FIELDS[2:6]} for name in ("transcript", "codex_exec", "self_reported")}
    if not isinstance(date, str) or datetime.date.fromisoformat(date).isoformat() != date:
        raise ValueError('Invalid token execution date')
    for row in read_csv_records(csv_path).values():
        if row["date"] != date: continue
        try: metadata = json.loads(row["notes"])
        except ValueError: continue
        if not isinstance(metadata, dict) or metadata.get("source") not in categories: continue
        for key in FIELDS[2:6]: categories[metadata["source"]][key] += row[key]
    return {"execution_date": date, "by_provenance": categories,
            "excludes": "legacy/unattributed/synthetic rows; selected-message scope remains in run notes"}


def main():
    parser=argparse.ArgumentParser(description='Record explicitly attributed Claude or Codex run usage.')
    add_timezone_arguments(parser)
    parser.add_argument('--date',help='Execution date for a manual record')
    parser.add_argument('--target-date',help='Timesheet target date, distinct from execution date')
    parser.add_argument('--claude-dir'); parser.add_argument('--csv-path')
    parser.add_argument('--run-manifest',help='JSON identifying run/session and marked boundaries')
    parser.add_argument('--session-file',help='Deprecated without a run manifest: does not establish run attribution')
    parser.add_argument('--run-id')
    parser.add_argument('--record-usage',nargs=4,metavar=('SESSION_ID','INPUT','OUTPUT','CACHE'),help='Self-reported cumulative run totals; requires --run-id')
    args=parser.parse_args()
    try:
        name,tz=timezone_settings(args.config,args.timezone)
        paths=token_settings(args.config,args.claude_dir,args.csv_path)
        if args.run_manifest and args.record_usage: raise ValueError('Choose transcript evidence or a manual record')
        if args.run_manifest:
            record=collect_run(args.run_manifest,tz,expected_target=args.target_date,expected_run=args.run_id,claude_dir=paths['claude_dir'])
        elif args.record_usage:
            if not args.run_id or '/' in args.run_id: raise ValueError('Manual cumulative totals require --run-id without /')
            session,*numbers=args.record_usage; counts=tuple(nonnegative(n) for n in numbers)
            date=args.date or get_local_date_str(tz)
            target=args.target_date or date
            if datetime.date.fromisoformat(target).isoformat()!=target: raise ValueError('Invalid target-date')
            record=make_record(date,f'{session}/{args.run_id}',counts,json.dumps({'source':'self_reported','run_id':args.run_id,'target_date':target,'timezone':name,'scope':'manual_cumulative_run_total'}))
        else:
            raise ValueError('Supply --run-manifest or --record-usage with --run-id. Unrelated transcripts are never implicitly scanned.')
        update_csv(paths['csv_path'],[record])
    except (ValueError,OSError,TypeError) as exc:
        print(f'Token recording blocked: {exc}',file=sys.stderr); return 2
    print(json.dumps({'record':record,'execution_day_totals':daily_totals(paths['csv_path'],record['date']),'csv_path':str(paths['csv_path'])},indent=2)); return 0


if __name__=='__main__': sys.exit(main())
