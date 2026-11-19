#!/usr/bin/env python3
"""Reseal edited Gorilla lifecycle work records without touching the source run."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.gorilla import TRAFFIC
from tsbench.planner.gorilla_state import APPEND, ITER, is_state


def main(run):
    parent = report_batch_execution(run)
    plan = load_json(run/'plan.json')
    indices = {s['method']:i for i,s in enumerate(plan['slots']) if is_state(s) and s['name']==TRAFFIC}
    outcomes = {}

    def write(path,obj):
        path.write_bytes(canonical_bytes(obj)+b'\n')

    def reject(name,method,expected,change):
        with tempfile.TemporaryDirectory(prefix='tsbench-gorilla-state-reseal-') as t:
            copy = Path(t)/'run'
            shutil.copytree(run,copy)
            rows = _rows(copy/'ledger.jsonl')
            change(copy,rows[indices[method]])
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(row)+b'\n' for row in rows))
            seal = load_json(copy/'seal.json')
            seal.pop('seal_id')
            seal['files'] = _files(copy)
            write(copy/'seal.json',{**seal,'seal_id':content_id(seal)})
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(expected in str(exc),f'wrong Gorilla lifecycle denial: {exc}')
                outcomes[name] = str(exc)
            else:
                raise AssertionError(f'{name} survived resealing')

    def elide_copy(copy,row):
        path = copy/'logs'/row['product_slot']/'prefix-work.stdout'
        val = load_json(path)
        val.update(source_copy_calls=0,source_bytes_copied=0)
        row['gorilla_state']['work']['prefix-work'] = val
        write(path,val)

    def fake_backward_seek(copy,row):
        path = copy/'logs'/row['product_slot']/'iterator-work.stdout'
        val = load_json(path)
        val[1].update(next_calls=1,rows_scanned=1)
        row['gorilla_state']['work']['iterator-work'] = val
        write(path,val)

    def extra_mount(_copy,row):
        row['operations'][1]['input_mounts'].update(row['operations'][0]['input_mounts'])

    def alter_progress(copy,row):
        path = copy/'logs'/row['product_slot']/'state-resume.stdout'
        val = load_json(path)
        val['resumed_prefix']['chunk_bits'] -= 1
        write(path,val)

    reject('erase_resume_copy',APPEND,'scan/copy or iterator work differs',elide_copy)
    reject('misstate_backward_seek_work',ITER,'scan/copy or iterator work differs',fake_backward_seek)
    reject('mount_uncompressed_prefix_at_resume',APPEND,'lifecycle input closure differs',extra_mount)
    reject('change_resumed_prefix_bits',APPEND,'resume progress or bad snapshot differs',alter_progress)
    require(report_batch_execution(run)==parent,'Gorilla control changed the original run')
    return {'schema':'bmk.gorilla-state-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':outcomes}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
