"""Bind actual C11 and shipped Source training as distinct development workloads."""
from hashlib import sha256
import math
from pathlib import Path
import struct

from ..assets import content_id, digest, load_json, local_file, require, verify_asset
from ..build.environment import LOCK
from .corad_inference import CONFIG
from .corpus_windows import bind_training_window, bind_window, read_tv_window

POLICY = 'configs/suites/dev_corad_v1/training-policy.json'
TEST = 'tsbench.control.corad'
DIR = 'corad-native-control'
BRIDGE = 'corad-native/source_backend/train.py'
STAGED_BRIDGE = 'source-bridge.py'
VECTORS = 'source-input.npy'
NATIVE_REJECTIONS = {'insufficient_training_samples':2,'out_of_range_mask':1,'sparse_nonconvergence':5}
CHECKS = {
    'corad-c-training': ('disjoint_train_only','explicit_seed_column_mask_and_sample_caps','lars_and_cd_known_answer',
                         'kkt_and_sparse_nonconvergence','outer_limit_reported_separately','heldout_with_frozen_model'),
    'corad-source-training': ('disjoint_train_only','locked_sklearn_bridge','model_and_dictionary_bound',
                              'heldout_native_inference','training_budget_and_repeatability_policy'),
}


def ref(name, raw):
    return {'path':name,'bytes':len(raw),'sha256':sha256(raw).hexdigest()}


def retained_paths(bundle):
    return {f'{DIR}/{name}' for name in (*bundle['artifacts'], *(a[k]['path'] for a in bundle['data'].values()
                         for k in ('timestamps','values')))}


def source_argv(bundle, label):
    return ['-I','-B',STAGED_BRIDGE,'--input',VECTORS,'--output',label+'.json','--atoms',str(bundle['model']['atoms']),
            '--alpha',str(bundle['c_options']['alpha']),'--source-root','.']


def _columns(root, cfg, kind, binder):
    windows, words = [], []
    stamps = None
    for col in cfg['columns']:
        window = binder(root,cfg['corpus'],cfg['corpus_id'],{'dataset':cfg['dataset'],'column':col,**cfg[kind]})
        ts, values = read_tv_window(root,window)
        require(stamps is None or stamps==ts,'CORAD training column timestamps differ')
        require(all(math.isfinite(x) for (x,) in struct.iter_unpack('<d',values)),'nonfinite CORAD development input')
        stamps = ts
        words.append(values)
        windows.append(window)
    raw = b''.join(words)
    ticks = [x for (x,) in struct.iter_unpack('<q',stamps)]
    require(len(ticks)==cfg[kind]['count'] and all(a<b for a,b in zip(ticks,ticks[1:])),
            'CORAD window is not strictly ordered')
    return ({'windows':windows,'first_timestamp':ticks[0],'last_timestamp':ticks[-1],
             'timestamps':ref(f'{kind}.i64le',stamps),'values':ref(f'{kind}.f64le',raw)},(stamps,raw))


def plan_corad_training(root: Path):
    cfg = load_json(local_file(root,CONFIG))
    policy = load_json(local_file(root,POLICY))
    require(policy == {'schema':'bmk.dev-corad-training-policy/1','capacity_bytes_per_artifact':16384,
                       'statistics_absolute_tolerance':1e-10,'quality':'observed_only_no_formal_budget',
                       'c':{'abi_size':72,'version':1,'solver':0,'normalize':1,'objective_tolerance':1e-8,'seeded_repetitions':2},
                       'source':{'fresh_processes':2,'max_iter':10,'timeout_seconds':25,
                                 'random_state':'upstream_default_not_bit_reproducible',
                                 'thread_environment':{k:'1' for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')},
                                 'versions':{'numpy':'1.24.3','pandas':'2.0.3','scipy':'1.11.1','sklearn':'1.3.0'}}},
            'invalid bounded CORAD training policy')
    require(cfg['schema']=='bmk.dev-corad-cases/1' and cfg['selection']==80 and cfg['c_sparse_solver']=='lars' and
            cfg['training_column_mask']==7 and cfg['columns']==['pressure','air_temperature','relative_humidity'] and
            cfg['train']['count']==129 and cfg['evaluation']['count']==67 and cfg['tricklet']==4 and
            cfg['atoms']==4 and cfg['nonzero']==2 and cfg['threshold']==0.9 and cfg['alpha']==0.25 and
            2<=cfg['c_max_iter']<=10 and 0<cfg['c_solver_max_iter']<=4000 and 0<cfg['c_sparse_solver_tolerance']<=1e-8,
            'invalid frozen CORAD training configuration')
    data, raw = {},{}
    for kind,binder in [('train',bind_training_window),('evaluation',bind_window)]:
        data[kind],raw[kind] = _columns(root,cfg,kind,binder)
    train, held = data['train'],data['evaluation']
    require(train['last_timestamp']<held['first_timestamp'] and
            train['windows'][0]['partition_end']<=held['windows'][0]['partition_start'], 'CORAD overlapping train/held-out')
    from ..api import check_sources
    source = check_sources(root,source_ids={'corad-native'})['sources']['corad-native']
    manifest = load_json(verify_asset(root,source['source_manifest']))
    [bridge] = [x['sha256'] for x in manifest['files'] if x['path']==BRIDGE]
    size = (cfg['train']['count']//cfg['tricklet'])*cfg['training_column_mask'].bit_count()
    c = policy['c']
    opts = {'size':c['abi_size'],'version':c['version'],'solver':c['solver'],'normalize':c['normalize'],
            'seed':cfg['c_seed'],'training_columns':cfg['training_column_mask'],'max_training_samples':size,
            'alpha':cfg['alpha'],'max_iter':cfg['c_max_iter'],'solver_max_iter':cfg['c_solver_max_iter'],
            'tolerance':c['objective_tolerance'],'solver_tolerance':cfg['c_sparse_solver_tolerance']}
    source_labels = ['source-sklearn', 'source-sklearn-repeat']
    models = ['c-lars', *source_labels]
    body = {'schema':'bmk.corad-training-cases/1','test':TEST,'evidence_path':DIR+'/audit.json','config_id':content_id(cfg),
            'policy':policy,'columns':cfg['columns'],'data':data,'archive_sha256':source['archive']['sha256'],
            'bridge_sha256':bridge,'environment_lock_sha256':digest(local_file(root,LOCK)),'c_options':opts,
            'native_rejections':NATIVE_REJECTIONS,'source_labels':source_labels,'models':models,
            'model':{'columns':len(cfg['columns']),**{k:cfg[k] for k in ('tricklet','atoms','nonzero','threshold')}},
            'artifacts':[STAGED_BRIDGE,VECTORS, *(x+'.json' for x in source_labels),
                         *(x+s for x in models for s in ('.model.crd1','.heldout.crd1','.restored.f64le'))],
            'qualification_granted':False}
    policy_id = content_id(body)
    body['cases'] = []
    for route,checks in CHECKS.items():
        for check in checks:
            row = {'name':route.removeprefix('corad-')+'-'+check.replace('_','-'),'selection':80,'route':route,
                   'check':check,'policy_id':policy_id}
            body['cases'].append({**row,'case_id':content_id(row)})
    return {**body,'bundle_id':content_id(body)},raw
