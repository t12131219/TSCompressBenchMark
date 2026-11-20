#!/usr/bin/env python3
"""Freeze, execute, or independently verify representative M3 pcodec page timings."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_pcodec_page_timing import execute, freeze, verify_report
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def selector(text):
    try:
        dataset, column, start = text.split(':')
        return dataset, int(column), int(start)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('case must be DATASET:COLUMN:ROW_START') from exc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('plan')
    for name in ('m3-plan', 'source-plan', 'source-run', 'out'):
        p.add_argument(f'--{name}', type=Path, required=True)
    cases = p.add_mutually_exclusive_group(required=True)
    cases.add_argument('--case', action='append', type=selector)
    cases.add_argument('--all-files-first-column', action='store_true',
                       help='cover every page group of the first value column per applicable file from the same complete M3 run')
    p.add_argument('--cpu', type=int, required=True)
    p.add_argument('--overlap-run', help='project-relative active functional run to disclose as interference')
    p = commands.add_parser('run')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--runs', type=Path, required=True)
    p = commands.add_parser('verify')
    p.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'plan':
            plan = freeze(ROOT, args.m3_plan, args.source_plan, args.source_run, args.case, args.cpu, args.overlap_run,
                          full_corpus=args.all_files_first_column)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(args.out, plan)
            print(plan['plan_content_id'])
        elif args.command == 'run':
            print(execute(ROOT, load_json(args.plan), args.runs))
        else:
            print(json.dumps(verify_report(args.run), sort_keys=True, ensure_ascii=False, indent=2))
    except (ContractError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
