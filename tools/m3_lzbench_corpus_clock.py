#!/usr/bin/env python3
"""Freeze, execute and verify whole-corpus Zstd/XZ native-clock observations."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_lzbench_corpus_clock import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='action', required=True)
    f = commands.add_parser('plan')
    for key in ('source-plan', 'source-run', 'build', 'out'):
        f.add_argument('--' + key, type=Path, required=True)
    f.add_argument('--cpu', action='append', required=True, type=int)
    r = commands.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = commands.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.action == 'plan':
            plan = freeze(ROOT, a.source_plan.resolve(strict=True), a.source_run.resolve(strict=True),
                          a.build.resolve(strict=True), sorted(a.cpu))
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, plan)
            print(json.dumps({'plan_content_id': plan['plan_content_id'], 'cases': len(plan['cases']),
                              'conditional': len(plan['conditional'])}))
        elif a.action == 'run':
            print(execute(ROOT, load_json(a.plan), a.runs.resolve()))
        else:
            report = verify(a.run.resolve(strict=True))
            print(json.dumps({k: report[k] for k in ('run_id', 'file_routes', 'conditional', 'verified_trials')}))
    except (ContractError, OSError) as e:
        p.exit(1, f'{e}\n')


if __name__ == '__main__':
    main()
