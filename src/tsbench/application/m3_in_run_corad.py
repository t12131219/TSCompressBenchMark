"""Measured CORAD fits and held-out consumers on the primary M3 ledger."""
from collections import Counter, defaultdict
from functools import partial
from math import isfinite
from pathlib import Path
from random import Random
from statistics import median
import shutil
import struct
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns

from ..assets import content_id, digest, load_json, local_file, require
from ..planner.corad_corpus import C, INFERENCE, SOURCE, TRAINERS
from ..planner.corad_training import STAGED_BRIDGE, VECTORS, plan_corad_training
from ..planner.corad_training_execution import bridge_bytes
from ..planner.m3_corad import DRIVER, FOLDER
from ..planner.m3_corad_ingress import bind_cohorts
from ..qualification.corad_training import _normalization
from ..qualification.corad_wire import interpret
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.corad_source import invoke_source
from ..supervisor.isolated_worker import invoke_isolated_tool
from .corad_corpus_execution import LIMITS, SOURCE_LIMITS, _identity, _ref, _stage, judge_quality
from .corad_training_execution import _npy
from .m3_in_run_failure import _sync
from .m3_in_run_measurement import guard
from .m3_metric_details import distribution

DIRECTORY = 'measurement-corad-anchors'
FAILED = 'measurement-corad-failures'
TOOL = 'corad-corpus-clock'
ROUNDS = 3
READY = ('verified','quality_rejected')
NATIVE = {'c-train':('corad_model_train','corad_model_save'), 'source-pack':('corad_model_pack',),
          'encode':('corad_model_load','corad_model_config','corad_model_encode'), 'decode':('corad_decode',)}
BILL = ('header_bytes','embedded_model_bytes','tricklet_record_bytes','tail_bytes')


def timed_bridge(raw):
    # Keep the exact archive script, options and shipped RNG. The only additional
    # work inside the fit boundary is two monotonic/CPU clock reads.
    return ('''import functools, json, time
from sklearn.decomposition import DictionaryLearning
_fit = DictionaryLearning.fit
_clocks = []
@functools.wraps(_fit)
def _measured(self, *args, **kwargs):
    wall, cpu = time.monotonic_ns(), time.process_time_ns()
    result = _fit(self, *args, **kwargs)
    _clocks.append({"call":"DictionaryLearning.fit", "cpu_ns":time.process_time_ns()-cpu, "wall_ns":time.monotonic_ns()-wall})
    return result
DictionaryLearning.fit = _measured
exec(compile(''' + repr(raw) + ''', 'frozen-source-bridge.py', 'exec'), {})
assert len(_clocks) == 1
print(json.dumps({"calls":_clocks}))
''').encode('utf-8')


def bridge(root):
    source,_ = plan_corad_training(root)
    return timed_bridge(bridge_bytes(root,source))


def schedule(route,cid):
    ops = ('encode','decode') if route == INFERENCE else ('train',)
    rng = Random(f'20261120/corad/{cid}')
    for r in range(ROUNDS+1):
        for op in rng.sample(ops,len(ops)):
            yield {'round':r,'phase':'measured' if r else 'warmup','direction':op,'path':f'{DIRECTORY}/{cid}/{r:02d}-{op}'}


def _file(root,ref):
    p = local_file(root,ref['path'])
    require(_ref(root,p) == ref,'CORAD measurement file changed')
    return p


def _bindings(root,item,entry):
    contract=item['input']['corad_contract']
    return bind_cohorts(root,entry,[c for c in contract['cohorts'] if c['state']=='eligible'],contract['layout'])


def _width(b):
    return len(b['ordered_columns'])


def _count(span):
    a,z=span['absolute_rows']; return z-a


