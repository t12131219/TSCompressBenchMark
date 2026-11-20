#!/usr/bin/env python3
"""Freeze and audit CORAD branch controls through the same guarded public ABI."""
from argparse import ArgumentParser
import json
from pathlib import Path
from struct import pack
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application import corad_execution as worker
from tsbench.application.m3_sealed_ledger import full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import content_id, load_json, local_file, require, verify_asset
from tsbench.corad_quality import assess, calibrate
from tsbench.planner.corad_deployment import DEPLOYMENT, NATIVE
from tsbench.planner.corad_execution import COLS, identity, is_corad, steps
from tsbench.planner.m3_corad_specialized import fixture_inputs
from tsbench.qualification.corad_inference import HEADER
from tsbench.qualification.corad_wire import interpret
from tsbench.recovery import stage_recovery
from tsbench.supervisor.isolated_worker import launcher_lock

SCHEMA = 'bmk.m3-corad-specialist-branch-probe/1'


def reference(path):
    return {'path': path.relative_to(ROOT).as_posix(), **identity(path.read_bytes())}


def controls(schema):
    # Four basis atoms, at most two nonzeros, a complete tricklet and a raw tail.
    # Scaling preserves Pearson 1 without preserving the values of the copied record.
    model = NATIVE.pack(b'CRD1', 0, 3, 4, 4, 2, 0.9, NATIVE.size + 22*8)
    model += pack('<22d', *(float(i == j) for i in range(4) for j in range(4)), 0., 1., 0., 1., 0., 1.)
    deployment = DEPLOYMENT.pack(b'BMKCDP\x01\0', len(schema), len(model)) + schema + model
    a = (1., 0., 2., 0.)
    for case, factor, expected in (('safe-reference', 1, 1), ('unsafe-correlated-reference', 100, 0)):
        data = (a + (4., 5., 6.), tuple(v*factor for v in a) + (7., 8., 9.), (0., 1., 0., 2., 10., 11., 12.))
        yield case, deployment.hex(), {'schema': schema, **{k: pack('<7d', *v) for k, v in zip(COLS, data, strict=True)}}, expected


