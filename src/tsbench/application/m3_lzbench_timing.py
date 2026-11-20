"""Repeated isolated native lzbench sessions and XZ worker-lane observations."""
from collections import Counter
from contextlib import contextmanager
import filecmp
import os
from pathlib import Path
from random import Random
import re
import shutil
import uuid

from ..assets import content_id, digest, load_json, local_file, relative_parts, require, verify_asset
from ..planner.m3_lzbench_session import input_size as session_size
from ..planner.m3_lzbench_workers import input_size as worker_size
from ..qualification.lzbench import zstd_frame
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import invoke_isolated_tool, launcher_lock
from ..supervisor import lzbench_large_worker as large
from .m3_lzbench_session import observation
from .m3_lzbench_workers import LANES, _obs, artifact, outcome, wire_info
from .m3_metric_details import distribution
from .m3_real_corpus_execution import _entry_map, _stage_dataset
from .smoke import _line, _rows, utc, write_new

ROUTES = {'zstd-session': 'lzbench_session', 'xz-session': 'lzbench_session', 'xz-workers': 'lzbench_workers', 'zstd-workers': 'lzbench_workers'}
WARMUPS, ROUNDS, SEED = 2, 7, 20261120
DIRECTIONS = ('encode', 'decode')
LIMITS = {'address_space_bytes': 512 << 20, 'file_bytes': 8 << 20, 'wall_seconds': 30}
SCHEMA = 'bmk.m3-lzbench-session-timing-plan/1'
SEAL = 'bmk.m3-lzbench-session-timing-seal/1'
SCHEMA_V2 = 'bmk.m3-lzbench-session-timing-plan/2'
POLICY = {'warmups': WARMUPS, 'rounds': ROUNDS, 'seed': SEED, 'parallel_trials': 1,
          'task': 'whole_canonical_v_object_native_session', 'xz_worker_decode': 'all_lanes_read_same_two_worker_frame',
          'scope': 'supervised_process_tree_including_sandbox_lifecycle_and_driver_file_io_excluding_source_ingress',
          'native_operation_wall_ns': None, 'native_operation_clock_missing': 'frozen_control_has_no_whole_operation_clock',
          'first_output_scope': 'driver_loop_from_immediately_before_first_native_call_loop_includes_span_file_io',
          'affinity_scope': 'inherited_process_affinity_not_per_worker_cpu_observation',
          'cache': 'uncontrolled', 'retention': 'frozen_input_frames_and_per_trial_logs_hashes_not_all_trial_outputs'}
POLICY_V2 = {**POLICY, 'zstd_worker_decode': 'fresh_zero_worker_process_each_lane_reads_own_fixed_frame',
             'large_inputs': 'exact_output_rlimit_one_object_only_and_anchor_rebuilt_if_released'}
CODE = ('src/tsbench/application/m3_lzbench_timing.py', 'src/tsbench/application/m3_lzbench_session.py',
        'src/tsbench/application/m3_lzbench_workers.py', 'src/tsbench/application/m3_real_corpus_execution.py',
        'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/recovery.py', 'src/tsbench/supervisor/process.py',
        'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/application/m3_metric_details.py')


def _ref(root, path):
    return {'path': path.relative_to(root).as_posix(), **artifact(path)}


def _file(root, ref):
    path = verify_asset(root, ref)
    require(path.stat().st_size == ref['bytes'], 'lzbench timing asset size differs')
    return path


def _folder(root, relative):
    path = root.joinpath(*relative_parts(relative)).resolve(strict=True)
    require(path.is_dir() and path.is_relative_to(root), 'lzbench timing run is outside workspace')
    return path


def _identity(doc, key):
    require(doc[key] == content_id({k: v for k, v in doc.items() if k != key}), f'wrong lzbench timing {key}')


def _functional(plan, run):
    report, ledger = (local_file(run, name) for name in ('report.json', 'ledger.jsonl'))
    seal = load_json(local_file(run, 'completion.json'))
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'report_sha256': digest(report), 'ledger_sha256': digest(ledger)}
    require(seal == {**body, 'seal_id': content_id(body)}, 'lzbench reference functional seal differs')
    summary = load_json(report)
    require(summary['run_id'] == run.name and summary['plan_content_id'] == plan['plan_content_id'],
            'lzbench reference report identity differs')
    return seal, _rows(ledger)


