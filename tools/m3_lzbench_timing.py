#!/usr/bin/env python3
"""Freeze, execute or verify isolated M3 lzbench session and XZ worker repetitions."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_lzbench_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--m3-plan', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--reference', action='append', nargs=4, metavar=('DATASET', 'ROUTE', 'PLAN', 'RUN'), required=True)
    p.add_argument('--cpu', action='append', type=int, required=True)
    p.add_argument('--overlap-run')
    p = sub.add_parser('run')
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--runs', type=Path, required=True)
    p = sub.add_parser('verify')
    p.add_argument('--run', type=Path, required=True)
    a = parser.parse_args()
    try:
        if a.action == 'plan':
            references = [(d, r, Path(p), Path(run)) for d, r, p, run in a.reference]
            doc = freeze(ROOT, a.m3_plan, references, a.cpu, a.overlap_run)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, doc)
            print(doc['plan_content_id'])
        elif a.action == 'run':
            print(execute(ROOT, load_json(a.plan), a.runs))
        else:
            print(json.dumps(verify(a.run), ensure_ascii=False, sort_keys=True, indent=2))
    except (ContractError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
