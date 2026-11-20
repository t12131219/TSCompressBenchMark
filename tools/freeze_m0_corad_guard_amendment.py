#!/usr/bin/env python3
"""Freeze or independently verify a narrow M0 CORAD qualification amendment."""
from argparse import ArgumentParser
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.smoke import write_new
from tsbench.assets import load_json, local_file, require
from tsbench.planner.m0_corad_guard_amendment import freeze
from tsbench.planner.native_corpus import verify_native_corpus_plan


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--m0-receipt', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--out', type=Path); mode.add_argument('--verify', type=Path)
    a = parser.parse_args()
    doc = freeze(ROOT, a.m0_receipt)
    verified = verify_native_corpus_plan(ROOT, load_json(local_file(ROOT, doc['base_definition']['path'])))
    require(verified['definition_verified'], 'CORAD amendment has no original M0 definition')
    if a.out:
        write_new(a.out, doc)
    else:
        require(doc == load_json(a.verify), 'CORAD amendment must recompute exactly')
    print(doc['amendment_id'], len(doc['obligations']))


if __name__ == '__main__':
    main()