def _variant(e, lane):
    if lane == 'session':
        return {'frame': e['frame'], 'retain': e['retained_frame'], 'decode_anchor': lane,
                'expected': {op: e[op] for op in DIRECTIONS}}
    enc = e['encode'][lane]
    xz = e['codec'] == 'xz'
    dec = e['decode_shared' if xz else 'decode_own'][lane]
    anchor = '2' if xz else lane
    require(dec['source_frame'] == e['encode'][anchor]['frame'], 'worker decode reference frame differs')
    return {'frame': enc['frame'], 'retain': e['retained'].get(lane), 'decode_anchor': anchor,
            'expected': {'encode': enc['observed'], 'decode': dec['observed']}, 'wire': enc['wire']}


def freeze(root, m3_plan, references, cpus, overlap=None):
    """references: (dataset ID, route, source plan path, sealed source run path)."""
    root = root.resolve(strict=True)
    m3_plan = m3_plan.resolve(strict=True)
    require(m3_plan.is_relative_to(root), 'lzbench primary plan must stay in project')
    main = load_json(m3_plan)
    _identity(main, 'plan_content_id')
    require(1 <= len(references) <= 8 and 1 <= len(cpus) <= 4 and len(set(cpus)) == len(cpus),
            'invalid lzbench timing case or CPU count')
    env = [resource.environment(cpu) for cpu in cpus]
    require(len({(e['core_id'], e['package_id']) for e in env}) == len(cpus), 'lzbench timing CPUs must be on distinct physical cores')
    overlap = _folder(root, overlap).relative_to(root).as_posix() if overlap else None
    definitions = load_json(_file(root, main['definition']['plan']))
    ingress = _entry_map(root, definitions)
    work = {(r['dataset_id'], r['route']): r for r in main['work_items']}
    rng, lookup, cases, tools, libs = Random(SEED), {}, [], {}, {}
    ordered_pairs = [(d, r) for d, r, _, _ in references]
    expanded = any(r == 'zstd-workers' for _, r in ordered_pairs)
    file_limits = large.LIMITS if expanded else LIMITS
    require(len(set(ordered_pairs)) == len(ordered_pairs), 'duplicate lzbench timing case')
    for dataset, route, src_plan, src_run in references:
        src_plan, src_run = src_plan.resolve(strict=True), src_run.resolve(strict=True)
        require(route in ROUTES and (dataset, route) in work and src_plan.is_relative_to(root) and src_run.is_relative_to(root),
                'invalid lzbench timing route or reference')
        family = ROUTES[route]
        worker = family == 'lzbench_workers'
        zstd_worker = route == 'zstd-workers'
        require(not worker or len(cpus) >= 3, 'worker timing needs capacity for caller and two workers')
        if (src_plan, src_run) not in lookup:
            old = load_json(src_plan)
            _identity(old, 'plan_content_id')
            seal, rows = _functional(old, src_run)
            lookup[src_plan, src_run] = old, seal, rows
        old, seal, rows = lookup[src_plan, src_run]
        binding = main['build'][family]
        require(binding == old['build'][family] and main['definition']['plan_content_id'] == old['definition']['plan_content_id'],
                'lzbench source and M3 route build/definition differ')
        for k in ('executable', 'dependency'):
            _file(root, binding[k])
        for rel, h in binding['code'].items():
            verify_asset(root, {'path': rel, 'sha256': h})
        item = work[dataset, route]
        matches = [r for r in rows if r.get('work_item_id') == item['work_item_id']]
        require(len(matches) == 1 and all(matches[0][k] == item[k] for k in ('dataset_id', 'route', 'applicability', 'operation'))
                and matches[0]['status'] == 'verified', 'lzbench reference lacks the verified frozen work item')
        proof = matches[0]['evidence']
        size = (worker_size if worker else session_size)(item, ingress[dataset])
        original = {'bytes': size, 'sha256': ingress[dataset]['canonical']['values_sha256']}
        budget = (large.LIMITS if zstd_worker else LIMITS)['file_bytes']
        require(proof['source'] == original and size + size // 10 + 65536 <= budget,
                'lzbench input identity or diagnostic file ceiling differs')
        require(not worker or not outcome(proof), 'historical worker observations were not met')
        lanes = LANES[proof['codec']] if worker else ('session',)
        variants = {lane: _variant(proof, lane) for lane in lanes}
        for v in variants.values():
            if zstd_worker and v['retain'] is None:
                # The source main ledger still seals the released frame's exact digest.
                continue
            require(v['retain'] is not None and set(v['retain']) == {'path', 'bytes', 'sha256'} and
                    v['frame'] == {k: v['retain'][k] for k in ('bytes', 'sha256')}, 'lzbench verified source has no retained lane frame')
            _file(src_run, v['retain'])
        tools[family] = {k: binding['executable'][k] for k in ('path', 'sha256')}
        libs[binding['dependency']['path']] = binding['dependency']
        row = {'dataset_id': dataset, 'route': route, 'codec': route.split('-')[0], 'family': family, 'source': original,
               'work_item_id': item['work_item_id'], 'operation_config_id': item['operation_config_id'], 'variants': variants,
               'scope': item['input']['row_ranges'], 'source_plan': _ref(root, src_plan), 'source_run': src_run.relative_to(root).as_posix(),
               'source_seal': seal['seal_id'], 'order': [rng.sample(lanes, len(lanes)) for _ in range(WARMUPS + ROUNDS)]}
        cases.append({**row, 'case_id': content_id(row)})
    closure = plan_recovery(root, {}, (), tools=tools, libraries=list(libs.values()))
    body = {'schema': SCHEMA_V2 if expanded else SCHEMA, 'main_plan': _ref(root, m3_plan), 'definition': main['definition']['plan'], 'cases': cases,
            'policy': POLICY_V2 if expanded else POLICY, 'limits': file_limits, 'runtime': closure, 'environment': env, 'overlap_run': overlap,
            'protocol': {'code': {n: digest(local_file(root, n)) for n in (CODE + ('src/tsbench/supervisor/lzbench_large_worker.py',) if expanded else CODE)}, 'launchers': launcher_lock()},
            'timing_admitted': False, 'qualification_granted': False}
    return {**body, 'plan_content_id': content_id(body)}


