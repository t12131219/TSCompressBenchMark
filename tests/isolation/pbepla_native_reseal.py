#!/usr/bin/env python3
"""Reject PBEPLA semantic evidence edits after recomputing the outer seal."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.pbepla_execution import PROGRESSIVE, REPLAY, is_pbepla


def main(run):
    parent = report_batch_execution(run)
    slots = load_json(run/'plan.json')['slots']
    indices = {(s['method'],s['spec']['name']):i for i,s in enumerate(slots)
               if is_pbepla(s) and s['variant']=='prefixes'}
    rejections = {}

    def reject(label,method,name,error,mutate):
        with tempfile.TemporaryDirectory(prefix='tsbench-pbepla-reseal-') as tmp:
            copy = Path(tmp)/'run'
            shutil.copytree(run,copy)
            ledger = _rows(copy/'ledger.jsonl')
            row = ledger[indices[method,name]]
            mutate(copy,row)
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in ledger))
            seal = load_json(copy/'seal.json')
            del seal['seal_id']
            seal['files'] = _files(copy)
            (copy/'seal.json').write_bytes(canonical_bytes({**seal,'seal_id':content_id(seal)})+b'\n')
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(error in str(exc),f'wrong PBEPLA semantic refusal: {exc}')
                rejections[label] = str(exc)
            else:
                raise AssertionError(f'{label} survived reseal')

    def add_original(_copy,row):
        ops = {op['operation']:op for op in row['operations']}
        ops['restore-1']['input_mounts']['input'] = ops['native-encode']['input_mounts']['input']

    def early_sink(copy,row):
        path = copy/'logs'/row['product_slot']/'callback-encode.stdout'
        io = load_json(path)
        io['first_sink_after_pass'] = 1
        row['pbepla']['replay']['io'] = io
        path.write_bytes(canonical_bytes(io)+b'\n')

    def wrong_prefix_output(_copy,row):
        ops = {op['operation']:op for op in row['operations']}
        ops['restore-1']['outputs']['out'] = ops['restore-2']['outputs']['out']

    reject('leak_original_into_abi_decoder',PROGRESSIVE,'piecewise','mount or scratch closure differs',add_original)
    reject('count_replay_sink_as_online',REPLAY,'weather','replay',early_sink)
    reject('substitute_other_prefix_restore',PROGRESSIVE,'weather','actual output identity',wrong_prefix_output)
    require(report_batch_execution(run)==parent,'PBEPLA control modified parent run')
    return {'schema':'bmk.pbepla-native-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':rejections}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
