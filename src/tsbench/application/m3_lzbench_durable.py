"""Source-to-verified-durable repetitions for the whole-file Zstd/XZ V routes."""
from collections import Counter, defaultdict
import filecmp
import os
import shutil
from time import monotonic_ns, process_time_ns
from uuid import uuid4

from ..assets import content_id, load_json, local_file, parse_json, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from ..supervisor.isolated_worker import launcher_lock
from .m3_lzbench_corpus_clock import (_call, _distribution, _schedule, _verify_clocks, verify as verify_native)
from .m3_lzbench_timing import _affinity, _file, _folder, _identity, _ref
from .m3_lzbench_workers import artifact
from .m3_real_corpus_execution import _entry_map, _stage_dataset
from .smoke import _line, utc, write_new

SCHEMA = 'bmk.m3-lzbench-durable-plan/1'
SEAL = 'bmk.m3-lzbench-durable-seal/1'
POLICY = {
    'role': 'whole_object_v_only_no_timestamp_output_or_export_to_source_text',
    'encode_input': 'locked text original independently opened, read, parsed, normalized and staged on each trial',
    'decode_input': 'one fixed native frame only, no original or canonical staging mounted',
    'completion': 'real file and ancestor directory fsync plus artifact_each validation, before reclamation',
    'order': 'reuse all named r2 file/route/lane/phase decisions; no post-outcome selection or frame rebuilding',
    'comparison': 'paired only within this scope; do not subtract other runs as an estimate of ingress',
    'cache': 'inherited, no eviction or host exclusivity claim',
    'reservation': resource.RESERVATION,
    'cpu': 'controller process time and wait4 isolated child user/system/RSS reported separately; no total peak-RSS inference',
    'failure': 'stop on protocol or validation failure; retain partial evidence without issuing a completion seal',
    'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False,
}
PIPELINE_CLOCKS = ('ingress_stage_wall_ns', 'ingress_validation_wall_ns', 'staged_to_synced_wall_ns',
                   'output_fsync_wall_ns', 'output_validation_wall_ns', 'verified_durable_wall_ns')
CODE = ('tools/m3_lzbench_durable.py', 'src/tsbench/application/m3_lzbench_durable.py',
        'src/tsbench/application/m3_lzbench_corpus_clock.py', 'src/tsbench/application/m3_lzbench_timing.py',
        'src/tsbench/application/m3_lzbench_workers.py', 'src/tsbench/application/m3_real_corpus_execution.py',
        'src/tsbench/supervisor/lzbench_corpus_clock.py', 'src/tsbench/supervisor/isolated_worker.py',
        'src/tsbench/supervisor/process.py', 'src/tsbench/supervisor/timing_resource.py',
        'src/tsbench/corpus_ingress.py', 'src/tsbench/recovery.py')


def freeze(root, native_run):
    """Start only from a complete independent native timing run, not from partial trials."""
    proof = verify_native(native_run)
    plan_file = local_file(native_run, 'plan.json')
    native = load_json(plan_file)
    require(proof['plan_content_id'] == native['plan_content_id'] and native['launchers'] == launcher_lock(),
            'durable pipeline source identity or isolation launcher differs')
    # Protect timing and verification paths from changes since native r2 was frozen.
    for ref in native['code']:
        _file(root, ref)
    entries = _entry_map(root, load_json(_file(root, native['definition'])))
    anchors = {}
    for case in native['cases']:
        key = case['case_id']
        entry = entries[case['dataset_id']]
        require(case['source'] == {'bytes': entry['rows'] * entry['value_count'] * 8,
                                   'sha256': entry['canonical']['values_sha256']} and
                case['canonical_object_id'] == entry['canonical']['object_id'], 'pipeline source differs from native timing')
        anchors[key] = {lane: {'path': f'cases/{key}/{lane}.frame', **v['frame']} for lane, v in case['variants'].items()}
        for frame in anchors[key].values():
            _file(native_run, frame)
    originals = {dataset: {k: entries[dataset][k] for k in ('id', 'file', 'parser', 'rows', 'value_count', 'canonical')}
                 for dataset in sorted({c['dataset_id'] for c in native['cases']})}
    body = {
        'schema': SCHEMA, 'policy': POLICY, 'native_run': native_run.relative_to(root).as_posix(),
        'native_files': [_ref(root, local_file(native_run, f)) for f in ('plan.json', 'completion.json', 'report.json')],
        'native_plan_id': native['plan_content_id'], 'runtime': native['runtime'], 'definition': native['definition'],
        'cases': native['cases'], 'conditional': native['conditional'], 'anchors': anchors, 'originals': originals,
        'launchers': native['launchers'], 'environment': native['environment'],
        'code': [_ref(root, local_file(root, name)) for name in CODE],
    }
    return {**body, 'plan_content_id': content_id(body)}