def _schedule(case):
    for i, lanes in enumerate(case['order']):
        for op in DIRECTIONS:
            for lane in lanes:
                yield {'case_id': case['case_id'], 'phase': 'warmup' if i < WARMUPS else 'measured',
                       'round': i + 1 if i < WARMUPS else i + 1 - WARMUPS, 'direction': op, 'lane': lane,
                       'path': f"cases/{case['case_id']}/{i+1:02d}-{op}-{lane}"}


@contextmanager
def _affinity(cpus):
    previous = os.sched_getaffinity(0)
    os.sched_setaffinity(0, cpus)
    try:
        require(os.sched_getaffinity(0) == set(cpus), 'lzbench timing could not pin CPU set')
        yield
    finally:
        os.sched_setaffinity(0, previous)


def _environment(root, plan):
    overlap = None
    if plan['overlap_run']:
        path = _folder(root, plan['overlap_run'])
        overlap = {'path': plan['overlap_run'], 'sealed': (path / 'completion.json').is_file(),
                   'ledger_bytes': local_file(path, 'ledger.jsonl').stat().st_size}
    return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)),
            'cpu_snapshots': [resource.observe(e['cpu']) for e in plan['environment']], 'other_functional_run': overlap}


def _verify_native(case, trial, native, proc, sessions):
    op, lane = trial['direction'], trial['lane']
    variant = case['variants'][lane]
    anchor = case['variants'][variant['decode_anchor']]['frame']
    source, product = (case['source'], variant['frame']) if op == 'encode' else (anchor, case['source'])
    require(proc['operation'] == 'native' and proc['returncode'] == 0 and proc['status'] == 'completed' and proc['reason'] == '' and
            proc['input_mounts'] == {'object': source} and type(proc['pid']) is int and proc['pid'] > 0 and
            isinstance(proc['session_id'], str) and re.fullmatch('[0-9a-f]{32}', proc['session_id']) and
            proc['session_id'] not in sessions and type(proc['process_wall_ns']) is int and proc['process_wall_ns'] > 0,
            'lzbench isolated process identity or fixed input mount differs')
    sessions.add(proc['session_id'])
    usage = proc['child_usage']
    require(set(usage) == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and usage['maxrss_bytes'] > 0 and
            all(type(v) is int and v >= 0 for v in usage.values()), 'lzbench process resource samples differ')
    expected = variant['expected'][op]
    require(native['effective_parameters'] == expected['effective_parameters'], 'lzbench effective runtime configuration differs')
    if lane == 'session':
        observation(native, source['bytes'], product['bytes'])
        require(native['jobs']['worker_threads'] == expected['jobs']['worker_threads'] and
                0 < native['first_output_driver_wall_ns'] <= proc['process_wall_ns'],
                'lzbench session first output or observed worker evidence differs')
    else:
        require(_obs(native, expected['jobs']['worker_threads'], expected['entry'], source['bytes'], product['bytes']) and
                type(native['calls']) is int and native['calls'] > 0, 'worker observed labor differs from matched configuration')
    return product


