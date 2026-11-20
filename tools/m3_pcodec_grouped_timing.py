#!/usr/bin/env python3
"""Freeze, execute, or verify whole-file pcodec page measurements."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_pcodec_grouped_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    f = subs.add_parser('plan')
    for name in ('source-plan', 'source-run', 'tool', 'out'):
        f.add_argument('--' + name, type=Path, required=True)
    f.add_argument('--cpu', type=int, required=True)
    r = subs.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = subs.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    a = parser.parse_args()
    try:
        if a.action == 'plan':
            plan = freeze(ROOT, a.source_plan.resolve(strict=True), a.source_run.resolve(strict=True),
                          a.tool.resolve(strict=True), a.cpu)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, plan)
            print(json.dumps({'plan_content_id': plan['plan_content_id'], 'cases': len(plan['cases']),
                              'groups_per_lane': sum(c['group_count'] for c in plan['cases'])}))
        elif a.action == 'run':
            print(execute(ROOT, load_json(a.plan), a.runs.resolve()))
        else:
            report = verify(a.run.resolve(strict=True))
            print(json.dumps({k: report[k] for k in ('run_id', 'verified_trials', 'file_routes')}))
    except (ContractError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
