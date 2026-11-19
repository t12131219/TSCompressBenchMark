"""Frozen ZFP development cases: raw field, actual OpenMP work and mutable array."""
from hashlib import sha256
from itertools import product
import math
from pathlib import Path
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from .corpus_windows import bind_window, read_tv_window

CONFIG = 'configs/suites/dev_zfp_v1/cases.json'
TEST, REPORT, PLUGIN = 'tsbench.worker.zfp.recovery', 'zfp-control.json', 'zfp-reversible'
DIAGNOSTIC = 'tsbench_zfp_omp_control'
WEATHER = 'zfp-weather-original.f64'
HEADER, MAGIC = struct.Struct('<8sIQIQ'), b'BMKZFP\1\0'
TYPE_LAYOUT = {'i32': (5, 'i'), 'i64': (7, 'q'), 'f32': (9, 'f'), 'f64': (10, 'd')}
BATCH_INPUT_REJECTIONS = {'empty': 1, 'wrong_dtype': 1, 'unknown_options': 3}
BATCH_WIRE_REJECTIONS = {'truncated': 5, 'trailing': 5, 'empty': 5, 'dtype': 5, 'unaligned': 5, 'count_limit': 7}
FIELD_REJECTIONS = {'integer_accuracy': 1, 'precision_above_width': 1, 'overlap': 1, 'cuda_cpu_build': 1}
ARRAY_REJECTIONS = {'point_oob': 1, 'nonfinite_write': 1, 'range_oob': 1, 'export_capacity': 1,
                    'truncated_raw': 1, 'wrong_derived_size': 1, 'wrong_mode': 1}
FIELD_PROFILES = {
    'rate-tail': ('f64', 'rate', [1029], [0], 13.37, 13.25),
    'accuracy-reversed-padded': ('f64', 'accuracy', [7,5], [-2,19], .1, .0625),
    'precision-permuted-reversed': ('f32', 'precision', [5,4,3], [3,18,-1], 13, 13),
    'reversible-4d': ('i64', 'reversible', [5,3,2,2], [0,0,0,0], 0, 0),
}
CHECKS = {
    'field-baseline': ('i32_i64_f32_f64_reversible', 'block_edges_and_tail', 'independent_schema_and_word_padding',
                       'wrong_dtype_and_empty_rejected'),
    'field-modes': ('reversible_and_rate_precision_accuracy', 'rank_1_to_4', 'strides_and_untouched_padding',
                    'effective_mode_vs_request', 'per_mode_original_domain_bound', 'invalid_layout_and_options'),
    'openmp-encode': ('serial_control_and_openmp_one', 'identical_field_workers_policy', 'serial_decode_restore'),
    'fixed-rate-array': ('separate_array_format', 'requested_vs_aligned_rate', 'cache_write_evict_flush',
                         'reopen_and_cross_block_range', 'post_persist_bound_untouched_blocks', 'invalid_metadata'),
}


def ref(path, raw):
    return {'path': path, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}


def pack(dtype, values):
    values = list(values)
    return struct.pack(f'<{len(values)}{TYPE_LAYOUT[dtype][1]}', *values)


def values(dtype, raw):
    return [v for (v,) in struct.iter_unpack('<' + TYPE_LAYOUT[dtype][1], raw)]


def batch_inputs(real, window):
    for dtype, bits in (('i32',32), ('i64',64)):
        hi = 1 << (bits-1)
        yield f'tail-{dtype}', dtype, pack(dtype,[0,-hi,hi-1,hi-2,-81]), {}
    for dtype,code,man,ex in (('f32','I',23,8), ('f64','Q',52,11)):
        inf, sign = ((1<<ex)-1)<<man, 1<<(man+ex)
        v = [0,sign,1,sign|1,inf,sign|inf,inf|(1<<(man-1))|17,inf|17,inf-(1<<man)]
        yield f'tail-{dtype}', dtype, struct.pack('<9'+code,*v), {}
    for count in (3,4,5,4095,4096,4097,window['count']):
        label = 'weather-test-co2' if count == window['count'] else f'weather-{count}'
        yield label, 'f64', real[:count*8], {'window': {**window,'count':count}}


def field_layout(req):
    shape = req['shape']
    strides = [s or math.prod(shape[:d]) for d,s in enumerate(req['strides'])]
    offsets = [sum(a*b for a,b in zip(reversed(i),strides,strict=True))
               for i in product(*(range(n) for n in reversed(shape)))]
    lo, hi = min(offsets), max(offsets)
    require(len(set(offsets)) == len(offsets), 'overlapping frozen ZFP field')
    return {'strides': strides, 'offset_bounds': [lo,hi], 'span_count': hi-lo+5, 'origin': 2-lo,
            'offsets': [i+2-lo for i in offsets]}


def field_input(req, real):
    count = math.prod(req['shape'])
    dtype, mode = req['type'], req['mode']
    if req['id'] == 'rate-tail':
        return real[:8*count]
    if mode == 'reversible':
        return pack(dtype,[-(2**61)+(i+1)*31 if i%2 else 2**62-(i+1)*13 for i in range(count)])
    # Deterministic dyadic fixture: no system libm-dependent sine oracle.
    return pack(dtype,[((i*91) % 509 - 254)/64 + (i%5)*.375 for i in range(count)])


def field_metadata(req):
    return {key: req[key] for key in ('type','shape','mode','requested','strides')}