def _run_trial(run, plan, case, trial, raw, frames, sessions):
    op, lane = trial['direction'], trial['lane']
    scratch = run / trial['path']
    scratch.mkdir()
    input_path = raw if op == 'encode' else frames[case['variants'][lane]['decode_anchor']]
    n = case['source']['bytes']
    cap = n + n // 10 + 65536 if op == 'encode' else n
    if case['route'] == 'zstd-workers':
        folder, proc = large.run_zstd_worker(run / 'runtime', plan['runtime'], plan['limits'], scratch, input_path,
                                            op, lane if op == 'encode' else '0', cap, lambda: False)
    else:
        args = [case['codec'], op, *([] if lane == 'session' else [lane]), '/inputs/object', '/out/object', str(cap)]
        folder, proc = invoke_isolated_tool(run / 'runtime', plan['runtime'], case['family'], LIMITS, scratch, scratch,
                                             'native', {'object': input_path}, args, lambda: False, observe=True, file_ceiling=8 << 20)
    stdout, stderr = scratch / 'native.stdout', scratch / 'native.stderr'
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and stderr.stat().st_size == 0 and
            {p.name for p in folder.iterdir()} == {'object'}, f'lzbench isolated {lane} {op} failed: {stderr.read_text()[:500]}')
    native = load_json(stdout)
    expected = _verify_native(case, trial, native, proc, sessions)
    output = folder / 'object'
    result = artifact(output)
    require(result == expected, 'lzbench repeated output differs from frozen frame or canonical V identity')
    if op == 'encode' and not frames[lane].exists():
        require(case['route'] == 'zstd-workers' and trial['phase'] == 'warmup' and trial['round'] == 1 and
                case['variants'][lane]['retain'] is None, 'unexpected missing frozen frame')
        output.replace(frames[lane])
    else:
        require(filecmp.cmp(output, frames[lane] if op == 'encode' else raw, shallow=False),
                'lzbench repeated output differs byte for byte')
        output.unlink()
    folder.rmdir()
    return {**trial, 'native': native, 'process': proc, 'output': result, 'logs': [_ref(run, stdout), _ref(run, stderr)]}


