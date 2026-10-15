"""Joint T/V bridge and explicit independent-chunk records scheme.

Native payloads are complete EncXOR chunks. No synthesized timestamps, casts,
raw fallback or serialized-chunk append are used. MTS repeats T per column.
"""
from __future__ import annotations
import ctypes as ct
import hashlib
import json
import numpy as np
from .c_abi_v1 import CAbiBridge, byte_buffer
from ..artifact import EncodedObject, MAX_DECODE_BYTES, MAX_PARTS, checked_array, pack_bundle
from ..data import TimeSeriesObject, array_descriptor, canonical_json, fingerprint
from ..errors import Unsupported
from ..registry import CodecError, UnsupportedError
KEY = 'gorilla-prometheus-xor'
SCHEMA = 'tsbench.gorilla-records/1'
MAX_SAMPLES = 65535

class GorillaBridge(CAbiBridge):

    def _config(self, params):
        return canonical_json({'path': params['path']})

    def encode(self, array, params=None):
        raise UnsupportedError('Gorilla requires paired T/V records; use the joint object scheme')

    def encode_pairs(self, timestamps, values, params):
        if timestamps.dtype.str != '<i8' or values.dtype.str != '<f8' or timestamps.ndim != 1 or (values.ndim != 1) or (timestamps.shape != values.shape) or (len(values) > MAX_SAMPLES):
            raise UnsupportedError('Gorilla needs <=65535 paired int64 / float64 samples')
        params = self.registry.resolve_params(KEY, params)
        pairs = np.empty((len(values), 2), dtype='<u8')
        pairs[:, 0] = timestamps.view('<u8')
        pairs[:, 1] = values.view('<u8')
        data = pairs.tobytes()
        self.last_input_identity = {'content_sha256': hashlib.sha256(data).hexdigest(), 'dtype': '|u1', 'shape': [len(data)], 'nbytes': len(data), 'layout': 'LE_I64_U64_INTERLEAVED_PAIRS', 'abi': 'tscb-c-v1'}
        storage = ct.create_string_buffer(data, max(1, len(data)))
        source = byte_buffer(storage, capacity=len(data), used=len(data))
        with self._session(params, 'encode') as handle:
            bound = ct.c_uint64()
            self._check(self.lib.tscb_compress_bound(handle, ct.byref(source), ct.byref(bound)), handle, 'bound')
            if bound.value > 2 + (157 * MAX_SAMPLES + 7) // 8:
                raise CodecError('Gorilla returned an invalid bound')
            output_storage = ct.create_string_buffer(bound.value)
            output = byte_buffer(output_storage, capacity=bound.value)
            arguments = (handle, ct.byref(source), ct.byref(output))
            status = self.lib.tscb_compress(*arguments)
            self._check(status, handle, 'compress')
            if not 2 <= output.used_bytes <= bound.value:
                raise CodecError('Gorilla returned invalid used bytes')
            payload = output_storage.raw[:output.used_bytes]
            finish_storage = ct.create_string_buffer(1)
            finish = byte_buffer(finish_storage, capacity=0)
            arguments = (handle, ct.byref(finish))
            status = self.lib.tscb_finalize(*arguments)
            self._check(status, handle, 'finalize')
            if finish.used_bytes:
                raise CodecError('Gorilla one-shot finalize returned unexpected tail')
        return payload

    def decode_pairs(self, payload, count, params):
        if type(count) is not int or not 0 <= count <= MAX_SAMPLES or len(payload) < 2 or (int.from_bytes(payload[:2], 'big') != count):
            raise ValueError('Gorilla raw sample count differs from chunk directory')
        restored = super().decode(payload, '<f8', (count, 2), params)
        return (restored[:, 0].copy().view('<i8'), restored[:, 1].copy())

def names_and_arrays(obj):
    by_role = {}
    roles = obj.schema.get('roles', {})
    for name, array in obj.components.items():
        role = roles.get(name, name)
        if role not in {'T', 'V', 'mask'} or role in by_role:
            raise Unsupported('Gorilla records require one T, one V and at most one mask', stage='capability')
        by_role[role] = (name, array)
    if not {'T', 'V'} <= by_role.keys():
        raise Unsupported('Gorilla requires actual paired T/V; values-only and timestamp-only are unsupported', stage='capability')
    return by_role

