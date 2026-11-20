"""Same-run whole-file Zstd/XZ clocks and detached native worker controls."""
from collections import defaultdict
import os
from pathlib import Path
from random import Random
import shutil
from tempfile import TemporaryDirectory

from ..assets import load_json, local_file, require
from ..planner.m3_in_run_measurement_v10 import ROUTES
from ..planner.m3_lzbench_session import input_size
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_in_run_failure as failure, m3_lzbench_corpus_clock as clock, m3_lzbench_durable as durable

DIRECTORY = 'measurement-lzbench-anchors'
FAILED = 'measurement-lzbench-failures'


def _case(item,row,entry,cid):
    route = item['route']; codec,family = route.split('-'); e = row['evidence']
    n = input_size(item,entry); source = {'bytes':n,'sha256':entry['canonical']['values_sha256']}
    require(row['status'] == 'verified' and e['driver'] == ROUTES[item['selection'],route] and e['codec'] == codec and
            e['source'] == source and clock._encode_cap(n) <= clock.launcher.FILE_CEILING and
            (e['recovered'] == source if family == 'session' else not clock.outcome(e)),
            'lzbench timing needs the verified same-run whole-file operation')
    lanes = ('session',) if family == 'session' else clock.LANES[codec]
    variants = {lane:clock._variant(e,lane) for lane in lanes}
    for lane,v in variants.items():
        require(0 < v['frame']['bytes'] <= clock.launcher.FILE_CEILING, 'lzbench fixed frame exceeds isolation ceiling')
        if ref := v['retain']:
            name = 'native' if family == 'session' else lane
            require(ref['path'] == f"retained/{item['work_item_id']}/{name}.frame" and
                    {k:ref[k] for k in ('bytes','sha256')} == v['frame'], 'lzbench functional retained frame differs')
    return {**{k:item[k] for k in ('work_item_id','dataset_id','route','canonical_object_id','operation_config_id')},
            'case_id':cid,'source':source,'codec':codec,'family':family,'variants':variants}


def _schedule(case):
    cid = case['case_id']; rng = Random(f'{clock.SEED}/{cid}')
    rounds = [rng.sample(list(case['variants']),len(case['variants'])) for _ in range(clock.WARMUPS+clock.ROUNDS)]
    for slot in clock._schedule({**case,'order':rounds}):
        name = Path(slot['path']).name
        yield {**slot,'path':f'{DIRECTORY}/{cid}/{name}/{slot["direction"]}'}


def _check_frame(case,lane,path):
    v = case['variants'][lane]
    require(clock.artifact(path) == v['frame'] and ('wire' not in v or
            clock.wire_info(path,case['codec'],case['source']['bytes']) == v['wire']), 'lzbench fixed frame bytes or wire differ')


def _fixed(root,run,work,binding,case,entry):
    anchor = work/'anchor'; products = anchor/'frames'; products.mkdir(parents=True)
    raw = None
    for lane,v in case['variants'].items():
        dst = products/f'{lane}.frame'
        if v['retain'] is not None:
            shutil.copyfile(clock._file(run,v['retain']),dst)
        else:
            if raw is None:
                stage = anchor/'stage'; stage.mkdir()
                raw, = clock._stage_dataset(root,entry,stage,'v_bytes_interleaved')['paths']
                require(clock.artifact(raw) == case['source'], 'lzbench anchor original-domain source differs')
            scratch = anchor/'encode'; scratch.mkdir()
            output,proc,native,path,_ = clock._call(work,binding,case,scratch,raw,'encode',lane)
            clock._verify_clocks(case,{'direction':'encode','lane':lane},native,proc,path,set())
            output.rename(dst)
            _check_frame(case,lane,dst)
            shutil.rmtree(scratch)
        _check_frame(case,lane,dst)
        failure._sync(dst)
    failure._sync(products)
    base = run/DIRECTORY/case['case_id']; base.mkdir(parents=True)
    products.rename(base/'frames')
    for p in (base,base.parent,run):
        failure._sync(p)
    return {lane:clock._ref(run,base/'frames'/f'{lane}.frame') for lane in case['variants']}


