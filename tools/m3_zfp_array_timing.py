#!/usr/bin/env python3
"""Freeze, run and independently recompute ZFP fixed-rate array diagnostics."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.application.m3_zfp_array_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    plan = actions.add_parser('plan')
    for name in ('source-plan','source-run','tool','out'):
        plan.add_argument('--'+name, type=Path, required=True)
    plan.add_argument('--cpu', type=int, required=True)
    run = actions.add_parser('run')
    run.add_argument('--plan', type=Path, required=True)
    run.add_argument('--runs', type=Path, required=True)
    check = actions.add_parser('verify')
    check.add_argument('--run', type=Path, required=True)
    a = parser.parse_args()
    try:
        if a.action == 'plan':
            frozen = freeze(ROOT, a.source_plan.resolve(strict=True), a.source_run.resolve(strict=True), a.tool.resolve(strict=True), a.cpu)
            a.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(a.out,frozen)
            print(json.dumps({'plan_content_id': frozen['plan_content_id'], 'files': len(frozen['cases']),
                              'windows': sum(len(c['units']) for c in frozen['cases']),
                              'rejected_windows_from_r40': sum(c['rejected_windows'] for c in frozen['cases'])}))
        elif a.action == 'run':
            print(execute(ROOT, load_json(a.plan), a.runs.resolve()))
        else:
            report = verify(a.run.resolve(strict=True))
            print(json.dumps({k: report[k] for k in ('run_id','reconciled_trials','verified_file_scope_trials','file_status',
                                                   'window_count','rejected_windows')}))
    except (ContractError, OSError) as exc:
        parser.exit(1,f'{exc}\n')


if __name__ == '__main__':
    main()
