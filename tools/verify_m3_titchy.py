#!/usr/bin/env python3
"""Audit Titchy native scopes and replay a detached sample per file and route."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from tsbench.application.m3_titchy import audit_specialized, inspect_frame, restore_batch, stage_titchy
from tsbench.application.m3_titchy_access import CHUNK_ROWS, WIRE_POLICY, invoke, validate_access
from tsbench.application.m3_titchy_stream import POLICY, SPEC, validate_stream
from tsbench.application.m3_sealed_ledger import full_run_rows, full_run_source
from tsbench.application.smoke import _worker_json, write_new
from tsbench.assets import content_id, digest, load_json, local_file, require, verify_asset
from tsbench.contracts import load_contract
from tsbench.corpus_ingress import load_full_manifest
from tsbench.planner.m3_real_corpus import check_m3_real_corpus_plan
from tsbench.planner.m3_titchy import BATCH_DRIVER
from tsbench.planner.typed_batch import TITCHY
from tsbench.qualification.titchy_wire import decode_tchy, decode_tstr
from tsbench.recovery import DIRECTORY, plan_recovery, stage_recovery
from tsbench.supervisor.isolated_worker import invoke_isolated_tool, invoke_isolated_worker, launcher_lock

ROUTES = {'batch': BATCH_DRIVER, 'packet-stream': 'titchy-stream-control/1',
          'loaded-file-access': 'titchy-access-control/1', 'batch-range': 'titchy-access-control/1'}
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 15}


def _isolated_sample(runtime, work, mode, inputs, args):
    require(mode in ROUTES and inputs.keys() == ({'archive', 'config'} if mode == 'packet-stream' else {'frame'}),
            'Titchy replay may mount only the selected compressed product and its declared configuration')
    bundle, spec = runtime
    if mode == 'batch':
        out, proc = invoke_isolated_worker(bundle, spec, {'plugin': TITCHY, 'options': {}}, LIMITS, work, work,
                                           'decode-columns', inputs, args, lambda: False, label='replay', observe=True)
    else:
        tool = mode if mode == 'packet-stream' else 'access'
        out, proc = invoke_isolated_tool(bundle, spec, tool, LIMITS, work, work, 'replay', inputs, args,
                                         lambda: False, bind_inputs=True)
    stderr = work / 'replay.stderr'
    expected = {'raw', 'schema'} if mode == 'batch' else {'raw'}
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and stderr.stat().st_size == 0 and
            {p.name for p in out.iterdir()} == expected and
            proc['input_mounts'] == {k: {'bytes': p.stat().st_size, 'sha256': digest(p)} for k, p in inputs.items()},
            f'Titchy isolated replay failed for {mode}: {proc["status"]}: {stderr.read_text()[:500]}')
    return out, _worker_json(work / 'replay.stdout', 2 if mode == 'batch' else 1), proc


def _sample(root, run, plan, row, runtimes=None):
    mode = row['route']
    evidence = row['evidence']
    u = evidence['units'][0]
    n = u['row_range'][1]
    ref = evidence['retained_sample']
    refs = ref['parts'] if mode == 'packet-stream' else {'frame': ref}
    require(u['column'] == 0 and u['row_range'] == [0, n] and all(
        r['path'].startswith(f"retained/{row['work_item_id']}/") for r in refs.values()),
        'Titchy selected sample is not the first unit in its frozen namespace')
    proc = None
    with tempfile.TemporaryDirectory(prefix='titchy-corpus-audit-') as tmp:
        work = Path(tmp)
        if mode == 'batch':
            frame = verify_asset(run, ref)
            wire = frame.read_bytes()
            require(len(wire) == ref['bytes'] == u['artifact_bytes'] and ref['sha256'] == u['frame_sha256'], 'Titchy batch sample frame differs')
            if runtimes is None:
                copy = work / 'frame'
                copy.write_bytes(wire)
                record, _ = restore_batch(root, plan['specialized']['titchy'], work, copy)
                out = work
            else:
                out, record, proc = _isolated_sample(runtimes['batch'], work, mode, {'frame': frame},
                                                       ['/inputs/frame', '/out/schema', '/out/raw'])
                require(record[1] == {'threads': 1, 'mode': 'batch', 'operation': 'decode', 'backend': 'titchy-c11',
                                      'entry': 'titchy_c_decode'}, 'Titchy isolated ABI backend differs')
            schema = (out / 'schema').read_bytes()
            native, billing = inspect_frame(wire, n, schema)
            raw, _ = decode_tchy(native, 64, n, WIRE_POLICY)
            require(record[0] == {'columns': [{'dtype': 8, 'count': n}]} and (out / 'raw').read_bytes() == raw and
                    sha256(schema).hexdigest() == u['schema_sha256'] and sha256(native).hexdigest() == u['native_sha256'] and
                    billing == {k: u[k] for k in billing}, 'Titchy batch sample replay differs')
        elif mode == 'packet-stream':
            require((ref['column'], ref['row_range'], ref['restored_sha256']) == (0, [0, n], u['restored_sha256']) and
                    ref['parts'].keys() == {'tstr', 'tsc1'}, 'Titchy stream retained extent differs')
            a, c = (verify_asset(run, refs[k]) for k in ('tstr', 'tsc1'))
            archive, config = a.read_bytes(), c.read_bytes()
            require(sha256(archive).hexdigest() == u['archive_sha256'] and sha256(config).hexdigest() == u['config_sha256'] and
                    len(archive) == ref['parts']['tstr']['bytes'] and len(config) == ref['parts']['tsc1']['bytes'],
                    'Titchy stream sample identity differs')
            raw, packets = decode_tstr(archive, config, {**SPEC, 'count': n}, POLICY)
            require(len(packets) == u['encode']['packets'], 'Titchy stream sample packet count differs')
            if runtimes is None:
                (work / 'archive').write_bytes(archive); (work / 'config').write_bytes(config)
                control = local_file(root, plan['build']['titchy_stream']['executable']['path'])
                decoded, _ = invoke(control, work, 'decode', 'archive', 'config', 'raw')
                out = work
            else:
                out, (decoded,), proc = _isolated_sample(runtimes['direct'], work, mode, {'archive': a, 'config': c},
                                                           ['decode', '/inputs/archive', '/inputs/config', '/out/raw'])
            billing = validate_stream(n, archive, config, u['encode'], decoded)
            require((out / 'raw').read_bytes() == raw and billing == {k: u[k] for k in billing}, 'Titchy stream sample replay differs')
        else:
            frame = verify_asset(run, ref)
            wire = frame.read_bytes()
            require((ref['column'], ref['row_range'], ref['sha256'], ref['bytes']) == (0, [0,n], u['sha256'], len(wire)),
                    'Titchy access sample identity differs')
            raw, _ = decode_tchy(wire, 64, n, WIRE_POLICY)
            if runtimes is None:
                (work / 'frame').write_bytes(wire)
                control = local_file(root, plan['build']['titchy_access']['executable']['path'])
                observed, _ = invoke(control, work, mode, 'frame', str(n), 'raw')
                out = work
            else:
                out, (observed,), proc = _isolated_sample(runtimes['direct'], work, mode, {'frame': frame},
                                                            [mode, '/inputs/frame', str(n), '/out/raw'])
            billing = validate_access(mode, raw, wire, (out / 'raw').read_bytes(), u['encode'], observed)
            require(billing == {k: u[k] for k in billing} and sha256(raw).hexdigest() == ref['restored_sha256'],
                    'Titchy access sample replay differs')
    result = {'mode': mode, 'dataset_id': row['dataset_id'], 'rows': n, 'restored_sha256': sha256(raw).hexdigest()}
    return {**result, 'work_item_id': row['work_item_id'], 'parts': refs, 'process': proc} if proc else result


def _originals(root, entry):
    with tempfile.TemporaryDirectory(prefix='m3-titchy-oracle-') as tmp:
        paths = stage_titchy(root, entry, Path(tmp))['paths']
        by_column, by_block = [], []
        for path in paths:
            by_column.append(digest(path))
            with path.open('rb') as stream:
                by_block.extend(sha256(raw).hexdigest() for raw in iter(lambda: stream.read(8*CHUNK_ROWS), b''))
    return by_column, by_block


def verify(root, plan_path, run, *, replay=False):
    plan = load_json(plan_path)
    check_m3_real_corpus_plan(root, plan)
    report_path, ledger = (local_file(run, p) for p in ('report.json', 'ledger.jsonl'))
    report = load_json(report_path)
    load_contract(root, 'm3-real-corpus-plan').validate(plan, 'plan')
    load_contract(root, 'm3-real-corpus-run').validate(report, 'report')
    seal = load_json(local_file(run, 'completion.json'))
    require(seal['plan_content_id'] == report['plan_content_id'] == plan['plan_content_id'] and
            seal['run_id'] == report['run_id'] == run.name and seal['report_sha256'] == digest(report_path) and
            seal['ledger_sha256'] == digest(ledger) and seal['seal_id'] == content_id({k: v for k, v in seal.items() if k != 'seal_id'}),
            'Titchy M3 run seal differs')
    spec, binding = report['specialized']['titchy'], plan['specialized']['titchy']
    typed = [{'entry_kind': 'specialized_product', 'selection': 85, **f} for f in spec['fixtures'].values()]
    with ledger.open(encoding='utf-8') as stream:
        for line, row in zip(stream, [*report['rows'], *typed, *report['obligations']], strict=True):
            require(json.loads(line) == row, 'Titchy ledger differs from report')
    expected = [r for r in plan['work_items'] if r['selection'] == 85]
    require(report['partial_preflight'] and report['route_filter'] == sorted(ROUTES) and
            report['statuses'] == {'verified': 92} and len(report['rows']) == len(expected) == 92,
            'Titchy corpus preflight scope or terminal differs')
    corpus = _audit_corpus(root, run, plan, zip(expected, report['rows'], strict=True))
    obligations = [o for o in plan['obligations'] if o['selection'] == 85]
    require(len(report['obligations']) == len(obligations) == 22 and all(
        all(row[k] == base[k] for k in ('obligation_id', 'selection', 'route', 'check', 'kind'))
        for row, base in zip(report['obligations'], obligations, strict=True)), 'Titchy specialist denominator differs')
    return {'schema': 'bmk.m3-titchy-audit/1', 'run_id': report['run_id'], 'run_seal_id': seal['seal_id'],
            'plan_content_id': plan['plan_content_id'], **corpus,
            'specialized': audit_specialized(root, run, binding, report['obligations'], spec, replay=replay),
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}


def _audit_corpus(root, run, plan, rows, runtimes=None):
    definition = load_json(verify_asset(root, plan['definition']['plan']))
    entries = {e['id']: e for e in load_full_manifest(root, definition['bindings']['manifest'], parse=False)['datasets']}
    source, samples, parity = {}, [], {}
    totals = {key: Counter() for key in ROUTES}
    seen, sessions = set(), set()
    for decision, row in rows:
        require(all(row[k] == decision[k] for k in ('work_item_id', 'dataset_id', 'route', 'operation', 'applicability')) and
                row['status'] == 'verified' and row['applicability'] == 'input_domain_matches' and not row['reason'],
                'Titchy file-route status invalid')
        dataset, route = row['dataset_id'], row['route']
        require((dataset, route) not in seen and route in ROUTES, 'Titchy corpus decision duplicated or unknown')
        seen.add((dataset, route))
        entry = entries[dataset]
        if dataset not in source:
            source[dataset] = _originals(root, entry)
        whole, blocks = source[dataset]
        evidence, units = row['evidence'], row['evidence']['units']
        step = entry['rows'] if route == 'packet-stream' else CHUNK_ROWS
        expected_ranges = [(i, [p, min(entry['rows'], p+step)]) for i in range(entry['value_count']) for p in range(0, entry['rows'], step)]
        require(evidence['driver'] == ROUTES[route] and not evidence['timing_admitted'] and
                [(u['column'], u['row_range']) for u in units] == expected_ranges and
                len(units) == decision['input']['size_estimate']['input_units'] and
                evidence['input_bytes'] == decision['input']['size_estimate']['native_input_bytes_one_pass'] ==
                sum(u['logical_input_bytes'] for u in units) and evidence['artifact_bytes'] == sum(u['artifact_bytes'] for u in units),
                'Titchy planned input or artifact accounting differs')
        if route == 'packet-stream':
            require([u['restored_sha256'] for u in units] == whole and all(
                u['artifact_bytes'] == u['archive_framing_bytes'] + u['payload_bytes'] + u['config_bytes'] and
                u['padding_samples'] == (-entry['rows']) % POLICY['chunk'] for u in units),
                'Titchy stream whole-column digest or packet costs differ')
            totals[route].update({'packets': sum(u['encode']['packets'] for u in units),
                                  'packets_before_finish': sum(u['packets_before_finish'] for u in units)})
        else:
            part = 'native_sha256' if route == 'batch' else 'sha256'
            signature = [(u[part], u['header_bytes'], u['index_bytes'], u['dictionary_and_payload_bytes']) for u in units]
            require(parity.setdefault(dataset, signature) == signature, 'Titchy batch and access native payloads differ')
            if route == 'batch':
                require([u['restored_sha256'] for u in units] == blocks and all(
                    u['artifact_bytes'] == u['native_frame_bytes'] + u['abi_envelope_bytes'] and
                    u['native_frame_bytes'] == u['header_bytes'] + u['index_bytes'] + u['dictionary_and_payload_bytes'] for u in units) and
                    evidence['native_frame_bytes'] == sum(u['native_frame_bytes'] for u in units) and
                    evidence['abi_envelope_bytes'] == sum(u['abi_envelope_bytes'] for u in units), 'Titchy batch recovery or fees differ')
                totals[route].update({k: evidence[k] for k in ('native_frame_bytes', 'abi_envelope_bytes')})
            else:
                require(all(u['artifact_bytes'] == u['header_bytes'] + u['index_bytes'] + u['dictionary_and_payload_bytes'] for u in units),
                        'Titchy access artifact accounting differs')
        sample = _sample(root, run, plan, row, runtimes)
        require(sample['restored_sha256'] == (whole if route == 'packet-stream' else blocks)[0], 'Titchy sample does not restore declared source')
        if runtimes is not None:
            session = sample['process']['session_id']
            require(session and session not in sessions, 'Titchy isolated replay did not use a fresh session')
            sessions.add(session)
        samples.append(sample)
        totals[route].update(files=1, units=len(units), input_bytes=evidence['input_bytes'], artifact_bytes=evidence['artifact_bytes'])
    require(seen == {(dataset, route) for dataset in entries for route in ROUTES}, 'Titchy corpus projection omitted a route or file')
    return {'totals': totals, 'native_batch_access_parity': True, 'replayed_samples': samples}


def verify_full_corpus(root, plan_path, run):
    plan = load_json(plan_path)
    ledger, seal_id = full_run_source(plan, run)
    binding = plan['specialized']['titchy']
    launchers = launcher_lock()
    require(binding['launchers'] == launchers, 'Titchy replay launchers differ')
    controls = {k: plan['build'][v] for k, v in (('access', 'titchy_access'), ('packet-stream', 'titchy_stream'))}
    require(controls['access']['dependency'] == controls['packet-stream']['dependency'], 'Titchy native libraries differ')
    for ref in (controls['access']['dependency'], *(b['executable'] for b in controls.values())):
        require(verify_asset(root, ref).stat().st_size == ref['bytes'], 'Titchy audit runtime size differs')
    direct = plan_recovery(root, {}, (), tools={k: {field: b['executable'][field] for field in ('path', 'sha256')}
                                               for k, b in controls.items()}, libraries=[controls['access']['dependency']])
    rows = ((decision, row) for row, decision in full_run_rows(plan, ledger)
            if row.get('entry_kind') is None and decision['selection'] == 85)
    with tempfile.TemporaryDirectory(prefix='m3-titchy-full-runtime-') as tmp:
        stage_recovery(root, Path(tmp), direct)
        runtimes = {'direct': (Path(tmp) / DIRECTORY, direct),
                    'batch': (run / 'titchy-specialized' / DIRECTORY, binding['decoder'])}
        corpus = _audit_corpus(root, run, plan, rows, runtimes)
    doc = {'schema': 'bmk.m3-titchy-full-corpus-replay/1', 'run_id': run.name, 'run_seal_id': seal_id,
            'plan_content_id': plan['plan_content_id'], 'scope': 'native_corpus_samples_excludes_specialist_products',
            'launchers': launchers, 'direct_runtime': direct, 'batch_recovery_id': binding['decoder']['recovery_id'],
            'limits': LIMITS, **corpus,
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}
    return {**doc, 'audit_id': content_id(doc)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--replay', action='store_true')
    parser.add_argument('--full-ledger', action='store_true', help='audit and isolate replay of corpus samples from a full run')
    parser.add_argument('--out', type=Path, help='write a new JSON audit only after verification')
    args = parser.parse_args()
    if args.full_ledger and args.replay:
        parser.error('--replay is for specialist products in a route-filtered preflight; --full-ledger replays corpus samples')
    run = args.run.resolve(strict=True)
    audit = verify_full_corpus(ROOT, args.plan, run) if args.full_ledger else verify(ROOT, args.plan, run, replay=args.replay)
    if args.out is None:
        print(json.dumps(audit, indent=2))
    else:
        write_new(args.out, audit)
