"""Exact ALP/Titchy public-ABI corpus anchors and bounded detached driver."""
from collections import Counter
from contextlib import ExitStack
import os
from pathlib import Path
from struct import pack

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, require
from ..planner.m3_fixed_batch import AUTO, SCALAR
from ..qualification.linear_batch import HEADER
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import invoke_isolated_worker, launcher_lock, validate_limits
from .m3_abi_corpus_timing import br, files, groups, identities, name, verify_frames
from .m3_real_corpus_execution import _entry_map
from .m3_sealed_ledger import full_run_rows, full_run_source
from .m3_sprintz_query import _stage as stage_columns
from .m3_sprintz_timing import check, relative

SCHEMA = 'bmk.m3-column-batch-population/1'
ROUTES = {(9, 'auto-batch'): ('alp-auto', (SCALAR,)), (9, 'decode-backends'): ('alp-auto', (SCALAR, AUTO)),
          (85, 'batch'): ('titchy-batch', ('default',))}
ROWS = 65536
LIMITS = {'address_space_bytes': 512 << 20, 'file_bytes': 8 << 20, 'wall_seconds': 60}
CODE = ('native/measurement/column_batch/main.cpp', 'native/measurement/column_batch/CMakeLists.txt',
        'native/runtime/plugin_loader.cpp', 'native/runtime/plugin_loader.hpp', 'include/tsbench/plugin_abi.h',
        'src/tsbench/application/m3_column_batch.py', 'src/tsbench/application/m3_abi_corpus_timing.py',
        'src/tsbench/application/m3_sealed_ledger.py', 'src/tsbench/application/m3_sprintz_query.py',
        'src/tsbench/corpus_ingress.py', 'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py',
        'src/tsbench/supervisor/process.py', 'tools/m3_column_batch.py')


def schema(plugin, rows):
    data = {'role': 'value', 'rows': rows, 'dtype': 'f64' if plugin == 'alp-auto' else 'u64'}
    if plugin == 'titchy-batch':
        data['layout'] = 'f64-bitcast'
    return canonical_bytes(data)


def _titchy_native(op):
    return {'backend': 'titchy-c11', 'mode': 'batch', 'threads': 1, 'operation': op, 'entry': f'titchy_c_{op}'}


def project(item, entry, proof):
    plugin, backends = ROUTES[item['selection'], item['route']]
    nrows, cols = entry['rows'], entry['value_count']
    extent = item['input']
    span, = extent['row_ranges']
    require(item['plugin'] == plugin and item['canonical_object_id'] == span['object_id'] == entry['canonical']['object_id'] and
            span == {'object_id': item['canonical_object_id'], 'partition': 'full', 'start': 0, 'end': nrows} and
            extent['full_extent_of_file_rows_and_value_columns'] and not extent['skipped_row_ranges'] and
            extent['value_column_range'] == [0, cols] and extent['slice_extent']['max_per_unit'] == ROWS and
            extent['representation'] == ('f64_columns' if plugin == 'alp-auto' else 'u64_bitcast_per_f64_column'),
            'column batch does not bind the full original extent')
    expected = [(c, [lo, min(lo+ROWS, nrows)]) for c in range(cols) for lo in range(0, nrows, ROWS)]
    actual = [(u['column'], u['row_range']) for u in proof['units']]
    require(actual == expected and len(actual) == extent['size_estimate']['input_units'], 'column batch geometry differs')
    units = []
    for (column, span), row in zip(expected, proof['units'], strict=True):
        count = span[1] - span[0]
        schema_id = br(schema(plugin, count))
        if plugin == 'alp-auto':
            type_info = {'dtype': 10, 'count': count}
            require(row['original']['schema'] == schema_id and all(row['original'][k] == v for k, v in type_info.items()) and
                    row['decodes'].keys() == set(backends) and
                    all(d['restored'] == row['original'] for d in row['decodes'].values()), 'ALP fixed frame recovery differs')
            original, artifact = row['original']['raw'], row['artifact']
            envelope_bytes = HEADER.size + schema_id['bytes']
            native = {'encode': row['encode']['native'], **{b: row['decodes'][b]['native'] for b in backends}}
        else:
            require(row['schema_sha256'] == schema_id['sha256'] and row['abi_envelope_bytes'] == HEADER.size + schema_id['bytes'] and
                    row['artifact_bytes'] == row['native_frame_bytes'] + row['abi_envelope_bytes'], 'Titchy frame billing differs')
            original = {'bytes': row['logical_input_bytes'], 'sha256': row['restored_sha256']}
            artifact = {'bytes': row['artifact_bytes'], 'sha256': row['frame_sha256']}
            envelope_bytes = row['abi_envelope_bytes']
            native = {'encode': _titchy_native('encode'), 'default': _titchy_native('decode')}
        require(original['bytes'] == count * 8 and artifact['bytes'] > envelope_bytes, 'column batch byte extent differs')
        units.append({'column': column, 'row_range': span, 'schema': schema_id, 'original': original, 'artifact': artifact,
                      'cost': {'abi_envelope': envelope_bytes, 'native_frame': artifact['bytes'] - envelope_bytes}, 'native': native})
    require(sum(u['original']['bytes'] for u in units) == extent['size_estimate']['native_input_bytes_one_pass'] == cols*nrows*8,
            'column batch original bytes differ from plan')
    return units


