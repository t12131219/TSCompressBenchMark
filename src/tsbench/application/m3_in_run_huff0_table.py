"""Same-run ETB1 1X/4X table training and detached whole-holdout trials."""
from pathlib import Path
from random import Random
import shutil
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns

from ..assets import load_json, local_file, require
from ..corpus_ingress import read_batches
from ..planner.m3_huff0_table import DRIVER, KEY, STREAMS, inputs
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_huff0_etb1_timing as timing, m3_in_run_failure as failure
from .m3_in_run_measurement import guard
from .m3_metric_details import distribution

DIRECTORY = 'measurement-huff0-table-anchors'
FAILED = 'measurement-huff0-table-failures'


def _cases(item,row,entry,cid):
    p = row['evidence']; train,held = inputs(item,entry)
    require(row['status']=='verified' and (item['selection'],item['route']) == KEY and p['driver']==DRIVER and not p['errors'] and
            p['training']['bytes']==train[1]-train[0] and p['holdout']=={'bytes':held[1]-held[0],
                'sha256':entry['partitions'][2]['canonical']['values_sha256']} and set(p['profiles'])==set(map(str,STREAMS)),
            'ETB1 needs the verified same-run training and held-out work')
    cases = {}
    for streams in STREAMS:
        k = str(streams); lane = p['profiles'][k]; blocks = lane['blocks']
        model,wire,sidecar = (lane[a] for a in ('model','frame','binding'))
        cost = {'model':model['bytes'],'model_block_binding':sidecar['bytes'],'block_headers':len(blocks)*timing.TABLE.size,
                'block_payload':sum(b['body_bytes'] for b in blocks)}
        require(lane['status']=='verified' and lane['recovered']==p['holdout'] and lane['encode']==lane['decode'] and
                all(lane[op]['context_count']==1 and lane[op]['streams']==streams for op in timing.OPS) and
                timing.binary_ref(timing.binding(streams,model,wire))==sidecar and sum(cost.values())==lane['complete_bytes'] and
                cost['block_headers']+cost['block_payload']==wire['bytes'] and len(blocks)+1==item['input']['size_estimate']['input_units'] and
                [b['original_bytes'] for b in blocks]==[min(timing.BLOCK,p['holdout']['bytes']-a) for a in range(0,p['holdout']['bytes'],timing.BLOCK)],
                'ETB1 native profile, held-out blocks or complete billing differs')
        groups = timing.groups(blocks)
        require(all(0 < g[role+'_bytes'] <= timing.LIMITS['file_bytes'] for g in groups for role in ('raw','wire')),
                'ETB1 group exceeds the bounded transport limit')
        cases[k] = {**{a:item[a] for a in ('dataset_id','work_item_id','operation_config_id','canonical_object_id')},
                    'case_id':cid,'source_file':entry['file'],'configuration':item['input'],'streams':streams,
                    'training':p['training'],'holdout':p['holdout'],'model':model,'wire':wire,'binding':sidecar,'cost':cost,'blocks':blocks,
                    'groups':groups,'native':{op:lane[op] for op in timing.OPS},'historical_set_present':False}
    return cases


def _schedule(cid):
    rng = Random(f'20261120/etb1/{cid}')
    for r in range(timing.ROUNDS+1):
        for op in rng.sample(timing.OPS,len(timing.OPS)):
            for streams in rng.sample(STREAMS,len(STREAMS)):
                yield {'round':r,'phase':'measured' if r else 'warmup','operation':op,'direction':op,'streams':streams,
                       'path':f'{DIRECTORY}/{cid}/{streams}x/{r:02d}-{op}'}


