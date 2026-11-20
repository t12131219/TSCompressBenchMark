"""Same-scope, file-isolated repeats of the sealed M3 Zstd dictionary case."""
from collections import Counter
from pathlib import Path
from random import Random
from statistics import median
from tempfile import TemporaryDirectory
from time import monotonic_ns, process_time_ns
from uuid import uuid4
import os
import shutil

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..planner.m3_zstd_dictionary import DRIVER, KEY, LIMIT, extents
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource, zstd_dictionary_grouped as launch
from ..supervisor.isolated_worker import launcher_lock
from .m3_lzbench_timing import _affinity, _file, _folder, _identity, _ref
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_zstd_dictionary_grouped import FRAME, HEAD, inspect_archive, stage_inputs
from .smoke import _line, utc, write_new

SCHEMA = 'bmk.m3-zstd-dictionary-timing-plan/1'
OPERATIONS = ('train', 'encode', 'decode')
WARMUPS, ROUNDS, SEED = 1, 3, 173528
POLICY = {
    'warmups': WARMUPS, 'rounds': ROUNDS, 'order_seed': SEED, 'holdout_frame_bytes': LIMIT,
    'scope': 'three separate operations; one files-only process per direction and file',
    'train': 'reopen verified original in controller; worker only receives exact train prefix; output is independently verified dictionary',
    'encode': 'reopen verified original in controller; worker only receives exact holdout and fixed dictionary',
    'decode': 'worker only receives fixed ZDG1 and fixed dictionary; no original, raw values or training input',
    'fixed': 'one r40 dictionary and one independently verified ZDG1 per file; no retraining inside encode or decode',
    'native': 'training call, or sum over per-frame session construct, feature_io streaming and session teardown; not pure kernel',
    'process': 'supervised child wall and wait4 user/system CPU and peak RSS, not codec-exclusive',
    'durable': 'from original or fixed inputs through isolation, output validation and file plus immediate directory fsync',
    'billing': 'native frames plus ZDG1 overhead plus one necessary serialized dictionary; training input and cost kept separate',
    'cache': 'inherited, no eviction or cold-cache claim', 'exclusive_cpu': False, 'reservation': resource.RESERVATION,
    'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False,
}


def _population(source, ledger, source_run, entries):
    rng, cases = Random(SEED), []
    for row, item in full_run_rows(source, ledger):
        if row.get('entry_kind') is not None or (item['selection'], item['route']) != KEY:
            continue
        ds = item['dataset_id']
        e, entry = row['evidence'], entries[ds]
        ranges, each, count = extents(item, entry)
        dictionary = e['dictionary']
        frames = e['frames']
        held = {'bytes': ranges[1][1] - ranges[1][0], 'sha256': entry['partitions'][2]['canonical']['values_sha256']}
        cap = item['input']['training']['dictionary_capacity_bytes']
        require(row['status'] == 'verified' and e['driver'] == DRIVER and not e['fallback_used'] and e['test_attempted'] and
                e['failed_units'] == 0 and e['holdout'] == held and e['train_bytes'] == each * count == ranges[0][1]-ranges[0][0] and
                0 < held['bytes'] <= launch.FILE_CEILING and len(frames) == (held['bytes'] + LIMIT-1)//LIMIT and
                8 <= dictionary['bytes'] <= cap and dictionary['id'] > 1 and
                e['holdout_object_id'] == item['input']['training']['evaluation']['partition_object_id'],
                'r40 dictionary populations, geometry or terminal differs')
        for i, frame in enumerate(frames):
            lo, hi = i*LIMIT, min(held['bytes'], (i+1)*LIMIT)
            require((frame['index'], frame['holdout_byte_range'], frame['logical_bytes']) == (i, [lo, hi], hi-lo) and
                    frame['status'] == 'verified' and frame['restored_sha256'] == frame['input_sha256'] and
                    frame['dictionary_id'] == dictionary['id'], 'r40 dictionary frame geometry or recovery differs')
        native_bytes = sum(f['bytes'] for f in frames)
        require(e['verified_frame_bytes'] == native_bytes and
                e['verified_frame_bytes_plus_shared_dictionary_once'] == native_bytes + dictionary['bytes'],
                'r40 dictionary frame count or billing differs')
        _dict_facts(dictionary, _file(source_run, dictionary))
        anchor = {k: e[k] for k in ('dictionary', 'frames', 'holdout', 'train_prefix_sha256', 'verified_frame_bytes',
                                    'verified_frame_bytes_plus_shared_dictionary_once')}
        body = {k: item[k] for k in ('work_item_id', 'dataset_id', 'route', 'operation_config_id', 'canonical_object_id')}
        body.update(item=item, anchor=anchor, source=entry['file'], training=[cap, each, count],
                    order=[rng.sample(OPERATIONS, len(OPERATIONS)) for _ in range(WARMUPS + ROUNDS)])
        cases.append({**body, 'case_id': content_id(body)})
    require(len(cases) == len(entries) == 23 and {c['dataset_id'] for c in cases} == set(entries),
            'dictionary diagnostic must cover all frozen files')
    return cases


