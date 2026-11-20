#!/usr/bin/env python3
"""Check corpus artifact custody in exactly one sealed M3 run."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_full_custody import audit
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--allow-partial', action='store_true', help='accept an explicitly scoped diagnostic run')
    p.add_argument('--replay-pages', action='store_true', help='replay pcodec samples via the locked files-only closure')
    a = p.parse_args()
    try:
        doc = audit(ROOT, load_json(a.plan), a.run, allow_partial=a.allow_partial, replay_pages=a.replay_pages)
        print(json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
