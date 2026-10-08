"""Strict adapter for one fresh, completed `codex exec --json` invocation."""
import datetime
import hashlib
import json
from pathlib import Path

from activity_settings import parse_timestamp
from activity_snapshot import read_snapshot, fingerprint


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def completed_usage(path, thread_id=None):
    """CLI usage is a turn total; item events are not additional token records."""
    from collect_token_usage import nonnegative
    thread, started, usage = None, False, None
    try:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            obj = json.loads(line)
            if not isinstance(obj, dict): raise ValueError('Invalid Codex event')
            kind = obj.get('type')
            if kind in ('error', 'turn.failed'):
                raise ValueError('Codex invocation failed; completed total is not established')
            if kind == 'thread.started':
                if thread is not None or started: raise ValueError('Expected one fresh Codex thread')
                thread = obj.get('thread_id')
                if not isinstance(thread, str) or not thread or '/' in thread:
                    raise ValueError('Missing Codex thread identity')
            elif kind == 'turn.started':
                if thread is None or started: raise ValueError('Expected exactly one Codex turn')
                started = True
            elif kind == 'turn.completed':
                if not started or usage is not None: raise ValueError('Ambiguous Codex completion')
                raw = obj.get('usage')
                if not isinstance(raw, dict): raise ValueError('Missing Codex usage')
                required = ('input_tokens', 'cached_input_tokens', 'output_tokens')
                if any(k not in raw for k in required): raise ValueError('Incomplete Codex usage')
                usage = {k: nonnegative(raw[k]) for k in required}
                if usage['cached_input_tokens'] > usage['input_tokens']:
                    raise ValueError('Codex cached input exceeds total input')
                if 'reasoning_output_tokens' in raw:
                    reasoning = nonnegative(raw['reasoning_output_tokens'])
                    if reasoning > usage['output_tokens']: raise ValueError('Reasoning exceeds output')
                    usage['reasoning_output_tokens'] = reasoning
            elif 'usage' in obj:
                raise ValueError('Unsupported Codex usage event')
        if usage is None: raise ValueError('No completed Codex usage; not zero tokens')
        if thread_id is not None and thread != thread_id: raise ValueError('Codex thread mismatch')
        return thread, usage
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Codex event log is unreadable or malformed') from exc


def collect_codex_run(location, manifest, tz, *, expected_target=None,
                      expected_run=None, expected_ai_output=None):
    from collect_token_usage import make_record
    from build_timesheet import load_ai_judgments, build_entries
    if manifest.get('schema') != 'codex_exec_run_v1': raise ValueError('Unsupported Codex run schema')
    if type(manifest.get('process_exit_code')) is not int or manifest['process_exit_code'] != 0:
        raise ValueError('Codex process did not complete successfully')
    run_id, target = manifest.get('run_id'), manifest.get('target_date')
    if not isinstance(run_id, str) or not run_id.strip() or '/' in run_id: raise ValueError('Invalid Codex run_id')
    if not isinstance(target, str) or datetime.date.fromisoformat(target).isoformat() != target:
        raise ValueError('Invalid Codex target_date')
    if expected_target is not None and target != expected_target: raise ValueError('Usage target conflicts with the timesheet date')
    if expected_run is not None and run_id != expected_run: raise ValueError('Usage run_id conflicts with the frozen snapshot')
    start, end = (parse_timestamp(manifest[k]).astimezone(datetime.timezone.utc)
                  for k in ('started_at', 'ended_at'))
    if end <= start: raise ValueError('Usage requires a positive marked invocation window')
    paths = {}
    for key in ('session_file', 'snapshot_file', 'ai_output_file'):
        value = manifest.get(key)
        if not isinstance(value, str) or not value: raise ValueError('Missing Codex evidence path')
        path = Path(value).expanduser()
        paths[key] = path if path.is_absolute() else Path(location).resolve().parent / path
        if sha256(paths[key]) != manifest.get(key + '_sha256'):
            raise ValueError('Codex evidence digest mismatch')
    if expected_ai_output is not None and paths['ai_output_file'].resolve() != Path(expected_ai_output).resolve():
        raise ValueError('Codex usage belongs to a different AI output')
    snapshot = read_snapshot(paths['snapshot_file'])
    if snapshot['run_id'] != run_id or snapshot['normalized']['date'] != target:
        raise ValueError('Codex evidence belongs to a different snapshot')
    if snapshot['collection']['status'] != 'complete': raise ValueError('Codex live usage requires a complete snapshot')
    if fingerprint(snapshot['ai_input']) != manifest.get('ai_input_fingerprint'):
        raise ValueError('Codex input differs from frozen payload')
    judgments = load_ai_judgments(paths['ai_output_file'])
    build_entries(snapshot['blocks'], judgments)
    if {v.get('block_id') for v in judgments} != {v['block_id'] for v in snapshot['ai_input']['blocks']}:
        raise ValueError('Codex output must cover exactly the eligible AI blocks')
    thread, usage = completed_usage(paths['session_file'], manifest.get('session_id'))
    if not isinstance(manifest.get('session_id'), str): raise ValueError('Missing Codex session_id')
    # Codex input includes cached input. Existing CSV partitions input/cache.
    counts = (usage['input_tokens'] - usage['cached_input_tokens'],
              usage['output_tokens'], usage['cached_input_tokens'])
    execution_date = start.astimezone(tz).date().isoformat()
    notes = { 'source': 'codex_exec', 'provider': 'codex', 'run_id': run_id,
              'session_id': thread, 'target_date': target, 'execution_date': execution_date,
              'started_at': manifest['started_at'], 'ended_at': manifest['ended_at'],
              'scope': 'codex_summary_invocation', 'usage_schema': 'codex_exec_run_v1',
              'provider_usage': usage, 'input_definition': 'uncached input = provider input - cached input',
              'cache_definition': 'provider cached input; no separate cache-write count exposed',
              'total_definition': 'provider input + provider output; cache and reasoning are not added twice',
              'timezone': getattr(tz, 'key', str(tz)),
              'evidence': {k + '_sha256': manifest[k + '_sha256'] for k in paths} }
    return make_record(execution_date, f'codex:{thread}/{run_id}', counts, json.dumps(notes, sort_keys=True))
