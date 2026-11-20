#!/usr/bin/env python3
"""Audit full versus projected repeat evidence against one sealed functional M3 run."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_measurement_inventory import MODES, audit
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json, require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--evidence', nargs=2, action='append', metavar=('MODE', 'SEALED_DIAGNOSTIC_RUN'), default=[])
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument('--out', type=Path)
    dest.add_argument('--verify', type=Path)
    args = p.parse_args()
    try:
        require(all(mode in MODES for mode, _ in args.evidence), 'unknown diagnostic mode')
        report = audit(ROOT, args.plan.resolve(strict=True), args.run.resolve(strict=True),
                       [(mode, Path(path).resolve(strict=True)) for mode, path in args.evidence])
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(args.out, report)
        else:
            require(report == load_json(args.verify), 'measurement inventory does not recompute')
        print(json.dumps({'inventory_id': report['inventory_id'], 'decisions': len(report['decisions']),
                          'linked_diagnostics': len(report['diagnostics']),
                          'verified_decision_coverage': {kind: dict(Counter(r['clock_coverage'][kind] for r in report['decisions']
                                                                           if r['status'] == 'verified'))
                                                         for kind in ('native_repeat', 'verified_durable_repeat')}}))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
