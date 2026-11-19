"""Independent structure checks and reproducible negative inputs for linear envelopes."""
import struct

from ..assets import require
from ..planner.alp import SPECIAL, SPECIAL_POS
from ..planner.gorilla import sha
from .alp_wire import analyze, corrupt_positions
from .lzbench import zstd_frame
from . import typed_batch as typed
from . import xz_batch as xz
from . import pcodec_batch as pco
from ..planner.xz_batch import METHOD as XZ_METHOD

HEADER = struct.Struct('<8sIQIQ')
MAGIC = {'alp-auto': b'BMKALP\x01\0', 'zstd': b'BMKZST\x01\0', XZ_METHOD:xz.MAGIC, **typed.MAGIC, **pco.MAGIC}


def parts(wire, slot):
    c = slot['original']
    start = HEADER.size+c['schema_bytes']
    col, = c['columns']
    require(start < len(wire) <= slot['max_frame_bytes'], 'linear envelope exceeds declared bound')
    require(HEADER.unpack_from(wire) == (MAGIC[slot['method']], col['dtype'], col['count'], c['schema_bytes'], len(wire)-start),
            'linear envelope shape differs')
    schema, payload = wire[HEADER.size:start], wire[start:]
    require(sha(schema) == c['schema_sha256'], 'linear envelope schema differs')
    return schema, payload


def wrap(slot, schema, payload, *, count=None, dtype=None):
    col, = slot['original']['columns']
    n = col['count'] if count is None else count
    return HEADER.pack(MAGIC[slot['method']], col['dtype'] if dtype is None else dtype, n, len(schema), len(payload))+schema+payload


def inspect_linear(wire, slot, original=None, *, upstream=False):
    _, payload = parts(wire, slot)
    c = slot['original']
    if slot['method'] == 'alp-auto':
        col, = c['columns']
        width = {9:32, 10:64}[col['dtype']]
        layout = analyze(payload, original, width, count=col['count'])
        expected = slot['wire_checks']
        if 'vector_count' in expected and expected['vector_count'] is not None:
            require(layout['coded_vectors'] + layout['raw_vectors'] == expected['vector_count'],
                    'ALP vector boundary differs')
        if 'rowgroup_kinds' in expected:
            require(layout['rowgroup_kinds'] == expected['rowgroup_kinds'] and
                    [layout[k] for k in ('coded_decimal_vectors','coded_rd_vectors','raw_vectors')] ==
                    expected['decimal_rd_raw_vectors'], 'ALP native branch coverage differs')
        if expected.get('special_exception_bits'):
            require(layout['special_exception_bits'] == [{'index':i,'bits':hex(v)} for i,v in zip(SPECIAL_POS,SPECIAL[width],strict=True)],
                    'ALP decimal exception sidecar did not retain the expected bits')
    elif slot['method'] in typed.MAGIC:
        layout = typed.inspect_payload(slot, payload)
    elif slot['method'] == XZ_METHOD:
        layout = xz.inspect_xz(slot, payload)
    elif slot['method'] in pco.MAGIC:
        layout = pco.inspect_pcodec(slot, payload)
    else:
        layout = zstd_frame(payload)
        require(layout['content_size'] == c['column_bytes'][0] and type(layout['window']) is int and
                0 <= layout['window'] <= 65536 and layout['dictionary_id'] == 0 and layout['checksum'] is False,
                'Zstd frame differs from the level-3 dictionary-free one-block profile')
    if upstream:
        require(slot['method'] == 'zstd' and slot['upstream_zstd'], 'unexpected upstream frame')
    return {'native_payload_bytes': len(payload), 'native_payload_sha256': sha(payload), 'wire':layout}


def mutations(wire, slot):
    schema, payload = parts(wire, slot)
    col, = slot['original']['columns']
    if slot['method'] == 'alp-auto':
        pos = []
        analyze(payload, None, {9:32,10:64}[col['dtype']], positions=pos, count=col['count'])
        result = {label:wrap(slot,schema,changed) for label,(_,changed) in corrupt_positions(payload,pos).items()}
    elif slot['method'] in typed.MAGIC:
        result = typed.mutated_inputs(wire,slot,schema,payload,lambda body,**kw:wrap(slot,schema,body,**kw))
    elif slot['method'] == XZ_METHOD:
        result = xz.reject_xz(slot,payload,lambda body,**kw:wrap(slot,schema,body,**kw))
    elif slot['method'] in pco.MAGIC:
        result = pco.reject_pcodec(wire,slot,payload,lambda body,**kw:wrap(slot,schema,body,**kw))
    else:
        n = col['count']
        result = {'wrong_output_count': wrap(slot,schema,payload,count=(n-1 if n else 1)),
                  'truncated_payload': wrap(slot,schema,payload[:-1])}
    require(set(result) == set(slot['reject_decodes']) and wire not in result.values(), 'linear negative definitions differ')
    return result


def check_info(slot, layout, encode, decode):
    if slot['method'] in typed.MAGIC:
        typed.verify_typed_info(slot,layout,encode,decode)
        return
    if slot['method'] == XZ_METHOD:
        xz.verify_xz_info(layout,encode,decode)
        return
    if slot['method'] in pco.MAGIC:
        pco.verify_pcodec_info(slot,encode,decode)
        return
    alp = slot['method'] == 'alp-auto'
    for op, info, backend in (('encode',encode,'alpn-auto-encoder' if alp else 'ln-zstd-baseline'),
                              ('decode',decode,'scalar-unfused' if alp else 'ln-zstd-baseline')):
        require(info['operation'] == op and info['mode'] == 'batch' and info['backend'] == backend and
                type(info['threads']) is int and info['threads'] == 1, 'linear worker operation/backend differs')
    if alp:
        require(all(encode[k] == layout[k] for k in ('alp_groups','rd_groups','raw_groups','coded_vectors','raw_vectors')) and
                decode['requested_backend'] == 'scalar-unfused' and decode['rd_vectors'] == layout['coded_rd_vectors'] and
                decode['scalar_vectors'] == layout['coded_decimal_vectors'] and decode['raw_vectors'] == layout['raw_vectors'],
                'ALP counters differ from independent ALN1 structure')
    else:
        require(encode['level'] == 3 and encode['blocks'] == decode['blocks'] == 1 and
                encode['fallback'] is decode['fallback'] is False, 'Zstd baseline effective profile differs')
