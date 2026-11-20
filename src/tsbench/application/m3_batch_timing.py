"""Serial paired clock observations on frozen M3 case units and their raw ledger."""
from collections import Counter
from contextlib import ExitStack
from hashlib import sha256
from pathlib import Path
import shutil
from statistics import median
from tempfile import TemporaryDirectory
import time
import uuid

from ..assets import ContractError, canonical_bytes, content_id, digest, load_json, local_file, require
from ..planner.frame_batches import LANES
from ..planner.m3_batch_timing import PROFILE_EXACT, check_plan, checked_file, protocol, reference, schedule
from ..qualification.frame_batches import _SAMPLE_KEYS
from ..supervisor import timing_resource as resource
from ..supervisor.process import invoke
from .m3_real_corpus_execution import _entry_map, _stage_dataset
from .smoke import _line, _rows, write_new
from .timing import _check_process, _loops, _sample_from_stdout, _state

FILES = ('plan.json', 'environment.json', 'batches.jsonl')
DIRECTIONS = ('encode', 'decode')


def _inputs(staged, case, directory):
    original = case['original']
    byte_view = case['view'] == 'v_bytes_interleaved'
    unit = case['geometry']
    width = 1 if byte_view else 8
    with staged['paths'][unit.get('column', 0)].open('rb') as stream:
        start, end = unit['byte_range' if byte_view else 'row_range']
        stream.seek(start * width)
        raw = stream.read((end - start) * width)
    count = end - start
    schema = canonical_bytes({'role': 'bytes', 'dtype': 'u8', 'bytes': count} if byte_view else
                             {'role': 'value', 'dtype': 'f64', 'rows': count})
    require(original == {'raw': {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()},
                         'schema': {'bytes': len(schema), 'sha256': sha256(schema).hexdigest()},
                         'dtype': 2 if byte_view else 10, 'count': count}, 'M3 timing input differs from frozen unit')
    directory.mkdir()
    files = directory / 'values.bin', directory / 'schema.json'
    for p, data in zip(files, (raw, schema), strict=True):
        p.write_bytes(data)
    return files


def _stage_build(root, roles, target):
    target.mkdir()
    refs = {**roles['lanes'], **roles['project_runtime_assets']}
    copied = {}
    for name, ref in refs.items():
        data = checked_file(root, ref)
        p = target / data.name
        with data.open('rb') as source, p.open('xb') as output:
            shutil.copyfileobj(source, output)
        require(digest(p) == ref['sha256'] and p.stat().st_size == ref['bytes'], 'M3 staged timing build differs')
        p.chmod(0o500 if name in LANES else 0o400)
        copied[name] = p
    return copied


def _logical(case):
    return case['bytes']['logical_value_bytes'] + case['bytes']['schema_bytes']


def _check_sample(sample, case, group, proc, config, cpu, lane, loops):
    require(sample.keys() == _SAMPLE_KEYS and sample['lifecycle'] == group['lifecycle'] and sample['lane'] == lane and
            sample['pid'] == proc['pid'] and sample['warmups'] == config['warmups'] and
            all(type(sample[k]) is int and sample[k] == loops for k in ('loops', 'encoded_verified', 'decoded_verified')),
            'M3 native batch identity/counts differ')
    counts = ('encode_batch_ns', 'decode_batch_ns', 'release_ns')
    require(all(type(sample[k]) is int and sample[k] > 0 for k in counts) and
            sum(sample[k] for k in counts) <= proc['process_wall_ns'] and
            all(sample[k] == [cpu, cpu] for k in ('encode_cpu_endpoints', 'decode_cpu_endpoints')),
            'M3 native clock scope/CPU differs from supervised batch')
    frame, budget, logical = case['frame'], config['retention_budget_bytes'], _logical(case)
    require(sample['reference_sha256'] == frame['sha256'] and sample['frame_bytes_each'] == frame['bytes'] and
            sample['decoded_logical_and_schema_total'] == logical * loops and sample['budget_bytes'] == budget and
            frame['bytes'] * loops <= sample['frame_capacity_total'] <= budget - logical * loops - frame['bytes'],
            'M3 native byte counts/capacity differ from frozen inputs')
    require(all(sample[f'warmup_{d}_info'] == case['expected_native'][d] for d in DIRECTIONS),
            'M3 native warmup route/backend differs from functional case')


