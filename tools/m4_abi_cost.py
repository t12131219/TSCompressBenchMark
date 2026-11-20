#!/usr/bin/env python3
"""Plan, run or independently recompute multiscale same-work M4 ABI controls."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m4_abi_cost import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest='action', required=True)
    f = subs.add_parser('plan')
    for name in ('source', 'build', 'out'):
        f.add_argument('--'+name, required=True, type=Path)
    f.add_argument('--cpu', required=True, type=int)
    r = subs.add_parser('run')
    r.add_argument('--plan', required=True, type=Path)
    r.add_argument('--runs', required=True, type=Path)
    v = subs.add_parser('verify')
    v.add_argument('--run', required=True, type=Path)
    a = p.parse_args()
    try:
        if a.action == 'plan':
            out = a.out.resolve()
            out.parent.mkdir(parents=True, exist_ok=True)
            doc = freeze(ROOT, a.source.resolve(strict=True), a.build.resolve(strict=True), a.cpu, out.parent / 'inputs')
            write_new(out, doc)
            print(json.dumps({'plan_content_id': doc['plan_content_id'], 'slots': doc['slot_count']}))
        elif a.action == 'run':
            print(execute(ROOT, load_json(a.plan), a.runs.resolve()))
        else:
            report = verify(a.run.resolve(strict=True))
            print(json.dumps({k: report[k] for k in ('run_id', 'plan_content_id', 'trials', 'stage_accepted')}))
    except (ContractError, OSError) as exc:
        p.exit(1, str(exc)+'\n')


if __name__ == '__main__':
    main()
