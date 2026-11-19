#!/usr/bin/env python3
"""Reject a CORAD quality upgrade or broadened decoder access after resealing."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.corad_execution import is_corad


def main(run):
    parent=report_batch_execution(run)
    index, = [i for i,s in enumerate(load_json(run/'plan.json')['slots']) if is_corad(s)]
    results={}

    def reject(label,message,mutate):
        with tempfile.TemporaryDirectory(prefix='tsbench-corad-reseal-') as tmp:
            copy=Path(tmp)/'run'; shutil.copytree(run,copy)
            rows=_rows(copy/'ledger.jsonl')
            mutate(rows[index])
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in rows))
            seal=load_json(copy/'seal.json'); del seal['seal_id']; seal['files']=_files(copy)
            (copy/'seal.json').write_bytes(canonical_bytes({**seal,'seal_id':content_id(seal)})+b'\n')
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(message in str(exc),f'wrong CORAD semantic refusal: {exc}')
                results[label]=str(exc)
            else:
                raise AssertionError(f'{label} survived reseal')

    def admit(row):
        row['corad']['quality_comparable']=True
        for model in row['corad']['quality_gate']['heldout'].values():
            model['decision']='passed'
            for col in model['columns']:
                col.update(max_abs_passed=True,rmse_passed=True)

    def original(row):
        ops={op['operation']:op for op in row['operations']}
        ops['restore-0']['input_mounts']['v0']=ops['encode-0']['input_mounts']['v0']

    reject('admit_both_rejected_heldout_models','quality or functional ledger differs',admit)
    reject('leak_original_column_into_decoder','mount or output identity differs',original)
    require(report_batch_execution(run)==parent,'CORAD control modified parent run')
    return {'schema':'bmk.corad-inference-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':results}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
