"""Whole-file native clocks, independently bound to the sealed M3 functional corpus."""
from collections import Counter
import filecmp
import os
from pathlib import Path
from random import Random
import shutil
from statistics import median
from time import monotonic_ns
import uuid

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..recovery import plan_recovery, stage_recovery
from ..supervisor import lzbench_corpus_clock as launcher, timing_resource as resource
from ..supervisor.isolated_worker import launcher_lock
from .m3_lzbench_timing import _affinity, _file, _folder, _identity, _ref, _variant, _verify_native
from .m3_lzbench_workers import LANES, artifact, outcome, wire_info
from .m3_real_corpus_execution import _entry_map, _stage_dataset
from .m3_sealed_ledger import full_run_rows, full_run_source
from .smoke import _line, utc, write_new

SCHEMA = 'bmk.m3-lzbench-full-native-clock-plan/1'
SEAL = 'bmk.m3-lzbench-full-native-clock-seal/1'
ROUTES = ('zstd-session', 'xz-session', 'zstd-workers', 'xz-workers')
DIRECTIONS = ('encode', 'decode')
BUCKETS = ('native_setup', 'native_process', 'native_framing', 'native_cleanup')
WARMUPS, ROUNDS, SEED = 1, 3, 263701
SOURCES = ('CMakeLists.txt', 'clock.hpp', 'session.cpp', 'workers.cpp')
CODE = ('application/m3_lzbench_corpus_clock.py', 'application/m3_lzbench_timing.py',
        'application/m3_lzbench_workers.py', 'application/m3_lzbench_session.py',
        'application/m3_real_corpus_execution.py', 'application/m3_sealed_ledger.py',
        'supervisor/lzbench_corpus_clock.py', 'supervisor/isolated_worker.py',
        'supervisor/process.py', 'supervisor/timing_resource.py', 'recovery.py')
POLICY = {
    'warmups': WARMUPS, 'rounds': ROUNDS, 'seed': SEED,
    'session_spans': {'input_bytes': 307, 'output_bytes': 521},
    'worker_spans': {'encode': {'input_bytes': 262139, 'output_bytes': 65521},
                     'decode': {'input_bytes': 1 << 20, 'output_bytes': 131071},
                     'xz_synchronous_encode': {'block_bytes': 131072, 'inner_input_bytes': 16384}},
    'decode': 'fixed own Zstd frames, own session frames, and one shared XZ worker lane-2 frame',
    'native_call_clock': 'sum of inclusive caller-wall spans, nonoverlapping; worker CPU is not summed here',
    'driver_clock': 'from validated entrypoint to final observation formatting, including file I/O and close, not fsync',
    'durable_clock': 'existing canonical or fixed frame file, launch preparation, isolated operation, output file and directory fsync',
    'cache_policy': 'inherited, no eviction claim; stage each full canonical V once; fsync and validate output before reclaim',
    'native_job_hook': 'match worker count; decode with XZ MT may report variable worker re-entry counts, not block counts',
    'reservation': resource.RESERVATION, 'exclusive_cpu': False,
    'timing_admitted': False, 'qualification_granted': False,
}


def _population(plan, ledger, source_run):
    cases, conditional = [], []
    rng = Random(SEED)
    for row, item in full_run_rows(plan, ledger):
        if row.get('entry_kind') is not None or item['route'] not in ROUTES:
            continue
        route = item['route']
        codec, family = route.split('-')
        body = {k: item[k] for k in ('dataset_id', 'route', 'work_item_id', 'operation_config_id', 'canonical_object_id')}
        if item['applicability'] == 'condition_not_triggered':
            require(family == 'workers' and row['status'] == 'condition_not_triggered', 'unexpected lzbench conditional row')
            conditional.append({**body, 'reasons': item['reasons']})
            continue
        require(item['applicability'] == 'input_domain_matches' and row['status'] == 'verified',
                'applicable lzbench reference is not verified')
        e = row['evidence']
        require(e['codec'] == codec and (family != 'workers' or not outcome(e)), 'lzbench worker reference differs')
        lanes = LANES[codec] if family == 'workers' else ('session',)
        variants = {lane: _variant(e, lane) for lane in lanes}
        for v in variants.values():
            if v['retain'] is not None:
                require(v['frame'] == {k: v['retain'][k] for k in ('bytes', 'sha256')}, 'lzbench retained reference differs')
                _file(source_run, v['retain'])
            require(0 < v['frame']['bytes'] <= launcher.FILE_CEILING, 'lzbench frame exceeds file budget')
        n = e['source']['bytes']
        require(0 < n and _encode_cap(n) <= launcher.FILE_CEILING, 'lzbench source exceeds file budget')
        body.update(codec=codec, family=family, source=e['source'], variants=variants, scope=item['input']['row_ranges'],
                    order=[rng.sample(lanes, len(lanes)) for _ in range(WARMUPS + ROUNDS)])
        cases.append({**body, 'case_id': content_id(body)})
    population = [(c['dataset_id'], c['route']) for c in cases + conditional]
    datasets = {d for d, _ in population}
    require(datasets and Counter(population) == Counter((d, r) for d in datasets for r in ROUTES),
            'lzbench population omits or duplicates a dataset/route decision')
    return cases, conditional


