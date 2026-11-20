"""Train and repeat exact r40 ETB1 table/holdout variants under isolation."""
from collections import Counter, defaultdict
from hashlib import sha256
import os
from pathlib import Path
from random import Random
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..planner.huff0 import BLOCK, TABLE
from ..planner.m3_huff0_table import KEY, STREAMS
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_tool, launcher_lock
from .m3_huff0_table import binding, layout, stage
from .m3_metric_details import distribution
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_sprintz_durable import sync_outputs
from .m3_sprintz_timing import LIMITS, check, ref, relative
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-huff0-exact-etb1-timing/1'
TOOL = 'huff0-etb1-timing'
OPS = ('train', 'encode', 'decode')
ROUNDS = 3
GROUP_BLOCKS = (6 << 20) // (BLOCK + TABLE.size)
POLICY = {'sample': 'one_fresh_isolated_process_per_whole_variant_direction_round', 'contexts': 1,
          'encode': 'one_table_load_and_complete_holdout_blocks', 'decode': 'one_table_load_and_complete_block_sequence',
          'train': 'one_constructor_from_frozen_bounded_training_prefix_only',
          'outer_wall': 'from_prepared_inputs_with_supervision_verification_and_fsync',
          'file_groups': 'transport_only_no_native_block_splits_or_extra_table_loads'}
CODE = ('src/tsbench/application/m3_huff0_etb1_timing.py', 'tools/m3_huff0_etb1_timing.py',
        'native/measurement/huff0_etb1/main.cpp', 'native/measurement/huff0_etb1/CMakeLists.txt',
        'src/tsbench/application/m3_huff0_table.py', 'src/tsbench/planner/m3_huff0_table.py',
        'src/tsbench/application/m3_sealed_ledger.py', 'src/tsbench/corpus_ingress.py',
        'src/tsbench/application/m3_sprintz_durable.py', 'src/tsbench/application/m3_sprintz_timing.py',
        'src/tsbench/application/m3_metric_details.py', 'src/tsbench/recovery.py',
        'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py',
        'src/tsbench/supervisor/timing_resource.py')


def schedule():
    rng = Random(20261120)
    return [{'round': i, 'phase': 'warmup' if not i else 'measured', 'operation': op}
            for i in range(ROUNDS+1) for op in rng.sample(OPS, len(OPS))]


def groups(blocks):
    out = []
    for a in range(0, len(blocks), GROUP_BLOCKS):
        b = min(a+GROUP_BLOCKS, len(blocks))
        out.append({'name': f'g{len(out):05d}.bin', 'blocks': [a, b],
                    'raw_bytes': sum(x['original_bytes'] for x in blocks[a:b]),
                    'wire_bytes': sum(x['body_bytes']+TABLE.size for x in blocks[a:b])})
    require(out, 'empty ETB1 holdout')
    return out


def binary_ref(data):
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest()}


