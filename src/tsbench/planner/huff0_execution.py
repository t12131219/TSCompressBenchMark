"""Binding of FEC1 frames and ETB1 model/block products to one ledger."""
from ..assets import canonical_bytes, content_id, require
from . import huff0_bmi2 as bmi2
from .huff0 import (BLOCK, CHECKS, CONFIG, CONTROL, ENVELOPE, FEC, FEC_REJECTIONS, INPUT_REJECTIONS,
                    NONEMPTY_FEC_REJECTIONS, PLUGIN, RECORD, TABLE, TABLE_REJECTIONS, fec_inputs,
                    plan_huff0, ref, table_inputs, train_input)

PROTOCOL = 'huff0-bound-v1'
TOOL, TARGET = 'huff0-native-direct', CONTROL
SHARED = 'huff0-shared-table'
ROUTES = {(29, PLUGIN): PLUGIN, (29, SHARED): SHARED}
METHOD = {'wire':'ETB1', 'model_binding':'sha256-sidecar-v1', 'block_bytes':BLOCK}
SOURCES = (CONFIG, 'tests/native/huff0_control.cpp', 'cmake/development-tests.cmake',
           'src/tsbench/planner/huff0.py', 'src/tsbench/planner/huff0_execution.py',
           'src/tsbench/application/huff0_execution.py', 'src/tsbench/qualification/huff0.py')
SIDECAR_LIMIT = 4096


def is_huff0(slot):
    return slot.get('protocol') == PROTOCOL


def fec_schema(name):
    return canonical_bytes({'dtype':'u8','column':'v','case':name})


def fec_rejections(slot):
    return {**FEC_REJECTIONS, **(NONEMPTY_FEC_REJECTIONS if slot['modes'] else {})}


def operations(slot):
    if slot['expected_status']:
        return [('encode',None)]
    compare = [(bmi2.OPERATION,bmi2.TOOL)] if slot.get(bmi2.KEY) else []
    if slot['method']==PLUGIN:
        return [('encode',None),('fec-encode',TOOL),('fec-decode',TOOL),*compare,('decode',None),
                *((name,None) for name in fec_rejections(slot))]
    return [(name,bmi2.TOOL if name==bmi2.OPERATION else TOOL) for name in ('train','table-encode','train-alternate','load-alternate','table-decode',
                                    *([bmi2.OPERATION] if compare else []), *TABLE_REJECTIONS, *(['raw-mutation'] if slot['profile']=='synthetic' else []))]


def _parts(slot):
    if slot['expected_status']:
        return {}
    if slot['method']==PLUGIN:
        return {'frame':ENVELOPE.size+len(fec_schema(slot['name']))+FEC.size+
                len(slot['modes'])*RECORD.size+slot['input']['bytes']}
    return {'model':1024,'binding':SIDECAR_LIMIT,
            **{f'block-{i}':TABLE.size+x['bytes'] for i,x in enumerate(slot['blocks'])}}


def huff0_inputs(root, *, compare_bmi2=False):
    from .batch_execution import BatchInput

    bundle, data = plan_huff0(root)
    products, binds, fec, bad, tables = {}, {}, [], [], []

    def add(body, schema, columns):
        body = {'protocol':PROTOCOL, **body}
        if compare_bmi2 and not body['expected_status']:
            body[bmi2.KEY] = True
        body['parts'] = _parts(body)
        sid = content_id(body)
        require(sid not in products,'duplicate Huff0 execution input')
        products[sid] = {**body,'product_slot':sid},BatchInput(schema,tuple(columns))
        return sid

    for name,raw,window,modes in fec_inputs(data['test'],bundle['test_window']):
        fec.append(add({'method':PLUGIN,'name':name,'input':ref('frozen:'+name,raw), 'modes':modes,
                        'lineage':window,'dtype':2,'options':{},'expected_status':0},fec_schema(name),[raw]))
    for name,status in INPUT_REJECTIONS.items():
        raw = b'\0'*8
        bad.append(add({'method':PLUGIN,'name':name,'input':ref('frozen:'+name,raw),'modes':[], 'lineage':None,
                        'dtype':10 if status==1 else 2, 'options':{'table_log':9} if status==3 else {},
                        'expected_status':status},b'{}',[raw]))
    for name,streams,blocks,modes in table_inputs(data['test']):
        train = train_input(name,data['train'])
        tables.append(add({'method':SHARED,'profile':name,'streams':streams,'modes':modes,'expected_status':0,
                           'training':ref('frozen:'+name+'-training',train),
                           'blocks':[ref(f'frozen:{name}-block-{i}',b) for i,b in enumerate(blocks)],
                           'lineage':{'train':bundle['train_window'],'holdout':bundle['test_window'],
                                      'transform':bundle['transform']} if name=='weather-chronological' else None},
                          train,blocks))
    for case in bundle['cases']:
        slots = tables if case['route']==SHARED else fec + (bad if case['check']=='length_corruption_and_size_reject' else [])
        binds[case['case_id']] = bundle['bundle_id'],slots
    require(len(binds)==sum(map(len,CHECKS.values())), 'Huff0 obligation denominator differs')
    return products,binds


def input_bytes(slot):
    if slot['method']==PLUGIN:
        return slot['input']['bytes']+len(b'{}' if slot['expected_status'] else fec_schema(slot['name']))
    return slot['training']['bytes']+sum(x['bytes'] for x in slot['blocks'])


def check_slots(plan):
    rows = [s for s in plan['slots'] if is_huff0(s)]
    fec = [s for s in rows if s['method']==PLUGIN and not s['expected_status']]
    bad = [s for s in rows if s['expected_status']]
    tables = [s for s in rows if s['method']==SHARED]
    require(len(rows)==11 and len(fec)==5 and {s['name'] for s in fec}==
            {'empty','raw','rle','mixed-stored-branches','weather-heldout-u8'} and
            len(bad)==2 and {s['name']:s['expected_status'] for s in bad}==INPUT_REJECTIONS and
            all(s['method']==PLUGIN for s in bad), 'Huff0 FEC1 slot coverage differs')
    require(len(tables)==4 and {(s['profile'],s['streams']) for s in tables}==
            {(p,n) for p in ('synthetic','weather-chronological') for n in (1,4)} and
            all(len(s['blocks'])==len(s['modes'])==(5 if s['profile']=='synthetic' else 2) and
                s['training']['bytes']==BLOCK and all(0<=b['bytes']<=BLOCK for b in s['blocks']) for s in tables),
            'Huff0 ETB1 slot coverage differs')
    require(all((s.get(bmi2.KEY) is True if plan.get('suite')==bmi2.SUITE and not s['expected_status'] else bmi2.KEY not in s)
                for s in rows),'Huff0 portable comparison slot differs')
    require(all(s['parts']==_parts(s) and max([input_bytes(s),*s['parts'].values()])<=plan['limits']['file_bytes'] for s in rows),
            'Huff0 per-product byte ceilings differ')
