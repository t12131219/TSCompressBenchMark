#!/usr/bin/env python3
"""Compare the original CORAD and an isolated reference-error guard without changing r40."""
from argparse import ArgumentParser
import json
from pathlib import Path
from struct import pack
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from build_m3_corad_reference_guard import ref
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import write_new
from tsbench.assets import ContractError, content_id, load_json, local_file, require, verify_asset
from tsbench.corad_quality import assess
from tsbench.planner.corad_deployment import NATIVE
from tsbench.planner.corad_execution import identity, is_corad, split_deployment
from tsbench.qualification.corad_inference import HEADER, verify_bounds
from tsbench.qualification.corad_wire import interpret
from tsbench.recovery import plan_recovery, stage_recovery
from tsbench.supervisor.isolated_worker import invoke_isolated_tool, launcher_lock

SCHEMA = 'bmk.m3-corad-reference-guard-diagnostic/1'
LIMITS = {'address_space_bytes': 128 << 20, 'file_bytes': 16384, 'wall_seconds': 10}
VARIANTS = ('frozen', 'guard')


def _portable(reference):
    return {k: reference[k] for k in ('path', 'sha256')}


def _synthetic(shift):
    # Exact independent basis: OMP can reconstruct both columns, and Pearson is +1 either way.
    model = NATIVE.pack(b'CRD1', 0, 2, 4, 4, 4, 0.9, NATIVE.size + 20 * 8)
    model += pack('<20d', *(float(i == j) for i in range(4) for j in range(4)), 0., 1., 0., 1.)
    values = pack('<8d', 1., 2., 3., 4., *(float(i + shift) for i in range(1, 5)))
    return model, values


def _payload(wrapped):
    magic, schema, reserve, size = HEADER.unpack_from(wrapped)
    raw = wrapped[HEADER.size + schema:]
    require(magic == b'BMKCRD\x01\0' and reserve == 0 and size == len(raw), 'frozen CORAD envelope differs')
    return raw


def _split(values, rows, cols):
    require(len(values) == rows * cols * 8, 'CORAD guard result shape differs')
    return [values[8*i*rows:8*(i+1)*rows] for i in range(cols)]


