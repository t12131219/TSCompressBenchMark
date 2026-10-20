#!/usr/bin/env python3
"""Replay hash-bound source evidence through the new Bench core and fresh oracles.

No timings here are performance measurements. Baseline corpus is an explicit
input, not an implicit qualification inherited from the independent release.
"""
from __future__ import annotations
import argparse
import ctypes as C
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time
import zlib

import numpy as np
from tsbench.build import artifact_path, sha
from tsbench.registry import Registry

ROOT = Path(__file__).resolve().parents[2]
METHODS = {1: 'chimp', 2: 'chimp32', 3: 'chimpn', 4: 'chimp128-no-index', 5: 'chimpn32',
           7: 'pmc-mr', 8: 'swing-filter', 9: 'swing-filter-disjoint', 10: 'swing-filter-disjoint-quantized'}
U8P = C.POINTER(C.c_uint8)
class Config(C.Structure):
    _fields_ = [('version', C.c_uint32), ('dtype', C.c_uint32), ('rank', C.c_uint32),
                ('order', C.c_uint32), ('shape', C.c_uint64 * 8), ('params', C.c_char_p), ('model', C.c_char_p)]
class Result(C.Structure):
    _fields_ = [('data', U8P), ('size', C.c_size_t), ('capacity', C.c_size_t), ('owner', C.c_void_p)]
class Server:
    def __init__(self, command):
        self.command = list(map(str, command))
        self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    def call(self, mode, method, data, count, history=128, epsilon=.1):
        self.proc.stdin.write(struct.pack('<IIIfII', mode, method, history, epsilon, count, len(data)) + data)
        self.proc.stdin.flush()
        header = self.proc.stdout.read(8)
        if len(header) != 8:
            raise RuntimeError(f'oracle terminated: {self.command}')
        status, count = struct.unpack('<II', header)
        result = self.proc.stdout.read(count)
        if len(result) != count:
            raise RuntimeError('short oracle response')
        return status, result
    def close(self):
        self.proc.stdin.close()
        assert self.proc.wait(timeout=20) == 0

def normalize(data, segments=False, points=False):
    data = bytearray(data)
    if segments:
        for at in range(0, len(data), 52):
            for offset in (16, 24, 32, 40):
                if np.isnan(struct.unpack_from('<d', data, at + offset)[0]):
                    struct.pack_into('<Q', data, at + offset, 0x7ff8000000000000)
            if np.isnan(struct.unpack_from('<f', data, at + 48)[0]):
                struct.pack_into('<I', data, at + 48, 0x7fc00000)
    if points:
        values = np.frombuffer(data, dtype=np.dtype([('t','<i8'),('v','<f4')]))
        bits = values['v'].view('<u4')
        bits[np.isnan(values['v'])] = 0x7fc00000
    return bytes(data)

def library(key):
    lib = C.CDLL(str(artifact_path(ROOT, key)))
    lib.tsbench_core_create.argtypes = [C.POINTER(Config), C.c_int, C.POINTER(C.c_void_p)]
    lib.tsbench_core_destroy.argtypes = [C.c_void_p]
    lib.tsbench_core_bound.argtypes = [C.c_void_p, U8P, C.c_size_t, C.POINTER(C.c_size_t)]
    for op in ('encode','decode'):
        getattr(lib, 'tsbench_core_' + op).argtypes = [C.c_void_p, U8P, C.c_size_t, U8P, C.c_size_t, C.POINTER(Result)]
    lib.tsbench_core_release.argtypes = [C.POINTER(Result)]
    lib.tsbench_core_error.argtypes = [C.c_void_p]; lib.tsbench_core_error.restype = C.c_char_p
    return lib

