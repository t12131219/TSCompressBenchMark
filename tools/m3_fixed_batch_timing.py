#!/usr/bin/env python3
"""Freeze, execute or recompute M3 real-corpus paired timing diagnostics."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_batch_timing import report_timing, run_timing
from tsbench.application.smoke import write_new
from tsbench.assets import load_json
from tsbench.planner.m3_batch_timing import plan_timing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan')
    for name in ('functional-plan', 'functional-run', 'audit', 'probe', 'out'):
        plan.add_argument('--' + name, required=True, type=Path)
    plan.add_argument('--cpu', required=True, type=int)
    plan.add_argument('--full-ledger', action='store_true', help='bind the complete sealed functional ledger rather than a preflight')
    run = commands.add_parser('run')
    run.add_argument('--plan', required=True, type=Path)
    run.add_argument('--results', required=True, type=Path)
    report = commands.add_parser('report')
    report.add_argument('--run', required=True, type=Path)
    args = parser.parse_args()
    if args.command == 'plan':
        frozen = plan_timing(ROOT, args.functional_plan.resolve(strict=True), args.functional_run.resolve(strict=True),
                             args.audit.resolve(strict=True), args.probe.resolve(strict=True), cpu=args.cpu,
                             full_ledger=args.full_ledger)
        write_new(args.out, frozen)
        print(json.dumps({'plan_content_id': frozen['plan_content_id'], 'cases': len(frozen['cases']),
                          'groups': len(frozen['groups']), 'expected_batches': frozen['expected_batches']}))
    elif args.command == 'run':
        path = run_timing(ROOT, load_json(args.plan), args.results.resolve())
        rendered = report_timing(path)
        write_new(path / 'report.json', rendered)
        print(json.dumps({'run': str(path), 'status_counts': rendered['status_counts']}))
    else:
        print(json.dumps(report_timing(args.run.resolve(strict=True)), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
