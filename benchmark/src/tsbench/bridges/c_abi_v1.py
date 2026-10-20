"""Small, explicit bridge for the preserved tscb_* ABI version 1.

Input envelopes are native codec contracts. They are not the benchmark wire
format. An encoder and a decoder never share a native context.
"""
from __future__ import annotations

import ctypes as ct
import json
import hashlib
import math
import struct
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..errors import Unavailable
from ..registry import CapacityError, CodecError, CodecSpec, Registry, SourceDomainError, UnsupportedError


class Buffer(ct.Structure):
    _fields_ = [('data',ct.c_void_p),('capacity_bytes',ct.c_uint64),('used_bytes',ct.c_uint64),
                ('dtype',ct.c_uint32),('rank',ct.c_uint32),('shape',ct.c_uint64*8),
                ('strides_bytes',ct.c_int64*8),('alignment_bytes',ct.c_uint64),
                ('ownership',ct.c_uint32),('reserved',ct.c_uint32)]


class NativeTiming(ct.Structure):
    _fields_ = [('struct_size',ct.c_uint32),('version',ct.c_uint32),
                ('native_encode_wall_ns',ct.c_uint64),('native_decode_wall_ns',ct.c_uint64)]


CHIMP_FAMILY = {'chimp', 'chimp32', 'chimp128', 'chimpn', 'chimp128-no-index', 'chimpn32',
                'pmc-mr', 'swing-filter', 'swing-filter-disjoint', 'swing-filter-disjoint-quantized'}
CHIMP_METHODS = dict(zip(('chimp','chimp32','chimp128','chimpn','chimp128-no-index','chimpn32',
                         'pmc-mr','swing-filter','swing-filter-disjoint','swing-filter-disjoint-quantized'),
                        (1,2,3,3,4,5,7,8,9,10)))
SPRINTZ_FAMILY = {'sprintz-delta','sprintz-fire','sprintz-delta-huffman','sprintz-fire-huffman'}
_COLUMN_KEYS = CHIMP_FAMILY | {'alp','alp-rd','chimp','chimp128','elf','elf-plus','elf-star','self-star',
                'serf-qt','serf-xor','neats-lossless-i64','leats-lossless-i64','zfp-accuracy-1d'}
_KINDS = {'elf-plus':3,'self-star':4,'elf':6,'elf-star':7}
_CONFIG_KEYS = {
    'lz4-frame': ('block_checksum','block_mode','block_size_id','compression_level','content_checksum'),
    'zstd-frame': ('compression_level','content_checksum'),
    'brotli-stream': ('compression_level','window_bits'),
    'bzip2-stream': ('compression_level',), 'deflate-zlib': ('compression_level','window_bits'),
    'xz-stream': ('compression_level',),
    'snappy-raw': ('compression_level','content_checksum'),
    'lzsse2-raw': ('compression_level','content_checksum'),
    'lzsse8-raw': ('compression_level','content_checksum'),
    'lzss-raw': ('ei','ej','initial_byte'),
    'lzss-dipperstein-c': ('initial_byte','length_bits','match_finder','offset_bits'),
}
_ZERO_FINISH = _COLUMN_KEYS | SPRINTZ_FAMILY | {'huff0','fse',
                'simdcomp-u32','lzsse2-raw','lzsse8-raw','lzss-raw','lzss-dipperstein-c'}


def byte_buffer(storage, *, capacity: int, used: int = 0) -> Buffer:
    address = ct.addressof(storage)
    alignment = 1
    while alignment < 64 and address % (alignment*2) == 0:
        alignment *= 2
    shape = (ct.c_uint64*8)(used)
    strides = (ct.c_int64*8)(1)
    return Buffer(address,capacity,used,11,1,shape,strides,alignment,0,0)


def array_buffer(array: np.ndarray, *, output: bool = False) -> Buffer:
    address = array.ctypes.data
    alignment = 1
    while alignment < 64 and address % (alignment*2) == 0:
        alignment *= 2
    codes = {'|i1':1,'|u1':2,'<i2':3,'<u2':4,'<i4':5,'<u4':6,'<i8':7,'<u8':8,'<f4':9,'<f8':10}
    strides = (array.dtype.itemsize,) if array.ndim == 1 and array.size == 0 else array.strides
    return Buffer(address,array.nbytes,0 if output else array.nbytes,codes[array.dtype.str],array.ndim,
                  (ct.c_uint64*8)(*array.shape),(ct.c_int64*8)(*strides),alignment,0,0)


