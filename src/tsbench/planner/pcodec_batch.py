"""Standalone pcodec batch products drawn from the frozen native case bundle."""
import struct

from ..assets import content_id, require
from .gorilla import sha
from .pcodec import BATCH_CHECKS, C_NATIVE, HEADER, SOURCE, TRAFFIC, TYPES, identity, plan_pcodec

ROUTES = {(11,'source-auto'):SOURCE, (11,'c-native-auto'):C_NATIVE}
METHODS = {method:{'plugin':method,'options':{}} for method in ROUTES.values()}
TOOL = 'pcodec-batch-direct'
TARGET = 'tsbench_pcodec_batch_control'
POLICY = 'configs/suites/m3_first_batch_native_v2/pcodec-batch-execution.json'
SOURCES = ('plugins/codecs/pcodec/batch_control.c', 'src/tsbench/planner/pcodec.py',
           'src/tsbench/planner/pcodec_batch.py', 'src/tsbench/qualification/pcodec_batch.py')
BAD_FRAMES = {'envelope_trailing':5, 'payload_trailing':5, 'payload_truncated':5,
              'missing_payload_metadata':5, 'count_too_large':5, 'other_format':5}
F16_REJECTION = 'f16-extreme-bits'


def pcodec_inputs(root):
    from .batch_execution import BatchInput

    plan, original = plan_pcodec(root)
    originals = {name:(dtype,data) for name,dtype,data in original}
    products, by_method = {}, {}
    for method,specs in plan['batch'].items():
        require(method in METHODS, 'unknown pcodec tool route')
        ids = by_method[method] = {}
        for fixture in specs:
            name = fixture['case']
            dtype, data = originals[name]
            abi, native, code = TYPES[dtype]
            n = fixture['count']
            schema = fixture['schema'].encode('ascii')
            require(fixture['dtype'] == dtype and identity(data) == fixture['plain'] and
                    len(data) == n * struct.calcsize(code) <= 8192, 'pcodec batch fixture source differs')
            rejected = fixture['frame'] is None
            require(rejected == (method == C_NATIVE and dtype == 'f16' and name == F16_REJECTION),
                    'pcodec f16 rejection scope differs')
            negatives = {} if rejected else {**BAD_FRAMES, **({'count_too_small':7} if n else {})}
            body = {'method':method, 'name':name, 'lineage':{'case':fixture,'window':plan['window'] if name == TRAFFIC else None},
                    'expected_status':1 if rejected else 0, 'original':{'columns':[{'dtype':abi,'count':n}],
                    'column_bytes':[len(data)],'column_sha256':[sha(data)],'schema_bytes':len(schema),'schema_sha256':sha(schema)},
                    'max_frame_bytes':0 if rejected else HEADER.size+len(schema)+len(data)+65536,
                    'wire_checks':{'native_type':native},'reject_decodes':list(negatives),'reject_statuses':negatives,
                    'upstream_zstd':False}
            sid = ids[name] = content_id(body)
            products[sid] = {**body,'product_slot':sid}, BatchInput(schema,(data,))
        require(ids.keys() == originals.keys(), 'pcodec standalone fixture denominator differs')
    binds = {}
    for case in plan['cases']:
        route = case['route']
        if route not in BATCH_CHECKS:
            continue
        method = ROUTES[(11,route)]
        rows = by_method[method]
        if case['check'] in {'explicit_f16_rejection','f16_special_bits'}:
            names = [F16_REJECTION]
        else:
            names = [name for name in rows if method == SOURCE or name != F16_REJECTION]
        binds[case['case_id']] = plan['bundle_id'], [rows[n] for n in names]
    require(len(binds) == sum(map(len,BATCH_CHECKS.values())) and
            {sid for _,ids in binds.values() for sid in ids} == set(products), 'pcodec standalone obligation scope differs')
    return products, binds
