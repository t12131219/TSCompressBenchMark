#!/usr/bin/env python3
"""Audit a full switched-input run submitted by the ordinary M3 CLI."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.m3_input_switch import audit
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json, require


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('plan','run'):
        p.add_argument('--'+name,type=Path,required=True)
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument('--out',type=Path)
    dest.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        r = audit(ROOT,load_json(a.plan),a.run.resolve(strict=True))
        if a.verify:
            require(r==load_json(a.verify),'M3 input switch audit differs from independent recomputation')
        else:
            write_new(a.out,r)
        print(r['audit_id'],r['statuses'],r['selections_with_execution_and_validation_evidence'],r['selections_with_verified_switch_result'])
    except (ContractError,OSError,ValueError) as e:
        p.exit(1,str(e)+'\n')


if __name__ == '__main__':
    main()
