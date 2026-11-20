#!/usr/bin/env python3
"""Plan, run and recompute the whole-file C11 Gorilla timing diagnosis."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from tsbench.application.m3_gorilla_corpus_clock import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    plan = commands.add_parser('plan')
    for name in ('source-plan', 'source-run', 'out'):
        plan.add_argument('--' + name, type=Path, required=True)
    plan.add_argument('--cpu', type=int, required=True)
    run = commands.add_parser('run')
    run.add_argument('--plan', type=Path, required=True)
    run.add_argument('--runs', type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'plan':
            frozen = freeze(ROOT, args.source_plan.resolve(strict=True), args.source_run.resolve(strict=True), args.cpu)
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(args.out, frozen)
            print(f"{frozen['plan_content_id']}: {len(frozen['cases'])} applicable, {len(frozen['excluded'])} excluded")
        elif args.action == 'run':
            print(execute(ROOT, load_json(args.plan), args.runs.resolve()))
        else:
            proof = verify(args.run.resolve(strict=True))
            print(f"{proof['run_id']}: {proof['verified_trials']} trials, {proof['isolated_operations']} isolated operations")
    except (ContractError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
