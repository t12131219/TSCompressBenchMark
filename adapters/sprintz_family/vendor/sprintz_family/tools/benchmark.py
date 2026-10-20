from pathlib import Path
import ctypes as C,time,statistics,json,hashlib,platform
p=Path(__file__).resolve().parents[1];data=(p/'tests/data/national_illness_counts.u16le').read_bytes()
class Conf(C.Structure):_fields_=[(k,C.c_uint32) for k in ['width','predictor','huffman','path','ndims']]
l=C.CDLL(str(p/'build/libsprintz.so'));l.sz_encode.argtypes=[C.POINTER(Conf),C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)];l.sz_decode.argtypes=[C.POINTER(Conf),C.c_void_p,C.c_size_t,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
rows=[]
for fire in [0,1]:
 for h in [0,1]:
  for path in [0,1]:
   c=Conf(16,fire,h,path,3);out=C.create_string_buffer(300000);de=C.create_string_buffer(len(data));z=C.c_size_t();k=C.c_size_t();times={}
   for op in ['encode','decode']:
    runs=[]
    for batch in range(16):
     begin=time.perf_counter_ns()
     for i in range(40):
      rc=l.sz_encode(C.byref(c),data,len(data),out,len(out),C.byref(z)) if op=='encode' else l.sz_decode(C.byref(c),out,z.value,len(data),de,len(de),C.byref(k));assert rc==0
     elapsed=(time.perf_counter_ns()-begin)/40
     if batch:runs.append(elapsed)
    times[op+'_median_ns']=statistics.median(runs);times[op+'_MiB_s']=len(data)/statistics.median(runs)*1e9/2**20
   assert de.raw==data;rows.append({'config':[16,fire,h,path,3],'raw_bytes':len(data),'encoded_bytes':z.value,**times})
r={'scope':'STANDALONE_API_ONLY_NOT_FORMAL','method':'ctypes call + staging + checked native codec + output commit; 1 warmup batch,15 measured batches x40 operations,median; no disk IO timed; no CPU pinning; payload sizes exclude out-of-band config','platform':platform.platform(),'input_sha256':hashlib.sha256(data).hexdigest(),'library_sha256':hashlib.sha256((p/'build/libsprintz.so').read_bytes()).hexdigest(),'results':rows}
(p/'evidence/performance.json').write_text(json.dumps(r,indent=2)+'\n');print('performance protocol recorded',len(rows))
