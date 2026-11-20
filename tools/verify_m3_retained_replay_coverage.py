#!/usr/bin/env python3
"""Extend a sealed retained-file coverage audit with the final lzbench replay."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, digest, load_json, require, verify_asset


def coverage(root, prior, replay):
    prior, replay = (p.resolve(strict=True) for p in (prior,replay))
    require(prior.is_relative_to(root) and replay.is_relative_to(root), 'coverage evidence not inside workspace')
    doc = load_json(prior)
    require(doc.pop('coverage_id') == content_id(doc) and doc['schema']=='bmk.m3-r40-corpus-retained-replay-coverage/1' and
            not doc['specialists_counted'] and not doc['new_reference_artifacts_counted'] and
            not doc['timing_admitted'] and not doc['stage_accepted'], 'prior replay coverage differs')
    inventory = load_json(verify_asset(root, doc['inventory']))
    require(inventory['source_seal_id']==doc['run_seal_id'] and inventory['run_id']==doc['run_id'], 'physical inventory refers to a different run')
    known = {r['path']:(r['bytes'],r['sha256']) for r in inventory['physical_inventory']}
    require(len(known)==len(inventory['physical_inventory'])==doc['physical_files'], 'physical inventory denominator differs')
    known_paths = set(known)
    covered = set()
    for e in doc['evidence']:
        for k in ('evidence','report'):
            if k in e:
                verify_asset(root, e[k])
        a = e['physical_files']
        require(len(set(a))==len(a) and not covered.intersection(a), 'prior coverage double counts a physical file')
        covered.update(a)
    remaining = set(doc['unreplayed_paths'])
    require(len(covered)==doc['replay_verified_physical_files'] and covered<=known_paths and known_paths-covered==remaining and
            len(remaining)==len(doc['unreplayed_paths'])==doc['unreplayed_physical_files'], 'prior coverage partition differs')
    verified = load_json(replay)
    require(verified.pop('audit_id')==content_id(verified) and verified['schema']=='bmk.m3-lzbench-full-ledger-audit/1' and
            verified['run_seal_id']==doc['run_seal_id'] and verified['run_id']==doc['run_id'], 'lzbench audit is not from this run')
    refs = verified['replayed_files']
    paths = {r['path'] for r in refs}
    require(len(paths)==len(refs) and paths==remaining and all(known[r['path']]==(r['bytes'],r['sha256']) for r in refs),
            'lzbench replay does not match exactly the unresolved physical identities')
    new = {'evidence':{'path':replay.relative_to(root).as_posix(),'sha256':digest(replay)},'physical_files':sorted(paths)}
    doc.update(evidence=[*doc['evidence'],new], previous={'path':prior.relative_to(root).as_posix(),'sha256':digest(prior)},
               replay_verified_physical_files=len(covered|paths), unreplayed_physical_files=0, unreplayed_paths=[])
    return {**doc, 'coverage_id':content_id(doc)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prior',type=Path,required=True)
    p.add_argument('--lzbench-replay',type=Path,required=True)
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument('--out',type=Path)
    out.add_argument('--verify',type=Path)
    a = p.parse_args()
    try:
        result = coverage(ROOT,a.prior,a.lzbench_replay)
        if a.verify:
            require(result==load_json(a.verify),'saved retained replay coverage differs from recomputation')
        else:
            write_new(a.out,result)
        print(result['coverage_id'],result['replay_verified_physical_files'])
    except (ContractError,OSError,ValueError) as exc:
        p.exit(1,f'{exc}\n')


if __name__=='__main__':
    main()
