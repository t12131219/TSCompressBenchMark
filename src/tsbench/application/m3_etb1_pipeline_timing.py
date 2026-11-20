"""Whole-source ETB1 training/encode/publish and files-only durable restoration."""
from collections import defaultdict
from itertools import groupby
import os
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_huff0_etb1_timing as etb1
from .m3_metric_details import distribution
from .m3_real_corpus_execution import _entry_map
from .m3_sprintz_timing import check, ref, relative
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-etb1-source-durable/1'
OPS = ('encode', 'decode')
ROUNDS = 3
POLICY = {'encode': 'read_locked_original_extract_disjoint_train_and_holdout_train_encode_verify_publish',
          'decode': 'read_verify_binding_then_model_and_block_only_restore_verify_publish_canonical_holdout',
          'durability': 'fsync_all_product_files_dir_rename_fsync_parent_not_crash_replay',
          'basis': 'one_complete_pipeline_per_variant_direction_round', 'cleanup': 'outside_whole_clock',
          'ranking': False}
CODE = ('src/tsbench/application/m3_etb1_pipeline_timing.py', 'tools/m3_etb1_pipeline_timing.py',
        'src/tsbench/application/m3_huff0_etb1_timing.py', 'src/tsbench/application/m3_huff0_table.py',
        'src/tsbench/application/m3_sprintz_durable.py', 'src/tsbench/supervisor/process.py',
        'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/timing_resource.py',
        'src/tsbench/recovery.py', 'src/tsbench/corpus_ingress.py')


def schedule():
    rng = Random(20261120)
    return [{'phase': 'warmup' if n == 0 else 'measured', 'round': n, 'direction': op}
            for n in range(ROUNDS + 1) for op in rng.sample(OPS, len(OPS))]


def freeze(root, native_run, cpu):
    report = etb1.verify(native_run)
    require(load_json(native_run/'report.json') == report and not report['excluded'], 'ETB1 source diagnostic does not verify')
    raw = load_json(native_run/'plan.json')
    require(etb1.launcher_lock() == raw['launchers'], 'ETB1 isolation launchers changed')
    body = {'schema': SCHEMA, 'native_run': native_run.relative_to(root).as_posix(), 'native_seal': report['seal_id'],
            'source_seal': report['source_seal'], 'source': raw['source'], 'runtime': raw['runtime'], 'launchers': raw['launchers'],
            'limits': raw['limits'], 'cases': raw['cases'], 'policy': POLICY, 'schedule': schedule(),
            'environment': resource.environment(cpu), 'code': {k: digest(local_file(root, k)) for k in CODE}}
    return {**body, 'plan_id': content_id(body)}


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(temp, dst, names):
    require(temp.parent == dst.parent and not dst.exists() and set(p.name for p in temp.iterdir()) == set(names),
            'ETB1 durable publication requires the exact files and a fresh sibling target')
    for n in names:
        with local_file(temp, n).open('rb') as f:
            os.fsync(f.fileno())
    fsync_dir(temp)
    temp.rename(dst)
    fsync_dir(dst.parent)


def check_binding(case, product):
    model = ref(local_file(product, 'model'))
    expected = etb1.binding(case['streams'], model, case['wire'])
    sidecar = local_file(product, 'binding.json').read_bytes()
    require(model == case['model'] and sidecar == expected and etb1.binary_ref(sidecar) == case['binding'],
            'ETB1 durable model-to-block binding differs')


