"""Same-run Zstd dictionary training, holdout encoding, and detached recovery."""
from pathlib import Path
from random import Random
import shutil
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns

from ..assets import local_file, require
from ..planner.m3_zstd_dictionary import DRIVER, KEY, LIMIT, extents
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource, zstd_dictionary_grouped as launch
from . import m3_in_run_failure as failure, m3_zstd_dictionary_timing as timing
from .m3_in_run_measurement import guard
from .m3_zstd_dictionary_grouped import inspect_archive, stage_inputs

DIRECTORY = 'measurement-zstd-dictionary-anchors'
FAILED = 'measurement-zstd-dictionary-failures'


def _case(item, row, entry, cid):
    require(row['status'] == 'verified' and (item['selection'], item['route']) == KEY,
            'dictionary timing needs a verified same-run training and holdout decision')
    e = row['evidence']
    spans, each, count = extents(item, entry)
    d = e['dictionary']
    cap = item['input']['training']['dictionary_capacity_bytes']
    held = {'bytes': spans[1][1]-spans[1][0], 'sha256': entry['partitions'][2]['canonical']['values_sha256']}
    require(e['driver'] == DRIVER and e['test_attempted'] and not e['fallback_used'] and e['failed_units'] == 0 and
            e['holdout'] == held and 0 < held['bytes'] <= launch.FILE_CEILING and
            e['train_bytes'] == each*count == spans[0][1]-spans[0][0] and
            e['holdout_object_id'] == item['input']['training']['evaluation']['partition_object_id'] and
            d['path'] == f"retained/{item['work_item_id']}/trained.zdict" and 8 <= d['bytes'] <= cap and d['id'] > 1,
            'same-run dictionary input, training, or artifact identity differs')
    return {**{k: item[k] for k in ('dataset_id','route','work_item_id','operation_config_id')},
            'case_id':cid, 'item':item, 'source':entry['file'], 'training':[cap,each,count],
            'anchor':{k:e[k] for k in ('dictionary','frames','holdout','train_prefix_sha256','verified_frame_bytes',
                                      'verified_frame_bytes_plus_shared_dictionary_once')}}


def _schedule(cid):
    rng = Random(f'{timing.SEED}/{cid}')
    for i in range(timing.WARMUPS+timing.ROUNDS):
        for op in rng.sample(timing.OPERATIONS, len(timing.OPERATIONS)):
            yield {'case_id':cid, 'op':op, 'direction':op, 'repeat':i,
                   'phase':'warmup' if i < timing.WARMUPS else 'measured',
                   'path':f'{DIRECTORY}/{cid}/{i:02d}-{op}'}


def _fixed(root, run, work, binding, case, entry):
    e = case['anchor']; d = e['dictionary']; logical = e['holdout']['bytes']
    scratch = work/'anchor'; products = scratch/'fixed'; products.mkdir(parents=True)
    dictionary = products/'shared.zdict'; archive = products/'heldout.zdg'
    shutil.copyfile(timing._file(run,d), dictionary)
    timing._dict_facts(d, dictionary)
    held = stage_inputs(root,case['item'],entry,scratch,e,roles=('holdout',))['holdout']
    wire, proc, _, _ = timing._op(work,binding,scratch/'encode','encode',held,dictionary=dictionary,logical=logical)
    require(proc['input_mounts'] == {'holdout':e['holdout'],'dictionary':timing._facts(d)}, 'dictionary anchor encode input differs')
    proof = inspect_archive(wire,e)
    wire.rename(archive)
    restored, proc, _, _ = timing._op(work,binding,scratch/'decode','decode',archive,dictionary=dictionary,logical=logical)
    require(proc['input_mounts'] == {'archive':timing._facts(proof),'dictionary':timing._facts(d)} and
            timing._amounts(restored) == e['holdout'], 'dictionary anchor detached restoration differs')
    for p in (dictionary,archive,products):
        timing._sync(p)
    base = run/DIRECTORY/case['case_id']; base.mkdir(parents=True)
    products.rename(base/'fixed')
    for p in (base,base.parent,run):
        timing._sync(p)
    return {'dictionary':timing._ref(run,base/'fixed'/dictionary.name),
            'archive':{'path':f'{DIRECTORY}/{case["case_id"]}/fixed/{archive.name}', **proof}}


