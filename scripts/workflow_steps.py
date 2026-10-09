#!/usr/bin/env python3
"""Run and inspect timesheet stages without an outer AI agent or publishing."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
VIEWS = ('sources', 'normalized', 'blocks', 'review', 'ai-input', 'request',
         'instructions', 'prompt', 'schema', 'response', 'ai-output', 'grouping', 'events', 'usage', 'timesheet', 'logs')


def pretty(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def run_logged(run_dir, stage, command):
    """Stream combined output and retain each attempt without truncating old logs."""
    log_dir = run_dir / 'logs'
    log_dir.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', prefix=stage + '-',
                                     suffix='.log', dir=log_dir, delete=False) as log:
        print(f'Log: {log.name}', flush=True)
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True) as process:
            for line in process.stdout:
                print(line, end='', flush=True)
                log.write(line)
                log.flush()
            code = process.wait()
        log.write(f'\nProcess exit code: {code}\n')
    return code


def snapshot_for(run_dir):
    from activity_snapshot import read_snapshot
    return read_snapshot(run_dir / 'activity.json')


def inspect_run(run_dir, view):
    if view == 'logs':
        return '\n'.join(str(p) for p in sorted((run_dir / 'logs').glob('*.log'))) or 'No stage logs yet.'
    snapshot = snapshot_for(run_dir)
    normalized = snapshot['normalized']
    if view == 'sources':
        return pretty({'status': snapshot['collection']['status'],
                       'sources': snapshot['collection']['sources'],
                       'commits': normalized['commits'], 'pull_requests': normalized['pull_requests'],
                       'calendar': normalized['calendar'], 'calendar_context': normalized.get('calendar_context', [])})
    if view in ('normalized', 'blocks'):
        return pretty(snapshot[view])
    if view == 'review':
        return pretty({'unassigned_activity': snapshot['unassigned_activity'],
                       'overtime_review': normalized.get('overtime_review')})
    if view == 'ai-input':
        return pretty(snapshot['ai_input'])
    if view in ('request', 'instructions', 'prompt'):
        # Before summary, show what the compact runner would send. Afterwards,
        # show the actual files recorded by that invocation.
        actual = run_dir / 'codex' / {'request': 'request.json', 'instructions': 'instructions.txt', 'prompt': 'prompt.txt'}[view]
        if actual.exists():
            data = actual.read_text(encoding='utf-8')
            return pretty(json.loads(data)) if view == 'request' else data
        if (run_dir / 'codex').exists():
            raise ValueError(f'This invocation has no recorded {view}; cannot reconstruct its historical input. See codex/ and stage logs.')
        from run_codex_summary import summary_input, summary_instructions
        request, _, prompt = summary_input(snapshot, 'compact')
        if view == 'instructions':
            return summary_instructions(request)
        return pretty(request) if view == 'request' else prompt
    if view == 'usage':
        from collect_token_usage import collect_run
        from activity_settings import resolve_timezone
        manifest = run_dir / 'codex/usage-run.json'
        if not manifest.exists():
            manifest = run_dir / 'codex/usage-attempt.json'
        if not manifest.exists():
            return pretty({'status': 'UNKNOWN' if snapshot['ai_input']['blocks'] else 'SKIPPED',
                           'reason': 'No recorded AI invocation usage; no zero-token claim.'})
        try:
            record = collect_run(manifest, resolve_timezone(normalized['timezone'], allow_legacy_offset=True),
                                 expected_target=normalized['date'], expected_run=snapshot['run_id'])
        except ValueError as exc:
            return pretty({'status': 'UNKNOWN', 'reason': str(exc)})
        notes = json.loads(record['notes'])
        return pretty({'status': 'MEASURED', 'scope': notes['scope'],
                       'provider_usage': notes['provider_usage'],
                       'csv_counts': {k: record[k] for k in ('input_tokens', 'cache_tokens', 'output_tokens', 'total_tokens')},
                       'formula': 'total = provider input + provider output; cached input is included in input',
                       'manifest': str(manifest)})
    paths = {'ai-output': run_dir / 'codex/ai-output.json',
             'grouping': run_dir / 'codex/grouping.json',
             'response': run_dir / 'codex/response.json',
             'schema': run_dir / 'codex/output-schema.json',
             'events': run_dir / 'codex/events.jsonl',
             'timesheet': run_dir / 'timesheets' / (normalized['date'] + '.md')}
    path = paths[view]
    if not path.exists():
        raise ValueError(f'{view} is not available yet: {path}')
    data = path.read_text(encoding='utf-8')
    return pretty(json.loads(data)) if view in ('ai-output', 'response', 'schema', 'grouping') else data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='stage', required=True)
    prepare = subs.add_parser('prepare', help='Collect live sources and freeze blocks; no AI call')
    prepare.add_argument('run_dir', type=Path, help='New output directory; existing paths are refused')
    prepare.add_argument('--date', help='YYYY-MM-DD; default today in profile timezone')
    prepare.add_argument('--config', type=Path, default=ROOT / 'config/user-config.json')
    hours = prepare.add_mutually_exclusive_group(required=True)
    hours.add_argument('--start', help='Morning start, e.g. 09:00; uses current default full-day/OT policy')
    hours.add_argument('--windows', help='Explicit windows, e.g. "09:00-12:00, 13:30-17:30"')
    prepare.add_argument('--end', help='With --start: custom start/end, without default full-day/OT expansion')
    summary = subs.add_parser('summary', help='Call the isolated compact AI summary once')
    summary.add_argument('run_dir', type=Path)
    summary.add_argument('--model')
    summary.add_argument('--codex', default='codex')
    assemble = subs.add_parser('assemble', help='Save final preview and usage; no recollection or AI call')
    assemble.add_argument('run_dir', type=Path)
    assemble.add_argument('--without-ai', action='store_true', help='Explicitly use deterministic fallback descriptions')
    show = subs.add_parser('show', help='Inspect one stage output without network or AI calls')
    show.add_argument('run_dir', type=Path)
    show.add_argument('view', choices=VIEWS)
    args = parser.parse_args(argv)
    run_dir = args.run_dir.expanduser().resolve()
    try:
        if args.stage == 'show':
            print(inspect_run(run_dir, args.view))
            return 0
        pipeline = [sys.executable, str(ROOT / 'scripts/run_pipeline.py')]
        if args.stage == 'prepare':
            if args.end is not None and args.start is None:
                parser.error('--end requires --start')
            # Validate hours before claiming a new run directory or collecting.
            from work_windows import parse_work_windows, default_work_day_windows
            if args.windows is not None:
                parse_work_windows(args.windows)
                hours_args = ['--work-windows', args.windows, '--review-ot']
            elif args.end is not None:
                from commit_intervals import work_confirmation
                work_confirmation(args.date, args.start, args.end)
                hours_args = ['--work-start', args.start, '--work-end', args.end]
            else:
                default_work_day_windows(args.start)
                hours_args = ['--work-day-start', args.start]
            run_dir.mkdir(parents=True, exist_ok=False)
            command = pipeline + ['--phase', 'prepare', '--config', str(args.config.expanduser().resolve()),
                                  '--snapshot', str(run_dir / 'activity.json'),
                                  '--export-ai-input', str(run_dir / 'ai-input.json'),
                                  '--output-dir', str(run_dir / 'timesheets'), *hours_args]
            if args.date:
                command += ['--date', args.date]
        else:
            snapshot = snapshot_for(run_dir)
            if args.stage == 'summary':
                if not snapshot['ai_input']['blocks']:
                    print('SKIPPED: no eligible AI blocks. Continue with assemble.')
                    return 0
                command = [sys.executable, str(ROOT / 'scripts/run_codex_summary.py'),
                           '--snapshot', str(run_dir / 'activity.json'), '--run-dir', str(run_dir / 'codex'),
                           '--codex', args.codex]
                if args.model:
                    command += ['--model', args.model]
            else:
                command = pipeline + ['--phase', 'assemble', '--snapshot', str(run_dir / 'activity.json'),
                                      '--output-dir', str(run_dir / 'timesheets')]
                if snapshot['ai_input']['blocks'] and not args.without_ai:
                    for name in ('ai-output.json', 'usage-run.json'):
                        if not (run_dir / 'codex' / name).exists():
                            raise ValueError('Run summary successfully first, or explicitly assemble --without-ai')
                    command += ['--ai-output', str(run_dir / 'codex/ai-output.json'),
                                '--usage-run-manifest', str(run_dir / 'codex/usage-run.json'),
                                '--token-csv-path', str(run_dir / 'token-usage.csv')]
        return run_logged(run_dir, args.stage, command)
    except (ValueError, OSError) as exc:
        print(f'STEP BLOCKED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
