"""Freeze independent ZFP field, OpenMP and fixed-rate array lanes."""
from pathlib import PurePosixPath

from ..assets import content_id, require
from .batch_execution import BatchInput
from .zfp import (FIELD_PROFILES, PLUGIN, array_input, field_input, field_layout, pack, plan_zfp, ref, values)

FIELD, OMP, ARRAY = 'field-modes','openmp-encode','fixed-rate-array'
PROTOCOL = 'zfp-native-bound-v1'
METHODS = {m:{'codec':PLUGIN,'entry':e} for m,e in
           ((FIELD,'zn_encode_field / zn_decode_field'),(OMP,'zn_encode_field / zn_decode_field'),(ARRAY,'zn_array_*'))}
ROUTES = {(31,m):m for m in METHODS}
TOOL, OBSERVER = 'zfp-native-direct','zfp-openmp-observer'
TARGETS = {TOOL:'tsbench_zfp_native_control',OBSERVER:'tsbench_zfp_sealed_omp_control'}
THREAD_ENV = {'OMP_DYNAMIC':'FALSE','OMP_THREAD_LIMIT':'2'}
THREADS = {'serial':1,'1':1,'2':2}
SOURCES = ('plugins/codecs/zfp-reversible/native_control.cpp','plugins/codecs/zfp-reversible/CMakeLists.txt',
           'tests/native/zfp_omp_control.cpp','src/tsbench/planner/zfp_execution.py','src/tsbench/planner/zfp.py',
           'src/tsbench/application/zfp_execution.py','src/tsbench/qualification/zfp.py')
TYPES = {'i32':1,'i64':2,'f32':3,'f64':4}
MODES = {'reversible':0,'rate':1,'precision':2,'accuracy':3}


def identity(raw):
    r = ref('',raw)
    return {k:r[k] for k in ('bytes','sha256')}


def tool_paths(build):
    path = PurePosixPath(build['plugins'][PLUGIN]['library']['path'])
    return {n:path.with_name(t) for n,t in TARGETS.items()}


def is_zfp(slot):
    return slot.get('protocol')==PROTOCOL


def metadata(method,spec):
    def words(*xs):
        return (' '.join(map(str,xs))+'\n').encode('ascii')
    if method==ARRAY:
        return words('ZNARRAY1',spec['shape'][0],spec['requested_rate'],spec['effective_rate'])
    if method==OMP:
        return words('ZNFIELD1',4,1,0,0,spec['count'],1,1,1,0,0,0,0,0,spec['count'])
    layout = field_layout(spec)
    rank = len(spec['shape'])
    return words('ZNFIELD1',TYPES[spec['type']],rank,MODES[spec['mode']],spec['requested'],
                 *spec['shape'],*([1]*(4-rank)),*spec['strides'],*([0]*(4-rank)),layout['origin'],layout['span_count'])


def input_span(spec,raw):
    layout = field_layout(spec)
    span = [-8191]*layout['span_count']
    for i,v in zip(layout['offsets'],values(spec['type'],raw),strict=True):
        span[i] = v
    return pack(spec['type'],span)


def blobs(method,spec,raw=None):
    if method==FIELD:
        return {'input':input_span(spec,raw)}
    if method==OMP:
        return {'input':raw}
    start,_ = array_input(spec)
    return {'input':pack('f64',start),'patch':pack('f64',[spec['point_value'],*spec['range_values']])}


def _slot(method,spec,raw):
    meta = metadata(method,spec)
    input_refs = {k:identity(v) for k,v in blobs(method,spec,raw).items()}
    parts = {'metadata':len(meta)}
    if method==FIELD:
        parts.update(frame=1<<16,span=input_refs['input']['bytes'])
        if spec['id']=='rate-tail':
            parts['quality-original'] = len(raw)
    elif method==OMP:
        parts.update({f'frame-{k}':1<<18 for k in THREADS})
    else:
        parts.update(before=64,after=64,baseline=13*8,restored=13*8)
    body = {'protocol':PROTOCOL,'method':method,'spec':spec,'inputs':input_refs,'parts':parts}
    return {**body,'product_slot':content_id(body)}


def _specs(bundle,real):
    for f in bundle['fields']:
        yield FIELD,f,field_input(f,real)
    yield OMP,{**bundle['openmp'],'window':bundle['window'],'original':bundle['weather']},real
    yield ARRAY,bundle['array'],None


