"""Matched, non-ranking native profile passes and replay from one sealed ledger."""
from collections import Counter
from hashlib import sha256, shake_256
import os
from pathlib import Path, PurePosixPath
import random
import re
import shutil
from statistics import median
import struct
import tempfile
import uuid

from ..analysis.trace import summarize_trace
from ..assets import (ContractError, canonical_bytes, content_id, digest, load_json, local_file,
                      parse_json, relative_parts, require, verify_asset)
from ..contracts import compile_contract
from ..supervisor.process import invoke
from ..supervisor.timing_resource import PRLIMIT, reserve
from .smoke import _line, _publish, _ref, _rows, write_new

ROUTES = ('alp-fused', 'zstd-mt', 'xz-opaque')
PASSES = ('timing_only', 'trace_off', 'profiled')
DIRECTIONS = ('encode', 'decode')
ROUNDS, SEED, CAP = 3, 20261119, 128
DRIVER = 'tsbench_profile_driver'
LIBS = ('plugins/codecs/alp-auto/libalp_native.so', 'plugins/codecs/zstd/liblzbench_native.so')
OVERLAY = ('trace-overlay/codec.cpp', 'trace-overlay/zstdmt_compress.c')
SCHEMA = 'trace.schema.json'
PROTOCOL = ('CMakeLists.txt', 'cmake/trace-profile.cmake', 'tools/prepare_trace_overlay.py',
            'include/tsbench/trace_api.h', 'native/tracing/collector.cpp', 'native/tracing/collector.hpp',
            'native/measurement/profile_driver.cpp', 'src/tsbench/analysis/trace.py', 'src/tsbench/application/profiling.py',
            'src/tsbench/supervisor/process.py', 'src/tsbench/supervisor/timing_resource.py')


