#!/usr/bin/env python3
"""Selection 85: native batch, stream and indexed access are distinct workloads."""
from contextlib import contextmanager
import ctypes as c
import hashlib
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_worker_support import ROOT, run_worker
from tsbench.assets import canonical_bytes, digest, load_json
from tsbench.planner.titchy_access import BACKING, SCOPE, expected_queries, plan_titchy_access
from tsbench.planner.titchy_native import KNOWN_REJECTIONS, fixtures, plan_titchy_native, retained_paths
from tsbench.runtime import create_build_lock, resolve_worker

PLUGIN = 'titchy-batch'
HEADER = struct.Struct('<8sIQIQ')
MAGIC = b'BMKTCH\1\0'
LIMIT = 1_000_000
UINT64_MAX = (1 << 64) - 1
INVALID, CAPACITY, STREAM = 1, 2, 4
PTR, SIZE, U64, INT = c.c_void_p, c.c_size_t, c.c_uint64, c.c_int
PP, PS, PU = c.POINTER(PTR), c.POINTER(SIZE), c.POINTER(U64)
READ_AT = c.CFUNCTYPE(INT, PTR, U64, PTR, SIZE)
TSTR = struct.Struct('<5sBBHQI')
TSTR_RECORD = struct.Struct('<HI')
TSC1 = struct.Struct('<4sBBHBxHdQ4x')


class Config(c.Structure):
    _fields_ = [('bits', c.c_uint8), ('chunk', c.c_uint8), ('split', c.c_uint16),
                ('endian', c.c_uint8), ('threshold', c.c_double), ('active_bytes', U64)]


class Stats(c.Structure):
    _fields_ = [('samples', SIZE), ('chunks', SIZE), ('bases', SIZE), ('active', SIZE), ('pending', SIZE),
                ('ready', SIZE), ('id_width', c.c_uint), ('deviation_width', c.c_uint), ('finished', INT)]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def config(bits=64, maximum=UINT64_MAX):
    return Config(bits, 4, 1000, 0, .25, maximum)