def operation(lib, raw, count, dtype, params, decoder=False):
    config = Config(1, dtype, 1, 0, (C.c_uint64 * 8)(count), json.dumps(params, sort_keys=True).encode(), None)
    handle, result = C.c_void_p(), Result()
    status = lib.tsbench_core_create(C.byref(config), int(decoder), C.byref(handle))
    if status:
        return status, b'', lib.tsbench_core_error(None).decode()
    source = (C.c_uint8 * max(1,len(raw))).from_buffer_copy(raw or b'\0')
    try:
        status = getattr(lib,'tsbench_core_' + ('decode' if decoder else 'encode'))(handle, source, len(raw), None, 0, C.byref(result))
        error = lib.tsbench_core_error(handle).decode()
        # Exercise owning API with no caller capacity; context destruction must
        # not invalidate returned bytes. Failures must not return partial output.
        lib.tsbench_core_destroy(handle); handle = None
        if status:
            assert not result.size and not result.owner
            return status, b'', error
        assert result.owner and result.size <= result.capacity
        return 0, C.string_at(result.data, result.size), ''
    finally:
        if handle:
            lib.tsbench_core_destroy(handle)
        lib.tsbench_core_release(C.byref(result))

def run(args):
    args.out.mkdir(parents=True, exist_ok=False)
    registry = Registry(ROOT)
    libs = {key: library(key) for key in [*METHODS.values(), 'chimp128']}
    cpp = Server([args.cli, 'server'])
    java = None
    if args.fresh_java:
        classes = args.out / 'java-classes'; classes.mkdir()
        sources = sorted((ROOT/'adapters/chimp_family/reference/oracle-src').rglob('*.java'))
        subprocess.run(['javac','-d',str(classes),*map(str,sources)],check=True,capture_output=True)
        java = Server(['java','-Xmx512m','-cp',classes,'Oracle'])
    def blob(digest):
        data = gzip.decompress((args.baseline/'blobs'/(digest+'.gz')).read_bytes())
        assert hashlib.sha256(data).hexdigest() == digest
        return data
    rows, skipped, stats = [], Counter(), Counter()
    started = time.monotonic()
    index_data = (args.baseline/'cases.jsonl').read_bytes()
    with (args.out/'cases.jsonl').open('w') as log:
        try:
            for line in index_data.splitlines():
                row = json.loads(line); m = row['method_id']; count = row['count']; n = row.get('history',128); eps = row.get('epsilon',.1)
                if m not in METHODS:
                    skipped['unrequested_method'] += 1; continue
                if row['status'] != 'PASS':
                    skipped['standalone_non_pass'] += 1; continue
                if m == 4 and n != 128:
                    skipped['no_index_profile_fixed_128'] += 1; continue
                data = blob(row['input_sha256'])
                if m >= 7:
                    points = np.frombuffer(data,dtype=[('t','<i8'),('v','<f4')])
                    if not np.array_equal(points['t'], np.arange(count)):
                        skipped['external_timestamps_outside_bench_profile'] += 1; continue
                    raw = points['v'].tobytes(); dtype = 9
                else:
                    dtype = 9 if m in (2,5) else 10
                    words = np.frombuffer(data,dtype='<u8')
                    raw = words.astype('<u4').tobytes() if dtype == 9 else data
                keys = [METHODS[m]] + (['chimp128'] if m == 3 and n == 128 else [])
                expected_frame = blob(row['frame_sha256'])
                expected_points = blob(row['source_decoded_sha256'])
                if java:
                    st, source = java.call(1,m,data,count,n,eps)
                    assert not st and normalize(source,segments=m>=7) == normalize(blob(row['source_sha256']),segments=m>=7), (row['case'],'fresh Java encode')
                    if m >= 7:
                        st, output = java.call(5,m,data,count,n,eps)
                        assert not st and normalize(output,points=True) == normalize(expected_points,points=True)
                for key in keys:
                    params = {'block_size':1048576} if m < 7 else {'epsilon':repr(eps),'quality_mode':'compatible'}
                    if key in ('chimpn','chimpn32'): params['history'] = n
                    params = registry.resolve_params(key, params)
                    st, frame, error = operation(libs[key],raw,count,dtype,params)
                    assert not st, (row['case'],key,error)
                    # Frozen C++ frame can have arithmetic NaN sign differences
                    # from Java. Lossless paths always compare every exact byte.
                    assert frame == expected_frame or (m>=7 and frame[:32]==expected_frame[:32] and normalize(frame[32:-4],segments=True)==normalize(expected_frame[32:-4],segments=True)), (row['case'],key,'frame')
                    assert zlib.crc32(frame[:-4]) == struct.unpack_from('<I',frame,len(frame)-4)[0]
                    if java and m < 7:
                        st, back = java.call(2,m,frame[32:-4],count,n,eps)
                        assert not st and back == data
                        # Fresh original raw -> complete frame -> Bench decoder.
                        source_frame = bytearray(frame[:32]);struct.pack_into('<Q',source_frame,24,len(source));source_frame += source;source_frame += struct.pack('<I',zlib.crc32(source_frame))
                        st, back, error = operation(libs[key],bytes(source_frame),count,dtype,{},True)
                        assert not st and back == raw, (row['case'],key,'fresh Java -> Bench',error)
                    st, back, error = operation(libs[key],expected_frame,count,dtype,{},True)
                    assert not st, (row['case'],key,'cold',error)
                    if m < 7:
                        assert back == raw
                        st, independent = cpp.call(4,m,frame,count,n,eps)
                        assert not st and independent == data
                    else:
                        expected_raw = np.frombuffer(expected_points,dtype=[('t','<i8'),('v','<f4')])['v'].tobytes()
                        def normalized_f32_bits(raw):
                            bits = np.frombuffer(raw, dtype='<u4').copy()
                            bits[np.isnan(bits.view('<f4'))] = 0x7fc00000
                            return bits
                        # Preserve signed zero and every finite f32 bit; only
                        # arithmetic NaN payload/sign is unspecified by Java.
                        assert np.array_equal(normalized_f32_bits(back), normalized_f32_bits(expected_raw))
                        st, independent = cpp.call(4,m,frame,count,n,eps)
                        assert not st and normalize(independent,points=True) == normalize(expected_points,points=True)
                        strict_params = {**params,'quality_mode':'strict_abs'}
                        st, strict_frame, error = operation(libs[key],raw,count,dtype,strict_params)
                        good = row.get('absolute_epsilon_pass',True)
                        assert (st == 0) == good, (row['case'],key,'strict',good,st,error)
                        if good: assert strict_frame == frame
                        else: stats['strict_quality_rejections'] += 1
                    item = {'case':row['case'],'key':key,'count':count,'kind':row['kind'],'method':m,'history':n,
                            'input_sha256':row['input_sha256'],'frame_sha256':hashlib.sha256(frame).hexdigest(),
                            'stored_source_replay':True,'fresh_java':bool(java),'cpp_cli_cold_decode':True,'status':'PASS'}
                    rows.append(item); log.write(json.dumps(item,separators=(',',':'))+'\n')
                    stats[key] += 1;stats['values'] += count
                if len(rows) and len(rows)%1000 == 0:
                    print('validated',len(rows),flush=True)
        finally:
            cpp.close()
            if java:java.close()
    assert index_data == (args.baseline/'cases.jsonl').read_bytes()
    report = {'schema':'tsbench.chimp-family-qualification/1','status':'PASS','cases':len(rows),'values':stats.pop('values'),
              'by_key':dict(stats),'skipped':dict(skipped),'selection':'requested methods, fixed no-index=128, implicit unit timestamp grid; explicit alias replay',
              'fresh_java':bool(java),'elapsed_seconds':time.monotonic()-started,
              'case_log_sha256':sha(args.out/'cases.jsonl'),'baseline_case_index_sha256':hashlib.sha256(index_data).hexdigest(),
              'baseline_verification_sha256':sha(args.baseline/'verification.json'),'cli_sha256':sha(args.cli),
              'tool_sha256':sha(Path(__file__)), 'artifacts':{key:{'path':str(artifact_path(ROOT,key)),'sha256':sha(artifact_path(ROOT,key))} for key in libs},
              'scope':'source differential, binding and cold decode correctness only; no formal throughput or inherited standalone gates'}
    (args.out/'qualification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--cli',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--fresh-java',action='store_true');run(p.parse_args())
