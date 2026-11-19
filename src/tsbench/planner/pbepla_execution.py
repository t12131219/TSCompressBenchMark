"""Freeze PBEPLA batch, detached progressive and callback replay steps."""
from hashlib import sha256
from pathlib import PurePosixPath
import struct

from ..assets import canonical_bytes, content_id, require
from .batch_execution import BatchInput
from .pbepla_progressive import (REJECT_OPTIONS, REPLAY_HELPER, boundary_source, plan_pbepla_progressive, schema_bytes)

PLUG = 'pbepla-rr'
PROGRESSIVE, REPLAY = 'pbepla-progressive','pbepla-replay'
PROTOCOL = 'pbepla-native-bound-v1'
ROUTES = {(87,r):r for r in (PROGRESSIVE,REPLAY)}
METHODS = {PROGRESSIVE:{'codec':PLUG,'entry':'tba_pbepla_encode_ex / tba_pbepla_prefix'},
           REPLAY:{'codec':PLUG,'entry':'tba_pbepla_encode_stream / tba_pbepla_decode_stream','online_input':False}}
# Recovery closure needs a valid ABI method identity; every operation binds its own literal options.
DEFAULT_METHOD = {'plugin':PLUG,'options':{'eps':[1]}}
DIRECT, CALLBACK = 'pbepla-direct','pbepla-replay-observer'
TARGETS = {DIRECT:'tsbench_pbepla_native_control',CALLBACK:REPLAY_HELPER}
FILE_CEILING = 2 << 20
CAP = 131072
SOURCES = ('plugins/codecs/pbepla-rr/CMakeLists.txt','plugins/codecs/pbepla-rr/native_control.cpp',
           'tests/native/pbepla_replay_control.cpp','cmake/development-tests.cmake','src/tsbench/planner/pbepla_progressive.py',
           'src/tsbench/planner/pbepla_execution.py','src/tsbench/application/pbepla_execution.py',
           'src/tsbench/qualification/pbepla_progressive.py')


def is_pbepla(slot):
    return slot.get('protocol')==PROTOCOL


def tool_paths(build):
    p = PurePosixPath(build['plugins'][PLUG]['library']['path'])
    return {n:p.with_name(t) for n,t in TARGETS.items()}


def identity(data):
    return {'bytes':len(data),'sha256':sha256(data).hexdigest()}


def limit(slot,base):
    return {**base,'file_bytes':FILE_CEILING,'wall_seconds':15} if slot['variant'].startswith('budget-') else base


def _slot(method,variant,spec,*,fault_policy=None,replay_policy=None):
    parts = {}
    if variant=='prefixes':
        parts = {spec['word_path']:spec['word_bytes'],**{n:CAP for n in spec['frame_paths']}}
        if fault_policy:
            parts[fault_policy['partial']] = CAP
    elif variant.startswith('budget-'):
        parts = {spec['frame']:CAP}
        if variant=='budget-at':
            parts['restored'] = spec['count']*8
    body = {'protocol':PROTOCOL,'method':method,'variant':variant,'spec':spec,'parts':parts}
    if fault_policy:
        body['fault_policy'] = fault_policy
    if replay_policy:
        body['replay_policy'] = replay_policy
    return {**body,'product_slot':content_id(body)}


def _definitions(bundle):
    policy = bundle['failure_policy']
    for spec in bundle['inputs']:
        yield _slot(PROGRESSIVE,'prefixes',spec),spec['name']
    for spec in bundle['inputs']:
        if spec['replay']:
            yield _slot(REPLAY,'prefixes',spec,fault_policy=policy if spec['name']==policy['fault_input'] else None,
                        replay_policy=bundle['replay_policy']),spec['name']
    for spec in policy['boundary']:
        yield _slot(PROGRESSIVE,spec['name'],spec),spec['name']
    weather = next(s for s in bundle['inputs'] if s['name']=='weather')
    yield _slot(PROGRESSIVE,'input-negatives',weather,fault_policy=policy),'weather'


