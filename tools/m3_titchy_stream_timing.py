#!/usr/bin/env python3
"""Plan, execute and verify Titchy whole-column stream repeats under isolation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_titchy_stream_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='action', required=True)
    f = commands.add_parser('plan')
    for key in ('m3-plan', 'source-plan', 'source-run', 'out'):
        f.add_argument('--' + key, type=Path, required=True)
    f.add_argument('--dataset', action='append')
    f.add_argument('--cpu', required=True, type=int)
    f.add_argument('--overlap-run')
    r = commands.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = commands.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.action == 'plan':
            plan = freeze(ROOT, a.m3_plan, a.source_plan, a.source_run, a.dataset, a.cpu, a.overlap_run)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, plan)
            print(plan['plan_content_id'])
        elif a.action == 'run':
            print(execute(ROOT, load_json(a.plan), a.runs))
        else:
            print(json.dumps(verify(a.run), ensure_ascii=False, indent=2, sort_keys=True))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