def _stage_role(root,item,entry,case,work,role):
    train = role=='train'; a,b=inputs(item,entry)[0 if train else 1]; width=entry['value_count']*8
    dest = work/('train' if train else 'holdout')
    with dest.open('xb') as out:
        for batch in read_batches(root,entry):
            first=batch.start*width; end=first+len(batch.values)
            if first<b and a<end:
                out.write(memoryview(batch.values)[max(a,first)-first:min(b,end)-first])
    require(timing.ref(dest)==case['training' if train else 'holdout'],'ETB1 staged slice differs from locked original domain')
    if train:
        return {'train':dest}, None
    chunks=work/'groups'; chunks.mkdir()
    with dest.open('rb') as src:
        for g in case['groups']:
            raw=src.read(g['raw_bytes']); require(len(raw)==g['raw_bytes'],'ETB1 short staged group')
            (chunks/g['name']).write_bytes(raw)
        require(not src.read(1),'ETB1 staged holdout has trailing bytes')
    refs=timing.verify_group_files(case,chunks,'raw')
    return {n:chunks/n for n in refs},refs


def _fixed(root,run,work,plan,item,entry,cases,cid):
    anchor=work/'anchor'; scratch=anchor/'inputs'; scratch.mkdir(parents=True)
    first=next(iter(cases.values()))
    train,_=_stage_role(root,item,entry,first,scratch,'train')
    enc,raw=_stage_role(root,item,entry,first,scratch,'encode')
    retain=anchor/'fixed'; retain.mkdir(); result={}
    for k,case in cases.items():
        base=retain/f'{k}x'; base.mkdir()
        trained,proc,native=timing.invoke(work/'runtime',plan['measurement']['huff0_table_grouped'],case,'train',train,anchor/'train')
        require(proc['input_mounts']=={'train':case['training']} and native['context_count']==1 and
                {p.name for p in trained.iterdir()}=={'model'} and timing.ref(local_file(trained,'model'))==case['model'],
                'ETB1 same-run anchor trained model differs')
        (trained/'model').rename(base/'model'); shutil.rmtree(anchor/'train')
        wire,proc,native=timing.invoke(work/'runtime',plan['measurement']['huff0_table_grouped'],case,'encode',
                                       {'model':base/'model',**enc},anchor/'encode')
        require(proc['input_mounts']=={'model':case['model'],**raw} and native['context_count']==1,'ETB1 held-out preparation input differs')
        refs=timing.verify_group_files(case,wire,'wire'); wire.rename(base/'wire')
        sidecar=timing.binding(case['streams'],case['model'],case['wire'])
        (base/'binding.json').write_bytes(sidecar)
        require(timing.binary_ref(sidecar)==case['binding'],'ETB1 anchor SHA model/block binding differs')
        for p in (base/'binding.json', base/'model',*(base/'wire'/n for n in refs),base/'wire',base):
            failure._sync(p)
        shutil.rmtree(anchor/'encode')
        result[k]={'raw':raw,'wire':refs}
    failure._sync(retain)
    base=run/DIRECTORY/cid; base.parent.mkdir(exist_ok=True); retain.rename(base)
    for p in (base,base.parent,run):
        failure._sync(p)
    return result


def _retain(run,cid,kind,ops,where):
    refs=[]
    for op in ops:
        path=where(op); dst=run/FAILED/cid/kind/op
        for name in failure.NAMES:
            original=f"{op}.{name.split('.')[1]}"
            if (path/original).exists():
                dst.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(local_file(path,original),dst/name)
                failure._sync(dst/name)
                refs.append(timing.relative(run,dst/name))
        if dst.is_dir():
            for p in (dst,*dst.parents):
                failure._sync(p)
                if p==run:
                    break
    return refs


