"""Bridge for the four stateless rw_* bindings, with explicit column framing."""
from __future__ import annotations

import ctypes as ct
import hashlib
import struct
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..errors import Unavailable
from ..registry import CapacityError, CodecError, CodecSpec, Registry, SourceDomainError

_MAGIC = b'TSBCRW1\0'


class Config(ct.Structure):
    _fields_ = [('rows',ct.c_uint64),('columns',ct.c_uint64),
                *[(key,ct.c_uint32) for key in ('a','b','c','d','seed','mode')],
                *[(key,ct.c_double) for key in ('x','y','z')],('model',ct.c_char_p)]


@lru_cache(maxsize=16)
def load_library(path: str, digest: str):
    del digest
    try:
        lib = ct.CDLL(path)
    except OSError as error:
        raise Unavailable(f'cannot load RW library {path}: {error}') from error
    lib.rw_version.argtypes = []
    lib.rw_version.restype = ct.c_uint32
    lib.rw_algorithm.argtypes = []
    lib.rw_algorithm.restype = ct.c_char_p
    ptr,size = ct.c_void_p,ct.c_size_t
    lib.rw_bound.argtypes = [ct.POINTER(Config),ptr,size,ct.POINTER(size),ptr,size]
    lib.rw_encode.argtypes = [ct.POINTER(Config),ptr,size,ptr,size,ct.POINTER(size),ptr,size]
    lib.rw_decode.argtypes = [ptr,size,ptr,size,ct.POINTER(size),ptr,size]
    for name in ('rw_bound','rw_encode','rw_decode'):
        getattr(lib,name).restype = ct.c_int
    return lib


