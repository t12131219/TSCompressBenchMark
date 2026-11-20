#!/usr/bin/env python3
"""Separate file-to-result wall clocks for the exact M4 ALP diagnostic case."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
from random import Random
import sys
from tempfile import TemporaryDirectory
from time import monotonic_ns
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_batch_timing import _inputs, report_timing
from tsbench.application.m3_fixed_batch import ENCODE, _call, _identity, restore_frame
from tsbench.application.m3_metric_details import distribution
from tsbench.application.m3_real_corpus_execution import _entry_map, _stage_dataset
from tsbench.application.smoke import _line, _rows, write_new
from tsbench.assets import ContractError, content_id, load_json, local_file, require
from tsbench.planner.m3_batch_timing import PROFILE_EXACT, checked_file, reference
from tsbench.planner.m3_fixed_batch import DIRECTORY
from tsbench.supervisor import timing_resource as resource
from tsbench.supervisor.isolated_worker import launcher_lock

SCHEMA = 'bmk.m3-alp-exact-file-pipeline/1'
POLICY = {'encode_ingress': 'complete_locked_raw_file_parse_and_f64_staging_then_one_declared_column_window',
          'encode_verify': 'frame_identity_and_independent_frame_only_restore_inside_outer_clock',
          'decode_ingress': 'persisted_complete_BMK_frame_only_no_raw_source_ingress',
          'decode_verify': 'restored_output_and_schema_SHA256_vs_verified_M3_oracle_inside_outer_clock',
          'write': 'worker_output_files_then_fsync_and_parent_directory_fsync_inside_outer_clock',
          'cleanup': 'temporary_cleanup_and_ledger_write_outside', 'verification': 'artifact_each',
          'raw_input_cache': 'uncontrolled', 'independent_operations': True, 'warmups': 2, 'measured_rounds': 7,
          'host_cpu_exclusive': False, 'native_times_not_used_to_derive_pipeline_wall': True}


def _schedule():
    rng = Random(20261120)
    for i in range(POLICY['warmups'] + POLICY['measured_rounds']):
        for op in rng.sample(('encode', 'decode'), 2):
            yield {'index': i, 'phase': 'warmup' if i < POLICY['warmups'] else 'measured', 'direction': op}


def _id(body, key):
    return body[key] == content_id({k: v for k, v in body.items() if k != key})


@contextmanager
def _pinned(cpu):
    mask = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {cpu})
    try:
        yield
    finally:
        os.sched_setaffinity(0, mask)


def _sync(*paths):
    require(paths and all(p.parent == paths[0].parent for p in paths), 'pipeline outputs must share one directory')
    for p in paths:
        with p.open('rb') as f:
            os.fsync(f.fileno())
    fd = os.open(paths[0].parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _observe(root, work, bundle, binding, entry, case, frame, item, trial):
    backend = case['decode_backend']
    original, product = case['original'], {k: case['frame'][k] for k in ('bytes', 'sha256')}
    start = monotonic_ns()
    if trial['direction'] == 'encode':
        staged = _stage_dataset(root, entry, work, item['view'])
        raw, schema = _inputs(staged, case, work / 'staged')
        ready = monotonic_ns()
        out, proc, (native,) = _call(bundle, binding, 'alp-auto', backend, work / 'encode', ENCODE,
                                      {'raw': raw, 'schema': schema}, ['/inputs/schema', '/out/frame', str(original['dtype']), '/inputs/raw'],
                                      ('frame',), 1)
        wire = out / 'frame'
        _sync(wire)
        published = monotonic_ns()
        require(_identity(wire) == product, 'ALP pipeline encoded bytes differ from the exact frame')
        replay = restore_frame(bundle, binding, item, backend, work / 'verify', wire, product, original)
        require((work / 'encode' / 'encode.stderr').stat().st_size == 0 and
                (work / 'verify' / f'decode-{backend}.stderr').stat().st_size == 0, 'ALP encode verification logged errors')
        end = monotonic_ns()
        detail = {'worker': proc, 'native': native, 'output': product, 'replay': replay,
                  'parts_ns': {'ingress_and_stage': ready-start, 'supervise_encode_and_sync': published-ready,
                               'artifact_recover_and_verify': end-published}}
    else:
        replay = restore_frame(bundle, binding, item, backend, work / 'decode', frame, product, original)
        checked = monotonic_ns()
        _sync(work / 'decode' / 'out' / 'raw', work / 'decode' / 'out' / 'schema')
        require((work / 'decode' / f'decode-{backend}.stderr').stat().st_size == 0, 'ALP decode logged errors')
        end = monotonic_ns()
        detail = {'worker': replay['process'], 'native': replay['native'], 'output': replay['restored'], 'replay': None,
                  'parts_ns': {'supervise_decode_and_verify': checked-start, 'sync_checked_outputs': end-checked}}
    return {**trial, 'wall_ns': end-start, **detail}


def _validate(row, trial, case, sessions):
    def process(proc, mounts, operation):
        require(proc['input_mounts'] == mounts and proc['operation'] == operation and proc['status'] == 'completed' and
                proc['returncode'] == 0 and not proc['reason'] and proc['session_id'] and proc['session_id'] not in sessions and
                type(proc['process_wall_ns']) is int and 0 < proc['process_wall_ns'] < row['wall_ns'] and
                proc['child_usage']['maxrss_bytes'] > 0, 'ALP pipeline process, mount or nested wall identity differs')
        sessions.add(proc['session_id'])

    op = trial['direction']
    part_keys = ({'ingress_and_stage', 'supervise_encode_and_sync', 'artifact_recover_and_verify'} if op == 'encode'
                 else {'supervise_decode_and_verify', 'sync_checked_outputs'})
    parts = row['parts_ns']
    require(all(row[k] == v for k, v in trial.items()) and row['native'] == case['expected_native'][op] and
            parts.keys() == part_keys and all(type(v) is int and v > 0 for v in parts.values()) and
            row['wall_ns'] == sum(parts.values()), 'ALP pipeline trial, native backend or parent timestamps differ')
    original, frame = case['original'], {k: case['frame'][k] for k in ('bytes', 'sha256')}
    label = 'decode-' + case['decode_backend']
    if op == 'encode':
        process(row['worker'], {k: original[k] for k in ('raw', 'schema')}, 'encode')
        proof = row['replay']
        require(row['output'] == frame and proof['restored'] == original and proof['native'] == case['expected_native']['decode'] and
                row['worker']['process_wall_ns'] < parts['supervise_encode_and_sync'] and
                proof['process']['process_wall_ns'] < parts['artifact_recover_and_verify'], 'ALP pipeline encoded frame or restore differs')
        process(proof['process'], {'frame': frame}, label)
    else:
        process(row['worker'], {'frame': frame}, label)
        require(row['output'] == original and row['replay'] is None and
                row['worker']['process_wall_ns'] < parts['supervise_decode_and_verify'], 'ALP pipeline decoded bytes or extent differ')


def _report(run):
    seal = load_json(local_file(run, 'completion.json'))
    require(seal['schema'] == SCHEMA + '-seal' and seal['run_id'] == run.name and _id(seal, 'seal_id') and
            seal['files'].keys() == {'plan.json', 'trials.jsonl', 'environment.json'}, 'ALP pipeline run seal differs')
    for ref in seal['files'].values():
        checked_file(run, ref)
    plan = load_json(run / 'plan.json')
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and _id(plan, 'plan_id') and
            plan['plan_id'] == seal['plan_id'] and plan['schedule'] == list(_schedule()), 'ALP pipeline schedule differs')
    case = plan['case']
    env = load_json(run / 'environment.json')
    require(env['affinity'] == [plan['environment']['cpu']], 'ALP pipeline did not keep the selected affinity')
    seen, data = set(), {'encode': [], 'decode': []}
    for row, trial in zip(_rows(run / 'trials.jsonl'), plan['schedule'], strict=True):
        _validate(row, trial, case, seen)
        if row['phase'] == 'measured':
            data[row['direction']].append(row)
    logical = case['bytes']['logical_value_bytes']
    summary = {}
    def repeated(values):
        return {**distribution(values), 'sample_basis': 'fresh_process_per_measured_round_excludes_warmup'}

    for op, rows in data.items():
        wall = repeated([r['wall_ns'] for r in rows])
        summary[op] = {'pipeline_wall_ns': wall, 'logical_mib_s_from_outer_wall': logical * len(rows) * 1e9 / ((1 << 20) * wall['sum']),
                       'serial_parts_ns': {k: repeated([r['parts_ns'][k] for r in rows]) for k in rows[0]['parts_ns']},
                       'worker_usage_not_whole_pipeline': [r['worker']['child_usage'] for r in rows],
                       'whole_pipeline_cpu_and_peak_rss': None, 'resource_reason': 'coordinator and worker resources not combined'}
    return {'schema': SCHEMA + '-report', 'seal_id': seal['seal_id'], 'run_id': run.name, 'plan_id': plan['plan_id'],
            'functional_seal': plan['functional_seal'], 'paired_timing_seal': plan['paired_timing_seal'], 'case': case,
            'policy': POLICY, 'environment': env, 'verified_trials': len(plan['schedule']), 'isolated_child_calls': len(seen),
            'directions': summary, 'source_physical_bytes': plan['source_file']['bytes'],
            'diagnostic_only': True, 'qualification_granted': False, 'stage_accepted': False}


def run(root, paired_run, output):
    paired = report_timing(paired_run)
    p = load_json(paired_run / 'plan.json')
    base = p['functional']
    require(base['source_projection'] == PROFILE_EXACT and paired['status_counts'] == {'verified': p['expected_batches']},
            'ALP pipeline needs the successful exact-unit paired clock evidence')
    m3 = load_json(checked_file(root, base['plan']))
    ref = checked_file(root, base['ledger'])
    bundle = ref.parent / DIRECTORY
    binding = m3['build']['fixed_batch']
    require(launcher_lock() == binding['launchers'], 'ALP pipeline launchers differ')
    case, = [v for v in p['cases'] if v['decode_backend'] == 'falp-auto']
    require(case['expected_native']['decode']['backend'] == 'falp-avx2', 'ALP pipeline requires the profiled AVX2 mode')
    frame = checked_file(root, case['frame'])
    item, = [v for v in m3['work_items'] if v['work_item_id'] == case['work_item_id']]
    entry = _entry_map(root, load_json(checked_file(root, m3['definition']['plan'])))[case['dataset_id']]
    cpu = p['environment']['cpu']
    body = {'schema': SCHEMA, 'case': case, 'source_file': entry['file'], 'environment': resource.environment(cpu), 'policy': POLICY,
            'functional_seal': base['seal_id'], 'paired_timing_seal': paired['seal_id'], 'schedule': list(_schedule()),
            'verifier': reference(root, Path(__file__).resolve())}
    plan = {**body, 'plan_id': content_id(body)}
    require(output.is_relative_to(root), 'ALP pipeline output must stay in project')
    with resource.reserve():
        output.mkdir(parents=True, exist_ok=True)
        folder = output / uuid.uuid4().hex
        folder.mkdir()
        write_new(folder / 'plan.json', plan)
        sessions = set()
        with _pinned(cpu), (folder / 'trials.jsonl').open('xb') as ledger:
            before = resource.observe(cpu)
            for trial in plan['schedule']:
                with TemporaryDirectory(prefix='pipeline-', dir=folder) as tmp:
                    row = _observe(root, Path(tmp), bundle, binding, entry, case, frame, item, trial)
                    _validate(row, trial, case, sessions)
                    _line(ledger, row)
            env = {'affinity': sorted(os.sched_getaffinity(0)), 'before': before, 'after': resource.observe(cpu)}
        write_new(folder / 'environment.json', env)
        seal = {'schema': SCHEMA + '-seal', 'run_id': folder.name, 'plan_id': plan['plan_id'], 'files': {
            k: reference(folder, folder / k) for k in ('plan.json', 'trials.jsonl', 'environment.json')}}
        write_new(folder / 'completion.json', {**seal, 'seal_id': content_id(seal)})
        write_new(folder / 'report.json', _report(folder))
    return folder


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('--paired-run', type=Path, required=True)
    r.add_argument('--out', type=Path, required=True)
    v = sub.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    a = parser.parse_args()
    try:
        if a.command == 'run':
            print(run(ROOT, a.paired_run.resolve(strict=True), a.out.resolve()))
        else:
            result = _report(a.run.resolve(strict=True))
            require(load_json(a.run / 'report.json') == result, 'ALP pipeline derived report differs')
            print(f"{result['run_id']} {result['verified_trials']} verified trials")
    except (ContractError, OSError) as exc:
        parser.exit(1, f'{exc}\n')
