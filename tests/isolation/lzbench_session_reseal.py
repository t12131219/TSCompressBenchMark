#!/usr/bin/env python3
"""Reject semantically invalid native-session evidence even with a valid seal."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.lzbench_session import is_session


def write(path,value):
    path.write_bytes(canonical_bytes(value)+b'\n')


def main(run):
    parent = report_batch_execution(run)
    indices = {s['method']:i for i,s in enumerate(load_json(run/'plan.json')['slots']) if is_session(s)}
    outcomes = {}

    def reject(name,method,expected,mutate):
        with tempfile.TemporaryDirectory(prefix='tsbench-lzbench-reseal-') as directory:
            copy = Path(directory)/'run'
            shutil.copytree(run,copy)
            ledger = _rows(copy/'ledger.jsonl')
            row = ledger[indices[method]]
            mutate(copy,row)
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in ledger))
            seal = load_json(copy/'seal.json')
            del seal['seal_id']
            seal['files'] = _files(copy)
            write(copy/'seal.json',{**seal,'seal_id':content_id(seal)})
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(expected in str(exc),f'wrong lzbench session denial: {exc}')
                outcomes[name] = str(exc)
            else:
                raise AssertionError(f'{name} survived resealing')

    def hide_finish(copy,row):
        log = copy/'logs'/row['product_slot']/'session-exercise.stdout'
        evidence = load_json(log)
        evidence['calls']['encode-first'][-1][-1] = 0
        write(log,evidence)

    def drop_guard(copy,row):
        log = copy/'logs'/row['product_slot']/'session-exercise.stdout'
        evidence = load_json(log)
        evidence['guards'].pop('decode-budget')
        row['session']['guards'].pop('decode-budget')
        write(log,evidence)

    def mount_first_at_second(_copy,row):
        row['operations'][2]['input_mounts']['predecessor'] = row['operations'][1]['input_mounts']['frame']

    reject('erase_native_finish','zstd-session','span or finish accounting differs',hide_finish)
    reject('omit_decoder_budget_rejection','xz-session','rejection census differs',drop_guard)
    reject('mount_predecessor_at_second_restore','xz-session','session input closure differs',mount_first_at_second)
    require(report_batch_execution(run)==parent,'lzbench reseal control changed the original run')
    return {'schema':'bmk.lzbench-session-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':outcomes}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
