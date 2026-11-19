#!/usr/bin/env python3
"""Resign scratch copies of real Huff0 products; never mutate the submitted run."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.huff0_execution import _model_binding
from tsbench.application.smoke import _ref, _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner import huff0_bmi2 as bmi2
from tsbench.planner.huff0 import TABLE
from tsbench.planner.huff0_execution import SHARED


def main(run):
    original = report_batch_execution(run)
    plan = load_json(run/'plan.json')
    index, = [i for i,s in enumerate(plan['slots']) if s['method']==SHARED and s['profile']=='synthetic' and s['streams']==1]
    slot = plan['slots'][index]
    rejected = {}

    def exercise(label, wanted, mutate):
        with tempfile.TemporaryDirectory(prefix='tsbench-huff0-reseal-') as tmp:
            scratch = Path(tmp)/'run'
            shutil.copytree(run,scratch)
            rows = _rows(scratch/'ledger.jsonl')
            row = rows[index]
            mutate(scratch,row)
            (scratch/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in rows))
            seal = load_json(scratch/'seal.json')
            seal.pop('seal_id')
            seal['files'] = _files(scratch)
            (scratch/'seal.json').write_bytes(canonical_bytes({**seal,'seal_id':content_id(seal)})+b'\n')
            try:
                report_batch_execution(scratch)
            except ContractError as exc:
                require(wanted in str(exc),f'wrong failure for {label}: {exc}')
                rejected[label] = str(exc)
            else:
                raise AssertionError(label+' passed with a fresh seal')

    def alternate(scratch,row):
        model = scratch/row['parts']['model']['path']
        model.write_bytes((scratch/row['controls']['alternate']['path']).read_bytes())
        row['parts']['model'] = _ref(scratch,model)

    def no_binding(scratch,row):
        (scratch/row['parts'].pop('binding')['path']).unlink()

    def raw_byte(scratch,row):
        blocks = [scratch/row['parts'][f'block-{i}']['path'] for i in range(len(slot['blocks']))]
        i = slot['modes'].index('raw')
        data = bytearray(blocks[i].read_bytes())
        data[TABLE.size] ^= 1
        blocks[i].write_bytes(data)
        row['parts'][f'block-{i}'] = _ref(scratch,blocks[i])
        binding = scratch/row['parts']['binding']['path']
        binding.write_bytes(_model_binding(slot,scratch/row['parts']['model']['path'],blocks))
        row['parts']['binding'] = _ref(scratch,binding)

    def dispatch(scratch,row):
        log = scratch/'logs'/row['product_slot']/'table-decode.stdout'
        obj = load_json(log)
        obj['completed_decode_calls'][1][1] += 1
        log.write_bytes(canonical_bytes(obj)+b'\n')

    exercise('alternate_for_primary','expected model/block binding differs',alternate)
    exercise('unaccounted_deleted_binding','validation evidence differs',no_binding)
    exercise('raw_literal_with_updated_binding','original-byte oracle differs',raw_byte)
    exercise('forged_native_calls','native decode entry or count differs',dispatch)
    if plan.get('suite')==bmi2.SUITE:
        def swapped_dso(scratch,row):
            # Re-sealing the package does not let the primary library enter the OFF scope.
            name = 'lib/libreference.so'
            dest = scratch/bmi2.DIRECTORY/name
            dest.chmod(0o600)
            dest.write_bytes((scratch/'recovery'/name).read_bytes())

        def wrong_mount(scratch,row,key):
            control, = [o for o in row['operations'] if o['operation']==bmi2.OPERATION]
            other = row['controls']['alternate'] if key=='model' else row['parts']['block-1']
            control['input_mounts'][key] = {k:other[k] for k in ('bytes','sha256')}

        def no_portable_work(scratch,row):
            log = scratch/'logs'/row['product_slot']/(bmi2.OPERATION+'.stdout')
            obj = load_json(log)
            obj['completed_decode_calls'] = [[0,0] for _ in obj['completed_decode_calls']]
            log.write_bytes(canonical_bytes(obj)+b'\n')

        exercise('on_library_in_portable_scope','recovery package differs',swapped_dso)
        exercise('portable_decoded_with_wrong_model','same retained payloads and model',lambda s,r: wrong_mount(s,r,'model'))
        exercise('portable_decoded_wrong_block','same retained payloads and model',lambda s,r: wrong_mount(s,r,'block-0'))
        exercise('portable_claimed_no_native_work','native decode entry or count differs',no_portable_work)
    require(report_batch_execution(run)==original,'control mutated original run')
    return {'schema':'bmk.huff0-reseal-controls/1','run_id':original['run_id'],'seal_id':original['seal_id'],'rejections':rejected}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
