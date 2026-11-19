#!/usr/bin/env python3
"""Decode the primary slot's exact compressed inputs with the separately built portable DSO."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_worker_support import run_worker
from tsbench.assets import canonical_bytes, digest, load_json
from tsbench.planner.huff0 import REPORT
from tsbench.qualification.huff0_portable import portable_cases


def decode(library, observer, primary_out, output):
    primary_path = primary_out/REPORT
    primary = load_json(primary_path)
    rows = []
    with tempfile.TemporaryDirectory(prefix='tsbench-huff0-portable-') as tmp:
        sandbox = Path(tmp)
        for binary in (library,observer):
            shutil.copy2(binary,sandbox/binary.name)
        for idx,case in enumerate(portable_cases(primary,primary_out)):
            kind,name,_,artifacts,data,model,model_bytes,expected,_ = case
            case_dir = sandbox/str(idx)
            case_dir.mkdir()
            if model_bytes is None:
                args = ['fec-decode']
            else:
                (case_dir/'model').write_bytes(model_bytes)
                args = ['table-decode','model']
            for i,body in enumerate(data):
                (case_dir/f'in-{i}').write_bytes(body)
                args.extend((f'in-{i}',f'out-{i}'))
            result = run_worker(case_dir,[str(sandbox/observer.name),*args],library_dir=sandbox)
            observed = [digest(case_dir/f'out-{i}') for i in range(len(data))]
            assert observed == expected, f'Huff0 portable recovery differs: {name}'
            rows.append({'kind':kind,'case':name,'artifacts':artifacts,'model':model,
                         'restored_sha256':observed,'native':json.loads(result.stdout)})
    output.write_bytes(canonical_bytes({'schema':'bmk.huff0-portable-decode/1','primary_report_sha256':digest(primary_path),
        'bundle_id':primary['bundle_id'],'driver_sha256':digest(Path(__file__)),
        'binaries':{p.name:digest(p) for p in (library,observer)},'formal_qualification':False,'rows':rows})+b'\n')


if __name__ == '__main__':
    decode(*(Path(p).resolve() for p in sys.argv[1:]))