def _dep(run,b,producer):
    name=b['input_binding_id']; prefix=f'products/{name}/{producer}'
    root=run/FOLDER
    p=local_file(root,f'{prefix}/deployment.json'); dep=load_json(p)
    require(dep == {'dataset':b['source'],'producer':producer,'input_binding_id':name,
                    'producer_binding_id':b['producer_binding_ids'][producer],'train':b['train'],
                    'ordered_columns':b['ordered_columns'],'model':dep['model'],
                    'deployment_id':content_id({k:v for k,v in dep.items() if k!='deployment_id'})} and
            dep['model']['path']==f'{prefix}/model.crd1','CORAD same-run deployment identity differs')
    model=_file(root,dep['model']); _,shape,arrays=interpret(model.read_bytes())
    require((shape['rows'],shape['columns'])==(0,_width(b)),'CORAD same-run model geometry differs')
    return dep,model,arrays


def _cases(root,plan,item,row,entry,run,material=None):
    e=row['evidence']; route=item['route']; material=material if material is not None else _bindings(root,item,entry)
    require(row['status'] in READY and e['driver']==DRIVER and e['artifact_root']==FOLDER and not e['execution_errors'] and
            e['cohort_ids']==[b['input_binding_id'] for b,_,_ in material],'CORAD same-run input cohort identities differ')
    result=[]
    if route != INFERENCE:
        fits=e['fits']; require(e['producer']==route and len(fits)==e['expected_fits']==len(material),'CORAD fit denominator differs')
        for (b,train,_),fit in zip(material,fits,strict=True):
            dep,model,_ = _dep(run,b,route)
            require(fit['status']=='verified' and fit['deployment']==dep and fit['input_binding_id']==b['input_binding_id'],
                    'CORAD measured training lacks same-run producer result')
            result.append({'b':b,'train':train,'producer':route,'fixed_model':model,'fit':fit})
        return result
    n=sum(len(tests) for _,_,tests in material)
    require(e['input_bindings']==[b for b,_,_ in material] and e['expected_frames']==2*n and
            set(e['evaluations'])==set(TRAINERS) and all(len(e['evaluations'][p])==n for p in TRAINERS),
            'CORAD inference population differs')
    for p in TRAINERS:
        rows=iter(e['evaluations'][p])
        for b,_,tests in material:
            dep,model,arrays=_dep(run,b,p)
            for i,(span,raw) in enumerate(zip(b['test_frames'],tests,strict=True)):
                r=next(rows)
                require(r['status'] in READY and r['input_binding_id']==b['input_binding_id'] and r['producer']==p and
                        r['deployment_id']==dep['deployment_id'] and r['frame_range']==span['absolute_rows'] and
                        r['frame']['path']==f'products/{b["input_binding_id"]}/{p}/heldout-{i}.crd1' and
                        r['logical_value_bytes']==len(raw),'CORAD measured held-out frame identity differs')
                frame=_file(run/FOLDER,r['frame']); recovered,meta,assembled=interpret(frame.read_bytes(),max_values=131072)
                q,ok=judge_quality(raw,recovered,b['ordered_columns'],b['train_only_quality_bounds'])
                require((meta['rows'],meta['columns'])==(_count(span),_width(b)) and assembled==arrays and
                        r['restore']==_identity(recovered) and r['original_domain_metrics']==q and
                        r['status']==('verified' if ok else 'quality_rejected') and r['quality_gates']==b['train_only_quality_bounds'] and
                        r['frame_accounting']=={k:meta[k] for k in BILL} and sum(r['frame_accounting'].values())==r['frame']['bytes'],
                        'CORAD same-run held-out accounting or independent original-domain quality differs')
                result.append({'b':b,'span':span,'raw':raw,'producer':p,'fixed_model':model,'fixed_frame':frame,'evaluation':r})
    require(any(c['evaluation']['status']=='quality_rejected' for c in result)==(row['status']=='quality_rejected'),
            'CORAD functional quality terminal disagrees with constituent held-out samples')
    return result


