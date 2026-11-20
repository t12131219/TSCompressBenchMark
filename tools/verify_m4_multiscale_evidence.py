#!/usr/bin/env python3
"""Join independently replayed profile, full native clock, and paired ABI records."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m4_cost_comparison import audit_multiscale
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json, require


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('native-run', 'abi-run', 'profile-run'):
        ap.add_argument('--' + key, type=Path, required=True)
    output = ap.add_mutually_exclusive_group(required=True)
    output.add_argument('--out', type=Path)
    output.add_argument('--verify', type=Path)
    a = ap.parse_args()
    try:
        result = audit_multiscale(ROOT, *(path.resolve(strict=True) for path in (a.native_run, a.abi_run, a.profile_run)))
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, result)
        else:
            require(load_json(a.verify) == result, 'multiscale/profile evidence differs from recomputation')
        print(json.dumps({k: result[k] for k in ('audit_id', 'abi_verified_direction_trials', 'profile_verified_direction_trials')}))
    except (ContractError, OSError) as exc:
        ap.exit(1, str(exc)+'\n')
