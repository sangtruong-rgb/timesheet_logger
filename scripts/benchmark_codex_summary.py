#!/usr/bin/env python3
"""Compare both summary strategies on one frozen snapshot, without publishing."""
import argparse
import json
import re
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from activity_snapshot import read_snapshot
from build_timesheet import build_entries
from collect_token_usage import collect_run, update_csv
from run_codex_summary import run_summary


def attempt_ledger(directory, snapshot, model):
    """Count each verified invocation once, including rejected summaries/retries."""
    attempts, records = [], {}
    totals = {strategy: {'known_tokens': 0, 'unknown_attempts': 0, 'measured_attempts': 0}
              for strategy in ('legacy', 'compact')}
    for path in sorted(directory.iterdir()):
        match = re.fullmatch(r'(legacy|compact)(?:-retry-[1-9][0-9]*)?', path.name)
        if not match or not path.is_dir():
            continue
        strategy = match[1]
        receipt = path / 'usage-attempt.json'
        success = path / 'usage-run.json'
        manifest_path = receipt if receipt.exists() else success
        info = {'strategy': strategy, 'directory': path.name, 'usage_status': 'unknown',
                'summary_status': 'unknown', 'total_tokens': None}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if (manifest.get('model_requested') != model or manifest.get('summary_strategy') != strategy
                    or manifest.get('reasoning_effort') != 'low'
                    or manifest.get('run_id') != snapshot['run_id']
                    or manifest.get('target_date') != snapshot['normalized']['date']):
                raise ValueError('Attempt ledger contains a conflicting invocation')
            info['summary_status'] = manifest.get('summary_status', 'success')
            if manifest.get('usage_status', 'measured') == 'measured':
                record = collect_run(manifest_path, ZoneInfo(snapshot['normalized']['timezone']),
                                     expected_target=snapshot['normalized']['date'], expected_run=snapshot['run_id'])
                key = (record['date'], record['session_id'])
                if key in records:
                    raise ValueError('Attempt ledger contains a duplicate invocation')
                records[key] = record
                info.update(usage_status='measured', total_tokens=record['total_tokens'],
                            provider_usage=json.loads(record['notes'])['provider_usage'])
                totals[strategy]['known_tokens'] += record['total_tokens']
                totals[strategy]['measured_attempts'] += 1
        if info['usage_status'] == 'unknown':
            totals[strategy]['unknown_attempts'] += 1
        attempts.append(info)
    ledger = {'attempts': attempts, 'strategies': totals,
              'all_attempts_measured': all(t['unknown_attempts'] == 0 for t in totals.values()),
              'total_known_tokens': sum(t['known_tokens'] for t in totals.values())}
    from atomic_storage import atomic_write
    atomic_write(directory / 'attempts.json', json.dumps(ledger, ensure_ascii=False, indent=2))
    if records:
        update_csv(directory / 'token-usage.csv', list(records.values()))
    return ledger


def benchmark(snapshot_path, directory, *, model, codex='codex', timeout=300, resume=False):
    snapshot = read_snapshot(snapshot_path)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=resume)
    results, entries, source_entries = {}, {}, {}
    for strategy in ('legacy', 'compact'):
        result_path = directory / (strategy + '-result.json')
        if resume and result_path.exists():
            result = json.loads(result_path.read_text())
            manifest = json.loads(Path(result['usage_run_manifest']).read_text())
            record = collect_run(result['usage_run_manifest'], ZoneInfo(snapshot['normalized']['timezone']),
                                 expected_target=snapshot['normalized']['date'], expected_run=snapshot['run_id'],
                                 expected_ai_output=result['ai_output'])
            if (result['provider_usage'] != json.loads(record['notes'])['provider_usage'] or
                    manifest['model_requested'] != model or manifest['reasoning_effort'] != 'low' or
                    manifest['summary_strategy'] != strategy or result['cli_version'] != manifest['cli_version']):
                raise ValueError('Existing benchmark result conflicts with verified invocation')
        else:
            started = time.monotonic()
            run_path = directory / strategy
            attempt = 0
            while resume and run_path.exists():
                attempt += 1
                run_path = directory / f'{strategy}-retry-{attempt}'
            try:
                result = run_summary(snapshot_path, run_path, model=model, codex=codex,
                                     timeout=timeout, reasoning_effort='low', strategy=strategy)
            finally:
                # Preserve incurred costs even when summary validation aborts.
                attempt_ledger(directory, snapshot, model)
            result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        usage = result['provider_usage']
        result['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
        result['uncached_input_tokens'] = usage['input_tokens'] - usage['cached_input_tokens']
        results[strategy] = result
        judgments = json.loads(Path(result['ai_output']).read_text())
        entries[strategy] = build_entries(snapshot['blocks'], judgments)
        # Validate the accepted grouped rows above; compare each original source
        # interval below. Compact v5+ is allowed to present fewer rows than legacy.
        source_entries[strategy] = build_entries(snapshot['blocks'], [
            {k: v for k, v in item.items() if k != 'workstream_group'} for item in judgments])
        collect_run(result['usage_run_manifest'], ZoneInfo(snapshot['normalized']['timezone']),
                    expected_target=snapshot['normalized']['date'], expected_run=snapshot['run_id'],
                    expected_ai_output=result['ai_output'])
        result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')

    def structural(rows):
        return [{**row, 'entry': {k: v for k, v in row['entry'].items() if k != 'description'}} for row in rows]

    if structural(source_entries['legacy']) != structural(source_entries['compact']):
        raise ValueError('Benchmark changed source intervals, evidence or metadata')
    if results['legacy']['cli_version'] != results['compact']['cli_version']:
        raise ValueError('CLI version changed during benchmark')
    ledger = attempt_ledger(directory, snapshot, model)
    before, after = results['legacy'], results['compact']
    def reduction(old, new):
        return round(100 * (1 - new / old), 2) if old else None

    report = {'snapshot': str(Path(snapshot_path).resolve()), 'snapshot_run_id': snapshot['run_id'],
              'target_date': snapshot['normalized']['date'], 'model': model, 'reasoning_effort': 'low',
              'cli_version': before['cli_version'], 'repetitions_per_strategy': 1,
              'scope': 'AI summary invocations only; provider input includes their context; excludes outer chat',
              'results': results, 'timesheet_rows': len(snapshot['blocks']),
              'intervals_evidence_metadata_unchanged': structural(entries['legacy']) == structural(entries['compact']),
              'source_intervals_evidence_metadata_unchanged': True,
              'output_rows': {strategy: len(rows) for strategy, rows in entries.items()},
              'attempt_usage': ledger,
              'input_reduction_percent': reduction(before['provider_usage']['input_tokens'], after['provider_usage']['input_tokens']),
              'total_reduction_percent': reduction(before['total_tokens'], after['total_tokens']),
              'quality_note': 'Source coverage and evidence validated; compact grouping may reduce rows. Description meaning requires review. One pair is not a statistical estimate.'}
    (directory / 'benchmark.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--codex', default='codex')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--resume', action='store_true', help='Verify and reuse completed measurements; preserve failed attempts')
    args = parser.parse_args()
    try:
        if args.timeout <= 0:
            raise ValueError('Timeout must be positive')
        report = benchmark(args.snapshot, args.run_dir, model=args.model, codex=args.codex, timeout=args.timeout,
                           resume=args.resume)
    except (OSError, ValueError) as exc:
        print(f'BENCHMARK BLOCKED: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