def _execute(plan, run, case, group, inputs, bins, expected, lane, loops, name, cancelled):
    work = inputs[0].parent
    output = work / 'reference.bmk'
    limits = plan['policy']
    cfg = plan['config']
    cpu = plan['environment']['cpu']
    args = [resource.TASKSET, '--cpu-list', str(cpu), resource.PRLIMIT,
            f"--as={limits['address_space_bytes']}:{limits['address_space_bytes']}",
            f"--fsize={limits['file_bytes']}:{limits['file_bytes']}", '--core=0:0', '--',
            bins[lane], bins[case['module']], case['plugin'], canonical_bytes(case['options']).decode('ascii'),
            group['lifecycle'], str(case['original']['dtype']), str(loops), str(cfg['warmups']),
            str(cfg['retention_budget_bytes']), *inputs, output, lane]
    logs = run / 'logs'
    process = invoke(args, work, logs, name, limits['timeout_seconds'], cancelled, observe_process=True, capture_usage=True)
    terminal, reason = process['status'], process['reason']
    observation = None
    try:
        if terminal == 'completed':
            require(output.is_file() and not output.is_symlink() and output.stat().st_size == len(expected) and
                    output.read_bytes() == expected and not (logs / f'{name}.stderr').stat().st_size,
                    'M3 batch did not reproduce the frozen complete frame')
            returned = {**_sample_from_stdout(logs / f'{name}.stdout'), 'reference_sha256': sha256(expected).hexdigest()}
            _check_sample(returned, case, group, process, cfg, cpu, lane, loops)
            terminal, observation = 'verified', returned
    except (ValueError, OSError, KeyError, TypeError) as exc:
        terminal, reason = 'validation_failed', str(exc)
    if output.exists():
        if terminal == 'verified':
            output.unlink()
        else:
            output.rename(logs / f'{name}.rejected.bmk')
    return terminal, reason, process, observation


def run_timing(root, plan, results, *, cancelled=lambda: False):
    check_plan(plan)
    cpu = plan['environment']['cpu']
    require(plan['protocol'] == protocol(root) and plan['environment'] == resource.environment(cpu),
            'M3 timing implementation or resource binding changed')
    functional = plan['functional']
    exact = functional.get('source_projection') == PROFILE_EXACT
    keys = ('ledger', 'anchor', 'profile_plan', 'profile_reference_seal', 'runtime_reference_seal') if exact else ('audit', 'probe')
    for key in ('plan', 'report', *keys):
        checked_file(root, functional[key])
    if not exact and 'ledger' in functional:
        checked_file(root, functional['ledger'])
    definition = load_json(checked_file(root, plan['definition']))
    entries = _entry_map(root, definition)
    cases = {c['case_id']: c for c in plan['cases']}
    results.mkdir(parents=True, exist_ok=True)
    with resource.reserve(), TemporaryDirectory(prefix='m3-paired-timing-', dir=results) as scratch, ExitStack() as stack:
        work = Path(scratch)
        build = {plugin: _stage_build(root, roles, work / plugin) for plugin, roles in plan['physical_build'].items()}
        inputs, frames, staged = {}, {}, {}
        for id_, case in cases.items():
            key = case['dataset_id'], case['view']
            if key not in staged:
                directory = Path(stack.enter_context(TemporaryDirectory(dir=work)))
                staged[key] = _stage_dataset(root, entries[key[0]], directory, key[1])
            inputs[id_] = _inputs(staged[key], case, work / id_)
            frames[id_] = checked_file(root, case['frame']).read_bytes()
        run = results / uuid.uuid4().hex
        run.mkdir(mode=0o700)
        (run / 'logs').mkdir()
        write_new(run / 'plan.json', plan)
        before, started = resource.observe(cpu), time.monotonic_ns()
        i = 0
        with (run / 'batches.jsonl').open('xb') as ledger:
            for group in plan['groups']:
                key = group['case_id']
                case = cases[key]
                pilots = []
                for phase, round_, lane in schedule(group):
                    i += 1
                    name = f'batch-{i:04d}'
                    loops = 1 if phase == 'calibration' else _loops(plan['config'], _logical(case), pilots)
                    if loops is None or cancelled():
                        status = 'blocked_calibration' if loops is None else 'cancelled'
                        reason = 'matched calibration unavailable' if loops is None else 'cancel requested before launch'
                        proc, sample = _state(name, status, reason), None
                    else:
                        status, reason, proc, sample = _execute(plan, run, case, group, inputs[key], build[case['plugin']],
                                                               frames[key], lane, loops, name, cancelled)
                    if phase == 'calibration':
                        pilots.append(sample)
                    _line(ledger, {'batch': name, 'group_id': group['group_id'], 'phase': phase, 'round': round_, 'lane': lane,
                                   'loops': loops, 'status': status, 'reason': reason, 'process': proc, 'sample': sample})
        write_new(run / 'environment.json', {'resource': plan['environment'], 'before': before, 'after': resource.observe(cpu),
                                               'measurement_loop_wall_ns': time.monotonic_ns() - started})
        files = {p.relative_to(run).as_posix(): reference(run, p)
                 for p in [*(run / name for name in FILES), *sorted((run / 'logs').iterdir())]}
        body = {'schema': 'bmk.m3-fixed-batch-timing-seal/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': files}
        write_new(run / 'completion.json', {**body, 'seal_id': content_id(body)})
    return run