def array_input(req):
    start = [i/10-.5 for i in range(req['shape'][0])]
    after = start.copy()
    after[req['point_index']] = req['point_value']
    i = req['range_start']
    after[i:i+len(req['range_values'])] = req['range_values']
    return start, after


def array_metadata(req):
    return {'format':'zfp-fixed-rate-array/1','dtype':req['type'],'shape':req['shape'],'mode':'rate','requested_rate':req['requested_rate'],
            'effective_rate':req['effective_rate']}


def retained_paths(bundle):
    return {WEATHER, *(b['artifact'] for b in bundle['batch']),
            *(v for r in bundle['fields'] for v in r['artifacts'].values()),
            *(p['payload'] for p in bundle['openmp']['profiles']), *bundle['array']['artifacts'].values()}


def plan_zfp(root: Path):
    cfg = load_json(local_file(root,CONFIG))
    require(isinstance(cfg,dict) and cfg.keys() == {'schema','selection','corpus','corpus_id','window','batch','fields','openmp','array'} and
            cfg['schema'] == 'bmk.dev-zfp-cases/1' and cfg['selection'] == 31, 'invalid ZFP case policy')
    require(canonical_bytes(cfg['batch']) == canonical_bytes({'plugin':PLUGIN,'role':'value','options':{},'dtypes':list(TYPE_LAYOUT)}) and
            canonical_bytes(cfg['openmp']) == canonical_bytes({'threads':[1,2],'chunk_blocks':64}), 'invalid ZFP ABI or worker policy')
    window = bind_window(root,cfg['corpus'],cfg['corpus_id'],cfg['window'])
    require(window['count'] == 8192, 'invalid ZFP worker source count')
    _, real = read_tv_window(root,window)
    require(all(math.isfinite(x) for x in values('f64',real)), 'nonfinite ZFP weather fixture')
    batch = []
    for name,dtype,raw,lineage in batch_inputs(real,window):
        batch.append({'case':name,'dtype':dtype,'input':ref('frozen:'+name,raw),'artifact':f'zfp-{name}.bmk', **lineage})
    require(isinstance(cfg['fields'],list) and all(isinstance(x,dict) for x in cfg['fields']) and [x.get('id') for x in cfg['fields']] == list(FIELD_PROFILES),
            'wrong ZFP field mode closure')
    fields = []
    for req, (dtype,mode,shape,strides,requested,effective) in zip(cfg['fields'],FIELD_PROFILES.values(),strict=True):
        limit = req.get('max_observed_error')
        require(req.keys() == {'id','type','mode','shape','strides','requested','max_observed_error'} and
                canonical_bytes(field_metadata(req)) == canonical_bytes(dict(type=dtype,mode=mode,shape=shape,strides=strides,requested=requested)) and
                type(limit) in (float,int) and (0 < limit <= 1 if mode != 'reversible' else limit == 0), 'invalid ZFP field request')
        label = req['id']
        fields.append({**req, 'effective':effective, 'input':ref('frozen:'+label,field_input(req,real)),
                       'artifacts':{key:f'zfp-{label}.{suffix}' for key,suffix in
                                    (('payload','zfp'),('metadata','json'),('restored_span','out'))}})
    req = cfg['array']
    require(isinstance(req,dict) and req.keys() == {'type','shape','requested_rate','max_observed_error','point_index',
            'point_value','range_start','range_values'} and (req['type'],req['shape'],req['requested_rate'],
            req['point_index'],req['range_start']) == ('f64',[13],18,1,3) and isinstance(req['range_values'],list) and len(req['range_values']) == 4 and
            all(type(x) in (int,float) and math.isfinite(x) and abs(x) <= 1 for x in [req['point_value'],*req['range_values']]) and
            type(req['max_observed_error']) in (float,int) and 0 < req['max_observed_error'] <= 1e-4, 'invalid ZFP array policy')
    array = {**req, 'effective_rate':32, 'artifacts':{key:f'zfp-array-{suffix}' for key,suffix in
            (('before','before.zfp'),('after','after.zfp'),('metadata','config.json'),('baseline','before.out'),('restored','after.out'))}}
    omp = {'chunk_blocks':64,'env':{'OMP_DYNAMIC':'FALSE','OMP_THREAD_LIMIT':'2'},'count':window['count'],
           'profiles':[{'policy':p,'threads':n,'payload':f'zfp-omp-{p}.zfp'} for p,n in [('serial',1),('1',1),('2',2)]]}
    body = {'schema':'bmk.zfp-native-cases/1','test':TEST,'evidence_path':REPORT,'config_id':content_id(cfg),
            'window':window,'weather':ref(WEATHER,real),'batch':batch,'fields':fields,'array':array,'openmp':omp,
            'data_artifact_max_bytes':1<<20, 'fixture_recipe':'zfp-reversible-boundaries-dyadic-fields-and-trusted-restores/1',
            'rejections':{'batch_input':BATCH_INPUT_REJECTIONS,'batch_wire':BATCH_WIRE_REJECTIONS,
                          'field':FIELD_REJECTIONS,'array':ARRAY_REJECTIONS},'qualification_granted':False}
    policy_id = content_id(body)
    body['cases'] = []
    for route, names in CHECKS.items():
        for check in names:
            row = {'name':f'zfp-{route}-{check.replace("_","-")}','selection':31,'route':route,'check':check,'policy_id':policy_id}
            body['cases'].append({**row,'case_id':content_id(row)})
    return {**body,'bundle_id':content_id(body)}, real
