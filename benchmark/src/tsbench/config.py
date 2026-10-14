"""One strict TOML experiment, expanded before execution."""
from copy import deepcopy
from pathlib import Path
import math
import re
import tomllib

DEFAULT_TASK={'kind':'values','fidelity':'bitwise','boundary':'object_memory','lifecycle':'independent_object','cache_policy':'natural'}
DEFAULT_EXECUTION={'sessions':1,'rounds':7,'warmup_objects':2,'seed':20261012,'timeout_s':120,'qualification_cache':True,'save_artifacts':True}
DEFAULT_PROFILE={'id':'cpu-single','device':'cpu','native_threads':1,'object_workers':1,'memory_limit_mb':4096}


def _unknown(d,allowed,label):
    if not isinstance(d,dict): raise ValueError(f'{label} must be a table')
    unknown=set(d)-set(allowed)
    if unknown: raise ValueError(f'{label}: unknown fields {sorted(unknown)}')


def _positive(v,label,minimum=1):
    if type(v) is not int or v<minimum: raise ValueError(f'{label} must be integer >= {minimum}')


def resolve(source,base_dir=None):
    c=deepcopy(source)
    _unknown(c,{'schema','name','output','asset_root','build_root','datasets','methods','profiles','task','execution','analysis'},'experiment')
    if c.get('schema')!='tsbench.experiment/1': raise ValueError('schema must be tsbench.experiment/1')
    if not isinstance(c.get('name'),str) or not c['name']: raise ValueError('experiment needs name')
    base=Path(base_dir or '.').resolve()
    c['_base_dir']=str(base)
    c['_asset_root']=str(Path(c.get('asset_root',Path(__file__).resolve().parents[3])).expanduser().resolve())
    if c.get('asset_root') and not Path(c['asset_root']).is_absolute(): c['_asset_root']=str((base/c['asset_root']).resolve())
    c['_build_root']=str(Path(c.get('build_root',Path(c['_asset_root'])/'build/tsbench')).expanduser().resolve())
    if c.get('build_root') and not Path(c['build_root']).is_absolute(): c['_build_root']=str((base/c['build_root']).resolve())
    output=Path(c.get('output',Path(c['_asset_root'])/'runs'/c['name'])).expanduser()
    c['output']=str(output if output.is_absolute() else (base/output).resolve())
    if not c.get('datasets') or not c.get('methods'): raise ValueError('need datasets and methods')
    for group in ('datasets','methods','profiles'):
        if group=='profiles': c[group]=c.get(group,[DEFAULT_PROFILE.copy()])
        if not isinstance(c[group],list) or not c[group]: raise ValueError(f'{group} must be a nonempty array')
        ids=[]
        for d in c[group]:
            if not isinstance(d,dict) or not isinstance(d.get('id'),str) or not d['id']: raise ValueError(f'{group} entries need id')
            if not re.fullmatch(r'[\w.-]+',d['id']) or d['id'] in {'.','..'}:raise ValueError(f'{group} id must be a safe token without separators')
            ids.append(d['id'])
        if len(set(ids))!=len(ids): raise ValueError(f'duplicate {group} id')
    for d in c['datasets']:
        _unknown(d,{'id','format','path','component','key','components','columns','dtype','encoding','delimiter','timestamp_column','timestamp_parser','time_unit','missing_tokens','missing','fill_value','schema','start','stop','step','columns_indices','order','source','license'},'dataset')
        if 'path' not in d: raise ValueError('dataset needs path')
        if d.get('format')=='csv' and 'dtype' not in d: raise ValueError('CSV requires dtype')
        if d.get('missing','reject') not in {'reject','mask'}: raise ValueError('unknown missing policy')
        if d.get('order','C') not in {'C','F'}: raise ValueError('order must be C/F')
        from .data import validate_selection_spec
        validate_selection_spec(d)
    for m in c['methods']:
        _unknown(m,{'id','codec','params','components','chunk_rows','channelwise','transform'},'method')
        if not isinstance(m.get('codec'),str): raise ValueError('method needs codec')
        m.setdefault('params',{})
        if not isinstance(m['params'],dict): raise ValueError('method params must be a table')
        for name,entry in m.get('components',{}).items():
            _unknown(entry,{'codec','params','transform'},f'component method {name}')
            if not isinstance(entry.get('codec'),str): raise ValueError('component needs codec')
            entry.setdefault('params',{})
        for route in [m,*m.get('components',{}).values()]:
            if route.get('transform','identity') not in {'identity','integer_affine_gcd'}:raise ValueError('unknown method transform')
        if 'chunk_rows' in m: _positive(m['chunk_rows'],'chunk_rows')
        if 'channelwise' in m and type(m['channelwise']) is not bool: raise ValueError('channelwise must be boolean')
    task=c.setdefault('task',{})
    _unknown(task,set(DEFAULT_TASK)|{'error_bound','relative_floor','special_values','invalid_values'},'task')
    c['task']={**DEFAULT_TASK,**task};task=c['task']
    if task['kind'] not in {'values','timestamps','records','component'}: raise ValueError('unsupported task kind')
    if task['fidelity'] not in {'bitwise','numeric_equivalent','bounded_abs','range_relative','point_relative','empirical_quality'}: raise ValueError('unknown fidelity')
    if task['boundary']!='object_memory' or task['lifecycle']!='independent_object' or task['cache_policy']!='natural':
        raise ValueError('this CPU executor supports object_memory/independent_object/natural only')
    if type(task.get('error_bound')) is bool:raise ValueError('error_bound must be a quality number; boolean is not accepted')
    if task['fidelity'] in {'bounded_abs','range_relative','point_relative'}:
        if 'error_bound' not in task or not math.isfinite(float(task['error_bound'])) or float(task['error_bound'])<0: raise ValueError('quality task needs finite nonnegative error_bound')
    if 'relative_floor' in task and (type(task['relative_floor']) is bool or not math.isfinite(float(task['relative_floor'])) or float(task['relative_floor'])<0):raise ValueError('relative_floor must be finite nonnegative; boolean is not accepted')
    if task.get('special_values','bitwise')!='bitwise':raise ValueError('special_values policy currently requires bitwise')
    if task.get('invalid_values','preserve')!='preserve':raise ValueError('invalid_values currently requires preserve')
    for p in c['profiles']:
        _unknown(p,{'id','device','native_threads','object_workers','affinity','memory_limit_mb','runtime_preload'},'profile')
        p.update({**DEFAULT_PROFILE,**p})
        _positive(p['native_threads'],'native_threads');_positive(p['object_workers'],'object_workers')
        if p['device']!='cpu' or p['object_workers']!=1: raise ValueError('CPU sequential executor requires device=cpu/object_workers=1')
        if 'affinity' in p and (not isinstance(p['affinity'],list) or not p['affinity'] or any(type(x) is not int or x<0 for x in p['affinity'])): raise ValueError('affinity needs nonnegative cpu IDs')
        if 'memory_limit_mb' in p:_positive(p['memory_limit_mb'],'memory_limit_mb')
        preload=p.get('runtime_preload',[])
        if not isinstance(preload,list) or any(not isinstance(x,str) for x in preload):raise ValueError('runtime_preload must be an array of absolute library paths')
        from .runtime import worker_environment
        worker_environment({},p)
    ex=c.setdefault('execution',{})
    _unknown(ex,set(DEFAULT_EXECUTION)|{'total_budget_s','max_pending_workers','retry'},'execution')
    c['execution']={**DEFAULT_EXECUTION,**ex};ex=c['execution']
    for k in ('sessions','rounds'):_positive(ex[k],k)
    _positive(ex['warmup_objects'],'warmup_objects',0)
    if type(ex['seed']) is not int: raise ValueError('seed must be integer')
    if type(ex['timeout_s']) is bool or not math.isfinite(float(ex['timeout_s'])) or ex['timeout_s']<=0: raise ValueError('timeout_s must be positive finite')
    if 'total_budget_s' in ex and (type(ex['total_budget_s']) is bool or not math.isfinite(float(ex['total_budget_s'])) or ex['total_budget_s']<=0):raise ValueError('total_budget_s must be positive finite')
    if 'max_pending_workers' in ex:_positive(ex['max_pending_workers'],'max_pending_workers')
    if type(ex.get('retry',False)) is not bool:raise ValueError('retry must be boolean')
    for k in ('qualification_cache','save_artifacts'):
        if type(ex[k]) is not bool: raise ValueError(f'{k} must be bool')
    a=c.setdefault('analysis',{})
    _unknown(a,{'summary','inference'},'analysis')
    a.setdefault('summary','median_iqr');a.setdefault('inference','none')
    if a['inference']!='none' or a['summary']!='median_iqr': raise ValueError('only descriptive median_iqr/none is implemented')
    return c


def load(path):
    p=Path(path).expanduser().resolve(strict=True)
    with p.open('rb') as f: c=resolve(tomllib.load(f),p.parent)
    c['_config_path']=str(p)
    return c