def encode_trial(root, bundle, plan, case, item, entry, folder, prepared=None, do_publish=True):
    phases = {}
    start = monotonic_ns()
    train, held, raw = prepared or etb1.stage_groups(root, item, entry, case, folder/'ingress')
    tick = monotonic_ns()
    phases['source_read_and_stage_ns'] = tick-start
    model_dir, p0, train_native = etb1.invoke(bundle, plan, case, 'train', {'train': train}, folder/'train')
    model = local_file(model_dir, 'model')
    require({p.name for p in model_dir.iterdir()} == {'model'} and ref(model) == case['model'], 'ETB1 durable model differs')
    end = monotonic_ns()
    phases['train_and_check_ns'] = end-tick
    wire_dir, p1, enc_native = etb1.invoke(bundle, plan, case, 'encode', {'model': model, **{n: held/n for n in raw}}, folder/'encode')
    wire = etb1.verify_group_files(case, wire_dir, 'wire')
    tick = monotonic_ns()
    phases['holdout_encode_and_check_ns'] = tick-end
    draft, result = (folder/n for n in ('draft-etb1', 'etb1'))
    draft.mkdir()
    model.rename(draft/'model')
    for name in wire:
        (wire_dir/name).rename(draft/name)
    (draft/'binding.json').write_bytes(etb1.binding(case['streams'], case['model'], case['wire']))
    check_binding(case, draft)
    files = {**wire, 'model': case['model'], 'binding.json': case['binding']}
    if do_publish:
        publish(draft, result, files)
    else:
        draft.rename(result)
    end = monotonic_ns()
    phases['assemble_bind_and_publish_ns'] = end-tick
    return result, {'phases_ns': phases, 'wall_ns': end-start, 'raw': raw, 'wire': wire, 'products': files,
                    'children': {'train': p0, 'encode': p1}, 'native': {'train': train_native, 'encode': enc_native}}


def decode_trial(bundle, plan, case, product, folder):
    start = monotonic_ns()
    check_binding(case, product)
    names = [g['name'] for g in case['groups']]
    # Only encoded bytes and the model enter the decoder. SHA-256 mount hashes
    # are checked outside the decoder against this same sealed reference set.
    paths = {n: product/n for n in [*names, 'model']}
    tick = monotonic_ns()
    out, proc, native = etb1.invoke(bundle, plan, case, 'decode', paths, folder/'decode')
    raw = etb1.verify_group_files(case, out, 'raw')
    checked = monotonic_ns()
    draft = folder/'draft-restored'
    out.rename(draft)
    publish(draft, folder/'restored', raw)
    end = monotonic_ns()
    return {'phases_ns': {'check_binding_ns': tick-start, 'decode_and_check_ns': checked-tick, 'publish_ns': end-checked},
            'wall_ns': end-start, 'products': raw, 'children': {'decode': proc}, 'native': {'decode': native}}


def validate(plan, case, t, row, refs, seen):
    direction = t['direction']
    require(row['case_id'] == case['case_id'] and all(row[k] == v for k, v in t.items()), 'ETB1 pipeline trial scope differs')
    parts = row['phases_ns']
    phase = {'train': 'train_and_check_ns', 'encode': 'holdout_encode_and_check_ns', 'decode': 'decode_and_check_ns'}
    if direction == 'encode':
        require(set(parts) == {'source_read_and_stage_ns', phase['train'], phase['encode'], 'assemble_bind_and_publish_ns'} and
                row['raw'] == refs['raw'] and row['wire'] == refs['wire'] and
                row['products'] == {**refs['wire'], 'model': case['model'], 'binding.json': case['binding']},
                'ETB1 complete durable encode product differs')
        mounts = {'train': {'train': case['training']}, 'encode': {**refs['raw'], 'model': case['model']}}
    else:
        require(set(parts) == {'check_binding_ns', phase['decode'], 'publish_ns'} and row['products'] == refs['raw'],
                'ETB1 complete durable recovery differs')
        mounts = {'decode': {**refs['wire'], 'model': case['model']}}
    require(all(type(v) is int and v > 0 for v in parts.values()) and row['wall_ns'] == sum(parts.values()) and
            row['native'].keys() == row['children'].keys() == mounts.keys(), 'ETB1 pipeline phase sum or process population differs')
    for op, m in mounts.items():
        p, d = row['children'][op], row['native'][op]
        native = {k:v for k,v in d.items() if k not in ('table_wall_ns','block_calls_wall_ns','cpu_endpoints')}
        require(p['operation'] == op and p['input_mounts'] == m and p['status'] == 'completed' and p['returncode'] == 0 and
                not p['reason'] and p['session_id'] and p['session_id'] not in seen and p['child_usage']['maxrss_bytes'] > 0 and
                d['cpu_endpoints'] == [plan['environment']['cpu']]*2 and native == case['native'][op] and d['table_wall_ns'] > 0 and
                (d['block_calls_wall_ns'] == 0 if op == 'train' else d['block_calls_wall_ns'] > 0) and
                0 < d['table_wall_ns']+d['block_calls_wall_ns'] <= p['process_wall_ns'] <= parts[phase[op]],
                'ETB1 pipeline child mounts, native configuration or nested clock differs')
        seen.add(p['session_id'])