def original(route):
    if route == 'alp-fused':
        return struct.pack('<8192d', *((i % 161 - 80) / 10 for i in range(8192)))
    if route == 'zstd-mt':
        return shake_256(b'tsbench-zstd-matched-profile/1').digest((5 << 20) + 617)
    require(route == 'xz-opaque', 'unknown profile route')
    return bytes((i // 19 + i % 29 * 7) % 256 for i in range(32768))


def _schedule():
    rng = random.Random(SEED)
    rows = [(case, r, mode, CAP if mode == 'profiled' else 0)
            for case in ROUTES for r in range(1, ROUNDS + 1) for mode in rng.sample(PASSES, len(PASSES))]
    rows.append(('alp-fused', 0, 'profiled', 2))
    return [{'slot': f'p{n:02d}', 'case': case, 'round': r, 'mode': mode, 'capacity': cap}
            for n, (case, r, mode, cap) in enumerate(rows, 1)]


def _artifacts(dirs):
    paths = {}
    for mode, names in [('plain', (DRIVER, *LIBS)), ('profile', (DRIVER, *LIBS, 'libtsbench_trace.so', *OVERLAY))]:
        directory = PurePosixPath(*relative_parts(dirs[mode]))
        paths[mode] = {name: (directory / name).as_posix() for name in names}
    return paths


def plan_profile(root: Path, plain: str, profiled: str):
    require(plain != profiled, 'profile control requires two distinct build directories')
    builds = {'plain': plain, 'profile': profiled}
    refs = {mode: {name: {'path': path, 'sha256': digest(local_file(root, path))} for name, path in paths.items()}
            for mode, paths in _artifacts(builds).items()}
    inputs = {case: {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
              for case in ROUTES for raw in [original(case)]}
    source_lock = load_json(local_file(root, 'third_party/sources.lock.json'))
    native_archives = {name: source_lock['sources'][name]['archive'] for name in ('alp-native', 'lzbench-native')}
    schema = load_json(local_file(root, 'schemas/' + SCHEMA))
    body = {'schema': 'bmk.native-profile-plan/1', 'builds': builds, 'artifacts': refs, 'inputs': inputs,
            'schema_id': compile_contract('trace', schema).document_id,
            'native_archives': native_archives,
            'code': {name: digest(local_file(root, name)) for name in PROTOCOL},
            'prlimit_sha256': digest(Path(PRLIMIT)), 'schedule': _schedule(), 'seed': SEED,
            'allowed_cpus': sorted(os.sched_getaffinity(0)),
            'extent': 'prepare_native_operation_cleanup_write_and_close_not_input_read_or_external_verify',
            'formal_performance': False, 'qualification_granted': False}
    return {**body, 'plan_content_id': content_id(body)}


def _snapshot(path):
    require(path.stat().st_size <= (1 << 20), 'profile output exceeds metadata bound')
    return parse_json(path.read_text(encoding='utf-8'), 'native profile observation')


def _stage(root, work, plan):
    result = {}
    for mode, assets in plan['artifacts'].items():
        place = work / mode
        place.mkdir()
        for name, ref in assets.items():
            src = verify_asset(root, ref)
            if name in OVERLAY:
                continue
            dest = place / src.name
            shutil.copy2(src, dest)
            require(digest(dest) == ref['sha256'], 'profile ELF staging differs')
        result[mode] = place
    return result


def _call(work, logs, plan, trial, case, op, filename, src, dst, binaries, cancelled):
    n = plan['inputs'][case]['bytes']
    argv = [PRLIMIT, '--core=0:0', '--as=536870912:536870912', '--fsize=8388608:8388608', '--',
            binaries / DRIVER, trial['mode'], case, op, str(n), src, dst, str(trial['capacity'])]
    return invoke(argv, work, logs, filename, 10, cancelled,
                  environment={'LC_ALL': 'C', 'LD_LIBRARY_PATH': str(binaries)},
                  observe_process=True, capture_usage=True)


def run_profile(root: Path, plan, *, cancelled=lambda: False):
    root = root.resolve(strict=True)
    with reserve():
        require(plan == plan_profile(root, plan['builds']['plain'], plan['builds']['profile']), 'stale native profile plan')
        out = root / 'results'
        require(not out.is_symlink(), 'profile results root is a symlink')
        out.mkdir(exist_ok=True)
        run = out / uuid.uuid4().hex
        run.mkdir(mode=0o700)
        logs = run / 'logs'
        logs.mkdir()
        products = run / 'frames'
        products.mkdir()
        for name, data in [('plan.json', plan), (SCHEMA, load_json(local_file(root, 'schemas/' + SCHEMA)))]:
            write_new(run / name, data)
        with tempfile.TemporaryDirectory(prefix='.profile-work-', dir=run) as tmp, (run / 'trials.jsonl').open('xb') as ledger:
            work = Path(tmp)
            programs = _stage(root, work, plan)
            for case in ROUTES:
                (work / case).write_bytes(original(case))
            for trial in plan['schedule']:
                case, sid = trial['case'], trial['slot']
                bin_dir = programs['plain' if trial['mode'] == 'timing_only' else 'profile']
                artifact, dst = products / (sid + '.native'), work / (sid + '.restored')
                enc = _call(work, logs, plan, trial, case, 'encode', sid + '-encode', work / case, artifact, bin_dir, cancelled)
                ops = [enc]
                frame = _ref(run, artifact) if artifact.is_file() else None
                restored = None
                status = enc['status']
                if status == 'completed' and frame is not None and frame['bytes'] > 0:
                    dec = _call(work, logs, plan, trial, case, 'decode', sid + '-decode', artifact, dst, bin_dir, cancelled)
                    ops.append(dec)
                    status = dec['status']
                    if status == 'completed' and dst.is_file():
                        restored = {'bytes': dst.stat().st_size, 'sha256': digest(dst)}
                        if restored == plan['inputs'][case] and dst.read_bytes() == (work / case).read_bytes():
                            status = 'verified'
                if status == 'completed':
                    status = 'validation_failed'
                _line(ledger, {'slot': sid, 'status': status, 'operations': ops, 'artifact': frame, 'restored': restored})
        evidence = [run / name for name in ('plan.json', SCHEMA, 'trials.jsonl')] + sorted(logs.iterdir()) + sorted(products.iterdir())
        body = {'schema': 'bmk.native-profile-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': [_ref(run, path) for path in evidence]}
        write_new(run / 'completion.json', {**body, 'seal_id': content_id(body)})
        return report_profile(root, run.name)


def _cycles(obs, active):
    row = obs['cycles']
    require(row.keys() == {'scope', 'status', 'value', 'errno'} and row['scope'] == 'caller_thread_user_only',
            'invalid hardware counter scope')
    status = row['status']
    require((not active and status == 'disabled' and row['value'] is None and row['errno'] is None) or
            (active and status == 'unavailable' and row['value'] is None and type(row['errno']) is int and row['errno'] > 0) or
            (active and status == 'measured' and type(row['value']) is int and row['value'] >= 0 and row['errno'] is None),
            'invalid unavailable/disabled/measured cycles evidence')
    return row


def _check_native(obs, proc, direction, trial, values, frame, schema):
    case, mode, cap = trial['case'], trial['mode'], trial['capacity']
    counters = ('alp_fused_vectors', 'native_jobs', 'native_worker_threads', 'native_caller_jobs')
    require(obs.keys() == {'pid', 'pass_kind', 'wall_ns', 'input_bytes', 'output_bytes', 'trace', 'cycles', *counters} and
            obs['pid'] == proc['pid'] and obs['pass_kind'] == mode and type(obs['wall_ns']) is int and
            0 < obs['wall_ns'] <= proc['process_wall_ns'] and all(type(obs[k]) is int and obs[k] >= 0 for k in counters),
            'native profile record differs from actual launched operation')
    sizes = (values['bytes'], frame['bytes'])
    require((obs['input_bytes'], obs['output_bytes']) == (sizes if direction == 'encode' else sizes[::-1]),
            'native profile operation bytes differ from validated boundary')
    if case == 'alp-fused' and direction == 'decode':
        require(obs['alp_fused_vectors'] > 0, 'ALP did not execute explicit AVX2 fused vectors')
    else:
        require(obs['alp_fused_vectors'] == 0, 'unexpected ALP fused vectors')
    if case == 'zstd-mt' and direction == 'encode':
        require(obs['native_jobs'] > 2 and obs['native_worker_threads'] == 2 and obs['native_caller_jobs'] == 0,
                'requested Zstd did not demonstrate two actual native worker threads')
    else:
        require(all(obs[k] == 0 for k in counters[1:]), 'unexpected Zstd native jobs outside MT encode')
    active = mode == 'profiled'
    cycles = _cycles(obs, active)
    trace = obs['trace']
    summary = None
    if active:
        schema.validate(trace, 'sealed native trace snapshot')
        summary = summarize_trace(trace, cap, obs, case, direction)
        require((trial['round'] == 0) == (summary['dropped'] > 0), 'trace pressure control disagrees with lost events')
    else:
        require(trace is None, 'timing control unexpectedly recorded spans')
    visibility = ('disabled' if not active else 'opaque' if case == 'xz-opaque' else
                  'fused' if case == 'alp-fused' and direction == 'decode' else
                  'measured' if case == 'zstd-mt' and direction == 'encode' else 'not_measured')
    if active and not trial['round']:
        visibility = 'not_measured'  # the low capacity control dropped L2
    return {'direction': direction, 'operation_wall_ns': obs['wall_ns'], 'input_bytes': obs['input_bytes'],
            'output_bytes': obs['output_bytes'], 'process_usage_not_per_span': proc['child_usage'],
            'l2_visibility': visibility, 'unobserved_stage_duration_ns': None, 'trace': summary,
            'cycles': cycles, 'native_counters': {k: obs[k] for k in counters}}


def _repeats(trials):
    groups = []
    for case in ROUTES:
        for direction in DIRECTIONS:
            values = []
            for round_ in range(1, ROUNDS + 1):
                rows = [r for r in trials if r['case'] == case and r['round'] == round_ and r['status'] == 'verified']
                if len(rows) == len(PASSES):
                    times = {r['mode']: next(op['operation_wall_ns'] for op in r['observations'] if op['direction'] == direction)
                             for r in rows}
                    values.append({'round': round_, 'wall_ns': times,
                        'profiled_minus_disabled_ns': times['profiled'] - times['trace_off'],
                        'disabled_minus_pristine_ns': times['trace_off'] - times['timing_only']})
            groups.append({'case': case, 'direction': direction, 'planned_rounds': ROUNDS,
                'complete_matched_rounds': values,
                'median_profiled_minus_disabled_ns': median([x['profiled_minus_disabled_ns'] for x in values]) if values else None,
                'median_disabled_minus_pristine_ns': median([x['disabled_minus_pristine_ns'] for x in values]) if values else None})
    return groups


def read_profile(root, run_id):
    require(isinstance(run_id, str) and re.fullmatch('[0-9a-f]{32}', run_id), 'invalid profile run id')
    run = local_file(root, f'results/{run_id}/completion.json').parent
    seal = load_json(run / 'completion.json')
    require(seal['schema'] == 'bmk.native-profile-seal/1' and seal['run_id'] == run_id and
            seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}), 'invalid native profile seal')
    sealed = {r['path']: r for r in seal['files']}
    used = {'plan.json', SCHEMA, 'trials.jsonl'}
    require(len(sealed) == len(seal['files']) and used <= sealed.keys(), 'missing or duplicate profile evidence')
    for record in sealed.values():
        require(verify_asset(run, record).stat().st_size == record['bytes'], 'profile evidence size differs')
    plan = load_json(run / 'plan.json')
    require(plan['plan_content_id'] == seal['plan_content_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}) and
            plan['schedule'] == _schedule() and plan['formal_performance'] is False and plan['qualification_granted'] is False,
            'profile plan identity or matched schedule differs')
    require(plan['inputs'] == {case: {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}
                for case in ROUTES for raw in [original(case)]}, 'profile plan input identity differs')
    schema = compile_contract('trace', load_json(run / SCHEMA))
    require(schema.document_id == plan['schema_id'], 'trace schema snapshot differs')
    records = _rows(run / 'trials.jsonl')
    require(len(records) == len(plan['schedule']), 'incomplete profile trial ledger')
    seen, frames, measurements = set(), {}, []
    for trial, record in zip(plan['schedule'], records, strict=True):
        sid, case = trial['slot'], trial['case']
        artifact, state, operations = record['artifact'], record['status'], record['operations']
        require(record['slot'] == sid and 1 <= len(operations) <= 2, 'invalid profile trial slot')
        if artifact is not None:
            path = f'frames/{sid}.native'
            require(artifact == sealed.get(path), 'profile frame not sealed to trial')
            used.add(path)
        if len(operations) == 2:
            require(operations[0]['status'] == 'completed' and artifact is not None, 'decode without ordered completed encode')
        observations = []
        for op, direction in zip(operations, DIRECTIONS):
            name = f'{sid}-{direction}'
            require(op['operation'] == name, 'profile operation order differs')
            stdout, stderr = (f'logs/{name}.{ext}' for ext in ('stdout', 'stderr'))
            if op['pid'] is not None:
                require(op['session_id'] not in seen and {stdout, stderr} <= sealed.keys(), 'profile operation lacks unique session or logs')
                seen.add(op['session_id'])
            used.update({stdout, stderr} & sealed.keys())
            if state == 'verified':
                require(op['pid'] and op['status'] == 'completed' and op['returncode'] == 0 and stdout in sealed,
                        'verified profile trial requires completed native worker')
                native = _snapshot(run / stdout)
                observations.append(_check_native(native, op, direction, trial, plan['inputs'][case], artifact, schema))
        if state == 'verified':
            require(len(operations) == 2 and record['restored'] == plan['inputs'][case] and artifact['bytes'] > 0,
                    'profile trial has no bitwise recovery evidence')
            value = {k: artifact[k] for k in ('sha256', 'bytes')}
            require(frames.setdefault(case, value) == value, 'comparison arms did not produce identical native bytes')
        else:
            require(state == operations[-1]['status'] and state != 'completed' or
                    state == 'validation_failed' and operations[-1]['status'] == 'completed', 'invalid profile terminal state')
        measurements.append({**trial, 'status': state, 'observations': observations})
    require(sealed.keys() == used, 'unbound sealed profiling evidence')
    counts = dict(sorted(Counter(m['status'] for m in measurements).items()))
    return run, {'schema': 'bmk.native-profile-report/1', 'run_id': run_id, 'plan_content_id': plan['plan_content_id'],
                 'seal_id': seal['seal_id'], 'statuses': counts, 'trials': measurements, 'frame_bytes_by_case': frames,
                 'perturbation': _repeats(measurements), 'all_verified': counts == {'verified': len(measurements)},
                 'formal_performance': False, 'qualification_granted': False, 'stage_accepted': False,
                 'clock': 'std::chrono::steady_clock', 'l0_extent': plan['extent'], 'allowed_cpus': plan['allowed_cpus']}


def report_profile(root: Path, run_id: str):
    run, report = read_profile(root, run_id)
    derived = run / 'derived'
    require(not derived.is_symlink(), 'invalid derived profile directory')
    derived.mkdir(exist_ok=True)
    _publish(derived / 'report.json', report)
    return report