def freeze(plan_file, source_run):
    source = load_json(plan_file)
    _, seal = full_run_source(source, source_run)
    binding = source['specialized']['corad']
    sid, = [sid for sid, slot in binding['slots'].items() if is_corad(slot)]
    slot, sample = fixture_inputs(ROOT)[0][sid]
    require(slot == binding['slots'][sid], 'CORAD source fixture changed')
    report = load_json(local_file(source_run, 'report.json'))
    orig = report['specialized']['corad']['fixtures'][sid]
    require(orig['status'] == 'validation_failed' and orig['reason'] == 'CORAD held-out path lost a native branch' and
            len(orig['operations']) == 1 and orig['operations'][0]['operation'] == 'encode-0', 'not the sealed branch failure')
    bundle = slot['bundle']
    raw, calibration = sample.columns
    require(worker._input_extents(slot, {bundle['input']['path']: raw,
             bundle['quality_policy']['calibration']['path']: calibration}) == raw, 'changed original specialist input')
    bounds = calibrate(bundle['input']['columns'], worker._columns(calibration, bundle['quality_policy']['calibration']['rows']),
                       bundle['quality_policy']['definition'])
    cases = []
    for i in (0, 3):
        spec = bundle['frames'][i]
        inputs, _ = worker._io(slot, {bundle['input']['path']: raw}, f'encode-{i}')
        cases.append({'id': spec['route'] + '-prior-held-out', 'deployment': slot['deployments'][i//3],
                      'mounts': {k: v.hex() for k, v in inputs.items()}, 'expected_references': None,
                      'prior_frame': orig['operations'][0]['outputs']['frame'] if i == 0 else None})
    for name, deployment, files, refs in controls(inputs['schema']):
        cases.append({'id': name, 'deployment': deployment, 'mounts': {k: v.hex() for k, v in files.items()},
                      'expected_references': refs, 'prior_frame': None})
    return {'schema': SCHEMA, 'source_plan': reference(plan_file), 'source_run': source_run.relative_to(ROOT).as_posix(),
            'source_seal': seal, 'source_slot': sid, 'driver': reference(Path(__file__).resolve()), 'bounds': bounds,
            'quality_policy_id': bundle['quality_policy']['policy_id'], 'decode': binding['decoder'], 'limits': binding['limits'],
            'launchers': launcher_lock(), 'cases': cases, 'stage_accepted': False, 'qualification_granted': False}


def evaluate(plan, run, evidence):
    require(set(evidence) == {c['id'] for c in plan['cases']}, 'CORAD branch probe population differs')
    results, seen = {}, set()
    for case in plan['cases']:
        key = case['id']; base = run / 'cases' / key
        rec = evidence[key]
        frame = local_file(base, 'frame').read_bytes()
        inputs = {k: bytes.fromhex(case['mounts'][k]) for k in ('schema', *COLS)}
        schema = inputs['schema']
        require(HEADER.unpack_from(frame) == (b'BMKCRD\x01\0', len(schema), 0, len(frame)-HEADER.size-len(schema)) and
                frame[HEADER.size:HEADER.size+len(schema)] == schema, 'CORAD branch frame envelope differs')
        restored, parts, model = interpret(frame[HEADER.size+len(schema):])
        rows = parts['rows']
        n = rows*8
        columns = worker._columns(restored, rows)
        require(parts['columns'] == 3 and all(len(inputs[k]) == n for k in COLS) and
                bytes.fromhex(case['deployment']).endswith(model) and
                all(local_file(base, name).read_bytes() == bits for name, bits in
                    zip(('schema', *COLS), (schema, *columns), strict=True)), 'CORAD independent branch restore or layout differs')
        mounts = {k: identity(v) for k, v in inputs.items()}
        for label, process, ins, outs in (('encode', rec[0], mounts, {'frame': identity(frame)}),
                                          ('restore', rec[1], {'frame': identity(frame)},
                                           {k: identity(v) for k, v in zip(('schema', *COLS), (schema, *columns), strict=True)})):
            session = process['session_id']
            require(len(rec) == 2 and process['operation'] == label and process['status'] == 'completed' and
                    process['returncode'] == 0 and session and session not in seen and process['input_mounts'] == ins and
                    process['outputs'] == outs and local_file(base, f'{label}.stderr').stat().st_size == 0,
                    'CORAD scoped branch process evidence differs')
            seen.add(session)
        want = case['expected_references']
        if want is not None:
            require(parts['references'] == want and parts['sparse_records'] == 3-want and parts['tail_bytes'] == 72 and
                    all(col == inputs[k] for k, col in zip(COLS, columns, strict=True)), 'CORAD exact branch controls did not match')
        prior_frame = case['prior_frame']
        require(prior_frame is None or prior_frame == identity(frame), 'CORAD first frame does not reproduce prior sealed digest')
        results[key] = {'frame': identity(frame), 'restored': identity(restored), 'references': parts['references'],
                        'sparse_records': parts['sparse_records'], 'tail_bytes': parts['tail_bytes'],
                        **({'quality': assess(plan['bounds'], [inputs[k] for k in COLS], columns)} if want is None else {})}
    return {'schema': SCHEMA + '-report', 'plan_id': content_id(plan), 'results': results, 'observed_processes': len(seen),
            'stage_accepted': False, 'qualification_granted': False}


def execute(plan, run):
    run.mkdir()
    binding = {'decoder': plan['decode'], 'limits': plan['limits']}
    stage_recovery(ROOT, run, binding['decoder'])
    evidence = {}
    for case in plan['cases']:
        base = run / 'cases' / case['id']; base.mkdir(parents=True)
        # The common recipe declares a second deployment for wrong-model refusal; only encode-0 and restore-0 run here.
        recipe = steps({'deployments': [case['deployment']]*2, 'bundle': {'frames': [{'case': 'held-out'}]}})
        inputs = {k: bytes.fromhex(case['mounts'][k]) for k in ('schema', *COLS)}
        ops = evidence[case['id']] = []
        frame = worker._invoke(run, binding, None, base, 'encode', recipe['encode-0'], inputs, base, lambda: False, ops)
        restored = worker._invoke(run, binding, None, base, 'restore', recipe['restore-0'], frame, base, lambda: False, ops)
        for name, value in (frame | restored).items():
            (base / name).write_bytes(value)
    write_new(run / 'operations.json', evidence)
    write_new(run / 'report.json', evaluate(plan, run, evidence))


def main():
    parser = ArgumentParser(description=__doc__)
    cmd = parser.add_subparsers(dest='cmd', required=True)
    f = cmd.add_parser('plan'); f.add_argument('--source-plan', type=Path, required=True)
    f.add_argument('--source-run', type=Path, required=True); f.add_argument('--out', type=Path, required=True)
    for name in ('run', 'verify'):
        c = cmd.add_parser(name); c.add_argument('--plan', type=Path, required=True); c.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    if args.cmd == 'plan':
        plan = freeze(args.source_plan.resolve(strict=True), args.source_run.resolve(strict=True))
        write_new(args.out, plan)
        return
    plan = load_json(args.plan)
    require(plan == freeze(verify_asset(ROOT, plan['source_plan']), (ROOT / plan['source_run']).resolve(strict=True)),
            'frozen CORAD branch probe inputs differ')
    args.run = args.run.resolve()
    require(args.run.is_relative_to(ROOT), 'CORAD branch probe output escaped workspace')
    if args.cmd == 'run':
        execute(plan, args.run)
    else:
        report = evaluate(plan, args.run, load_json(local_file(args.run, 'operations.json')))
        require(report == load_json(local_file(args.run, 'report.json')), 'CORAD branch report did not recompute')
        print(json.dumps({k: {m: r[m] for m in ('references', 'sparse_records', 'tail_bytes')} for k, r in report['results'].items()}))


if __name__ == '__main__':
    main()
