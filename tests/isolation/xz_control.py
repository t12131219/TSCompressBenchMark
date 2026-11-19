#!/usr/bin/env python3
"""Compare the XZ baseline worker with the locked legacy lzbench entry."""
import ctypes as c
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import uuid
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest
from tsbench.planner.corpus_windows import bind_window, read_tv_window
from tsbench.runtime import create_build_lock, resolve_worker

METHOD = 'xz-baseline'
MAGIC = b'BMKXZ\x00\x01\x00'
HEADER = struct.Struct('<8sIQIQ')
LIMIT = 65536
CORPUS_ID = 'a9904b1ce2068186e1c3e47eccf406e030d9e73973defe50d0508c91334929b3'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class NativeXZ:
    def __init__(self, path):
        lib = c.CDLL(str(path))

        def function(name, restype, *args):
            func = getattr(lib, name)
            func.restype, func.argtypes = restype, args
            return func

        self.destroy = function('ln_destroy', None, c.c_void_p)
        name = function('ln_codec_name', c.c_char_p, c.c_int)
        self.codec = 7  # LN_XZ in the locked public header
        assert name(self.codec) == b'xz'
        create = function('ln_create', c.c_int, c.c_int, c.c_int, c.POINTER(c.c_void_p))
        self.bound = function('ln_compress_bound', c.c_size_t, c.c_int, c.c_size_t)
        self.compress = function('ln_compress', c.c_int, c.c_void_p, c.c_void_p, c.c_size_t,
                                 c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t))
        self.ctx = c.c_void_p()
        assert create(self.codec, 6, c.byref(self.ctx)) == 0 and self.ctx.value

    def pack(self, source):
        bound = self.bound(self.codec, len(source))
        assert bound > 0
        payload = c.create_string_buffer(bound)
        size = c.c_size_t()
        assert self.compress(self.ctx, source, len(source), payload, bound, c.byref(size)) == 0
        assert 0 < size.value <= bound
        return payload.raw[:size.value]

    def close(self):
        self.destroy(self.ctx)


