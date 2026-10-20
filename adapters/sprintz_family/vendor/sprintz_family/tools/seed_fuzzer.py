from pathlib import Path
import ctypes as C,random,struct,hashlib
p=Path(__file__).resolve().parents[1];target=p/'tests/fuzz-seeds';target.mkdir(exist_ok=True)
class Conf(C.Structure):_fields_=[(k,C.c_uint32) for k in ['width','predictor','huffman','path','ndims']]
l=C.CDLL(str(p/'build/libsprintz.so'));l.sz_encode.argtypes=[C.POINTER(Conf),C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
r=random.Random(20261017);count=0
for bits in [8,16]:
 for fire in [0,1]:
  for h in [0,1]:
   for path in range(6):
    for d in [1,2,3,4,5,8,17,65,128]:
     for pattern in [0,1]:
      raw=bytes(r.randrange(256) if pattern else 0 for i in range(1024));c=Conf(bits,fire,h,path,d);out=C.create_string_buffer(10000);n=C.c_size_t()
      if l.sz_encode(C.byref(c),raw,len(raw),out,len(out),C.byref(n)):continue
      data=bytes([bits==16,fire,h,path,d-1])+struct.pack('<H',len(raw))+b'\0'+out.raw[:n.value]
      (target/hashlib.sha256(data).hexdigest()).write_bytes(data);count+=1
print('seeds',count)
