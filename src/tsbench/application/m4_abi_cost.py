"""Sealed true same-ABI comparisons across representative real input sizes."""
from collections import defaultdict
import os
from random import Random
import re
import shutil
from statistics import median
from uuid import uuid4

from ..assets import canonical_bytes, content_id, load_json, local_file, parse_json, require
from ..corpus_ingress import read_batches
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import m4_abi_cost as launcher, timing_resource as resource
from ..supervisor.isolated_worker import launcher_lock
from .m3_lzbench_timing import _affinity, _file, _identity, _ref
from .m3_lzbench_workers import artifact
from .m3_real_corpus_execution import _entry_map
from .smoke import _line, utc, write_new

SCHEMA = 'bmk.m4-abi-identical-work-plan/1'
SEAL = 'bmk.m4-abi-identical-work-seal/1'
CONFIG = 'configs/experiments/measurement_controls/m4_abi_cost_v1.json'
EXACT_ALP = 'results/m3-alp-m4-exact-20261120-r1/anchor.json'
ARMS = ('direct', 'framework')
LIVES = ('cold', 'steady_reset')
DIRECTIONS = ('encode', 'decode')
STAGES = ('prepare', 'result_ready', 'release', 'destroy')
COUNTS = ('new_calls', 'new_bytes', 'memcpy_calls', 'memcpy_bytes')
CODE = ('src/tsbench/application/m4_abi_cost.py', 'src/tsbench/supervisor/m4_abi_cost.py', 'tools/m4_abi_cost.py',
        'src/tsbench/corpus_ingress.py', 'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py',
        'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/supervisor/process.py',
        'native/measurement/m4_abi_cost/main.cpp', 'native/measurement/m4_abi_cost/CMakeLists.txt',
        'native/runtime/plugin_loader.cpp', 'native/runtime/plugin_loader.hpp', 'include/tsbench/plugin_abi.h')
POLICY = {
    'scope': 'same pristine public ABI and artifact-ready typed output; same loader outside the native clocks',
    'context': 'cold=create; steady_reset=one untimed same-direction operation and release, then timed reset',
    'paired': 'one independent isolated process per direction/arm; seeded within-pair order; no outlier deletion',
    'output': 'detached decode sees fixed frame and the separately declared typed schema, not original V',
    'counts': 'separate executable; its wall clocks are null. Only host out-of-line operator new/memcpy are observable',
    'process_wall': 'supervised exit including startup, input read, validation of ABI view, and serialization; no fsync',
    'cache': 'tied to logical shape and host cache geometry, not measured cache residency; inherited cache state',
    'on_failure': 'abort with stderr and incomplete raw evidence; no success seal or omission of failed sample',
    'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False,
}


def _geometry(config, entries, env):
    require(set(config) == {'schema', 'seed', 'measured_rounds', 'cases'} and config['schema'] == 'bmk.m4-abi-identical-work-control/1' and
            type(config['seed']) is int and 3 <= config['measured_rounds'] <= 15, 'invalid multiscale experiment policy')
    result = []
    caches = {c['level']: c['bytes'] for c in env['cache_topology'] if c['kind'] == 'Unified'}
    for c in config['cases']:
        require(re.fullmatch(r'[a-z0-9-]+', c['id']) and c['id'] not in {x['id'] for x in result} and
                c['plugins'] and len(set(c['plugins'])) == len(c['plugins']) and set(c['plugins']) <= launcher.MODULES.keys(), 'invalid M4 case or codec set')
        entry = entries[c['dataset']]
        lo, hi = c['rows']
        col = c['column']
        require(type(lo) is int and type(hi) is int and 0 <= lo < hi <= entry['rows'] and
                (col is None or (type(col) is int and 0 <= col < entry['value_count'])), 'invalid M4 case source projection')
        n = (hi - lo) * (entry['value_count'] if col is None else 1) * 8
        if 'zstd' in c['plugins'] or 'xz-baseline' in c['plugins']:
            require(n <= 65536, 'do not turn a batch ABI rejection into a timing case')
        ceiling = n + 65536 if c['regime'] == 'logical_input_exceeds_llc' else launcher.LIMITS['file_bytes']
        require(n < launcher.RAW_FILE_CEILING and ceiling <= launcher.RAW_FILE_CEILING, 'M4 input or output exceeds tool capacity')
        if c['regime'] == 'logical_shape_inside_l2':
            require(3 * (n + 65536) < caches[2], 'small raw-store nominal shape does not fit in L2')
        if c['regime'] == 'logical_input_exceeds_llc':
            require(c['plugins'] == ['raw-store'] and col is None and n > caches[max(caches)] and n >= 8 << 20,
                    'large raw-store nominal shape does not exceed shared LLC or is not portable to its isolation limit')
        else:
            require(n < ceiling, 'normal M4 ABI source exceeds isolated output budget')
        result.append({**c, 'logical_bytes': n, 'dtype': 2 if col is None else 10, 'count': n if col is None else hi - lo,
                       'ceiling': ceiling, 'source_file': entry['file'], 'canonical_object_id': entry['canonical']['object_id']})
    return result