def plan_slots(root):
    bundle,real = plan_zfp(root)
    slots, by_method = {}, {m:[] for m in METHODS}
    for method,spec,raw in _specs(bundle,real):
        slot = _slot(method,spec,raw)
        sid = slot['product_slot']
        slots[sid] = slot,BatchInput(b'',() if raw is None else (raw,))
        by_method[method].append(sid)
    binds = {c['case_id']:(bundle['bundle_id'],by_method[c['route']]) for c in bundle['cases'] if c['route'] in METHODS}
    require(len(slots)==6 and len(binds)==15,'ZFP route or required obligation denominator differs')
    return slots,binds


def check_slots(plan):
    lanes = [s for s in plan['slots'] if is_zfp(s)]
    require([s['method'] for s in lanes]==[FIELD]*4+[OMP,ARRAY], 'ZFP lane closure differs')
    fields, omp, array = lanes[:4],lanes[4],lanes[5]
    for slot,(name,profile) in zip(fields,FIELD_PROFILES.items(),strict=True):
        f = slot['spec']
        require(f['id']==name and [f[k] for k in ('type','mode','shape','strides','requested','effective')]==list(profile) and
                0 <= f['max_observed_error'] <= 1,'ZFP frozen field mode differs')
        if name!='rate-tail':
            require(slot==_slot(FIELD,f,field_input(f,None)),'ZFP synthetic field input differs')
        else:
            n = 1029*8
            require(slot['parts']=={'metadata':len(metadata(FIELD,f)),'frame':1<<16,'span':n+32,'quality-original':n} and
                    f['input']['bytes']==n and slot['inputs']['input']['bytes']==n+32,'ZFP rate-tail extent differs')
    spec = omp['spec']
    require(spec['env']==THREAD_ENV and spec['count']==8192 and spec['chunk_blocks']==64 and
            [(p['policy'],p['threads']) for p in spec['profiles']]==list(THREADS.items()) and
            omp['inputs']=={'input':{k:spec['original'][k] for k in ('bytes','sha256')}} and
            omp['parts']=={'metadata':len(metadata(OMP,spec)),**{f'frame-{k}':1<<18 for k in THREADS}},
            'ZFP worker or same-field plan differs')
    require(array==_slot(ARRAY,array['spec'],None),'ZFP array input or metadata differs')
    require(all(max([*s['parts'].values(),*(x['bytes'] for x in s['inputs'].values())]) <= plan['limits']['file_bytes'] for s in lanes),
            'ZFP lane exceeds file limit')


def required_slots(ob,slots):
    return [s['product_slot'] for s in slots if is_zfp(s) and s['method']==ob['route']]


def supports_condition(ob):
    return (ob['kind'],ob['selection'],ob['route'],ob['check'])==('conditional',31,OMP,'native_block_work_on_two_threads')


def condition_slots(ob,slots):
    require(supports_condition(ob) and ob['condition_case']['criteria']==
            {'profiles':list(THREADS),'encoding_tids':list(THREADS.values()),'decode_on_caller':True,'same_field_work':True},
            'ZFP conditional worker policy differs')
    found = required_slots(ob,slots)
    require(len(found)==1,'ZFP worker evidence needs one same-field slot')
    return found


def steps(slot):
    method,spec = slot['method'],slot['spec']
    result = {}
    def add(label,op,mounts,outputs,*,tool=TOOL,env=None):
        cmd = [op] if tool==TOOL else []
        cmd += ['/inputs/'+m for m in mounts]
        if tool==OBSERVER:
            cmd += [str(spec['count']),op,str(spec['chunk_blocks']),'frame']
        result[label] = {'tool':tool,'argv':cmd,'mounts':mounts,'outputs':outputs,'env':env or {}}
    if method==FIELD:
        op = 'field-encode-controls' if spec['id']=='rate-tail' else 'field-encode'
        add('encode',op,{'metadata':'metadata','input':'input'},{'frame':'frame'})
        add('restore','field-decode',{'metadata':'metadata','wire':'frame'},{'span':'span'})
    elif method==ARRAY:
        add('update','array-update',{'metadata':'metadata','input':'input','patch':'patch'},{'before':'before','after':'after'})
        add('reopen-before','array-decode',{'metadata':'metadata','wire':'before'},{'span':'baseline'})
        add('reopen-after','array-decode-controls',{'metadata':'metadata','wire':'after'},{'span':'restored'})
    else:
        for key in THREADS:
            add('encode-'+key,key,{'input':'input'},{'frame':'frame-'+key},tool=OBSERVER,env=THREAD_ENV)
        for key in THREADS:
            add('restore-'+key,'field-decode',{'metadata':'metadata','wire':'frame-'+key},{'span':None})
    return result


def operations(slot):
    return [(label,step['tool']) for label,step in steps(slot).items()]
