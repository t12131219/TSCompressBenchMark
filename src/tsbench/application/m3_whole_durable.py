"""Verified-durable replay for the Sprintz FIRE, Huff0 FEC1 and SElf* whole-file routes."""
from collections import Counter
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
from time import monotonic_ns
from uuid import uuid4

from ..assets import content_id, digest, load_json, local_file, parse_json, require
from ..recovery import stage_recovery
from ..supervisor import timing_resource as resource
from . import m3_abi_corpus_timing as abi, m3_selfstar_timing as selfstar
from .m3_column_batch_timing import _pin, _verify_staged, distribution
from .m3_fixed_batch_corpus import _sync
from .m3_real_corpus_execution import _entry_map
from .m3_sprintz_timing import check, relative
from .smoke import _line, write_new

SCHEMA = 'bmk.m3-whole-durable/1'
DRIVERS = {'abi': abi, 'selfstar': selfstar}
ROUTES = ('fire-batch', 'huff0-reference', 'selfstar-batch', 'selfstar-incremental')
CODE = ('src/tsbench/application/m3_whole_durable.py', 'src/tsbench/application/m3_fixed_batch_corpus.py',
        'src/tsbench/application/m3_column_batch_timing.py', 'tools/m3_whole_durable.py')
POLICY = {'encode': 'locked original through typed canonical staging, isolated exact direction, verification and fsync',
          'decode': 'frozen frame inputs only through isolated exact direction, original bits/schema verification and fsync',
          'completion': 'fsync of each produced file and all output directories inside the run, after verification',
          'repeats': 'same locked schedule and operation geometry as each baseline; all durations measured anew',
          'retention': 'one fixed frame and canonical typed value group set per file-route, no repeated products',
          'ordered_incremental': selfstar.POLICY['incremental'], 'reservation': resource.RESERVATION,
          'cache': 'inherited', 'exclusive_cpu': False, 'timing_admitted': False, 'stage_accepted': False,
          'qualification_granted': False}


def _native_runs(root, plan):
    runs = {}
    for kind, binding in plan['sources'].items():
        seal = check(root, binding['seal'])
        require(seal.name == 'completion.json', 'foreign native seal')
        runs[kind] = seal.parent
    return runs


def freeze(root, runs, cpu, dataset=None):
    require(runs.keys() == DRIVERS.keys(), 'requires both native reference runs')
    sources, cases, terms = {}, [], []
    plan_ref = source_run = source_seal = None
    for kind, driver in DRIVERS.items():
        run = runs[kind]
        baseline_file = local_file(run, 'plan.json')
        baseline = load_json(baseline_file)
        report = local_file(run, 'report.json')
        require(driver.verify(run) == load_json(report), 'native reference report fails recomputation')
        ref = baseline['source_plan' if kind == 'abi' else 'source']
        run_dir, seal = baseline['source_run'], baseline['source_seal']
        if plan_ref is None:
            plan_ref, source_run, source_seal = ref, run_dir, seal
        require((ref, run_dir, seal) == (plan_ref, source_run, source_seal), 'native references do not share one functional seal')
        source = (root / run_dir).resolve(strict=True)
        require(source.is_relative_to(root) and driver.freeze(root, check(root, ref), source,
                        check(root, baseline['worker']), cpu) == baseline, 'native reference geometry, build or resource differs')
        sources[kind] = {'plan': relative(root, baseline_file), 'seal': relative(root, local_file(run, 'completion.json')),
                         'report': relative(root, report)}
        cases.extend({'driver': kind, **case} for case in baseline['cases'] if dataset in (None, case['dataset_id']))
        terms.extend({'driver': kind, **case} for case in baseline['excluded'] if dataset in (None, case['dataset_id']))
    require({c['route'] for c in cases} == set(ROUTES) and len(cases) == len({c['case_id'] for c in cases}),
            'durable plan omits or repeats route cases')
    body = {'schema': SCHEMA, 'sources': sources, 'source_plan': plan_ref, 'source_run': source_run, 'source_seal': source_seal,
            'environment': resource.environment(cpu), 'policy': POLICY, 'dataset_projection': dataset, 'cases': cases,
            'excluded': terms, 'code': {n: digest(local_file(root, n)) for n in CODE}}
    return {**body, 'plan_content_id': content_id(body)}


def _source_plans(root, plan):
    require(freeze(root, _native_runs(root, plan), plan['environment']['cpu'], plan['dataset_projection']) == plan,
            'whole-durable plan differs from frozen native and functional references')
    return {kind: load_json(check(root, b['plan'])) for kind, b in plan['sources'].items()}


