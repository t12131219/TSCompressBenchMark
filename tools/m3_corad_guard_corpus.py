#!/usr/bin/env python3
"""Freeze, run and verify the opt-in CORAD guard on the complete r40 CORAD extent."""
from argparse import ArgumentParser
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application import m3_corad_guard_corpus as corpus
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode',required=True)
    f = sub.add_parser('plan')
    for name in ('source-plan','source-run','build-lock','pilot','out'):
        f.add_argument('--'+name,type=Path,required=True)
    f.add_argument('--dataset')
    r = sub.add_parser('run')
    r.add_argument('--plan',type=Path,required=True)
    r.add_argument('--out',type=Path,required=True)
    sub.add_parser('verify').add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    try:
        if a.mode == 'plan':
            doc = corpus.freeze(ROOT,a.source_plan.resolve(),a.source_run.resolve(),a.build_lock.resolve(),a.pilot.resolve(),a.dataset)
            a.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(a.out,doc)
            print(json.dumps({'files':len(doc['cases']),'cohorts':doc['cohorts'],'frame_count':doc['frame_count']}))
        elif a.mode == 'run':
            corpus.execute(ROOT,load_json(a.plan),a.out.resolve())
        else:
            report = corpus.verify(ROOT,a.out.resolve())
            print(json.dumps({k:report[k] for k in ('files','cohorts','frames','observed_processes','summaries')}))
    except (ContractError,OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')


if __name__ == '__main__':
    main()