def freeze(root, source, source_run, worker, cpu):
    plan = load_json(source)
    ledger, seal = full_run_source(plan, source_run)
    entries = _entry_map(root, load_json(check(root, plan['definition']['plan'])))
    cases, excluded = [], []
    for row, item in full_run_rows(plan, ledger):
        if item is None or 'entry_kind' in row or (row.get('selection'), row.get('route')) != KEY:
            continue
        ds = row['dataset_id']
        if row['status'] != 'verified':
            excluded.append({'dataset_id': ds, 'status': row['status'], 'reason': row['reason']})
            continue
        p, entry = row['evidence'], entries[ds]
        for streams in STREAMS:
            lane = p['profiles'][str(streams)]
            train, held = p['training'], p['holdout']
            model, wire, sidecar = (lane[k] for k in ('model', 'frame', 'binding'))
            blocks = lane['blocks']
            costs = {'model': model['bytes'], 'model_block_binding': sidecar['bytes'], 'block_headers': len(blocks)*TABLE.size,
                     'block_payload': sum(b['body_bytes'] for b in blocks)}
            require(lane['status'] == 'verified' and lane['recovered'] == held and
                    lane['encode'] == lane['decode'] and all(lane[k]['context_count'] == 1 and lane[k]['streams'] == streams for k in OPS) and
                    binary_ref(binding(streams, model, wire)) == sidecar and sum(costs.values()) == lane['complete_bytes'] and
                    costs['block_headers'] + costs['block_payload'] == wire['bytes'] and
                    [b['original_bytes'] for b in blocks] == [min(BLOCK, held['bytes']-n) for n in range(0, held['bytes'], BLOCK)],
                    'ETB1 whole held-out evidence differs from sealed ledger')
            case = {'dataset_id': ds, 'work_item_id': item['work_item_id'], 'canonical_object_id': item['canonical_object_id'],
                    'source_file': entry['file'], 'configuration': item['input'], 'streams': streams, 'training': train,
                    'holdout': held, 'model': model, 'wire': wire, 'binding': sidecar, 'cost': costs, 'blocks': blocks,
                    'groups': groups(blocks), 'native': {k: lane[k] for k in OPS}, 'historical_set_present': bool(lane['retained'])}
            cases.append({**case, 'case_id': content_id(case)})
    require(cases, 'no verified ETB1 cases')
    lib = plan['build']['huff0_table']['dependency']
    check(root, lib)
    exe = relative(root, worker)
    runtime = plan_recovery(root, {}, [], tools={TOOL: {k: exe[k] for k in ('path', 'sha256')}}, libraries=[lib])
    tool, = runtime['tools'].values()
    require(Path(lib['path']).name in runtime['files'][tool]['needed'], 'ETB1 timing worker is not linked to the frozen DSO')
    body = {'schema': SCHEMA, 'source': relative(root, source), 'source_run': source_run.relative_to(root).as_posix(), 'source_seal': seal,
            'worker': exe, 'runtime': runtime, 'launchers': launcher_lock(), 'limits': LIMITS, 'policy': POLICY, 'schedule': schedule(),
            'cases': cases, 'excluded': excluded, 'environment': resource.environment(cpu),
            'code': {name: digest(local_file(root, name)) for name in CODE}}
    return {**body, 'plan_id': content_id(body)}


def verify_group_files(case, directory, lane):
    """Hash one whole ordered artifact as well as its bounded physical extents."""
    require({p.name for p in directory.iterdir()} == {g['name'] for g in case['groups']}, 'ETB1 output groups differ')
    whole = sha256()
    out, n = {}, 0
    for g in case['groups']:
        name = g['name']
        path = local_file(directory, name)
        data = path.read_bytes()
        require(len(data) == g[lane+'_bytes'], 'ETB1 output group length differs')
        whole.update(data)
        n += len(data)
        out[name] = binary_ref(data)
        if lane == 'wire':
            a, b = g['blocks']
            require(layout(path, case['streams'], g['raw_bytes']) == case['blocks'][a:b], 'ETB1 original block evidence differs')
    require({'bytes': n, 'sha256': whole.hexdigest()} == case['wire' if lane == 'wire' else 'holdout'],
            'ETB1 whole sequence digest differs from r40')
    return out


def stage_groups(root, item, entry, case, directory):
    directory.mkdir()
    t, held, train, holdout = stage(root, item, entry, directory)
    require(train == case['training'] and holdout == case['holdout'], 'ETB1 frozen train/holdout scope differs')
    out = directory / 'groups'; out.mkdir()
    with held.open('rb') as source:
        for g in case['groups']:
            data = source.read(g['raw_bytes'])
            require(len(data) == g['raw_bytes'], 'ETB1 staged group shorter than required')
            (out / g['name']).write_bytes(data)
        require(not source.read(1), 'ETB1 held-out source was not exactly consumed')
    return t, out, verify_group_files(case, out, 'raw')