def _summary(case, rows):
    n = case['source']['bytes']
    output = {}
    for lane, variant in case['variants'].items():
        by_op = {}
        for op in DIRECTIONS:
            repeated = [r for r in rows if r['phase'] == 'measured' and (r['lane'], r['direction']) == (lane, op)]
            require(len(repeated) == ROUNDS, 'incomplete lzbench measured sample denominator')
            clocks = {'process_wall_ns': [r['process']['process_wall_ns'] for r in repeated]}
            for key in ('user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'):
                clocks[key] = [r['process']['child_usage'][key] for r in repeated]
            first = None
            if lane == 'session':
                key = 'first_output_driver_wall_ns'
                clocks[key] = [r['native'][key] for r in repeated]
                first = {'call_ordinals': [r['native']['first_output_call'] for r in repeated],
                         'consumed_byte_counts': [r['native']['first_output_after_consumed_bytes'] for r in repeated],
                         'output_byte_counts': [r['native']['first_output_bytes'] for r in repeated]}
            workers = Counter(r['native']['jobs']['worker_threads'] for r in repeated)
            by_op[op] = {'process_mib_per_second': n * len(repeated) * 1e9 / ((1 << 20) * sum(clocks['process_wall_ns'])),
                         'distributions': {k: {**distribution(v), 'sample_basis': 'fresh_process_matched_repetitions'} for k, v in clocks.items()},
                         'native_operation_wall_ns': None, 'first_output': first,
                         'first_output_missing': None if first else 'worker_control_does_not_record_first_output',
                         'observed_background_workers': {str(k): v for k, v in workers.items()},
                         'effective_parameters': variant['expected'][op]['effective_parameters']}
        output[lane] = {'logical_bytes': n, 'complete_encode_product_bytes': variant['frame']['bytes'],
                        'shared_or_own_decode_frame_bytes': case['variants'][variant['decode_anchor']]['frame']['bytes'],
                        'compression_ratio': n / variant['frame']['bytes'], 'decode_anchor': variant['decode_anchor'],
                        'directions': by_op}
    return {'case_id': case['case_id'], **{k: case[k] for k in ('dataset_id', 'route', 'work_item_id', 'operation_config_id')},
            'units': 'whole_canonical_v_object', 'trials': len(rows), 'lanes': output}


def recompute(run, plan):
    _identity(plan, 'plan_content_id')
    expanded = any(c['route'] == 'zstd-workers' for c in plan['cases'])
    require((plan['schema'], plan['policy'], plan['limits']) ==
            ((SCHEMA_V2, POLICY_V2, large.LIMITS) if expanded else (SCHEMA, POLICY, LIMITS)) and
            plan['timing_admitted'] is False and plan['qualification_granted'] is False, 'invalid lzbench diagnostics plan')
    for name, ref in plan['runtime']['files'].items():
        _file(run, {'path': f'runtime/{name}', **{k: ref[k] for k in ('bytes', 'sha256')}})
    observations = load_json(run / 'environment.json')
    expected_affinity = sorted(e['cpu'] for e in plan['environment'])
    for snap in (observations['before'], observations['after']):
        require(snap['affinity'] == expected_affinity and len(snap['cpu_snapshots']) == len(expected_affinity) and
                (snap['other_functional_run'] or {}).get('path') == plan['overlap_run'], 'lzbench affinity or interference record differs')
    rows = iter(_rows(run / 'trials.jsonl'))
    sessions, cases = set(), []
    rng = Random(SEED)
    for case in plan['cases']:
        _identity(case, 'case_id')
        cid = case['case_id']
        lanes = LANES[case['codec']] if case['family'] == 'lzbench_workers' else ('session',)
        require(set(case['variants']) == set(lanes) and
                case['order'] == [rng.sample(lanes, len(lanes)) for _ in range(WARMUPS + ROUNDS)],
                'lzbench lane scheduler differs')
        _file(run, {'path': f'cases/{cid}/source/values/bytes.bin', **case['source']})
        for lane, v in case['variants'].items():
            frame = _file(run, {'path': f'cases/{cid}/{lane}.frame', **v['frame']})
            if case['family'] == 'lzbench_workers':
                require(wire_info(frame, case['codec'], case['source']['bytes']) == v['wire'], 'retained worker frame wire differs')
            elif case['codec'] == 'zstd':
                zstd_frame(frame.read_bytes())
        records = []
        for trial in _schedule(case):
            row = next(rows, None)
            require(row is not None and row.keys() == trial.keys() | {'native', 'process', 'output', 'logs'} and
                    all(row[k] == v for k, v in trial.items()), 'lzbench raw rows differ from matched trial schedule')
            names = [f"{trial['path']}/native.{suffix}" for suffix in ('stdout', 'stderr')]
            require([r['path'] for r in row['logs']] == names and row['logs'][1]['bytes'] == 0, 'lzbench log extent differs')
            stdout, _ = (_file(run, ref) for ref in row['logs'])
            require(load_json(stdout) == row['native'], 'lzbench raw stdout differs from observation')
            require(_verify_native(case, trial, row['native'], row['process'], sessions) == row['output'],
                    'lzbench recorded trial product differs from frozen lane result')
            records.append(row)
        cases.append(_summary(case, records))
    require(cases and next(rows, None) is None, 'unexpected extra lzbench trial or empty timing run')
    return {'schema': 'bmk.m3-lzbench-session-timing-report/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'verified_trials': len(sessions), 'cases': cases, 'environment': observations, 'policy': plan['policy'],
            'interference': 'declared_concurrent_functional_run' if plan['overlap_run'] else 'not_controlled_at_host_level',
            'timing_admitted': False, 'qualification_granted': False}