class Native:
    def __init__(self, library):
        lib = c.CDLL(str(library))
        self.statuses = {}
        def bind(name, args, result=INT):
            f = getattr(lib, 'titchy_' + name)
            f.argtypes, f.restype = args, result
            setattr(self, name, f)
        pc = c.POINTER(Config)
        bind('bound', [SIZE, pc], SIZE)
        bind('c_encode', [PU, SIZE, pc, PTR, SIZE, PS])
        bind('c_decode', [PTR, SIZE, PU, SIZE, SIZE, PS])
        bind('c_range', [PTR, SIZE, SIZE, SIZE, PU, SIZE, SIZE])
        bind('reader_open', [READ_AT, PTR, SIZE, SIZE, PP])
        bind('reader_open_file', [c.c_char_p, SIZE, PP])
        bind('reader_free', [PTR], None)
        bind('reader_count', [PTR], SIZE)
        bind('reader_bit', [PTR, SIZE, c.POINTER(c.c_uint8)])
        bind('reader_sample', [PTR, SIZE, PU])
        bind('reader_range', [PTR, SIZE, SIZE, PU, SIZE])
        bind('stream_encoder_create', [pc, SIZE, SIZE, PP])
        bind('stream_decoder_create', [pc, SIZE, PP])
        bind('stream_encoder_free', [PTR], None)
        bind('stream_decoder_free', [PTR], None)
        bind('stream_encoder_reset', [PTR])
        bind('stream_decoder_reset', [PTR])
        bind('stream_encoder_info', [PTR, pc, PS, c.POINTER(Stats)])
        bind('stream_push', [PTR, U64])
        bind('stream_finish', [PTR])
        bind('stream_pop', [PTR, PTR, SIZE, PS, PS])
        bind('stream_decode_packet', [PTR, PTR, SIZE, SIZE, PU, SIZE, PS])

    def expect(self, label, got, want):
        assert got == want, (label, got, want)
        if label:
            self.statuses[label] = got

    @contextmanager
    def handle(self, create, free, *args, status=0, label=None):
        ptr = PTR()
        try:
            rc = create(*args, c.byref(ptr))
            self.expect(label, rc, status)
            assert bool(ptr) == (rc == 0), (create.__name__, rc, status)
            yield ptr
        finally:
            free(ptr)

    def batch(self, values, cfg):
        n = len(values)
        data = (U64 * n)(*values)
        bound = self.bound(n, c.byref(cfg))
        assert bound
        out, used = c.create_string_buffer(bound), SIZE()
        assert self.c_encode(data, n, c.byref(cfg), out, bound, c.byref(used)) == 0
        assert 38 <= used.value <= bound
        payload = out.raw[:used.value]
        restored, got = (U64 * n)(), SIZE()
        assert self.c_decode(payload, len(payload), restored, n, n, c.byref(got)) == 0
        assert got.value == n and tuple(restored) == values
        return payload, bound

    def progress(self, enc, target):
        conf, packet, st = Config(), SIZE(), Stats()
        assert self.stream_encoder_info(enc, c.byref(conf), c.byref(packet), c.byref(st)) == 0
        assert packet.value == target
        return {key: getattr(st, key) for key, _ in st._fields_}

    def pop(self, enc, cap=16384, status=0, label=None):
        b = c.create_string_buffer(max(1, cap))
        n, chunks = SIZE(10), SIZE(10)
        self.expect(label, self.stream_pop(enc, b, cap, c.byref(n), c.byref(chunks)), status)
        assert (not n.value and not chunks.value) if status else (bool(n.value) == bool(chunks.value))
        return chunks.value, b.raw[:n.value]

    def packet(self, dec, packet, cap=None, status=0, chunk_size=4, label=None):
        chunks, wire = packet
        n = chunks * chunk_size
        cap = n if cap is None else cap
        out, count = (U64 * cap)(), SIZE(10)
        self.expect(label, self.stream_decode_packet(dec, wire, len(wire), chunks, out, cap, c.byref(count)), status)
        assert count.value == (0 if status else n)
        return tuple(out[:count.value])


def words(raw, bits=64):
    return tuple(v for (v,) in struct.iter_unpack({8:'<B', 16:'<H', 32:'<I', 64:'<Q'}[bits], raw))


