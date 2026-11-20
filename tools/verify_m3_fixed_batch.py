#!/usr/bin/env python3
"""Verify sealed M3 batch sample retention, optionally replaying without originals."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_fixed_batch_audit import audit_fixed_batch
from tsbench.application.smoke import write_new
from tsbench.assets import load_json

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--full-ledger', action='store_true',
                        help='stream the original full ledger and check its seal without loading the detailed report')
    parser.add_argument('--out', type=Path, help='write a new audit JSON file after verification')
    args = parser.parse_args()
    audit = audit_fixed_batch(ROOT, load_json(args.plan), args.run.resolve(strict=True), replay=args.replay,
                              full_ledger=args.full_ledger)
    if args.out is None:
        print(json.dumps(audit, indent=2, ensure_ascii=False))
    else:
        write_new(args.out, audit)