def freeze(source_file, source_run, build_file):
    source, build = load_json(source_file), load_json(build_file)
    ledger, seal = full_run_source(source, source_run)
    require(build['build_id'] == content_id({k: v for k,v in build.items() if k != 'build_id'}) and
            build['base_build_id'] == source['build']['build_id'], 'CORAD guard build does not match frozen run')
    for name in ('candidate', 'patch', 'patched_source', 'base_dependency', 'base_control', 'restore_source'):
        verify_asset(ROOT, build[name])
    binding = source['specialized']['corad']
    slot, = [s for s in binding['slots'].values() if is_corad(s)]
    require(build['base_dependency']['sha256'] == binding['decoder']['files']['lib/libcorad_c.so']['sha256'],
            'original comparison does not use r40 dependency')
    bundle = slot['bundle']
    verdict = product = None
    for row, _ in full_run_rows(source, ledger):
        if row.get('entry_kind') == 'specialized_obligation' and row.get('selection') == 80 and row.get('check') == 'bound_predeclared_before_formal_run':
            verdict = row
        if row.get('entry_kind') == 'specialized_product' and row.get('product_slot') == slot['product_slot']:
            product = row
    require(verdict and product and verdict['status'] == 'quality_rejected' and product['status'] == 'verified' and
            verdict['evidence']['quality_gate'] == product['corad']['quality_gate'], 'r40 CORAD reference verdict differs')
    folder = source_run / 'corad-specialized/products' / slot['product_slot']
    source_raw, calibration = bundle['input'], bundle['quality_policy']['calibration']
    bounds = verify_bounds(folder, bundle['quality_policy'], source_raw['columns'], bundle['window'])
    cases = []
    for i, model in enumerate(bundle['models']):
        model_route = model['definition']['training']['route']
        _, bytes_model = split_deployment(slot['deployments'][i])
        reference = local_file(folder, f'corad-{model_route}-held-out.bmk')
        for name, data_ref, data_rows in (('calibration', calibration, calibration['rows']), ('heldout', source_raw, source_raw['rows'])):
            original = local_file(folder, data_ref['path'])
            require(identity(original.read_bytes()) == {k: data_ref[k] for k in ('bytes', 'sha256')}, 'CORAD sealed source bits differ')
            cases.append({'id': f'{model_route}-{name}', 'subset': name, 'model_hex': bytes_model.hex(), 'rows': data_rows, 'cols': 3,
                          'source': ref(original), **({'reference': ref(reference),
                                      'reference_gate': verdict['evidence']['quality_gate']['heldout'][model_route]} if name == 'heldout' else {})})
    for name, shift, expected in (('copy-identical', 0, 1), ('reject-shifted-copy', 100, 0)):
        model, values = _synthetic(shift)
        cases.append({'id': name, 'subset': 'synthetic', 'model_hex': model.hex(), 'source_hex': values.hex(),
                      'rows': 4, 'cols': 2, 'guard_references': expected})
    runtimes = {v: plan_recovery(ROOT, {}, (), tools={k: _portable(x) for k,x in build[v].items() if k != 'library'},
                                 libraries=[_portable(build[v]['library'])]) for v in VARIANTS}
    body = {'schema': SCHEMA, 'source_plan': ref(source_file), 'source_run': source_run.relative_to(ROOT).as_posix(),
            'source_seal': seal, 'build_lock': ref(build_file), 'runtimes': runtimes, 'cases': cases, 'limits': LIMITS,
            'launchers': launcher_lock(), 'driver': ref(Path(__file__).resolve()), 'bounds': bounds, 'quality_policy_id': bundle['quality_policy']['policy_id'],
            'tuned_parameters': [], 'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}
    return {**body, 'plan_id': content_id(body)}


def _inputs(case):
    return bytes.fromhex(case['model_hex']), (bytes.fromhex(case['source_hex']) if 'source_hex' in case else
                                            verify_asset(ROOT, case['source']).read_bytes())


def _call(run, plan, runtime, verb, job, inputs, output, records):
    work = run / 'operations' / job
    work.mkdir(parents=True)
    closure = plan['runtimes'][runtime]
    out, proc = invoke_isolated_tool(run / runtime, closure, verb, LIMITS, work, work, verb, inputs,
                                    [f'/inputs/{name}' for name in inputs], lambda: False,
                                    observe=True)
    stderr = (work / (verb+'.stderr')).read_text()
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and not stderr and
            {p.name for p in out.iterdir()} == {output}, f'CORAD {job}: {proc["status"]}: {stderr[:240]}')
    result = local_file(out, output)
    records[job] = {'process': proc, 'output': result.relative_to(run).as_posix()}
    return result


def _analyze(run, plan, records):
    results, sessions, expected_ops = {}, set(), set()
    for case in plan['cases']:
        model, raw = _inputs(case)
        rows, cols = case['rows'], case['cols']
        results[case['id']] = observations = {}
        for variant in VARIANTS:
            jid = f'{case["id"]}-{variant}'
            outputs = {}
            for op, mounts, filename in (('encode', {'model': model, 'values': raw}, 'native'), ('decode', None, 'restored')):
                job = jid + '-' + op
                expected_ops.add(job)
                rec = records[job]
                state = rec['process']
                if mounts is None:
                    mounts = {'frame': outputs['encode']}
                path = f'operations/{job}/out/{filename}'
                require(state['status'] == 'completed' and not state['reason'] and state['returncode'] == 0 and
                        state['operation'] == op and state['session_id'] and state['session_id'] not in sessions and
                        state['input_mounts'] == {k: identity(b) for k,b in mounts.items()} and rec['output'] == path and
                        local_file(run, f'operations/{job}/{op}.stderr').stat().st_size == 0, 'CORAD isolated evidence differs')
                sessions.add(state['session_id'])
                outputs[op] = local_file(run, path).read_bytes()
            native = outputs['encode']
            restored, sections, embedded = interpret(native)
            require(restored == outputs['decode'] and native[:4] == b'CRD1' and sections['rows'] == rows and sections['columns'] == cols and
                    native[8:24] == model[8:24] and embedded == model[NATIVE.size:], 'guard differs from original CRD1 model or decoder')
            obs = {'native': identity(native), 'recovered': identity(restored), 'references': sections['references']}
            observations[variant] = obs
            if case['subset'] == 'synthetic':
                require(obs['references'] == (1 if variant == 'frozen' else case['guard_references']), 'synthetic reference census differs')
                if variant == 'guard':
                    require(restored == raw, 'synthetic guard did not recover all original values exactly')
                obs['exact'] = restored == raw
            else:
                obs['quality'] = assess(plan['bounds'], _split(raw, rows, cols), _split(restored, rows, cols))
                if variant == 'frozen' and 'reference' in case:
                    require(native == _payload(verify_asset(ROOT, case['reference']).read_bytes()) and obs['quality'] == case['reference_gate'],
                            'control does not reproduce the sealed r40 frame and quality rejection')
    require(set(records) == expected_ops, 'guard operation population differs')
    return {'schema': SCHEMA + '-report', 'plan_id': plan['plan_id'], 'source_seal': plan['source_seal'], 'cases': results,
            'observed_processes': len(sessions), 'stage_accepted': False, 'timing_admitted': False, 'qualification_granted': False}