def _stage(root, entries, cases, folder):
    folder.mkdir(parents=True, exist_ok=False)
    by_data = defaultdict(list)
    for c in cases:
        by_data[c['dataset']].append(c)
    for dataset, group in by_data.items():
        entry = entries[dataset]
        data = {c['id']: bytearray() for c in group}
        stride = entry['value_count'] * 8
        for batch in read_batches(root, entry):
            for c in group:
                lo = max(0, c['rows'][0] - batch.start)
                hi = min(batch.rows, c['rows'][1] - batch.start)
                if lo >= hi:
                    continue
                if c['column'] is None:
                    data[c['id']].extend(batch.values[lo * stride:hi * stride])
                else:
                    off = c['column'] * 8
                    data[c['id']].extend(b''.join(batch.values[i * stride + off:i * stride + off + 8] for i in range(lo, hi)))
        for c in group:
            source = data.pop(c['id'])
            require(len(source) == c['logical_bytes'], 'M4 projected source byte extent differs')
            sub = folder / c['id']
            sub.mkdir()
            (sub / 'values').write_bytes(source)
            schema = {'role': 'value', 'dtype': 'f64', 'rows': c['count']} if c['dtype'] == 10 else {'role': 'bytes', 'dtype': 'u8', 'bytes': c['count']}
            (sub / 'schema').write_bytes(canonical_bytes(schema))


def _schedule(config, cases):
    rng = Random(config['seed'])
    n = 0
    for c in cases:
        for plugin in c['plugins']:
            for lifecycle in LIVES:
                for phase, rounds, mode in [('warmup', 1, 'timing_only'), ('measured', config['measured_rounds'], 'timing_only'), ('counted', 1, 'counted')]:
                    for i in range(1, rounds + 1):
                        for direction in rng.sample(DIRECTIONS, 2):
                            for arm in rng.sample(ARMS, 2):
                                n += 1
                                yield {'slot': f'{n:05d}', 'case': c['id'], 'plugin': plugin, 'lifecycle': lifecycle, 'direction': direction,
                                       'phase': phase, 'mode': mode, 'round': i, 'arm': arm}


def _derive(root, source, build, cpu, inputs, *, stage=False):
    plan = load_json(source)
    _identity(plan, 'plan_content_id')
    ref = plan['build']['lock']
    locked = load_json(_file(root, ref))
    require(locked['build_id'] == plan['build']['build_id'], 'M4 shared M3 build lock differs')
    config = load_json(local_file(root, CONFIG))
    env = resource.environment(cpu)
    entries = _entry_map(root, load_json(_file(root, plan['definition']['plan'])))
    cases = _geometry(config, entries, env)
    if stage:
        _stage(root, entries, cases, inputs)
    for c in cases:
        c['inputs'] = {name: _ref(root, local_file(inputs, f"{c['id']}/{name}")) for name in ('schema', 'values')}
    expected = load_json(local_file(root, EXACT_ALP))
    exact, = (c for c in cases if c['id'] == 'alp-exact-profile')
    require(expected['geometry'] == {'column': exact['column'], 'row_range': exact['rows']} and
            all(artifact(_file(root, exact['inputs'][local])) == expected['original'][remote] for local, remote in [('values', 'raw'), ('schema', 'schema')]),
            'M4 selected ALP profile anchor is not the same raw unit or schema')
    _file(root, expected['frame'])
    tools = {k: _ref(root, local_file(build, name)) for k, name in launcher.TOOLS.items()}
    runtime = plan_recovery(root, locked, {p: {'plugin': p, 'options': {}} for p in launcher.MODULES},
                            tools={k: {i: v[i] for i in ('path', 'sha256')} for k, v in tools.items()})
    body = {'schema': SCHEMA, 'policy': POLICY, 'm3_plan': _ref(root, source), 'build_lock': ref, 'build': build.relative_to(root).as_posix(),
            'input_directory': inputs.relative_to(root).as_posix(), 'config': _ref(root, local_file(root, CONFIG)), 'recipe': config,
            'cases': cases, 'slot_count': sum(1 for _ in _schedule(config, cases)), 'environment': env, 'runtime': runtime,
            'exact_alp': {'evidence': _ref(root, local_file(root, EXACT_ALP)), 'frame': expected['frame'],
                          'decode_execution_info': expected['restores']['falp-auto']['native']},
            'tools': tools, 'launchers': launcher_lock(), 'code': [_ref(root, local_file(root, n)) for n in CODE]}
    return {**body, 'plan_content_id': content_id(body)}


