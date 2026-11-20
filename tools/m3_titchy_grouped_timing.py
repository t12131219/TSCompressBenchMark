#!/usr/bin/env python3
"""Plan, run or independently replay grouped Titchy mechanisms."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application import m3_titchy_grouped_timing as timing
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    cmds = p.add_subparsers(dest='action',required=True)
    f = cmds.add_parser('plan')
    f.add_argument('--population',type=Path,required=True)
    f.add_argument('--cpu',type=int,required=True)
    f.add_argument('--dataset',action='append',default=[])
    f.add_argument('--out',type=Path,required=True)
    r = cmds.add_parser('run')
    r.add_argument('--plan',type=Path,required=True)
    r.add_argument('--runs',type=Path,required=True)
    v = cmds.add_parser('verify')
    v.add_argument('--run',type=Path,required=True)
    a = p.parse_args()
    try:
        if a.action=='plan':
            result = timing.freeze(ROOT,a.population.resolve(strict=True),a.cpu,a.dataset)
            a.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(a.out,result)
            print(result['plan_content_id'])
        elif a.action=='run':
            print(timing.execute(ROOT,load_json(a.plan),a.runs.resolve()),flush=True)
        else:
            report = timing.verify(a.run.resolve(strict=True))
            print(json.dumps({k:report[k] for k in ('run_id','verified_trials','dataset_projection')} | {'cases':len(report['cases'])}))
    except (ContractError,OSError) as e:
        p.exit(1,f'{e}\n')


if __name__=='__main__':
    main()