def plan_slots(root):
    bundle,_,raw = plan_pbepla_progressive(root)
    slots,binds = {},{}
    for s,key in _definitions(bundle):
        data = boundary_source(s['spec']['count']) if s['variant'].startswith('budget-') else raw[key]
        require(identity(data)['sha256']==s['spec']['input_sha256'],'PBEPLA original differs from frozen source')
        slots[s['product_slot']] = s,BatchInput(b'',(data,))
    for case in bundle['cases']:
        ids = required_slots(case,(s for s,_ in slots.values()))
        require(ids,'PBEPLA obligation has no executable lane')
        binds[case['case_id']] = bundle['bundle_id'],ids
    require(len(slots)==13 and len(binds)==33,'PBEPLA case denominator differs')
    return slots,binds


def required_slots(case,slots):
    match = []
    for s in slots:
        if not is_pbepla(s) or s['method']!=case['route']:
            continue
        c = case['check']
        if c=='decreasing_eps_and_work_bound':
            ok = s['variant'].startswith('budget-') or s['variant']=='input-negatives'
        elif c=='reject_bad_layers_and_nonfinite':
            ok = not s['variant'].startswith('budget-')
        elif c=='changed_source_rewind_and_sink_failures':
            ok = 'fault_policy' in s
        else:
            ok = case['name']==f'{s["spec"]["name"]}-{c}' and s['variant']=='prefixes'
        if ok:
            match.append(s['product_slot'])
    return match


def check_slots(plan):
    rows = [s for s in plan['slots'] if is_pbepla(s)]
    prog = rows[:7]
    names = ['empty','constant','piecewise','sixteen-layers','weather','connected-explicit-grid','symmetric-single']
    require(len(rows)==13 and [s['spec']['name'] for s in prog]==names and
            [s['method'] for s in rows]==[PROGRESSIVE]*7+[REPLAY]*3+[PROGRESSIVE]*3 and
            [s['variant'] for s in rows]==['prefixes']*10+['budget-at','budget-over','input-negatives'],
            'PBEPLA frozen execution lane closure differs')
    require([s['spec']['name'] for s in rows[7:10]]==['empty','piecewise','weather'] and
            [s['spec'] for s in rows[7:10]]==[prog[i]['spec'] for i in (0,2,4)] and
            [len(s['spec']['requested_eps']) for s in prog]==[1,3,3,16,3,2,1], 'PBEPLA prefix/replay denominator differs')
    fault = rows[8]['fault_policy']
    require(fault==rows[-1]['fault_policy'] and rows[-1]['spec']==prog[4]['spec'] and fault['work_limit']==2097152 and
            fault['options']==list(REJECT_OPTIONS) and fault['reject_dtype']==9 and
            fault['nonfinite_u64']==[0x7ff8000000000042,0x7ff0000000000000,0xfff0000000000000] and
            fault['fault_modes']==['changed','no-rewind','sink-fail','value-limit'] and fault['fault_input']=='piecewise',
            'PBEPLA negative contract differs')
    for s in rows:
        f = s['spec']
        if s['variant']=='prefixes':
            require(f['input_id']==content_id({k:v for k,v in f.items() if k!='input_id'}) and
                    f['frame_paths']==[f'pbepla-{f["name"]}-L{i}.bmk' for i in range(1,len(f['requested_eps'])+1)] and
                    f['word_path']==f'pbepla-{f["name"]}.f64le' and f['word_bytes']==8+8*f['count']*(len(f['requested_eps'])+1),
                    'PBEPLA prefix artifact definition differs')
            if s['method']==REPLAY:
                require(s['replay_policy']=={'scope':'logical_callback_and_stdio_not_physical_io','empty_passes':1,
                        'nonempty_passes_without_retry':3,'max_numerical_retries':0,'expect_batch_payload_identity':True},
                        'PBEPLA native replay policy differs')
        require(s==_slot(s['method'],s['variant'],f,fault_policy=s.get('fault_policy'),replay_policy=s.get('replay_policy')) and
                max([8*f['count'],*s['parts'].values()])<=limit(s,plan['limits'])['file_bytes'], 'PBEPLA retention or ceiling differs')
    require([s['spec'] for s in rows[-3:-1]]==fault['boundary'] and
            [s['spec']['count'] for s in rows[-3:-1]]==[131072,131073], 'PBEPLA value-layer boundary differs')


