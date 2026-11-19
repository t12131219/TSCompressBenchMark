#!/usr/bin/env python3
"""ZFP candidate semantic negatives, even after the modified run is resealed."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.zfp_execution import ARRAY, OMP, is_zfp


def write(path,value):
    path.write_bytes(canonical_bytes(value)+b'\n')


def main(run):
    parent = report_batch_execution(run)
    idx = {s['method']:i for i,s in enumerate(load_json(run/'plan.json')['slots']) if is_zfp(s)}
    results = {}

    def reject(label,method,message,damage):
        with tempfile.TemporaryDirectory(prefix='tsbench-zfp-reseal-') as tmp:
            copy = Path(tmp)/'run'
            shutil.copytree(run,copy)
            ledger = _rows(copy/'ledger.jsonl')
            row = ledger[idx[method]]
            damage(copy,row)
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in ledger))
            seal = load_json(copy/'seal.json')
            del seal['seal_id']
            seal['files'] = _files(copy)
            write(copy/'seal.json',{**seal,'seal_id':content_id(seal)})
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(message in str(exc),f'wrong ZFP negative: {exc}')
                results[label] = str(exc)
            else:
                raise AssertionError(f'{label} survived reseal')

    def forged_worker(copy,row):
        path = copy/'logs'/row['product_slot']/'encode-2.stdout'
        doc = load_json(path)
        doc['encode_block_work'] = [{'tid':doc['caller_tid'],'blocks':2048}]
        row['zfp']['profiles']['2'] = doc
        write(path,doc)

    def leaked_input(_copy,row):
        row['operations'][-1]['input_mounts']['input'] = row['operations'][0]['input_mounts']['input']

    def wrong_metadata(copy,row):
        ref = row['parts']['metadata']
        p = copy/ref['path']
        p.write_bytes(p.read_bytes().replace(b'18',b'19'))
        row['parts']['metadata'] = _files(copy)[ref['path']]
        for op in row['operations']:
            op['input_mounts']['metadata'] = {k:row['parts']['metadata'][k] for k in ('bytes','sha256')}

    reject('collapse_two_worker_census_to_caller',OMP,'invalid native block work record',forged_worker)
    reject('leak_original_into_omp_restore',OMP,'mount or environment closure differs',leaked_input)
    reject('replace_array_rate_metadata',ARRAY,'external format metadata differs',wrong_metadata)
    require(report_batch_execution(run)==parent,'ZFP control modified parent run')
    return {'schema':'bmk.zfp-native-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':results}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
