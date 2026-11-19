#!/usr/bin/env python3
"""Targeted validation of selection 11: standalone worker and native state APIs."""
from contextlib import contextmanager
import ctypes as c
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest, load_json
from tsbench.planner.pcodec import (CONFIG, C_NATIVE, DEFAULTS, HEADER, MAGIC, SOURCE, TRAFFIC, TYPES, identity,
                                    intmult_inputs, page_spans, plan_pcodec)
from tsbench.qualification.pcodec import verify_pcodec
from tsbench.runtime import create_build_lock, resolve_worker

PC_INVALID, PC_CORRUPT, PC_UNSUPPORTED, PC_LIMIT = 1, 4, 5, 6
PTR, SIZE, INT = c.c_void_p, c.c_size_t, c.c_int
PP, PSIZE, PINT = c.POINTER(PTR), c.POINTER(SIZE), c.POINTER(INT)


class Buffer(c.Structure):
    _fields_ = [('data', PTR), ('size', SIZE)]


class PageConfig(c.Structure):
    _fields_ = [(name, INT) for name in ('level', 'mode', 'delta', 'order', 'quant_k', 'enable_8_bit')] + [
        ('int_base', c.c_uint64), ('float_base', c.c_double), ('max_page_n', SIZE)]


class BatchConfig(c.Structure):
    _fields_ = [(name,INT) for name in ('level','mode','delta','quant_k')] + [('base',c.c_double),('chunk_n',SIZE)]


def bind(lib, name, types, restype=INT):
    fn = getattr(lib, name)
    fn.argtypes, fn.restype = types, restype
    return fn


class Native:
    def __init__(self, path):
        self.lib = lib = c.CDLL(str(path))
        self.available = bind(lib, 'pc_source_backend_available', ())
        self.free = bind(lib, 'pc_free', [PTR], None)
        self.source = bind(lib, 'pc_compress', [PTR, SIZE, INT, PTR, PP, PSIZE])
        self.native = bind(lib, 'pc_compress_native', [PTR, SIZE, INT, PTR, PP, PSIZE])
        self.decode = bind(lib, 'pc_decompress_bounded', [PTR, SIZE, INT, SIZE, PP, PSIZE])
        self.intmult = bind(lib, 'pc_compress_intmult', [PTR, SIZE, INT, c.c_uint64, INT, INT, SIZE, PP, PSIZE])
        self.default = bind(lib, 'pc_default_config', (), BatchConfig)
        self.rust_default = bind(lib, 'pcs_default_config', (), PageConfig)
        self.rust_encode = bind(lib, 'pcs_compress', [PTR, SIZE, INT, c.POINTER(PageConfig), c.POINTER(Buffer)])
        self.rust_decode = bind(lib, 'pcs_decompress', [PTR, SIZE, INT, SIZE, c.POINTER(Buffer), PSIZE])
        self.rust_free = bind(lib, 'pcs_buffer_free', [PTR, SIZE], None)
        assert self.available() == 1

    def encode_source_reference(self, data, count, dtype):
        default = self.default()
        assert {k:getattr(default,k) for k in DEFAULTS} == DEFAULTS
        cfg = self.rust_default()
        cfg.level, cfg.mode, cfg.delta = default.level, default.mode, default.delta
        cfg.quant_k, cfg.float_base, cfg.int_base = default.quant_k, default.base, 0
        cfg.max_page_n, cfg.enable_8_bit = default.chunk_n, 1
        out = Buffer()
        try:
            assert self.rust_encode(data,count,dtype,c.byref(cfg),c.byref(out)) == 0
            return c.string_at(out.data,out.size)
        finally:
            self.rust_free(out.data,out.size)

    def decode_source_reference(self, payload, dtype, count, width):
        out, decoded = Buffer(), SIZE()
        try:
            assert self.rust_decode(payload,len(payload),dtype,count,c.byref(out),c.byref(decoded)) == 0
            assert decoded.value == count and out.size == count*width
            return c.string_at(out.data,out.size) if out.size else b''
        finally:
            self.rust_free(out.data,out.size)

    def result(self, fn, *args, status=0, width=1):
        p, count = PTR(), SIZE()
        try:
            rc = fn(*args, c.byref(p), c.byref(count))
            assert rc == status, (fn.__name__, rc, status)
            if rc:
                assert not p and count.value == 0
                return None
            assert p
            return c.string_at(p, count.value * width)
        finally:
            self.free(p)


