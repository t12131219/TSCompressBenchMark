#!/usr/bin/env python3
"""Recompute a machine-readable M3 run census or freeze binding-coverage evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_ledger_census import census
from tsbench.assets import load_json
from tsbench.planner.m3_binding_coverage import binding_coverage
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, help='omit for plan binding coverage only')
    args = parser.parse_args()
    plan = load_json(args.plan)
    if args.run:
        output = census(ROOT, plan, args.run.resolve(strict=True))
    else:
        check_m3_real_corpus_plan(ROOT, plan)
        output = binding_coverage(plan)
    print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
