"""Genuine cuSZp 1D FIXED CUDA owners, host wire, and independent sessions.

Host encode/decode include transfers, completion, payload/wire checks and packing.
Device methods finish CUDA work and transfer output ownership; materialize is
explicit and separate. A caller includes session creation/close in an independent
object clock. No automatic device reset or CPU fallback is permitted.
"""
from __future__ import annotations
from contextlib import AbstractContextManager
import ctypes as ct
from dataclasses import dataclass
import hashlib
import json
from numbers import Real
from pathlib import Path
import struct
import numpy as np

KEY='cuszp-fixed-1d'
MAX_N=16777216
_PREFIX=struct.Struct('<4sBBBBQdQ32s')
HEADER_BYTES=_PREFIX.size+32


class GPUError(RuntimeError):
    def __init__(self,status,message):
        super().__init__(message);self.status=status
        self.classification={1:'error',2:'unsupported',3:'error',4:'error',5:'oom',6:'unavailable'}.get(status,'error')


class Info(ct.Structure):
    _fields_=[('struct_size',ct.c_uint32),('version',ct.c_uint32),('device',ct.c_uint32),('dtype',ct.c_uint32),
              ('count',ct.c_uint64),('error_bound',ct.c_double),('payload_bytes',ct.c_uint64),('scratch_bytes',ct.c_uint64),
              ('input_bytes',ct.c_uint64),('output_bytes',ct.c_uint64),('output_capacity_bytes',ct.c_uint64),
              ('owned_allocation_peak_bytes',ct.c_uint64),('device_event_ms',ct.c_double)]


def canonical_error_bound(dtype,error_bound):
    dtype=np.dtype(dtype)
    if dtype.str not in {'<f4','<f8'}:raise GPUError(2,'cuSZp supports little-endian float32/float64 only')
    if isinstance(error_bound,(bool,np.bool_)) or not isinstance(error_bound,Real):raise GPUError(2,'error bound must be a real numeric scalar, not boolean')
    value=float(error_bound)
    if not np.isfinite(value) or value<=0:raise GPUError(2,'error bound must be finite and positive')
    if dtype.itemsize==4:
        with np.errstate(over='ignore',under='ignore'):actual=np.float32(value)
        if float(actual)>value:actual=np.nextafter(actual,np.float32(0))
        value=float(actual)
    if not np.isfinite(value) or value<float(np.finfo(dtype).tiny):raise GPUError(2,'error bound is outside normal dtype domain')
    return value


