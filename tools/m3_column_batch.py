#!/usr/bin/env python3
"""Freeze or independently audit whole-column ALP and Titchy batch anchors."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_column_batch import freeze
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json, require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ('source-plan', 'source-run', 'worker'):
        p.add_argument('--'+arg, type=Path, required=True)
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument('--out', type=Path)
    dest.add_argument('--verify', type=Path)
    a = p.parse_args()
    try:
        pop = freeze(ROOT, *(x.resolve(strict=True) for x in (a.source_plan, a.source_run, a.worker)))
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, pop)
        else:
            require(load_json(a.verify) == json.loads(json.dumps(pop)), 'column batch population does not recompute')
        print(json.dumps({'population_id': pop['population_id'], 'file_routes': Counter(c['route'] for c in pop['cases']),
                          'frozen_units': sum(len(c['units']) for c in pop['cases']), 'excluded': len(pop['excluded'])}))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
