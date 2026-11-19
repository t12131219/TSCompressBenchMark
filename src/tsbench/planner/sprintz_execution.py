"""Bind native Sprintz batch and compressed-domain query to distinct products."""
from zlib import crc32

from ..assets import canonical_bytes, content_id, require
from ..qualification.sprintz import reductions
from .sprintz import CHECKS, DECODE_REJECTIONS, WORKER_REJECTIONS, WORKER_SCHEMA, plain, plan_sprintz, ref

PLUGIN, QUERY = 'sprintz-fire', 'sprintz-fire-query'
TOOL, TARGET = 'sprintz-native-direct', 'tsbench_sprintz_control'
PROTOCOL = 'sprintz-fire-bound-v1'
ROUTES = {(19,'fire-batch'):PLUGIN,(19,'query'):QUERY}
ABI_METHOD = {'plugin':PLUGIN,'options':{}}
QUERY_METHOD = {'wire':'SFB1','algorithm':'fire','path':0,'mode':'auto','operation':'unsigned_channel_count_sum_max'}
SOURCES = ('src/tsbench/planner/sprintz_execution.py','src/tsbench/application/sprintz_execution.py',
           'src/tsbench/planner/sprintz.py','src/tsbench/qualification/sprintz.py',
           'tests/native/sprintz_control.cpp','cmake/development-tests.cmake')
RESULT_LIMIT = 8192
NATIVE_BACKEND = 'repaired-reference-fix1'
ISA_SKIP = 'SKIP: Sprintz requires AVX2/BMI/BMI2/LZCNT/POPCNT'
SCHEMA = canonical_bytes(WORKER_SCHEMA)


def is_sprintz(slot):
    return slot.get('protocol') == PROTOCOL


def native_limit(slot):
    s = slot['shape']
    # SFB1 + RLE header + literals/packed value bytes + two block paddings,
    # worst-case run length tags and group width headers. The native unframer
    # also imposes a separate broad 4 * message-limit cap.
    bits = 3 if s['width']==8 else 4
    groups = s['count']//(8*s['dims'])+1
    group_overhead = (2*s['dims']*bits+7)//8+18
    return min(32+4*s['message_limit_bytes'],40+slot['original']['bytes']+groups*group_overhead)


def file_limit(slot):
    return max([RESULT_LIMIT,input_bytes(slot),*slot['parts'].values()])


def input_bytes(slot):
    return slot['original']['bytes'] + (2 if slot['expected_status'] else len(SCHEMA) if slot['abi'] else 0)


def operations(slot):
    if slot['expected_status']:
        return [('encode',None)]
    ops = [('sfb1-encode',TOOL)]
    if slot['abi']:
        ops.append(('encode',None))
    if slot['method']==QUERY:
        ops.append(('sfb1-query',TOOL))
    ops.append(('sfb1-decode',TOOL))
    if slot['abi']:
        ops += [('decode',None),*((name,None) for name in DECODE_REJECTIONS)]
    if slot['method']==PLUGIN and slot['shape']['name']=='worker-cap':
        ops.append(('native-limits',TOOL))
    return ops


def sprintz_inputs():
    from .batch_execution import BatchInput

    bundle = plan_sprintz()
    products, slots, bad, binds = {}, {}, {}, {}

    def add(body,raw,schema):
        fields = {'protocol':PROTOCOL, **body}
        sid = content_id(fields)
        require(sid not in products, 'duplicate Sprintz frozen input')
        products[sid] = {**fields,'product_slot':sid},BatchInput(schema,(raw,))
        return sid

    for method in (PLUGIN,QUERY):
        for shape in bundle['shapes']:
            name, width, dims, count = (shape[k] for k in ('name','width','dims','count'))
            original = plain(name,width,dims,count)
            require(ref('generated:'+name,original)==shape['original'], 'Sprintz frozen source differs')
            abi = method==PLUGIN and bool(shape['worker_frame'])
            body = {'method':method,'name':name,'shape':shape,'abi':abi,'dtype':2 if width==8 else 4,'expected_status':0,
                    'original':shape['original'],'raw_crc32':crc32(original),
                    'oracle':reductions(original,width,dims) if method==QUERY else None}
            body['parts'] = {'frame':native_limit(body)+(32+len(SCHEMA) if abi else 0),
                             **({'reductions':RESULT_LIMIT} if method==QUERY else {})}
            slots[method,name] = add(body,original,SCHEMA if abi else b'')
    for name, status in WORKER_REJECTIONS.items():
        dtype, raw = (10,bytes(8)) if name=='f64' else (4,bytes(65538))
        bad[name] = add({'method':PLUGIN,'name':name,'shape':None,'abi':True,'dtype':dtype,'expected_status':status,
                         'original':ref('generated:'+name,raw),'parts':{}},raw,b'{}')
    for case in bundle['cases']:
        route, check = case['route'], case['check']
        method = ROUTES[19,route]
        ids = [slots[method,name] for name in CHECKS[route][check]]
        if check=='channel_count_and_size_reject':
            ids += list(bad.values())
        binds[case['case_id']] = bundle['bundle_id'],ids
    return products,binds


def check_slots(plan):
    products,by_case = sprintz_inputs()
    require([s for s in plan['slots'] if is_sprintz(s)]==[s for s,_ in products.values()],
            'Sprintz product slots differ from frozen native fixtures')
    require(all(plan['case_products'].get(cid)=={'bundle_id':bundle,'product_slots':ids}
                for cid,(bundle,ids) in by_case.items()), 'Sprintz per-case product binding differs')