def _self_paths(folder, wanted):
    selfstar.verified(folder, wanted)
    return {n: local_file(folder, n) for n in wanted}


def _raw(root, entry, case, work):
    require(entry['canonical']['object_id'] == case['canonical_object_id'] and entry['file'] == case['source_file'],
            'durable source does not match frozen case')
    if case['driver'] == 'abi':
        return abi.prepare_values(root, entry, case, work)
    folder = work / 'values'
    selfstar._stage(root, entry, folder)
    for col in range(case['cols']):
        (folder / selfstar.names(col)[1]).write_bytes(selfstar.schema(case['rows'], col))
    return _self_paths(folder, selfstar.refs(case)[0])


def _anchors(base, case):
    if case['driver'] == 'abi':
        n = len(list(abi.groups(case['units'])))
        raw, wire = abi.files(base / 'raw', n), abi.files(base / 'wire', n)
        _verify_staged(raw, case)
        return (raw, abi.identities(raw)), (wire, abi.verify_frames(wire, case['units']))
    a, b = selfstar.refs(case)
    return (_self_paths(base / 'raw', a), a), (_self_paths(base / 'wire', b), b)


def _resolved(run, plan, case, trial, inputs, work):
    op = trial['operation']
    begin = monotonic_ns()
    if case['driver'] == 'abi':
        out, row = abi.invoke(run, plan, case, trial, inputs, work)
        if op == 'encode':
            require(abi.verify_frames(out, case['units']) == row['output'], 'durable ABI frame changed after measurement')
    else:
        folder, process, native = selfstar.invoke(run / 'runtime', plan, case, op, inputs, work)
        expected = selfstar.refs(case)[int(op == 'encode')]
        out = _self_paths(folder, expected)
        row = {'case_id': case['case_id'], **trial, 'process': process, 'native': native,
               'native_totals_ns': selfstar.totals(plan, case, op, native), 'output': expected,
               'staged_supervision_and_verification_wall_ns': monotonic_ns()-begin}
    return out, row


def _validate(plan, case, t, row, raw, wire, seen):
    if case['driver'] == 'abi':
        m, o = (raw, wire) if t['operation'] == 'encode' else (wire, raw)
        abi.validate(plan, case, t, row, m, o, seen)
    else:
        selfstar.validate(plan, case, t, row, seen)
    require(row['durable_wall_ns'] >= row['staged_supervision_and_verification_wall_ns'] + row['fsync_wall_ns'] and
            row['fsync_wall_ns'] > 0, 'durable path must include the staged direction and disjoint fsync')


def _summarize(case, rows):
    if case['driver'] == 'abi':
        result = abi.summarize(case, rows)
        logical = result['logical_bytes']
    else:
        result = selfstar.summarize(case, rows)
        logical = result['counts']['input_bytes']
    for op in ('encode', 'decode'):
        chosen = [r for r in rows if r['phase'] == 'measured' and r['operation'] == op]
        times = [r['durable_wall_ns'] for r in chosen]
        result['directions'][op]['verified_durable'] = {'wall_ns': distribution(times),
                'fsync_wall_ns': distribution([r['fsync_wall_ns'] for r in chosen]),
                'logical_mib_per_second': distribution([logical * 1e9 / (n * (1 << 20)) for n in times])}
    return result


def _recompute(run, plan, baselines):
    for kind, native in baselines.items():
        for n, asset in native['runtime']['files'].items():
            check(run, {'path': f'{kind}/runtime/{n}', **{k: asset[k] for k in ('bytes', 'sha256')}})
    env = load_json(local_file(run, 'environment.json'))
    require(env['affinity'] == [plan['environment']['cpu']] and env.keys() == {'affinity', 'before', 'after'},
            'durable observation environment differs')
    results, seen = [], set()
    with local_file(run, 'trials.jsonl').open('rb') as ledger:
        for case in plan['cases']:
            kind = case['driver']
            base = run / kind / 'cases' / case['case_id']
            (_, raw), (_, wire) = _anchors(base, case)
            rows = []
            for i, t in enumerate(baselines[kind]['schedule']):
                row = parse_json(ledger.readline(), 'whole-durable ledger row')
                op = t['operation']
                require(load_json(local_file(base, f'logs/{i}/{op}.stdout')) == row['native'] and
                        local_file(base, f'logs/{i}/{op}.stderr').stat().st_size == 0, 'durable worker log differs')
                _validate(baselines[kind], case, t, row, raw, wire, seen)
                rows.append(row)
            results.append(_summarize(case, rows))
        require(not ledger.read(1), 'whole-durable ledger has extra observations')
    return {'schema': SCHEMA + '-report', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'source_seal': plan['source_seal'], 'source_plan': plan['source_plan'], 'dataset_projection': plan['dataset_projection'],
            'environment': env, 'policy': POLICY, 'verified_trials': len(seen),
            'file_routes': dict(Counter(c['route'] for c in results)), 'cases': results, 'excluded': plan['excluded'],
            **{k: False for k in ('timing_admitted', 'qualification_granted', 'stage_accepted')}}


