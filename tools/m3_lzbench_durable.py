#!/usr/bin/env python3
"""Plan, execute or independently audit real-source durable Zstd/XZ trials."""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_lzbench_durable import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = ArgumentParser(description=__doc__)
    actions = p.add_subparsers(dest='action', required=True)
    make = actions.add_parser('plan')
    make.add_argument('--native-run', type=Path, required=True)
    make.add_argument('--out', type=Path, required=True)
    run = actions.add_parser('run')
    run.add_argument('--plan', type=Path, required=True)
    run.add_argument('--runs', type=Path, required=True)
    check = actions.add_parser('verify')
    check.add_argument('--run', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.action == 'plan':
            plan = freeze(ROOT, args.native_run.resolve(strict=True))
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(args.out, plan)
            print(json.dumps({'plan_content_id': plan['plan_content_id'], 'cases': len(plan['cases']),
                              'conditional': len(plan['conditional'])}))
        elif args.action == 'run':
            print(execute(ROOT, load_json(args.plan), args.runs.resolve()))
        else:
            report = verify(ROOT, args.run.resolve(strict=True))
            print(json.dumps({k: report[k] for k in ('run_id', 'file_routes', 'conditional', 'verified_trials')}))
    except (ContractError, OSError) as exc:
        p.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
