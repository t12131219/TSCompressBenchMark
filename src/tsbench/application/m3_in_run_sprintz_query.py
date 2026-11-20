"""Isolated whole-file Sprintz query repeats from the same functional decision."""
from pathlib import Path
from random import Random
import shutil
from tempfile import TemporaryDirectory
from time import process_time_ns

from ..assets import load_json, local_file, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_in_run_failure as failure, m3_sprintz_durable as durable
from .m3_in_run_measurement import guard
from .m3_metric_details import distribution
from .m3_sprintz_timing import _column_names, _native, _verify_columns

DIRECTORY = 'measurement-sprintz-query-anchors'
FAILED = 'measurement-sprintz-query-failures'


def _case(item,row,entry,cid):
    e = row['evidence']; extent = item['input']; rows,cols = entry['rows'],entry['value_count']
    units = [{k:v for k,v in u.items() if k != 'native_wall_ns'} for u in e['units']]
    require(row['status'] == 'verified' and (item['selection'],item['route']) == (19,'query') and
            (e['rows'],e['columns']) == (rows,cols) and extent['full_extent_of_file_rows_and_value_columns'] and
            item['canonical_object_id'] == entry['canonical']['object_id'] and
            [(u['column'],u['row_start'],u['row_end']) for u in units] ==
            [(c,a,min(rows,a+durable.ROWS)) for c in range(cols) for a in range(0,rows,durable.ROWS)] and
            len(units) == extent['size_estimate']['input_units'] and
            all(u['raw_bytes'] == (u['row_end']-u['row_start'])*8 and u['frame_bytes'] == durable.HEADER.size+u['payload_bytes'] for u in units) and
            e['input_bytes'] == rows*cols*8 and e['artifact_bytes'] == sum(u['frame_bytes'] for u in units),
            'Sprintz same-run query geometry or byte charges differ')
    return {**{k:item[k] for k in ('work_item_id','dataset_id','canonical_object_id','operation_config_id')},
            'case_id':cid,'source_file':entry['file'],'configuration':extent,'rows':rows,'columns':cols,'units':units,
            'groups':durable.groups(rows,cols,units),'workspace_bytes':e['codec_workspace_bytes']}


def _schedule(cid):
    rng = Random(f'20261120/{cid}')
    for r in range(durable.ROUNDS+1):
        for op in rng.sample(durable.OPS,len(durable.OPS)):
            yield {'round':r,'phase':'measured' if r else 'warmup','operation':op,'direction':op,
                   'path':f'{DIRECTORY}/{cid}/{r:02d}-{op}'}


def _logs(run,cid,kind,op,path):
    target = run/FAILED/cid/kind/op
    refs = []
    for name in failure.NAMES:
        original = f"{op}.{name.split('.')[1]}"
        if (path/original).exists():
            target.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(local_file(path,original),target/name)
            failure._sync(target/name)
            refs.append(durable.relative(run,target/name))
    if refs:
        for p in (target,*target.parents):
            failure._sync(p)
            if p == run:
                break
    return refs


def _fixed(root,run,work,binding,case,entry):
    anchor = work/'anchor'; anchor.mkdir(); stage = anchor/'stage'
    durable._stage(root,entry,stage)
    columns = _verify_columns(case,stage,oracle=True)
    files,p,doc = durable.invoke(work/'runtime',binding,case,'encode',{name:stage/name for name in _column_names(case)},anchor/'encode')
    require(p['input_mounts'] == columns and _native(case,'encode',doc),'Sprintz same-run anchor process differs')
    archives = durable.verify_archives(case,files)
    durable.sync_outputs(files,archives)
    base = run/DIRECTORY/case['case_id']; base.mkdir(parents=True)
    files.rename(base/'archives')
    for path in (base,base.parent,run):
        failure._sync(path)
    return {'columns':columns,'archives':archives}


def _trial(root,run,work,binding,case,entry,ready,slot,scratch):
    base = run/DIRECTORY/case['case_id']; op = slot['operation']; cpu = process_time_ns()
    obs = durable.trial(root,work/'runtime',binding,case,entry,base/'archives',ready,slot,scratch)
    elapsed = process_time_ns()-cpu
    durable.validate(case,slot,obs,ready,set())
    target = run/slot['path']; pub = scratch/'published'; pub.mkdir()
    for name in failure.NAMES:
        src = local_file(scratch/'operation',f"{op}.{name.split('.')[1]}")
        dst = pub/name; shutil.copyfile(src,dst); failure._sync(dst)
    failure._sync(pub)
    pub.rename(target); failure._sync(base)
    return {**obs,'controller_cpu_ns':elapsed,'logs':[durable.relative(run,target/n) for n in failure.NAMES],
            'status':'measured_as_declared'}