def freeze(root, source_plan, source_run, build, cpus):
    require(list(cpus) == sorted(set(cpus)) and len(cpus) >= 2, 'choose at least two distinct measurement CPUs')
    environment = [resource.environment(cpu) for cpu in cpus]
    require(len({(e['package_id'], e['core_id']) for e in environment}) == len(cpus), 'choose distinct physical cores')
    plan = load_json(source_plan)
    ledger, seal_id = full_run_source(plan, source_run)
    cases, conditional = _population(plan, ledger, source_run)
    bindings = [plan['build'][name] for name in ('lzbench_session', 'lzbench_workers')]
    lib = bindings[0]['dependency']
    require(bindings[1]['dependency'] == lib, 'lzbench baseline references different native libraries')
    lib_path = _file(root, lib)
    for binding in bindings:
        _file(root, binding['executable'])
        for name, sha256 in binding['code'].items():
            require(digest(local_file(root, name)) == sha256, 'lzbench frozen control code differs')
    archives = [_ref(root, local_file(lib_path.parent, 'upstream/libln_kernels.a'))]
    headers = lib_path.parent / 'source/lzbench-native'
    header_deps = [headers / 'include' / n for n in ('lzbench_extended.hpp', 'lzbench_native.h')]
    xz_api = headers / 'vendor/lzbench/lz/xz/src/liblzma/api'
    header_deps += [xz_api / 'lzma.h', *sorted((xz_api / 'lzma').glob('*.h'))]
    tools = {k: _ref(root, local_file(build, name)) for k, name in launcher.TOOLS.items()}
    closure = plan_recovery(root, {}, (), tools={k: {n: r[n] for n in ('path', 'sha256')} for k, r in tools.items()}, libraries=[lib])
    require(all('liblzbench_native.so' in closure['files'][p]['needed'] for p in closure['tools'].values()),
            'clock driver is missing the frozen lzbench library')
    body = {
        'schema': SCHEMA, 'source_plan': _ref(root, source_plan), 'source_run': source_run.relative_to(root).as_posix(),
        'source_seal': seal_id, 'definition': plan['definition']['plan'], 'build': build.relative_to(root).as_posix(),
        'cases': cases, 'conditional': conditional, 'environment': environment, 'policy': POLICY,
        'runtime': closure, 'archived_link_inputs': archives, 'headers': [_ref(root, p) for p in header_deps],
        'launchers': launcher_lock(), 'tools': tools, 'code': [_ref(root, local_file(root, n)) for n in (
            *(f'native/measurement/lzbench_corpus/{s}' for s in SOURCES), *(f'src/tsbench/{s}' for s in CODE),
            'tools/m3_lzbench_corpus_clock.py')],
    }
    return {**body, 'plan_content_id': content_id(body)}


def _encode_cap(n):
    return n + n // 10 + 65536


def _schedule(case):
    ident = case['case_id']
    for i, lanes in enumerate(case['order']):
        for op in DIRECTIONS:
            for lane in lanes:
                yield {'case_id': ident, 'phase': 'warmup' if i < WARMUPS else 'measured',
                       'round': i + 1 if i < WARMUPS else i + 1 - WARMUPS,
                       'direction': op, 'lane': lane, 'path': f'cases/{ident}/{i+1:02d}-{op}-{lane}'}


