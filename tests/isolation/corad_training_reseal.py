#!/usr/bin/env python3
"""Reject forged convergence and training/holdout mixing under a recomputed seal."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.corad_training_execution import C, SOURCE, is_training


def main(run):
    parent=report_batch_execution(run)
    indices={s['method']:i for i,s in enumerate(load_json(run/'plan.json')['slots']) if is_training(s)}
    results={}

    def reject(label,method,message,mutate):
        with tempfile.TemporaryDirectory(prefix='tsbench-corad-training-reseal-') as t:
            copy=Path(t)/'run'; shutil.copytree(run,copy)
            rows=_rows(copy/'ledger.jsonl'); mutate(copy,rows[indices[method]])
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in rows))
            seal=load_json(copy/'seal.json'); del seal['seal_id']; seal['files']=_files(copy)
            (copy/'seal.json').write_bytes(canonical_bytes({**seal,'seal_id':content_id(seal)})+b'\n')
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(message in str(exc),f'wrong CORAD training semantic refusal: {exc}')
                results[label]=str(exc)
            else:
                raise AssertionError(f'{label} survived reseal')

    def converged(copy,row):
        for i,fit in enumerate(row['training']['c_training']['fits']):
            fit['stats']['converged']=1
            log=copy/'logs'/row['product_slot']/f'fit-{i}.stdout'; doc=load_json(log)
            doc['stats']['converged']=1
            log.write_bytes(canonical_bytes(doc)+b'\n')

    def heldout(_,row):
        ops={op['operation']:op for op in row['operations']}
        ops['train-source-sklearn']['input_mounts']['heldout']=ops['evaluate-source-sklearn']['input_mounts']['values']

    reject('relabel_outer_limit_as_convergence',C,'outer iteration limit is not convergence',converged)
    reject('mount_heldout_in_source_fit',SOURCE,'training mount or output identity differs',heldout)
    require(report_batch_execution(run)==parent,'CORAD training control modified parent run')
    return {'schema':'bmk.corad-training-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':results}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
