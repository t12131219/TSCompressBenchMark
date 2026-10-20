#!/usr/bin/env python3
"""Save object/CLI and native products under new implementation identities."""
from pathlib import Path
import sys,json,hashlib,subprocess
import numpy as np
from tsbench import native
from tsbench.data import TimeSeriesObject,array_order
from tsbench.config import DEFAULT_TASK,DEFAULT_PROFILE,DEFAULT_EXECUTION
from tsbench.registry import Registry
from tsbench.schemes import ObjectScheme,decode_once
ROOT=Path(__file__).resolve().parents[2]
KEYS=('sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman')
def main(out):
 out.mkdir(parents=True,exist_ok=False);objects=[];batches=[];native.ensure_driver(ROOT,ROOT/'build/tsbench')
 for key in KEYS:
  for dtype in ('|u1','<i2'):
   params=Registry(ROOT).resolve_params(key,{'path':1})
   for order in ('C','F'):
    a=np.array(np.arange(771).reshape(257,3)*17,dtype=dtype,order=order);before=a.tobytes(order=order);obj=TimeSeriesObject({'V':a},{'topology':'SYNCHRONOUS_MTS','roles':{'V':'V'}})
    for partition in ('whole','channel-chunks'):
     folder=out/f'{key}-{np.dtype(dtype).str[1:]}-{order}-{partition}';folder.mkdir();method={'id':key,'codec':key,'params':params}
     if partition=='channel-chunks':method.update(channelwise=True,chunk_rows=127)
     encoded=ObjectScheme(method,ROOT).encode_once(obj);restored=decode_once(encoded,ROOT).components['V']
     assert restored.tobytes(order=order)==before==a.tobytes(order=order) and restored.shape==a.shape and array_order(restored)==order
     wire=folder/'object.tsb';wire.write_bytes(encoded.wire)
     command=[sys.executable,'-m','tsbench','decode',str(wire),str(folder/'decoded'),'--asset-root',str(ROOT),'--build-root',str(ROOT/'build/tsbench')]
     subprocess.run(command,check=True,capture_output=True,text=True,timeout=60)
     desc=json.loads((folder/'decoded/object.json').read_text());cold=np.load(folder/'decoded'/desc['components']['V'],allow_pickle=False);assert cold.tobytes(order=order)==before
     objects.append({'case':folder.name,'status':'PASS','wire_bytes':len(encoded.wire),'input_sha256':hashlib.sha256(before).hexdigest(),'independent_cli_decode':True})
   a=np.asarray(np.arange(771).reshape(257,3)*17,dtype=dtype);obj=TimeSeriesObject({'V':a},{'roles':{'V':'V'}});method={'id':key,'codec':key,'params':params}
   for boundary in ('native_core','native_api'):
    for lifecycle in ('prepared','fresh_request'):
     task={**DEFAULT_TASK,'boundary':boundary,'lifecycle':lifecycle};support=native.capability(method,obj,task,DEFAULT_PROFILE,ROOT,ROOT/'build/tsbench');assert support['supported'],support
     m=native.NativeMeasurement(method,task,{**DEFAULT_EXECUTION,'native_loops':2,'native_warmup_loops':1,'native_batch_memory_mb':16,'timeout_s':60},support,ROOT,ROOT/'build/tsbench');m.prepare(obj);row,_=m.measure(obj,independent=True,artifact_dir=out/f'{key}-{np.dtype(dtype).str[1:]}-{boundary}-{lifecycle}')
     assert row['verification']['passed'] and row['verification']['validated_operations']==3 and row['independent_recovery']['passed'];payload=Path(row['artifact_path']).read_bytes();assert payload[:4]==b'SZF1' and row['codec_complete_bytes']==len(payload)
     batches.append(row)
 result={'status':'PASS','objects':objects,'object_count':len(objects),'native_combinations':len(batches),'native_products':sum(len(r['native_products']) for r in batches),'native_rows':batches,'scope':'correctness and durable cold recovery; not formal throughput'}
 (ROOT/'docs/sprintz_integration/object-native-qualification.json').write_text(json.dumps(result,indent=2)+'\n');print({k:v for k,v in result.items() if k not in ('objects','native_rows')})
if __name__=='__main__':main(Path(sys.argv[1]).resolve())