def _retain(run, cid, kind, slots):
    refs = []
    for op, srcdir in slots:
        for name in failure.NAMES:
            src = srcdir/name
            if src.exists():
                dest = run/FAILED/cid/kind/op/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(local_file(srcdir, name), dest)
                timing._sync(dest)
                refs.append(timing._ref(run,dest))
                for p in (dest.parent,dest.parent.parent,run/FAILED/cid,run/FAILED,run):
                    timing._sync(p)
    return refs


def _trial(root, run, work, binding, case, entry, fixed, slot):
    # Keep verified-durable time separate from control-plane validation of
    # logs and publication of those logs in the main run.
    scratch = work/slot['path']; op = slot['op']; e = case['anchor']
    a, b, ingress = monotonic_ns(), process_time_ns(), None
    original = None if op == 'decode' else case['source']
    d = local_file(work,fixed['dictionary']['path'])
    if op == 'decode':
        source = local_file(work,fixed['archive']['path'])
        output, proc, native, logs = timing._op(work,binding,scratch,op,source,dictionary=d,logical=e['holdout']['bytes'])
    else:
        with TemporaryDirectory(dir=scratch.parent,prefix=f'{op}-stage-') as tmp:
            role = 'train' if op == 'train' else 'holdout'
            source = stage_inputs(root,case['item'],entry,Path(tmp),e,roles=(role,))[role]
            ingress = monotonic_ns()-a
            args = {'training':tuple(case['training'])} if op == 'train' else {'dictionary':d,'logical':e['holdout']['bytes']}
            output, proc, native, logs = timing._op(work,binding,scratch,op,source,**args)
    if op == 'train':
        product = timing._dict_facts(e['dictionary'],output)
    elif op == 'encode':
        product = timing._facts(inspect_archive(output,e))
        require(product == timing._facts(fixed['archive']), 'trial dictionary archive differs from fixed archive')
    else:
        product = timing._amounts(output)
        require(product == e['holdout'], 'trial dictionary detached restoration differs')
    for p in (output,output.parent,scratch,scratch.parent):
        timing._sync(p)
    obs = {**slot,'source_original':original,'ingress_wall_ns':ingress,'process':proc,'native':native,'product':product,
           'durable_wall_ns':monotonic_ns()-a,'controller_cpu_ns':process_time_ns()-b,
           'logs':[timing._ref(work,p) for p in logs]}
    timing._check_trial(work,case,fixed,slot,obs,set())
    dest = run/slot['path']; dest.mkdir()
    for ref in obs['logs']:
        name = Path(ref['path']).name
        timing._file(work,ref).rename(dest/name)
        timing._sync(dest/name)
    timing._sync(dest)
    return {**obs,'status':'measured_as_declared'}


