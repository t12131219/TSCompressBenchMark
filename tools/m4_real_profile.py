#!/usr/bin/env python3
"""Profile three representative real M3 units with pristine, trace-off, and trace-on arms."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m4_real_profile import execute, freeze, recompute
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, load_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    commands = p.add_subparsers(dest='action', required=True)
    f = commands.add_parser('plan')
    for key in ('m3-plan', 'build', 'out'):
        f.add_argument('--' + key, type=Path, required=True)
    f.add_argument('--alp', nargs=5, metavar=('DATASET', 'COLUMN', 'START', 'PLAN', 'RUN'), required=True)
    f.add_argument('--zstd', nargs=3, metavar=('DATASET', 'PLAN', 'RUN'), required=True)
    f.add_argument('--xz', nargs=3, metavar=('DATASET', 'BYTE_START', 'TIMING_RUN'), required=True)
    f.add_argument('--cpu', type=int, action='append', required=True)
    f.add_argument('--overlap-run')
    r = commands.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = commands.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.action == 'plan':
            da, col, lo, ap, ar = a.alp
            dz, zp, zr = a.zstd
            dx, start, xr = a.xz
            plan = freeze(ROOT, m3=a.m3_plan, build=a.build, alp=(da, int(col), int(lo), Path(ap), Path(ar)),
                          zstd=(dz, Path(zp), Path(zr)), xz=(dx, int(start), Path(xr)), cpus=a.cpu, overlap=a.overlap_run)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, plan)
            print(plan['plan_content_id'])
        elif a.action == 'run':
            print(execute(ROOT, load_json(a.plan), a.runs))
        else:
            print(json.dumps(recompute(a.run), ensure_ascii=False, indent=2, sort_keys=True))
    except (ContractError, OSError, ValueError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
