#!/usr/bin/env python3
"""Freeze and recompute the Titchy grouped mechanism populations."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.m3_titchy_grouped import freeze
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json, require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ('source-plan','source-run','tool'):
        p.add_argument('--'+flag,type=Path,required=True)
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument('--out',type=Path)
    dest.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        pop = freeze(ROOT, *(x.resolve(strict=True) for x in (a.source_plan,a.source_run,a.tool)))
        if a.out:
            a.out.parent.mkdir(parents=True,exist_ok=True)
            write_new(a.out,pop)
        else:
            require(load_json(a.verify)==pop,'Titchy grouped population differs from r40 replay')
        print(json.dumps({'population_id':pop['population_id'],'file_routes':Counter(c['route'] for c in pop['cases']),
                          'units':sum(len(c['units']) for c in pop['cases']), 'excluded':len(pop['excluded'])}))
    except (ContractError,OSError) as e:
        p.exit(1,f'{e}\n')


if __name__ == '__main__':
    main()
