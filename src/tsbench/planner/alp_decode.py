"""Bind backend requests to one standalone ALN1 artifact per selected fixture."""
from pathlib import PurePosixPath

from ..assets import content_id, require
from .alp import AVX512, ID, METHOD as PLUGIN, REAL, RG, fixtures, plan_alp, sha
from .batch_execution import BatchInput

METHOD = 'alp-decode-backends'
PROTOCOL = 'alp-decode-backends-bound-v1'
ROUTE = (9,'decode-backends')
TOOL, TARGET = 'alp-decode-direct','tsbench_alp_decode_control'
REQUESTS = tuple(ID)[:5]
METHODS = {METHOD:{'codec':PLUGIN,'entry':'alpn_decompress_ex','encode_mode':'ALPN_AUTO','requests':list(REQUESTS)}}
CONDITIONS = {'avx2_decimal_with_native_work':'falp-avx2',
              'avx512bw_decimal_with_effective_dispatch':AVX512}
SOURCES = ('plugins/codecs/alp-auto/CMakeLists.txt','plugins/codecs/alp-auto/decode_control.c',
           'src/tsbench/planner/alp_decode.py','src/tsbench/application/alp_decode.py','src/tsbench/qualification/alp.py')


def tool_path(build):
    return PurePosixPath(build['plugins'][PLUGIN]['library']['path']).with_name(TARGET)


def is_decode(slot):
    return slot.get('protocol')==PROTOCOL


def identity(raw):
    return {'bytes':len(raw),'sha256':sha(raw)}


def _slot(fixture):
    n = fixture['count']
    size = fixture['input_bytes']
    require(n>0 and fixture['width'] in (32,64) and size==n*(fixture['width']//8), 'invalid frozen ALP shape')
    body = {'protocol':PROTOCOL,'method':METHOD,'fixture':fixture,
            'parts':{'frame':size+(n+RG-1)//RG+16}}
    return {**body,'product_slot':content_id(body)}


def original(slot):
    f = slot['fixture']
    return {'bytes':f['input_bytes'],'sha256':f['input_sha256']}


def plan_slots(root):
    bundle, raw = plan_alp(root)
    slots, names, binds = {}, {}, {}
    require(bundle['requests']==list(REQUESTS),'ALP request denominator differs')
    for f in bundle['fixtures']:
        slot = _slot(f)
        name,sid = f['name'],slot['product_slot']
        require(identity(raw[name])==original(slot),'ALP original identity differs')
        names[name] = sid
        slots[sid] = slot,BatchInput(b'',(raw[name],))
    for c in bundle['cases']:
        if (c['selection'],c['route'])==ROUTE:
            binds[c['case_id']] = bundle['bundle_id'],[names[f['name']] for f in c['criteria']['fixtures']]
    require(len(slots)==9 and len(binds)==4,'ALP decode fixture or obligation denominator differs')
    return slots,binds


def check_slots(plan):
    rows = [s for s in plan['slots'] if is_decode(s)]
    baseline = {s['name']:s for s in plan['slots'] if s['method']==PLUGIN and s.get('lineage',{}).get('width') in (32,64)}
    expected = {f'f{w}-{label}':identity(raw) for w in (32,64) for label,raw,_ in fixtures(w)}
    require(f'f64-{REAL}' in baseline,'ALP weather tail is absent from the batch inputs')
    expected[f'f64-{REAL}'] = {'bytes':1029*8,'sha256':baseline[f'f64-{REAL}']['original']['column_sha256'][0]}
    require(len(rows)==9 and set(baseline)==set(expected) and {s['product_slot']:s for s in rows}==
            {s['product_slot']:s for s in (_slot(r['lineage']) for r in baseline.values())} and
            all(original(s)==expected[s['fixture']['name']] and s['parts']['frame']<=plan['limits']['file_bytes'] for s in rows),
            'ALP decode fixtures or frame bounds differ from the frozen batch inputs')


def supports_condition(ob):
    return ob['kind']=='conditional' and (ob['selection'],ob['route'])==ROUTE and ob['check'] in CONDITIONS


def condition_slots(ob, slots):
    require(supports_condition(ob),'unexpected ALP decode condition')
    case = ob['condition_case']
    require(case['criteria']['width']==64 and case['criteria']['backend']==CONDITIONS[ob['check']] and
            case['criteria']['fixture']=='mixed-decimal-raw' and case['criteria']['branch']=='decimal',
            'ALP SIMD condition definition differs')
    found = [s['product_slot'] for s in slots if is_decode(s) and s['fixture']['name']=='f64-mixed-decimal-raw']
    require(len(found)==1,'ALP SIMD condition needs exactly one common mixed frame')
    return found


def operations(_slot):
    return [('encode',TOOL),*((request,TOOL) for request in REQUESTS)]