def summarize(case, rows):
    result = {}
    for op in OPS:
        chosen = [r for r in rows if r['phase'] == 'measured' and r['direction'] == op]
        require(len(chosen) == ROUNDS, 'ETB1 pipeline sample denominator differs')
        observations = defaultdict(list)
        for r in chosen:
            observations['whole_wall_ns'].append(r['wall_ns'])
            for k, ns in r['phases_ns'].items():
                observations[k].append(ns)
            for activity, p in r['children'].items():
                observations[activity+'_child_wall_ns'].append(p['process_wall_ns'])
                for k, n in p['child_usage'].items():
                    observations[f'{activity}_child_{k}'].append(n)
        result[op] = {'distributions': {k: {**distribution(a), 'sample_basis': POLICY['basis']} for k, a in observations.items()},
                      'whole_holdout_mib_per_second': case['holdout']['bytes']*ROUNDS*1e9/(sum(observations['whole_wall_ns'])*(1<<20))}
    charge = sum(case['cost'].values())
    return {k:case[k] for k in ('dataset_id','work_item_id','streams','training','holdout','cost','configuration')} | {
        'logical_source_file_bytes_per_encode':case['source_file']['bytes'], 'complete_bytes':charge,
        'ratio':case['holdout']['bytes']/charge, 'directions':result}


def verify(run):
    plan, seal = (load_json(local_file(run,n)) for n in ('plan.json','completion.json'))
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and plan['schedule'] == schedule() and
            plan['plan_id'] == content_id({k:v for k,v in plan.items() if k != 'plan_id'}) and plan['limits'] == etb1.LIMITS and
            seal['schema'] == SCHEMA+'-seal' and seal['run_id'] == run.name and seal['plan_id'] == plan['plan_id'] and
            seal['seal_id'] == content_id({k:v for k,v in seal.items() if k != 'seal_id'}) and
            seal['files'].keys() == {'plan.json','environment.json','refs.json','trials.jsonl'}, 'ETB1 pipeline seal differs')
    for f in seal['files'].values():
        check(run,f)
    for n, x in plan['runtime']['files'].items():
        check(run, {'path':'runtime/'+n,'sha256':x['sha256'],'bytes':x['bytes']})
    env, references = (load_json(run/n) for n in ('environment.json','refs.json'))
    require(env['affinity'] == [plan['environment']['cpu']] and references.keys() == {c['case_id'] for c in plan['cases']},
            'ETB1 pipeline CPU or reference scope differs')
    results, seen = [], set()
    with (run/'trials.jsonl').open('rb') as log:
        for c in plan['cases']:
            require(c['case_id'] == content_id({k:v for k,v in c.items() if k!='case_id'}), 'ETB1 pipeline case identity differs')
            refs = references[c['case_id']]
            require(all({k:v['bytes'] for k,v in refs[lane].items()} == {g['name']:g[lane+'_bytes'] for g in c['groups']}
                        for lane in ('raw','wire')), 'ETB1 pipeline fixed archive/holdout extent differs')
            trials = []
            for t in plan['schedule']:
                trial = parse_json(log.readline(),'ETB1 pipeline trial')
                validate(plan,c,t,trial,refs,seen)
                trials.append(trial)
            results.append(summarize(c,trials))
        require(not log.read(1),'ETB1 pipeline has extra trials')
    return {'schema':SCHEMA+'-report', 'run_id':run.name, 'seal_id':seal['seal_id'], 'source_seal':plan['source_seal'],
            'native_seal':plan['native_seal'], 'policy':POLICY, 'environment':env, 'results':results,
            'verified_trials':len(results)*len(schedule()),'isolated_trial_processes':len(seen),
            'not_measured':{'whole_path_cpu_rss':'only child wait4 counters, not total coordinator/process tree',
                            'exclusivity':'cooperative TSBench reservation, not isolated OS core'},
            'timing_admitted':False,'qualification_granted':False,'stage_accepted':False}


