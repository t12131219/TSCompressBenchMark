#!/usr/bin/env python3
"""Recompute exact M3/M4 input bindings and separate, valid cost comparisons."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tsbench.application.m4_cost_comparison import compare
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, load_json, require


def _legacy_projection(result):
    # Only for verification of immutable v1 outputs; v1's interference text
    # was constant and must not be used to interpret the run environment.
    body = {k: v for k, v in result.items() if k not in ('comparison_id', 'multiscale_abi_diagnostics')}
    body['schema'] = 'bmk.m4-real-cost-comparison/1'
    body['policy'] = {'subtract_only_matched_same_scope_pairs': True,
                      'interference': 'profile run declared functional overlap; no causal estimates or formal rank',
                      'unmeasured': {'allocation_or_copy_counts': None, 'host_exclusivity': None,
                                     'matched_direct_to_framework_all_size_costs': None}}
    return {**body, 'comparison_id': content_id(body)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('profile','alp','zstd','xz'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--multiscale-link', type=Path, help='exact replayed multiscale/profile link for this profile seal')
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out',type=Path)
    out.add_argument('--verify',type=Path)
    args = p.parse_args()
    try:
        result = compare(ROOT,args.profile,{'alp-fused':args.alp,'zstd-mt':args.zstd,'xz-opaque':args.xz},
                         multiscale_link=args.multiscale_link)
        if args.verify:
            stored = load_json(args.verify)
            if stored.get('schema') == 'bmk.m4-real-cost-comparison/1':
                require(args.multiscale_link is None, 'legacy M4 cost comparison cannot bind multiscale evidence')
                result = _legacy_projection(result)
                print('Historical v1 overlap text is not derived from the sealed environment.', file=sys.stderr)
            require(result==stored,'M4 cost comparison differs from recomputation')
        else:
            write_new(args.out,result)
        print(result['comparison_id'],len(result['cases']))
    except (ContractError,OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')


if __name__=='__main__':
    main()
