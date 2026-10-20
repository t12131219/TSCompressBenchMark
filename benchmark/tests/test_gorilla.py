"""Gorilla admission uses archived upstream bytes and hostile object directories."""
from pathlib import Path
import copy
import ctypes as ct
import hashlib
import json
import os
import struct
import subprocess
import sys
import numpy as np
import pytest
from tsbench.artifact import EncodedObject, pack_bundle, read_bundle_prefix
from tsbench.bridges import create_bridge
from tsbench.bridges.c_abi_v1 import byte_buffer
from tsbench.build import build_codec
from tsbench.data import TimeSeriesObject, fingerprint
from tsbench.errors import Unsupported
from tsbench.schemes import ObjectScheme, capability, decode_once

ROOT = Path(__file__).resolve().parents[2]
KEY = 'gorilla-prometheus-xor'
BITS = np.array([0, 2**63, 0x7ff0000000000000, 0xfff0000000000000,
                 0x7ff0000000000001, 0x7ff8123456781234, 1, 0xffffffffffffffff], dtype='<u8')

@pytest.fixture(scope='module')
def bridge():
    build_codec(ROOT, KEY)
    return create_bridge(ROOT, KEY)


def obj(n=17, columns=None, order='C', custom=False):
    t = np.resize(np.array([-2**63, 2**63-1, 0, -1, 0, 0, 7, 2], dtype='<i8'), n)
    v = np.resize(BITS, n * (columns or 1)).view('<f8')
    if columns: v = np.array(v.reshape(n, columns), order=order)
    names = ['time', 'value'] if custom else ['T', 'V']
    return TimeSeriesObject(dict(zip(names, [t, v])), {'roles': dict(zip(names, ['T', 'V'])), 'time_unit': 'ms'})


def method(path='optimized', **extra):
    return {'codec': KEY, 'params': {'path': path}, **extra}


def roundtrip(o, m):
    before = fingerprint(o)
    encoded = ObjectScheme(m, asset_root=ROOT).encode_once(o)
    restored = decode_once(encoded, asset_root=ROOT)
    assert fingerprint(restored) == before == fingerprint(o)
    return encoded


def chunks(path, magic, records=False):
    data = path.read_bytes(); assert data[:4] == magic
    count = struct.unpack_from('<I', data, 4)[0]; offset = 8; out = []
    for _ in range(count):
        n = struct.unpack_from('<I', data, offset)[0]; offset += 4
        size = n*16 if records else n
        out.append(data[offset:offset+size]); offset += size
    assert offset == len(data)
    return out


@pytest.mark.parametrize('path', ['canonical', 'optimized'])
def test_archived_source_vectors_complete_bytes_and_cross_decode(bridge, path):
    base = ROOT/'adapters/gorilla_prometheus_xor/vendor/gorilla/tests/golden'
    inputs = chunks(base/'input.bin', b'GRI1', True)
    outputs = chunks(base/'expected_output.bin', b'GRS1')
    assert len(inputs) == len(outputs) == 36
    for pairs, expected in zip(inputs, outputs):
        a = np.frombuffer(pairs, dtype='<u8').reshape(-1, 2)
        t, v = a[:,0].copy().view('<i8'), a[:,1].copy().view('<f8')
        assert bridge.encode_pairs(t, v, {'path': path}) == expected
        times, values = bridge.decode_pairs(expected, len(t), {'path': path})
        assert times.tobytes() == t.tobytes() and values.tobytes() == v.tobytes()