def measure(root, plan, item, entry, run, row, work):
    m = plan['measurement']; frozen = m['population'][item['work_item_id']]; cid = frozen['case_id']
    binding = m['zstd_dictionary_grouped']; cpu = m['environment']['cpu']; before = resource.observe(cpu)
    fixed = err = None; logs, trials = [], []
    case = _case(item,row,entry,cid)
    try:
        stage_recovery(root,work,binding['runtime'],directory='runtime')
        fixed = _fixed(root,run,work,binding,case,entry)
        # Give the detached scratch runner read-only source files, not the run tree.
        scratch_fixed = work/DIRECTORY/cid/'fixed'; scratch_fixed.mkdir(parents=True)
        for ref in fixed.values():
            shutil.copyfile(timing._file(run,ref), work/ref['path'])
    except (ValueError, OSError) as exc:
        anchor = work/'anchor'
        logs = _retain(run,cid,'anchor',[(op,anchor/op) for op in timing.OPERATIONS])
        err = 'dictionary same-run anchor failed: ' + failure.reason(exc,anchor,run/FAILED/cid/'anchor')
        base = run/DIRECTORY/cid
        if base.exists():
            shutil.rmtree(base)
        fixed = None
    for slot in _schedule(cid):
        if err:
            trials.append({**slot,'status':'not_run_after_measurement_failure','reason':err})
            continue
        try:
            trials.append(_trial(root,run,work,binding,case,entry,fixed,slot))
        except (ValueError, OSError) as exc:
            scratch = work/slot['path']; target = run/FAILED/cid/'trial'/slot['op']
            logs = _retain(run,cid,'trial',[(slot['op'],scratch)])
            err = failure.reason(exc,scratch,target)
            trials.append({**slot,'status':'measurement_failed','reason':err})
        finally:
            scratch = work/slot['path']
            if scratch.exists():
                shutil.rmtree(scratch)
    doc = {**frozen,'anchors':fixed,'failure_logs':logs,'status':'measurement_failed' if err else 'measured_and_verified',
           'reason':err,'trials':trials,'timing_admitted':False,'resource_before':before,'resource_after':resource.observe(cpu)}
    return {**doc,'summary':recompute(root,plan,item,entry,run,row,doc,set())}


def recompute(root, plan, item, entry, run, row, doc, seen):
    frozen = plan['measurement']['population'][item['work_item_id']]; cid = frozen['case_id']
    case = _case(item,row,entry,cid); e = case['anchor']; base = run/DIRECTORY/cid
    fixed = doc['anchors']; passed = doc['status'] == 'measured_and_verified'
    require(doc['case_id'] == cid and doc['adapter'] == frozen['adapter'] and doc['timing_admitted'] is False and
            doc['status'] in ('measurement_failed','measured_and_verified') and
            (doc['reason'] is None if passed else bool(doc['reason'])) and (fixed is not None or not passed),
            'dictionary same-run timing terminal differs')
    failure.check(run,f'{FAILED}/{cid}',doc,timing.OPERATIONS)
    paths, measured = set(), []
    if fixed is not None:
        for key, name in (('dictionary','shared.zdict'),('archive','heldout.zdg')):
            require(fixed[key]['path'] == f'{DIRECTORY}/{cid}/fixed/{name}', 'dictionary fixed path differs')
            paths.add(fixed[key]['path'])
        timing._dict_facts(e['dictionary'], timing._file(run,fixed['dictionary']))
        arc = fixed['archive']
        require(inspect_archive(timing._file(run,arc),e) == {k:v for k,v in arc.items() if k != 'path'},
                'dictionary fixed archive chain differs')
    failed = fixed is None
    require(len(doc['trials']) == len(timing.OPERATIONS)*(timing.WARMUPS+timing.ROUNDS), 'dictionary trial denominator differs')
    for slot, trial in zip(_schedule(cid),doc['trials'],strict=True):
        require(all(trial[k] == v for k,v in slot.items()), 'dictionary frozen trial schedule differs')
        if not failed and trial['status'] == 'measured_as_declared':
            timing._check_trial(run,case,fixed,slot,{k:v for k,v in trial.items() if k != 'status'},seen)
            paths.update(r['path'] for r in trial['logs'])
            if trial['phase'] == 'measured':
                measured.append({**trial,'phase':'measure'})
        else:
            require(not passed and trial.get('reason') == doc['reason'] and
                    trial['status'] == ('not_run_after_measurement_failure' if failed else 'measurement_failed'),
                    'dictionary trial terminal differs')
            failed = True
    require(passed == (not failed), 'dictionary decision disagrees with trial terminals')
    inventory = list(base.rglob('*'))
    require(not base.is_symlink() and base.exists() == bool(fixed) and all(not p.is_symlink() for p in inventory) and
            paths == {p.relative_to(run).as_posix() for p in inventory if p.is_file()}, 'dictionary evidence inventory differs')
    return timing._summarize(case,fixed,measured) if passed else None


def observe(root, plan, item, entry, run, row):
    with guard(plan), TemporaryDirectory(prefix='m3-dictionary-primary-',dir=run) as tmp:
        return measure(root,plan,item,entry,run,row,Path(tmp))
