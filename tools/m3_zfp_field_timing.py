#!/usr/bin/env python3
"""Freeze, run, or verify reversible ZFP whole-field diagnostics."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_zfp_field_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    actions = p.add_subparsers(dest='action', required=True)
    f = actions.add_parser('plan')
    for name in ('source-plan', 'source-run', 'worker', 'observer', 'out'):
        f.add_argument('--'+name, type=Path, required=True)
    f.add_argument('--cpus', type=int, nargs=2, required=True)
    r = actions.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = actions.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.action == 'plan':
            refs = [getattr(args, k).resolve(strict=True) for k in ('source_plan', 'source_run', 'worker', 'observer')]
            plan = freeze(ROOT, *refs, args.cpus)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(args.out, plan)
            print(json.dumps({'plan_content_id': plan['plan_content_id'], 'files': len(plan['cases']),
                              'columns_per_lane': sum(c['columns'] for c in plan['cases'])}))
        elif args.action == 'run':
            print(execute(ROOT, load_json(args.plan), args.runs.resolve()))
        else:
            report = verify(args.run.resolve(strict=True))
            print(json.dumps({k: report[k] for k in ('run_id', 'verified_trials', 'separate_observer_operations', 'file_routes')}))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
