#!/usr/bin/env python3
"""Freeze, run or independently replay the real-input axis role diagnostics."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_axis_roles import audit_roles, run_roles
from tsbench.application.smoke import write_new
from tsbench.assets import load_json
from tsbench.planner.m3_axis_roles import plan_roles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan')
    for name in ('projection', 'build-lock', 'out'):
        plan.add_argument(f'--{name}', type=Path, required=True)
    run = commands.add_parser('run')
    for name in ('plan', 'results'):
        run.add_argument(f'--{name}', type=Path, required=True)
    audit = commands.add_parser('audit')
    audit.add_argument('--run', type=Path, required=True)
    audit.add_argument('--replay', action='store_true')
    args = parser.parse_args()
    if args.command == 'plan':
        frozen = plan_roles(ROOT, args.projection.resolve(strict=True), args.build_lock.resolve(strict=True))
        write_new(args.out, frozen)
        print(json.dumps({'plan_content_id': frozen['plan_content_id'], 'cases': len(frozen['cases'])}))
    elif args.command == 'run':
        run = run_roles(ROOT, load_json(args.plan), args.results.resolve())
        result = audit_roles(run)
        write_new(run / 'report.json', result)
        print(json.dumps({'run': str(run), 'role_cases': result['role_cases']}))
    else:
        print(json.dumps(audit_roles(args.run.resolve(strict=True), replay=args.replay), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
