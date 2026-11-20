#!/usr/bin/env python3
"""Audit and repeat frozen Huff0 FEC1 frames and ETB1 shared-table variants."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
from random import Random
import sys
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from tsbench.application.m3_huff0_fec1 import frames
from tsbench.application.m3_huff0_table import binding, checked_identity, layout, stage
from tsbench.application.m3_metric_details import distribution
from tsbench.application.m3_real_corpus_execution import _entry_map
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import _line, write_new
from tsbench.assets import ContractError, content_id, digest, load_json, local_file, parse_json, require, verify_asset
from tsbench.planner.huff0 import ENVELOPE, FEC, RECORD, TABLE
from tsbench.planner.m3_huff0_fec1 import KEY as FEC1_KEY, TARGET as FEC1_TOOL
from tsbench.planner.m3_huff0_table import KEY as ETB1_KEY, STREAMS
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.supervisor import timing_resource as resource
from tsbench.supervisor.isolated_worker import invoke_isolated_tool, launcher_lock

SCHEMA = 'bmk.m3-huff0-corpus-repeats/1'
ETB1_TOOL = 'huff0-etb1'
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 8 << 20, 'wall_seconds': 60}
ROUNDS = 3
OPS = {'FEC1': ('encode', 'decode'), 'ETB1': ('train', 'encode', 'decode')}
LIFECYCLE = 'fresh_isolated_process_natural_os_cache'


def info(path):
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def relative(root, path):
    return {'path': path.relative_to(root).as_posix(), **info(path)}


def check(root, ref):
    path = verify_asset(root, ref)
    require(path.stat().st_size == ref['bytes'], 'Huff0 asset length differs')
    return path


def schedule(fmt):
    rng = Random(20261120)
    return [{'round': r, 'operation': op, 'phase': 'warmup' if r == 0 else 'measured'}
            for r in range(ROUNDS + 1) for op in rng.sample(OPS[fmt], len(OPS[fmt]))]


def freeze(root, plan_path, run, cpu):
    plan = load_json(plan_path)
    ledger, seal = full_run_source(plan, run)
    cases, excluded = [], []
    for row, item in full_run_rows(plan, ledger):
        key = (row.get('selection'), row.get('route'))
        if item is None or 'entry_kind' in row or key not in (FEC1_KEY, ETB1_KEY):
            continue
        require(row['status'] == 'verified' and not row['reason'], 'Huff0 source contains an unverified route decision')
        proof = row['evidence']
        common = {k: item[k] for k in ('dataset_id', 'work_item_id', 'canonical_object_id', 'input', 'route')}
        if key == FEC1_KEY:
            n, offset = 0, 0
            for group in proof['groups']:
                for frame in group['frames']:
                    sample = frame.get('retained')
                    if sample:
                        require(frame['frame'] == {k: sample[k] for k in ('bytes', 'sha256')},
                                'Huff0 retained FEC1 identity differs')
                        n += 1
                        row_counts = defaultdict(int)
                        for r in frame['records']:
                            row_counts[r['mode'] + '_body'] += r['body_bytes']
                        cost = {'abi_header': ENVELOPE.size, 'schema': proof['schema']['bytes'], 'fec_header': FEC.size,
                                'record_headers': RECORD.size * len(frame['records']), **row_counts}
                        require(sum(cost.values()) == frame['frame']['bytes'], 'Huff0 FEC1 sample byte charge differs')
                        cases.append({**common, 'format': 'FEC1', 'canonical_value_byte_range': [offset, offset + frame['decoded']['bytes']],
                                      'artifact': frame['frame'], 'original': frame['decoded'], 'schema': proof['schema'],
                                      'reference': relative(root, check(run, sample)), 'cost': cost, 'records': frame['records']})
                    offset += frame['decoded']['bytes']
            require(n and offset == proof['input']['bytes'], 'Huff0 FEC1 extent or retention differs')
        else:
            for streams in STREAMS:
                lane = proof['profiles'][str(streams)]
                require(lane['status'] == 'verified' and lane['recovered'] == proof['holdout'], 'Huff0 ETB1 source differs')
                if not lane['retained']:
                    excluded.append({**{k: common[k] for k in ('dataset_id', 'route', 'work_item_id')}, 'streams': streams,
                                     'reason': 'no_historical_retained_model_and_block_sequence'})
                    continue
                expected = dict(zip(('model.etb1', 'test.blocks', 'binding.json'),
                                    (lane['model'], lane['frame'], lane['binding']), strict=True))
                require(lane['retained'].keys() == expected.keys(), 'Huff0 ETB1 retained set differs')
                paths = {n: relative(root, check(run, ref)) for n, ref in lane['retained'].items()}
                require(all({k: paths[n][k] for k in value} == value for n, value in expected.items()),
                        'Huff0 ETB1 retained object identity differs')
                cost = {'model': lane['model']['bytes'], 'binding_sidecar': lane['binding']['bytes'],
                        'block_headers': TABLE.size * len(lane['blocks']),
                        'block_bodies': sum(b['body_bytes'] for b in lane['blocks'])}
                require(sum(cost.values()) == lane['complete_bytes'], 'Huff0 ETB1 billing differs')
                cases.append({**common, 'format': 'ETB1', 'streams': streams, 'training': proof['training'],
                              'original': proof['holdout'], 'artifact': expected, 'references': paths, 'cost': cost,
                              'blocks': lane['blocks'], 'native': {k: lane[k] for k in OPS['ETB1']}})
    spec = plan['build']['huff0_table']
    for k in ('executable', 'dependency'):
        check(root, spec[k])
    etb = plan_recovery(root, {}, [], tools={ETB1_TOOL: {k: spec['executable'][k] for k in ('path', 'sha256')}},
                        libraries=[spec['dependency']])
    fec = plan['build']['huff0_fec1']
    require(launcher_lock() == fec['launchers'], 'Huff0 FEC1 isolation launcher changed')
    body = {'schema': SCHEMA, 'source_plan': relative(root, plan_path), 'source_run': run.relative_to(root).as_posix(),
            'source_seal': seal, 'runtime': {'FEC1': fec['decoder'], 'ETB1': etb}, 'limits': LIMITS,
            'launchers': launcher_lock(), 'env': resource.environment(cpu), 'lifecycle': LIFECYCLE,
            'cases': [{**c, 'case_id': content_id(c)} for c in cases], 'excluded': excluded,
            'code': {name: digest(local_file(root, name)) for name in
                     ('tools/m3_huff0_corpus_repeats.py', 'src/tsbench/application/m3_sealed_ledger.py',
                      'src/tsbench/application/m3_huff0_fec1.py', 'src/tsbench/application/m3_huff0_table.py',
                      'src/tsbench/supervisor/isolated_worker.py', 'src/tsbench/supervisor/process.py',
                      'src/tsbench/supervisor/timing_resource.py', 'src/tsbench/recovery.py')}}
    return {**body, 'plan_id': content_id(body)}


def protocol(case, op):
    if case['format'] == 'FEC1':
        lib = '/runtime/lib/libbmk_huff0_reference.so'
        if op == 'encode':
            return ('raw', 'schema'), [op, lib, '/inputs/raw', '/inputs/schema', '/out/result']
        return ('frame',), [op, lib, '/inputs/frame', '/out/result']
    if op == 'train':
        return ('train',), [op, str(case['streams']), '/inputs/train', '/out/result']
    names = ('model', 'holdout' if op == 'encode' else 'blocks')
    return names, [op, *('/inputs/' + p for p in names), '/out/result']


def expected(case, op):
    if case['format'] == 'FEC1':
        frame, raw = case['artifact'], case['original']
        obs = {'frames': 1, 'input_bytes': raw['bytes'], 'frame_bytes': frame['bytes']}
        return ({'raw': raw, 'schema': case['schema']}, frame, obs) if op == 'encode' else ({'frame': frame}, raw, obs)
    art = case['artifact']
    model, blocks = art['model.etb1'], art['test.blocks']
    mounts, output = {'train': ({'train': case['training']}, model),
                      'encode': ({'model': model, 'holdout': case['original']}, blocks),
                      'decode': ({'model': model, 'blocks': blocks}, case['original'])}[op]
    return mounts, output, case['native'][op]


def invoke(run, plan, case, work, op, paths):
    names, argv = protocol(case, op)
    executable = FEC1_TOOL if case['format'] == 'FEC1' else ETB1_TOOL
    work.mkdir()
    if case['format'] == 'ETB1' and op == 'decode':
        checked_identity(paths['binding'].read_bytes(), case['streams'], info(paths['model']), info(paths['blocks']))
    out, proc = invoke_isolated_tool(run / case['format'], plan['runtime'][case['format']], executable, LIMITS,
                                     work, work, op, {n: paths[n] for n in names}, argv, lambda: False,
                                     observe=True, file_ceiling=LIMITS['file_bytes'])
    stderr = work / (op + '.stderr')
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and stderr.stat().st_size == 0 and
            {p.name for p in out.iterdir()} == {'result'},
            f"Huff0 isolated {op}: {proc['status']}: {stderr.read_text()[:300]}")
    return out / 'result', proc, load_json(work / (op + '.stdout'))


def validate(case, row, trial, seen):
    op = trial['operation']
    mounts, output, native = expected(case, op)
    p = row['process']
    require(row['case_id'] == case['case_id'] and all(row[k] == v for k, v in trial.items()) and
            row['output'] == output and row['native_observation'] == native and p['input_mounts'] == mounts and
            p['operation'] == op and p['status'] == 'completed' and p['returncode'] == 0 and not p['reason'] and
            p['session_id'] and p['session_id'] not in seen and p['pid'] > 0 and
            0 < p['process_wall_ns'] <= row['staged_supervision_wall_ns'] and p['child_usage']['maxrss_bytes'] > 0,
            'Huff0 repeat trial does not reproduce frozen mount, output, metadata or clock')
    seen.add(p['session_id'])


def prepare(run, plan, case, item, entry, work, seen):
    if case['format'] == 'FEC1':
        frame = check(ROOT, case['reference'])
        schema = work / 'schema'
        schema.write_bytes(json.dumps({'role': 'bytes', 'dtype': 'u8', 'rows': entry['rows']}, separators=(',', ':')).encode())
        require(info(schema) == case['schema'], 'Huff0 FEC1 frozen ABI schema differs')
        # Do not stage source values in (or mount them into) the initial recovery.
        paths = {'schema': schema, 'frame': frame}
    else:
        refs = {k: check(ROOT, v) for k, v in case['references'].items()}
        require(layout(refs['test.blocks'], case['streams'], case['original']['bytes']) == case['blocks'],
                'Huff0 ETB1 original block geometry differs')
        paths = {dst: refs[src] for dst, src in
                 (('model', 'model.etb1'), ('blocks', 'test.blocks'), ('binding', 'binding.json'))}
    trial = {'operation': 'decode', 'phase': 'untimed_recovery', 'round': -1}
    restored, proc, obs, wall = observe(run, plan, case, work / 'historical-recovery', trial, paths)
    recovery = observation(case, trial, proc, obs, restored, wall)
    validate(case, recovery, trial, seen)
    if case['format'] == 'FEC1':
        raw = restored.read_bytes()
        (_, parsed), = frames(frame.read_bytes(), raw, schema.read_bytes())
        require(parsed == {'frame': case['artifact'], 'decoded': case['original'], 'records': case['records']},
                'Huff0 FEC1 exact frame layout/CRC differs')
        paths['raw'] = restored
    else:
        train, holdout, tr_ref, ho_ref = stage(ROOT, item, entry, work)
        require(tr_ref == case['training'] and ho_ref == case['original'], 'Huff0 ETB1 disjoint input digest differs')
        paths.update(train=train, holdout=holdout)
    return paths, recovery


def observe(run, plan, case, work, trial, paths):
    tick = monotonic_ns()
    out, proc, meta = invoke(run, plan, case, work, trial['operation'], paths)
    identity = info(out)
    return out, proc, (meta, identity), monotonic_ns() - tick


def observation(case, trial, proc, obs, output, wall):
    del output  # The output digest was computed before the outer clock stopped.
    meta, ident = obs
    return {'case_id': case['case_id'], **trial, 'process': proc, 'native_observation': meta,
            'output': ident, 'staged_supervision_wall_ns': wall}


def summarize(case, rows):
    result = {}
    for op in OPS[case['format']]:
        measured = [r for r in rows if r['operation'] == op and r['phase'] == 'measured']
        require(len(measured) == ROUNDS, 'Huff0 direction lacks measured repetitions')
        clocks = {k: [r['process']['child_usage'][k] for r in measured] for k in ('user_cpu_ns', 'system_cpu_ns', 'maxrss_bytes')}
        clocks['isolated_process_wall_ns'] = [r['process']['process_wall_ns'] for r in measured]
        clocks['staged_supervision_wall_ns'] = [r['staged_supervision_wall_ns'] for r in measured]
        logical = case['training' if op == 'train' else 'original']['bytes']
        result[op] = {'logical_bytes': logical, 'native_wall_ns': None,
                      'repeat_distributions': {k: {**distribution(v), 'sample_basis': LIFECYCLE} for k, v in clocks.items()},
                      'isolated_process_logical_mib_per_second': logical * ROUNDS * 1e9 / (sum(clocks['isolated_process_wall_ns']) * (1 << 20))}
    return {k: case[k] for k in ('case_id', 'dataset_id', 'format', 'route', 'work_item_id')} | {
        'input_scope': {'canonical_value_byte_range': case['canonical_value_byte_range']} if case['format'] == 'FEC1' else
                       {'streams': case['streams'], 'training': case['input']['training'],
                        'holdout_row_ranges': case['input']['row_ranges'], 'columns': case['input']['value_column_range']},
        'cost': case['cost'], 'artifact_bytes': sum(case['cost'].values()),
        'ratio': case['original']['bytes'] / sum(case['cost'].values()), 'directions': result}


def verify(run):
    plan = load_json(local_file(run, 'plan.json'))
    seal = load_json(local_file(run, 'completion.json'))
    require(plan['schema'] == SCHEMA and plan['plan_id'] == content_id({k: v for k, v in plan.items() if k != 'plan_id'}) and
            plan['lifecycle'] == LIFECYCLE and plan['limits'] == LIMITS and seal['plan_id'] == plan['plan_id'] and
            seal['schema'] == SCHEMA + '-seal' and seal['run_id'] == run.name and
            seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}) and
            seal['files'].keys() == {'plan.json', 'trials.jsonl', 'environment.json'}, 'Huff0 repeat seal differs')
    for f in seal['files'].values():
        check(run, f)
    for fmt, spec in plan['runtime'].items():
        for path, ref in spec['files'].items():
            check(run, {'path': fmt + '/' + path, 'bytes': ref['bytes'], 'sha256': ref['sha256']})
    env = load_json(run / 'environment.json')
    require(env['affinity'] == [plan['env']['cpu']], 'Huff0 repeat scope affinity differs')
    results, seen = [], set()
    with (run / 'trials.jsonl').open('rb') as ledger:
        for case in plan['cases']:
            require(case['case_id'] == content_id({k: v for k, v in case.items() if k != 'case_id'}), 'Huff0 case identity differs')
            verify_row = lambda t: parse_json(ledger.readline(), 'Huff0 ' + t['phase'])
            t = {'operation': 'decode', 'phase': 'untimed_recovery', 'round': -1}
            validate(case, verify_row(t), t, seen)
            rows = []
            for t in schedule(case['format']):
                row = verify_row(t)
                validate(case, row, t, seen)
                rows.append(row)
            results.append(summarize(case, rows))
        require(not ledger.read(1), 'Huff0 repeat ledger has extra trials')
    return {'schema': SCHEMA + '-report', 'run_id': run.name, 'source_seal': plan['source_seal'], 'seal_id': seal['seal_id'],
            'results': results, 'excluded_shared_table_variants': plan['excluded'], 'isolated_calls': len(seen), 'environment': env,
            'not_measured': {'native_wall_ns': 'frozen control binaries emit identities and reuse counts but no native clock',
                             'end_to_end': 'source ingress and staging precede all timed trials; no output fsync extent',
                             'allocation': 'single CPU affinity and cooperative lock, not OS exclusivity'},
            'timing_admitted': False, 'qualification_granted': False, 'stage_accepted': False}


def execute(plan, output):
    source = local_file(ROOT, plan['source_plan']['path'])
    source_run = (ROOT / plan['source_run']).resolve(strict=True)
    cpu = plan['env']['cpu']
    require(output.is_relative_to(ROOT) and source_run.is_relative_to(ROOT) and
            freeze(ROOT, source, source_run, cpu) == plan, 'Huff0 plan, source assets or host changed')
    owner = load_json(source)
    entries = _entry_map(ROOT, load_json(check(ROOT, owner['definition']['plan'])))
    items = {i['work_item_id']: i for i in owner['work_items']}
    output.mkdir(parents=True, exist_ok=True)
    with resource.reserve():
        run = output / uuid4().hex
        run.mkdir()
        write_new(run / 'plan.json', plan)
        for fmt, spec in plan['runtime'].items():
            stage_recovery(ROOT, run, spec, directory=fmt)
        seen, affinity = set(), os.sched_getaffinity(0)
        try:
            os.sched_setaffinity(0, {cpu})
            env = {'affinity': sorted(os.sched_getaffinity(0)), 'before': resource.observe(cpu)}
            with (run / 'trials.jsonl').open('xb') as ledger:
                for case in plan['cases']:
                    with TemporaryDirectory(prefix='huff0-', dir=run) as temp:
                        work = Path(temp)
                        paths, recovery = prepare(run, plan, case, items[case['work_item_id']], entries[case['dataset_id']], work, seen)
                        _line(ledger, recovery)
                        for i, t in enumerate(schedule(case['format'])):
                            out, proc, obs, wall = observe(run, plan, case, work / str(i), t, paths)
                            row = observation(case, t, proc, obs, out, wall)
                            validate(case, row, t, seen)
                            _line(ledger, row)
            env['after'] = resource.observe(cpu)
        finally:
            os.sched_setaffinity(0, affinity)
        write_new(run / 'environment.json', env)
        seal = {'schema': SCHEMA + '-seal', 'run_id': run.name, 'plan_id': plan['plan_id'],
                'files': {name: relative(run, run / name) for name in ('plan.json', 'trials.jsonl', 'environment.json')}}
        write_new(run / 'completion.json', {**seal, 'seal_id': content_id(seal)})
    write_new(run / 'report.json', verify(run))
    return run


def main():
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest='action', required=True)
    f = subs.add_parser('plan')
    for k in ('source-plan', 'source-run', 'out'):
        f.add_argument('--' + k, type=Path, required=True)
    f.add_argument('--cpu', type=int, required=True)
    r = subs.add_parser('run')
    r.add_argument('--plan', type=Path, required=True)
    r.add_argument('--runs', type=Path, required=True)
    v = subs.add_parser('verify')
    v.add_argument('--run', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.action == 'plan':
            plan = freeze(ROOT, a.source_plan.resolve(strict=True), a.source_run.resolve(strict=True), a.cpu)
            a.out.parent.mkdir(parents=True, exist_ok=True)
            write_new(a.out, plan)
            print(json.dumps({'plan_id': plan['plan_id'], 'cases': len(plan['cases']), 'excluded': len(plan['excluded'])}))
        elif a.action == 'run':
            print(execute(load_json(a.plan), a.runs.resolve()))
        else:
            print(json.dumps(verify(a.run.resolve(strict=True)), sort_keys=True))
    except (ContractError, OSError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