def _validate(case, trial, row, original, sessions):
    encode = trial['direction'] == 'encode'
    require(set(row) == {*trial, 'clock', 'process', 'wall_ns', 'controller_cpu_ns', 'source_original', 'output', 'logs'} and
            all(row[k] == v for k, v in trial.items()), 'durable trial differs from frozen schedule')
    require(row['source_original'] == (original['file'] if encode else None), 'wrong original source or decode read the original')
    require(type(row['controller_cpu_ns']) is int and row['controller_cpu_ns'] >= 0, 'missing durable controller CPU extent')
    timing = row['wall_ns']
    require(set(timing) == set(PIPELINE_CLOCKS), 'durable timing scope differs')
    prefix = PIPELINE_CLOCKS[:2]
    require(all((type(timing[k]) is int and timing[k] > 0) if encode else timing[k] is None for k in prefix) and
            all(type(timing[k]) is int and timing[k] > 0 for k in PIPELINE_CLOCKS[2:]) and
            sum(timing[k] or 0 for k in (*prefix, 'staged_to_synced_wall_ns', 'output_validation_wall_ns')) <= timing['verified_durable_wall_ns'],
            'durable operation wall time misses ingress, child or validation extent')
    work = {'source_to_synced_output_wall_ns': timing['staged_to_synced_wall_ns'], 'output_fsync_wall_ns': timing['output_fsync_wall_ns']}
    require(_verify_clocks(case, trial, row['clock'], row['process'], work, sessions) == row['output'],
            'durable trial bytes or native parity differs')


def _trial(root, run, plan, case, item, entry, frames, sessions):
    op, lane = item['direction'], item['lane']
    v = case['variants'][lane]
    place = run / item['path']
    place.mkdir()
    start = monotonic_ns()
    cpu_start = process_time_ns()
    ingress = ingress_check = None
    if op == 'encode':
        # The parser exhausts the original, checking SHA/row count before returning.
        stage = place / 'stage'
        stage.mkdir()
        raw, = _stage_dataset(root, entry, stage, 'v_bytes_interleaved')['paths']
        staged = monotonic_ns()
        ingress = staged - start
        require(artifact(raw) == case['source'], 'durable source canonical V differs')
        ingress_check = monotonic_ns() - staged
        source = raw
    else:
        source = frames[v['decode_anchor']]
    output, process, clock, path, logs = _call(run, plan, case, place, source, op, lane)
    validate_start = monotonic_ns()
    result = artifact(output)
    if op == 'encode':
        require(result == v['frame'] and filecmp.cmp(output, frames[lane], shallow=False), 'durable encoded artifact differs from fixed frame')
    else:
        require(result == case['source'], 'durable decoder did not reconstruct exact original-domain V bytes')
    controller_cpu = process_time_ns() - cpu_start
    validated = monotonic_ns()
    timing = {'ingress_stage_wall_ns': ingress, 'ingress_validation_wall_ns': ingress_check,
              'staged_to_synced_wall_ns': path['source_to_synced_output_wall_ns'], 'output_fsync_wall_ns': path['output_fsync_wall_ns'],
              'output_validation_wall_ns': validated - validate_start, 'verified_durable_wall_ns': validated - start}
    row = {**item, 'clock': clock, 'process': process, 'wall_ns': timing, 'source_original': entry['file'] if op == 'encode' else None,
           'controller_cpu_ns': controller_cpu, 'output': result, 'logs': logs}
    _validate(case, item, row, entry, sessions)
    return row, output


def _summarize(case, rows):
    directions = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row['phase'] == 'measured':
            directions[row['direction']][row['lane']].append(row)
    n = case['source']['bytes']
    summary = {}
    for op, lanes in directions.items():
        summary[op] = {}
        for lane, samples in lanes.items():
            v = case['variants'][lane]
            frame = v['frame'] if op == 'encode' else case['variants'][v['decode_anchor']]['frame']
            wall = {k: (_distribution([r['wall_ns'][k] for r in samples]) if samples[0]['wall_ns'][k] is not None else None)
                    for k in PIPELINE_CLOCKS}
            summary[op][lane] = {'samples': len(samples), 'whole_v_logical_bytes': n, 'complete_native_frame': frame,
                                 'ratio': n / frame['bytes'], 'wall_ns': wall,
                                 'controller_cpu_ns': _distribution([r['controller_cpu_ns'] for r in samples]),
                                 'isolated_child': {k: _distribution([r['process']['child_usage'][k] for r in samples])
                                                    for k in ('user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes')},
                                 'controller_trial_peak_rss_bytes': None,
                                 'observed_worker_threads': _distribution([r['clock']['functional']['jobs']['worker_threads'] for r in samples]),

                                 'verified_durable_mib_per_s': _distribution([n * 1e9 / ((1 << 20) * r['wall_ns']['verified_durable_wall_ns'])
                                                                                for r in samples])}
    return {'dataset_id': case['dataset_id'], 'route': case['route'], 'work_item_id': case['work_item_id'],
            'operation_config_id': case['operation_config_id'], 'lanes': summary}