def _trial(root,run,work,plan,item,entry,case,refs,slot,scratch):
    op=slot['operation']; k=str(slot['streams']); base=run/DIRECTORY/case['case_id']/f'{k}x'
    start,cpu=monotonic_ns(),process_time_ns(); ingress=None
    if op=='decode':
        require(local_file(base,'binding.json').read_bytes()==timing.binding(case['streams'],case['model'],case['wire']),
                'ETB1 detached model and ordered block binding differs')
        paths={n:local_file(base/'wire',n) for n in refs['wire']}
    else:
        paths,_=_stage_role(root,item,entry,case,scratch,op)
        ingress=monotonic_ns()-start
    if op!='train':
        paths['model']=local_file(base,'model')
    _,obs=timing.trial(work/'runtime',plan['measurement']['huff0_table_grouped'],case,slot,paths,scratch/'native')
    wall,elapsed=monotonic_ns()-start,process_time_ns()-cpu
    timing.validate(plan['measurement'],case,slot,obs,refs,set())
    pub=scratch/'publish'; pub.mkdir(); dst=run/slot['path']
    for name in failure.NAMES:
        path=pub/name; shutil.copyfile(local_file(scratch/'native',f"{op}.{name.split('.')[1]}"),path); failure._sync(path)
    failure._sync(pub); pub.rename(dst); failure._sync(base)
    return {**obs,'status':'measured_as_declared','controller_cpu_ns':elapsed,'whole_verified_durable_wall_ns':wall,
            'ingress_stage_wall_ns':ingress,'logs':[timing.relative(run,dst/n) for n in failure.NAMES]}


def measure(root,plan,item,entry,run,row,work):
    m=plan['measurement']; frozen=m['population'][item['work_item_id']]; cid=frozen['case_id']; cpu=m['environment']['cpu']
    cases=_cases(item,row,entry,cid); base=run/DIRECTORY/cid; before=resource.observe(cpu)
    ready=err=None; logs,trials=[],[]
    try:
        stage_recovery(root,work,m['huff0_table_grouped']['runtime'],directory='runtime')
        ready=_fixed(root,run,work,plan,item,entry,cases,cid)
    except (ValueError,OSError) as exc:
        anchor=work/'anchor'; logs=_retain(run,cid,'anchor',('train','encode'),lambda op:anchor/op)
        err='ETB1 anchor failed: '+failure.reason(exc,anchor,run/FAILED/cid/'anchor')
        if base.exists():
            shutil.rmtree(base)
        ready=None
    for slot in _schedule(cid):
        if err:
            trials.append({**slot,'status':'not_run_after_measurement_failure','reason':err})
            continue
        with TemporaryDirectory(prefix='trial-',dir=work) as tmp:
            scratch=Path(tmp); k=str(slot['streams']); op=slot['operation']
            try:
                trials.append(_trial(root,run,work,plan,item,entry,cases[k],ready[k],slot,scratch))
            except (ValueError,OSError) as exc:
                dst=run/slot['path']
                if dst.exists():
                    shutil.rmtree(dst)
                logs=_retain(run,cid,'trial',(op,),lambda _:scratch/'native')
                err=failure.reason(exc,scratch/'native',run/FAILED/cid/'trial'/op)
                trials.append({**slot,'status':'measurement_failed','reason':err})
    doc={**frozen,'status':'measurement_failed' if err else 'measured_and_verified','anchors':ready,'trials':trials,
         'timing_admitted':False,'reason':err,'failure_logs':logs,'resource_before':before,'resource_after':resource.observe(cpu)}
    return {**doc,'summary':recompute(root,plan,item,entry,run,row,doc,set(),verified_ready=ready)}


