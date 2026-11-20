#!/usr/bin/env python3
"""Freeze, run or verify whole-file M3 Sprintz-FIRE and Huff0 ABI timing diagnostics."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_abi_corpus_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='action', required=True)
    f = commands.add_parser('plan')
    for n in ('source-plan', 'source-run', 'worker', 'out'):
        f.add_argument('--' + n, type=Path, required=True)
    f.add_argument('--cpu', type=int, required=True)
    r = commands.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = commands.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.action == 'plan':
            plan = freeze(ROOT, a.source_plan.resolve(strict=True), a.source_run.resolve(strict=True),
                          a.worker.resolve(strict=True), a.cpu)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, plan)
            print(json.dumps({'plan_id': plan['plan_id'], 'cases': len(plan['cases']), 'excluded': plan['excluded']}))
        elif a.action == 'run':
            print(execute(ROOT, load_json(a.plan), a.runs.resolve()))
        else:
            print(json.dumps(verify(a.run.resolve(strict=True)), sort_keys=True))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
