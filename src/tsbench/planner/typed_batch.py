"""Additional frozen typed routes, with intentional worker/native rejection cases."""
from ..assets import canonical_bytes, content_id, require
from .gorilla import sha
from .titchy_access import plan_titchy_access
from .titchy_native import KNOWN_REJECTIONS, LIMIT, fixtures, pack, plan_titchy_native
from .zfp import BATCH_INPUT_REJECTIONS, BATCH_WIRE_REJECTIONS, TYPE_LAYOUT, batch_inputs, plan_zfp
from ..qualification.titchy_wire import native_bound

TITCHY, ZFP = 'titchy-batch', 'zfp-reversible'
TITCHY_TOOL = 'titchy-c-direct'
TITCHY_TARGET = 'tsbench_titchy_batch_control'
TITCHY_SOURCE = 'plugins/codecs/titchy-batch/direct_control.c'
ROUTES = {85: ('batch', TITCHY), 31: ('field-baseline', ZFP)}
METHODS = {p:{'plugin':p, 'options':{}} for _,p in ROUTES.values()}
POLICY = 'configs/suites/m3_first_batch_native_v2/extended-batch-execution.json'
SOURCES = (TITCHY_SOURCE, 'src/tsbench/planner/typed_batch.py', 'src/tsbench/qualification/typed_batch.py',
           'src/tsbench/planner/titchy_native.py', 'src/tsbench/planner/titchy_access.py',
           'src/tsbench/planner/zfp.py', 'src/tsbench/qualification/titchy_wire.py')


def typed_inputs(root, max_frame_bytes):
    from .batch_execution import BatchInput

    products, binds = {}, {}
    def add(method, name, dtype, n, raw, schema, lineage, wire_cap, rejection=0, options=None, decode=None):
        require(len(raw) == n * {2:1,4:2,5:4,6:4,7:8,8:8,9:4,10:8}[dtype], 'invalid typed original byte extent')
        body = {'method':method, 'name':name, 'lineage':lineage, 'expected_status':rejection,
                'original':{'columns':[{'dtype':dtype,'count':n}], 'column_bytes':[len(raw)], 'column_sha256':[sha(raw)],
                            'schema_bytes':len(schema), 'schema_sha256':sha(schema)},
                'max_frame_bytes':wire_cap, 'wire_checks':{}, 'reject_decodes':list(decode or {}), 'upstream_zstd':False}
        if rejection:
            body['negative_options'] = options or {}
        else:
            body['reject_statuses'] = decode
        sid = content_id(body)
        require(sid not in products, 'duplicate typed batch slot')
        products[sid] = {**body,'product_slot':sid}, BatchInput(schema,(raw,))
        return sid

    access, cfg, source = plan_titchy_access(root)
    titchy = plan_titchy_native(access,cfg,source)
    titchy_route = ROUTES[85][0]
    matches = {r['case']:r for r in titchy['batch']}
    titchy_ok = []
    for name, bits, values, _ in fixtures(source,access['cases'][0]['window']):
        data, n = pack(values,bits), len(values)
        spec = matches[name]
        require(sha(data) == spec['input_sha256'] and n == spec['count'] and bits == spec['bits_per_sample'],
                'Titchy batch source differs from frozen inputs')
        schema = canonical_bytes({'dtype':f'u{bits}','column':'v'})
        titchy_ok.append(add(TITCHY,name,{8:2,16:4,32:6,64:8}[bits],n,data,schema,spec,
                             32+len(schema)+native_bound(n,bits,4,1000),decode=KNOWN_REJECTIONS['batch_frames']))
    require(len(titchy_ok) == len(matches), 'Titchy positive scope differs')
    titchy_check = {'worker_f64':(10,1,bytes(8),{}),'worker_unknown_option':(8,1,bytes(8),{'bits':64}),
                    'worker_count':(2,LIMIT+1,bytes(LIMIT+1),{})}
    titchy_bad = [add(TITCHY,name,dtype,n,raw,b'{}',{'control':'frozen_titchy_worker_input_rejections'},0,
                      KNOWN_REJECTIONS['batch_input'][name],opts) for name,(dtype,n,raw,opts) in titchy_check.items()]
    for case in titchy['cases']:
        if case['route'] == titchy_route:
            binds[case['case_id']] = titchy['bundle_id'], (titchy_ok+titchy_bad if
                case['check'] == 'size_capacity_and_options_rejected' else titchy_ok)

    zfp, weather = plan_zfp(root)
    specs = {row['case']:row for row in zfp['batch']}
    zfp_ok = []
    for name, dtype, raw, _ in batch_inputs(weather,zfp['window']):
        spec = specs[name]
        require(spec['input']['bytes'] == len(raw) and spec['input']['sha256'] == sha(raw) and spec['dtype'] == dtype,
                'ZFP batch source differs from frozen inputs')
        zfp_ok.append(add(ZFP,name,TYPE_LAYOUT[dtype][0],len(raw)//(int(dtype[1:])//8),raw,
                          canonical_bytes({'column':'value','dtype':dtype}),spec,max_frame_bytes,decode=BATCH_WIRE_REJECTIONS))
    require(len(zfp_ok) == len(specs), 'ZFP positive scope differs')
    zfp_check = {'empty':(10,0,b'',{}), 'wrong_dtype':(8,1,bytes(8),{}),
                 'unknown_options':(10,1,bytes(8),{'mode':'rate'})}
    zfp_bad = [add(ZFP,name,dtype,n,raw,b'{}',{'control':'frozen_zfp_worker_input_rejections'},0,
                   BATCH_INPUT_REJECTIONS[name],opts) for name,(dtype,n,raw,opts) in zfp_check.items()]
    for case in zfp['cases']:
        if case['route'] == ROUTES[31][0]:
            binds[case['case_id']] = zfp['bundle_id'], zfp_ok+zfp_bad if case['check']=='wrong_dtype_and_empty_rejected' else zfp_ok
    return products, binds