def _trial(root,run,work,binding,case,entry,frames,slot):
    scratch = work/slot['path']; scratch.parent.mkdir(parents=True)
    obs,_ = durable._trial(root,work,binding,case,slot,entry,frames,set())
    target = run/slot['path']; target.parent.mkdir()
    # Publish only complete log pairs, separate from the timed output.
    with TemporaryDirectory(prefix='publish-',dir=work) as tmp:
        pub = Path(tmp)/'logs'; pub.mkdir()
        for ref in obs['logs']:
            path = pub/Path(ref['path']).name
            shutil.copyfile(clock._file(work,ref),path)
            failure._sync(path)
        failure._sync(pub)
        pub.rename(target)
    for p in (target.parent,target.parent.parent):
        failure._sync(p)
    return {**obs,'status':'measured_as_declared'}


def _metrics(case,rows):
    summary = durable._summarize(case,rows); groups = defaultdict(list)
    for t in rows:
        if t['phase'] == 'measured':
            groups[t['direction'],t['lane']].append(t)
    n = case['source']['bytes']; dist = clock._distribution
    for (op,lane),group in groups.items():
        records = [t['clock'] for t in group]
        lane_summary = summary['lanes'][op][lane]
        require(len(group) == clock.ROUNDS,'lzbench did not measure every matched round')
        call = [sum(c[k]['wall_ns'] for k in clock.BUCKETS) for c in records]
        lane_summary.update(native_inclusive_call_wall_ns=dist(call),
                            native_call_buckets={k:dist([c[k]['wall_ns'] for c in records]) for k in clock.BUCKETS},
                            native_call_mib_per_s=dist([n*1e9/((1<<20)*ns) for ns in call]),
                            first_driver_output_wall_ns=dist([c['first_driver_output_wall_ns'] for c in records]),
                            first_driver_output_bytes=dist([c['first_driver_output_bytes'] for c in records]),
                            driver_wall_ns=dist([c['driver_wall_ns'] for c in records]),
                            process_wall_ns=dist([t['process']['process_wall_ns'] for t in group]),
                            observed_native_jobs={k:dist([c['functional']['jobs'][k] for c in records])
                                                  for k in records[0]['functional']['jobs']},
                            effective_parameters=case['variants'][lane]['expected'][op]['effective_parameters'],
                            payload_bytes_excluding_native_framing=None,
                            payload_bytes_unavailable_reason='not_separately_exposed_by_native_driver')
    return summary


def _cpus(m,case):
    env = m['lzbench_clock']['worker_environment'] if case['family'] == 'workers' else [m['environment']]
    return [v['cpu'] for v in env]


def _snapshot(cpus):
    return {'affinity':sorted(os.sched_getaffinity(0)),'cpus':{str(c):resource.observe(c) for c in cpus}}


def measure(root,plan,item,entry,run,row,work):
    m = plan['measurement']; frozen = m['population'][item['work_item_id']]; cid = frozen['case_id']
    binding = m['lzbench_clock']; case = _case(item,row,entry,cid); cpus = _cpus(m,case)
    base = run/DIRECTORY/cid; failed = f'{FAILED}/{cid}'; before = _snapshot(cpus)
    fixed = err = None; logs,trials = [],[]
    try:
        stage_recovery(root,work,binding['runtime'],directory='runtime')
        fixed = _fixed(root,run,work,binding,case,entry)
        frames = {lane:local_file(run,r['path']) for lane,r in fixed.items()}
    except (ValueError,OSError) as exc:
        scratch = work/'anchor'; logs = failure.retain(run,failed,'anchor',scratch,('encode',))
        err = 'lzbench same-run anchor failed: ' + failure.reason(exc,scratch,run/failed/'anchor')
        if base.exists():
            shutil.rmtree(base)
        fixed = None
    for slot in _schedule(case):
        if err:
            trials.append({**slot,'status':'not_run_after_measurement_failure','reason':err})
            continue
        scratch = (work/slot['path']).parent
        try:
            trials.append(_trial(root,run,work,binding,case,entry,frames,slot))
        except (ValueError,OSError) as exc:
            dest = (run/slot['path']).parent
            if dest.exists():
                shutil.rmtree(dest)
            logs = failure.retain(run,failed,'trial',scratch,(slot['direction'],))
            err = failure.reason(exc,scratch,run/failed/'trial')
            trials.append({**slot,'status':'measurement_failed','reason':err})
        finally:
            if scratch.exists():
                shutil.rmtree(scratch)
    doc = {**frozen,'anchors':fixed,'failure_logs':logs,'status':'measurement_failed' if err else 'measured_and_verified',
           'reason':err,'trials':trials,'timing_admitted':False,'cpu_budget':cpus,'resource_before':before,'resource_after':_snapshot(cpus)}
    return {**doc,'summary':recompute(root,plan,item,entry,run,row,doc,set())}