@pytest.mark.parametrize('n', [0, 1, 2, 6, 7, 8, 65534, 65535, 65536])
@pytest.mark.parametrize('path', ['canonical', 'optimized'])
def test_joint_tail_count_limit_and_special_bits(bridge, path, n):
    o = obj(n, custom=True)
    wire = roundtrip(o, method(path, chunk_rows=65535))
    assert wire.descriptor['codec_input_bytes'] == n*16
    assert len(wire.descriptor['joint_parts']) == max(1, (n+65534)//65535)


@pytest.mark.parametrize('order', ['C', 'F'])
@pytest.mark.parametrize('n', [0, 17])
def test_channelwise_records_mask_cost_and_schema(bridge, order, n):
    o = obj(n, 3, order)
    mask = np.array(np.arange(n*3).reshape(n,3)%2, dtype='u1', order=order)
    o = TimeSeriesObject({**o.components, 'mask': mask}, {**o.schema, 'roles': {'T':'T','V':'V','mask':'mask'}})
    wire = roundtrip(o, method(channelwise=True, chunk_rows=7))
    assert wire.descriptor['codec_input_bytes'] == n*16*3 + mask.nbytes
    assert len(wire.descriptor['joint_parts']) == 3*max(1, (n+6)//7)
    assert wire.stored_bytes > wire.payload_bytes


def test_rejects_unpaired_casts_implicit_mts_and_oversized_chunks(bridge):
    cases = [(TimeSeriesObject({'V':np.zeros(2)},{}), method()),
             (TimeSeriesObject({'T':np.arange(2,dtype='<i8')},{}), method()),
             (TimeSeriesObject({'T':np.arange(2,dtype='<i8'),'V':np.zeros(2,dtype='<f4')},{}), method()),
             (obj(17,3), method()), (obj(65536), method()),
             (obj(), method(transform='integer_affine_gcd')),
             (obj(), method(components={'V':{'codec':KEY}}))]
    for o,m in cases:
        with pytest.raises(Unsupported): ObjectScheme(m, asset_root=ROOT).encode_once(o)
        assert not capability(m,o,{'kind':'records'},{'native_threads':1},ROOT)['supported']
    with pytest.raises(Unsupported): bridge.encode(np.zeros(2))


def test_native_atomic_short_capacity_malformed_and_reset(bridge):
    data = np.column_stack([obj().components['T'].view('<u8'), obj().components['V'].view('<u8')]).astype('<u8').tobytes()
    ins = ct.create_string_buffer(data); source = byte_buffer(ins,capacity=len(data),used=len(data))
    with bridge._session({'path':'optimized'}, 'encode') as h:
        bound = ct.c_uint64(); assert bridge.lib.tscb_compress_bound(h,ct.byref(source),ct.byref(bound)) == 0
        storage = ct.create_string_buffer(b'\xa5'*(bound.value+16)); output = byte_buffer(storage,capacity=bound.value-1,used=3)
        assert bridge.lib.tscb_compress(h,ct.byref(source),ct.byref(output)) == 3
        assert output.used_bytes == 3 and storage.raw == b'\xa5'*(bound.value+16)+b'\0'
        output.capacity_bytes = bound.value
        assert bridge.lib.tscb_compress(h,ct.byref(source),ct.byref(output)) == 0
        raw = storage.raw[:output.used_bytes]
        assert storage.raw[bound.value:bound.value+16] == b'\xa5'*16
        assert ins.raw[:len(data)] == data
        assert bridge.lib.tscb_compress(h,ct.byref(source),ct.byref(output)) != 0
        empty = ct.create_string_buffer(1); final = byte_buffer(empty,capacity=0)
        for _ in range(2): assert bridge.lib.tscb_finalize(h,ct.byref(final)) == 0 and final.used_bytes == 0
        assert bridge.lib.tscb_reset(h,1) == 2
        assert bridge.lib.tscb_reset(h,0) == 0
        for bad in [raw[:-1],raw+b'\0',b'\0\1']:
            bads=ct.create_string_buffer(bad); src=byte_buffer(bads,capacity=len(bad),used=len(bad))
            dest=ct.create_string_buffer(b'\x5a'*(len(data)+16)); out=byte_buffer(dest,capacity=len(data),used=3)
            assert bridge.lib.tscb_decompress(h,ct.byref(src),ct.byref(out)) != 0
            assert out.used_bytes==3 and dest.raw==b'\x5a'*(len(data)+16)+b'\0'


def test_joint_decoder_rejects_other_columns_different_timestamps(bridge):
    wire=roundtrip(obj(17,2),method(channelwise=True));d,b=read_bundle_prefix(wire.wire);body=bytearray(b)
    p=d['joint_parts'][1];o=obj(17);t=o.components['T'].copy();t[0]=1
    payload=bridge.encode_pairs(t,o.components['V'],p['params'])
    body=body[:p['offset']]+payload; p['length']=len(payload);p['sha256']=hashlib.sha256(payload).hexdigest()
    with pytest.raises(ValueError,match='timestamps'):decode_once(EncodedObject(pack_bundle(d,bytes(body))),ROOT)


@pytest.mark.parametrize('corruption', ['gap','overlap','count','dtype','params','empty_duplicate','trailing'])
def test_rejects_rechecksummed_corrupt_joint_directory(bridge,corruption):
    wire=roundtrip(obj(0 if corruption=='empty_duplicate' else 17),method(chunk_rows=7))
    d,b=read_bundle_prefix(wire.wire)
    if corruption=='gap':d['joint_parts'][1]['row_start']+=1
    if corruption=='overlap':d['joint_parts'][1]['row_start']-=1
    if corruption=='count':
        p=d['joint_parts'][0];body=bytearray(b);body[p['offset']+1]^=1;b=bytes(body);p['sha256']=hashlib.sha256(b[p['offset']:p['offset']+p['length']]).hexdigest()
    if corruption=='dtype':d['components'][1]['dtype']='<f4'
    if corruption=='params':d['joint_parts'][0]['params']['path']='auto'
    if corruption=='empty_duplicate':d['joint_parts'].append(copy.deepcopy(d['joint_parts'][0]))
    if corruption=='trailing':b+=b'\0'
    with pytest.raises(ValueError):decode_once(EncodedObject(pack_bundle(d,b)),ROOT)


def test_saved_wire_decodes_in_new_process_and_runner_records_failures(bridge,tmp_path):
    from tsbench.runner import run
    from tsbench.records import read_jsonl
    o=obj(17);np.savez(tmp_path/'records.npz',**o.components);np.save(tmp_path/'values.npy',o.components['V'])
    wire=roundtrip(o,method());(tmp_path/'saved.tsb').write_bytes(wire.wire)
    done=subprocess.run([sys.executable,'-m','tsbench','decode',str(tmp_path/'saved.tsb'),str(tmp_path/'decoded'),'--asset-root',str(ROOT)],capture_output=True,text=True)
    assert done.returncode==0,done.stderr
    meta=json.loads((tmp_path/'decoded/object.json').read_text())
    for name,file in meta['components'].items():assert np.load(tmp_path/'decoded'/file).tobytes()==o.components[name].tobytes()
    config={'schema':'tsbench.experiment/1','name':'gorilla-admission','_base_dir':str(tmp_path),'_asset_root':str(ROOT),
            'datasets':[{'id':'paired','path':'records.npz','components':{'T':'T','V':'V'}}, {'id':'unpaired','path':'values.npy'}],
            'methods':[{'id':'gorilla',**method()}],'task':{'kind':'records','fidelity':'bitwise','boundary':'object_memory','lifecycle':'independent_object'},
            'execution':{'sessions':1,'rounds':2,'warmup_objects':0,'timeout_s':30,'qualification_cache':False}}
    dest=run(config,tmp_path/'run');manifest=json.loads((dest/'manifest.json').read_text())
    assert sorted(c['status'] for c in manifest['cases'])==['ready','unsupported']
    rows,tail=read_jsonl(dest/'observations.jsonl');assert tail is None
    trials=[r for r in rows if r['phase']=='measurement' and r['event']=='terminal']
    assert len(trials)==2 and all(r['status']=='ok' for r in trials)
    exact=[r for r in rows if r.get('qualification_kind')=='exact' and r['event']=='terminal']
    assert len(exact)==1 and exact[0]['independent_recovery']['decoder_process']