def _source_arrays(case):
    raw=case['train']; w=_width(case['b']); rows=_count(case['b']['train']); column_bytes=rows*8
    means,scales,vectors=_normalization([raw[i:i+column_bytes] for i in range(0,len(raw),column_bytes)],4,(1<<w)-1)
    return means,scales,_npy(vectors,len(vectors)//4,4)


def _dictionary(case, model_json):
    import math
    n=(_count(case['b']['train'])//4)*_width(case['b']); d=model_json['dictionary']
    require(set(model_json)=={'backend','max_iter','alpha','dictionary','rows','features'} and
            (model_json['backend'],model_json['max_iter'],model_json['alpha'],model_json['rows'],model_json['features'])==
            ('upstream-CORAD-sklearn-DictionaryLearning',10,.25,n,4) and
            isinstance(d,list) and len(d)==4 and all(isinstance(a,list) and len(a)==4 and
                all(type(v) in (float,int) and math.isfinite(v) for v in a) for a in d),'CORAD Source trained dictionary differs')
    return [x for a in d for x in a]


def _run_native(runtime,spec,work,record,label,paths,args,name):
    step=work/label; step.mkdir()
    out,p=invoke_isolated_tool(runtime,spec,TOOL,LIMITS,step,work,label,paths,args,lambda:False,observe=True)
    record[label]=p
    require(p['status']=='completed' and p['returncode']==0 and not (work/f'{label}.stderr').stat().st_size,
            f'CORAD {label} did not complete: {p["status"]}')
    obs=load_json(local_file(work,f'{label}.stdout'))
    product=local_file(out,name)
    require(obs['functional']['native_status']==0 and {x.name for x in out.iterdir()}=={name} and
            product.stat().st_size==obs['functional']['output_bytes'],'CORAD native product closure differs')
    return product


def _unit(run,plan,work,runtime,case,op,bridge_data,record):
    b=case['b']; w=_width(b); binding=plan['measurement']['corad_clock']; spec=binding['runtime']
    native=partial(_run_native,runtime,spec,work,record)
    if op=='train':
        if case['producer']==C:
            raw=_stage(work/'train',case['train']); model=native('c-train',{'train':raw},['train','/inputs/train',str(w)],'model')
            require(model.read_bytes()==case['fixed_model'].read_bytes(),'CORAD measured C fit differs from same-run deterministic fit')
            extras={}
        else:
            means,scales,npy=_source_arrays(case)
            parts={STAGED_BRIDGE:_stage(work/STAGED_BRIDGE,bridge_data),VECTORS:_stage(work/VECTORS,npy)}
            step=work/'source-train';step.mkdir()
            argv=['-I','-B',STAGED_BRIDGE,'--input',VECTORS,'--output','trained.json','--atoms','4','--alpha','0.25','--source-root','.']
            out,p=invoke_source(binding,{'argv':argv,'outputs':['trained.json']},SOURCE_LIMITS,step,work,'source-train',parts,lambda:False)
            record['source-train']=p
            require(p['status']=='completed' and p['returncode']==0 and
                    {x.name for x in out.iterdir()}=={'trained.json'},'CORAD measured Source fit did not complete')
            trained=local_file(out,'trained.json'); atoms=_dictionary(case,load_json(trained))
            arrays=_stage(work/'arrays',struct.pack(f'<{16+2*w}d',*atoms,*means,*scales))
            model=native('source-pack',{'arrays':arrays},['pack','/inputs/arrays',str(w)],'model')
            _,meta,blob=interpret(model.read_bytes())
            require((meta['rows'],meta['columns'])==(0,w) and blob==struct.pack(f'<{16+2*w}d',*atoms,*(x for pair in zip(means,scales,strict=True) for x in pair)),
                    'CORAD measured Source model arrays differ from train-only fit')
            extras={'dictionary.json':trained}
        output=model; extras['model.crd1']=model
    else:
        dims=[str(_count(case['span'])),str(w)]; r=case['evaluation']
        if op=='encode':
            raw=_stage(work/'test',case['raw'])
            output=native(op,{'model':case['fixed_model'],'test':raw},['encode','/inputs/model','/inputs/test',*dims],'frame')
            require(_identity(output.read_bytes())=={k:r['frame'][k] for k in ('bytes','sha256')},'CORAD repeated encode changed fixed held-out frame')
        else:
            output=native(op,{'frame':case['fixed_frame']},['decode','/inputs/frame',*dims],'values')
            require(_identity(output.read_bytes())==r['restore'],'CORAD measured frame-only restore differs from verified quality evidence')
        extras={}
    for p in {output,*extras.values()}:
        _sync(p); _sync(p.parent); _sync(p.parent.parent)
    return _identity(output.read_bytes()),extras


def _publish(run,base,work,record,extras):
    paths={f'{label}.{suffix}':local_file(work,f'{label}.{suffix}') for label in record for suffix in ('stdout','stderr')}
    paths.update(extras)
    base.mkdir(parents=True)
    refs={}
    for name,path in paths.items():
        shutil.copyfile(path,base/name); _sync(base/name); refs[name]=_ref(run,base/name)
    for place in (base,base.parent,base.parent.parent):
        _sync(place)
    return refs


def _trial(plan,run,work,runtime,cases,slot,bridge_data):
    units=[]; path=run/slot['path']; samples=[]
    op=slot['direction']; start,cpu=monotonic_ns(),process_time_ns()
    # Prepare and verify the entire cohort sequence before publishing any log.
    # Publication and scratch reclamation are not included in the operation clock.
    error=None
    for i,case in enumerate(cases):
        scratch=work/f'{i:05d}';scratch.mkdir()
        record={}
        try:
            t=monotonic_ns(); product,extras=_unit(run,plan,scratch,runtime,case,op,bridge_data,record)
            samples.append((scratch,record,extras))
            units.append({'status':'completed','product':product,'processes':record,'wall_ns':monotonic_ns()-t})
        except (ValueError,OSError) as exc:
            error=(str(exc) or type(exc).__name__).replace(scratch.as_posix(),f'unit/{i:05d}')
            target=run/FAILED/Path(slot['path']).parent.name/Path(slot['path']).name/f'{i:05d}'
            refs=_publish(run,target,scratch,record,{}) if record else {}
            units.append({'status':'failed','reason':error,'processes':record,'files':refs})
            break
    wall,controller=monotonic_ns()-start,process_time_ns()-cpu
    for i,(unit,(scratch,record,extras)) in enumerate(zip(units,samples)):
        unit['files']=_publish(run,path/f'{i:05d}',scratch,record,extras)
    if error:
        return {**slot,'status':'measurement_failed','reason':error,'units':units,'unissued_units':len(cases)-len(units)}
    return {**slot,'status':'measured_as_declared','units':units,'whole_verified_durable_wall_ns':wall,'controller_cpu_ns':controller}


def _facts(ref):
    return {k:ref[k] for k in ('bytes','sha256')}


def _positive(x):
    return type(x) is int and x>0


def _verify_process(run,base,label,state,refs,mounts,names,seen,*,success=True):
    p=state
    require(p['operation']==label and p['session_id'] and p['session_id'] not in seen and
            (not success or (p['status']=='completed' and p['returncode']==0 and not p['reason'] and
                             type(p['pid']) is int and p['pid']>0 and _positive(p['process_wall_ns']) and
                             p['input_mounts']==mounts and set(p['child_usage'])=={'user_cpu_ns','system_cpu_ns','maxrss_bytes'} and
                             all(type(v) is int and v>=0 for v in p['child_usage'].values()) and
                             p['child_usage']['maxrss_bytes']>0)), 'CORAD timed isolation, process or mounts differ')
    seen.add(p['session_id'])
    stdout,stderr=(_file(run,refs[f'{label}.{suffix}']) for suffix in ('stdout','stderr'))
    require(not success or label=='source-train' or stderr.stat().st_size==0,'CORAD native clock stderr differs')
    if not success:
        return None
    obs=load_json(stdout)
    require(set(obs)==({'calls'} if label=='source-train' else {'calls','driver_wall_ns','functional'}) and
            [c['call'] for c in obs['calls']]==list(names) and all(set(c)=={'call','wall_ns','cpu_ns'} and
                _positive(c['wall_ns']) and type(c['cpu_ns']) is int and c['cpu_ns']>=0 for c in obs['calls']) and
            0<sum(c['wall_ns'] for c in obs['calls'])<=obs.get('driver_wall_ns',p['process_wall_ns'])<=p['process_wall_ns'],
            'CORAD native/Source call scope differs from measurement contract')
    return obs


def _verify_unit(run,plan,case,slot,unit,base,seen):
    op=slot['direction']; b=case['b']; w=_width(b); refs=unit['files']; procs=unit['processes']
    names={'train':('c-train',) if case['producer']==C else ('source-train','source-pack'),
           'encode':('encode',),'decode':('decode',)}[op]
    failure=unit['status']=='failed'
    require(set(procs)==set(names[:len(procs)]) if failure else set(procs)==set(names),'CORAD expected child process sequence differs')
    products=() if failure or op!='train' else ('model.crd1',) if case['producer']==C else ('model.crd1','dictionary.json')
    expected={*(f'{label}.{suffix}' for label in procs for suffix in ('stdout','stderr')),*products}
    require(set(refs)==expected and all(r['path']==f'{base}/{name}' for name,r in refs.items()),'CORAD retained process coordinates differ')
    if failure:
        for label,p in procs.items():
            _verify_process(run,base,label,p,refs,None,None,seen,success=False)
        return None
    rows=_count(b['train'] if op=='train' else case['span'])
    if op=='train':
        model=_file(run,refs['model.crd1']); model_id=_facts(refs['model.crd1'])
        if case['producer']==C:
            require(model.read_bytes()==case['fixed_model'].read_bytes() and model_id==_facts(case['fit']['deployment']['model']),
                    'CORAD C fit bytes differ on independent audit')
            mounts={'c-train':{'train':b['train']['values']}}
        else:
            means,scales,npy=_source_arrays(case); atoms=_dictionary(case,load_json(_file(run,refs['dictionary.json'])))
            raw=struct.pack(f'<{16+2*w}d',*atoms,*means,*scales)
            _,meta,embedded=interpret(model.read_bytes())
            require((meta['rows'],meta['columns'])==(0,w) and embedded==struct.pack(f'<{16+2*w}d',*atoms,
                        *(x for pair in zip(means,scales,strict=True) for x in pair)),
                    'CORAD Source normalization, dictionary and packed model differ on audit')
            mounts={'source-train':{STAGED_BRIDGE:plan['measurement']['corad_clock']['timed_source_bridge'],VECTORS:_identity(npy)},
                    'source-pack':{'arrays':_identity(raw)}}
        product=model_id
    elif op=='encode':
        mounts={'encode':{'test':case['span']['values'],'model':_identity(case['fixed_model'].read_bytes())}}
        product=_facts(case['evaluation']['frame'])
    else:
        mounts={'decode':{'frame':_facts(case['evaluation']['frame'])}}
        product=case['evaluation']['restore']
    records={}
    for label,p in procs.items():
        obs=records[label]=_verify_process(run,base,label,p,refs,mounts[label],
                                            ('DictionaryLearning.fit',) if label=='source-train' else NATIVE[label],seen)
        if label!='source-train':
            observed=obs['functional']
            if label=='c-train':
                require(observed==case['fit']['native'],'CORAD C fit native stats differ')
            else:
                require(observed=={'native_status':0,'rows':0 if label=='source-pack' else rows,'columns':w,
                                   'output_bytes':product['bytes']},'CORAD native extent differs')
    require(unit['status']=='completed' and unit['product']==product and _positive(unit['wall_ns']) and
            sum(p['process_wall_ns'] for p in procs.values())<=unit['wall_ns'],'CORAD operation product or verified durable scope differs')
    return records


def _round_distribution(key, values, sample_basis):
    require(len(values)==ROUNDS,'CORAD whole-decision repeat denominator differs')
    if key.endswith('_mib_s'):
        require(all(type(v) is float and isfinite(v) and v>=0 for v in values),'invalid CORAD throughput observations')
        # Throughput is a rate, not an integer counter and not additive across rounds.
        return {'count':len(values),'min':min(values),'median':median(values),'max':max(values),'sample_basis':sample_basis}
    return {**distribution(values),'sample_basis':sample_basis}


def _summary(item, row, cases, measured):
    route=item['route']; scopes=TRAINERS if route==INFERENCE else (route,)
    cost={p:{'logical_bytes':sum(len(c['raw'] if route==INFERENCE else c['train']) for c in cases if c['producer']==p),
             'units':sum(c['producer']==p for c in cases)} for p in scopes}
    if route==INFERENCE:
        for p in scopes:
            cohort=[c['evaluation'] for c in cases if c['producer']==p]
            components={k:sum(c['frame_accounting'][k] for c in cohort) for k in BILL}
            total=sum(components.values())
            cost[p].update(artifact_bytes=total,components=components,ratio=cost[p]['logical_bytes']/total,
                           quality_statuses=dict(Counter(e['status'] for e in cohort)))
    sample_basis='independent_whole_decision_round_one_fresh_process_per_native_unit'
    buckets=defaultdict(list)
    for trial, records in measured:
        op=trial['direction']; values=defaultdict(Counter)
        for c,u,r in zip(cases,trial['units'],records,strict=True):
            p=c['producer']; values[p]['sum_unit_verified_durable_wall_ns']+=u['wall_ns']
            for label,obs in r.items():
                usage=u['processes'][label]['child_usage']
                values[p][f'{label}_process_wall_ns']+=u['processes'][label]['process_wall_ns']
                for key in ('user_cpu_ns','system_cpu_ns'):
                    values[p][f'{label}_{key}']+=usage[key]
                key=f'{label}_max_child_peak_rss_bytes'
                values[p][key]=max(values[p][key],usage['maxrss_bytes'])
                for call in obs['calls']:
                    for k in ('wall_ns','cpu_ns'):
                        values[p][f'{call["call"]}_{k}']+=call[k]
            if op=='train':
                values[p]['serialized_model_bytes']+=u['product']['bytes']
        for p,counters in values.items():
            for name,value in counters.items():
                buckets[op,p,name].append(value)
            if op in ('encode','decode'):
                api='corad_model_encode_wall_ns' if op=='encode' else 'corad_decode_wall_ns'
                n=cost[p]['logical_bytes']; scale=1e9/(1<<20)
                buckets[op,p,'native_mib_s'].append(n*scale/counters[api])
                buckets[op,p,'verified_durable_mib_s'].append(n*scale/counters['sum_unit_verified_durable_wall_ns'])
        for key in ('whole_verified_durable_wall_ns','controller_cpu_ns'):
            buckets[op,'all',key].append(trial[key])
    directions={}
    for (op,p,key),xs in buckets.items():
        directions.setdefault(op,{}).setdefault(p,{})[key]=_round_distribution(key,xs,sample_basis)
    return {'dataset_id':item['dataset_id'],'route':route,'operation_config_id':item['operation_config_id'],
            'sample_basis':sample_basis,'cost':cost,'directions':directions,'input_scope':'verified_cohorts_prepared_once_outside_trial',
            'quality_terminal':row['status'],'qualified_performance_samples':0,'diagnostic_only':row['status']=='quality_rejected',
            'native_threads':1 if route!=SOURCE else None,
            'source_threads_note':'one pinned CPU, numerical backend thread limits set to one; active thread census not observed' if route==SOURCE else None}


def _inventory(run,directory,files):
    root=run/directory; entries=list(root.rglob('*'))
    require(not root.is_symlink() and all(not p.is_symlink() for p in entries) and
            files=={p.relative_to(run).as_posix() for p in entries if p.is_file()},'CORAD retained trial inventory differs')


def recompute(root,plan,item,entry,run,row,doc,seen,*,cases=None):
    frozen=plan['measurement']['population'][item['work_item_id']]; cid=frozen['case_id']
    cases=cases if cases is not None else _cases(root,plan,item,row,entry,run)
    done='measured_quality_rejected' if row['status']=='quality_rejected' else 'measured_and_verified'
    passed=doc['status']==done
    require(doc['case_id']==cid and doc['adapter']==frozen['adapter'] and doc['timing_admitted'] is False and
            doc['status'] in ('measurement_failed',done) and (doc['reason'] is None if passed else bool(doc['reason'])) and
            doc['anchors']=={'units':len(cases),'reference':'same_run_functional_products'},'CORAD measurement terminal or reference differs')
    expected=list(schedule(item['route'],cid)); measured=[]; failed=False; files=set(); failures=set()
    require(len(expected)==len(doc['trials']),'CORAD operation trial denominator differs')
    for slot,t in zip(expected,doc['trials'],strict=True):
        require(all(t[k]==v for k,v in slot.items()),'CORAD frozen trial slot differs')
        if failed:
            require(t['status']=='not_run_after_measurement_failure' and t.get('reason')==doc['reason'],'CORAD unissued trial was counted')
            continue
        if t['status']=='measurement_failed':
            require(not passed and t['reason']==doc['reason'] and 0<len(t['units'])<=len(cases) and
                    t['unissued_units']==len(cases)-len(t['units']) and t['units'][-1]['status']=='failed' and
                    all(u['status']=='completed' for u in t['units'][:-1]),'CORAD failed trial denominator differs')
            failed=True
        else:
            require(t['status']=='measured_as_declared' and len(t['units'])==len(cases) and
                    all(u['status']=='completed' for u in t['units']) and _positive(t['controller_cpu_ns']) and
                    _positive(t['whole_verified_durable_wall_ns']) and
                    sum(u['wall_ns'] for u in t['units'])<=t['whole_verified_durable_wall_ns'],
                    'CORAD completed trial whole sequence or clock differs')
        clocks=[]
        for i,(u,c) in enumerate(zip(t['units'],cases)):
            base=f"{slot['path']}/{i:05d}"; basket=files
            if u['status']=='failed':
                base=base.replace(DIRECTORY,FAILED,1); basket=failures
            clocks.append(_verify_unit(run,plan,c,slot,u,base,seen)); basket.update(r['path'] for r in u['files'].values())
        if not failed and t['phase']=='measured':
            measured.append((t,clocks))
    require(passed==(not failed) and sorted(failures)==sorted(r['path'] for r in doc['failure_logs']),
            'CORAD failure or retained log census differs')
    _inventory(run,f'{DIRECTORY}/{cid}',files); _inventory(run,f'{FAILED}/{cid}',failures)
    return _summary(item,row,cases,measured) if passed else None


def observe(root,plan,item,entry,run,row):
    m=plan['measurement']; frozen=m['population'][item['work_item_id']]; cid=frozen['case_id']; cpu=m['environment']['cpu']
    # Reuse complete functional artifacts; independent measurements never use r40.
    cases=_cases(root,plan,item,row,entry,run); start=resource.observe(cpu)
    timed=bridge(root) if item['route']==SOURCE else None
    if timed is not None:
        require(_identity(timed)==m['corad_clock']['timed_source_bridge'],'CORAD timed Source bridge changed')
    trials=[]; error=None
    with guard(plan), TemporaryDirectory(prefix='m3-corad-primary-',dir=run) as folder:
        work=Path(folder); runtime=work/'runtime'; stage_recovery(root,work,m['corad_clock']['runtime'],directory=runtime.name)
        (run/DIRECTORY/cid).mkdir(parents=True)
        for slot in schedule(item['route'],cid):
            if error:
                trials.append({**slot,'status':'not_run_after_measurement_failure','reason':error})
                continue
            with TemporaryDirectory(prefix='trial-',dir=work) as tmp:
                trial=_trial(plan,run,Path(tmp),runtime,cases,slot,timed)
            trials.append(trial)
            if trial['status']=='measurement_failed':
                error=trial['reason']
    failures=[r for t in trials if t['status']=='measurement_failed' for u in t['units'] if u['status']=='failed' for r in u['files'].values()]
    done='measured_quality_rejected' if row['status']=='quality_rejected' else 'measured_and_verified'
    doc={**frozen,'status':'measurement_failed' if error else done,'reason':error,'timing_admitted':False,
         'anchors':{'units':len(cases),'reference':'same_run_functional_products'},'trials':trials,'failure_logs':failures,
         'resource_before':start,'resource_after':resource.observe(cpu)}
    return {**doc,'summary':recompute(root,plan,item,entry,run,row,doc,set(),cases=cases)}
