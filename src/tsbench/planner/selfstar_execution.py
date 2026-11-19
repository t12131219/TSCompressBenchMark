"""Execution inputs for selected SElf* batch and native finalized-block routes."""
from ..assets import content_id, require
from .selfstar import (BLOCK, CHECKS, DTYPE_ID, HEADER, INPUT_REJECTIONS, NAN, PLUGIN, case_inputs,
                       fixture, plan_selfstar, schema_bytes, sha)

PROTOCOL = 'selfstar-ordered-object/1'
LIVE = 'selfstar-incremental'
TOOL, TARGET = 'selfstar-ordered-direct', 'tsbench_selfstar_ordered_control'
TOOL_SOURCE = 'plugins/codecs/selfstar-batch/ordered_control.cpp'
SOURCES = (TOOL_SOURCE,'src/tsbench/planner/selfstar_execution.py','src/tsbench/planner/selfstar.py',
           'src/tsbench/application/selfstar_execution.py','src/tsbench/qualification/selfstar_wire.py')
ROUTES = {(4,PLUGIN):PLUGIN, (4,LIVE):LIVE}
LIVE_METHOD = {'tool':TOOL,'mode':'native_add_finish_and_drained_read','scope':'finalized_blocks_not_online_stream'}
PARITY, READ, STATE, LIMITS = 'selfstar-parity', 'selfstar-reader', 'selfstar-state', 'selfstar-limits'
ABI_ENCODE, ABI_DECODE, LIVE_ENCODE = 'encode-columns','decode-columns','selfstar-live-encode'
MUTATIONS = ('frame-truncated','block-truncated','zero-bit-length','oversize-bit-length','trailing-byte','zero-values','unsupported-dtype')


def is_selfstar(slot):
    return slot.get('protocol')==PROTOCOL


def frame_limit(width, count, schema_size):
    return HEADER.size+schema_size+sum(4+((min(BLOCK,count-r)+1)*(width+28)+395+7)//8 for r in range(0,count,BLOCK))


def operations(slot):
    if slot['expected_status']:
        return [(ABI_ENCODE,None)]
    live = slot['method']==LIVE
    ops = [(LIVE_ENCODE,TOOL)] if live else [(ABI_ENCODE,None)]
    ops += [(PARITY,TOOL),(READ,TOOL)]
    if not live:
        ops.append((ABI_DECODE,None))
    if slot['count']>BLOCK:
        ops.append((STATE,TOOL))
    if slot['name']=='fixture-1591':
        ops.append((LIMITS,TOOL))
        if not live:
            ops.extend((op,None) for op in MUTATIONS)
    return ops


def selfstar_inputs(root):
    from .batch_execution import BatchInput

    bundle,weather = plan_selfstar(root)
    products, binds = {}, {}
    positives, rejected, controlled = {}, {}, {}

    def add(method,width,name,plain,*,status=0,lineage=None):
        schema = schema_bytes(width,name)
        dtype = 5 if name=='unsupported-dtype' else DTYPE_ID[width]
        n = len(plain)//(width//8)
        require(n*(width//8)==len(plain), 'invalid SElf* plain extent')
        body = {'protocol':PROTOCOL,'method':method,'width':width,'dtype':dtype,'count':n,'name':name,
                'lineage':lineage,'original':{'bytes':len(plain),'sha256':sha(plain),'schema_bytes':len(schema),'schema_sha256':sha(schema)},
                'expected_status':status,'options':{'block_values':1000} if name=='unsupported-block-option' else {},
                'parts':{'frame':frame_limit(width,n,len(schema))} if not status else {}}
        sid = content_id(body)
        require(sid not in products,'duplicate SElf* execution input')
        products[sid] = {**body,'product_slot':sid},BatchInput(schema,(plain,))
        return sid

    for method in (PLUGIN,LIVE):
        positives[method],controlled[method] = [], []
        for spec,(width,name,plain) in zip(bundle['objects'],case_inputs(bundle['fixtures'],weather),strict=True):
            require(sha(plain)==spec['input']['sha256'] and (width,name)==(spec['width'],spec['case']), 'SElf* original definition differs')
            lineage = bundle['window'] if name=='weather-co2-heldout' else spec['input']
            sid = add(method,width,name,plain,lineage=lineage)
            positives[method].append(sid)
            if name=='fixture-1591': controlled[method].append(sid)
    for width in (32,64):
        for tag,bits in zip(('qnan','snan'),NAN[width],strict=True):
            name = f'f{width}-{tag}-tail'
            rejected[name] = add(PLUGIN,width,name,fixture(width,BLOCK)+bits.to_bytes(width//8,'little'),status=INPUT_REJECTIONS[name])
    for name,raw in [('empty',b''),('unsupported-dtype',b'\0'*4),('unsupported-block-option',fixture(32,1))]:
        rejected[name] = add(PLUGIN,64 if name=='empty' else 32,name,raw,status=INPUT_REJECTIONS[name])
    require(set(rejected)==INPUT_REJECTIONS.keys(), 'incomplete SElf* input rejections')
    for c in bundle['cases']:
        route,check = c['route'],c['check']
        all_pos = positives[route]
        ordered = [sid for sid in all_pos if products[sid][0]['count']>BLOCK]
        selected = {
            'block_boundary_512_empty_tail':all_pos+[rejected['empty']],
            'bits_and_canonical_nan_policy':all_pos+[sid for n,sid in rejected.items() if 'nan-tail' in n],
            'block_reset_order':ordered,'independent_native_compare':all_pos,
            'exception_or_domain_reject':list(rejected.values())+controlled[route],
            'add_finish_and_replay_bits':all_pos,'state_reset_and_exception':ordered,
            'full_finalized_block_recovery':all_pos,'incremental_state_bounds':controlled[route],
        }[check]
        binds[c['case_id']] = bundle['bundle_id'],selected
    require(len(binds)==sum(map(len,CHECKS.values())), 'SElf* obligation denominator differs')
    return products,binds


def check_selfstar_slots(plan):
    slots = [s for s in plan['slots'] if is_selfstar(s)]
    require(len(slots)==25 and {s['method'] for s in slots}=={PLUGIN,LIVE},'SElf* protocol slot coverage differs')
    for m in (PLUGIN,LIVE):
        rows = [s for s in slots if s['method']==m and not s['expected_status']]
        require({(s['width'],s['name'],s['count']) for s in rows}==
                {(w,f'fixture-{n}',n) for w in (32,64) for n in (1,512,1591,2049)}|{(64,'weather-co2-heldout',1543)} and len(rows)==9,
                'SElf* ordered object denominator differs')
        for s in rows:
            require(s['parts']=={'frame':frame_limit(s['width'],s['count'],s['original']['schema_bytes'])} and
                    s['count']*(s['width']//8)==s['original']['bytes'] and s['dtype']==DTYPE_ID[s['width']] and not s['options'],
                    'SElf* ordered product bounds differ')
    bad = [s for s in slots if s['expected_status']]
    require({s['name']:s['expected_status'] for s in bad}==INPUT_REJECTIONS and all(s['method']==PLUGIN and not s['parts'] for s in bad),
            'SElf* rejection coverage differs')