class RwAbiBridge:
    def __init__(self, spec: CodecSpec, path: Path, digest: str):
        self.spec,self.key = spec,spec.key
        self.registry = Registry(spec.root)
        self.lib = load_library(str(path),digest)
        if self.lib.rw_version() != 1 or self.lib.rw_algorithm().decode() != self.key:
            raise CodecError(f'{self.key}: RW binary identity mismatch')
        self.last_native_ns = None
        self.last_native_timing = None
        self.last_input_identity = None

    def _config(self, rows: int, params: dict) -> Config:
        c = Config(rows,1,0,0,0,0,params.get('model_seed',0),0,0,0,0,b'')
        if self.key == 'abba':
            c.a,c.b,c.c,c.d = params['min_k'],params['max_k'],params['max_len'],params['norm']
            c.x,c.y,c.z = float(params['compression_tolerance']),float(params['digitization_tolerance']),float(params['scl'])
            c.mode = int(params['clustering'] == 'INCREMENTAL')
        elif self.key == 'fabba':
            c.a = params['max_len']
            c.x,c.y,c.z = float(params['tolerance']),float(params['alpha']),float(params['scl'])
        elif self.key == 'deepzip':
            c.a = params['lanes']
            record = self.spec.document['adapter']['models'][params['model_key']]
            model = self.spec.root / record['path']
            if not model.is_file() or hashlib.sha256(model.read_bytes()).hexdigest() != record['sha256']:
                raise Unavailable(f'{self.key}: model missing or hash differs')
            c.model = str(model).encode()
        elif self.key == 'dzip':
            c.mode = int(params['mode'] == 'COMBINED')
        return c

    def _call(self, operation: str, data: bytes, config=None, capacity=0):
        source = ct.create_string_buffer(data,max(1,len(data)))
        error = ct.create_string_buffer(2048)
        used = ct.c_size_t()
        if operation == 'bound':
            status = self.lib.rw_bound(ct.byref(config),source,len(data),ct.byref(used),error,len(error))
        else:
            output = ct.create_string_buffer(max(1,capacity))
            arguments = [source,len(data),output,capacity,ct.byref(used),error,len(error)]
            if operation == 'encode':
                arguments.insert(0,ct.byref(config))
            status = getattr(self.lib,'rw_'+operation)(*arguments)
        if status == 3:
            raise CapacityError(f'{self.key} {operation}: insufficient native capacity')
        if status:
            message = error.value.decode(errors='replace')
            raise CodecError(f'{self.key} {operation}: {message}')
        if operation == 'bound':
            if used.value > 2**31:
                raise CapacityError('RW bound exceeds 2 GiB bridge allocation budget')
            return used.value
        if used.value > capacity:
            raise CodecError('RW output exceeds caller capacity')
        return output.raw[:used.value]

    def encode(self, array: np.ndarray, params: dict | None = None) -> bytes:
        self.spec.validate_array(array)
        params = self.registry.resolve_params(self.key,params)
        if self.key == 'deepzip':
            alphabet = self.spec.document['adapter']['models'][params['model_key']]['alphabet_size']
            if np.any(array >= alphabet):
                raise SourceDomainError('DeepZip: MODEL_ALPHABET_UNSUPPORTED')
        columns = [array] if array.ndim == 1 else [array[:,index] for index in range(array.shape[1])]
        input_data = b''.join(np.ascontiguousarray(column).tobytes() for column in columns)
        self.last_input_identity = {
            'content_sha256': hashlib.sha256(input_data).hexdigest(), 'dtype': array.dtype.str,
            'shape': list(array.shape) if array.ndim == 1 else [len(columns),array.shape[0]],
            'layout': 'ROW_MAJOR_CONTIGUOUS' if array.ndim == 1 else 'COLUMN_COLLECTION_CONTIGUOUS',
            'nbytes': len(input_data), 'abi': 'rw-v1',
        }
        frames = []
        for column in columns:
            if self.key in {'abba','fabba'}:
                with np.errstate(all='ignore'):
                    residual = column[:-1] + (column[1:] - column[:-1]) - column[1:]
                    error = np.abs(residual) if self.key == 'abba' and params['norm'] == 1 else residual*residual
                if np.any(~np.isfinite(error)) or np.any(error > np.finfo(np.float64).eps):
                    raise SourceDomainError(f'{self.key}: SEGMENT_ENDPOINT_ARITHMETIC_UNSUPPORTED')
            if self.key == 'dzip' and np.unique(column).size == 9:
                raise SourceDomainError('DZip: MODEL_ALPHABET_UNSUPPORTED')
            data = np.ascontiguousarray(column).tobytes()
            config = self._config(column.size,params)
            bound = self._call('bound',data,config)
            frames.append(self._call('encode',data,config,bound))
        return _MAGIC + struct.pack('<I',len(frames)) + b''.join(struct.pack('<Q',len(frame)) for frame in frames) + b''.join(frames)

    def decode(self, payload: bytes, dtype, shape, params: dict | None = None) -> np.ndarray:
        dtype,shape = np.dtype(dtype),tuple(shape)
        self.registry.resolve_params(self.key,params)
        if len(shape) not in self.spec.ranks or dtype.str not in self.spec.dtypes or payload[:8] != _MAGIC or len(payload) < 12:
            raise CodecError('RW bridge frame/descriptor mismatch')
        count = struct.unpack_from('<I',payload,8)[0]
        expected_count = shape[1] if len(shape) == 2 else 1
        if count != expected_count or len(payload) < 12+count*8:
            raise CodecError('RW column table mismatch')
        lengths = struct.unpack_from('<'+'Q'*count,payload,12)
        at = 12+count*8
        columns = []
        for length in lengths:
            if length > len(payload)-at:
                raise CodecError('truncated RW column payload')
            decoded = self._call('decode',payload[at:at+length],capacity=shape[0]*dtype.itemsize)
            if len(decoded) != shape[0]*dtype.itemsize:
                raise CodecError('RW decoded byte count mismatch')
            columns.append(np.frombuffer(decoded,dtype=dtype).copy())
            at += length
        if at != len(payload):
            raise CodecError('trailing RW bridge bytes')
        return columns[0].reshape(shape) if len(shape) == 1 else np.column_stack(columns)
