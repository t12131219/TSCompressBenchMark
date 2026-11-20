#!/usr/bin/env python3
"""Freeze, run or recompute sealed M3 Sprintz FIRE SFB1 repeat diagnostics."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_sprintz_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    f = sub.add_parser('plan')
    for name in ('source-plan', 'source-run', 'out'):
        f.add_argument('--' + name, type=Path, required=True)
    f.add_argument('--scope', choices=('retained', 'whole-bounded'), required=True)
    f.add_argument('--cpu', type=int, required=True)
    r = sub.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = sub.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.action == 'plan':
            plan = freeze(ROOT, args.source_plan.resolve(strict=True), args.source_run.resolve(strict=True), args.scope, args.cpu)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(args.out, plan)
            print(json.dumps({'plan_id': plan['plan_id'], 'cases': len(plan['cases']), 'excluded': plan['excluded']}))
        elif args.action == 'run':
            print(execute(ROOT, load_json(args.plan), args.runs.resolve()))
        else:
            print(json.dumps(verify(args.run.resolve(strict=True)), ensure_ascii=False, sort_keys=True))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
