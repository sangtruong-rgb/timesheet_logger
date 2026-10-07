#!/usr/bin/env python3
"""Attributed run usage. Never implicitly scan or charge unrelated Claude sessions."""
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


def usage_object(obj):
    if not isinstance(obj, dict): return None
    for container in (obj, obj.get('message'), obj.get('response')):
        if isinstance(container, dict) and isinstance(container.get('usage'), dict): return container['usage']
    return obj.get('model_usage') if isinstance(obj.get('model_usage'), dict) else None


def parse_transcript_line_usage(obj):
    usage = usage_object(obj)
    if usage is None: return 0, 0, 0
    def count(primary, alias): return nonnegative(usage.get(primary, usage.get(alias, 0)))
    return (count('input_tokens', 'prompt_tokens'), count('output_tokens', 'completion_tokens'),
            count('cache_read_input_tokens', 'cache_read') + count('cache_creation_input_tokens', 'cache_creation'))


def usage_identity(obj):
    for container in (obj.get('message'), obj.get('response')):
        if isinstance(container, dict) and isinstance(container.get('id'), str) and container['id']: return container['id']
    for name in ('message_id', 'requestId', 'request_id', 'id', 'uuid'):
        value = obj.get(name)
        if isinstance(value, str) and value: return value
    # Legacy records without IDs can only be deduplicated as exact snapshots.
    return 'legacy:' + hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def usage_records(path, start, end, message_ids=None):
    """Last timestamped usage snapshot per message; a malformed line cannot lose valid ones."""
    selected, skipped = {}, 0
    try:
        with Path(path).open(encoding='utf-8') as stream:
            for line in stream:
                if not line.strip(): continue
                try:
                    obj = json.loads(line)
                    usage = usage_object(obj)
                    recognized = {'input_tokens','output_tokens','prompt_tokens','completion_tokens',
                                  'cache_read_input_tokens','cache_creation_input_tokens','cache_read','cache_creation'}
                    if usage is None or not recognized.intersection(usage): continue
                    counts = parse_transcript_line_usage(obj)
                    timestamp = parse_timestamp(obj.get('timestamp')).astimezone(datetime.timezone.utc)
                    if not start <= timestamp < end: continue
                    key = usage_identity(obj)
                    if message_ids is not None and key not in message_ids: continue
                    if key not in selected or timestamp >= selected[key][0]: selected[key] = (timestamp, counts)
                except (ValueError, TypeError, KeyError, OverflowError):
                    skipped += 1
    except (OSError, UnicodeError) as exc:
        raise ValueError('Requested transcript is unreadable; token records were preserved') from exc
    if skipped: print(f'Warning: skipped {skipped} malformed/untimestamped usage line(s); valid records retained.', file=sys.stderr)
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


def collect_run(manifest_path, tz, *, expected_target=None, expected_run=None, claude_dir=None):
    location = Path(manifest_path)
    try:
        manifest = json.loads(location.read_text(encoding='utf-8'))
        if not isinstance(manifest, dict): raise ValueError('Run manifest must be an object')
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


def csv_contents(csv_path, new_records):
    existing={}
    path=Path(csv_path)
    if path.exists():
        with path.open(encoding='utf-8',newline='') as stream:
            reader=csv.DictReader(stream)
            if reader.fieldnames != FIELDS: raise ValueError('Token CSV header is corrupt or unsupported; preserved for review')
            for row in reader:
                valid=validated_record(row); key=(valid['date'],valid['session_id'])
                if key in existing: raise ValueError('Duplicate token CSV run identities; preserved for review')
                existing[key]=valid
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
    categories = {name: {key: 0 for key in FIELDS[2:6]} for name in ("transcript", "self_reported")}
    with Path(csv_path).open(encoding="utf-8", newline="") as stream:
        for raw in csv.DictReader(stream):
            row = validated_record(raw)
            if row["date"] != date: continue
            try: metadata = json.loads(row["notes"])
            except ValueError: continue
            if not isinstance(metadata, dict) or metadata.get("source") not in categories: continue
            for key in FIELDS[2:6]: categories[metadata["source"]][key] += row[key]
    return {"execution_date": date, "by_provenance": categories,
            "excludes": "legacy/unattributed/synthetic rows; selected-message scope remains in run notes"}


def main():
    parser=argparse.ArgumentParser(description='Record explicitly attributed Claude run usage.')
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
