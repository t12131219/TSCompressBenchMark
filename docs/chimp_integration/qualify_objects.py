#!/usr/bin/env python3
"""Chimp object/CLI and durable native product checks; no throughput qualification."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from tsbench import native
from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE,DEFAULT_EXECUTION
from tsbench.data import TimeSeriesObject,array_order
from tsbench.schemes import ObjectScheme,decode_once
from tsbench.registry import Registry
from tsbench.quality_metadata import extract

ROOT=Path(__file__).resolve().parents[2]
KEYS=('chimp','chimp32','chimp128','chimpn','chimp128-no-index','chimpn32','pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized')
FILTERS=set(KEYS[6:])
def digest(b):return hashlib.sha256(b).hexdigest()
def main(out):
    out.mkdir(parents=True,exist_ok=False);rows=[];batches=[];reg=Registry(ROOT)
    for key in KEYS:
        dtype=reg.get(key).dtypes[0];lossy=key in FILTERS;params=reg.resolve_params(key,{'epsilon':'.125'} if lossy else {})
        for order in ('C','F'):
            a=np.array(np.arange(771).reshape(257,3)/8,dtype=dtype,order=order)
            if not lossy:a[0,0]=-0.;a[1,1]=np.inf
            before=a.tobytes(order=order);obj=TimeSeriesObject({'V':a},{'topology':'SYNCHRONOUS_MTS','roles':{'V':'V'}})
            for partition in ('whole','channel-chunks'):
                name=f'{key}-{order}-{partition}';folder=out/name;folder.mkdir()
                method={'id':key,'codec':key,'params':params}
                if partition=='channel-chunks':method.update(channelwise=True,chunk_rows=127)
                encoded=ObjectScheme(method,ROOT).encode_once(obj)
                restored=decode_once(encoded,ROOT).components['V']
                assert a.tobytes(order=order)==before and restored.shape==a.shape and restored.dtype==a.dtype and array_order(restored)==order
                if lossy:assert np.max(np.abs(restored.astype('f8')-a.astype('f8')))<=.125
                else:assert restored.tobytes(order=order)==before
                wire=folder/'object.tsb';wire.write_bytes(encoded.wire)
                command=[sys.executable,'-m','tsbench','decode',str(wire.resolve()),str((folder/'decoded').resolve()),'--asset-root',str(ROOT),'--build-root',str(ROOT/'build/tsbench')]
                done=subprocess.run(command,check=True,capture_output=True,text=True,timeout=120)
                desc=json.loads((folder/'decoded/object.json').read_text());independent=np.load(folder/'decoded'/desc['components']['V'],allow_pickle=False)
                assert independent.tobytes(order=order)==restored.tobytes(order=order)
                settings=extract(encoded.wire) if lossy else None
                if lossy:assert len(settings['parts'])==(9 if partition=='channel-chunks' else 1)
                rows.append({'case':name,'status':'PASS','dtype':dtype,'order':order,'shape':list(a.shape),'wire_bytes':len(encoded.wire),'wire_sha256':digest(encoded.wire),'input_sha256':digest(before),'independent_cli_decode':True,'command':command,'quality_metadata':settings})
        for boundary in ('native_core','native_api'):
            for lifecycle in ('prepared','fresh_request'):
                a=np.arange(257,dtype=dtype)/8;obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}});method={'id':key,'codec':key,'params':params}
                task={**DEFAULT_TASK,'boundary':boundary,'lifecycle':lifecycle}
                if lossy:task.update(fidelity='bounded_abs',error_bound=.125)
                execution={**DEFAULT_EXECUTION,'native_loops':2,'native_warmup_loops':1,'native_batch_memory_mb':16,'timeout_s':60}
                native.ensure_driver(ROOT,ROOT/'build/tsbench');support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench');assert support['supported'],support
                m=native.NativeMeasurement(method,task,execution,support,ROOT,ROOT/'build/tsbench');m.prepare(obj)
                row,wire=m.measure(obj,independent=True,artifact_dir=out/'native-products')
                assert row['verification']['passed'] and row['verification']['validated_operations']==3 and row['independent_recovery']['passed']
                batches.append({'key':key,'boundary':boundary,'lifecycle':lifecycle,'row':row})
        print(key,'PASS',flush=True)
    report={'status':'PASS','objects':len(rows),'batches':len(batches),'validated_native_products':sum(x['row']['verification']['validated_operations'] for x in batches),'object_cases':rows,'native_batches':batches,'tool_sha256':digest(Path(__file__).read_bytes()),'scope':'qualification-sized operations only, not formal performance'}
    (out/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();main(a.out.resolve())