def freeze(root, source, build, cpu, inputs):
    require(inputs.is_relative_to(root) and inputs.parent.is_dir(), 'M4 input staging must stay in project')
    return _derive(root, source, build, cpu, inputs, stage=True)


def _validate(plan, c, t, row, mounts, output, seen):
    doc, p = row['native'], row['process']
    require(all(row[k] == v for k, v in t.items()) and row['output'] == output and p['input_mounts'] == mounts and
            p['operation'] == 'cost' and p['status'] == 'completed' and p['returncode'] == 0 and p['reason'] == '' and
            re.fullmatch(r'[0-9a-f]{32}', p['session_id']) and p['session_id'] not in seen and
            type(p['process_wall_ns']) is int and p['process_wall_ns'] > 0 and p['pid'] > 0 and p['child_usage']['maxrss_bytes'] > 0 and
            all(type(v) is int and v >= 0 for v in p['child_usage'].values()), 'M4 ABI paired isolated execution or extent differs')
    seen.add(p['session_id'])
    warm = int(t['lifecycle'] == 'steady_reset')
    require(all(doc[k] == t[k] for k in ('arm', 'lifecycle', 'direction')) and doc['cpu_endpoints'] == [plan['environment']['cpu']] * 2 and
            doc['logical_bytes'] == c['logical_bytes'] and doc['input_bytes'] == mounts['object']['bytes'] and
            doc['output_bytes'] == output['bytes'] <= doc['capacity_bytes'] and
            doc['protocol'] == {'create': 1, 'reset': warm, 'warmup': warm, 'operation': 1, 'measured_output_release': 1, 'info': 1, 'destroy': 1},
            'M4 ABI public operation, lifecycle or output ownership extent differs')
    info = doc['execution_info']
    require(info['operation'] == t['direction'] and info['mode'] == 'batch' and info['threads'] == 1,
            'unexpected native mode, direction or effective threads')
    if t['direction'] == 'decode' and t['case'] == 'alp-exact-profile':
        require(info == plan['exact_alp']['decode_execution_info'], 'M4 did not repeat the exact associated fused decode work')
    counted = t['mode'] == 'counted'
    for stage in STAGES:
        x = doc[stage]
        if counted:
            require(x['wall_ns'] is None and set(x['counts']) == set(COUNTS) and
                    all(type(n) is int and n >= 0 for n in x['counts'].values()), 'M4 counter-only arm contains timing or wrong counts')
        else:
            require(x['counts'] is None and type(x['wall_ns']) is int and 0 < x['wall_ns'] <= p['process_wall_ns'],
                    'M4 timing-only arm contains counts or invalid clock')
    if counted:
        require(doc['result_ready']['counts']['new_calls'] == int(t['arm'] == 'framework'), 'M4 same-work holder allocation mismatch')
    else:
        require(sum(doc[s]['wall_ns'] for s in STAGES) <= p['process_wall_ns'], 'M4 ABI clocks extend beyond process clock')


def _call(run, plan, c, t, place, source, schema):
    place.mkdir(parents=True)
    folder, proc = launcher.run(run / 'runtime', plan['runtime'], place, t['plugin'], t['mode'], t['arm'], t['lifecycle'],
                                t['direction'], {'object': source, 'schema': schema}, c['count'], c['dtype'], c['ceiling'])
    stdout, stderr = (local_file(place, f'cost.{ext}') for ext in ('stdout', 'stderr'))
    logs = [_ref(run, stdout), _ref(run, stderr)]
    if proc['status'] != 'completed' or stderr.stat().st_size or {q.name for q in folder.iterdir()} != {'result'}:
        write_new(place / 'failure.json', {'trial': t, 'case': c['id'], 'process': proc, 'logs': logs})
        require(False, f"M4 ABI {c['id']} {t['plugin']} {t['arm']} {t['direction']}: {proc['status']} {stderr.read_text()[:500]}")
    result = local_file(folder, 'result')
    return result, {**t, 'native': load_json(stdout), 'process': proc, 'output': artifact(result), 'logs': logs}