def freeze(root, source_file, source_run, worker):
    validate_limits(LIMITS, file_ceiling=LIMITS['file_bytes'])
    source = load_json(source_file)
    ledger, seal = full_run_source(source, source_run)
    entries = _entry_map(root, load_json(check(root, source['definition']['plan'])))
    cases, excluded = [], []
    for row, item in full_run_rows(source, ledger):
        if 'entry_kind' in row or (key := (row['selection'], row['route'])) not in ROUTES:
            continue
        basis = {k: item[k] for k in ('dataset_id', 'route', 'selection', 'plugin', 'canonical_object_id', 'work_item_id',
                                      'operation_config_id', 'operation')}
        if row['status'] != 'verified':
            excluded.append({**basis, 'status': row['status'], 'reason': row['reason']})
            continue
        entry = entries[item['dataset_id']]
        units = project(item, entry, row['evidence'])
        body = {**basis, 'configuration': item['input'], 'source_file': entry['file'], 'decode_backends': ROUTES[key][1],
                'units': units, 'group_count': len(list(groups(units)))}
        cases.append({**body, 'case_id': content_id(body)})
    require({(c['selection'], c['route']) for c in cases} == ROUTES.keys(), 'no verified population for a required batch route')
    frozen = load_json(check(root, source['build']['lock']))
    require(frozen['build_id'] == source['build']['build_id'], 'column batch codec build identity differs')
    modules = {plugin: frozen['plugins'][plugin] for plugin, _ in ROUTES.values()}
    worker_ref = relative(root, worker)
    build = {'worker': worker_ref, 'plugins': modules, 'source_build_id': frozen['build_id']}
    runtime = plan_recovery(root, {**build, 'build_id': content_id(build)}, {p: {} for p in modules})
    body = {'schema': SCHEMA, 'source_plan': relative(root, source_file), 'source_run': source_run.relative_to(root).as_posix(),
            'source_seal': seal, 'worker': worker_ref, 'runtime': runtime, 'cases': cases, 'excluded': excluded,
            'limits': LIMITS, 'launchers': launcher_lock(), 'code': {p: digest(local_file(root, p)) for p in CODE},
            'timing_admitted': False, 'stage_accepted': False, 'qualification_granted': False}
    return {**body, 'population_id': content_id(body)}


def prepare_values(root, entry, case, work):
    units = case['units']
    require(entry['file'] == case['source_file'] and entry['canonical']['object_id'] == case['canonical_object_id'],
            'column batch staged source identity differs')
    paths = stage_columns(root, entry, work / 'columns')
    folder = work / 'values'
    folder.mkdir()
    with ExitStack() as stack:
        readers = [stack.enter_context(p.open('rb')) for p in paths]
        for g, (start, end) in enumerate(groups(units)):
            with (folder / name(g)).open('xb') as out:
                for u in units[start:end]:
                    lo, hi = u['row_range']
                    stream = readers[u['column']]
                    require(stream.tell() == lo*8, 'column batch staged coordinate differs')
                    bits, typed = stream.read((hi-lo)*8), schema(case['plugin'], hi-lo)
                    require(br(bits) == u['original'] and br(typed) == u['schema'], 'column batch original bits or schema differ')
                    out.write(pack('<II', len(bits), len(typed)))
                    out.write(typed)
                    out.write(bits)
        require(all(not f.read(1) for f in readers), 'column batch staging left unread values')
    return files(folder, case['group_count'])


def verify_census(case, slot, obs, cpu):
    units = case['units']
    require(obs['frames'] == len(units) and obs['groups'] == case['group_count'] and
            obs['raw_bytes'] == sum(u['original']['bytes'] for u in units) and
            obs['archive_bytes'] == sum(u['artifact']['bytes'] for u in units) and obs['cpu_endpoints'] == [cpu]*2 and
            min(obs['abi_wall_ns'], obs['context_create_wall_ns']) > 0, 'column batch call coverage or timing differs')
    actual = Counter()
    for part in obs['execution_census']:
        key, count = canonical_bytes(part['info']), part['count']
        require(type(count) is int and 0 < count <= len(units) and key not in actual, 'invalid column batch execution census')
        actual[key] = count
    require(actual == Counter(canonical_bytes(u['native'][slot]) for u in units), 'column batch effective native work differs')


def invoke(population, bundle, case, slot, inputs, work):
    require(slot == 'encode' or slot in case['decode_backends'], 'unplanned column batch operation')
    op = 'encode' if slot == 'encode' else 'decode'
    options = {'decode_backend': SCALAR if op == 'encode' else slot} if case['plugin'] == 'alp-auto' else {}
    require(set(inputs) == {name(i) for i in range(case['group_count'])}, 'column batch input group inventory differs')
    cpu, = os.sched_getaffinity(0)
    work.mkdir()
    out, proc = invoke_isolated_worker(bundle, population['runtime'], {'plugin': case['plugin'], 'options': options}, LIMITS,
                                       work, work, op, inputs, ['/inputs', '/out', str(len(inputs))], lambda: False,
                                       observe=True, file_ceiling=LIMITS['file_bytes'])
    error = (work / (op + '.stderr')).read_text()
    require(proc['status'] == 'completed' and proc['returncode'] == 0 and not error,
            f"{case['dataset_id']} {case['route']} {slot}: {proc['status']}: {error[:300]}")
    obs = load_json(work / (op + '.stdout'))
    verify_census(case, slot, obs, cpu)
    require(obs['abi_wall_ns'] + obs['context_create_wall_ns'] <= proc['process_wall_ns'] and
            proc['input_mounts'] == identities(inputs), 'column batch process scope or mounts differ')
    result = files(out, case['group_count'])
    return result, obs, proc