def validate_method(method, obj):
    arrays = names_and_arrays(obj)
    t, v = (arrays['T'][1], arrays['V'][1])
    if method.get('components') or method.get('transform', 'identity') not in {None, 'identity'}:
        raise Unsupported('Gorilla joint scheme does not accept per-component routes or transforms', stage='capability')
    if t.dtype.str != '<i8' or t.ndim != 1 or v.dtype.str != '<f8' or (v.ndim not in (1, 2)) or (t.shape[0] != v.shape[0]):
        raise Unsupported('Gorilla requires int64 T[N] and float64 V[N] or explicit channelwise V[N,M]', stage='capability')
    if v.ndim == 2 and (not method.get('channelwise', False) or v.shape[1] == 0):
        raise Unsupported('Gorilla MTS requires explicit channelwise=true and at least one column', stage='capability')
    chunk = method.get('chunk_rows', max(1, t.shape[0]))
    if type(chunk) is not int or not 1 <= chunk <= MAX_SAMPLES:
        raise Unsupported('Gorilla needs explicit chunk_rows<=65535 for larger objects', stage='capability')
    channels = v.shape[1] if v.ndim == 2 else 1
    if max(1, (len(t) + chunk - 1) // chunk) * channels + ('mask' in arrays) > MAX_PARTS:
        raise Unsupported('Gorilla chunk/channel directory exceeds part limit', stage='capability')
    if 'mask' in arrays:
        mask = arrays['mask'][1]
        if mask.dtype.str not in {'|u1', '|b1'} or mask.shape != v.shape:
            raise Unsupported('Gorilla raw mask must be bool/uint8 with V shape', stage='capability')
    return (arrays, chunk, channels)

def encode_object(obj, method, bridge):
    arrays, chunk, channels = validate_method(method, obj)
    params = bridge.registry.resolve_params(KEY, method.get('params', {}))
    t, v = (arrays['T'][1], arrays['V'][1])
    body = bytearray()
    joint = []
    inputs = []
    components = [{'name': name, 'role': obj.schema.get('roles', {}).get(name, name), **array_descriptor(a), 'parts': []} for name, a in obj.components.items()]
    for channel in range(channels):
        for start in list(range(0, len(t), chunk)) or [0]:
            stop = min(start + chunk, len(t))
            column = np.ascontiguousarray(v[start:stop, channel] if v.ndim == 2 else v[start:stop])
            metadata = {'codec': KEY, 'component': [arrays['T'][0], arrays['V'][0]], 'channel': channel, 'row_start': start, 'row_stop': stop}
            payload = bridge.encode_pairs(np.ascontiguousarray(t[start:stop]), column, params)
            entry = {'codec': KEY, 'format_version': 1, 'params': params, 'row_start': start, 'row_stop': stop, 'channel': channel, 'offset': len(body), 'length': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
            joint.append(entry)
            inputs.append({**bridge.last_input_identity, 'channel': channel, 'row_start': start, 'row_stop': stop})
            body.extend(payload)
    for c in components:
        if c['role'] == 'mask':
            a = obj.components[c['name']]
            payload = a.tobytes(order=c['order'])
            c['parts'] = [{'codec': 'raw-store', 'format_version': 1, 'params': {}, **array_descriptor(a), 'offset': len(body), 'length': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}]
            inputs.append({'component': c['name'], 'nbytes': len(payload), 'content_sha256': hashlib.sha256(payload).hexdigest(), 'abi': 'builtin-raw-v1'})
            body.extend(payload)
    partition = {'version': 1, 'chunk_rows': chunk, 'channelwise': v.ndim == 2, 'state': 'independent fresh EncXOR chunk per column/span; repeated T charged'}
    desc = {'schema_version': SCHEMA, 'schema': dict(obj.schema), 'components': components, 'joint_parts': joint, 'raw_object_id': fingerprint(obj), 'codec_input_id': 'sha256:' + hashlib.sha256(canonical_json(inputs)).hexdigest(), 'codec_input_bytes': sum((i['nbytes'] for i in inputs)), 'codec_input_scope': 'interleaved LE timestamp/value_bits pairs plus raw mask; repeated T charged', 'transform_id': 'sha256:' + hashlib.sha256(canonical_json(partition)).hexdigest(), 'partition': partition, 'dependency_policy': 'standalone; no external model/dictionary', 'identity_cost_policy': 'input/payload/descriptor checksums inside object encode boundary'}
    validate_joint_descriptor(desc, bytes(body))
    return EncodedObject(pack_bundle(desc, bytes(body)))

def validate_joint_descriptor(desc, body):
    if not isinstance(desc.get('schema'), dict):
        raise ValueError('missing Gorilla object schema')
    components = desc.get('components')
    if not isinstance(components, list) or not 2 <= len(components) <= 3:
        raise ValueError('invalid Gorilla component list')
    names = set()
    roles = {}
    total = 0
    for c in components:
        total += checked_array(c)
        name, role = (c.get('name'), c.get('role'))
        if not isinstance(name, str) or not name or name in names or (role in roles) or (role not in {'T', 'V', 'mask'}) or (desc['schema'].get('roles', {}).get(name, name) != role):
            raise ValueError('invalid Gorilla component role/name')
        names.add(name)
        roles[role] = c
    if total > MAX_DECODE_BYTES or not {'T', 'V'} <= roles.keys():
        raise ValueError('invalid Gorilla decompressed object size/roles')
    t, v = (roles['T'], roles['V'])
    if t['dtype'] != '<i8' or len(t['shape']) != 1 or v['dtype'] != '<f8' or (len(v['shape']) not in (1, 2)) or (t['shape'][0] != v['shape'][0]) or (t.get('parts') != []) or (v.get('parts') != []):
        raise ValueError('invalid Gorilla paired component descriptors')
    channels = v['shape'][1] if len(v['shape']) == 2 else 1
    joint = desc.get('joint_parts')
    if not channels or channels > MAX_PARTS or (not isinstance(joint, list)) or (not 1 <= len(joint) <= MAX_PARTS - ('mask' in roles)):
        raise ValueError('invalid Gorilla chunk directory')
    intervals = []

    def payload(p):
        start, size = (p.get('offset'), p.get('length'))
        if type(start) is not int or type(size) is not int or start < 0 or (size < 0) or (start + size > len(body)):
            raise ValueError('Gorilla payload interval out of bounds')
        raw = body[start:start + size]
        if hashlib.sha256(raw).hexdigest() != p.get('sha256'):
            raise ValueError('Gorilla payload checksum mismatch')
        intervals.append((start, start + size))
        return raw
    groups = {}
    for p in joint:
        if not isinstance(p, dict) or p.get('codec') != KEY or p.get('format_version') != 1 or (not isinstance(p.get('params'), dict)):
            raise ValueError('invalid Gorilla native format/configuration')
        if set(p['params']) != {'path'} or p['params']['path'] not in {'canonical', 'optimized'}:
            raise ValueError('invalid Gorilla execution path')
        channel, start, stop = (p.get('channel'), p.get('row_start'), p.get('row_stop'))
        if any((type(x) is not int for x in (channel, start, stop))) or not 0 <= channel < channels or (not 0 <= start <= stop <= t['shape'][0]) or (stop - start > MAX_SAMPLES) or (start == stop and t['shape'][0] != 0):
            raise ValueError('invalid Gorilla chunk span/channel')
        raw = payload(p)
        if len(raw) < 2 or int.from_bytes(raw[:2], 'big') != stop - start:
            raise ValueError('Gorilla raw sample count mismatch')
        groups.setdefault(channel, []).append((start, stop))
    if set(groups) != set(range(channels)):
        raise ValueError('missing Gorilla channels')
    for spans in groups.values():
        end = 0
        if t['shape'][0] == 0 and spans != [(0, 0)]:
            raise ValueError('duplicate empty Gorilla chunks')
        for start, stop in sorted(spans):
            if start != end:
                raise ValueError('Gorilla partition gap or overlap')
            end = stop
        if end != t['shape'][0]:
            raise ValueError('incomplete Gorilla partition')
    if 'mask' in roles:
        c = roles['mask']
        if c['dtype'] not in {'|u1', '|b1'} or c['shape'] != v['shape'] or (not isinstance(c.get('parts'), list)) or (len(c['parts']) != 1):
            raise ValueError('invalid Gorilla raw mask')
        p = c['parts'][0]
        if p.get('codec') != 'raw-store' or p.get('format_version') != 1 or p.get('params') != {} or any((p.get(k) != c[k] for k in ('dtype', 'shape', 'order'))) or (len(payload(p)) != checked_array(c)):
            raise ValueError('invalid Gorilla raw mask payload')
    end = 0
    for start, stop in sorted(intervals):
        if start != end:
            raise ValueError('Gorilla payload overlap/gap')
        end = stop
    if end != len(body):
        raise ValueError('unaccounted Gorilla body bytes')
    return components

def decode_object(desc, body, bridge):
    components = validate_joint_descriptor(desc, body)
    roles = {c['role']: c for c in components}
    t = np.empty(roles['T']['shape'], dtype='<i8')
    v = np.empty(roles['V']['shape'], dtype='<f8', order=roles['V']['order'])
    for p in sorted(desc['joint_parts'], key=lambda p: (p['channel'], p['row_start'])):
        start, stop, channel = (p['row_start'], p['row_stop'], p['channel'])
        times, values = bridge.decode_pairs(body[p['offset']:p['offset'] + p['length']], stop - start, p['params'])
        if channel == 0:
            t[start:stop] = times
        elif t[start:stop].tobytes() != times.tobytes():
            raise ValueError('Gorilla MTS columns disagree on shared timestamps')
        if v.ndim == 1:
            v[start:stop] = values
        else:
            v[start:stop, channel] = values
    output = {roles['T']['name']: t, roles['V']['name']: v}
    if 'mask' in roles:
        c = roles['mask']
        p = c['parts'][0]
        raw = body[p['offset']:p['offset'] + p['length']]
        source = np.frombuffer(raw, dtype=c['dtype']).reshape(c['shape'], order=c['order'])
        restored = source.copy(order=c['order'])
        output[c['name']] = restored
    return TimeSeriesObject(output, desc['schema'])
