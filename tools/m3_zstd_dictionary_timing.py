#!/usr/bin/env python3
"""Freeze, execute or independently recompute grouped Zstd dictionary diagnostics."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_zstd_dictionary_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('plan')
    for name in ('source-plan', 'source-run', 'tool', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--cpu', type=int, required=True)
    r = sub.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = sub.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'plan':
            plan = freeze(ROOT, args.source_plan.resolve(strict=True), args.source_run.resolve(strict=True),
                          args.tool.resolve(strict=True), args.cpu)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(args.out, plan)
            print(json.dumps({'plan_content_id': plan['plan_content_id'], 'files': len(plan['cases']),
                              'heldout_frames': sum(len(c['anchor']['frames']) for c in plan['cases'])}))
        elif args.action == 'run':
            print(execute(ROOT, load_json(args.plan), args.runs.resolve()))
        else:
            report = verify(args.run.resolve(strict=True))
            print(json.dumps({k: report[k] for k in ('run_id', 'verified_trials', 'file_routes')}))
    except (ContractError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
