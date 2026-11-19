#!/usr/bin/env python3
"""Re-seal forged ALP condition/counter/mount observations; semantic audit must reject."""
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from tsbench.api import report_batch_execution
from tsbench.application.batch_execution import _files
from tsbench.application.smoke import _rows
from tsbench.assets import ContractError, canonical_bytes, content_id, load_json, require
from tsbench.planner.alp_decode import is_decode


def write(path,row):
    path.write_bytes(canonical_bytes(row)+b'\n')


def main(run):
    parent = report_batch_execution(run)
    indices = {s['fixture']['name']:i for i,s in enumerate(load_json(run/'plan.json')['slots']) if is_decode(s)}
    outcomes = {}

    def reseal(name,fixture,expected,mutate):
        with tempfile.TemporaryDirectory(prefix='tsbench-alp-decode-reseal-') as tmp:
            copy = Path(tmp)/'run'
            shutil.copytree(run,copy)
            ledger = _rows(copy/'ledger.jsonl')
            row = ledger[indices[fixture]]
            mutate(copy/'logs'/row['product_slot'],row)
            (copy/'ledger.jsonl').write_bytes(b''.join(canonical_bytes(r)+b'\n' for r in ledger))
            seal = load_json(copy/'seal.json')
            del seal['seal_id']
            seal['files'] = _files(copy)
            write(copy/'seal.json',{**seal,'seal_id':content_id(seal)})
            try:
                report_batch_execution(copy)
            except ContractError as exc:
                require(expected in str(exc),f'wrong ALP reseal denial: {exc}')
                outcomes[name] = str(exc)
            else:
                raise AssertionError(f'{name} survived resealing')

    def edit(logs,row,request,change):
        path = logs/(request+'.stdout')
        doc = load_json(path)
        change(doc)
        write(path,doc)
        row['decode_backends']['requests'][request]['native'] = doc

    def erase512(logs,row):
        edit(logs,row,'falp-avx512bw',lambda d:d['caps'].__setitem__(4,[0,0]))

    def rewrite_availability_as_work(logs,row):
        edit(logs,row,'falp-avx512bw',lambda d:d.update(written=1 if d['status'] else 0))

    def fake_decimal(logs,row):
        edit(logs,row,'falp-auto',lambda d:d['counts'].__setitem__(d['effective'] % 3,2))

    def leak(_logs,row):
        row['operations'][1]['input_mounts']['raw'] = row['operations'][0]['input_mounts']['raw']

    reseal('drop_compiled_avx512bw','f64-mixed-decimal-raw','lost compiled AVX512BW',erase512)
    expect = 'native rejection differs' if parent['obligation_evidence']['9/decode-backends/avx512bw_decimal_with_effective_dispatch']['state']=='pending_supported_runtime' else 'native dispatch or branch counters differ'
    reseal('substitute_written_for_execution','f64-mixed-decimal-raw',expect,rewrite_availability_as_work)
    reseal('claim_decimal_work_on_rd','f64-rd-only','native dispatch or branch counters differ',fake_decimal)
    reseal('mount_original_with_frame','f64-mixed-decimal-raw','mount only the shared frame',leak)
    require(report_batch_execution(run)==parent,'ALP negative controls modified original run')
    return {'schema':'bmk.alp-decode-reseal/1','run_id':parent['run_id'],'seal_id':parent['seal_id'],'rejections':outcomes}


if __name__=='__main__':
    sys.stdout.buffer.write(canonical_bytes(main(Path(sys.argv[1]).resolve(strict=True)))+b'\n')