def _inputs(run, c):
    return {name: _file(run, {'path': f"inputs/{c['id']}/{name}", **{k: c['inputs'][name][k] for k in ('bytes', 'sha256')}})
            for name in ('values', 'schema')}


def _pair_summary(rows):
    result = {}
    for key, pairs in rows.items():
        by_round = defaultdict(dict)
        for r in pairs:
            require(r['arm'] not in by_round[r['round']], 'M4 repeated arm in paired round')
            by_round[r['round']][r['arm']] = r
        require(all(set(pair) == set(ARMS) for pair in by_round.values()), 'M4 unpaired round')
        def distribution(values):
            return {'n_independent_pairs': len(values), 'min': min(values), 'median': median(values), 'max': max(values)}
        if key[-1] == 'measured':
            summary = {}
            for stage in STAGES + ('process_wall',):
                def sample(row):
                    return row['process']['process_wall_ns'] if stage == 'process_wall' else row['native'][stage]['wall_ns']
                a, b = ([sample(p[arm]) for p in by_round.values()] for arm in ARMS)
                summary[stage] = {'direct_ns': distribution(a), 'framework_ns': distribution(b),
                                  'paired_framework_minus_direct_ns': distribution([y - x for x, y in zip(a, b, strict=True)])}
        else:
            summary = {arm: {stage: rp[arm]['native'][stage]['counts'] for stage in STAGES}
                       for rp in by_round.values() for arm in ARMS}
        result.setdefault('/'.join(key[:-1]), {})[key[-1]] = summary
    return result


def _report(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY, 'unknown M4 ABI plan')
    cases = {c['id']: c for c in plan['cases']}
    inputs = {c['id']: {k: artifact(v) for k, v in _inputs(run, c).items()} for c in cases.values()}
    frames = load_json(local_file(run, 'anchors.json'))
    want = {f'{c["id"]}/{p}' for c in cases.values() for p in c['plugins']}
    require(set(frames) == want, 'M4 fixed decode anchor inventory differs')
    for key, a in frames.items():
        require(a['path'] == f'anchors/{key}.bmk', 'M4 unexpected fixed frame path')
        _file(run, a)
    require(artifact(_file(run, frames['alp-exact-profile/alp-auto'])) == {k: plan['exact_alp']['frame'][k] for k in ('bytes', 'sha256')},
            'M4 exact ALP fixed frame differs from associated M3 artifact')
    groups, info, seen = defaultdict(list), {}, set()
    with local_file(run, 'trials.jsonl').open(encoding='utf-8') as f:
        for t in _schedule(plan['recipe'], plan['cases']):
            r = parse_json(next(f, ''), 'M4 ABI trial')
            c = cases[t['case']]
            inputs_id = inputs[c['id']]
            frame = {k: frames[f"{t['case']}/{t['plugin']}"][k] for k in ('bytes', 'sha256')}
            enc = t['direction'] == 'encode'
            _validate(plan, c, t, r, {'object': inputs_id['values'] if enc else frame, 'schema': inputs_id['schema']},
                      frame if enc else inputs_id['values'], seen)
            names = [f"trials/{t['slot']}/cost.{s}" for s in ('stdout', 'stderr')]
            require([ref['path'] for ref in r['logs']] == names and r['logs'][1]['bytes'] == 0, 'M4 trial log extent differs')
            stdout, _ = (_file(run, ref) for ref in r['logs'])
            require(load_json(stdout) == r['native'], 'M4 raw ABI observation differs')
            key = tuple(t[k] for k in ('case', 'plugin', 'lifecycle', 'direction'))
            observed = r['native']['execution_info']
            require(info.setdefault('/'.join(key), observed) == observed, 'M4 paired effective backend/work changed between arms')
            if t['phase'] != 'warmup':
                groups[key + (t['phase'],)].append(r)
        require(next(f, None) is None and len(seen) == plan['slot_count'], 'M4 extra or missing ABI trial populations')
    env = load_json(local_file(run, 'environment.json'))
    require(set(env) == {'before', 'after'} and all(e['affinity'] == [plan['environment']['cpu']] for e in env.values()),
            'M4 ABI trial environment is not pinned as declared')
    return {'schema': 'bmk.m4-abi-identical-work-report/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'trials': len(seen), 'cases': plan['cases'], 'frame_inventory': frames, 'execution_info': info, 'pairs': _pair_summary(groups),
            'environment': env, 'policy': POLICY,
            'codec_allocation_copy_and_hardware_cache_counters': None, 'timing_admitted': False, 'stage_accepted': False}


