"""Bind two native TCHY access protocols and their independently charged outputs."""
from ..assets import content_id, require
from .titchy_access import CONFIG, SCOPE, TRANSFORM, plan_titchy_access
from .titchy_native import plan_titchy_native
from .typed_batch import TITCHY_TOOL

TOOL, TARGET = 'titchy-access-direct', 'tsbench_titchy_access_control'
PROTOCOL = 'titchy-access-bound-v1'
LOADED, RANGE = 'titchy-loaded-reader', 'titchy-stateless-range'
ROUTES = {(85,'loaded-file-access'):LOADED, (85,'batch-range'):RANGE}
METHODS = {LOADED:{'wire':'TCHY v2','mode':'read_at_immutable_reader','byte_scope':SCOPE},
           RANGE:{'wire':'TCHY v2','mode':'stateless_whole_container_range','byte_scope':'whole_input_container_not_read_at'}}
SOURCES = (CONFIG,'plugins/codecs/titchy-batch/access_control.cpp','plugins/codecs/titchy-batch/CMakeLists.txt',
           'src/tsbench/planner/titchy_execution.py','src/tsbench/application/titchy_execution.py',
           'src/tsbench/qualification/titchy_access.py')
RESULT_LIMIT = 8192
FILE_LIMIT = 128<<10


def is_access(slot):
    return slot.get('protocol')==PROTOCOL


def operations(slot):
    return [('tchy-encode',TITCHY_TOOL), *( [('loaded',TOOL),('file',TOOL)] if slot['method']==LOADED else [('range',TOOL)] )]


def access_inputs(root):
    from .batch_execution import BatchInput

    bundle,cfg,source = plan_titchy_access(root)
    native = plan_titchy_native(bundle,cfg,source)
    oracle,budget,_ = bundle['cases']
    products,binds = {},{}
    for (_,route),method in ROUTES.items():
        cases = [c for c in bundle['cases'] if c['route']==route]
        body = {'protocol':PROTOCOL,'method':method,'name':route,'original':{'bytes':len(source),'sha256':oracle['input_sha256']},
                'window':oracle['window'],'transform':TRANSFORM,'request':oracle['criteria']['request'],
                'limits':budget['criteria']['byte_limits'], 'expected':oracle['criteria']['expected'] if method==LOADED else
                oracle['criteria']['expected']['range'], 'passes':budget['criteria']['request_passes'] if method==LOADED else 1,
                'parts':{'backing':budget['criteria']['byte_limits']['max_backing_bytes'],'answer':RESULT_LIMIT}}
        sid = content_id(body)
        products[sid] = {**body,'product_slot':sid},BatchInput(b'',(source,))
        for b,candidates in ((bundle,cases),(native,[c for c in native['cases'] if c['route']==route])):
            for case in candidates:
                binds[case['case_id']] = b['bundle_id'],[sid]
    require(len(binds)==11,'Titchy access definition denominator differs')
    return products,binds


def check_slots(plan):
    rows = [s for s in plan['slots'] if is_access(s)]
    require(len(rows)==2 and {s['method'] for s in rows}==METHODS.keys(), 'Titchy access route denominator differs')
    a,b = rows
    require(all(a[k]==b[k] for k in ('window','request','original','transform','limits','parts')),'Titchy access inputs differ')
    for s in rows:
        req,limits,n = s['request'],s['limits'],s['window']['count']
        require(s['parts']=={'backing':FILE_LIMIT,'answer':RESULT_LIMIT} and s['original']['bytes']==8*n==32104 and
                limits=={'max_backing_bytes':FILE_LIMIT,'open':96,'point':64,'range':192,'bit':32} and s['transform']==TRANSFORM and
                req=={'point':4001,'range':[3997,9],'bits':[0,63,256064,256127]},'Titchy request or resource policy differs')
        require(s['passes']==(2 if s['method']==LOADED else 1),'Titchy reader lifecycle differs')
