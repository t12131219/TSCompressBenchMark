#!/usr/bin/env python3
"""Supplementary legacy C1 payload audit; main native_core audit is separate."""
import argparse
import json
from pathlib import Path
import shutil
import numpy as np
from audit_lzbench_current import ROOT,KEYS,IDS,Oracle,digest,dump,sha
from tsbench.bridges import create_bridge
from tsbench.registry import Registry


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--campaign',type=Path,required=True);a=parser.parse_args()
    campaign=a.campaign.resolve();output=campaign/'c1';output.mkdir(exist_ok=False)
    shutil.copy2(__file__,output/'audit_script.py')
    reference_file=campaign/'oracle_reference.json'
    library=json.loads(reference_file.read_text())['path'] if reference_file.exists() else campaign/'oracle/liblzbench_oracle.so'
    oracle=Oracle(library);reg=Registry(ROOT)
    inputs=json.loads((campaign/'inputs.json').read_text())
    selected=[r for r in inputs if r['name'] in ['zero-0','pattern-257','random-4096','pattern-65537'] or r['name'].startswith('real-')]
    rows=[]
    for key in KEYS:
        bridge=create_bridge(ROOT,key);params=reg.resolve_params(key)
        for case in selected:
            data=Path(case['path']).read_bytes();source=np.frombuffer(data,dtype='u1').copy();n=len(data)
            where=output/key/case['name'];where.mkdir(parents=True)
            row={'codec':key,'case':case['name'],'input_bytes':n,'input_sha256':digest(data)}
            try:
                encoded=bridge.encode(source,params);restored=bridge.decode(encoded,source.dtype,source.shape,params).tobytes()
                row.update(c1_roundtrip=restored==data,bytes=len(encoded),sha256=digest(encoded));assert restored==data
                (where/'c1-payload.bin').write_bytes(encoded)
                if key in IDS:
                    level=params.get('compression_level',0);param=params.get('window_bits',0) if key=='brotli-stream' else 0
                    expected=oracle.call(key,False,data,n,level,param)
                    row['lzbench_complete_equal']=encoded==expected
                    if key=='lz4-frame':
                        row['cross_reference']='SUPPLEMENTARY_LZ4_FRAME_API'
                        row['reference_decode_c1']=oracle.extra('audit_lz4_frame_decode',encoded,n)==data
                        cross=oracle.extra('audit_lz4_frame',data,n,level)
                    else:
                        row['cross_reference']='LZBENCH_WRAPPER'
                        row['reference_decode_c1']=oracle.call(key,True,encoded,n,level,param)==data
                        cross=expected
                    row['c1_decode_reference']=bridge.decode(cross,source.dtype,source.shape,params).tobytes()==data
                    assert row['reference_decode_c1'] and row['c1_decode_reference']
                else:row['lzbench_comparator']='NOT_REGISTERED'
                core_case=campaign/'cases'/key/'default'/case['name']/'bench_row.json'
                core=json.loads(core_case.read_text());payload=Path(core['artifact_path']).read_bytes()
                row['c1_equals_native_complete']=encoded==payload
                if key.startswith('lzss'):row['c1_equals_native_without_length']=encoded==payload[8:]
            except Exception as e:row['error']=str(e)
            rows.append(row)
        print(key, len([r for r in rows if r['codec']==key]),'errors',sum('error' in r for r in rows if r['codec']==key),flush=True)
    dump(output/'results.json',rows)
    dump(output/'summary.json',{'script_sha256':sha(__file__),'cases':len(rows),'errors':[r for r in rows if 'error'in r],
        'per_codec':{k:{'cases':len([r for r in rows if r['codec']==k]),'lzbench_complete_equal':sum(r.get('lzbench_complete_equal',False) for r in rows if r['codec']==k),
             'c1_equals_native_complete':sum(r.get('c1_equals_native_complete',False) for r in rows if r['codec']==k)} for k in KEYS}})

    if any('error' in r for r in rows):raise SystemExit(1)

if __name__=='__main__':main()