def _verify_clocks(case, trial, clocks, process, path_timing, sessions):
    direct = clocks['functional']
    op, lane = trial['direction'], trial['lane']
    expected = case['variants'][lane]['expected'][op]
    product = _verify_native(case, trial, direct, process, sessions)
    is_xz_mt_decode = case.get('codec') == 'xz' and op == 'decode' and expected['jobs']['worker_threads'] > 0
    # The vendored XZ decoder hook runs on worker entry *and* re-entry when
    # more input arrives, so its invocation count depends on scheduling.
    require(direct['jobs']['caller_jobs'] == expected['jobs']['caller_jobs'] and
            (is_xz_mt_decode or direct['jobs']['jobs'] == expected['jobs']['jobs']),
            'lzbench actual worker-hook job accounting differs from reference')
    expected_keys = {*BUCKETS, 'functional', 'driver_wall_ns', 'first_driver_output_wall_ns', 'first_driver_output_bytes'}
    require(set(clocks) == expected_keys and all(type(clocks[k]) is int for k in
            ('driver_wall_ns', 'first_driver_output_wall_ns', 'first_driver_output_bytes')) and
            0 < clocks['first_driver_output_wall_ns'] <= clocks['driver_wall_ns'] <= process['process_wall_ns'] and
            0 < clocks['first_driver_output_bytes'] <= product['bytes'], 'lzbench clock scopes or first output differ')
    for key in BUCKETS:
        bucket = clocks[key]
        require(set(bucket) == {'calls', 'wall_ns'} and all(type(v) is int and v >= 0 for v in bucket.values()) and
                (bucket['calls'] == 0) == (bucket['wall_ns'] == 0), 'lzbench native bucket differs')
    require(0 < sum(clocks[k]['wall_ns'] for k in BUCKETS) <= clocks['driver_wall_ns'], 'lzbench native call wall sum differs')
    counts = [clocks[k]['calls'] for k in BUCKETS]
    if lane == 'synchronous' and op == 'encode':
        blocks = expected['blocks']
        fallback = expected['uncompressed_fallback_blocks']
        require(direct['blocks'] == direct['calls'] == blocks and direct['uncompressed_fallback_blocks'] == fallback and
                counts[0] == blocks + 2 and counts[1] >= blocks + fallback and counts[2] == 6 + 4 * blocks - fallback and
                counts[3] == blocks + 1 and clocks['first_driver_output_bytes'] == 12, 'XZ synchronous native operation coverage differs')
    else:
        require(counts == [1 if lane == 'synchronous' else 2, direct['calls'], 0, 1] and
                (direct.get('blocks', 0), direct.get('uncompressed_fallback_blocks', 0)) == (0, 0),
                'lzbench span call accounting differs')
    if lane == 'session':
        require(direct['first_output_bytes'] == clocks['first_driver_output_bytes'] and
                direct['first_output_driver_wall_ns'] <= clocks['first_driver_output_wall_ns'], 'session first output clock differs')
    require(set(path_timing) == {'source_to_synced_output_wall_ns', 'output_fsync_wall_ns'} and
            all(type(v) is int and v > 0 for v in path_timing.values()) and process['process_wall_ns'] +
            path_timing['output_fsync_wall_ns'] <= path_timing['source_to_synced_output_wall_ns'], 'lzbench durable path clock differs')
    return product


def _fsync_output(output, stop):
    with output.open('rb') as stream:
        os.fsync(stream.fileno())
    folder = output.parent
    while folder != stop:
        fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        folder = folder.parent


def _call(run, plan, case, scratch, source, op, lane):
    cap = case['source']['bytes']
    native_lane = '0' if case['route'] == 'zstd-workers' and op == 'decode' else lane
    start = monotonic_ns()
    out, proc = launcher.run(run / 'runtime', plan['runtime'], scratch, source, case['codec'], case['family'],
                             op, native_lane, _encode_cap(cap) if op == 'encode' else cap)
    stdout, stderr = scratch / 'native.stdout', scratch / 'native.stderr'
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and stderr.stat().st_size == 0 and
            {p.name for p in out.iterdir()} == {'object'}, f"{case['dataset_id']} {case['route']} {op}/{lane}: {proc['status']} {stderr.read_text()[:500]}")
    output = out / 'object'
    require(output.is_file() and not output.is_symlink(), 'unexpected lzbench output file type')
    sync_start = monotonic_ns()
    _fsync_output(output, run.parent)
    end = monotonic_ns()
    return output, proc, load_json(stdout), {'source_to_synced_output_wall_ns': end - start,
                                            'output_fsync_wall_ns': end - sync_start}, [_ref(run, p) for p in (stdout, stderr)]