def invoke(bundle, plan, case, op, paths, work):
    work.mkdir()
    if op == 'train':
        argv = [op, str(case['streams']), '/inputs/train', '/out/model']
    else:
        counts = ','.join(str(b-a) for a, b in (g['blocks'] for g in case['groups']))
        argv = [op, '/inputs/model', '/inputs', '/out', counts]
    out, proc = invoke_isolated_tool(bundle, plan['runtime'], TOOL, LIMITS, work, work, op, paths, argv, lambda: False,
                                     observe=True, file_ceiling=LIMITS['file_bytes'])
    err = (work / (op + '.stderr')).read_text()
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and not err,
            f"ETB1 {case['dataset_id']}/{case['streams']}X/{op}: {proc['status']}: {err[:400]}")
    return out, proc, load_json(work / (op + '.stdout'))


def trial(bundle, plan, case, t, paths, work):
    op = t['operation']
    start = monotonic_ns()
    out, proc, doc = invoke(bundle, plan, case, op, paths, work)
    if op == 'train':
        require({p.name for p in out.iterdir()} == {'model'} and ref(local_file(out, 'model')) == case['model'], 'ETB1 model differs')
        output = {'model': case['model']}
    else:
        output = verify_group_files(case, out, 'wire' if op == 'encode' else 'raw')
    s = monotonic_ns()
    sync_outputs(out, output)
    end = monotonic_ns()
    return out, {'case_id': case['case_id'], **t, 'process': proc, 'native': doc, 'output': output,
                 'staged_verified_durable_wall_ns': end-start, 'output_fsync_wall_ns': end-s}


def validate(plan, case, t, row, refs, seen):
    op = t['operation']
    data, p = row['native'], row['process']
    model = {'model': case['model']}
    mounts, out = {'train': ({'train': case['training']}, model),
                   'encode': ({**model, **refs['raw']}, refs['wire']),
                   'decode': ({**model, **refs['wire']}, refs['raw'])}[op]
    keys = ('table_wall_ns', 'block_calls_wall_ns', 'cpu_endpoints')
    require(row['case_id'] == case['case_id'] and all(row[k] == v for k, v in t.items()) and
            row['output'] == out and p['input_mounts'] == mounts and p['operation'] == op and
            p['status'] == 'completed' and p['returncode'] == 0 and not p['reason'] and type(p['pid']) is int and p['pid'] > 0 and
            p['session_id'] and p['session_id'] not in seen and p['child_usage']['maxrss_bytes'] > 0 and
            data['cpu_endpoints'] == [plan['environment']['cpu']]*2 and {k:v for k,v in data.items() if k not in keys} == case['native'][op] and
            data['table_wall_ns'] > 0 and (data['block_calls_wall_ns'] == 0 if op == 'train' else data['block_calls_wall_ns'] > 0) and
            0 < data['table_wall_ns']+data['block_calls_wall_ns'] <= p['process_wall_ns'] <=
            row['staged_verified_durable_wall_ns'] - row['output_fsync_wall_ns'] and row['output_fsync_wall_ns'] > 0,
            'ETB1 trial scope, model, mount, resources or time differs')
    seen.add(p['session_id'])


