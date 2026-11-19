#!/usr/bin/env python3
"""Reject mode/base, native terminal and restore evidence edits after re-sealing a scratch copy."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _ref, _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.pcodec_intmult import is_intmult


def main(run):
    parent = report_batch_execution(run)
    plan = load_json(run/'plan.json')
    slots = {s['name']:i for i,s in enumerate(plan['slots']) if is_intmult(s)}
    outcomes = {}

    def write(path,data):
        path.write_bytes(canonical_bytes(data)+b'\n')

    def reject(name,case,expected,change):
        with tempfile.TemporaryDirectory(prefix='tsbench-intmult-reseal-') as tmp:
            copy = Path(tmp)/'run'
            shutil.copytree(run,copy)
            rows = _rows(copy/'ledger.jsonl')
            change(copy,rows[slots[case]])
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in rows))
            seal = load_json(copy/'seal.json')
            seal.pop('seal_id')
            seal['files'] = _files(copy)
            write(copy/'seal.json',{**seal,'seal_id':content_id(seal)})
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(expected in str(exc),f'wrong IntMult failure: {exc}')
                outcomes[name] = str(exc)
            else:
                raise AssertionError(f'{name} survived resealing')

    def lose_exact_base(copy,row):
        ref = row['parts']['frame']
        path = copy/ref['path']
        frame = bytearray(path.read_bytes())
        wrapped = 6+(6+(frame[6]&63)+1+7)//8
        frame[wrapped+6] ^= 0x10  # LSB of base follows 4-bit mode
        path.write_bytes(frame)
        row['parts']['frame'] = ref = _ref(copy,path)
        row['operations'][1]['input_mounts']['frame'] = {k:ref[k] for k in ('bytes','sha256')}

    def omit_footer(copy,row):
        path = copy/'logs'/row['product_slot']/'intmult-decode.stdout'
        data = load_json(path)
        data['spans'].pop()
        row['intmult']['decode']['spans'].pop()
        write(path,data)

    def forge_reject(copy,row):
        path = copy/'logs'/row['product_slot']/'intmult-encode.stdout'
        row['intmult']['encode']['output_pointer_null'] = False
        write(path,row['intmult']['encode'])

    def add_input(_copy,row):
        row['operations'][1]['input_mounts'].update(row['operations'][0]['input_mounts'])

    reject('round_wide_wire_base','wide-base','emitted mode or exact wire base differs',lose_exact_base)
    reject('omit_terminal_footer_read','high-entropy','metadata or footer drain differs',omit_footer)
    reject('hide_invalid_output_pointer','float-input','encode or rejection transcript differs',forge_reject)
    reject('add_oracle_to_decoder','multiples','mount only the standalone frame',add_input)
    require(report_batch_execution(run)==parent,'control changed original IntMult run')
    return {'schema':'bmk.intmult-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':outcomes}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