def _capacity(n):return ((n+32767)//32768)*1024*125


def _payload_check(payload,n):
    table_bytes=((n+32767)//32768)*1024
    if len(payload)<table_bytes or len(payload)>_capacity(n):raise GPUError(1,'payload length outside FIXED capacity')
    table=payload[:table_bytes]
    if any(b>30 for b in table):raise GPUError(1,'invalid FIXED width')
    if any(table[(n+31)//32:]):raise GPUError(1,'nonzero padding-only FIXED width')
    if table_bytes+sum(4+4*b for b in table if b)!=len(payload):raise GPUError(1,'FIXED rate table/length mismatch')


def pack(payload,dtype,count,error_bound):
    dtype=np.dtype(dtype);code=dtype.itemsize
    eb=canonical_error_bound(dtype,error_bound)
    if type(count) is not int or not 0<count<=MAX_N:raise GPUError(2,'count must be an integer in the cuSZp domain')
    payload=bytes(payload);_payload_check(payload,count)
    prefix=_PREFIX.pack(b'CSP1',1,code,0,0,count,eb,len(payload),hashlib.sha256(payload).digest())
    return prefix+hashlib.sha256(prefix).digest()+payload


def unpack(wire):
    wire=bytes(wire)
    if len(wire)<HEADER_BYTES:raise GPUError(1,'truncated CSP1 metadata')
    prefix=wire[:_PREFIX.size]
    if hashlib.sha256(prefix).digest()!=wire[_PREFIX.size:HEADER_BYTES]:raise GPUError(1,'CSP1 metadata digest mismatch')
    magic,version,code,mode,reserved,n,eb,size,digest=_PREFIX.unpack(prefix)
    if (magic,version,mode,reserved)!=(b'CSP1',1,0,0) or code not in {4,8}:raise GPUError(1,'unsupported CSP1 header')
    dtype=np.dtype('<f'+str(code))
    if not 0<n<=MAX_N or canonical_error_bound(dtype,eb)!=eb:raise GPUError(1,'invalid CSP1 typed configuration')
    payload=wire[HEADER_BYTES:]
    if len(payload)!=size or hashlib.sha256(payload).digest()!=digest:raise GPUError(1,'CSP1 payload length/digest mismatch')
    _payload_check(payload,n)
    return {'dtype':dtype.str,'count':n,'error_bound':eb,'mode':'FIXED','payload_bytes':size},payload


@dataclass(frozen=True)
class Encoded:
    wire:bytes
    info:dict
    @property
    def metadata(self):return unpack(self.wire)[0]


class Library:
    def __init__(self,path=None,root=None,build_root=None):
        root=Path(root or Path(__file__).resolve().parents[4]).resolve()
        base=Path(build_root or root/'build/tsbench-gpu').resolve()
        index=json.loads((base/(KEY+'.index.json')).read_text()) if path is None else None
        self.path=Path(path or index['artifact']).resolve();self.build_record=Path(index['build_record']) if index else self.path.parent/'build.json'
        self.evidence=json.loads(self.build_record.read_text())
        if index and index['identity_sha256']!=self.evidence['identity_sha256']:raise GPUError(6,'GPU index differs from build identity')
        actual=hashlib.sha256(self.path.read_bytes()).hexdigest()
        if actual!=self.evidence['artifact_sha256']:raise GPUError(6,'GPU binary differs from build identity')
        for entry in self.evidence['identity']['sources']:
            try:digest=hashlib.sha256((root/entry['path']).read_bytes()).hexdigest()
            except OSError as error:raise GPUError(6,'GPU source dependency unavailable: '+entry['path']) from error
            if digest!=entry['sha256']:raise GPUError(6,'GPU source dependency changed: '+entry['path'])
        for entry in self.evidence['compiled_dependencies']+self.evidence['toolchain_files']+self.evidence['link_dependencies']+self.evidence['runtime_dependencies']:
            try:
                with Path(entry['path']).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            except OSError as error:raise GPUError(6,'GPU build dependency unavailable: '+entry['path']) from error
            if digest!=entry['sha256']:raise GPUError(6,'GPU build dependency changed: '+entry['path'])
        self.lib=ct.CDLL(str(self.path));p=ct.c_void_p;u=ct.c_uint64;i=ct.c_int;d=ct.c_double;t=ct.c_uint32;out=ct.POINTER(p)
        self.lib.tsgpu_abi_version.restype=t
        if self.lib.tsgpu_abi_version()!=1:raise GPUError(6,'GPU ABI mismatch')
        self.lib.tsgpu_last_error.restype=ct.c_char_p
        signatures={'device_json':[i,ct.POINTER(ct.c_char_p)],'diagnostics_json':[ct.POINTER(ct.c_char_p)],'create':[i,t,u,d,out],'close':[p],
                    'prepare_input':[i,t,u,d,p,u,out],'release_input':[p],'copy_input':[p,p,u],
                    'encode_host':[p,p,u,out],'encode_device':[p,p,out],
                    'install_payload':[i,t,u,d,p,u,out],'payload_info':[p,ct.POINTER(Info)],'copy_payload':[p,p,u],'release_payload':[p],
                    'decode_device':[p,p,out],'decoded_info':[p,ct.POINTER(Info)],'copy_decoded':[p,p,u],'release_decoded':[p]}
        for name,args in signatures.items():
            f=getattr(self.lib,'tsgpu_'+name);f.argtypes=args;f.restype=t
    def call(self,name,*args):
        status=getattr(self.lib,'tsgpu_'+name)(*args)
        if status:raise GPUError(status,self.lib.tsgpu_last_error().decode(errors='replace'))
    def device_info(self,device=0):
        text=ct.c_char_p();self.call('device_json',device,ct.byref(text));return json.loads(text.value)
    def diagnostics(self):
        text=ct.c_char_p();self.call('diagnostics_json',ct.byref(text));return json.loads(text.value)
    def info(self,owner,kind):
        result=Info();result.struct_size=ct.sizeof(result);self.call(kind+'_info',owner,ct.byref(result))
        return {name:getattr(result,name) for name,_ in result._fields_}
    def transferred_info(self,owner,kind):
        try:return self.info(owner,kind)
        except BaseException:
            self.call('release_'+kind,owner)
            raise


class _Owner(AbstractContextManager):
    kind=''
    def __init__(self,library,pointer,metadata,info=None):self.library=library;self.pointer=pointer;self.metadata=metadata;self.info=info or {}
    def _open(self):
        if not self.pointer.value:raise GPUError(1,'device owner already closed')
    def close(self):
        if self.pointer.value:
            pointer=self.pointer;self.pointer=ct.c_void_p();self.library.call('release_'+self.kind,pointer)
    def __exit__(self,*exc):self.close();return False


class DeviceInput(_Owner):
    kind='input'
    def materialize(self):
        self._open();array=np.empty(self.metadata['count'],dtype=self.metadata['dtype'])
        self.library.call('copy_input',self.pointer,ct.c_void_p(array.ctypes.data),array.nbytes);return array


class DevicePayload(_Owner):
    kind='payload'
    def materialize(self):
        self._open();storage=ct.create_string_buffer(self.metadata['payload_bytes'])
        self.library.call('copy_payload',self.pointer,storage,len(storage))
        wire=pack(storage.raw,self.metadata['dtype'],self.metadata['count'],self.metadata['error_bound'])
        return Encoded(wire,self.info)


class DeviceDecoded(_Owner):
    kind='decoded'
    def materialize(self):
        self._open();array=np.empty(self.metadata['count'],dtype=self.metadata['dtype'])
        self.library.call('copy_decoded',self.pointer,ct.c_void_p(array.ctypes.data),array.nbytes);return array


def prepare_device_input(array,error_bound,device=0,library=None):
    library=library or Library();array=np.asarray(array)
    if array.ndim!=1 or not array.flags.c_contiguous:raise GPUError(2,'cuSZp input must be contiguous 1D')
    eb=canonical_error_bound(array.dtype,error_bound);p=ct.c_void_p()
    library.call('prepare_input',device,array.dtype.itemsize,array.size,eb,ct.c_void_p(array.ctypes.data),array.nbytes,ct.byref(p))
    return DeviceInput(library,p,{'dtype':array.dtype.str,'count':array.size,'error_bound':eb,'device':device})


def install_device_payload(wire,device=0,library=None):
    library=library or Library();meta,payload=unpack(wire);storage=ct.create_string_buffer(payload);p=ct.c_void_p()
    library.call('install_payload',device,np.dtype(meta['dtype']).itemsize,meta['count'],meta['error_bound'],storage,len(payload),ct.byref(p))
    return DevicePayload(library,p,{**meta,'device':device},library.transferred_info(p,'payload'))


class Session(AbstractContextManager):
    def __init__(self,dtype,count,error_bound,device=0,library=None):
        if type(count) is not int or not 0<count<=MAX_N:raise GPUError(2,'count must be an integer in the cuSZp domain')
        self.library=library or Library();dtype=np.dtype(dtype);eb=canonical_error_bound(dtype,error_bound)
        self.metadata={'dtype':dtype.str,'count':int(count),'error_bound':eb,'device':device};self.pointer=ct.c_void_p()
        self.library.call('create',device,dtype.itemsize,count,eb,ct.byref(self.pointer))
    def close(self):
        if self.pointer.value:
            p=self.pointer;self.pointer=ct.c_void_p();self.library.call('close',p)
    def __exit__(self,*exc):self.close();return False
    def _open(self):
        if not self.pointer.value:raise GPUError(1,'GPU session already closed')
    def encode_device(self,original):
        self._open();original._open();p=ct.c_void_p();self.library.call('encode_device',self.pointer,original.pointer,ct.byref(p));info=self.library.transferred_info(p,'payload')
        return DevicePayload(self.library,p,{**self.metadata,'payload_bytes':info['payload_bytes']},info)
    def encode_host(self,array):
        self._open();array=np.asarray(array)
        if array.ndim!=1 or not array.flags.c_contiguous or array.dtype.str!=self.metadata['dtype'] or array.size!=self.metadata['count']:raise GPUError(2,'host input differs from session typed object')
        p=ct.c_void_p();self.library.call('encode_host',self.pointer,ct.c_void_p(array.ctypes.data),array.nbytes,ct.byref(p));info=self.library.transferred_info(p,'payload')
        with DevicePayload(self.library,p,{**self.metadata,'payload_bytes':info['payload_bytes']},info) as owner:return owner.materialize()
    def decode_device(self,payload):
        self._open();payload._open();p=ct.c_void_p();self.library.call('decode_device',self.pointer,payload.pointer,ct.byref(p));info=self.library.transferred_info(p,'decoded')
        return DeviceDecoded(self.library,p,self.metadata,info)
    def decode_host(self,wire):
        self._open()
        with install_device_payload(wire,self.metadata['device'],self.library) as payload:
            with self.decode_device(payload) as result:return result.materialize(),result.info
