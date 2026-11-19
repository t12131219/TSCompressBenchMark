"""Validation of Titchy v2 and the trusted reversible 1-D ZFP envelope."""
from ..assets import require
from ..planner.gorilla import sha
from ..planner.titchy_native import BATCH_POLICY, LIMIT
from ..planner.typed_batch import TITCHY, ZFP
from .titchy_wire import decode_tchy, native_bound

MAGIC = {TITCHY:b'BMKTCH\x01\0',ZFP:b'BMKZFP\x01\0'}


def inspect_payload(slot, payload):
    source, method = slot['original'], slot['method']
    col, = source['columns']
    n = col['count']
    if method == TITCHY:
        width = {2:8,4:16,6:32,8:64}[col['dtype']]
        bound = native_bound(n,width,BATCH_POLICY['chunk'],BATCH_POLICY['split'])
        require(len(payload) <= bound, 'Titchy native bound exceeded')
        data,splits = decode_tchy(payload,width,n,BATCH_POLICY)
        require([sha(data)] == source['column_sha256'], 'independent Titchy reader disagrees with original bits')
        return {'native_bound':bound,'count':n,'width':width,'splits':splits,'independently_decoded_sha256':sha(data)}
    require(method == ZFP and n > 0 and col['dtype'] in {5,7,9,10} and len(payload)%8 == 0,
            'ZFP reversible envelope count, dtype or word extent differs')
    # The matching dtype/count are essential inputs to the raw kernel. No unsafe raw fuzz path.
    return {'count':n,'dtype':col['dtype'],'native_word_bytes':8,'native_words':len(payload)//8,
            'raw_payload_scope':'trusted_payload_with_locked_schema'}


def mutated_inputs(wire, slot, schema, payload, rewrap):
    if slot['method'] == TITCHY:
        n = slot['original']['columns'][0]['count']
        return {'truncated':wire[:-1], 'outer_trailing':wire+b'\0', 'count_mismatch':rewrap(payload,count=n+1),
                'count_limit':rewrap(payload,count=LIMIT+1), 'dtype_mismatch':rewrap(payload,dtype=10),
                'unexpected_endian':rewrap(payload[:7]+b'\x01'+payload[8:]), 'native_trailing':rewrap(payload+b'\0')}
    require(slot['method'] == ZFP, 'unknown typed envelope')
    return {'truncated':wire[:-1], 'trailing':wire+b'\0', 'empty':rewrap(payload,count=0),
            'dtype':rewrap(payload,dtype=8), 'unaligned':rewrap(payload[:-1]), 'count_limit':rewrap(payload,count=1<<28)}


def verify_typed_info(slot, layout, encode, decode):
    method = slot['method']
    for op, info in (('encode',encode),('decode',decode)):
        expected = {'threads':1,'mode':'batch','operation':op}
        if method == TITCHY:
            expected.update(backend='titchy-c11',entry=f'titchy_c_{op}')
        else:
            expected.update(backend='zfp-c11-serial',entry=f'zn_{op}',quality='reversible')
        require(info == expected and type(info['threads']) is int, 'typed batch effective native entry differs')


def titchy_direct_observation(slot, inspection, bytes_observed):
    n = slot['original']['columns'][0]['count']
    cap = 2 if n else 0
    return {'count':n,'bound':inspection['wire']['native_bound'],'bytes':bytes_observed,
            'encode_capacity_status':cap,'decode_capacity_status':cap,'decode_quota_status':cap}