def _seal(run, plan):
    body = {'schema': SCHEMA + '-seal', 'run_id': run.name, 'plan_content_id': plan['plan_content_id'],
            'files': {n: relative(run, local_file(run, n)) for n in ('plan.json', 'environment.json', 'trials.jsonl', 'report.json')}}
    return {**body, 'seal_id': content_id(body)}


def execute(root, plan, output):
    baselines = _source_plans(root, plan)
    require(output.is_relative_to(root), 'whole-durable output outside workspace')
    main = load_json(check(root, plan['source_plan']))
    entries = _entry_map(root, load_json(check(root, main['definition']['plan'])))
    cpu = plan['environment']['cpu']
    with resource.reserve(), _pin(cpu):
        output.mkdir(parents=True, exist_ok=True)
        sizes = [sum((u['original']['bytes'] + u['schema']['bytes'] + 8 + u['artifact']['bytes']) if c['driver'] == 'abi' else
                     (u['input_bytes'] + len(selfstar.schema(c['rows'], u['column'])) + u['artifact_bytes']) for u in c['units'])
                 for c in plan['cases']]
        require(shutil.disk_usage(output).free > sum(sizes) + 3 * max(sizes) + (256 << 20), 'whole-durable free disk budget exhausted')
        run = output / uuid4().hex
        run.mkdir()
        write_new(run / 'plan.json', plan)
        for kind, native in baselines.items():
            area = run / kind
            area.mkdir()
            stage_recovery(root, area, native['runtime'], directory='runtime')
        env = {'affinity': [cpu], 'before': resource.observe(cpu)}
        seen = set()
        with (run / 'trials.jsonl').open('xb') as ledger:
            for case in plan['cases']:
                kind = case['driver']
                area, native = run / kind, baselines[kind]
                base = area / 'cases' / case['case_id']
                (base / 'logs').mkdir(parents=True)
                entry = entries[case['dataset_id']]
                with TemporaryDirectory(dir=base, prefix='anchor-') as tmp:
                    b = Path(tmp)
                    staged = _raw(root, entry, case, b)
                    got, anchor = _resolved(area, native, case, {'operation': 'encode', 'round': -1, 'phase': 'anchor'}, staged, b / 'call')
                    next(iter(staged.values())).parent.rename(base / 'raw')
                    next(iter(got.values())).parent.rename(base / 'wire')
                (_, raw), (fixed, wire) = _anchors(base, case)
                t = {k: anchor[k] for k in ('operation', 'round', 'phase')}
                if kind == 'abi':
                    abi.validate(native, case, t, anchor, raw, wire, seen)
                else:
                    selfstar.validate(native, case, t, anchor, seen)
                for i, t in enumerate(native['schedule']):
                    with TemporaryDirectory(dir=base, prefix='trial-') as tmp:
                        b = Path(tmp)
                        begin = monotonic_ns()
                        inp = _raw(root, entry, case, b) if t['operation'] == 'encode' else fixed
                        got, row = _resolved(area, native, case, t, inp, b / 'call')
                        expected = wire if t['operation'] == 'encode' else raw
                        require(row['output'] == expected, 'durable directional output differs')
                        sync = monotonic_ns()
                        _sync(got, run)
                        end = monotonic_ns()
                        row.update(durable_wall_ns=end-begin, fsync_wall_ns=end-sync)
                        _validate(native, case, t, row, raw, wire, seen)
                        log = base / 'logs' / str(i)
                        log.mkdir()
                        for p in (b / 'call').glob('*.std*'):
                            p.rename(log / p.name)
                        _line(ledger, row)
                print(f"verified {case['dataset_id']} {case['route']}", flush=True)
        write_new(run / 'environment.json', {**env, 'after': resource.observe(cpu)})
        write_new(run / 'report.json', _recompute(run, plan, baselines))
        write_new(run / 'completion.json', _seal(run, plan))
    return run


def verify(root, run):
    plan = load_json(local_file(run, 'plan.json'))
    require(load_json(local_file(run, 'completion.json')) == _seal(run, plan), 'whole-durable seal differs')
    report = _recompute(run, plan, _source_plans(root, plan))
    require(report == load_json(local_file(run, 'report.json')), 'whole-durable report differs from replay')
    return report
