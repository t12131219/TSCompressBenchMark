"""Sprintz public ABI corpus roundtrips and isolated specialist products in one M3 run."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import tempfile
import time

from ..assets import ContractError, local_file, require
from ..planner import sprintz_execution as native_plan
from ..planner.m3_sprintz import DRIVER
from ..qualification.sprintz import GROUP_HEADER, check_sfb1
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import sprintz_execution as native
from .batch_execution import _files
from .m3_sprintz_query import HEADER, LANES, MESSAGE_BYTES, ROWS, SprintzHardwarePending, _stage


def _slot_plan(binding, slot):
    return {**binding, 'limits': {**binding['limits'], 'file_bytes': native_plan.file_limit(slot)}}


def _call(worker, library, direct, cwd, mode, *args):
    env = {'LC_ALL': 'C'}  # No inherited dynamic-loader overrides.
    tick = time.monotonic_ns()
    p = subprocess.run([str(worker), mode, str(library), native_plan.PLUGIN, '{}', *args],
                       cwd=cwd, env=env, capture_output=True, text=True, timeout=15)
    wall = time.monotonic_ns() - tick
    if p.returncode == 3 and p.stderr.startswith('plugin status 1:'):
        witness = subprocess.run([str(direct), 'reject'], cwd=cwd, env=env, capture_output=True,
                                 text=True, timeout=15)
        if witness.returncode == 77 and witness.stdout.strip() == native_plan.ISA_SKIP:
            raise SprintzHardwarePending(native_plan.ISA_SKIP)
    require(p.returncode == 0 and not p.stderr, f'Sprintz public ABI {mode} failed ({p.returncode}): {p.stderr.strip()}')
    report = [json.loads(line) for line in p.stdout.splitlines() if line]
    profile = {'lanes': LANES, 'threads': 1, 'algorithm': 'fire', 'path': 'generic_rle'}
    direction = 'encode' if mode == 'encode' else 'decode'
    require(len(report) == (1 if direction == 'encode' else 2) and report[-1] == {**profile, 'operation': direction},
            'Sprintz public ABI execution profile differs')
    return report, wall


def verify_frame(frame, raw, schema):
    start = GROUP_HEADER.size + len(schema)
    require(0 < len(raw) <= MESSAGE_BYTES and len(raw) % (LANES * 2) == 0 and
            start + HEADER.size <= len(frame) <= start + HEADER.size + 4 * MESSAGE_BYTES and
            GROUP_HEADER.unpack_from(frame) == (b'BMKSPR\x01\x00', 4, len(raw) // 2, len(schema), len(frame) - start) and
            frame[GROUP_HEADER.size:start] == schema, 'Sprintz public ABI frame schema/count/extent differs')
    inner = frame[start:]
    check_sfb1(inner, {'width': 16, 'dims': LANES, 'count': len(raw) // 2, 'message_limit_bytes': MESSAGE_BYTES,
                       'algorithm': 1, 'path': 0}, raw)
    return inner


def run_batch(root, plan, item, entry, work, run):
    """No query, native-direct encoding, or shortcut can stand in for the public ABI."""
    binding = plan['specialized']['sprintz']
    build = binding['decoder']
    worker = local_file(root, build['files'][build['worker']]['source'])
    library = local_file(root, build['files'][build['plugins'][native_plan.PLUGIN]]['source'])
    direct = local_file(root, build['files'][build['tools'][native_plan.TOOL]]['source'])
    cols, rows, extent = entry['value_count'], entry['rows'], item['input']
    require(extent['value_column_range'] == [0, cols] and len(extent['row_ranges']) == 1 and
            (extent['row_ranges'][0]['start'], extent['row_ranges'][0]['end']) == (0, rows) and
            extent['slice_extent']['max_per_unit'] == ROWS and extent['full_extent_of_file_rows_and_value_columns'] and
            extent['planned_transforms'] == ['f64_bitcast_to_u16_le_limb0_to_limb3'], 'Sprintz public ABI input extent differs')
    encode_dir, decode_dir = work / 'encode', work / 'decode'
    encode_dir.mkdir()
    decode_dir.mkdir()
    paths = _stage(root, entry, work / 'columns')
    units = []
    sample = None
    for col, path in enumerate(paths):
        with path.open('rb') as source:
            for start in range(0, rows, ROWS):
                end = min(start + ROWS, rows)
                raw = source.read((end - start) * LANES * 2)
                require(len(raw) == (end - start) * LANES * 2, 'Sprintz staged column ended early')
                schema = (json.dumps({'role': 'value', 'dtype': 'u16', 'layout': 'f64-le-limbs-row-major',
                                      'lanes': LANES, 'rows': end - start}, sort_keys=True,
                                     separators=(',', ':')).encode())
                raw_path, schema_path = encode_dir / 'raw', encode_dir / 'schema'
                raw_path.write_bytes(raw)
                schema_path.write_bytes(schema)
                _, enc_ns = _call(worker, library, direct, encode_dir, 'encode', '4', 'raw', 'schema', 'frame')
                frame_path = decode_dir / 'frame'
                (encode_dir / 'frame').rename(frame_path)
                raw_path.unlink()
                schema_path.unlink()
                require(frame_path.stat().st_size <= GROUP_HEADER.size + len(schema) + HEADER.size + 4 * MESSAGE_BYTES,
                        'Sprintz public ABI emitted an oversized frame')
                frame = frame_path.read_bytes()
                sfb1 = verify_frame(frame, raw, schema)
                report, dec_ns = _call(worker, library, direct, decode_dir, 'decode-columns', 'frame', 'schema', 'raw')
                recovered = (decode_dir / 'raw').read_bytes()
                require(report[0] == {'columns': [{'dtype': 4, 'count': len(raw) // 2}]} and
                        recovered == raw and (decode_dir / 'schema').read_bytes() == schema,
                        'Sprintz public ABI detached recovery differs')
                for p in decode_dir.iterdir():
                    p.unlink()
                record = {'column': col, 'row_start': start, 'row_end': end, 'raw_bytes': len(raw),
                          'artifact_bytes': len(frame), 'abi_envelope_bytes': len(frame) - len(sfb1),
                          'sfb1_bytes': len(sfb1), 'frame_sha256': sha256(frame).hexdigest(),
                          'sfb1_sha256': sha256(sfb1).hexdigest(), 'restored_sha256': sha256(recovered).hexdigest(),
                          'schema_sha256': sha256(schema).hexdigest(),
                          'process_wall_ns': {'encode': enc_ns, 'decode': dec_ns}}
                units.append(record)
                if sample is None:
                    sample = (frame, record)
            require(not source.read(1), 'Sprintz staged column has trailing data')
    size = extent['size_estimate']
    require((len(units), sum(u['raw_bytes'] for u in units)) == (size['input_units'], size['native_input_bytes_one_pass']),
            'Sprintz public ABI corpus byte extent does not close')
    frame, observed = sample
    rel = Path('retained') / item['work_item_id'] / 'batch-sample.bmk'
    (run / rel).parent.mkdir(parents=True)
    (run / rel).write_bytes(frame)
    return {'driver': DRIVER, 'columns': cols, 'rows': rows, 'native_threads': 1, 'units': units,
            'input_bytes': size['native_input_bytes_one_pass'],
            **{key: sum(u[key] for u in units) for key in ('artifact_bytes', 'abi_envelope_bytes', 'sfb1_bytes')},
            'verification': 'detached_public_abi_worker_with_frame_only_each_artifact_bit_exact',
            'clock_scope': 'diagnostic_process_wall_includes_startup_io_not_m2', 'timing_admitted': False,
            'retained_sample': {'path': rel.as_posix(), 'bytes': len(frame), 'sha256': observed['frame_sha256'],
                                'observation': observed}}


def _selected(binding, rows):
    require(all(r['selection'] == 19 and r['obligation_id'] in binding['obligation_slots'] for r in rows),
            'Sprintz specialist rows differ from frozen mapping')
    return sorted({sid for r in rows for sid in binding['obligation_slots'][r['obligation_id']]})


def _terminal(row, slot):
    return row['status'] == ('expected_rejection' if slot['expected_status'] else 'verified')


def run_specialized(root, run, binding, rows, append):
    folder = run / 'sprintz-specialized'
    folder.mkdir()
    products, _ = native_plan.sprintz_inputs()
    require(binding['slots'] == {sid: slot for sid, (slot, _) in products.items()}, 'Sprintz specialist inputs changed')
    ids = _selected(binding, rows)
    results = {}
    try:
        require(launcher_lock() == binding['launchers'], 'Sprintz isolation launchers changed')
        stage_recovery(root, folder, binding['decoder'])
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed', reason=str(exc))
    else:
        for name in ('logs', 'products'):
            (folder / name).mkdir()
        for sid in ids:
            slot, sample = products[sid]
            result = results[sid] = native.run_slot(folder, _slot_plan(binding, slot), slot, sample, lambda: False)
            append({'entry_kind': 'specialized_product', 'selection': 19, **result})
        for row in rows:
            slots = binding['obligation_slots'][row['obligation_id']]
            bad = [results[sid] for sid in slots if not _terminal(results[sid], binding['slots'][sid])]
            statuses = {f['status'] for f in bad}
            terminal = 'verified' if not bad else 'hardware_pending' if statuses <= {'unsupported_platform'} else 'failed'
            row.update(status=terminal, reason='; '.join(f"{binding['slots'][f['product_slot']]['name']}: {f['reason']}" for f in bad),
                       evidence={'driver': binding['driver'], 'fixture_slots': slots})
    return {'driver': binding['driver'], 'recovery_id': binding['decoder']['recovery_id'], 'fixtures': results,
            'statuses': dict(Counter(f['status'] for f in results.values())), 'files': _files(folder)}


def audit_specialized(run, binding, rows, evidence, *, replay=False):
    folder = run / 'sprintz-specialized'
    spec = binding['decoder']
    fixtures, files = evidence['fixtures'], evidence['files']
    require(evidence['driver'] == binding['driver'] and evidence['recovery_id'] == spec['recovery_id'] and
            set(fixtures) == set(_selected(binding, rows)) and files == _files(folder) and
            evidence['statuses'] == dict(Counter(f['status'] for f in fixtures.values())), 'Sprintz specialist evidence differs')
    closure = {f'{DIRECTORY}/{name}': {'path': f'{DIRECTORY}/{name}', 'bytes': ref['bytes'], 'sha256': ref['sha256']}
               for name, ref in spec['files'].items()}
    require({key: val for key, val in files.items() if key.startswith(DIRECTORY + '/')} == closure,
            'Sprintz staged closure differs')
    allowed = set(closure)
    for r in rows:
        require(r['status'] == 'verified' and not r['reason'] and
                r['evidence'] == {'driver': binding['driver'], 'fixture_slots': binding['obligation_slots'][r['obligation_id']]},
                'Sprintz obligation is not verified')
    if replay:
        require(launcher_lock() == binding['launchers'], 'Sprintz audit isolation launchers changed')
    replayed = []
    products, _ = native_plan.sprintz_inputs()
    for sid, row in fixtures.items():
        slot = binding['slots'][sid]
        plan = _slot_plan(binding, slot)
        require(row['product_slot'] == sid and _terminal(row, slot) and native.inspect_evidence(folder, plan, slot, row, files, allowed),
                'Sprintz specialist product did not verify')
        if replay and not slot['expected_status']:
            replayed.append(native.restore_slot(folder, plan, slot, row))
        elif replay:
            with tempfile.TemporaryDirectory(prefix='m3-sprintz-refusal-audit-') as tmp:
                path = Path(tmp)
                ex = native.Runner(folder, plan, slot, path, path, lambda: False)
                _, sample = products[sid]
                inp = {'input': ex.stage('input', sample.columns[0]), 'schema': ex.stage('schema', sample.schema)}
                ex.invoke('encode', inp, [str(slot['dtype']), '/inputs/input', '/inputs/schema', 'frame'], (),
                          abi='encode', status=slot['expected_status'])
                replayed.append({'product_slot': sid, 'expected_status': slot['expected_status']})
    require(files.keys() == allowed, 'Sprintz specialist has undeclared retained files')
    return {'verified_obligations': len(rows), 'fixture_statuses': evidence['statuses'], 'replayed': replayed}
