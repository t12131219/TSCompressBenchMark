#!/usr/bin/env python3
"""Freeze, run and verify full-extent fixed pcodec/Zstd/XZ ABI diagnostics."""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_fixed_batch_corpus as corpus
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    parser = ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('plan')
    for name in ('source-plan', 'source-run', 'worker', 'out'):
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
            plan = corpus.freeze(ROOT, a.source_plan.resolve(strict=True), a.source_run.resolve(strict=True),
                                 a.worker.resolve(strict=True), a.cpu, a.dataset)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, plan)
            print(json.dumps({'plan_content_id': plan['plan_content_id'], 'cases': len(plan['cases']),
                              'excluded': len(plan['excluded']), 'trials': 8 * len(plan['cases'])}))
        elif a.action == 'run':
            print(corpus.execute(ROOT, load_json(a.plan), a.runs.resolve()))
        else:
            report = corpus.verify(ROOT, a.run.resolve(strict=True))
            print(json.dumps({k: report[k] for k in ('run_id', 'file_routes', 'verified_trials', 'dataset_projection')}))
    except (ContractError, OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
