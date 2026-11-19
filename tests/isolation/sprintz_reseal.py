#!/usr/bin/env python3
"""Reject modified Sprintz query evidence even with a valid new file seal."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _ref, _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.sprintz_execution import QUERY


def main(run):
    report = report_batch_execution(run)
    plan = load_json(run/'plan.json')
    i, = [i for i,s in enumerate(plan['slots']) if s['method']==QUERY and s['name']=='u16-wide-sum']
    slot = plan['slots'][i]
    sid = slot['product_slot']
    require(slot['oracle']['sum'][0] >= 2**32, 'wide unsigned fixture no longer crosses 32 bits')
    rejected = {}

    def write(path, body):
        path.write_bytes(canonical_bytes(body)+b'\n')

    def exercise(label, reason, mutate):
        with tempfile.TemporaryDirectory(prefix='tsbench-sprintz-reseal-') as tmp:
            scratch = Path(tmp)/'run'
            shutil.copytree(run,scratch)
            rows = _rows(scratch/'ledger.jsonl')
            mutate(scratch,rows[i])
            (scratch/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in rows))
            seal = load_json(scratch/'seal.json')
            seal.pop('seal_id')
            seal['files'] = _files(scratch)
            write(scratch/'seal.json',{**seal,'seal_id':content_id(seal)})
            try:
                report_batch_execution(scratch)
            except ContractError as exc:
                require(reason in str(exc),f'unexpected rejection for {label}: {exc}')
                rejected[label] = str(exc)
            else:
                raise AssertionError(label+' passed with a fresh seal')

    def overflow(scratch,row):
        log = scratch/'logs'/sid/'sfb1-query.stdout'
        outcome = load_json(log)
        for key in ('auto','scalar'):
            outcome[key]['sum'][0] %= 2**32
        write(log,outcome)
        output = scratch/row['parts']['reductions']['path']
        result = load_json(output)
        result['sum'][0] %= 2**32
        write(output,result)
        row['parts']['reductions'] = _ref(scratch,output)
        row['sprintz_validation']['query'] = outcome

    def plaintext_mounted(_scratch,row):
        op, = [o for o in row['operations'] if o['operation']=='sfb1-query']
        op['input_mounts']['plaintext'] = {k:slot['original'][k] for k in ('sha256','bytes')}

    def missing_output(scratch,row):
        (scratch/row['parts'].pop('reductions')['path']).unlink()

    exercise('wrapped_32bit_sum','reductions, dispatch or refusal differs',overflow)
    exercise('hidden_plaintext_dependency','compressed-only query mount differs',plaintext_mounted)
    exercise('missing_reduction_product','product evidence differs',missing_output)
    require(report_batch_execution(run)==report,'control mutated original Sprintz run')
    return {'schema':'bmk.sprintz-reseal-controls/1','run_id':report['run_id'],'seal_id':report['seal_id'],'rejections':rejected}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
