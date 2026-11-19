#!/usr/bin/env python3
"""Mutate a copied ledger and recompute its seal; require semantic denials."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.lzbench_profiles import DICT, XZ, ZSTD, is_profile


def write(path,value):
    path.write_bytes(canonical_bytes(value)+b'\n')


def main(run):
    parent = report_batch_execution(run)
    indices = {s['method']:i for i,s in enumerate(load_json(run/'plan.json')['slots']) if is_profile(s)}
    outcomes = {}

    def reject(name,method,expected,mutate):
        with tempfile.TemporaryDirectory(prefix='tsbench-lzbench-profile-reseal-') as directory:
            copy = Path(directory)/'run'
            shutil.copytree(run,copy)
            ledger = _rows(copy/'ledger.jsonl')
            mutate(copy,ledger[indices[method]])
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in ledger))
            seal = load_json(copy/'seal.json')
            del seal['seal_id']
            seal['files'] = _files(copy)
            write(copy/'seal.json',{**seal,'seal_id':content_id(seal)})
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(expected in str(exc),f'wrong lzbench profile denial: {exc}')
                outcomes[name] = str(exc)
            else:
                raise AssertionError(f'{name} survived resealing')

    def leak_holdout(_copy,row):
        train,encode = [next(op for op in row['operations'] if op['operation']==k) for k in ('train','encode')]
        train['input_mounts']['raw'] = encode['input_mounts']['raw']

    def erase_two_workers(copy,row):
        path = copy/'logs'/row['product_slot']/'encode-2.stdout'
        doc = load_json(path)
        doc['encode_jobs']['worker_threads'] = 1
        row['profile']['observed']['2']['encode_jobs']['worker_threads'] = 1
        write(path,doc)

    def mount_truth_at_shared_decode(_copy,row):
        a,b = [next(op for op in row['operations'] if op['operation']==label) for label in ('encode-sync','decode-shared-2')]
        b['input_mounts']['raw'] = a['input_mounts']['raw']

    reject('leak_held_out_input_to_trainer',DICT,'profile input closure differs',leak_holdout)
    reject('substitute_requested_for_observed_workers',ZSTD,'worker trace identity/census differs',erase_two_workers)
    reject('mount_raw_at_same_frame_decode',XZ,'profile input closure differs',mount_truth_at_shared_decode)
    require(report_batch_execution(run)==parent,'profile reseal control changed the original run')
    return {'schema':'bmk.lzbench-profile-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':outcomes}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