class Pages:
    def __init__(self, lib, prefix):
        self.prefix = prefix
        def b(name, types, restype=INT):
            return bind(lib, prefix + '_' + name, types, restype)
        PB = c.POINTER(Buffer)
        self.default = b('default_config', (), PageConfig)
        self.chunk = b('chunk_new', [PTR, SIZE, INT, c.POINTER(PageConfig), PSIZE, SIZE, PP])
        self.encode_meta = b('chunk_header_meta', [PTR, PB])
        self.encode_page = b('chunk_page', [PTR, SIZE, PB])
        self.encode_counts = b('chunk_page_counts', [PTR, PB])
        self.enc_describe = b('chunk_describe', [PTR, PB])
        self.dec_describe = b('decoder_describe', [PTR, PB])
        self.destroy_chunk = b('chunk_destroy', [PTR], None)
        self.open = b('wrapped_open', [PTR, SIZE, INT, PP])
        self.file_open = b('file_open', [PTR, SIZE, INT, SIZE, PP])
        self.start = b('wrapped_start_page', [PTR, PTR, SIZE, SIZE, SIZE])
        self.read = b('read', [PTR, SIZE, PB, PSIZE, PINT])
        self.destroy_decoder = b('decoder_destroy', [PTR], None)
        self.free = b('buffer_free', [PTR, SIZE], None)

    @contextmanager
    def handle(self, fn, destroy, *args, status=0):
        p = PTR()
        try:
            rc = fn(*args, c.byref(p))
            assert rc == status and bool(p) == (rc == 0), (fn.__name__, rc, status)
            yield p
        finally:
            destroy(p)

    def output(self, fn, *args):
        buf = Buffer()
        try:
            assert fn(*args, c.byref(buf)) == 0, fn.__name__
            assert bool(buf.data) or not buf.size
            return c.string_at(buf.data, buf.size) if buf.size else b''
        finally:
            self.free(buf.data, buf.size)

    def step(self, p, cap, width, allowed=(0,)):
        buf, n, end = Buffer(), SIZE(), INT()
        try:
            rc = self.read(p, cap, c.byref(buf), c.byref(n), c.byref(end))
            assert rc in allowed, (self.prefix, rc, allowed)
            if rc:
                assert not buf.data and not buf.size and not n.value and not end.value
                return b'', 0, False, rc
            assert buf.size == n.value * width and (buf.data or not buf.size)
            return c.string_at(buf.data, buf.size) if buf.size else b'', n.value, bool(end.value), 0
        finally:
            self.free(buf.data, buf.size)

    def drain(self, p, cap, width, count):
        data, sizes = [], []
        for _ in range(count // cap + 3):
            raw, n, done, _ = self.step(p, cap, width)
            data.append(raw); sizes.append(n)
            if done:
                assert sum(sizes) == count
                return b''.join(data), sizes
        raise AssertionError('native decoder did not reach terminal state')


def rejects(root, invoke, path, statuses, check_outputs):
    r = invoke(*path, check=False)
    seen = [i for i in statuses if f'plugin status {i}:'.encode() in r.stderr]
    assert r.returncode == 3 and len(seen) == 1, r
    assert not any((root / p).exists() for p in check_outputs)
    return seen[0]


def batch_case(root, invoke, api, method, name, dtype, data, spec, evidence):
    bmk, pc, code = TYPES[dtype]
    width, schema = struct.calcsize(code), canonical_bytes({'column': 'value', 'dtype': dtype})
    n = len(data) // width
    (root / 'in').write_bytes(data); (root / 'schema').write_bytes(schema)
    if method == C_NATIVE and dtype == 'f16':
        api.result(api.native, data, n, pc, None, status=PC_UNSUPPORTED)
        abi_status = rejects(root, invoke, ('encode', bmk, 'in', 'schema', 'frame'), (1,), ('frame',))
        (root / 'in').unlink(); (root / 'schema').unlink()
        return {'case':name,'dtype':dtype,'native_status':PC_UNSUPPORTED,'abi_status':abi_status}
    direct_fn = api.source if method == SOURCE else api.native
    direct = api.result(direct_fn, data, n, pc, None)
    rust_encoded = None
    if method == SOURCE:
        rust_encoded = identity(api.encode_source_reference(data,n,pc))
        assert rust_encoded == identity(direct)
    rust_decoded = identity(api.decode_source_reference(direct,pc,n,width))
    assert rust_decoded == identity(data)
    assert api.result(api.decode, direct, len(direct), pc, n, width=width) == data
    if n:
        api.result(api.decode, direct, len(direct), pc, n - 1, status=PC_LIMIT)
    execution = json.loads(invoke('encode', bmk, 'in', 'schema', 'frame').stdout)
    assert execution['entry'] == direct_fn.__name__ and execution['fallback'] is None
    full = (root / 'frame').read_bytes()
    def frame(payload=direct, count=n):
        return HEADER.pack(MAGIC[method], bmk, count, len(schema), len(payload)) + schema + payload
    assert full == frame() and spec['frame']
    (evidence / spec['frame']).write_bytes(full)
    (root / 'in').unlink(); (root / 'schema').unlink()
    result = invoke('decode', 'frame', 'out', 'schema.out')
    desc, info = map(json.loads, result.stdout.splitlines())
    assert desc == {'dtype': bmk, 'count': n}
    assert info['entry'] == 'pc_decompress_bounded' and info['backend'] == 'rust-source'
    restored, restored_schema = (root / 'out').read_bytes(), (root / 'schema.out').read_bytes()
    assert restored == data and restored_schema == schema
    (root / 'out').unlink(); (root / 'schema.out').unlink()
    invalid = [('envelope_trailing',full+b'\0',5),('payload_trailing',frame(direct+b'\0'),5),
               ('payload_truncated',frame(direct[:-1]),5),('missing_payload_metadata',frame(b''),5),
               ('count_too_large',frame(count=n+1),5),
               ('other_format',MAGIC[C_NATIVE if method == SOURCE else SOURCE]+full[8:],5)]
    if n:
        invalid.append(('count_too_small',frame(count=n-1),7))
    negatives = {}
    for label,bad,status in invalid:
        (root / 'frame').write_bytes(bad)
        negatives[label] = rejects(root, invoke, ('decode', 'frame', 'out', 'schema.out'), (status,), ('out', 'schema.out'))
    (root / 'frame').unlink()
    return {'case':name,'dtype':dtype,'count':n,'input':identity(data),'frame':identity(full),'payload':identity(direct),
            'schema':identity(schema),'restored':identity(restored),'restored_schema':identity(restored_schema),
            'encode_entry':execution['entry'],'decode_entry':info['entry'],'decode_backend':info['backend'],
            'rust_reference_encoded':rust_encoded,'rust_reference_decoded':rust_decoded,
            'native_count_limit':PC_LIMIT if n else None,'rejected':negatives}


def decode_pages(root, pcodec, prefix):
    codec = Pages(pcodec.lib, prefix)
    sidecar = load_json(root / 'pages.json')
    counts, lengths = sidecar['counts'], sidecar['lengths']
    pc, cap = sidecar['dtype'], sidecar['capacity']
    meta = (root / 'shared.meta').read_bytes()
    assert len(meta) == sidecar['meta_bytes']
    # New process with only shared metadata and detached page files, out of order.
    traces = []
    for i in reversed(range(len(counts))):
        data = (root / f'{i}.page').read_bytes()
        assert len(data) == lengths[i]
        with codec.handle(codec.open, codec.destroy_decoder, meta, len(meta), pc) as decoder:
            assert codec.start(decoder, data, len(data), counts[i], counts[i]) == 0
            raw, spans = codec.drain(decoder, cap, 8, counts[i])
            (root / f'{i}.out').write_bytes(raw)
            assert spans == page_spans(counts[i],cap)
            traces.append({'index':i,'spans':spans,'restored':identity(raw)})
    print(json.dumps(traces))


def page_case(root, api, prefix, data, spec, lib, evidence):
    codec = Pages(api.lib, prefix)
    counts, cap = [p['count'] for p in spec['pages']], spec['capacity']
    pc, width = spec['dtype'], 8
    n = sum(counts); assert len(data) == n * width
    sizes = (SIZE * len(counts))(*counts)
    config = codec.default()
    assert config.mode == config.delta == -1
    with codec.handle(codec.chunk, codec.destroy_chunk, data, n, pc, c.byref(config), sizes, len(sizes)) as enc:
        meta = codec.output(codec.encode_meta, enc)
        assert codec.output(codec.encode_counts, enc) == bytes(sizes)
        info = json.loads(codec.output(codec.enc_describe, enc))
        pages = [codec.output(codec.encode_page, enc, i) for i in reversed(range(len(counts)))][::-1]
    (root / 'shared.meta').write_bytes(meta)
    for i, page in enumerate(pages):
        (root / f'{i}.page').write_bytes(page)
    proof = {'counts': counts, 'lengths': list(map(len, pages)), 'dtype': pc, 'capacity': cap, 'meta_bytes': len(meta)}
    sidecar = canonical_bytes(proof)
    (root / 'pages.json').write_bytes(sidecar)
    child = run_worker(root, [sys.executable, '-I', '-B', __file__, '--pages', root, lib, prefix])
    detached = json.loads(child.stdout)
    expected = [data[sum(counts[:i])*width:sum(counts[:i+1])*width] for i in range(len(counts))]
    for i, values in enumerate(expected):
        assert (root / f'{i}.out').read_bytes() == values
    # A new handle must parse shared metadata; detaching a page does not make a standalone artifact.
    missing_rc = PC_INVALID if prefix == 'pcn' else 3
    with codec.handle(codec.open, codec.destroy_decoder, b'', 0, pc, status=missing_rc):
        pass
    with codec.handle(codec.open, codec.destroy_decoder, meta, len(meta), pc) as d:
        assert json.loads(codec.output(codec.dec_describe, d)) == info
        p0, p1 = pages
        small_quota = codec.start(d,p0,len(p0),counts[0],counts[0]-1)
        assert small_quota == PC_LIMIT
        assert codec.start(d, p0, len(p0), counts[0], n) == 0
        _,_,_,bad_capacity = codec.step(d, cap-1, width, (PC_INVALID,))
        first, k, done, _ = codec.step(d, cap, width)
        assert k == cap and not done
        early_next = codec.start(d,p1,len(p1),counts[1],n)
        assert early_next == PC_INVALID
        tail, _ = codec.drain(d, cap, width, counts[0]-cap)
        assert first + tail == expected[0]
        # Source applies max_values per start; C native includes previously decoded values.
        second_quota = codec.start(d, p1, len(p1), counts[1], counts[1])
        assert second_quota == (PC_LIMIT if prefix == 'pcn' else 0)
        if prefix == 'pcn':
            assert codec.start(d, p1, len(p1), counts[1], n) == 0
        assert codec.drain(d, cap, width, counts[1])[0] == expected[1]
    # Final read must validate end of the encoded page, not just return requested values.
    with codec.handle(codec.open, codec.destroy_decoder, meta, len(meta), pc) as d:
        bad = pages[0] + b'\0'
        assert codec.start(d, bad, len(bad), counts[0], n) == 0
        assert codec.step(d, cap, width)[1] == cap
        assert codec.step(d, cap, width)[1] == cap
        _,_,_,trailing = codec.step(d, cap, width, (PC_CORRUPT,))
        _,_,_,poisoned = codec.step(d, cap, width, (PC_INVALID,))
    with codec.handle(codec.open, codec.destroy_decoder, meta, len(meta), pc) as d:
        partial = pages[0][:-1]
        truncated = codec.start(d,partial,len(partial),counts[0],n)
        stage = 'start'
        if truncated == 0:
            stage = 'drain'
            for _ in page_spans(counts[0],cap):
                _,_,done,truncated = codec.step(d,cap,width,(0,3,PC_CORRUPT))
                assert not done
                if truncated:
                    break
        assert truncated in (3,PC_CORRUPT)
    ownership = None
    if prefix == 'pcn':
        owned = c.create_string_buffer(pages[0])
        with codec.handle(codec.open, codec.destroy_decoder, meta, len(meta), pc) as d:
            assert codec.start(d,owned,len(pages[0]),counts[0],n) == 0
            c.memset(owned,0,len(pages[0]))
            restored,_ = codec.drain(d,cap,width,counts[0])
            assert restored == expected[0]
            ownership = identity(restored)
    for name, blob in [(spec['meta'],meta),(spec['sidecar'],sidecar),
                       *((p['page'],page) for p,page in zip(spec['pages'],pages,strict=True))]:
        (evidence/name).write_bytes(blob)
    return {'meta':identity(meta),'pages':[identity(p) for p in pages],
            'sidecar':identity(sidecar),'state':info,'detached':detached,'caller_buffer_overwrite_restore':ownership,
            'total_bytes_in_probe': len(sidecar)+len(meta)+sum(proof['lengths']),
            'rejected':{'missing_meta':missing_rc,'first_page_small_quota':small_quota,'early_next_page':early_next,
                        'read_capacity_255':bad_capacity,'after_first_with_second_quota':second_quota,
                        'trailing_at_drain':trailing,'read_after_error':poisoned,
                        'truncated_page':{'stage':stage,'status':truncated}}}


def decode_intmult(api, frame, dtype, count, capacity):
    _, pc, code = TYPES[dtype]
    source = Pages(api.lib, 'pcs')
    with source.handle(source.file_open, source.destroy_decoder, frame, len(frame), pc, count) as decoder:
        decoded, steps = source.drain(decoder, capacity, struct.calcsize(code), count)
        info = json.loads(source.output(source.dec_describe, decoder))
    return decoded, {'restored':identity(decoded),'spans':steps,'state':info}


def intmult_case(api, spec, inputs, evidence, library, work):
    params = spec['parameters']
    options = (params['level'],params['delta'],params['chunk_n'])
    frames, rejected = [], []
    for job in spec['frames']:
        data = inputs[job['case']]
        assert identity(data) == job['plain']
        dtype,count = job['dtype'],job['count']
        frame = api.result(api.intmult,data,count,TYPES[dtype][1],job['base'],*options)
        path = evidence/job['frame']
        path.write_bytes(frame)
        # Only the compressed artifact and the relocated source library go to the new decoder process.
        output = work/'restored'
        child = run_worker(work,[sys.executable,'-I','-B',__file__,'--intmult',library,path,dtype,str(count),
                                  str(params['read_capacity']),output])
        assert output.read_bytes() == data
        output.unlink()
        frames.append({'case':job['case'],'artifact':identity(frame),'fresh_process':json.loads(child.stdout)})
    for job in spec['rejected']:
        data = bytes(struct.calcsize(TYPES[job['dtype']][2]))
        assert identity(data) == job['plain']
        dst, n = PTR(), SIZE(999)
        try:
            status = api.intmult(data,1,TYPES[job['dtype']][1],job['base'],*options,c.byref(dst),c.byref(n))
            assert status == PC_INVALID and not dst and n.value == 0
            rejected.append({**job,'status':status,'output_bytes':n.value,'output_pointer_null':not dst})
        finally:
            api.free(dst)
    return {'entry':api.intmult.__name__,'parameters':params,'frames':frames,'rejected':rejected}


def main(worker, source_module, c_module, library, report):
    bundle,inputs = plan_pcodec(ROOT)
    values = next(data for case,_,data in inputs if case == TRAFFIC)
    binaries = worker,source_module,c_module,library
    with (tempfile.TemporaryDirectory(prefix='tsbench-pcodec-moved-') as temp,
          tempfile.TemporaryDirectory(dir=report.parent,prefix='.pcodec-report-') as stage):
        root = Path(temp)
        evidence = Path(stage)
        for directory in ('catalog', 'schemas', 'plugins', 'include', 'cmake', 'tools', 'third_party'):
            shutil.copytree(ROOT / directory, root / directory)
        for path in binaries:
            shutil.copy2(path, root / path.name)
        lock = create_build_lock(root, worker.name, {SOURCE: source_module.name, C_NATIVE: c_module.name})
        lib = root / library.name
        api = Native(lib)
        standalone, native_pages = {}, {}
        for method in (SOURCE,C_NATIVE):
            binding = resolve_worker(root, lock, method, {})
            def invoke(op, *args, check=True):
                return run_worker(root, [binding['worker'], op, binding['library'], method, '{}', *map(str, args)], check=check)
            standalone[method] = [batch_case(root,invoke,api,method,*case,spec,evidence)
                                  for case,spec in zip(inputs,bundle['batch'][method],strict=True)]
        for route, prefix in (('source-pages','pcs'),('native-pages','pcn')):
            path = root / route; path.mkdir()
            native_pages[route] = page_case(path,api,prefix,values,bundle['page'][route],lib,evidence)
        spec,data = intmult_inputs(load_json(ROOT / CONFIG)['intmult'])
        assert spec == bundle['intmult']
        work = root / 'intmult'
        work.mkdir()
        intmult = intmult_case(api,spec,data,evidence,lib,work)
        doc = {'schema':'bmk.m0-pcodec-control/3','bundle_id':bundle['bundle_id'],
               'case_ids':[x['case_id'] for x in bundle['cases']], 'config_id':bundle['config_id'],
               'archive_sha256':bundle['archive_sha256'],'definitions':digest(Path(__file__)),
               'build':{p.name:digest(root/p.name) for p in binaries},'window':bundle['window'],
               'formal_performance':False,'formal_qualification':False,
               'standalone':standalone,'pages':native_pages,'intmult':intmult}
        staged = evidence / bundle['evidence_path']
        staged.write_bytes(canonical_bytes(doc) + b'\n')
        verify_pcodec(bundle,doc['build'],doc['definitions'],evidence)
        for name in bundle['binary']:
            (evidence/name).replace(report.parent/name)
        staged.replace(report)


if __name__ == '__main__':
    if sys.argv[1] == '--pages':
        _, _, root, library, prefix = sys.argv
        decode_pages(Path(root), Native(library), prefix)
    elif sys.argv[1] == '--intmult':
        _, _, lib, path, dtype, count, capacity, output = sys.argv
        decoded, summary = decode_intmult(Native(lib),Path(path).read_bytes(),dtype,int(count),int(capacity))
        Path(output).write_bytes(decoded)
        print(json.dumps(summary))
    else:
        main(*(Path(p).resolve() for p in sys.argv[1:]))