def summarize(case, rows):
    directions = {}
    for op in OPS:
        chosen = [r for r in rows if r['phase'] == 'measured' and r['operation'] == op]
        require(len(chosen) == ROUNDS, 'ETB1 timing population differs')
        samples = defaultdict(list)
        for r in chosen:
            d, p = r['native'], r['process']
            samples['table_build_wall_ns' if op == 'train' else 'table_load_wall_ns'].append(d['table_wall_ns'])
            if op != 'train':
                samples['block_calls_wall_ns'].append(d['block_calls_wall_ns'])
                samples['native_setup_and_block_calls_wall_ns'].append(d['table_wall_ns']+d['block_calls_wall_ns'])
            samples['process_wall_ns'].append(p['process_wall_ns'])
            for k in ('staged_verified_durable_wall_ns', 'output_fsync_wall_ns'):
                samples[k].append(r[k])
            for k, v in p['child_usage'].items():
                samples['supervised_child_'+k].append(v)
        directions[op] = {'distributions': {k: {**distribution(v), 'sample_basis': POLICY['sample']} for k, v in samples.items()},
                          'holdout_mib_per_second': {k: case['holdout']['bytes'] * ROUNDS * 1e9 / ((1 << 20)*sum(samples[k])) for k in
                              ('block_calls_wall_ns', 'native_setup_and_block_calls_wall_ns', 'process_wall_ns',
                               'staged_verified_durable_wall_ns')} if op != 'train' else None}
    charge = sum(case['cost'].values())
    return {k:case[k] for k in ('dataset_id','work_item_id','configuration','streams','training','holdout','cost','historical_set_present')} | {
        'complete_bytes': charge, 'ratio': case['holdout']['bytes']/charge, 'transport_groups': len(case['groups']),
        'block_modes': dict(Counter(b['mode'] for b in case['blocks'])), 'directions': directions}


def verify(run):
    plan, seal = (load_json(local_file(run, n)) for n in ('plan.json', 'completion.json'))
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and plan['schedule'] == schedule() and plan['limits'] == LIMITS and
            plan['plan_id'] == content_id({k:v for k,v in plan.items() if k != 'plan_id'}) and seal['schema'] == SCHEMA+'-seal' and
            seal['plan_id'] == plan['plan_id'] and seal['run_id'] == run.name and
            seal['seal_id'] == content_id({k:v for k,v in seal.items() if k != 'seal_id'}) and
            seal['files'].keys() == {'plan.json','references.json','environment.json','trials.jsonl'}, 'ETB1 full timing seal differs')
    for f in seal['files'].values():
        check(run, f)
    for n, r in plan['runtime']['files'].items():
        check(run, {'path':'runtime/'+n, 'bytes':r['bytes'], 'sha256':r['sha256']})
    env, refs = (load_json(run/n) for n in ('environment.json','references.json'))
    require(env['affinity'] == [plan['environment']['cpu']] and refs.keys() == {c['case_id'] for c in plan['cases']},
            'ETB1 full timing environment or reference scope differs')
    result, seen = [], set()
    with (run/'trials.jsonl').open('rb') as f:
        for case in plan['cases']:
            require(case['case_id'] == content_id({k:v for k,v in case.items() if k!='case_id'}) and
                    case['groups'] == groups(case['blocks']) and binary_ref(binding(case['streams'], case['model'], case['wire'])) == case['binding'],
                    'ETB1 model binding or group plan differs')
            r = refs[case['case_id']]
            require(all({n:a['bytes'] for n,a in r[lane].items()} == {g['name']:g[lane+'_bytes'] for g in case['groups']}
                        for lane in ('raw','wire')), 'ETB1 reference transport scope differs')
            rows = []
            for t in plan['schedule']:
                row = parse_json(f.readline(), 'ETB1 full timing trial')
                validate(plan, case, t, row, r, seen)
                rows.append(row)
            result.append(summarize(case, rows))
        require(not f.read(1), 'ETB1 full timing ledger has extra attempts')
    return {'schema':SCHEMA+'-report', 'run_id':run.name, 'seal_id':seal['seal_id'], 'source_seal':plan['source_seal'],
            'environment':env, 'policy':POLICY, 'verified_trials':len(seen), 'results':result,'excluded':plan['excluded'],
            'not_measured':{'source_to_durable_endpoint':'full source ingest and train/test extraction are outside these timed trials',
                            'total_process_tree_usage':'only supervised child wait4 statistics', 'system_exclusivity':'cooperative reservation only'},
            'timing_admitted':False, 'qualification_granted':False, 'stage_accepted':False}