def input_bytes(slot):
    return 8*slot['spec']['count']+len(schema_bytes(slot['spec']['name']))


def options(eps):
    return canonical_bytes({'eps':eps}).decode('ascii')


def steps(slot):
    variant, spec = slot['variant'],slot['spec']
    n, eps = spec['count'],spec['requested_eps']
    k = len(eps)
    result = {}
    def add(label,tool,argv,mounts,out,*,reject=0,opts=None,temp=False):
        result[label] = {'tool':tool,'argv':list(map(str,argv)),'mounts':mounts,'outputs':out,'reject':reject,'opts':opts,'tmp':temp}
    def native_encode():
        g = spec['geometry'] or {}
        add('native-encode',DIRECT,['encode','/inputs/input',k,spec['expected_delay'],g.get('connected',0),g.get('symmetric_band',0),
            g.get('has_source_range',0),g.get('source_min',0),g.get('source_max',0),*eps,*g.get('resolutions',[0]*k)],{'input':'input'},['full'])
    def abi_encode(label,opts,dtype=10,status=0,src='input',schema='schema'):
        add(label,None,['encode',dtype,'/inputs/input','/inputs/schema','frame'],{'input':src,'schema':schema},
            [] if status else ['frame'],reject=status,opts=opts)
    def abi_decode(label,frame,status=0):
        add(label,None,['decode','/inputs/frame','out','schema'],{'frame':frame},[] if status else ['out','schema'],reject=status,opts='{}')
    def callback(label,mode,maximum):
        add(label,CALLBACK,[mode,'/inputs/input','full',maximum,spec['expected_delay'],*eps],{'input':'input'},['full'],temp=True)
    if variant=='input-negatives':
        for i,o in enumerate(slot['fault_policy']['options']):
            abi_encode(f'bad-option-{i}',o,status=3,schema='empty-schema')
        abi_encode('bad-dtype','{"eps":[1]}',9,1,schema='empty-schema')
        for i,_ in enumerate(slot['fault_policy']['nonfinite_u64']):
            abi_encode('nonfinite-'+str(i),'{"eps":[1]}',status=2,src='nonfinite-'+str(i),schema='empty-schema')
    elif variant=='budget-at':
        abi_encode('abi-encode',options(eps))
        abi_decode('abi-restore','budget-frame')
    elif variant=='budget-over':
        abi_encode('abi-encode',options(eps),status=7)
        native_encode()
        abi_decode('abi-restore','budget-frame',7)
    else:
        progressive = slot['method']==PROGRESSIVE
        if progressive:
            native_encode()
            if spec['geometry'] is None:
                abi_encode('abi-encode',options(eps))
        else:
            callback('callback-encode','normal',n)
        add('prefixes',DIRECT,['prefixes-controls' if progressive else 'prefixes','/inputs/full'],
            {'full':'full'},[f'L{i}' for i in range(1,k+1)])
        for i in range(1,k+1):
            abi_decode(f'restore-{i}',f'frame-{i}')
            if not progressive:
                add(f'emit-{i}',DIRECT,['stream-decode','/inputs/prefix',i,n],{'prefix':f'native-{i}'},['out'])
        if progressive:
            for name in ('truncated_native','zero_stored_layer',*(['payload_crc'] if n else [])):
                abi_decode(name,name,5)
        if 'fault_policy' in slot:
            for name in slot['fault_policy']['fault_modes']:
                callback('fault-'+name,'normal' if name=='value-limit' else name,n-int(name=='value-limit'))
            add('partial-reject',DIRECT,['partial-reject','/inputs/partial',n],{'partial':'partial'},[])
    return result


def operations(slot):
    return [(label,s['tool']) for label,s in steps(slot).items()]