def recompute(root,plan,item,entry,run,row,doc,seen):
    m = plan['measurement']; frozen = m['population'][item['work_item_id']]; cid = frozen['case_id']
    case = _case(item,row,entry,cid); base = run/DIRECTORY/cid; cpus = _cpus(m,case)
    fixed = doc['anchors']; passed = doc['status'] == 'measured_and_verified'
    require(doc['case_id'] == cid and doc['adapter'] == frozen['adapter'] and doc['timing_admitted'] is False and
            doc['status'] in ('measurement_failed','measured_and_verified') and doc['cpu_budget'] == cpus and
            all(doc[k]['affinity'] == cpus and set(doc[k]['cpus']) == set(map(str,cpus)) for k in ('resource_before','resource_after')) and
            (doc['reason'] is None if passed else bool(doc['reason'])) and (fixed is not None or not passed),
            'lzbench primary timing terminal or resource identity differs')
    failure.check(run,f'{FAILED}/{cid}',doc,('encode',))
    paths, measured = set(), []
    if fixed is not None:
        require(set(fixed) == set(case['variants']), 'lzbench fixed lane inventory differs')
        for lane,ref in fixed.items():
            require(ref['path'] == f'{DIRECTORY}/{cid}/frames/{lane}.frame','lzbench fixed frame path differs')
            _check_frame(case,lane,clock._file(run,ref))
            paths.add(ref['path'])
    failed = fixed is None; slots = list(_schedule(case))
    require(len(doc['trials']) == len(slots),'lzbench frozen trial denominator differs')
    for slot,t in zip(slots,doc['trials'],strict=True):
        require(all(t[k] == v for k,v in slot.items()),'lzbench frozen lane or direction differs')
        if not failed and t['status'] == 'measured_as_declared':
            expected = [f"{slot['path']}/{name}" for name in failure.NAMES]
            require([r['path'] for r in t['logs']] == expected and t['logs'][1]['bytes'] == 0,'lzbench trial log coordinates differ')
            stdout,_ = (clock._file(run,ref) for ref in t['logs'])
            require(load_json(stdout) == t['clock'],'lzbench native log differs from ledger')
            durable._validate(case,slot,{k:v for k,v in t.items() if k != 'status'},entry,seen)
            paths.update(expected)
            if slot['phase'] == 'measured':
                measured.append(t)
        else:
            require(not passed and t.get('reason') == doc['reason'] and
                    t['status'] == ('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'lzbench trial terminal differs')
            failed = True
    require(passed == (not failed),'lzbench decision disagrees with trial terminals')
    inventory = list(base.rglob('*'))
    require(not base.is_symlink() and base.exists() == bool(fixed) and all(not p.is_symlink() for p in inventory) and
            paths == {p.relative_to(run).as_posix() for p in inventory if p.is_file()},'lzbench retained evidence inventory differs')
    return _metrics(case,measured) if passed else None


def observe(root,plan,item,entry,run,row):
    m = plan['measurement']; env = m['lzbench_clock']['worker_environment'] if item['route'].endswith('-workers') else [m['environment']]
    cpus = [e['cpu'] for e in env]
    require([resource.environment(c) for c in cpus] == env,'lzbench measurement environment changed since freeze')
    with clock._affinity(cpus), TemporaryDirectory(prefix='m3-lzbench-primary-',dir=run) as tmp:
        return measure(root,plan,item,entry,run,row,Path(tmp))