def execute(root, plan, output):
    cpu = plan['environment']['cpu']
    require(output.is_relative_to(root) and plan == _derive(root, _file(root, plan['m3_plan']), root / plan['build'], cpu, root / plan['input_directory']),
            'M4 ABI execution binding differs from planned work')
    with resource.reserve(), _affinity([cpu]):
        output.mkdir(parents=True, exist_ok=True)
        require(shutil.disk_usage(output).free > (300 << 20) and os.statvfs(output).f_favail > 20000, 'insufficient M4 ABI observation storage')
        run = output / uuid4().hex
        run.mkdir()
        (run / 'trials').mkdir()
        write_new(run / 'plan.json', plan)
        stage_recovery(root, run, plan['runtime'], directory='runtime')
        cases = {c['id']: c for c in plan['cases']}
        inputs, frames, seen = {}, {}, set()
        for c in cases.values():
            target = run / 'inputs' / c['id']
            target.mkdir(parents=True)
            for name, ref in c['inputs'].items():
                shutil.copyfile(_file(root, ref), target / name)
            inputs[c['id']] = _inputs(run, c)
            for plugin in c['plugins']:
                key = f"{c['id']}/{plugin}"
                frame = run / 'anchors' / (key + '.bmk')
                frame.parent.mkdir(parents=True, exist_ok=True)
                if c['id'] == 'alp-exact-profile':
                    shutil.copyfile(_file(root, plan['exact_alp']['frame']), frame)
                else:
                    t = {'plugin': plugin, 'arm': 'direct', 'mode': 'timing_only', 'lifecycle': 'cold', 'direction': 'encode'}
                    product, _ = _call(run, plan, c, t, run / 'prepare' / c['id'] / plugin, inputs[c['id']]['values'], inputs[c['id']]['schema'])
                    product.replace(frame)
                frames[key] = _ref(run, frame)
        write_new(run / 'anchors.json', frames)
        def observe():
            return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)), 'cpu_observation': resource.observe(cpu)}

        before = observe()
        with (run / 'trials.jsonl').open('xb') as out:
            for t in _schedule(plan['recipe'], plan['cases']):
                c = cases[t['case']]
                v = inputs[c['id']]
                f = local_file(run, frames[f"{c['id']}/{t['plugin']}"]['path'])
                enc = t['direction'] == 'encode'
                source, expected = (v['values'], f) if enc else (f, v['values'])
                product, row = _call(run, plan, c, t, run / 'trials' / t['slot'], source, v['schema'])
                _validate(plan, c, t, row, {'object': artifact(source), 'schema': artifact(v['schema'])}, artifact(expected), seen)
                _line(out, row)
                product.unlink()
        write_new(run / 'environment.json', {'before': before, 'after': observe()})
        write_new(run / 'report.json', _report(run, plan))
        files = [_ref(run, run / n) for n in ('plan.json', 'trials.jsonl', 'report.json', 'anchors.json', 'environment.json')]
        seal = {'schema': SEAL, 'run_id': run.name, 'plan_content_id': plan['plan_content_id'], 'files': files}
        write_new(run / 'completion.json', {**seal, 'seal_id': content_id(seal)})
        return run


def verify(run):
    seal = load_json(local_file(run, 'completion.json'))
    _identity(seal, 'seal_id')
    require(seal['schema'] == SEAL and seal['run_id'] == run.name and [r['path'] for r in seal['files']] ==
            ['plan.json', 'trials.jsonl', 'report.json', 'anchors.json', 'environment.json'], 'invalid M4 ABI completion inventory')
    for ref in seal['files']:
        _file(run, ref)
    plan = load_json(local_file(run, 'plan.json'))
    require(seal['plan_content_id'] == plan['plan_content_id'], 'M4 ABI completion plan differs')
    report = _report(run, plan)
    require(report == load_json(local_file(run, 'report.json')), 'M4 ABI report differs from recomputation')
    return report