def _prepare(root, run, plan, case, raw, source_run):
    frames = {}
    for lane, v in case['variants'].items():
        dest = run / 'cases' / case['case_id'] / f'{lane}.frame'
        if v['retain'] is not None:
            shutil.copyfile(_file(source_run, v['retain']), dest)
        else:
            scratch = dest.parent / f'prepare-{lane}'
            scratch.mkdir()
            output, _, _, _, _ = _call(run, plan, case, scratch, raw, 'encode', lane)
            require(artifact(output) == v['frame'], 'released lzbench frame could not be reconstructed')
            output.replace(dest)
        require(artifact(dest) == v['frame'] and ('wire' not in v or wire_info(dest, case['codec'], case['source']['bytes']) == v['wire']),
                'lzbench anchor differs from sealed bytes or wire')
        frames[lane] = dest
    return frames


def _run_trial(run, plan, case, trial, raw, frames, sessions):
    scratch = run / trial['path']
    scratch.mkdir()
    op, lane = trial['direction'], trial['lane']
    v = case['variants'][lane]
    decode_input = frames[v['decode_anchor']]
    output, process, clocks, path_timing, logs = _call(run, plan, case, scratch, raw if op == 'encode' else decode_input, op, lane)
    wanted = _verify_clocks(case, trial, clocks, process, path_timing, sessions)
    require(artifact(output) == wanted and filecmp.cmp(output, frames[lane] if op == 'encode' else raw, shallow=False),
            'lzbench trial output differs from frozen frame or original-domain V bytes')
    output.unlink()
    output.parent.rmdir()
    return {**trial, 'native': clocks, 'process': process, 'path_timing': path_timing, 'output': wanted, 'logs': logs}


def _distribution(samples):
    return {'min': min(samples), 'median': median(samples), 'max': max(samples)}


def _report(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY, 'unexpected lzbench clock plan or policy')
    sessions, cases = set(), []
    with (run / 'trials.jsonl').open(encoding='utf-8') as stream:
        for case in plan['cases']:
            _identity(case, 'case_id')
            for lane, variant in case['variants'].items():
                require(artifact(local_file(run, f"cases/{case['case_id']}/{lane}.frame")) == variant['frame'], 'retained anchor differs')
            groups = {op: {lane: [] for lane in case['variants']} for op in DIRECTIONS}
            for trial in _schedule(case):
                row = parse_json(next(stream, ''), 'lzbench clock trial')
                require(set(row) == {*trial, 'native', 'process', 'path_timing', 'output', 'logs'} and
                        all(row[k] == v for k, v in trial.items()), 'unexpected lzbench trial schedule')
                names = [f"{trial['path']}/native.{s}" for s in ('stdout', 'stderr')]
                require([r['path'] for r in row['logs']] == names and row['logs'][1]['bytes'] == 0, 'lzbench trial log extents differ')
                stdout, _ = (_file(run, r) for r in row['logs'])
                require(load_json(stdout) == row['native'] and
                        _verify_clocks(case, trial, row['native'], row['process'], row['path_timing'], sessions) == row['output'],
                        'lzbench raw timing or recorded product differs')
                if trial['phase'] == 'measured':
                    c = row['native']
                    groups[trial['direction']][trial['lane']].append({
                        **{f'{k}_wall_ns': c[k]['wall_ns'] for k in BUCKETS},
                        'native_all_call_wall_ns': sum(c[k]['wall_ns'] for k in BUCKETS),
                        'driver_wall_ns': c['driver_wall_ns'], 'first_driver_output_wall_ns': c['first_driver_output_wall_ns'],
                        'process_wall_ns': row['process']['process_wall_ns'], **row['process']['child_usage'], **row['path_timing'],
                        **{f'native_hook_{k}': v for k, v in c['functional']['jobs'].items()},
                    })
            summaries = {}
            for op, lanes in groups.items():
                summaries[op] = {}
                for lane, rows in lanes.items():
                    distribution = {k: _distribution([r[k] for r in rows]) for k in rows[0]}
                    variant = case['variants'][lane]
                    frame = variant['frame'] if op == 'encode' else case['variants'][variant['decode_anchor']]['frame']
                    logical = case['source']['bytes']
                    summaries[op][lane] = {
                        'trials': len(rows), 'distributions': distribution, 'canonical_v_bytes': logical,
                        'full_native_frame': frame, 'logical_over_complete_native_frame': logical / frame['bytes'],
                        'payload_bytes_excluding_native_framing': None,
                        'throughput_mib_per_s': {k: _distribution([logical * 1e9 / ((1 << 20) * r[k]) for r in rows])
                                                 for k in ('native_all_call_wall_ns', 'driver_wall_ns', 'process_wall_ns',
                                                           'source_to_synced_output_wall_ns')},
                        'historical_job_hook': variant['expected'][op]['jobs'],
                    }
            cases.append({'dataset_id': case['dataset_id'], 'route': case['route'], 'case_id': case['case_id'], 'lanes': summaries})
        require(next(stream, None) is None, 'extra lzbench clock trial rows')
    return {'schema': 'bmk.m3-lzbench-full-native-clock-report/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'verified_trials': len(sessions), 'file_routes': dict(Counter(c['route'] for c in cases)),
            'conditional': dict(Counter(c['route'] for c in plan['conditional'])), 'cases': cases,
            'environment': load_json(run / 'environment.json'), 'policy': POLICY,
            'timing_admitted': False, 'qualification_granted': False}


