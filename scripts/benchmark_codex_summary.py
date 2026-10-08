#!/usr/bin/env python3
"""Compare both summary strategies on one frozen snapshot, without publishing."""
import argparse
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

from activity_snapshot import read_snapshot
from build_timesheet import build_entries
from collect_token_usage import collect_run, update_csv
from run_codex_summary import run_summary


def benchmark(snapshot_path, directory, *, model, codex='codex', timeout=300, resume=False):
    snapshot = read_snapshot(snapshot_path)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=resume)
    results, entries, records = {}, {}, []
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
            result = run_summary(snapshot_path, run_path, model=model, codex=codex,
                                 timeout=timeout, reasoning_effort='low', strategy=strategy)
            result['elapsed_seconds'] = round(time.monotonic() - started, 3)
        usage = result['provider_usage']
        result['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
        result['uncached_input_tokens'] = usage['input_tokens'] - usage['cached_input_tokens']
        results[strategy] = result
        entries[strategy] = build_entries(snapshot['blocks'], json.loads(Path(result['ai_output']).read_text()))
        records.append(collect_run(result['usage_run_manifest'], ZoneInfo(snapshot['normalized']['timezone']),
                                   expected_target=snapshot['normalized']['date'], expected_run=snapshot['run_id'],
                                   expected_ai_output=result['ai_output']))
        result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')

    def structural(rows):
        return [{**row, 'entry': {k: v for k, v in row['entry'].items() if k != 'description'}} for row in rows]

    if structural(entries['legacy']) != structural(entries['compact']):
        raise ValueError('Benchmark changed timesheet intervals, evidence or metadata')
    if results['legacy']['cli_version'] != results['compact']['cli_version']:
        raise ValueError('CLI version changed during benchmark')
    update_csv(directory / 'token-usage.csv', records)
    before, after = results['legacy'], results['compact']
    def reduction(old, new):
        return round(100 * (1 - new / old), 2) if old else None

    report = {'snapshot': str(Path(snapshot_path).resolve()), 'snapshot_run_id': snapshot['run_id'],
              'target_date': snapshot['normalized']['date'], 'model': model, 'reasoning_effort': 'low',
              'cli_version': before['cli_version'], 'repetitions_per_strategy': 1,
              'scope': 'AI summary invocations only; provider input includes their context; excludes outer chat',
              'results': results, 'timesheet_rows': len(snapshot['blocks']),
              'intervals_evidence_metadata_unchanged': True,
              'input_reduction_percent': reduction(before['provider_usage']['input_tokens'], after['provider_usage']['input_tokens']),
              'total_reduction_percent': reduction(before['total_tokens'], after['total_tokens']),
              'quality_note': 'Coverage and structural equivalence validated; description meaning requires review. One pair is not a statistical estimate.'}
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
