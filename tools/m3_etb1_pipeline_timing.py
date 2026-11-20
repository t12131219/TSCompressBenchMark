#!/usr/bin/env python3
"""Plan, run, and verify complete ETB1 source-to-durable repeats."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.m3_etb1_pipeline_timing import execute, freeze, verify
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action',required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('--native-run',type=Path,required=True)
    plan.add_argument('--out',type=Path,required=True)
    plan.add_argument('--cpu',type=int,required=True)
    run = sub.add_parser('run')
    run.add_argument('--plan',type=Path,required=True)
    run.add_argument('--runs',type=Path,required=True)
    audit = sub.add_parser('verify')
    audit.add_argument('--run',type=Path,required=True)
    args = parser.parse_args()
    try:
        if args.action == 'plan':
            frozen = freeze(ROOT,args.native_run.resolve(strict=True),args.cpu)
            args.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(args.out,frozen)
            print(json.dumps({'plan_id':frozen['plan_id'],'cases':len(frozen['cases'])}))
        elif args.action == 'run':
            print(execute(ROOT,load_json(args.plan),args.runs.resolve()))
        else:
            print(json.dumps(verify(args.run.resolve(strict=True)),sort_keys=True))
    except (ContractError,OSError) as e:
        parser.exit(1,f'{e}\n')


if __name__ == '__main__':
    main()
