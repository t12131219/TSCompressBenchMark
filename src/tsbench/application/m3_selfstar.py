"""Execute one ordered, bit-exact SElf* product per planned full V column."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from ..assets import ContractError, digest, local_file, require
from ..planner import selfstar_execution as suite
from ..planner.m3_selfstar import CORPUS_TOOL, DRIVERS
from ..planner.selfstar import BLOCK, HEADER
from ..qualification.selfstar_wire import read_frame
from ..recovery import DIRECTORY, stage_recovery
from ..supervisor.isolated_worker import launcher_lock
from . import selfstar_execution as probe
from .batch_execution import _files
from .m3_sprintz_query import _stage


def launch(root, binding, live, directory, operation, args):
    decoder = binding['decoder']
    binary = decoder['tools'][CORPUS_TOOL] if live else decoder['worker']
    command = [str(local_file(root, decoder['files'][binary]['source'])), operation]
    if not live:
        library = decoder['files'][decoder['plugins'][suite.PLUGIN]]
        command += [str(local_file(root, library['source'])), suite.PLUGIN, '{}']
    start = time.monotonic_ns()
    proc = subprocess.run([*command, *map(str, args)], cwd=directory, env={'LC_ALL': 'C'},
                          timeout=30, capture_output=True, text=True)
    wall = time.monotonic_ns() - start
    require(proc.returncode == 0 and not proc.stderr,
            f'SElf* {operation} failed ({proc.returncode}): {proc.stderr.strip()}')
    return [json.loads(line) for line in proc.stdout.splitlines() if line], wall


def wire_facts(wire, rows, schema):
    records = read_frame(wire, 64, rows, schema)
    native_bytes = sum(len(payload) for _, _, payload in records)
    require(HEADER.size + len(schema) + len(records)*4 + native_bytes == len(wire), 'SElf* byte accounting differs')
    return {'blocks': len(records), 'last_block_rows': records[-1][0], 'native_bits': sum(b for _, b, _ in records),
            'native_payload_bytes': native_bytes, 'block_header_bytes': len(records)*4,
            'object_envelope_bytes': HEADER.size + len(schema), 'artifact_bytes': len(wire)}


def _native_facts(facts):
    return {k: facts[k] for k in ('blocks', 'native_bits', 'native_payload_bytes')}


def _live_adds(rows):
    full, tail = divmod(rows, BLOCK)
    return full*5 + sum(tail > endpoint for endpoint in (0, 1, 8, 71, 192))


def validate_profiles(enc, dec, live, rows, facts):
    counts = _native_facts(facts)
    if live:
        before = enc[0].get('prefinish_bits') if enc else None
        require(type(before) is int and 0 < before < counts['native_bits'] and
                enc == [{'mode': 'live', 'rows': rows, **counts, 'add_calls': _live_adds(rows), 'prefinish_bits': before}] and
                dec == [{'mode': 'read-finalized', 'rows': rows, **counts, 'add_calls': 0, 'prefinish_bits': 0}],
                'SElf* add/finish or drain profile differs')
        return {'add_calls': enc[0]['add_calls'], 'prefinish_bits': before}
    profile = {'backend': 'selfstar-c-scalar', 'mode': 'batch', 'threads': 1, 'fallback': False,
               'block_values': BLOCK, 'block_header_bytes': facts['block_header_bytes'], **counts}
    require(enc == [{**profile, 'operation': 'encode'}] and
            dec == [{'columns': [{'dtype': 10, 'count': rows}]}, {**profile, 'operation': 'decode'}],
            'SElf* public ABI batch profile differs')
    return None


def restore(root, binding, live, work, wire):
    require({p.name for p in work.iterdir()} == {wire.name} and wire.parent == work, 'SElf* decoder input directory is not detached')
    return launch(root, binding, live, work, 'read-finalized' if live else 'decode-columns',
                  [wire.name, 'raw', 'schema'] if live else [wire.name, 'schema', 'raw'])


def run_selfstar(root, plan, item, entry, work, run):
    binding = plan['specialized']['selfstar']
    key = item['selection'], item['route']
    live = item['route'] == suite.LIVE
    rows, cols, extent = entry['rows'], entry['value_count'], item['input']
    require(0 < rows * 8 <= 64 << 20 and extent['value_column_range'] == [0, cols] and
            len(extent['row_ranges']) == 1 and (extent['row_ranges'][0]['start'], extent['row_ranges'][0]['end']) == (0, rows) and
            extent['full_extent_of_file_rows_and_value_columns'] and extent['representation'] == 'f64_columns' and
            not extent['planned_transforms'] and extent['slice_extent']['max_per_unit'] is None and
            extent['column_grouping'] == 'one_work_unit_series_per_value_column' and
            extent['size_estimate']['input_units'] == cols and extent['size_estimate']['native_input_bytes_one_pass'] == 8*rows*cols,
            'SElf* plan requires one complete original-bit-pattern V object per column')
    staged = _stage(root, entry, work / 'values')
    units = []
    samples = {}
    for col, raw in enumerate(staged):
        try:
            require(raw.stat().st_size == rows * 8, 'SElf* column staged wrong extent')
            expected_sha = digest(raw)
            schema = json.dumps({'role': 'value', 'dtype': 'f64', 'rows': rows, 'column_index': col,
                                 'state': 'ordered-per-column', 'native_block_values': BLOCK}, sort_keys=True,
                                separators=(',', ':')).encode()
            with tempfile.TemporaryDirectory(prefix='selfstar-col-', dir=work) as td:
                encode = Path(td) / 'encode'
                decode = Path(td) / 'decode'
                encode.mkdir()
                decode.mkdir()
                (encode / 'schema').write_bytes(schema)
                wire = decode / 'frame.bmk'
                enc, enc_ns = launch(root, binding, live, encode, 'live' if live else 'encode',
                                     [raw, 'schema', wire] if live else ['10', raw, 'schema', wire])
                require(0 < wire.stat().st_size <= suite.frame_limit(64, rows, len(schema)), 'SElf* artifact exceeds fee bound')
                facts = wire_facts(wire.read_bytes(), rows, schema)
                raw.unlink()  # The verifier uses the original digest, not a shared plaintext file.
                dec, dec_ns = restore(root, binding, live, decode, wire)
                replayed = decode / 'raw'
                require((decode / 'schema').read_bytes() == schema and
                        replayed.stat().st_size == rows*8 and digest(replayed) == expected_sha,
                        'SElf* recovered schema or raw column bits differ')
                details = validate_profiles(enc, dec, live, rows, facts)
                unit = {'column': col, 'row_range': [0, rows], 'input_bytes': rows*8, 'restored_sha256': expected_sha,
                        'schema_sha256': sha256(schema).hexdigest(), 'frame_sha256': digest(wire), **facts,
                        'lifecycle': details, 'process_wall_ns': {'encode': enc_ns, 'decode': dec_ns}}
                if col == 0:
                    relative = Path('retained') / item['work_item_id'] / 'full-column-zero.bmk'
                    (run / relative).parent.mkdir(parents=True)
                    shutil.copyfile(wire, run / relative)
                    samples = {'path': relative.as_posix(), 'sha256': unit['frame_sha256'], 'bytes': facts['artifact_bytes']}
                units.append(unit)
        except (ContractError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise ContractError(f'SElf* V column {col}: {exc}') from exc
    totals = {name: sum(u[name] for u in units) for name in ('blocks', 'input_bytes', 'artifact_bytes', 'native_bits',
              'native_payload_bytes', 'block_header_bytes', 'object_envelope_bytes')}
    return {'driver': DRIVERS[key], 'columns': cols, 'rows': rows, 'units': units, 'retained_sample': samples,
            'backend': 'selfstar-c-scalar', 'threads': 1, 'state_scope': 'one_directional_context_across_full_column',
            'clock_scope': 'diagnostic_process_wall_includes_startup_io_not_m2', 'timing_admitted': False, **totals}


def _selection(binding, rows):
    mapping = binding['obligation_slots']
    require(all(r['selection'] == 4 and r['obligation_id'] in mapping for r in rows), 'SElf* obligation binding differs')
    return sorted({sid for row in rows for sid in mapping[row['obligation_id']]})


def _terminal(slot, product):
    return product['status'] == ('expected_rejection' if slot['expected_status'] else 'verified')


def run_specialized(root, run, binding, rows, append):
    folder = run / 'selfstar-specialized'
    folder.mkdir()
    products, _ = suite.selfstar_inputs(root)
    require(binding['slots'] == {sid: s for sid, (s, _) in products.items()}, 'SElf* frozen fixtures differ')
    ids = _selection(binding, rows)
    observed = {}
    try:
        require(launcher_lock() == binding['launchers'], 'SElf* launchers changed')
        stage_recovery(root, folder, binding['decoder'])
    except (ContractError, OSError) as exc:
        for row in rows:
            row.update(status='dependency_failed', reason=str(exc))
    else:
        for name in ('products', 'logs'):
            (folder / name).mkdir()
        for sid in ids:
            slot, sample = products[sid]
            result = observed[sid] = probe.run_slot(folder, binding, slot, sample, lambda: False)
            append({'entry_kind': 'specialized_product', 'selection': 4, **result})
        for row in rows:
            slots = binding['obligation_slots'][row['obligation_id']]
            errors = [f"{binding['slots'][sid]['name']}: {observed[sid]['status']} ({observed[sid]['reason']})"
                      for sid in slots if not _terminal(binding['slots'][sid], observed[sid])]
            row.update(status='failed' if errors else 'verified', reason='; '.join(errors),
                       evidence={'driver': binding['driver'], 'fixture_slots': slots})
    return {'driver': binding['driver'], 'recovery_id': binding['decoder']['recovery_id'], 'fixtures': observed,
            'statuses': dict(Counter(f['status'] for f in observed.values())), 'files': _files(folder)}


def audit_specialized(root, run, binding, rows, evidence, *, replay=False):
    folder = run / 'selfstar-specialized'
    spec = binding['decoder']
    fixtures, files = evidence['fixtures'], evidence['files']
    require(evidence['driver'] == binding['driver'] and evidence['recovery_id'] == spec['recovery_id'] and
            set(fixtures) == set(_selection(binding, rows)) and files == _files(folder) and
            evidence['statuses'] == dict(Counter(f['status'] for f in fixtures.values())), 'SElf* specialist evidence differs')
    closure = {f'{DIRECTORY}/{name}': {'path': f'{DIRECTORY}/{name}', 'bytes': ref['bytes'], 'sha256': ref['sha256']}
               for name, ref in spec['files'].items()}
    require({key: val for key, val in files.items() if key.startswith(DIRECTORY + '/')} == closure,
            'SElf* staged closure differs')
    allowed = set(closure)
    for row in rows:
        require(row['status'] == 'verified' and not row['reason'] and
                row['evidence'] == {'driver': binding['driver'], 'fixture_slots': binding['obligation_slots'][row['obligation_id']]},
                'SElf* specialist obligation unverified')
    if replay:
        require(launcher_lock() == binding['launchers'], 'SElf* audit launchers changed')
    products, _ = suite.selfstar_inputs(root)
    replayed = []
    for sid, row in fixtures.items():
        slot = binding['slots'][sid]
        require(row['product_slot'] == sid and _terminal(slot, row) and
                probe.inspect_evidence(folder, binding, slot, row, files, allowed), 'SElf* specialist fixture unverified')
        if replay and not slot['expected_status']:
            replayed.append(probe.restore_slot(folder, binding, slot, row))
        elif replay:
            with tempfile.TemporaryDirectory(prefix='selfstar-refusal-replay-') as td:
                path = Path(td)
                work = path / 'work'
                work.mkdir()
                sample = products[sid][1]
                raw, schema = path / 'raw', path / 'schema'
                raw.write_bytes(sample.columns[0]); schema.write_bytes(sample.schema)
                out, op = probe._run(folder, binding, slot, work, path, suite.ABI_ENCODE, {'raw': raw, 'schema': schema},
                                     ['/inputs/schema', '/out/frame', str(slot['dtype']), '/inputs/raw'], lambda: False, None)
                require(probe._status(op, path, suite.ABI_ENCODE, slot['expected_status']) and not list(out.iterdir()),
                        'SElf* expected refusal did not replay')
                replayed.append({'product_slot': sid, 'expected_status': slot['expected_status']})
    require(files.keys() == allowed, 'SElf* specialist has undeclared retained files')
    return {'verified_obligations': len(rows), 'fixture_statuses': evidence['statuses'], 'replayed': replayed}