def _samples(group, case, rows):
    ordered = {lane: [r for r in rows if r['phase'] == 'measured' and r['lane'] == lane] for lane in LANES}
    rounds = []
    for a, b in zip(*(ordered[lane] for lane in LANES), strict=True):
        require(a['round'] == b['round'], 'M3 timing pair ordering differs')
        if a['status'] == b['status'] == 'verified':
            rounds.append({'round': a['round'], 'loops': a['loops'], 'directions': {
                d: {r['lane']: r['sample'][d + '_batch_ns'] for r in (a, b)} for d in DIRECTIONS}})
    lanes = {}
    for lane, observed in ordered.items():
        good = [r for r in observed if r['status'] == 'verified']
        medians = {d: median(r['sample'][d + '_batch_ns'] / r['loops'] for r in good) if good else None
                   for d in DIRECTIONS}
        lanes[lane] = {'verified_batches': len(good), 'inner_loops_not_independent': sum(r['loops'] for r in good),
                       'median_native_ns_per_operation': medians,
                       'median_native_mib_s': {d: case['bytes']['logical_value_bytes'] * 1e9 / (1 << 20) / value
                                               if value else None for d, value in medians.items()},
                       'process_diagnostics': [{'round': r['round'], 'wall_ns': r['process']['process_wall_ns'],
                                                 **r['process']['child_usage']} for r in good]}
    return {'group_id': group['group_id'], 'case_id': case['case_id'], 'lifecycle': group['lifecycle'],
            'dataset_id': case['dataset_id'], 'route': case['route'], 'unit_index': case['unit_index'],
            'decode_backend': case['decode_backend'], 'bytes': case['bytes'], 'matched_rounds': rounds, 'lanes': lanes}


def report_timing(run):
    """Recompute from a sealed run without original data or execution."""
    seal = load_json(local_file(run, 'completion.json'))
    require(seal['schema'] == 'bmk.m3-fixed-batch-timing-seal/1' and seal['run_id'] == run.name and
            seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}), 'M3 timing run seal differs')
    files = seal['files']
    require(set(FILES) <= files.keys() and all(k == v['path'] for k, v in files.items()), 'M3 timing closure differs')
    for ref in files.values():
        checked_file(run, ref)
    plan, env = (load_json(run / p) for p in FILES[:2])
    check_plan(plan)
    cpu = plan['environment']['cpu']
    require(seal['plan_content_id'] == plan['plan_content_id'] and env['resource'] == plan['environment'],
            'M3 timing run plan or environment differs')
    cases = {c['case_id']: c for c in plan['cases']}
    records = _rows(run / 'batches.jsonl')
    require(len(records) == plan['expected_batches'], 'M3 timing ledger does not cover frozen schedule')
    used = set(FILES)
    sessions, groups = set(), []
    i = 0
    for group in plan['groups']:
        pilots, rows = [], []
        case = cases[group['case_id']]
        for phase, round_, lane in schedule(group):
            row = records[i]
            i += 1
            name = f'batch-{i:04d}'
            loops = 1 if phase == 'calibration' else _loops(plan['config'], _logical(case), pilots)
            require((row['batch'], row['group_id'], row['phase'], row['round'], row['lane'], row['loops']) ==
                    (name, group['group_id'], phase, round_, lane, loops), 'M3 timing row differs from frozen schedule')
            proc, sample = row['process'], row['sample']
            _, logs = _check_process(row, name, sessions, files)
            used |= logs
            state = row['status']
            if state == 'verified':
                require(loops and proc['status'] == 'completed' and not row['reason'] and
                        files[f'logs/{name}.stderr']['bytes'] == 0, 'M3 verified timing row lacks successful process facts')
                _check_sample(sample, case, group, proc, plan['config'], cpu, lane, loops)
                require(sample == {**_sample_from_stdout(run / 'logs' / f'{name}.stdout'),
                                   'reference_sha256': case['frame']['sha256']}, 'M3 timing row differs from sealed worker log')
            else:
                require(sample is None and row['reason'] and
                        (state == proc['status'] != 'completed' or state == 'validation_failed' and proc['status'] == 'completed') and
                        (state == 'blocked_calibration') == (loops is None), 'M3 timing terminal inconsistent with observations')
            if phase == 'calibration':
                pilots.append(sample)
            rows.append(row)
        groups.append(_samples(group, case, rows))
    require(used == files.keys(), 'M3 timing seal has undeclared files')
    return {'schema': 'bmk.m3-fixed-batch-timing-report/1', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'seal_id': seal['seal_id'], 'functional_seal_id': plan['functional']['seal_id'],
            'status_counts': dict(sorted(Counter(r['status'] for r in records).items())),
            'scope': 'paired_same_abi_native_dev_nonexclusive_results_not_rankable',
            'native_times': 'encode_and_decode_clocks_exclude_input_io_verification_and_result_release',
            'process_metrics': 'whole_batch_child_not_direction_specific_and_not_end_to_end_ingestion',
            'merged_repeats': False, 'performance_admitted': False, 'environment': env, 'groups': groups}