@lru_cache(maxsize=96)
def load_library(path: str, digest: str):
    del digest  # Cache identity changes whenever the build's byte hash changes.
    try:
        lib = ct.CDLL(path)
    except OSError as error:
        raise Unavailable(f'cannot load native codec {path}: {error}') from error
    lib.tscb_get_abi_version.argtypes = []
    lib.tscb_get_abi_version.restype = ct.c_uint32
    if lib.tscb_get_abi_version() != 1:
        raise CodecError('native ABI version mismatch')
    lib.tscb_create.argtypes = [ct.c_char_p,ct.c_uint64,ct.POINTER(ct.c_void_p)]
    lib.tscb_create.restype = ct.c_uint32
    lib.tscb_destroy.argtypes = [ct.c_void_p]
    lib.tscb_destroy.restype = ct.c_uint32
    lib.tscb_reset.argtypes = [ct.c_void_p,ct.c_uint32]
    lib.tscb_reset.restype = ct.c_uint32
    lib.tscb_compress_bound.argtypes = [ct.c_void_p,ct.POINTER(Buffer),ct.POINTER(ct.c_uint64)]
    lib.tscb_compress_bound.restype = ct.c_uint32
    for name in ('tscb_compress','tscb_decompress'):
        getattr(lib,name).argtypes = [ct.c_void_p,ct.POINTER(Buffer),ct.POINTER(Buffer)]
        getattr(lib,name).restype = ct.c_uint32
    lib.tscb_finalize.argtypes = [ct.c_void_p,ct.POINTER(Buffer)]
    lib.tscb_finalize.restype = ct.c_uint32
    for name in ('tscb_get_manifest_json','tscb_get_last_error'):
        getattr(lib,name).argtypes = ([ct.c_void_p] if name.endswith('last_error') else []) + [ct.POINTER(ct.c_char_p),ct.POINTER(ct.c_uint64)]
        getattr(lib,name).restype = ct.c_uint32
    if hasattr(lib,'tscb_set_native_timing'):
        lib.tscb_set_native_timing.argtypes = [ct.c_void_p,ct.c_uint32]
        lib.tscb_set_native_timing.restype = ct.c_uint32
        lib.tscb_get_native_timing.argtypes = [ct.c_void_p,ct.POINTER(NativeTiming)]
        lib.tscb_get_native_timing.restype = ct.c_uint32
    return lib