def main(worker, module, library, report):
    corpus = 'datasets/manifests/first-batch-real-v2.json'
    window = bind_window(ROOT, corpus, CORPUS_ID, {'dataset':'mpi-beutenberg-weather', 'column':'co2',
                                                        'partition':'test', 'offset':0, 'count':1029})
    _, weather = read_tv_window(ROOT, window)
    entropy = hashlib.shake_256(b'tsbench/xz-baseline-boundary-v1').digest(LIMIT + 1)
    cases = [('empty', 2, 1, b''), ('limit-minus', 2, 1, entropy[:-2]),
             ('limit-exact', 2, 1, entropy[:-1]), ('weather-co2-tail', 10, 8, weather)]
    with tempfile.TemporaryDirectory(prefix='tsbench-xz-moved-') as tmp:
        root = Path(tmp)
        for folder in ('catalog', 'schemas', 'plugins', 'include', 'cmake', 'tools', 'third_party'):
            shutil.copytree(ROOT / folder, root / folder)
        for path in (worker, module, library):
            shutil.copy2(path, root / path.name)
        lock = create_build_lock(root, worker.name, {METHOD: module.name})
        binding = resolve_worker(root, lock, METHOD, {})
        native = NativeXZ(root / library.name)

        def run(op, *args, opts='{}', check=True):
            return run_worker(root, [binding['worker'], op, binding['library'], METHOD, opts, *map(str, args)], check=check)

        def fail(op, args, code, outputs, **kwargs):
            result = run(op, *args, check=False, **kwargs)
            assert result.returncode == 3 and f'plugin status {code}:'.encode() in result.stderr, result
            assert not any((root / name).exists() for name in outputs)

        def wrap(dtype, count, schema, payload):
            return HEADER.pack(MAGIC, dtype, count, len(schema), len(payload)) + schema + payload

        observations, payloads = [], {}
        try:
            for tag, dtype, width, raw in cases:
                count = len(raw) // width
                schema = canonical_bytes({'dtype':dtype, 'case':tag})
                (root / 'source').write_bytes(raw)
                (root / 'schema').write_bytes(schema)
                expected = native.pack(raw)
                enc = json.loads(run('encode', dtype, 'source', 'schema', 'frame').stdout)
                assert enc == dict(backend='ln-xz-baseline', mode='batch', threads=1, fallback=False,
                                   blocks=int(bool(raw)), check='none', operation='encode', preset=6)
                frame = (root / 'frame').read_bytes()
                assert frame == wrap(dtype, count, schema, expected)
                (root / 'source').unlink()
                (root / 'schema').unlink()
                desc, dec = map(json.loads, run('decode', 'frame', 'decoded', 'schema-out').stdout.splitlines())
                assert desc == {'dtype':dtype, 'count':count}
                assert dec == {**{k:v for k,v in enc.items() if k != 'preset'}, 'operation':'decode'}
                assert (root / 'decoded').read_bytes() == raw and (root / 'schema-out').read_bytes() == schema
                for name in ('frame', 'decoded', 'schema-out'):
                    (root / name).unlink()
                payloads[tag] = expected
                observations.append({'case':tag,'dtype':dtype,'count':count,'logical_bytes':len(raw),'source_sha256':sha(raw),
                                     'schema_sha256':sha(schema),'schema_bytes':len(schema),'envelope_header_bytes':HEADER.size,
                                     'frame_sha256':sha(frame),'frame_bytes':len(frame),'native_payload_sha256':sha(expected),
                                     'native_payload_bytes':len(expected),'byte_exact_recovery':True,'encode':enc,'decode':dec,
                                     **({'window':window} if tag == 'weather-co2-tail' else {})})
        finally:
            native.close()
        assert not native.bound(native.codec, LIMIT+1)
        (root / 'source').write_bytes(entropy)
        (root / 'schema').write_bytes(b'{}')
        fail('encode', (2, 'source', 'schema', 'frame'), 7, ('frame',))
        fail('encode', (2, 'source', 'schema', 'frame'), 3, ('frame',), opts='{"threads":2}')
        payload = payloads['weather-co2-tail']
        empty = payloads['empty']
        wrong_check = bytearray(payload)
        wrong_check[7] = wrong_check[-3] = 1
        struct.pack_into('<I',wrong_check,8,zlib.crc32(wrong_check[6:8]))
        struct.pack_into('<I',wrong_check,len(payload)-12,zlib.crc32(wrong_check[-8:-2]))
        index_at = len(payload) - 12 - 4 * (1 + struct.unpack_from('<I',payload,len(payload)-8)[0])
        bad_index = bytearray(payload)
        bad_index[index_at+1] ^= 1
        invalid = [('truncated-stream',payload[:-1],1029,5), ('concatenated-streams',empty+payload,1029,5),
                   ('stream-padding',payload+b'\0'*4,1029,5), ('misdeclared-count',payload,1028,5),
                   ('out-of-scope-check',wrong_check,1029,5), ('bad-index',bad_index,1029,5),
                   ('oversize-declared-output',payload,LIMIT//8+1,7),
                   ('oversize-payload',bytes(native.bound(native.codec,LIMIT)+1),1029,7)]
        for tag, bad, count, status in invalid:
            (root / 'frame').write_bytes(wrap(10,count,b'{}',bad))
            fail('decode', ('frame','decoded','schema-out'), status, ('decoded','schema-out'))
    doc = {'schema':'bmk.m0-xz-control/1','diagnostic_id':uuid.uuid4().hex,'probe_sha256':digest(Path(__file__)),
           'build':lock,'method':METHOD,'formal_performance':False,'formal_qualification':False,'cases':observations,
           'rejections':{'limit-plus':7,'unknown-option':3,**{tag:status for tag,_,_,status in invalid}}}
    with tempfile.TemporaryDirectory(dir=report.parent, prefix='.xz-report-') as tmp:
        staged = Path(tmp) / 'evidence.json'
        staged.write_bytes(canonical_bytes(doc) + b'\n')
        staged.replace(report)


if __name__ == '__main__':
    main(*(Path(arg).resolve() for arg in sys.argv[1:]))