def packed(values, bits=64):
    return b''.join(v.to_bytes(bits//8, 'little') for v in values)


def check_reject(root, invoke, op, args, status, outputs, options='{}'):
    r = invoke(op, *args, check=False, options=options)
    assert r.returncode == 3 and f'plugin status {status}:'.encode() in r.stderr, r
    assert not any((root / name).exists() for name in outputs)
    return status


def batch_case(root, invoke, api, name, bits, values, lineage=None):
    dtype = {8:2, 16:4, 32:6, 64:8}[bits]
    raw, schema = packed(values, bits), canonical_bytes({'dtype': f'u{bits}', 'column': 'v'})
    (root / 'input').write_bytes(raw); (root / 'schema').write_bytes(schema)
    native, bound = api.batch(values, config(bits))
    result = invoke('encode', dtype, 'input', 'schema', 'frame')
    assert json.loads(result.stdout) == {'backend': 'titchy-c11', 'entry': 'titchy_c_encode',
                                         'mode': 'batch', 'threads': 1, 'operation': 'encode'}
    full = (root / 'frame').read_bytes()
    def make(payload=native, n=len(values), type_id=dtype):
        return HEADER.pack(MAGIC, type_id, n, len(schema), len(payload)) + schema + payload
    assert full == make()
    (root / 'input').unlink(); (root / 'schema').unlink()
    desc, info = map(json.loads, invoke('decode', 'frame', 'restored', 'schema.out').stdout.splitlines())
    assert desc == {'dtype':dtype, 'count':len(values)} and info['entry'] == 'titchy_c_decode'
    restored, schema_out = (root / 'restored').read_bytes(), (root / 'schema.out').read_bytes()
    assert restored == raw and schema_out == schema
    (root / 'restored').unlink(); (root / 'schema.out').unlink()
    negatives = [(full[:-1], 5), (full+b'\0', 5), (make(n=len(values)+1), 5), (make(n=LIMIT+1), 7),
                 (make(type_id=10), 5), (make(native[:7]+b'\1'+native[8:]), 5), (make(native+b'\0'), 5)]
    rejected = {}
    for label, (bad, status) in zip(KNOWN_REJECTIONS['batch_frames'], negatives, strict=True):
        (root / 'frame').write_bytes(bad)
        rejected[label] = check_reject(root, invoke, 'decode', ['frame','restored','schema.out'], status, ['restored','schema.out'])
    (root / 'frame').unlink()
    artifact = f'titchy-{name}.bmk'
    (root / artifact).write_bytes(full)
    return {'artifact': artifact, 'detached_restored_sha256': sha(restored), 'descriptor': desc,
            'negative_statuses': rejected, 'case': name, 'bits_per_sample':bits, 'count':len(values), 'input_sha256':sha(raw),
            'native_bound':bound, 'native_bytes':len(native), 'native_sha256':sha(native),
            'schema_bytes':len(schema), 'artifact_bytes':len(full), 'artifact_sha256':sha(full),
            'bit_exact':True, 'negative_artifacts':len(negatives), **(lineage or {})}, native


def encode_packets(api, enc, values, target, check):
    packets, emitted_after_push, first, max_active, max_ready = [], [], None, 0, 0
    for i, value in enumerate(values, 1):
        assert api.stream_push(enc, value) == 0
        st = api.progress(enc, target)
        max_active, max_ready = max(max_active,st['active']), max(max_ready,st['ready'])
        if st['ready'] and first is None:
            first = i
            if check:
                api.expect('blocked_push', api.stream_push(enc, value), CAPACITY)
                api.expect('blocked_finish', api.stream_finish(enc), CAPACITY)
                assert api.pop(enc, cap=1, status=CAPACITY, label='small_pop') == (0,b'')
                assert api.progress(enc,target) == st
        while True:
            packet = api.pop(enc)
            if not packet[0]:
                break
            packets.append(packet)
            emitted_after_push.append(i)
    before = len(packets)
    assert api.stream_finish(enc) == 0
    while True:
        packet = api.pop(enc)
        if not packet[0]:
            break
        packets.append(packet)
    end = api.progress(enc,target)
    assert end['finished'] and end['samples'] == len(values)
    api.expect('push_after_finish', api.stream_push(enc, 0), INVALID)
    api.expect('finish_after_finish', api.stream_finish(enc), INVALID)
    return packets, {'first_packet_after_samples':first, 'packets_before_finish':before, 'max_active_bases':max_active,
                     'max_ready_packets_observed':max_ready, 'dictionary_bases':end['bases'],
                     'emitted_after_push':emitted_after_push,'finished_samples':end['samples']}


def detached_stream(root, api):
    raw = (root / 'stream.tstr').read_bytes()
    manifest = (root / 'stream.tsc1').read_bytes()
    m, bits, chunk, split, endian, target, threshold, active = TSC1.unpack(manifest)
    magic, b, cpc, cps, n, packet_count = TSTR.unpack_from(raw)
    assert m == b'TSC1' and magic == b'TSTR\1' and (b,cpc,cps) == (bits,chunk,split)
    assert 1 <= target <= 65535 and 0 <= n <= LIMIT
    padded = ((n+chunk-1)//chunk)*chunk
    conf = Config(bits,chunk,split,endian,threshold,active)
    out, pos = [], TSTR.size
    with api.handle(api.stream_decoder_create, api.stream_decoder_free, c.byref(conf), padded) as dec:
        for _ in range(packet_count):
            chunks, length = TSTR_RECORD.unpack_from(raw,pos)
            pos += TSTR_RECORD.size
            assert 0 < length <= len(raw)-pos and 0 < chunks <= target
            out.extend(api.packet(dec,(chunks,raw[pos:pos+length]),chunk_size=chunk))
            pos += length
    assert len(raw) == pos and len(out) == padded and not any(out[n:])
    (root / 'stream.out').write_bytes(packed(out[:n],bits))


def stream_case(root, api, lib, values, request):
    target, maximum = request['chunks_per_packet'], request['max_active_bytes']
    cfg = config(maximum=maximum)
    with api.handle(api.stream_encoder_create, api.stream_encoder_free, c.byref(cfg), target, len(values)) as enc:
        assert api.pop(enc) == (0,b'')
        packets, evidence = encode_packets(api, enc, values, target, True)
        assert api.stream_encoder_reset(enc) == 0 and api.progress(enc,target)['samples'] == 0
        replay_packets = encode_packets(api,enc,values,target,False)[0]
        assert replay_packets == packets
    assert evidence['first_packet_after_samples'] == target*cfg.chunk
    assert 0 < evidence['packets_before_finish'] < len(packets) and evidence['max_ready_packets_observed'] == 1
    assert evidence['max_active_bases'] == maximum // 36 < evidence['dictionary_bases']
    padded = ((len(values)+3)//4)*4
    assert padded-len(values) == 3
    def archive_wire(sequence):
        return TSTR.pack(b'TSTR\1',cfg.bits,cfg.chunk,cfg.split,len(values),len(sequence)) + b''.join(
            TSTR_RECORD.pack(chunks,len(wire))+wire for chunks,wire in sequence)
    archive = archive_wire(packets)
    manifest = TSC1.pack(b'TSC1',cfg.bits,cfg.chunk,cfg.split,cfg.endian,target,cfg.threshold,cfg.active_bytes)
    (root / 'stream.tstr').write_bytes(archive); (root / 'stream.tsc1').write_bytes(manifest)
    run_worker(root,[sys.executable,'-I','-B',__file__,'--stream',root,lib])
    recovered = (root / 'stream.out').read_bytes()
    assert recovered == packed(values)
    (root / 'stream.out').unlink()
    # Retry a caller capacity failure; reject stream corruption until reset.
    with api.handle(api.stream_decoder_create,api.stream_decoder_free,c.byref(cfg),padded) as dec:
        first = packets[0]
        api.packet(dec,first,cap=1,status=CAPACITY,label='small_output_retry')
        assert api.packet(dec,first) == values[:first[0]*4]
        assert api.stream_decoder_reset(dec) == 0
        api.packet(dec,(first[0],first[1][:-1]),status=STREAM,label='truncated_packet')
        api.packet(dec,first,status=INVALID,label='decode_after_corruption')
        assert api.stream_decoder_reset(dec) == 0
        assert api.packet(dec,first) == values[:first[0]*4]
    # The decoder value budget includes tail padding, not active encoder bases.
    with api.handle(api.stream_decoder_create,api.stream_decoder_free,c.byref(cfg),len(values)) as dec:
        for packet in packets[:-1]:
            api.packet(dec,packet)
        api.packet(dec,packets[-1],status=CAPACITY,label='tail_quota')
        api.packet(dec,packets[-1],status=INVALID,label='decode_after_quota')
    with api.handle(api.stream_encoder_create,api.stream_encoder_free,c.byref(cfg),target,0) as enc:
        api.expect('empty_session_overflow', api.stream_push(enc,1), INVALID)
        api.expect('finish_after_overflow', api.stream_finish(enc), INVALID)
        assert api.stream_encoder_reset(enc) == 0 and api.stream_finish(enc) == 0 and api.pop(enc) == (0,b'')
    return {**evidence,'packet_count':len(packets),'target_chunks':target,'active_lru_logical_bytes':maximum,
            'true_values':len(values),'padded_values':padded,'pad_zeros':padded-len(values),
            'packet_payload_bytes':sum(len(p) for _,p in packets),'archive_framing_bytes':TSTR.size+TSTR_RECORD.size*len(packets),
            'config_bytes':len(manifest),'all_required_artifact_bytes':len(archive)+len(manifest),
            'archive_sha256':sha(archive),'config_sha256':sha(manifest),'detached_bit_exact':True,
            'backpressure_and_output_capacity_retry':True,'encoder_and_decoder_reset_checked':True,
            'decoder_padding_budget_rejected':True, 'reset_archive_sha256':sha(archive_wire(replay_packets)),
            'detached_restored_sha256':sha(recovered), 'statuses':{k:api.statuses[k] for k in KNOWN_REJECTIONS['stream']}}


class ReadLog:
    def __init__(self, raw, deny=None):
        self.calls = []
        @READ_AT
        def read(_, offset, out, length):
            ok = offset <= len(raw) and length <= len(raw)-offset and offset != deny
            self.calls.append((offset,length,ok))
            if not ok:
                return 1
            if length:
                c.memmove(out,raw[offset:offset+length],length)
            return 0
        self.callback = read

    def drain(self):
        calls, self.calls = self.calls, []
        return {'calls': calls, 'requested_bytes': sum(n for _,n,_ in calls),
                'successful_bytes': sum(n for _,n,ok in calls if ok)}


def queries(api, r, n, req, account=None):
    assert api.reader_count(r) == n
    rows, costs = {}, {}
    def op(label, fn, args, logical):
        assert fn(*args) == 0
        if account:
            costs[label] = {**account.drain(),'result_logical_bits':logical}
    i = req['point']
    sample = U64()
    op('point',api.reader_sample,(r,i,c.byref(sample)),64)
    rows['point'] = sample.value
    start, count = req['range']
    out = (U64 * count)()
    op('range',api.reader_range,(r,start,count,out,count),count*64)
    rows['range'] = list(out)
    rows['bits'] = []
    for i in req['bits']:
        bit = c.c_uint8()
        op(f'bit-{i}',api.reader_bit,(r,i,c.byref(bit)),1)
        rows['bits'].append(bit.value)
    api.expect('reader_sample_oob', api.reader_sample(r,n,c.byref(sample)), INVALID)
    api.expect('reader_bit_oob', api.reader_bit(r,64*n,c.byref(c.c_uint8())), INVALID)
    api.expect('reader_capacity', api.reader_range(r,start,count,out,count-1), CAPACITY)
    api.expect('reader_range_oob', api.reader_range(r,n,1,out,count), INVALID)
    assert api.reader_range(r,n,0,None,0) == 0
    if account:
        assert not account.drain()['calls']
    return rows,costs


def detached_file_reader(root, api):
    request = load_json(root / 'queries.json')
    path = str(root/'access.tchy').encode()
    n = request['count']
    with api.handle(api.reader_open_file,api.reader_free,path,n) as r:
        rows,_ = queries(api,r,n,request['queries'])
    (root/'queries.out').write_bytes(canonical_bytes(rows))


def reader_case(root, api, lib, raw, values, request):
    n = len(values)
    start, count = request['range']
    expected = expected_queries(values, request)
    log = ReadLog(raw)
    splits = int.from_bytes(raw[34:38],'little')
    assert splits == 2
    with api.handle(api.reader_open,api.reader_free,log.callback,None,len(raw),n) as r:
        opened = log.drain()
        assert opened['calls'] == [(0,38,True),(38,24*splits,True)]
        got,costs = queries(api,r,n,request,log)
        assert got == expected
        assert all(0 < m['successful_bytes'] == m['requested_bytes'] < len(raw) for m in costs.values())
        assert costs['point']['requested_bytes'] < costs['range']['requested_bytes']
        again, again_costs = queries(api,r,n,request,log)
        assert (got,costs) == (again,again_costs)
    # The benchmark's full decode has already validated raw, and the file
    # reader gets its own immutable input. File-path correctness != disk bytes.
    (root/'access.tchy').write_bytes(raw)
    (root/'queries.json').write_bytes(canonical_bytes({'count':n,'queries':request}))
    run_worker(root,[sys.executable,'-I','-B',__file__,'--file',root,lib])
    file_results = load_json(root/'queries.out')
    assert file_results == expected
    with api.handle(api.reader_open_file,api.reader_free,str(root/'access.tchy').encode(),n-1,status=CAPACITY,label='file_quota'):
        pass
    with api.handle(api.reader_open_file,api.reader_free,str(root/'absent').encode(),n,status=INVALID,label='file_missing'):
        pass
    # Request errors are exposed to callers; do not silently read around them.
    log = ReadLog(raw,deny=38)
    with api.handle(api.reader_open,api.reader_free,log.callback,None,len(raw),n,status=STREAM,label='index_callback_failure'):
        assert log.calls[-1] == (38,24*splits,False)
    offset = int.from_bytes(raw[38+24+12:38+24+20],'little')
    log = ReadLog(raw,deny=offset)
    with api.handle(api.reader_open,api.reader_free,log.callback,None,len(raw),n) as r:
        api.expect('pair_callback_failure', api.reader_sample(r,request['point'],c.byref(U64())), STREAM)
        assert log.calls[-1] == (offset,8,False)
    # A noncontiguous first index entry is refused by open, not by the first query.
    damaged_index = bytearray(raw)
    damaged_index[38] ^= 1
    bad_idx = ReadLog(bytes(damaged_index))
    with api.handle(api.reader_open,api.reader_free,bad_idx.callback,None,len(raw),n,status=STREAM,label='bad_index'):
        assert bad_idx.calls == [(0,38,True),(38,24*splits,True)]
    # A valid header/index can still reference a malformed split payload.
    # The lazy reader never validated the unaccessed split; stateless range does.
    corrupt = raw[:offset]+b'\xff'+raw[offset+1:]
    log = ReadLog(corrupt)
    with api.handle(api.reader_open,api.reader_free,log.callback,None,len(corrupt),n) as r:
        sample = U64()
        assert api.reader_sample(r,0,c.byref(sample)) == 0 and sample.value == values[0]
        api.expect('touched_bad_pair', api.reader_sample(r,request['point'],c.byref(sample)), STREAM)
    want = (U64 * count)()
    assert api.c_range(raw,len(raw),start,count,want,count,n) == 0 and list(want) == expected['range']
    range_result = list(want)
    assert api.c_range(raw,len(raw),n,0,None,0,n) == 0
    api.expect('stateless_oob', api.c_range(raw,len(raw),n,1,want,count,n), INVALID)
    api.expect('stateless_capacity', api.c_range(raw,len(raw),start,count,want,count-1,n), CAPACITY)
    api.expect('stateless_quota', api.c_range(raw,len(raw),start,count,want,count,n-1), CAPACITY)
    api.expect('stateless_unrelated_bad_pair', api.c_range(corrupt,len(corrupt),0,1,want,count,n), STREAM)
    api.expect('stateless_bad_pair_empty_request', api.c_range(corrupt,len(corrupt),n,0,None,0,n), STREAM)
    return {'backing_bytes':len(raw),'backing_sha256':sha(raw),'splits':splits,'open_read_at':opened,'query_read_at':costs,
            'repeated_query_read_at':again_costs,'counts_scope':SCOPE,
            'read_at_results':[got,again],'detached_file_results':file_results,
            'detached_file_queries_bit_exact':True,'read_failure_and_oob_rejected':True,
            'lazy_validation_differs_from_whole_frame':True, 'statuses':{k:api.statuses[k] for k in KNOWN_REJECTIONS['access']},
            'index_mutation_sha256':sha(damaged_index),'pair_mutation_sha256':sha(corrupt),
            'valid_prefix_on_bad_later_split':sample.value, 'empty_range_at_eof_accepted':True,
            'stateless_range':{'bit_exact':True,'result':range_result,'validates_entire_container_before_each_call':True,
                               'out_of_range_capacity_and_unrelated_bad_split_rejected':True}}


def main(worker,module,library,report):
    bundle, cfg, source = plan_titchy_access(ROOT)
    oracle, accounting, _ = bundle['cases']
    window, reader = oracle['window'], oracle['criteria']['request']
    native_bundle = plan_titchy_native(bundle, cfg, source)
    stream = native_bundle['stream']
    values = words(source)
    assert packed(values) == source
    with tempfile.TemporaryDirectory(prefix='tsbench-titchy-moved-') as temp:
        root = Path(temp)
        for directory in ('catalog','schemas','plugins','include','cmake','tools','third_party'):
            shutil.copytree(ROOT/directory,root/directory)
        for p in (worker,module,library):
            shutil.copy2(p,root/p.name)
        lock = create_build_lock(root,worker.name,{PLUGIN:module.name})
        bound = resolve_worker(root,lock,PLUGIN,{})
        lib = root / library.name
        api = Native(lib)
        def invoke(op,*args,check=True,options='{}'):
            return run_worker(root,[bound['worker'],op,bound['library'],PLUGIN,options,*map(str,args)],check=check)
        observations = []
        for name, bits, samples, lineage in fixtures(source, window):
            row, native_frame = batch_case(root,invoke,api,name,bits,samples,lineage)
            observations.append(row)
            if name == 'traffic-split-and-tail':
                raw = native_frame
        (root/'schema').write_bytes(b'{}'); (root/'input').write_bytes(b'\0'*8)
        inputs = {}
        inputs['worker_f64'] = check_reject(root,invoke,'encode',[10,'input','schema','frame'],1,['frame'])
        inputs['worker_unknown_option'] = check_reject(root,invoke,'encode',[8,'input','schema','frame'],3,['frame'],
                                                       options='{"bits":64}')
        (root/'input').write_bytes(bytes(LIMIT+1))
        inputs['worker_count'] = check_reject(root,invoke,'encode',[2,'input','schema','frame'],7,['frame'])
        (root/'input').unlink(); (root/'schema').unlink()
        out, received = (U64 * len(values))(), SIZE(7)
        inputs['native_encode_capacity'] = api.c_encode((U64 * len(values))(*values),len(values),c.byref(config()),
                                                        c.create_string_buffer(1),1,c.byref(received))
        inputs['native_decode_capacity'] = api.c_decode(raw,len(raw),out,len(values)-1,len(values),c.byref(received))
        assert received.value == 0
        inputs['native_decode_quota'] = api.c_decode(raw,len(raw),out,len(values),len(values)-1,c.byref(received))
        assert received.value == 0 and inputs == KNOWN_REJECTIONS['batch_input']
        stream_report = stream_case(root,api,lib,values,stream)
        reader_report = reader_case(root,api,lib,raw,values,reader)
        retained = {name: (root/name).read_bytes() for name in retained_paths(native_bundle)}
    limits = accounting['criteria']['byte_limits']
    assert len(raw) <= limits['max_backing_bytes'] and reader_report['open_read_at']['requested_bytes'] <= limits['open']
    for field in ('query_read_at','repeated_query_read_at'):
        for label, ledger in reader_report[field].items():
            assert ledger['requested_bytes'] <= limits['bit' if label.startswith('bit-') else label]
    reader_report['backing_path'] = BACKING
    doc = {'schema':'bmk.m0-titchy-control/2','diagnostic_id':uuid.uuid4().hex,'config_id':bundle['config_id'],
           'access_bundle_id':bundle['bundle_id'],'access_case_ids':[case['case_id'] for case in bundle['cases']],
           'definitions':digest(Path(__file__)),'build':lock,'formal_qualification':False,'formal_performance':False,
           'batch':observations,'rejected_inputs':3,'stream':stream_report,'access':reader_report,
           'native_bundle_id':native_bundle['bundle_id'],'batch_input_statuses':inputs}
    with tempfile.TemporaryDirectory(dir=report.parent,prefix='.titchy-report-') as temp:
        staged = Path(temp)/'report.json'
        staged.write_bytes(canonical_bytes(doc)+b'\n')
        for name, data in retained.items():
            (Path(temp)/name).write_bytes(data)
        for name in retained:
            (Path(temp)/name).replace(report.parent/name)
        staged.replace(report)


if __name__ == '__main__':
    if sys.argv[1] in ('--stream','--file'):
        _,op,path,lib = sys.argv
        (detached_stream if op == '--stream' else detached_file_reader)(Path(path),Native(lib))
    else:
        main(*(Path(p).resolve() for p in sys.argv[1:]))
