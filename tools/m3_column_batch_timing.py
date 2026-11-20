#!/usr/bin/env python3
"""Plan, run and replay whole-column ALP/Titchy batch measurements."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import m3_column_batch_timing as timing
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    actions = p.add_subparsers(dest='action', required=True)
    plan = actions.add_parser('plan')
    plan.add_argument('--population', type=Path, required=True)
    plan.add_argument('--cpu', type=int, required=True)
    plan.add_argument('--dataset')
    plan.add_argument('--out', type=Path, required=True)
    run = actions.add_parser('run')
    run.add_argument('--plan', type=Path, required=True)
    run.add_argument('--runs', type=Path, required=True)
    verify = actions.add_parser('verify')
    verify.add_argument('--run', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.action == 'plan':
            doc = timing.freeze(ROOT,args.population.resolve(strict=True),args.cpu,args.dataset)
            args.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(args.out,doc)
            print(doc['plan_content_id'])
        elif args.action == 'run':
            print(timing.execute(ROOT,load_json(args.plan),args.runs.resolve()),flush=True)
        else:
            report = timing.verify(args.run.resolve(strict=True))
            print(json.dumps({k:report[k] for k in ('run_id','verified_trials','dataset_projection')} | {'cases':len(report['cases'])}))
    except (ContractError,OSError) as e:
        p.exit(1,f'{e}\n')


if __name__ == '__main__':
    main()