def execute(root, plan, output):
    cpus = [e['cpu'] for e in plan['environment']]
    source_run = _folder(root, plan['source_run'])
    require(freeze(root, _file(root, plan['source_plan']), source_run, _folder(root, plan['build']), cpus) == plan,
            'lzbench clock plan differs from sealed corpus projection')
    require(output.is_relative_to(root), 'lzbench timing run must be inside workspace')
    with resource.reserve(), _affinity(cpus):
        output.mkdir(parents=True, exist_ok=True)
        run = output / uuid.uuid4().hex
        run.mkdir()
        keep = sum(sum(v['frame']['bytes'] for v in c['variants'].values()) for c in plan['cases'])
        extents = {case['dataset_id']: case['source'] for case in plan['cases']}
        require(all(case['source'] == extents[case['dataset_id']] for case in plan['cases']), 'lzbench cross-route source identity differs')
        require(shutil.disk_usage(output).free > keep + sum(v['bytes'] for v in extents.values()) + 3 * launcher.FILE_CEILING and os.statvfs(output).f_favail > 10000,
                'insufficient disk space or inodes for lzbench clock run')
        write_new(run / 'plan.json', plan)
        stage_recovery(root, run, plan['runtime'], directory='runtime')
        entries = _entry_map(root, load_json(_file(root, plan['definition'])))
        staged = {}
        for dataset, ref in extents.items():
            stage = run / 'staging' / content_id(dataset)
            stage.mkdir(parents=True)
            raw, = _stage_dataset(root, entries[dataset], stage, 'v_bytes_interleaved')['paths']
            require(artifact(raw) == ref, 'canonical V source differs from the sealed r40 bytes')
            staged[dataset] = raw
        def env():
            return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)), 'cpu_snapshots': [resource.observe(cpu) for cpu in cpus]}
        before = env()
        sessions = set()
        with (run / 'trials.jsonl').open('xb') as stream:
            for case in plan['cases']:
                target = run / 'cases' / case['case_id']
                target.mkdir(parents=True)
                raw = staged[case['dataset_id']]
                frames = _prepare(root, run, plan, case, raw, source_run)
                for trial in _schedule(case):
                    _line(stream, _run_trial(run, plan, case, trial, raw, frames, sessions))
        shutil.rmtree(run / 'staging')
        write_new(run / 'environment.json', {'before': before, 'after': env()})
        write_new(run / 'report.json', _report(run, plan))
        body = {'schema': SEAL, 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': [_ref(run, run / n) for n in ('plan.json', 'environment.json', 'trials.jsonl', 'report.json')]}
        write_new(run / 'completion.json', {**body, 'seal_id': content_id(body)})
        return run


def verify(run):
    seal = load_json(run / 'completion.json')
    _identity(seal, 'seal_id')
    require(seal['schema'] == SEAL and seal['run_id'] == run.name and [r['path'] for r in seal['files']] ==
            ['plan.json', 'environment.json', 'trials.jsonl', 'report.json'], 'invalid lzbench clock seal')
    for ref in seal['files']:
        _file(run, ref)
    plan = load_json(run / 'plan.json')
    require(seal['plan_content_id'] == plan['plan_content_id'], 'wrong sealed lzbench clock plan')
    report = _report(run, plan)
    require(report == load_json(run / 'report.json'), 'lzbench clock report differs from retained trials')
    return report