def execute(root, plan, output):
    source = check(root, plan['source'])
    source_run = (root/plan['source_run']).resolve(strict=True)
    cpu = plan['environment']['cpu']
    require(output.is_relative_to(root) and source_run.is_relative_to(root) and
            freeze(root, source, source_run, check(root, plan['worker']), cpu) == plan, 'ETB1 source/run policy changed')
    frozen = load_json(source)
    entries = _entry_map(root, load_json(check(root, frozen['definition']['plan'])))
    items = {i['work_item_id']:i for i in frozen['work_items']}
    output.mkdir(parents=True, exist_ok=True)
    from itertools import groupby
    with resource.reserve():
        run = output/uuid4().hex
        run.mkdir()
        print(f'run={run}', flush=True)
        write_new(run/'plan.json', plan)
        bundle = run/'runtime'
        stage_recovery(root, run, plan['runtime'], directory=bundle.name)
        affinity, refs, seen = os.sched_getaffinity(0), {}, set()
        try:
            os.sched_setaffinity(0, {cpu})
            env = {'affinity':sorted(os.sched_getaffinity(0)), 'before':resource.observe(cpu)}
            with (run/'trials.jsonl').open('xb') as ledger:
                for ds, sequence in groupby(plan['cases'], key=lambda c:c['dataset_id']):
                    variants = list(sequence)
                    first = variants[0]
                    with TemporaryDirectory(prefix='etb1-', dir=run) as folder:
                        p = Path(folder)
                        tr, stage_dir, raw = stage_groups(root, items[first['work_item_id']], entries[ds], first, p/'stage')
                        for case in variants:
                            base = p/str(case['streams']); base.mkdir()
                            require(case['training'] == first['training'] and case['holdout'] == first['holdout'] and
                                    all(a['raw_bytes'] == b['raw_bytes'] and a['blocks'] == b['blocks'] for a,b in
                                        zip(case['groups'], first['groups'], strict=True)), 'ETB1 lanes change input geometry')
                            train = {'train': tr}
                            model_output, proc, doc = invoke(bundle, plan, case, 'train', train, base/'model')
                            require(proc['input_mounts'] == {'train':case['training']} and ref(model_output/'model') == case['model'] and
                                    doc['context_count'] == 1, 'ETB1 model did not reproduce r40')
                            enc = {'model':model_output/'model', **{n:stage_dir/n for n in raw}}
                            wire_dir, proc, doc = invoke(bundle, plan, case, 'encode', enc, base/'wire')
                            require(proc['input_mounts'] == {'model':case['model'], **raw} and doc['context_count'] == 1,
                                    'ETB1 wire preparation mounts differ')
                            wire = verify_group_files(case, wire_dir, 'wire')
                            require(binary_ref(binding(case['streams'], case['model'], case['wire'])) == case['binding'], 'ETB1 binding changed')
                            refs[case['case_id']] = {'raw':raw, 'wire':wire}
                            paths = {'train':train, 'encode':enc, 'decode':{'model':model_output/'model', **{n:wire_dir/n for n in wire}}}
                            for i,t in enumerate(plan['schedule']):
                                with TemporaryDirectory(prefix='trial-', dir=base) as scratch:
                                    _, row = trial(bundle, plan, case, t, paths[t['operation']], Path(scratch)/'work')
                                    validate(plan, case, t, row, refs[case['case_id']], seen)
                                    _line(ledger,row)
                            print(f"verified {ds} {case['streams']}X ({len(case['blocks'])} blocks)", flush=True)
            env['after'] = resource.observe(cpu)
        finally:
            os.sched_setaffinity(0, affinity)
        write_new(run/'environment.json', env)
        write_new(run/'references.json', refs)
        seal = {'schema':SCHEMA+'-seal', 'run_id':run.name, 'plan_id':plan['plan_id'],
                'files':{n:relative(run,run/n) for n in ('plan.json','references.json','environment.json','trials.jsonl')}}
        write_new(run/'completion.json', {**seal,'seal_id':content_id(seal)})
    write_new(run/'report.json', verify(run))
    return run