class CAbiBridge:
    def __init__(self, spec: CodecSpec, path: Path, digest: str):
        spec.require_enabled()
        self.spec = spec
        self.key = spec.key
        self.registry = Registry(spec.root)
        self.lib = load_library(str(path),digest)
        self.last_native_ns: int | None = None
        self.last_native_timing: dict | None = None
        self.last_input_identity: dict | None = None
        pointer,length = ct.c_char_p(),ct.c_uint64()
        status = self.lib.tscb_get_manifest_json(ct.byref(pointer),ct.byref(length))
        if status or not pointer:
            raise CodecError(f'{self.key}: missing native manifest')
        self.native_manifest = json.loads(ct.string_at(pointer,length.value))
        expected = 'simdcomp-source-u32' if self.key == 'simdcomp-u32' else self.key
        if self.native_manifest.get('algorithm') != expected:
            raise CodecError(f'{self.key}: native algorithm identity differs')
        if self.key in CHIMP_FAMILY and (self.native_manifest.get('implementation') != 'chimp-family-cpp-scalar-v1'
                or self.native_manifest.get('frame') != 'CFP1'):
            raise CodecError(f'{self.key}: stale Chimp library; rebuild the family binding')
        if self.key in SPRINTZ_FAMILY and (self.native_manifest.get('implementation') != 'sprintz-native-20261017-api-v1' or self.native_manifest.get('frame') != 'SZF1'):
            raise CodecError(f'{self.key}: stale Sprintz library; rebuild the native port binding')
        if spec.document['adapter']['factory'] == 'ALP_SAFE_V1_CTYPES':
            if (self.native_manifest.get('implementation') != 'cwida-alp-native-safe-v1'
                    or self.native_manifest.get('frame') != 'ALPRW001'):
                raise CodecError(f'{self.key}: stale ALP library; rebuild the safe-v1 binding')

    def _config(self, params: dict) -> bytes:
        if self.key in CHIMP_FAMILY | SPRINTZ_FAMILY:
            return json.dumps({'algorithm': self.key, **params}, sort_keys=True, separators=(',', ':')).encode()
        if self.key in _CONFIG_KEYS:
            config = {name:params[name] for name in _CONFIG_KEYS[self.key]}
            if self.key == 'lz4-frame':
                config['block_mode'] = int(config['block_mode'] == 'LINKED')
        elif self.key == 'simdcomp-u32':
            config = {name:params[name] for name in ('api','isa','starting_point')}
            config['coding'] = 'PLAIN'
        else:
            config = {'algorithm':self.key}
            if self.key in ('neats-lossless-i64','leats-lossless-i64'):
                config['max_bpc'] = params['max_bpc']
        return json.dumps(config,sort_keys=True,separators=(',',':')).encode()

    def _check(self, status: int, handle, operation: str) -> None:
        if not status:
            return
        pointer,length = ct.c_char_p(),ct.c_uint64()
        message = ''
        if handle.value and not self.lib.tscb_get_last_error(handle,ct.byref(pointer),ct.byref(length)) and pointer:
            message = ct.string_at(pointer,length.value).decode(errors='replace')
        detail = f'{self.key} {operation} status={status}: {message}'
        if status == 3:
            raise CapacityError(detail)
        if operation == 'compress' and (status == 2 or self.key in _KINDS and any(word in message.lower() for word in ('source','nan','decimal','lossless','significance','erasure','beta'))):
            raise SourceDomainError(detail)
        if status == 2:
            raise UnsupportedError(detail)
        raise CodecError(detail)

    @contextmanager
    def _session(self, params: dict, operation: str):
        handle = ct.c_void_p()
        config = self._config(params)
        status = self.lib.tscb_create(config,len(config),ct.byref(handle))
        try:
            self._check(status,handle,'create')
            if not handle.value:
                raise CodecError(f'{self.key}: create returned a null handle')
            self._check(self.lib.tscb_reset(handle,0),handle,'reset')
            self.last_native_ns = None
            self.last_native_timing = None
            timing_enabled = params.get('native_timing',False) and hasattr(self.lib,'tscb_set_native_timing')
            if timing_enabled:
                timing_enabled = self.lib.tscb_set_native_timing(handle,1) == 0
            yield handle
            if timing_enabled:
                timing = NativeTiming(ct.sizeof(NativeTiming),1,0,0)
                if not self.lib.tscb_get_native_timing(handle,ct.byref(timing)):
                    self.last_native_ns = int(timing.native_encode_wall_ns if operation == 'encode' else timing.native_decode_wall_ns)
                    self.last_native_timing = {'encode_ns':int(timing.native_encode_wall_ns),'decode_ns':int(timing.native_decode_wall_ns)}
        finally:
            if handle.value:
                self.lib.tscb_destroy(handle)

    def _input(self, array: np.ndarray, params: dict) -> bytes:
        n = array.shape[0]
        m = array.shape[1] if array.ndim == 2 else 1
        width = array.dtype.itemsize
        payload = array.T.copy(order='C').tobytes() if self.key in _COLUMN_KEYS and array.ndim == 2 else array.tobytes(order='C')
        if self.key in CHIMP_FAMILY:
            return struct.pack('<4sBBHQ', b'CFI1', width, CHIMP_METHODS[self.key], m, n) + payload
        if self.key in ('alp','alp-rd'):
            return struct.pack('<4sBBHQ',b'TAI1',width,0,m,n)+payload
        if self.key in _KINDS:
            return struct.pack('<4sBBHIQ',b'RWI1',width,_KINDS[self.key],m,params['block_size'],n)+payload
        if self.key.startswith('serf-'):
            if self.key == 'serf-xor' and width == 4 and params.get('adjust_digit',0) != 0:
                raise UnsupportedError('Serf-XOR float32 requires adjust_digit=0')
            return struct.pack('<4sBBHIQdq',b'SRI1',width,0,m,params['block_size'],n,float(params['error_bound']),params.get('adjust_digit',0))+payload
        if self.key in ('neats-lossless-i64','leats-lossless-i64'):
            return struct.pack('<4sBBHI',b'NTI1',width,0,m,n)+payload
        if self.key == 'zfp-accuracy-1d':
            requested = float(params['error_bound'])
            _,exponent = math.frexp(requested)
            if math.ldexp(1.0,exponent-1) <= 0:
                raise UnsupportedError('zfp error bound underflows its actual tolerance')
            return struct.pack('<4sBBHQd',b'ZFI1',width,0,m,n,requested)+payload
        if self.key in SPRINTZ_FAMILY:
            return struct.pack('<4sBBHQ',b'SZI1',width,0,m,array.size)+payload
        return payload

    def encode(self, array: np.ndarray, params: dict | None = None) -> bytes:
        self.spec.validate_array(array)
        params = self.registry.resolve_params(self.key,params)
        array = np.ascontiguousarray(array)
        data = self._input(array,params)
        self.last_input_identity = {
            'content_sha256': hashlib.sha256(data).hexdigest(),
            'dtype': array.dtype.str if self.key == 'simdcomp-u32' else '|u1',
            'shape': list(array.shape) if self.key == 'simdcomp-u32' else [len(data)],
            'layout': 'ROW_MAJOR_CONTIGUOUS' if self.key == 'simdcomp-u32' else 'NATIVE_ENVELOPE_SOA_BYTES' if self.key in _COLUMN_KEYS else 'NATIVE_ENVELOPE_ROW_MAJOR_BYTES' if self.key in SPRINTZ_FAMILY else 'CONTIGUOUS_BYTES',
            'nbytes': len(data), 'abi': 'tscb-c-v1',
        }
        source_storage = ct.create_string_buffer(data,max(1,len(data)))
        source = array_buffer(array) if self.key == 'simdcomp-u32' else byte_buffer(source_storage,capacity=len(data),used=len(data))
        with self._session(params,'encode') as handle:
            bound = ct.c_uint64()
            self._check(self.lib.tscb_compress_bound(handle,ct.byref(source),ct.byref(bound)),handle,'bound')
            if bound.value > 2**31:
                raise UnsupportedError('native bound exceeds 2 GiB bridge allocation budget')
            storage = ct.create_string_buffer(max(1,bound.value))
            output = byte_buffer(storage,capacity=bound.value)
            if self.key == 'simdcomp-u32':
                output.shape[0] = output.capacity_bytes
            self._check(self.lib.tscb_compress(handle,ct.byref(source),ct.byref(output)),handle,'compress')
            if output.used_bytes > output.capacity_bytes:
                raise CodecError('native encoder exceeded output capacity')
            encoded = storage.raw[:output.used_bytes]
            if self.key in _ZERO_FINISH:
                finish_storage = ct.create_string_buffer(1)
                finish = byte_buffer(finish_storage,capacity=0)
            else:
                finish_storage = ct.create_string_buffer(max(1,bound.value))
                finish = byte_buffer(finish_storage,capacity=bound.value)
            self._check(self.lib.tscb_finalize(handle,ct.byref(finish)),handle,'finalize')
            if finish.used_bytes > finish.capacity_bytes:
                raise CodecError('native Finish exceeded output capacity')
            encoded += finish_storage.raw[:finish.used_bytes]
            return encoded

    def decode(self, payload: bytes, dtype, shape, params: dict | None = None) -> np.ndarray:
        dtype = np.dtype(dtype)
        shape = tuple(shape)
        if self.key in CHIMP_FAMILY:
            expected = (dtype.itemsize, CHIMP_METHODS[self.key], shape[1] if len(shape) == 2 else 1, shape[0])
            if len(payload) < 16 or payload[:4] != b'CFS1' or struct.unpack_from('<BBHQ', payload, 4) != expected:
                raise CodecError(f'{self.key}: column shape/dtype differs from requested descriptor')
        if self.key in SPRINTZ_FAMILY:
            if len(payload) < 24 or payload[:4] != b'SZF1' or payload[4] != dtype.itemsize or struct.unpack_from('<H',payload,8)[0] != (shape[1] if len(shape)==2 else 1) or struct.unpack_from('<I',payload,12)[0] != math.prod(shape)*dtype.itemsize:
                raise CodecError(f'{self.key}: Sprintz frame geometry differs from requested descriptor')
        result = np.empty(shape,dtype=dtype)
        self.spec.validate_array(result) if self.key not in {'abba','fabba'} else None
        params = self.registry.resolve_params(self.key,params)
        storage = ct.create_string_buffer(payload,max(1,len(payload)))
        source = byte_buffer(storage,capacity=len(payload),used=len(payload))
        output_storage = ct.create_string_buffer(max(1,result.nbytes))
        output = array_buffer(result,output=True) if self.key == 'simdcomp-u32' else byte_buffer(output_storage,capacity=result.nbytes)
        with self._session(params,'decode') as handle:
            self._check(self.lib.tscb_decompress(handle,ct.byref(source),ct.byref(output)),handle,'decompress')
            if output.used_bytes != result.nbytes:
                raise CodecError(f'{self.key}: decoded {output.used_bytes} bytes; expected {result.nbytes}')
            if self.key != 'simdcomp-u32':
                flat = np.frombuffer(output_storage.raw[:result.nbytes],dtype=dtype)
                if self.key in _COLUMN_KEYS and len(shape) == 2:
                    result = flat.reshape(shape[1],shape[0]).T.copy(order='C')
                else:
                    result = flat.reshape(shape).copy()
            return result