def execute(root, plan, output):
    native_run = (root/plan['native_run']).resolve(strict=True)
    cpu = plan['environment']['cpu']
    require(native_run.is_relative_to(root) and output.is_relative_to(root) and freeze(root,native_run,cpu) == plan,
            'ETB1 pipeline plan, runtime, or environment changed')
    base_plan = load_json(check(root,plan['source']))
    entries = _entry_map(root,load_json(check(root,base_plan['definition']['plan'])))
    items = {i['work_item_id']:i for i in base_plan['work_items']}
    output.mkdir(parents=True,exist_ok=True)
    with resource.reserve():
        run = output/uuid4().hex
        run.mkdir()
        print(f'run={run}',flush=True)
        write_new(run/'plan.json',plan)
        bundle = run/'runtime'; stage_recovery(root,run,plan['runtime'],directory=bundle.name)
        affinity, seen, refs = os.sched_getaffinity(0), set(), {}
        try:
            os.sched_setaffinity(0,{cpu})
            env = {'affinity':sorted(os.sched_getaffinity(0)),'before':resource.observe(cpu)}
            with (run/'trials.jsonl').open('xb') as log:
                for ds, cases in groupby(plan['cases'],key=lambda c:c['dataset_id']):
                    cases = list(cases)
                    entry = entries[ds]
                    with TemporaryDirectory(prefix='etb1-cases-',dir=run) as tmp:
                        p = Path(tmp)
                        first = cases[0]; item = items[first['work_item_id']]
                        prepared = etb1.stage_groups(root,item,entry,first,p/'reference-ingress')
                        for c in cases:
                            a = p/str(c['streams']); a.mkdir()
                            refdir = a/'reference'; refdir.mkdir()
                            archive, built = encode_trial(root,bundle,plan,c,item,entry,refdir,prepared,do_publish=False)
                            fixed = {'raw':built['raw'],'wire':built['wire']}
                            refs[c['case_id']] = fixed
                            for t in plan['schedule']:
                                with TemporaryDirectory(prefix='trial-',dir=a) as scratch:
                                    phase = Path(scratch)
                                    if t['direction'] == 'encode':
                                        _, observed = encode_trial(root,bundle,plan,c,item,entry,phase)
                                    else:
                                        observed = decode_trial(bundle,plan,c,archive,phase)
                                    row = {**t,'case_id':c['case_id'],**observed}
                                    validate(plan,c,t,row,fixed,seen)
                                    _line(log,row)
                            print(f"verified {ds} {c['streams']}X durable",flush=True)
            env['after'] = resource.observe(cpu)
        finally:
            os.sched_setaffinity(0,affinity)
        write_new(run/'environment.json',env); write_new(run/'refs.json',refs)
        seal = {'schema':SCHEMA+'-seal','run_id':run.name,'plan_id':plan['plan_id'],
                'files':{n:relative(run,run/n) for n in ('plan.json','environment.json','refs.json','trials.jsonl')}}
        write_new(run/'completion.json',{**seal,'seal_id':content_id(seal)})
    write_new(run/'report.json',verify(run))
    return run
