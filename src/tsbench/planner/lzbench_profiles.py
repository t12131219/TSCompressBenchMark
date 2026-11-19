"""Freeze native dictionary and worker lanes, including exact files-only reads."""
from ..assets import content_id, require
from .lzbench import _dictionary_plan, _worker_plan, plan_lzbench
from .lzbench_session import tool_path

DICT, ZSTD, XZ = 'zstd-dictionary','zstd-workers','xz-workers'
PROTOCOL = 'lzbench-profiles-bound-v1'
ROUTES = {(40,DICT):DICT,(40,ZSTD):ZSTD,(39,XZ):XZ}
METHODS = {m:{'codec':m.split('-')[0], 'entry':'lzbench_native::session::process',
              'mode':'native-trained-dictionary' if m==DICT else 'native-worker-controls'} for m in ROUTES.values()}
TOOL, SYNC = 'lzbench-native-features','lzbench-xz-caller-sync'
TARGETS = {TOOL:'tsbench_lzbench_feature_control',SYNC:'tsbench_lzbench_xz_sync_control'}
FILE_CEILING = 8 << 20
SOURCES = ('plugins/codecs/zstd/CMakeLists.txt','tests/native/lzbench_contract.cpp','src/tsbench/supervisor/isolated_worker.py',
           'src/tsbench/planner/lzbench_profiles.py','src/tsbench/application/lzbench_profiles.py')


def tool_paths(build):
    return {tool:tool_path(build).with_name(target) for tool,target in TARGETS.items()}


def is_profile(slot):
    return slot.get('protocol')==PROTOCOL


def input_bytes(slot):
    spec = slot['spec']
    return (sum(x['bytes'] for x in spec['training_samples'])+spec['held_out']['bytes'] if slot['method']==DICT
            else spec['input']['bytes'])


def _slot(method,spec):
    dictionary = method==DICT
    if dictionary:
        parts = {spec['dictionary_path']:spec['capacity'],spec['frame_path']:spec['held_out']['bytes']+65536}
    else:
        names = list(spec['frame_paths'].values()) + ([spec['synchronous']['frame_path']] if method==XZ else [])
        parts = {name:spec['input']['bytes']+65536 for name in names}
    limits = {'file_bytes':(1 if dictionary else 6 if method==ZSTD else 3)<<20,
              'address_space_bytes':(128 if dictionary else 512)<<20,'wall_seconds':15}
    body = {'protocol':PROTOCOL,'method':method,'spec':spec,'parts':parts,'limits':limits}
    return {**body,'product_slot':content_id(body)}


def plan_slots(root):
    bundle = plan_lzbench(root)
    slots,binds = {},{}
    by = {DICT:bundle['dictionary'],ZSTD:bundle['workers']['zstd'],XZ:bundle['workers']['xz']}
    for method,spec in by.items():
        slot = _slot(method,spec)
        sid = slot['product_slot']
        slots[sid] = slot,None  # Inputs are generated inside the executor from the sealed fixture definitions.
        for c in bundle['cases']:
            if c['route']==method and (c['selection'],method) in ROUTES:
                binds[c['case_id']] = bundle['bundle_id'],[sid]
    require(len(slots)==3 and len(binds)==11,'lzbench profile obligation denominator differs')
    return slots,binds


def check_slots(plan):
    rows = [s for s in plan['slots'] if is_profile(s)]
    specs = {DICT:_dictionary_plan(),ZSTD:_worker_plan('zstd'),XZ:_worker_plan('xz')}
    require(len(rows)==3 and {s['method']:s for s in rows}=={m:_slot(m,spec) for m,spec in specs.items()},
            'lzbench profile fixture, lane or resource contract differs')