def freeze(root, plan_path, source_run, tool, cpu):
    source = load_json(plan_path)
    ledger, seal = full_run_source(source, source_run)
    definition = source['definition']['plan']
    entries = _entry_map(root, load_json(_file(root, definition)))
    tool_ref = _ref(root, tool)
    dictionary = source['build']['zstd_dictionary']
    _file(root, dictionary['executable'])
    _file(root, dictionary['dependency'])
    runtime = plan_recovery(root, {}, (), tools={launch.NAME: {k: tool_ref[k] for k in ('path', 'sha256')}},
                            libraries=[dictionary['dependency']])
    require(runtime['tools'] == {launch.NAME: launch.TOOL} and launch.LIBRARY in runtime['files'] and
            launch.LIBRARY.split('/')[-1] in runtime['files'][launch.TOOL]['needed'], 'grouped dictionary ELF binding differs')
    code = ('src/tsbench/application/m3_zstd_dictionary_timing.py', 'src/tsbench/application/m3_zstd_dictionary_grouped.py',
            'src/tsbench/supervisor/zstd_dictionary_grouped.py', 'src/tsbench/qualification/zstd_dictionary_grouped_wire.py',
            'src/tsbench/corpus_ingress.py', 'src/tsbench/planner/m3_zstd_dictionary.py', 'src/tsbench/supervisor/process.py',
            'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/application/m3_sealed_ledger.py',
            'native/measurement/zstd_dictionary_grouped/main.cpp', 'native/measurement/zstd_dictionary_grouped/CMakeLists.txt',
            'tools/m3_zstd_dictionary_timing.py', 'tests/isolation/zstd_dictionary_grouped_smoke.py')
    body = {'schema': SCHEMA, 'source_plan': _ref(root, plan_path), 'source_run': source_run.relative_to(root).as_posix(),
            'source_seal': seal, 'definition': definition, 'tool': tool_ref, 'runtime': runtime, 'policy': POLICY,
            'environment': resource.environment(cpu), 'launchers': launcher_lock(),
            'code': [_ref(root, local_file(root, f)) for f in code], 'cases': _population(source, ledger, source_run, entries)}
    return {**body, 'plan_content_id': content_id(body)}


def _facts(ref):
    return {k: ref[k] for k in ('bytes', 'sha256')}


def _amounts(path):
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def _dict_facts(ref, path):
    with path.open('rb') as f:
        head = f.read(8)
    got = _amounts(path)
    require(got == _facts(ref) and head[:4] == bytes.fromhex('37a430ec') and
            int.from_bytes(head[4:], 'little') == ref['id'], 'dictionary byte or ID parity differs from r40')
    return got