def execute(root, plan, output):
    root = root.resolve(strict=True)
    refs = [(c['dataset_id'], c['route'], _file(root, c['source_plan']), _folder(root, c['source_run'])) for c in plan['cases']]
    cpus = [e['cpu'] for e in plan['environment']]
    require(freeze(root, _file(root, plan['main_plan']), refs, cpus, plan['overlap_run']) == plan,
            'lzbench plan no longer matches its frozen functional reference')
    output = output.resolve()
    require(output.is_relative_to(root), 'lzbench timing output must stay within project')
    with resource.reserve():
        output.mkdir(parents=True, exist_ok=True)
        if plan['schema'] == SCHEMA_V2:
            sizes = sum(c['source']['bytes'] + sum(v['frame']['bytes'] for v in c['variants'].values()) for c in plan['cases'])
            require(shutil.disk_usage(output).free >= sizes + (256 << 20) and os.statvfs(output).f_favail >= 2000,
                    'insufficient space or inodes for frozen whole-object timing')
        run = output / uuid.uuid4().hex
        run.mkdir()
        write_new(run / 'plan.json', plan)
        stage_recovery(root, run, plan['runtime'], directory='runtime')
        entries = _entry_map(root, load_json(_file(root, plan['definition'])))
        prepared = []
        for case in plan['cases']:
            place = run / 'cases' / case['case_id']
            source = place / 'source'
            source.mkdir(parents=True)
            raw, = _stage_dataset(root, entries[case['dataset_id']], source, 'v_bytes_interleaved')['paths']
            require(artifact(raw) == case['source'], 'lzbench reconstructed full canonical V differs')
            frames = {}
            for lane, v in case['variants'].items():
                dest = place / f'{lane}.frame'
                if v['retain'] is not None:
                    shutil.copyfile(_file(_folder(root, case['source_run']), v['retain']), dest)
                    require(artifact(dest) == v['frame'], 'lzbench copied lane reference differs')
                frames[lane] = dest
            prepared.append((case, raw, frames))
        with _affinity(cpus), (run / 'trials.jsonl').open('xb') as stream:
            before = _environment(root, plan)
            sessions = set()
            for case, raw, frames in prepared:
                for trial in _schedule(case):
                    _line(stream, _run_trial(run, plan, case, trial, raw, frames, sessions))
            after = _environment(root, plan)
        write_new(run / 'environment.json', {'before': before, 'after': after})
        write_new(run / 'report.json', recompute(run, plan))
        body = {'schema': SEAL, 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': [_ref(run, run / n) for n in ('plan.json', 'environment.json', 'trials.jsonl', 'report.json')]}
        write_new(run / 'completion.json', {**body, 'seal_id': content_id(body)})
        return run


def verify(run):
    run = run.resolve(strict=True)
    seal = load_json(run / 'completion.json')
    _identity(seal, 'seal_id')
    require(seal['schema'] == SEAL and seal['run_id'] == run.name and [r['path'] for r in seal['files']] ==
            ['plan.json', 'environment.json', 'trials.jsonl', 'report.json'], 'invalid lzbench timing seal')
    for ref in seal['files']:
        _file(run, ref)
    plan = load_json(run / 'plan.json')
    require(plan['plan_content_id'] == seal['plan_content_id'], 'lzbench sealed plan identity differs')
    report = recompute(run, plan)
    require(report == load_json(run / 'report.json'), 'lzbench sealed report differs from recomputation')
    return report
