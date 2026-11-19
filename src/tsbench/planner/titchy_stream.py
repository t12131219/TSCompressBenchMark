"""Bind the frozen Titchy packet API independently of the TV/column worker ABI."""
from ..assets import content_id, require
from .titchy_access import CONFIG, TRANSFORM, plan_titchy_access
from .titchy_native import BATCH_POLICY, KNOWN_REJECTIONS, plan_titchy_native

TOOL, TARGET = 'titchy-stream-direct', 'tsbench_titchy_stream_control'
PROTOCOL, METHOD = 'titchy-stream-bound-v1', 'titchy-packet-stream'
ROUTES = {(85,'packet-stream'):METHOD}
METHODS = {METHOD:{'wire':'TSTR v1 + TSC1','mode':'native_push_drain_then_finish','decoder':'detached_packet_api'}}
FILE_LIMIT = 128 << 10
PARTS = {'archive':FILE_LIMIT,'config':32}
POLICY = {**BATCH_POLICY,'active_bytes':72}
SOURCES = (CONFIG,'plugins/codecs/titchy-batch/stream_control.cpp','plugins/codecs/titchy-batch/CMakeLists.txt',
           'src/tsbench/planner/titchy_stream.py','src/tsbench/planner/titchy_native.py',
           'src/tsbench/application/titchy_stream.py','src/tsbench/qualification/titchy_native.py',
           'src/tsbench/qualification/titchy_wire.py')


def is_stream(slot):
    return slot.get('protocol') == PROTOCOL


def operations(slot):
    return [('packet-encode',TOOL),('packet-decode',TOOL)]


def stream_inputs(root):
    from .batch_execution import BatchInput

    access,cfg,source = plan_titchy_access(root)
    native = plan_titchy_native(access,cfg,source)
    spec = native['stream']
    window = access['cases'][0]['window']
    body = {'protocol':PROTOCOL,'method':METHOD,'name':'packet-stream','window':window,'transform':TRANSFORM,
            'original':{'bytes':len(source),'sha256':spec['input_sha256']},'stream':spec,'policy':POLICY,
            'status_policy':KNOWN_REJECTIONS['stream'],'parts':PARTS}
    sid = content_id(body)
    binds = {c['case_id']:(native['bundle_id'],[sid]) for c in native['cases'] if c['route']=='packet-stream'}
    require(len(binds)==6,'Titchy stream obligation denominator differs')
    return {sid:({**body,'product_slot':sid},BatchInput(b'',(source,)))},binds


def check_slots(plan):
    rows = [s for s in plan['slots'] if is_stream(s)]
    require(len(rows)==1,'Titchy stream product denominator differs')
    s, = rows
    require(set(s)=={'protocol','method','name','window','transform','original','stream','policy','status_policy','parts','product_slot'}
            and s['method']==METHOD and s['name']=='packet-stream' and s['transform']==TRANSFORM and
            s['status_policy']==KNOWN_REJECTIONS['stream'] and s['policy']==POLICY and s['parts']==PARTS and
            s['original']['bytes']==8*s['window']['count']==32104 and
            s['stream']=={'archive':'stream.tstr','config':'stream.tsc1','count':4013,'chunks_per_packet':7,
                          'max_active_bytes':72,'max_artifact_bytes':FILE_LIMIT,'input_sha256':s['original']['sha256'],
                          'validator':'native_packet_and_tstr_detached_bits_v1'},'Titchy stream wire/resource policy differs')
    for sibling in plan['slots']:
        if sibling.get('method') in {'titchy-loaded-reader','titchy-stateless-range'}:
            require(all(s[k]==sibling[k] for k in ('window','original','transform')),'Titchy stream/access original differs')
