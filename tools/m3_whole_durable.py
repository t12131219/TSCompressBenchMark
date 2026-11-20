#!/usr/bin/env python3
"""Freeze, run and verify verified-durable Sprintz/Huff0/SElf* diagnostics."""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_whole_durable as timing
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    parser = ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('plan')
    for name in ('abi', 'selfstar', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--cpu', type=int, required=True)
    p.add_argument('--dataset')
    r = sub.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = sub.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    a = parser.parse_args()
    try:
        if a.action == 'plan':
            doc = timing.freeze(ROOT, {'abi': a.abi.resolve(strict=True), 'selfstar': a.selfstar.resolve(strict=True)}, a.cpu, a.dataset)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, doc)
            print(json.dumps({'plan_content_id': doc['plan_content_id'], 'file_routes': len(doc['cases']), 'trials': 8 * len(doc['cases'])}))
        elif a.action == 'run':
            print(timing.execute(ROOT, load_json(a.plan), a.runs.resolve()))
        else:
            doc = timing.verify(ROOT, a.run.resolve(strict=True))
            print(json.dumps({k: doc[k] for k in ('run_id', 'file_routes', 'verified_trials', 'dataset_projection')}))
    except (ContractError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
