#!/usr/bin/env python3
"""Reject modified access and stream outputs after rebuilding the evidence seal in scratch."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _ref, _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.titchy_execution import LOADED, RANGE
from tsbench.planner.titchy_stream import METHOD as STREAM_METHOD


def main(run):
    parent = report_batch_execution(run)
    plan = load_json(run/'plan.json')
    ix = {s['method']:i for i,s in enumerate(plan['slots']) if s['method'] in {LOADED,RANGE,STREAM_METHOD}}
    outcomes = {}

    def write(p,d):
        p.write_bytes(canonical_bytes(d)+b'\n')

    def exercise(name,method,expected,change):
        with tempfile.TemporaryDirectory(prefix='tsbench-titchy-reseal-') as t:
            work = Path(t)/'run'
            shutil.copytree(run,work)
            rows = _rows(work/'ledger.jsonl')
            change(work,rows[ix[method]])
            (work/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in rows))
            seal = load_json(work/'seal.json')
            seal.pop('seal_id')
            seal['files'] = _files(work)
            write(work/'seal.json',{**seal,'seal_id':content_id(seal)})
            try:
                report_batch_execution(work)
            except ContractError as exc:
                require(expected in str(exc), 'wrong Titchy reseal rejection: '+str(exc))
                outcomes[name] = str(exc)
            else:
                raise AssertionError(name+' passed with a new seal')

    def loadlog(work,r,label):
        path = work/'logs'/r['product_slot']/(label+'.stdout')
        return path,load_json(path)

    def read_budget(work,row):
        path,d = loadlog(work,row,'loaded')
        r = d['reads'][1]['range']
        r['requested_bytes'] -= 8
        r['successful_bytes'] -= 8
        write(path,d)
        row['titchy_access']['loaded'] = d

    def hide_corruption(work,row):
        path,d = loadlog(work,row,'range')
        d['statuses']['stateless_unrelated_bad_pair'] = 0
        write(path,d)
        row['titchy_access']['stateless'] = d

    def corrupt_answer(work,row):
        path = work/row['parts']['answer']['path']
        d = load_json(path)
        d['access']['range'][0] ^= 1
        write(path,d)
        row['parts']['answer'] = _ref(work,path)

    def extra_mount(_work,row):
        op = row['operations'][-1]
        op['input_mounts']['extra'] = op['input_mounts']['backing']

    exercise('modify_repeated_read_budget',LOADED,'repeated immutable reader ledger differs',read_budget)
    exercise('hide_outside_range_corruption',RANGE,'stateless range value or validation status differs',hide_corruption)
    exercise('rewrite_range_result',LOADED,'access result or accounting differs',corrupt_answer)
    exercise('mount_undeclared_input',RANGE,'mount only its immutable backing',extra_mount)
    if STREAM_METHOD in ix:
        def alter_part(work,row,key,change):
            path = work/row['parts'][key]['path']
            path.write_bytes(change(path.read_bytes()))
            ref = row['parts'][key] = _ref(work,path)
            row['operations'][1]['input_mounts'][key] = {k:ref[k] for k in ('bytes','sha256')}

        def forged_emission(work,row):
            p,d = loadlog(work,row,'packet-encode')
            d['emitted_after_push'][0] += 1
            row['titchy_stream']['emitted_after_push'][0] += 1
            row['titchy_stream']['first_packet_after_samples'] += 1
            write(p,d)

        def extra_stream_input(_work,row):
            row['operations'][1]['input_mounts'].update(row['operations'][0]['input_mounts'])

        exercise('change_config',STREAM_METHOD,'stream parameters or logical count differ',
                 lambda w,r:alter_part(w,r,'config',lambda b:b[:-1]+b'\1'))
        exercise('truncate_last_packet',STREAM_METHOD,'stream packet extent differs',
                 lambda w,r:alter_part(w,r,'archive',lambda b:b[:-1]))
        exercise('forge_prefinish_emission',STREAM_METHOD,'encoder transcript differs',forged_emission)
        exercise('mount_source_at_decode',STREAM_METHOD,'inputs are not separated',extra_stream_input)
    require(report_batch_execution(run)==parent,'control modified the original Titchy run')
    return {'schema':'bmk.titchy-access-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':outcomes}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