def _report(run, plan):
    _identity(plan, 'plan_content_id')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY, 'unknown durable pipeline plan')
    sessions, summary = set(), []
    with local_file(run, 'trials.jsonl').open(encoding='utf-8') as stream:
        for case in plan['cases']:
            _identity(case, 'case_id')
            rows = []
            for item in _schedule(case):
                row = parse_json(next(stream, ''), 'durable lzbench trial')
                _validate(case, item, row, plan['originals'][case['dataset_id']], sessions)
                names = [f"{item['path']}/native.{suffix}" for suffix in ('stdout', 'stderr')]
                require([r['path'] for r in row['logs']] == names and row['logs'][1]['bytes'] == 0,
                        'durable lzbench native log names or stderr differ')
                stdout, _ = (_file(run, r) for r in row['logs'])
                require(load_json(stdout) == row['clock'], 'durable report native stdout differs')
                rows.append(row)
            summary.append(_summarize(case, rows))
        require(next(stream, None) is None, 'extra durable pipeline row')
    env = load_json(local_file(run, 'environment.json'))
    cpus = [e['cpu'] for e in plan['environment']]
    require(set(env) == {'before', 'after'} and all(e['affinity'] == cpus for e in env.values()), 'durable run CPU binding differs')
    return {'schema': 'bmk.m3-lzbench-durable-report/1', 'plan_content_id': plan['plan_content_id'], 'run_id': run.name,
            'native_plan_id': plan['native_plan_id'], 'file_routes': dict(Counter(r['route'] for r in summary)),
            'conditional': dict(Counter(c['route'] for c in plan['conditional'])), 'verified_trials': len(sessions),
            'cases': summary, 'environment': env, 'policy': POLICY,
            'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False}


def execute(root, plan, output):
    native_run = _folder(root, plan['native_run'])
    require(freeze(root, native_run) == plan, 'durable plan no longer binds native reference or original assets')
    cpus = [e['cpu'] for e in plan['environment']]
    require(output.is_relative_to(root) and [resource.environment(cpu) for cpu in cpus] == plan['environment'],
            'durable run directory or CPU resource differs')
    with resource.reserve(), _affinity(cpus):
        output.mkdir(parents=True, exist_ok=True)
        require(shutil.disk_usage(output).free > (768 << 20) and os.statvfs(output).f_favail > 10000, 'durable output resources too small')
        run = output / uuid4().hex
        run.mkdir()
        write_new(run / 'plan.json', plan)
        stage_recovery(root, run, plan['runtime'], directory='runtime')
        entries = _entry_map(root, load_json(_file(root, plan['definition'])))

        def env():
            return {'utc': utc(), 'affinity': sorted(os.sched_getaffinity(0)), 'cpu_snapshots': [resource.observe(cpu) for cpu in cpus]}

        before = env()
        sessions = set()
        with (run / 'trials.jsonl').open('xb') as stream:
            for case in plan['cases']:
                (run / 'cases' / case['case_id']).mkdir(parents=True)
                frames = {lane: _file(native_run, v) for lane, v in plan['anchors'][case['case_id']].items()}
                entry = entries[case['dataset_id']]
                for item in _schedule(case):
                    row, product = _trial(root, run, plan, case, item, entry, frames, sessions)
                    _line(stream, row)  # Commit the exact verified observation before reclaiming products.
                    product.unlink()
                    product.parent.rmdir()
                    if item['direction'] == 'encode':
                        shutil.rmtree(product.parent.parent / 'stage')
        write_new(run / 'environment.json', {'before': before, 'after': env()})
        write_new(run / 'report.json', _report(run, plan))
        seal = {'schema': SEAL, 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
                'files': [_ref(run, run / name) for name in ('plan.json', 'trials.jsonl', 'environment.json', 'report.json')]}
        write_new(run / 'completion.json', {**seal, 'seal_id': content_id(seal)})
        return run


def verify(root, run):
    seal = load_json(local_file(run, 'completion.json'))
    _identity(seal, 'seal_id')
    require(seal['schema'] == SEAL and seal['run_id'] == run.name and [r['path'] for r in seal['files']] ==
            ['plan.json', 'trials.jsonl', 'environment.json', 'report.json'], 'durable pipeline seal inventory differs')
    for ref in seal['files']:
        _file(run, ref)
    plan = load_json(local_file(run, 'plan.json'))
    require(plan['plan_content_id'] == seal['plan_content_id'], 'durable pipeline plan identity differs')
    reference = _folder(root, plan['native_run'])
    rebuilt = freeze(root, reference)
    # Audit the actual frozen projection, not just internal arithmetic or self-hashes.
    require(all(plan[k] == rebuilt[k] for k in rebuilt if k not in ('code', 'plan_content_id')),
            'durable pipeline inputs differ from the complete native run')
    report = _report(run, plan)
    require(report == load_json(local_file(run, 'report.json')), 'durable pipeline report differs from raw trial recomputation')
    return report