def measure(root,plan,item,entry,run,row,work):
    m = plan['measurement']; frozen = m['population'][item['work_item_id']]; cid = frozen['case_id']; cpu = m['environment']['cpu']
    binding = m['sprintz_query_grouped']; case = _case(item,row,entry,cid)
    ready = err = None; logs,trials = [],[]; before = resource.observe(cpu)
    base = run/DIRECTORY/cid
    try:
        stage_recovery(root,work,binding['runtime'],directory='runtime')
        ready = _fixed(root,run,work,binding,case,entry)
    except (ValueError,OSError) as exc:
        logs = _logs(run,cid,'anchor','encode',work/'anchor'/'encode')
        err = 'Sprintz same-run anchor failed: '+failure.reason(exc,work/'anchor',run/FAILED/cid/'anchor')
        if base.exists():
            shutil.rmtree(base)
        ready = None
    for slot in _schedule(cid):
        if err:
            trials.append({**slot,'status':'not_run_after_measurement_failure','reason':err})
            continue
        with TemporaryDirectory(prefix='trial-',dir=work) as tmp:
            scratch = Path(tmp)
            try:
                trials.append(_trial(root,run,work,binding,case,entry,ready,slot,scratch))
            except (ValueError,OSError) as exc:
                target = run/slot['path']
                if target.exists():
                    shutil.rmtree(target)
                op = slot['operation']
                logs = _logs(run,cid,'trial',op,scratch/'operation')
                err = failure.reason(exc,scratch/'operation',run/FAILED/cid/'trial'/op)
                trials.append({**slot,'status':'measurement_failed','reason':err})
    doc = {**frozen,'anchors':ready,'failure_logs':logs,'status':'measurement_failed' if err else 'measured_and_verified',
           'reason':err,'trials':trials,'timing_admitted':False,'resource_before':before,'resource_after':resource.observe(cpu)}
    return {**doc,'summary':recompute(root,plan,item,entry,run,row,doc,set(),verified_columns=ready['columns'] if ready else None)}


def recompute(root,plan,item,entry,run,row,doc,seen,*,verified_columns=None):
    frozen = plan['measurement']['population'][item['work_item_id']]; cid = frozen['case_id']
    case = _case(item,row,entry,cid); base = run/DIRECTORY/cid; ready = doc['anchors']; passed = doc['status'] == 'measured_and_verified'
    require(doc['case_id'] == cid and doc['adapter'] == frozen['adapter'] and doc['timing_admitted'] is False and
            doc['status'] in ('measurement_failed','measured_and_verified') and
            (doc['reason'] is None if passed else bool(doc['reason'])) and (ready is not None or not passed),
            'Sprintz query timing terminal differs')
    failure.check(run,f'{FAILED}/{cid}',doc,('encode',))
    files, measured = set(),[]
    if ready is not None:
        if verified_columns is None:
            with TemporaryDirectory(prefix='m3-audit-sprintz-') as tmp:
                source = Path(tmp)/'columns'; durable._stage(root,entry,source)
                verified_columns = _verify_columns(case,source,oracle=True)
        require(ready == {'columns':verified_columns,'archives':durable.verify_archives(case,base/'archives')},
                'Sprintz ready archives or independently rebuilt source differ')
        files.update(f'{DIRECTORY}/{cid}/archives/{name}' for name in ready['archives'])
    failed = ready is None; slots = list(_schedule(cid))
    require(len(doc['trials']) == len(slots),'Sprintz whole-file operation denominator differs')
    for slot,t in zip(slots,doc['trials'],strict=True):
        require(all(t[k] == v for k,v in slot.items()),'Sprintz query frozen schedule differs')
        if not failed and t['status'] == 'measured_as_declared':
            wanted = [f"{slot['path']}/{name}" for name in failure.NAMES]
            require([r['path'] for r in t['logs']] == wanted and t['logs'][1]['bytes'] == 0 and
                    type(t['controller_cpu_ns']) is int and t['controller_cpu_ns'] > 0,'Sprintz query retained log or controller sample differs')
            stdout,_ = (durable.check(run,r) for r in t['logs'])
            require(load_json(stdout) == t['native'],'Sprintz native clock evidence differs from log')
            durable.validate(case,slot,t,ready,seen)
            files.update(wanted)
            if slot['phase'] == 'measured':
                measured.append(t)
        else:
            require(not passed and t.get('reason') == doc['reason'] and
                    t['status'] == ('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'Sprintz query trial terminal differs')
            failed = True
    require(passed == (not failed),'Sprintz query decision disagrees with operation terminals')
    entries = list(base.rglob('*'))
    require(not base.is_symlink() and base.exists() == bool(ready) and all(not p.is_symlink() for p in entries) and
            files == {p.relative_to(run).as_posix() for p in entries if p.is_file()},'Sprintz query retained inventory differs')
    if not passed:
        return None
    summary = durable.report_case(case,measured)
    for op in durable.OPS:
        summary['directions'][op]['distributions']['controller_cpu_ns'] = {
            **distribution([v['controller_cpu_ns'] for v in measured if v['operation'] == op]),'sample_basis':durable.POLICY['sample']}
    summary['native_threads'] = 1
    return summary


def observe(root,plan,item,entry,run,row):
    with guard(plan), TemporaryDirectory(prefix='m3-sprintz-primary-',dir=run) as tmp:
        return measure(root,plan,item,entry,run,row,Path(tmp))
