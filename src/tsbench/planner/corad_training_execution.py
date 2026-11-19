"""Frozen native and Source training lanes; held-out inference is a separate process."""
from importlib import metadata
from pathlib import Path
import sys
import tarfile

from ..assets import content_id, digest, require, verify_asset
from ..build.environment import check_tsbench
from .batch_execution import BatchInput
from .corad_execution import TOOL as ENCODE, METHOD, FILE_CEILING, identity
from .corad_training import BRIDGE, STAGED_BRIDGE, VECTORS, CHECKS, plan_corad_training, source_argv

C, SOURCE = tuple(CHECKS)
ROUTES = {(80,r):r for r in CHECKS}
METHODS = {C:{'codec':METHOD,'trainer':'corad_model_train'},SOURCE:{'codec':METHOD,'trainer':BRIDGE}}
PROTOCOL = 'corad-separated-training-v1'
TOOL,TARGET = 'corad-c-training-direct','tsbench_corad_training_control'
PYTHON = 'corad-source-tsbench'
SOURCES = ('plugins/codecs/corad-frozen/training_control.c','plugins/codecs/corad-frozen/CMakeLists.txt',
           'src/tsbench/planner/corad_training_execution.py','src/tsbench/application/corad_training_execution.py',
           'src/tsbench/planner/corad_training.py','src/tsbench/qualification/corad_training.py',
           'src/tsbench/build/environment.py','src/tsbench/supervisor/corad_source.py')
OPTION_KEYS = ('seed','training_columns','max_training_samples','max_iter','solver_max_iter','alpha','tolerance','solver_tolerance')
REJECTIONS = ('nan_atom','trailing_byte','truncated','max_values','model_load_data_frame','self_reference')


def is_training(slot):
    return slot.get('protocol')==PROTOCOL


def tool_path(build):
    from .corad_execution import tool_path as encode_path
    return encode_path(build).with_name(TARGET)


def programs(slot):
    env=slot.get('source_runtime')
    return {f'python/{PYTHON}':env} if env else {}


def source_runtime(root, bundle):
    prefix=Path(sys.prefix).resolve(strict=True)
    python=Path(sys.executable).resolve(strict=True)
    require(python.is_relative_to(prefix) and sys.version_info[:3]==(3,11,5),'CORAD Source requires the prepared tsbench Python')
    lock_id=check_tsbench(root)
    versions=bundle['policy']['source']['versions']
    for name,version in versions.items():
        package=metadata.distribution('scikit-learn' if name=='sklearn' else name)
        require(package.version==version and Path(package.locate_file('')).resolve().is_relative_to(prefix),
                f'CORAD Source dependency does not match tsbench: {name}')
    return {'executable':'/toolchain/bin/python','python_sha256':digest(python),'python_version':'3.11.5',
            'environment_lock_id':lock_id,'environment_lock_sha256':bundle['environment_lock_sha256'],
            'versions':versions,'mount_scope':'read_only_locked_tsbench_prefix_no_project_or_heldout',
            'thread_environment':bundle['policy']['source']['thread_environment']}


def bridge_bytes(root,bundle):
    from ..api import check_sources
    source=check_sources(root,source_ids={'corad-native'})['sources']['corad-native']['archive']
    require(source['sha256']==bundle['archive_sha256'],'CORAD Source package identity differs')
    with tarfile.open(verify_asset(root,source),'r:gz') as tar:
        item=tar.getmember(BRIDGE)
        require(item.isfile() and 0<item.size<=FILE_CEILING,'CORAD Source bridge outside size bound')
        with tar.extractfile(item) as f:
            data=f.read()
    require(identity(data)['sha256']==bundle['bridge_sha256'],'CORAD Source bridge content differs')
    return data


def parts(bundle,method):
    result={a['path']:a['bytes'] for data in bundle['data'].values() for a in (data['timestamps'],data['values'])}
    labels=['c-lars'] if method==C else bundle['source_labels']
    n=bundle['data']['evaluation']['values']['bytes']
    for k in labels:
        result.update({k+'.model.crd1':FILE_CEILING,k+'.heldout.crd1':FILE_CEILING,k+'.restored.f64le':n})
    if method==SOURCE:
        result.update({STAGED_BRIDGE:FILE_CEILING,VECTORS:FILE_CEILING,**{k+'.json':FILE_CEILING for k in labels}})
    return result


