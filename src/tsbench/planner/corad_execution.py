"""Bind actual CORAD inference and its predeclared quality key to one ledger slot."""
from pathlib import PurePosixPath
from hashlib import sha256

from ..assets import canonical_bytes, content_id, require
from .batch_execution import BatchInput
from .corad_deployment import DEPLOYMENT
from .corad_inference import METHOD, REJECTIONS, ROUTES as DEPLOYMENTS, plan_corad_inference

ROUTE = (80, 'corad-inference')
ROUTES = {ROUTE: METHOD}
PROTOCOL = 'corad-native-inference-v1'
DEFAULT_METHOD = {'plugin': METHOD, 'options': {}}
TOOL, TARGET = 'corad-c-inference-direct', 'tsbench_corad_inference_control'
QUALITY_CHECK = 'bound_predeclared_before_formal_run'
FILE_CEILING = 16384
SOURCES = ('plugins/codecs/corad-frozen/inference_control.c','plugins/codecs/corad-frozen/CMakeLists.txt',
           'src/tsbench/planner/corad_execution.py','src/tsbench/planner/corad_inference.py',
           'src/tsbench/planner/corad_deployment.py','src/tsbench/application/corad_execution.py',
           'src/tsbench/qualification/corad_wire.py','src/tsbench/qualification/corad_inference.py','src/tsbench/corad_quality.py')
COLS = ('v0','v1','v2')
RESTORED = ('schema',*COLS)
ENCODE_REJECTS = ('encode-without-model','column-order','unequal-row-count','wrong-dtype','nonfinite','encode-value-budget')
DECODE_REJECTS = ('wrong-expected-model','wrong-expected-schema','decode-value-budget','bad-reference','truncated','trailing-byte')


def is_corad(slot):
    return slot.get('protocol')==PROTOCOL


def tool_path(build):
    return PurePosixPath(build['plugins'][METHOD]['library']['path']).with_name(TARGET)


def limit(plan):
    return {**plan['limits'],'file_bytes':FILE_CEILING}


def identity(raw):
    return {'bytes':len(raw),'sha256':sha256(raw).hexdigest()}


def parts(bundle):
    a,b = bundle['input'],bundle['quality_policy']['calibration']
    return {a['path']:a['bytes'],b['path']:b['bytes'],**{f['path']:f['max_frame_bytes'] for f in bundle['frames']}}


def options(model):
    return canonical_bytes({'deployment':model}).decode('ascii')


def plan_slots(root):
    bundle,deployments,raw,calibration = plan_corad_inference(root)
    body = {'protocol':PROTOCOL,'method':METHOD,'bundle':bundle,'deployments':[d[3]['deployment'] for d in deployments],
            'parts':parts(bundle)}
    sid = content_id(body)
    return {sid:({**body,'product_slot':sid},BatchInput(b'',(b''.join(raw),calibration)))}, {
            c['case_id']:(bundle['bundle_id'],[sid]) for c in bundle['cases']}


def check_slots(plan):
    slots = [s for s in plan['slots'] if is_corad(s)]
    require(len(slots)==1,'CORAD inference execution lane differs')
    s, = slots
    b = s['bundle']; p = b['quality_policy']
    require(s.keys()=={'method','protocol','bundle','deployments','parts','product_slot'} and s['method']==METHOD and
            s['product_slot']==content_id({k:v for k,v in s.items() if k!='product_slot'}) and
            b['bundle_id']==content_id({k:v for k,v in b.items() if k!='bundle_id'}) and
            p['policy_id']==content_id({k:v for k,v in p.items() if k!='policy_id'}) and
            len(b['cases'])==9 and len({c['check'] for c in b['cases']})==6 and
            b['rejections']==REJECTIONS and s['parts']==parts(b) and max(s['parts'].values())<=limit(plan)['file_bytes'],
            'CORAD bundle, obligations or retention differ')
    require(b['input']['rows']==67 and p['calibration']['rows']==129 and
            b['input']['columns']==['pressure','air_temperature','relative_humidity'] and
            len(s['deployments'])==len(b['models'])==2 and
            [(f['route'],f['case'],f['rows']) for f in b['frames']]==[
                (d,t,n) for d in DEPLOYMENTS for t,n in (('held-out',67),('short-tail-only',3),('empty',0))],
            'CORAD frozen ordered holdout/deployments differ')
    for i,(l,m) in enumerate(zip(s['deployments'],b['models'],strict=True)):
        data = bytes.fromhex(l)
        schema,model = split_deployment(l)
        ref = m['definition']['model']
        require(len(data)*2+18<=1024 and identity(model)=={k:ref[k] for k in ('bytes','sha256')} and
                all(f['schema_hex']==schema.hex() and f['model_sha256']==ref['sha256'] and
                    f['deployment_id']==m['definition']['deployment_id'] and
                    f['encode_configuration_id']==m['configuration_id'] for f in b['frames'][3*i:3*i+3]),
                'CORAD model packet does not match frozen implementation and schema')


def split_deployment(literal):
    raw = bytes.fromhex(literal)
    require(len(raw)>=DEPLOYMENT.size,'CORAD deployment packet too short')
    magic,m,n = DEPLOYMENT.unpack_from(raw)
    require(magic==b'BMKCDP\x01\0' and m>0 and n>0 and len(raw)==DEPLOYMENT.size+m+n,'invalid bound CORAD deployment packet')
    return raw[DEPLOYMENT.size:DEPLOYMENT.size+m],raw[-n:]


def steps(slot):
    recipe = {}

    def encode(label,option,types=(10,10,10),reject=0):
        argv = ['/inputs/schema','frame']+[a for dtype,key in zip(types,COLS,strict=True) for a in (str(dtype),f'/inputs/{key}')]
        recipe[label] = dict(command='encode-columns',tool=None,options=option,argv=argv,inputs=['schema',*COLS],
                             outputs=[] if reject else ['frame'],reject=reject)

    def decode(label,option='{}',reject=0):
        recipe[label] = dict(command='decode-columns',tool=None,options=option,argv=['/inputs/frame',*RESTORED],inputs=['frame'],
                             outputs=[] if reject else list(RESTORED),reject=reject)

    opts = list(map(options,slot['deployments']))
    for i,f in enumerate(slot['bundle']['frames']):
        encode(f'encode-{i}',opts[i//3])
        recipe[f'native-{i}'] = dict(command=None,tool=TOOL,options=None,argv=['/inputs/model','/inputs/values'],
                                    inputs=['model','values'],outputs=['native'],reject=0)
        decode(f'restore-{i}')
        if f['case']=='held-out':
            decode(f'pinned-{i}',opts[i//3])
    for name in ENCODE_REJECTS:
        encode(name,'{}' if name=='encode-without-model' else opts[0],
               (8,10,10) if name=='wrong-dtype' else (10,10,10),REJECTIONS[name])
    for name in DECODE_REJECTS:
        decode(name,opts[1] if name=='wrong-expected-model' else opts[0] if name=='wrong-expected-schema' else '{}',REJECTIONS[name])
    return recipe


def operations(slot):
    return [(op,s['tool']) for op,s in steps(slot).items()]