def _seal(run, plan):
    refs = {p.relative_to(run).as_posix(): identity(p.read_bytes()) for p in sorted(run.rglob('*'))
            if p.is_file() and p.name != 'completion.json'}
    doc = {'schema': SCHEMA + '-seal', 'plan_id': plan['plan_id'], 'files': refs}
    return {**doc, 'seal_id': content_id(doc)}


def execute(run, plan):
    run.mkdir(parents=True, exist_ok=False)
    (run / 'operations').mkdir()
    write_new(run / 'plan.json', plan)
    for variant in VARIANTS:
        stage_recovery(ROOT, run, plan['runtimes'][variant], directory=variant)
    records = {}
    for case in plan['cases']:
        folder = run / case['id']
        folder.mkdir()
        model, values = _inputs(case)
        inputs = {'model':folder / 'model', 'values':folder / 'values'}
        for p, bits in zip(inputs.values(), (model, values), strict=True):
            p.write_bytes(bits)
        for variant in VARIANTS:
            base = f'{case["id"]}-{variant}'
            native = _call(run, plan, variant, 'encode', base+'-encode', inputs, 'native', records)
            _call(run, plan, 'frozen', 'decode', base+'-decode', {'frame': native}, 'restored', records)
    write_new(run / 'operations.json', records)
    write_new(run / 'report.json', _analyze(run, plan, records))
    write_new(run / 'completion.json', _seal(run, plan))


def verify(run):
    plan = load_json(local_file(run, 'plan.json'))
    require(load_json(local_file(run, 'completion.json')) == _seal(run, plan), 'CORAD guard comparison seal differs')
    source = verify_asset(ROOT, plan['source_plan'])
    build = verify_asset(ROOT, plan['build_lock'])
    source_run = (ROOT / plan['source_run']).resolve(strict=True)
    require(source_run.is_relative_to(ROOT) and plan == freeze(source, source_run, build), 'guard plan does not recompute')
    doc = _analyze(run, plan, load_json(local_file(run, 'operations.json')))
    require(doc == load_json(local_file(run, 'report.json')), 'guard report does not recompute')
    return doc


def main():
    p = ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    r = sub.add_parser('run')
    for arg in ('source-plan', 'source-run', 'build-lock', 'out'):
        r.add_argument('--' + arg, type=Path, required=True)
    sub.add_parser('verify').add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    try:
        if a.mode == 'run':
            execute(a.out.resolve(), freeze(a.source_plan.resolve(), a.source_run.resolve(), a.build_lock.resolve()))
        doc = verify(a.out.resolve())
        print(json.dumps({'observed_processes': doc['observed_processes'], 'cases': {k: {v: x.get('quality',{}).get('decision',x.get('exact'))
                                  for v,x in group.items()} for k,group in doc['cases'].items()}}))
    except (ContractError, OSError, ValueError) as exc:
        p.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