def plan_slots(root):
    bundle,data=plan_corad_training(root)
    source=source_runtime(root,bundle)
    bridge=bridge_bytes(root,bundle)
    original=tuple(v for kind in ('train','evaluation') for v in data[kind])
    slots,bindings={},{}
    for method in CHECKS:
        body={'protocol':PROTOCOL,'method':method,'bundle':bundle,'parts':parts(bundle,method)}
        if method==SOURCE:
            body['source_runtime']=source
        sid=content_id(body)
        slots[sid]={**body,'product_slot':sid},BatchInput(b'',original+((bridge,) if method==SOURCE else ()))
        for c in bundle['cases']:
            if c['route']==method:
                bindings[c['case_id']]=bundle['bundle_id'],[sid]
    return slots,bindings


def limits(plan, tool=None):
    base={**plan['limits'],'file_bytes':FILE_CEILING}
    return {**base,'address_space_bytes':768<<20,'wall_seconds':25} if tool==PYTHON else base


def check_slots(plan):
    rows=[r for r in plan['slots'] if is_training(r)]
    require([r['method'] for r in rows]==list(CHECKS),'CORAD must cover both C and Source training')
    b=rows[0]['bundle']
    require(rows[1]['bundle']==b and b['bundle_id']==content_id({k:v for k,v in b.items() if k!='bundle_id'}) and
            b['qualification_granted'] is False and len(b['cases'])==11 and
            b['data']['train']['timestamps']['bytes']==129*8 and b['data']['evaluation']['timestamps']['bytes']==67*8 and
            b['data']['train']['last_timestamp']<b['data']['evaluation']['first_timestamp'] and
            list(b['source_labels'])==['source-sklearn','source-sklearn-repeat'] and
            b['c_options']['max_training_samples']==96 and b['c_options']['training_columns']==7,
            'CORAD shared training bundle or holdout scope differs')
    for s in rows:
        require(s['parts']==parts(b,s['method']) and max(s['parts'].values())<=FILE_CEILING and
                s.keys()=={'protocol','method','product_slot','bundle','parts'}|({'source_runtime'} if s['method']==SOURCE else set()),
                'CORAD training slot or resource ceiling differs')
    env=rows[1]['source_runtime']
    require(env['environment_lock_sha256']==b['environment_lock_sha256'] and
            env['versions']==b['policy']['source']['versions'] and env['thread_environment']==b['policy']['source']['thread_environment'] and
            env['executable']=='/toolchain/bin/python' and env['python_version']=='3.11.5' and
            env['mount_scope']=='read_only_locked_tsbench_prefix_no_project_or_heldout', 'CORAD Source runtime differs')


def steps(slot):
    b=slot['bundle']; size=str(b['data']['evaluation']['values']['bytes']//8)
    recipe={}
    def add(label,argv,mounts,outputs,tool=TOOL):
        recipe[label]={'tool':tool,'argv':list(argv),'inputs':list(mounts),'outputs':list(outputs)}
    if slot['method']==C:
        opts=list(map(str,(b['c_options'][k] for k in OPTION_KEYS)))
        add('solver-controls',['controls',*opts],[],[])
        for label,cmd in (('fit-0','fit'),('fit-1','fit'),('fit-cap','fit-cap'),('fit-mask','fit-mask')):
            add(label,[cmd,'/inputs/train',*opts],['train'],['model'] if cmd=='fit' else [])
        labels=('c-lars',)
    else:
        labels=b['source_labels']
        for label in labels:
            add('train-'+label,source_argv(b,label),[STAGED_BRIDGE,VECTORS],[label+'.json'],PYTHON)
            add('pack-'+label,['pack','/inputs/arrays'],['arrays'],['model'])
    for label in labels:
        add('evaluate-'+label,['/inputs/model','/inputs/values'],['model','values'],['native'],ENCODE)
        add('restore-'+label,['decode','/inputs/frame',size],['frame'],['values'])
        for neg in REJECTIONS:
            if neg=='model_load_data_frame':
                add(label+'-'+neg,['model-load','/inputs/frame'],['frame'],[])
            else:
                add(label+'-'+neg,['decode','/inputs/frame',str(int(size)-1) if neg=='max_values' else size],['frame'],[])
                if neg=='self_reference':
                    recipe[label+'-'+neg]['when']='native_reference_exists'
    return recipe


def operations(slot):
    return [(label,s['tool']) for label,s in steps(slot).items()]
