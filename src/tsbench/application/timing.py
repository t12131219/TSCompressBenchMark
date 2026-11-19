"""Run and replay the serial, calibrated M2 development measurement ledger."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import re
import shutil
from statistics import median
import tempfile
import time
import uuid

from ..assets import (ContractError, canonical_bytes, content_id, digest, load_json, local_file,
                      parse_json, require, verify_asset)
from ..planner.frame_batches import LANES, choose_loops, materialize, plan_frame_batches, reference_path
from ..planner.timing import build_roles, check_plan, effective_methods, protocol, schedule
from ..qualification.frame_batches import verify_frame, verify_sample
from ..supervisor import timing_resource as resource
from ..supervisor.process import invoke
from .smoke import _line, _publish, _ref, _rows, write_new

PLAN = 'plan.json'
LEDGER = 'batches.jsonl'
ENV = 'environment.json'
SEAL = 'completion.json'
DIRECTIONS = ('encode', 'decode')
UNLAUNCHED = {'dependency_failed', 'blocked_calibration', 'cancelled', 'failed'}


def _stage_method(root, work, plan, method):
    roles = build_roles(method)
    directory = work / method
    directory.mkdir()
    files = plan['artifacts']
    for key in [*(roles[lane] for lane in LANES), roles['plugin'], *roles['dependencies']]:
        src = verify_asset(root, files[key])
        dst = directory / src.name
        shutil.copy2(src, dst)
        require(digest(dst) == files[key]['sha256'], 'staged timing asset differs from build')
    return {key: directory / Path(files[roles[key]]['path']).name for key in (*LANES, 'plugin')}


def _name(index):
    return f'batch-{index:04d}'


def _state(name, state, reason):
    return {'operation': name, 'status': state, 'reason': reason,
            'pid': None, 'session_id': None, 'returncode': None}


def _sample_from_stdout(path):
    require(path.stat().st_size <= 64 * 1024, 'native timing metadata exceeds bound')
    value = parse_json(path.read_text(encoding='utf-8'), 'native timing batch')
    require(isinstance(value, dict) and 'reference_sha256' not in value, 'invalid native timing metadata')
    return value


def _execute(run, work, plan, source, binaries, group, case, lane, loops, name, previous_info, cancelled):
    cfg = plan['batches']['config']
    cpu, pol = plan['environment']['cpu'], plan['policy']
    logical = case['bytes'] + case['schema_bytes']
    out = work / 'reference.bmk'
    options = canonical_bytes(group['options']).decode('ascii')
    argv = [resource.TASKSET, '--cpu-list', str(cpu), resource.PRLIMIT,
            f"--as={pol['address_space_bytes']}:{pol['address_space_bytes']}",
            f"--fsize={pol['per_file_bytes']}:{pol['per_file_bytes']}", '--core=0:0', '--',
            binaries[lane], binaries['plugin'], group['method'], options, group['lifecycle'], '10', str(loops),
            str(cfg['warmups']), str(cfg['retention_budget_bytes']), *source, out, lane]
    logs = run / 'logs'
    obs = invoke(argv, work, logs, name, pol['timeout_seconds'], cancelled, observe_process=True, capture_usage=True)
    sample = None
    state, reason = obs['status'], obs['reason']
    info = previous_info
    try:
        if state == 'completed':
            require(out.is_file() and not out.is_symlink() and 0 < out.stat().st_size <= pol['per_file_bytes'],
                    'worker omitted bounded native timing reference')
            wire = out.read_bytes()
            verify_frame(wire, group['method'], case)
            fingerprint = sha256(wire).hexdigest()
            measured = {**_sample_from_stdout(logs / f'{name}.stdout'), 'reference_sha256': fingerprint}
            native_info = _check_sample(measured, obs, lane, group, loops, cfg, (len(wire), fingerprint), logical, cpu)
            require(previous_info is None or previous_info == native_info, 'native lane changed warmup work')
            kept = run / 'references' / reference_path(case['id'], group['method'])
            if kept.exists():
                require(kept.read_bytes() == wire, 'retained reference differs across batches, lanes or lifecycle')
            else:
                out.rename(kept)
            sample, state, info = measured, 'verified', native_info
    except (ContractError, OSError, ValueError) as exc:
        state, reason = 'validation_failed', str(exc)
    finally:
        if out.exists():
            if state == 'verified':
                out.unlink()
            else:
                out.rename(logs / f'{name}.rejected.bmk')
    return obs, sample, state, reason, info


def _check_sample(sample, obs, lane, group, loops, cfg, reference, logical, cpu):
    info = verify_sample(sample, lane, group, loops, cfg, reference, logical, {cpu})
    require(sample['pid'] == obs['pid'], 'native batch pid differs from supervised process')
    require(all(sample[key] == [cpu, cpu] for key in ('encode_cpu_endpoints', 'decode_cpu_endpoints')),
            'native clock endpoints outside pinned CPU')
    require(sum(sample[key] for key in ('encode_batch_ns', 'decode_batch_ns', 'release_ns')) <= obs['process_wall_ns'],
            'native batch durations exceed whole child wall clock')
    return info


def _loops(config, logical, pilots):
    if len(pilots) == len(LANES) and all(p is not None for p in pilots):
        try:
            return choose_loops(config, logical, pilots)
        except ContractError:
            return None
    return None


def run_timing(root: Path, plan: dict, *, cancelled=lambda: False):
    """Reserve before publishing a run; all planned batches have one terminal row."""
    root = root.resolve(strict=True)
    with resource.reserve():
        check_plan(plan)
        cpu = plan['environment']['cpu']
        require(plan['batches'] == plan_frame_batches(root) and plan['protocol'] == protocol(root) and
                plan['method_bindings'] == effective_methods(root, plan['batches']), 'stale timing plan or execution protocol')
        require(plan['environment'] == resource.environment(cpu), 'measurement resource topology or affinity changed')
        results = root / 'results'
        require(not results.is_symlink(), 'results root cannot be a symlink')
        results.mkdir(exist_ok=True)
        run = results / uuid.uuid4().hex
        run.mkdir(mode=0o700)
        for name in ('logs', 'references', 'derived'):
            (run / name).mkdir()
        write_new(run / PLAN, plan)
        cfg = plan['batches']['config']
        started = time.monotonic_ns()
        before = resource.observe(cpu)
        with tempfile.TemporaryDirectory(prefix='.timing-work-', dir=run) as scratch, (run / LEDGER).open('xb') as ledger:
            work = Path(scratch)
            cases = {c['id']: c for c in plan['batches']['cases']}
            inputs, builds = {}, {}
            for cid, case in cases.items():
                values, schema = materialize(case)
                inputs[cid] = [work / f'{cid}.f64le', work / f'{cid}.json']
                for path, blob in zip(inputs[cid], (values, schema), strict=True):
                    path.write_bytes(blob)
            index = 0
            for group in plan['batches']['groups']:
                method = group['method']
                if method not in builds:
                    try:
                        builds[method] = _stage_method(root, work, plan, method)
                    except (ContractError, OSError) as exc:
                        builds[method] = str(exc)
                case = cases[group['case']]
                pilots, info = [], None
                logical = case['bytes'] + case['schema_bytes']
                for phase, round_, lane in schedule(group):
                    index += 1
                    name = _name(index)
                    loops = 1 if phase == 'calibration' else _loops(cfg, logical, pilots)
                    sample = None
                    if loops is None:
                        proc = _state(name, 'blocked_calibration', 'matched calibration cannot produce bounded common loops')
                    elif cancelled():
                        proc = _state(name, 'cancelled', 'cancel requested before launch')
                    elif isinstance(builds[method], str):
                        proc = _state(name, 'dependency_failed', builds[method])
                    else:
                        proc, sample, status, reason, info = _execute(run, work, plan, inputs[case['id']], builds[method],
                                group, case, lane, loops, name, info, cancelled)
                    if sample is None and proc['status'] != 'completed':
                        status, reason = proc['status'], proc['reason']
                    if phase == 'calibration':
                        pilots.append(sample)
                    _line(ledger, {'group_id': group['group_id'], 'index': index, 'phase': phase, 'round': round_,
                                   'lane': lane, 'loops': loops, 'process': proc, 'status': status,
                                   'reason': reason, 'sample': sample})
        write_new(run / ENV, {'before': before, 'after': resource.observe(cpu), 'elapsed_ns': time.monotonic_ns() - started})
        files = [run / name for name in (PLAN, LEDGER, ENV)] + sorted(
            p for kind in ('logs', 'references') for p in (run / kind).iterdir())
        body = {'schema': 'bmk.timing-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': [_ref(run, p) for p in files]}
        write_new(run / SEAL, {**body, 'seal_id': content_id(body)})
        # Don't let a second submission compete with this submission's own replay.
        return report_timing(root, run.name)


def _check_process(row, name, seen, sealed):
    proc = row['process']
    base = {'operation', 'status', 'pid', 'returncode', 'session_id', 'reason'}
    require(proc['operation'] == name and isinstance(proc['reason'], str), 'invalid supervised operation identity')
    outputs = {f'logs/{name}.{suffix}' for suffix in ('stdout', 'stderr')}
    if proc['pid'] is None:
        require(proc.keys() == base and proc['returncode'] is None and proc['session_id'] is None and
                proc['status'] in UNLAUNCHED, 'unexpected unlaunched batch facts')
        opened = outputs & sealed.keys()
        require(not opened or (opened == outputs and proc['status'] in {'dependency_failed', 'failed'} and
                all(sealed[key]['bytes'] == 0 for key in opened)), 'unexpected unlaunched batch logs')
        return 0, opened
    session = proc['session_id']
    require(proc.keys() == base | {'process_wall_ns', 'child_usage'} and
            type(proc['pid']) is int and proc['pid'] > 0 and type(proc['returncode']) is int and
            type(proc['process_wall_ns']) is int and proc['process_wall_ns'] > 0 and
            isinstance(session, str) and re.fullmatch('[0-9a-f]{32}', session) and session not in seen and
            outputs <= sealed.keys(), 'incomplete launched-batch supervision facts')
    seen.add(session)
    usage = proc['child_usage']
    require(usage.keys() == {'user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes'} and
            all(type(x) is int and x >= 0 for x in usage.values()), 'invalid timing process resource usage')
    status, code = proc['status'], proc['returncode']
    require((status == 'completed' and code == 0) or (status == 'crash' and code < 0) or
            (status == 'failed' and code > 0) or status in {'cancelled', 'timeout'},
            'process terminal differs from its observed return code')
    rejected = f'logs/{name}.rejected.bmk'
    if rejected in sealed:
        require(row['status'] != 'verified', 'verified batch has a rejected reference')
        outputs.add(rejected)
    return proc['process_wall_ns'], outputs


def _summarize(group, records):
    ordered = {lane: [row for row in records if row['phase'] == 'measured' and row['lane'] == lane] for lane in LANES}
    pairs = [r for r in range(1, len(ordered[LANES[0]]) + 1)
             if all(ordered[lane][r-1]['status'] == 'verified' for lane in LANES)]
    distributions = {}
    for lane in LANES:
        good = [row['sample'] for row in ordered[lane] if row['status'] == 'verified']
        distributions[lane] = {'verified_batch_samples': len(good), 'planned_batch_samples': len(ordered[lane]),
            'verified_inner_loops_not_independent': sum(sample['loops'] for sample in good),
            'batch_median_ns': {d: median([sample[d + '_batch_ns'] for sample in good]) if good else None for d in DIRECTIONS}}
    return {'group_id': group['group_id'], 'case': group['case'], 'method': group['method'],
            'lifecycle': group['lifecycle'], 'complete_matched_rounds': pairs,
            'paired_observations': [{d: {lane: ordered[lane][r-1]['sample'][d + '_batch_ns'] for lane in LANES}
                                     for d in DIRECTIONS} | {'round': r} for r in pairs], 'lanes': distributions}


def read_report(root: Path, run_id: str):
    require(isinstance(run_id, str) and re.fullmatch('[0-9a-f]{32}', run_id), 'invalid timing run ID')
    run = local_file(root, f'results/{run_id}/{SEAL}').parent
    envelope = load_json(run / SEAL)
    require(envelope.keys() == {'schema', 'run_id', 'plan_content_id', 'files', 'seal_id'} and
            envelope['schema'] == 'bmk.timing-seal/1' and envelope['run_id'] == run_id and
            envelope['seal_id'] == content_id({k: v for k, v in envelope.items() if k != 'seal_id'}), 'invalid timing seal')
    sealed = {row['path']: row for row in envelope['files']}
    used = {PLAN, ENV, LEDGER}
    require(len(sealed) == len(envelope['files']) and used <= sealed.keys(), 'missing or duplicate timing evidence assets')
    for item in sealed.values():
        require(verify_asset(run, item).stat().st_size == item['bytes'], 'sealed timing evidence size changed')
    plan = load_json(run / PLAN)
    check_plan(plan)
    require(envelope['plan_content_id'] == plan['plan_content_id'], 'seal differs from frozen timing plan')
    rows = _rows(run / LEDGER)
    require(len(rows) == plan['planned_batches'], 'timing ledger denominator differs from plan')
    cases = {c['id']: c for c in plan['batches']['cases']}
    cfg, cpu = plan['batches']['config'], plan['environment']['cpu']
    index, groups, wall, sessions, refs = 0, [], 0, set(), {}
    for group in plan['batches']['groups']:
        case = cases[group['case']]
        logical = case['bytes'] + case['schema_bytes']
        pilots, group_records, info = [], [], None
        for phase, round_, lane in schedule(group):
            row = rows[index]
            index += 1
            loops = 1 if phase == 'calibration' else _loops(cfg, logical, pilots)
            fields = {'group_id': group['group_id'], 'index': index, 'phase': phase, 'round': round_, 'lane': lane, 'loops': loops}
            require(row.keys() == fields.keys() | {'process', 'status', 'reason', 'sample'} and
                    all(row[k] == val for k, val in fields.items()), 'timing ledger order or calibrated loops differs from plan')
            state, proc, sample, name = row['status'], row['process'], row['sample'], _name(index)
            elapsed, logs = _check_process(row, name, sessions, sealed)
            wall += elapsed
            used.update(logs)
            if loops is None:
                require(proc['status'] == 'blocked_calibration', 'uncalibrated measurement attempted')
            else:
                require(proc['status'] != 'blocked_calibration', 'calibrated batch marked calibration-blocked')
            if state == 'verified':
                require(proc['status'] == 'completed' and row['reason'] == proc['reason'] == '',
                        'verified timing row without successful supervised batch')
                path = 'references/' + reference_path(case['id'], group['method'])
                require(path in sealed, 'native timing reference is not sealed')
                used.add(path)
                if path not in refs:
                    wire = (run / path).read_bytes()
                    verify_frame(wire, group['method'], case)
                    refs[path] = len(wire), sha256(wire).hexdigest()
                require(sample == {**_sample_from_stdout(run / f'logs/{name}.stdout'), 'reference_sha256': refs[path][1]},
                        'timing observation differs from sealed native stdout')
                native = _check_sample(sample, proc, lane, group, loops, cfg, refs[path], logical, cpu)
                require(info is None or info == native, 'matched rows used different warmup work')
                info = native
            else:
                require(sample is None and isinstance(row['reason'], str) and row['reason'] and
                        (proc['status'] == 'completed' and state == 'validation_failed' or
                         state == proc['status'] and row['reason'] == proc['reason']), 'invalid failed timing row')
            if phase == 'calibration':
                pilots.append(sample)
            group_records.append(row)
        groups.append({**_summarize(group, group_records), 'calibrated_loops': _loops(cfg, logical, pilots)})
    env = load_json(run / ENV)
    require(set(sealed) == used and env.keys() == {'before', 'after', 'elapsed_ns'} and
            type(env['elapsed_ns']) is int and env['elapsed_ns'] >= wall, 'unexpected assets or invalid serial run wall clock')
    for reading in (env['before'], env['after']):
        require(reading.keys() == {'cpu_ticks', 'clock_ticks_per_second', 'sampling_freq_khz'} and
                type(reading['clock_ticks_per_second']) is int and reading['clock_ticks_per_second'] > 0 and
                (reading['sampling_freq_khz'] is None or type(reading['sampling_freq_khz']) is int and reading['sampling_freq_khz'] > 0) and
                (reading['cpu_ticks'] is None or isinstance(reading['cpu_ticks'], list) and
                 len(reading['cpu_ticks']) == 8 and all(type(x) is int and x >= 0 for x in reading['cpu_ticks'])),
                'invalid advisory host observations')
    counts = dict(sorted(Counter(row['status'] for row in rows).items()))
    return run, {'schema': 'bmk.timing-report/1', 'run_id': run_id, 'plan_content_id': plan['plan_content_id'],
            'seal_id': envelope['seal_id'], 'stage_accepted': False, 'formal_performance': False,
            'planned_batches': len(rows), 'all_batches_verified': counts == {'verified': len(rows)}, 'statuses': counts,
            'policy': plan['policy'], 'resource': plan['environment'], 'resource_observations': env,
            'serial_child_wall_ns': wall, 'independent_matched_rounds': sum(len(g['complete_matched_rounds']) for g in groups),
            'groups': groups, 'observations': rows}


def report_timing(root: Path, run_id: str):
    run, report = read_report(root, run_id)
    derived = run / 'derived'
    require(not derived.is_symlink(), 'derived directory cannot be a symlink')
    derived.mkdir(exist_ok=True)
    _publish(derived / 'report.json', report)
    return report