def steps(slot):
    """Operation recipe used both by the executor and the plan/ledger auditor."""
    method,spec = slot['method'],slot['spec']
    codec = METHODS[method]['codec']
    result = {}

    def add(label,argv,mounts,outputs,*,error=None,tool=TOOL):
        result[label] = {'tool':tool,'argv':list(map(str,argv)),'mounts':mounts,'outputs':outputs,'error':error}

    def feature(label,frame,original,profile,params,*,encode=False,dictionary=None,error=None):
        source = 'raw' if encode else 'frame'
        mounts = {source:'raw' if encode else frame}
        if dictionary:
            mounts['dict'] = dictionary
        add(label,['roundtrip' if encode else 'decode',codec,'frame',spec.get('level',3),*profile,65536,'reuse',1,
                   '/inputs/dict' if dictionary else '-',f'/inputs/{source}','wire','raw',original['bytes'],
                   *(f'{k}={v}' for k,v in sorted(params.items()))],mounts,
            {} if error else {'wire':frame,'raw':'raw'},error=error)

    if method==DICT:
        dictionary,frame = spec['dictionary_path'],spec['frame_path']
        names = [f'train-{i:03}' for i in range(len(spec['training_samples']))]
        add('train',['train',spec['capacity'],dictionary,*(f'/inputs/{n}' for n in names)],
            {n:n for n in names},{dictionary:dictionary})
        for n in spec['bad_capacities']:
            add(f'reject-cap-{n}',['train',n,dictionary,'/inputs/train-000'],{'train-000':'train-000'}, {},error='dictionary training size')
        feature('encode',frame,spec['held_out'],spec['span_profiles']['roundtrip'],{},encode=True,dictionary=dictionary)
        for label,d,e in [('restore',dictionary,None),('reject-missing',None,'Dictionary mismatch'),
                          ('reject-wrong-id','wrong-dictionary','Dictionary mismatch')]:
            feature(label,frame,spec['held_out'],spec['span_profiles']['fresh_decode'],{},dictionary=d,error=e)
    else:
        for n in spec['settings']:
            frame = spec['frame_paths'][str(n)]
            feature(f'encode-{n}',frame,spec['input'],spec['span_profile'],{**spec['base'],spec['parameter']:n},encode=True)
        if method==XZ:
            sync = spec['synchronous']['frame_path']
            add('encode-sync',['xz-sync-encode','/inputs/raw'],{'raw':'raw'},{sync:sync},tool=SYNC)
        for n in spec['settings']:
            frame = spec['frame_paths'][str(n)]
            feature(f'restore-{n}',frame,spec['input'],spec['span_profile'],spec['base'] if method==ZSTD else
                    {**spec['base'],'threads':1})
        if method==XZ:
            shared = spec['frame_paths']['2']
            for n in spec['settings']:
                feature(f'decode-shared-{n}',shared,spec['input'],spec['xz_same_frame_decode_spans'],{**spec['base'],'threads':n})
            for key,frame in [('own',sync),('shared',shared)]:
                add(f'decode-sync-{key}',['xz-sync-decode','/inputs/frame'],{'frame':frame},{'sync.decoded':'raw'},tool=SYNC)
    return result


def operations(slot):
    return [(label,step['tool']) for label,step in steps(slot).items()]


def supports_condition(ob):
    return ob['kind']=='conditional' and (ob['selection'],ob['route']) in {(40,ZSTD),(39,XZ)}


def condition_slots(ob,slots):
    from .native_conditions import CONDITIONS

    case = ob['condition_case']
    key = (ob['selection'],ob['route'],case['predicate'])
    require(key in CONDITIONS,'unknown lzbench worker condition')
    check,bundle,selector,criteria = CONDITIONS[key]
    require((ob['check'],case['required_observation'],case['bundle_key'],case['selector'],case['criteria'])==
            (check,check,bundle,selector,criteria),'lzbench worker condition criteria differ')
    ids = [s['product_slot'] for s in slots if is_profile(s) and s['method']==ob['route']]
    require(len(ids)==1,'lzbench worker condition must bind one actual profile slot')
    return ids