def recompute(root,plan,item,entry,run,row,doc,seen,*,verified_ready=None):
    m=plan['measurement']; frozen=m['population'][item['work_item_id']]; cid=frozen['case_id']
    cases=_cases(item,row,entry,cid); base=run/DIRECTORY/cid; ready=doc['anchors']; passed=doc['status']=='measured_and_verified'
    require(doc['case_id']==cid and doc['adapter']==frozen['adapter'] and doc['timing_admitted'] is False and
            doc['status'] in ('measurement_failed','measured_and_verified') and (doc['reason'] is None if passed else bool(doc['reason'])) and
            (ready is not None or not passed),'ETB1 primary timing terminal differs')
    failure.check(run,f'{FAILED}/{cid}',doc,('train','encode'))
    paths=set(); measured={k:[] for k in cases}
    if ready is not None:
        require(set(ready)==set(cases),'ETB1 fixed lane inventory differs')
        if verified_ready is None:
            with TemporaryDirectory(prefix='m3-audit-etb1-') as tmp:
                _,raw=_stage_role(root,item,entry,next(iter(cases.values())),Path(tmp),'encode')
        for k,case in cases.items():
            place=base/f'{k}x'; files=[local_file(place,n) for n in ('model','binding.json')]
            require(timing.ref(files[0])==case['model'] and files[1].read_bytes()==timing.binding(case['streams'],case['model'],case['wire']),
                    'ETB1 fixed model or sidecar differs')
            require(ready[k]=={'raw':verified_ready[k]['raw'] if verified_ready is not None else raw,
                               'wire':timing.verify_group_files(case,place/'wire','wire')},'ETB1 fixed source or ordered blocks differ')
            paths.update(p.relative_to(run).as_posix() for p in (*files,*(place/'wire'/n for n in ready[k]['wire'])))
    slots=list(_schedule(cid)); failed=ready is None
    require(len(doc['trials'])==len(slots),'ETB1 matched lane operation denominator differs')
    for slot,t in zip(slots,doc['trials'],strict=True):
        require(all(t[k]==v for k,v in slot.items()),'ETB1 frozen schedule differs')
        if not failed and t['status']=='measured_as_declared':
            wanted=[f"{slot['path']}/{n}" for n in failure.NAMES]; op=slot['operation']; k=str(slot['streams'])
            ingress=t['ingress_stage_wall_ns']; wall=t['whole_verified_durable_wall_ns']
            require([r['path'] for r in t['logs']]==wanted and t['logs'][1]['bytes']==0 and
                    type(t['controller_cpu_ns']) is int and t['controller_cpu_ns']>0 and
                    (ingress is None if op=='decode' else type(ingress) is int and ingress>0) and
                    type(wall) is int and wall >= (ingress or 0)+t['staged_verified_durable_wall_ns'],
                    'ETB1 full-path clock or log path differs')
            stdout,_=(timing.check(run,r) for r in t['logs'])
            require(load_json(stdout)==t['native'],'ETB1 native observation differs from retained log')
            timing.validate(m,cases[k],slot,t,ready[k],seen); paths.update(wanted)
            if slot['phase']=='measured':
                measured[k].append(t)
        else:
            require(not passed and t.get('reason')==doc['reason'] and
                    t['status']==('not_run_after_measurement_failure' if failed else 'measurement_failed'),'ETB1 operation terminal differs')
            failed=True
    require(passed==(not failed),'ETB1 decision disagrees with operation terminals')
    inventory=list(base.rglob('*'))
    require(not base.is_symlink() and base.exists()==bool(ready) and all(not p.is_symlink() for p in inventory) and
            paths=={p.relative_to(run).as_posix() for p in inventory if p.is_file()},'ETB1 retained inventory differs')
    if not passed:
        return None
    result={}
    for k,case in cases.items():
        summary=timing.summarize(case,measured[k]); summary.pop('historical_set_present'); summary['reference_scope']='same_run'
        for op in timing.OPS:
            d=summary['directions'][op]; chosen=[t for t in measured[k] if t['operation']==op]
            for key in ('controller_cpu_ns','ingress_stage_wall_ns','whole_verified_durable_wall_ns'):
                xs=[t[key] for t in chosen]
                if xs[0] is not None:
                    d['distributions'][key]={**distribution(xs),'sample_basis':timing.POLICY['sample']}
            if op!='train':
                d['holdout_mib_per_second']['whole_verified_durable_wall_ns']=case['holdout']['bytes']*len(chosen)*1e9/(
                    (1<<20)*sum(t['whole_verified_durable_wall_ns'] for t in chosen))
        result[k]=summary
    return {'native_threads':1,'profiles':result}


def observe(root,plan,item,entry,run,row):
    with guard(plan), TemporaryDirectory(prefix='m3-etb1-primary-',dir=run) as tmp:
        return measure(root,plan,item,entry,run,row,Path(tmp))
