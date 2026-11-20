"""Titchy public ABI product recovery and specialist evidence in the M3 ledger."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import time

from ..assets import ContractError, digest, local_file, require, verify_asset
from ..planner.m3_titchy import BATCH_DRIVER, inputs
from ..planner.typed_batch import TITCHY
from ..qualification.linear_batch import HEADER, parts
from ..qualification.titchy_wire import INDEX, TCHY, decode_tchy, native_bound
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import batch_execution as batch, titchy_execution as access, titchy_stream as stream
from .m3_sprintz_query import _stage
from .m3_titchy_access import CHUNK_ROWS, WIRE_POLICY


def stage_titchy(root, entry, work):
    return {'paths': _stage(root, entry, work / 'values'), 'rows': entry['rows']}


def invoke_abi(root, binding, cwd, mode, arguments):
    spec = binding['decoder']
    worker, library = [str(local_file(root, spec['files'][k]['source'])) for k in (spec['worker'], spec['plugins'][TITCHY])]
    start = time.monotonic_ns()
    proc = subprocess.run([worker, mode, library, TITCHY, '{}', *map(str, arguments)], cwd=cwd,
                          env={'LC_ALL': 'C'}, capture_output=True, text=True, timeout=30)
    ns = time.monotonic_ns() - start
    require(proc.returncode == 0 and not proc.stderr, f'Titchy public ABI {mode} failed ({proc.returncode}): {proc.stderr.strip()}')
    records = [json.loads(line) for line in proc.stdout.splitlines() if line]
    op = 'encode' if mode == 'encode' else 'decode'
    require(len(records) == (1 if op == 'encode' else 2) and records[-1] == {'threads': 1, 'mode': 'batch',
            'operation': op, 'backend': 'titchy-c11', 'entry': f'titchy_c_{op}'}, 'Titchy public ABI profile differs')
    return records, ns


def inspect_frame(frame, n, schema):
    slot = {'method': TITCHY, 'max_frame_bytes': HEADER.size + len(schema) + native_bound(n, 64, 4, 1000),
            'original': {'columns': [{'dtype': 8, 'count': n}], 'schema_bytes': len(schema),
                                           'schema_sha256': sha256(schema).hexdigest()}}
    recovered, inner = parts(frame, slot)
    require(recovered == schema and TCHY.size <= len(inner) <= native_bound(n, 64, 4, 1000), 'invalid Titchy ABI size')
    h = TCHY.unpack_from(inner)
    require(h[:9] == (b'TCHY', 2, 64, 4, 0, 1000, 250000, (1 << 64)-1, n), 'Titchy public ABI native header differs')
    index = h[-1] * INDEX.size
    require(TCHY.size + index <= len(inner), 'Titchy public ABI index exceeds frame')
    return inner, {'artifact_bytes': len(frame), 'native_frame_bytes': len(inner), 'abi_envelope_bytes': HEADER.size + len(schema),
                   'header_bytes': TCHY.size, 'index_bytes': index, 'dictionary_and_payload_bytes': len(inner) - TCHY.size - index}


def restore_batch(root, binding, work, frame):
    require({p.name for p in work.iterdir()} == {frame.name} and frame.parent == work, 'Titchy ABI decoder input not detached')
    return invoke_abi(root, binding, work, 'decode-columns', [frame.name, 'schema', 'raw'])


def run_batch(root, plan, item, entry, work, run):
    binding = plan['specialized']['titchy']
    extent, nrows, cols = item['input'], entry['rows'], entry['value_count']
    require(extent['full_extent_of_file_rows_and_value_columns'] and extent['value_column_range'] == [0, cols] and
            len(extent['row_ranges']) == 1 and (extent['row_ranges'][0]['start'], extent['row_ranges'][0]['end']) == (0, nrows) and
            extent['slice_extent']['max_per_unit'] == CHUNK_ROWS and extent['representation'] == 'u64_bitcast_per_f64_column',
            'Titchy public ABI planned extent differs')
    paths = stage_titchy(root, entry, work)['paths']
    encode, detached = work / 'encode', work / 'detached'
    encode.mkdir(); detached.mkdir()
    units, sample = [], None
    for col, path in enumerate(paths):
        with path.open('rb') as src:
            for start in range(0, nrows, CHUNK_ROWS):
                stop = min(start + CHUNK_ROWS, nrows)
                n = stop-start
                raw = src.read(n*8)
                require(len(raw) == n*8, 'Titchy public ABI input cut short')
                schema = json.dumps({'role': 'value', 'dtype': 'u64', 'layout': 'f64-bitcast', 'rows': n},
                                    sort_keys=True, separators=(',', ':')).encode()
                (encode / 'raw').write_bytes(raw); (encode / 'schema').write_bytes(schema)
                frame = detached / 'frame.bmk'
                _, enc = invoke_abi(root, binding, encode, 'encode', ['8', 'raw', 'schema', frame])
                (encode / 'raw').unlink(); (encode / 'schema').unlink()
                require(frame.stat().st_size <= HEADER.size + len(schema) + native_bound(n,64,4,1000), 'Titchy ABI frame oversized')
                wire = frame.read_bytes()
                payload, facts = inspect_frame(wire, n, schema)
                decoded, dec = restore_batch(root, binding, detached, frame)
                require(decoded[0] == {'columns': [{'dtype': 8, 'count': n}]} and
                        (detached / 'schema').read_bytes() == schema and (detached / 'raw').read_bytes() == raw,
                        'Titchy ABI detached recovery differs from original bits')
                row = {'column': col, 'row_range': [start, stop], 'logical_input_bytes': len(raw), **facts,
                       'frame_sha256': sha256(wire).hexdigest(), 'native_sha256': sha256(payload).hexdigest(),
                       'restored_sha256': sha256(raw).hexdigest(), 'schema_sha256': sha256(schema).hexdigest(),
                       'process_wall_ns': {'encode': enc, 'decode': dec}}
                if sample is None:
                    independent, _ = decode_tchy(payload, 64, n, WIRE_POLICY)
                    require(independent == raw, 'Titchy ABI native payload differs in independent reader')
                    rel = Path('retained') / item['work_item_id'] / frame.name
                    (run / rel).parent.mkdir(parents=True)
                    (run / rel).write_bytes(wire)
                    sample = {'path': rel.as_posix(), 'bytes': len(wire), 'sha256': row['frame_sha256']}
                units.append(row)
                for out in detached.iterdir():
                    out.unlink()
            require(not src.read(1), 'Titchy ABI staged input has trailing bytes')
    nbytes = sum(u['logical_input_bytes'] for u in units)
    estimate = extent['size_estimate']
    require(sample and (len(units), nbytes) == (estimate['input_units'], estimate['native_input_bytes_one_pass']),
            'Titchy public ABI input scope does not close')
    return {'driver': BATCH_DRIVER, 'units': units, 'columns': cols, 'input_bytes': nbytes, 'retained_sample': sample,
            **{k: sum(u[k] for u in units) for k in ('artifact_bytes', 'native_frame_bytes', 'abi_envelope_bytes')},
            'backend': 'titchy-c11', 'native_threads': 1, 'timing_admitted': False,
            'clock_scope': 'diagnostic_process_wall_includes_startup_io_not_m2'}


def _select(binding, rows):
    mapping = binding['obligation_slots']
    require(all(r['selection'] == 85 and r['obligation_id'] in mapping for r in rows), 'Titchy obligation scope differs')
    return sorted({sid for row in rows for sid in mapping[row['obligation_id']]})


def _driver(slot):
    if slot['method'] == TITCHY:
        return batch
    return stream if slot['name'] == 'packet-stream' else access


def _ok(slot, product):
    return product['status'] == ('expected_rejection' if slot.get('expected_status') else 'verified')


def run_specialized(root, run, binding, rows, append):
    folder = run / 'titchy-specialized'
    folder.mkdir()
    products, _ = inputs(root)
    require(binding['slots'] == {sid: slot for sid, (slot, _) in products.items()}, 'Titchy specialist fixture drift')
    ids = _select(binding, rows)
    actual = {}
    try:
        require(launcher_lock() == binding['launchers'], 'Titchy isolation launcher changed')
        stage_recovery(root, folder, binding['decoder'])
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed', reason=str(exc))
    else:
        for sub in ('logs', 'products', 'controls'):
            (folder / sub).mkdir()
        for sid in ids:
            slot, sample = products[sid]
            driver = _driver(slot)
            execute = batch._case if driver is batch else driver.run_slot
            result = actual[sid] = execute(folder, binding, slot, sample, lambda: False)
            append({'entry_kind': 'specialized_product', 'selection': 85, **result})
        for row in rows:
            slots = binding['obligation_slots'][row['obligation_id']]
            bad = [f"{binding['slots'][sid]['name']}: {actual[sid]['status']} ({actual[sid]['reason']})"
                   for sid in slots if not _ok(binding['slots'][sid], actual[sid])]
            row.update(status='failed' if bad else 'verified', reason='; '.join(bad),
                       evidence={'driver': binding['driver'], 'fixture_slots': slots})
    return {'driver': binding['driver'], 'recovery_id': binding['decoder']['recovery_id'], 'fixtures': actual,
            'statuses': dict(Counter(f['status'] for f in actual.values())), 'files': batch._files(folder)}


def _audit_batch(folder, plan, slot, sample, row, files, allowed, replay):
    sid = slot['product_slot']
    logs = folder / 'logs' / sid
    labels = batch._linear_order(plan, slot)
    ops = row['operations']
    require([op['operation'] for op in ops] == labels and len({op['session_id'] for op in ops}) == len(ops),
            'Titchy batch specialist operation order differs')
    for op in ops:
        for suffix in ('stdout', 'stderr'):
            name = f"logs/{sid}/{op['operation']}.{suffix}"
            require(files[name]['bytes'] <= plan['limits']['file_bytes'], 'Titchy specialist log outside limits')
            allowed.add(name)
    status = slot['expected_status']
    if status:
        require(batch._rejected_log(ops[0], logs, labels[0], status) and row['reason'] == batch.INPUT_STATUS[status] and
                all(row[k] is None for k in ('artifact', 'restored', 'payload_validation', 'control_payload', 'decoder_rejections')),
                'Titchy batch expected refusal differs')
    else:
        require(not row['reason'] and all(batch._completed(op) for op in ops if op['operation'] not in slot['reject_decodes']),
                'Titchy specialist execution incomplete')
        frame_ref, native_ref = row['artifact'], row['control_payload']
        for relative, ref in ((f'products/{sid}.bmk', frame_ref), (f'controls/{sid}.tchy', native_ref)):
            require(ref == files[relative], 'Titchy specialist retained reference differs')
            allowed.add(relative)
        frame = verify_asset(folder, frame_ref)
        require(row['payload_validation'] == batch._inspect(frame, slot, sample.columns[0]) and row['restored'] == slot['original'],
                'Titchy specialist recovered digest or wire differs')
        batch._verify_linear(plan, row, slot, folder, frame_ref, native_ref)
    if replay:
        with tempfile.TemporaryDirectory(prefix='m3-titchy-batch-replay-') as td:
            work = Path(td)
            if status:
                ins = {k: work / k for k in ('schema', 'v')}
                ins['schema'].write_bytes(sample.schema); ins['v'].write_bytes(sample.columns[0])
                out, op = batch._encode(folder / DIRECTORY, plan, slot, work, work, ins, lambda: False)
                require(batch._rejected_log(op, work, labels[0], status) and not list(out.iterdir()), 'Titchy refusal did not replay')
            else:
                require(batch._restore(folder / DIRECTORY, plan, slot, frame, work, work, lambda: False) == row['restored'],
                        'Titchy specialist detached replay differs')
                data = batch._titchy_control(folder / DIRECTORY, plan, slot, work / 'out' / 'v', frame,
                                             row['payload_validation'], work, lambda: False)
                require(sha256(data).hexdigest() == native_ref['sha256'] and
                        batch._rejected_decodes(folder / DIRECTORY, plan, slot, frame, work, lambda: False) == row['decoder_rejections'],
                        'Titchy specialist direct replay or malformed-frame rejection differs')
    return {'product_slot': sid, 'status': row['status'], 'replayed': replay}


def audit_specialized(root, run, binding, rows, evidence, *, replay=False):
    folder = run / 'titchy-specialized'
    fixtures, files = evidence['fixtures'], evidence['files']
    spec = binding['decoder']
    require(evidence['driver'] == binding['driver'] and evidence['recovery_id'] == spec['recovery_id'] and
            set(fixtures) == set(_select(binding, rows)) and files == batch._files(folder) and
            evidence['statuses'] == dict(Counter(f['status'] for f in fixtures.values())), 'Titchy specialist evidence differs')
    closure = {f'{DIRECTORY}/{name}': {'path': f'{DIRECTORY}/{name}', 'bytes': ref['bytes'], 'sha256': ref['sha256']}
               for name, ref in spec['files'].items()}
    require({k: v for k, v in files.items() if k.startswith(DIRECTORY + '/')} == closure, 'Titchy specialist closure differs')
    allowed = set(closure)
    for row in rows:
        require(row['status'] == 'verified' and not row['reason'] and row['evidence'] == {
            'driver': binding['driver'], 'fixture_slots': binding['obligation_slots'][row['obligation_id']]}, 'Titchy obligation not verified')
    if replay:
        require(launcher_lock() == binding['launchers'], 'Titchy replay launchers differ')
    products, _ = inputs(root)
    replayed = []
    for sid, row in fixtures.items():
        slot, sample = products[sid]
        require(row['product_slot'] == sid and _ok(slot, row), 'Titchy specialist product not verified')
        driver = _driver(slot)
        if driver is batch:
            r = _audit_batch(folder, binding, slot, sample, row, files, allowed, replay)
            if replay:
                replayed.append(r)
        else:
            require(driver.inspect_evidence(folder, binding, slot, row, files, allowed), 'Titchy native mechanism not verified')
            if replay:
                replayed.append(driver.restore_slot(folder, binding, slot, row))
    require(files.keys() == allowed, 'Titchy specialist has undeclared files')
    return {'verified_obligations': len(rows), 'fixture_statuses': evidence['statuses'], 'replayed': replayed}