def _sync(path):
    fd = os.open(path, os.O_RDONLY | (os.O_DIRECTORY if path.is_dir() else 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _op(run, plan, place, op, source, **geometry):
    place.mkdir()
    output, proc = launch.run(run / 'runtime', plan['runtime'], place, source, op, **geometry)
    logs = [place / f'native.{x}' for x in ('stdout', 'stderr')]
    require(proc['status'] == 'completed', f"dictionary {op}: {proc['status']}; see {logs[1]}")
    require(logs[1].stat().st_size == 0 and output.is_file() and list(output.parent.iterdir()) == [output],
            'grouped dictionary product inventory differs')
    obs = load_json(logs[0])
    return output, proc, obs, logs


def _scratch(run, c):
    return run / 'cases' / c['case_id']


def _fixed(root, run, plan, c, entry):
    place = _scratch(run, c)
    fixed = place / 'fixed'
    fixed.mkdir(parents=True)
    e = c['anchor']
    dref = e['dictionary']
    target = fixed / 'shared.zdict'
    shutil.copyfile(_file(_folder(root, plan['source_run']), dref), target)
    _dict_facts(dref, target)
    logical = e['holdout']['bytes']
    archive = fixed / 'heldout.zdg'
    with TemporaryDirectory(dir=place, prefix='reference-') as tmp:
        w = Path(tmp)
        source = stage_inputs(root, c['item'], entry, w, e, roles=('holdout',))['holdout']
        wire, proc, _, _ = _op(run, plan, w / 'encode', 'encode', source, dictionary=target, logical=logical)
        require(proc['input_mounts'] == {'holdout': e['holdout'], 'dictionary': _facts(dref)}, 'dictionary setup encode input differs')
        proof = inspect_archive(wire, e)
        wire.rename(archive)
        output, proc, _, _ = _op(run, plan, w / 'decode', 'decode', archive, dictionary=target, logical=logical)
        require(proc['input_mounts'] == {'archive': _facts(proof), 'dictionary': _facts(dref)} and _amounts(output) == e['holdout'],
                'detached decode of fixed dictionary archive differs')
    for p in (target, archive, fixed, place):
        _sync(p)
    return {'dictionary': _ref(run, target), 'archive': {'path': archive.relative_to(run).as_posix(), **proof}}


def _schedule(c):
    for r, ops in enumerate(c['order']):
        for op in ops:
            yield {'op': op, 'repeat': r, 'phase': 'warmup' if r < WARMUPS else 'measure', 'case_id': c['case_id'],
                   'path': f"cases/{c['case_id']}/{r:02d}-{op}"}


def _trial(root, run, plan, c, entry, fixed, slot):
    place = run / slot['path']
    e, op = c['anchor'], slot['op']
    original = None if op == 'decode' else c['source']
    a, b, ingress = monotonic_ns(), process_time_ns(), None
    if op == 'decode':
        archive = local_file(run, fixed['archive']['path'])
        dictionary = local_file(run, fixed['dictionary']['path'])
        output, proc, obs, logs = _op(run, plan, place, op, archive, dictionary=dictionary, logical=e['holdout']['bytes'])
    else:
        with TemporaryDirectory(dir=place.parent, prefix=f'{op}-stage-') as tmp:
            role = 'train' if op == 'train' else 'holdout'
            input_ = stage_inputs(root, c['item'], entry, Path(tmp), e, roles=(role,))[role]
            ingress = monotonic_ns() - a
            params = {'training': tuple(c['training'])} if op == 'train' else {
                'dictionary': local_file(run, fixed['dictionary']['path']), 'logical': e['holdout']['bytes']}
            output, proc, obs, logs = _op(run, plan, place, op, input_, **params)
    if op == 'train':
        product = _dict_facts(e['dictionary'], output)
    elif op == 'encode':
        product = _facts(inspect_archive(output, e))
    else:
        product = _amounts(output)
    _sync(output)
    _sync(output.parent)
    _sync(place)
    wall, cpu = monotonic_ns()-a, process_time_ns()-b
    return {**slot, 'source_original': original, 'ingress_wall_ns': ingress, 'process': proc, 'native': obs, 'product': product,
            'durable_wall_ns': wall, 'controller_cpu_ns': cpu, 'logs': [_ref(run, path) for path in logs]}, output


def _check_trial(run, c, fixed, slot, row, sessions):
    require(set(row) == {*slot, 'source_original', 'ingress_wall_ns', 'process', 'native', 'product', 'durable_wall_ns',
                         'controller_cpu_ns', 'logs'} and all(row[k] == v for k,v in slot.items()), 'dictionary trial slot differs')
    op, e = slot['op'], c['anchor']
    dict_ref, archive = fixed['dictionary'], fixed['archive']
    cap, each, count = c['training']
    d = _facts(dict_ref)
    routed = {'train': ({'prefix': {'bytes': each*count, 'sha256': e['train_prefix_sha256']}}, d),
              'encode': ({'holdout': e['holdout'], 'dictionary': d}, _facts(archive)),
              'decode': ({'archive': _facts(archive), 'dictionary': d}, e['holdout'])}
    mounts, product = routed[op]
    proc, native = row['process'], row['native']
    want_native = {'operation': op, 'dictionary_id': e['dictionary']['id'], 'dictionary_bytes': d['bytes']}
    if op == 'train':
        want_native.update(samples=count, sample_bytes=each, input_bytes=each*count, dictionary_capacity_bytes=cap)
    else:
        want_native.update(logical_bytes=e['holdout']['bytes'], native_frames=archive['native_frames'],
                           native_frame_bytes=archive['native_frame_bytes'], wrapper_bytes=archive['wrapper_bytes'], worker_threads=0)
        require(type(native.get('jobs')) is int and native['jobs'] >= 0, 'dictionary worker job observation differs')
        want_native['jobs'] = native['jobs']
    require(set(native) == {*want_native, 'call_wall_ns', 'call_cpu_ns'} and
            all(native[k] == v for k,v in want_native.items()) and type(native['call_wall_ns']) is int and native['call_wall_ns'] > 0 and
            type(native['call_cpu_ns']) is int and native['call_cpu_ns'] >= 0, 'dictionary native observation or clock differs')
    ingress = row['ingress_wall_ns']
    require(row['source_original'] == (None if op == 'decode' else c['source']) and
            (ingress is None if op == 'decode' else type(ingress) is int and ingress > 0), 'dictionary ingress provenance differs')
    child = proc['child_usage']
    require(proc['status'] == 'completed' and proc['operation'] == 'native' and proc['returncode'] == 0 and not proc['reason'] and
            type(proc['pid']) is int and proc['pid'] > 0 and isinstance(proc['session_id'], str) and proc['session_id'] not in sessions and
            proc['input_mounts'] == mounts and row['product'] == product and
            set(child) == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and all(type(v) is int and v >= 0 for v in child.values()) and
            child['maxrss_bytes'] > 0 and type(proc['process_wall_ns']) is int and
            native['call_wall_ns'] <= proc['process_wall_ns'] and type(row['durable_wall_ns']) is int and
            (ingress or 0)+proc['process_wall_ns'] <= row['durable_wall_ns'] and type(row['controller_cpu_ns']) is int and row['controller_cpu_ns'] > 0,
            'dictionary trial did not verify isolation, output or clock boundaries')
    sessions.add(proc['session_id'])
    require([x['path'] for x in row['logs']] == [f"{slot['path']}/native.{x}" for x in ('stdout', 'stderr')] and
            row['logs'][1]['bytes'] == 0, 'dictionary trial log coordinates differ')
    stdout, _ = (_file(run, r) for r in row['logs'])
    require(load_json(stdout) == native, 'dictionary trial observation does not recompute from stdout')


def _dist(xs):
    return {'min': min(xs), 'median': median(xs), 'max': max(xs)}


def _summarize(c, fixed, rows):
    arc = fixed['archive']
    _, each, count = c['training']
    logical = c['anchor']['holdout']['bytes']
    result = {k: c[k] for k in ('dataset_id', 'case_id', 'route', 'work_item_id', 'operation_config_id')}
    result['configuration'] = c['item']['input']
    result['billing'] = {**{k: arc[k] for k in ('native_frames', 'native_frame_bytes', 'wrapper_bytes', 'dictionary_bytes', 'recovery_bytes')},
                         'holdout_logical_bytes': logical, 'train_logical_bytes': each*count, 'train_samples': count,
                         'holdout_logical_over_recovery': logical / arc['recovery_bytes']}
    for op in OPERATIONS:
        xs = [r for r in rows if r['phase'] == 'measure' and r['op'] == op]
        require(len(xs) == ROUNDS, 'dictionary measurements did not cover every repeat')
        metric = {'count': len(xs), 'native_wall_ns': _dist([r['native']['call_wall_ns'] for r in xs]),
                  'native_cpu_ns': _dist([r['native']['call_cpu_ns'] for r in xs]),
                  'process_wall_ns': _dist([r['process']['process_wall_ns'] for r in xs]),
                  'durable_wall_ns': _dist([r['durable_wall_ns'] for r in xs]),
                  'controller_cpu_ns': _dist([r['controller_cpu_ns'] for r in xs]),
                  'child_usage': {k: _dist([r['process']['child_usage'][k] for r in xs]) for k in xs[0]['process']['child_usage']}}
        if op != 'decode':
            metric['ingress_wall_ns'] = _dist([r['ingress_wall_ns'] for r in xs])
        if op != 'train':
            metric['observed_background_worker_threads'] = 0
            metric['logical_mib_s'] = {k: _dist([logical * 1e9 / ((1 << 20)*ns) for ns in v]) for k,v in (
                ('native', [r['native']['call_wall_ns'] for r in xs]), ('durable', [r['durable_wall_ns'] for r in xs]))}
        result[op] = metric
    return result


def _report(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and len(plan['cases']) == 23, 'dictionary plan contract differs')
    sets, env = [load_json(local_file(run, n)) for n in ('setup.json', 'environment.json')]
    require(set(sets) == {c['case_id'] for c in plan['cases']} and set(env) == {'before', 'after'} and
            all(e['affinity'] == [plan['environment']['cpu']] for e in env.values()), 'dictionary setup or CPU binding differs')
    rng, result, sessions = Random(SEED), [], set()
    with local_file(run, 'trials.jsonl').open(encoding='utf-8') as f:
        for c in plan['cases']:
            _identity(c, 'case_id')
            require(c['order'] == [rng.sample(OPERATIONS, len(OPERATIONS)) for _ in range(WARMUPS + ROUNDS)],
                    'dictionary freeze permutation differs')
            fixed = sets[c['case_id']]
            for k, name in (('dictionary', 'shared.zdict'), ('archive', 'heldout.zdg')):
                require(fixed[k]['path'] == f"cases/{c['case_id']}/fixed/{name}", 'dictionary setup artifact coordinate differs')
            _dict_facts(c['anchor']['dictionary'], _file(run, fixed['dictionary']))
            a = fixed['archive']
            require(inspect_archive(local_file(run, a['path']), c['anchor']) == {k: v for k,v in a.items() if k != 'path'},
                    'fixed dictionary frame chain differs')
            rows = []
            for slot in _schedule(c):
                row = parse_json(next(f, ''), 'dictionary grouped trial')
                _check_trial(run, c, fixed, slot, row, sessions)
                rows.append(row)
            result.append(_summarize(c, fixed, rows))
        require(next(f, None) is None, 'extra dictionary grouped trials')
    return {'schema': 'bmk.m3-zstd-dictionary-timing-report/1', 'run_id': run.name, 'source_seal': plan['source_seal'],
            'plan_content_id': plan['plan_content_id'], 'policy': POLICY, 'environment': env, 'cases': result,
            'verified_trials': len(sessions), 'file_routes': dict(Counter(c['route'] for c in result)),
            'qualification_granted': False, 'stage_accepted': False, 'timing_admitted': False}


def _seal(run):
    files = ('plan.json', 'setup.json', 'environment.json', 'trials.jsonl', 'report.json')
    body = {'schema': 'bmk.m3-zstd-dictionary-timing-seal/1', 'run_id': run.name,
            'files': [_ref(run, local_file(run, name)) for name in files]}
    return {**body, 'seal_id': content_id(body)}


def execute(root, plan, output):
    require(output.is_absolute() and output.is_relative_to(root), 'dictionary results must be project-local')
    cpu = plan['environment']['cpu']
    with resource.reserve():
        require(freeze(root, _file(root, plan['source_plan']), _folder(root, plan['source_run']), _file(root, plan['tool']), cpu) == plan,
                'grouped dictionary frozen inputs, executable or host differ')
        entries = _entry_map(root, load_json(_file(root, plan['definition'])))
        output.mkdir(parents=True, exist_ok=True)
        require(shutil.disk_usage(output).free >= (1 << 30), 'insufficient disk headroom for dictionary diagnostics')
        with _affinity([cpu]):
            run = output / uuid4().hex
            run.mkdir()
            write_new(run / 'plan.json', plan)
            stage_recovery(root, run, plan['runtime'], directory='runtime')
            def observe():
                return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)), 'cpu_snapshot': resource.observe(cpu)}
            before, setups, sessions = observe(), {}, set()
            with (run / 'trials.jsonl').open('xb') as f:
                for c in plan['cases']:
                    entry = entries[c['dataset_id']]
                    fixed = setups[c['case_id']] = _fixed(root, run, plan, c, entry)
                    for slot in _schedule(c):
                        row, product = _trial(root, run, plan, c, entry, fixed, slot)
                        _check_trial(run, c, fixed, slot, row, sessions)
                        _line(f, row)
                        product.unlink()
                        product.parent.rmdir()
            write_new(run / 'setup.json', setups)
            write_new(run / 'environment.json', {'before': before, 'after': observe()})
            write_new(run / 'report.json', _report(run, plan))
            write_new(run / 'completion.json', _seal(run))
            _sync(run)
    return run


def verify(run):
    root = Path(__file__).resolve().parents[3]
    require(load_json(local_file(run, 'completion.json')) == _seal(run), 'grouped dictionary seal differs')
    plan = load_json(local_file(run, 'plan.json'))
    source = load_json(_file(root, plan['source_plan']))
    source_run = _folder(root, plan['source_run'])
    ledger, seal = full_run_source(source, source_run)
    require(plan['definition'] == source['definition']['plan'] and plan['source_seal'] == seal, 'dictionary source seal differs')
    entries = _entry_map(root, load_json(_file(root, plan['definition'])))
    require(plan['cases'] == _population(source, ledger, source_run, entries), 'dictionary archived plan does not match sealed r40 work')
    for name, ref in plan['runtime']['files'].items():
        _file(run, {'path': f'runtime/{name}', **ref})
    result = _report(run, plan)
    require(result == load_json(local_file(run, 'report.json')), 'grouped dictionary report differs on recomputation')
    return result
