"""Freeze real projected T-only and V-only cases, not synthetic partner columns."""
from struct import pack, unpack_from

from ..assets import canonical_bytes, content_id, digest, load_json, require, verify_asset
from ..contracts import load_contract
from ..ingress import load_typed_source, sha
from ..plugins import discover, resolve
from ..recovery import plan_recovery
from ..supervisor.isolated_worker import launcher_lock
from .comparison import freeze_comparison
from .tv import exact_ticks

SCHEMA = 'bmk.m3-real-axis-plan/2'
CHUNK = 512
LIMITS = {'address_space_bytes': 256 << 20, 'file_bytes': 1 << 20, 'wall_seconds': 10}
ROUTES = {'timestamps_only': ('gorilla-t-derived', 'raw-timestamp'), 'values_only': ('gorilla-v-derived', 'alp-auto')}
MAGIC = {'gorilla-t-derived': b'BMKGT1\0\0', 'gorilla-v-derived': b'BMKGV1\0\0',
        'raw-timestamp': b'BMKRT1\0\0', 'alp-auto': b'BMKALP\x01\x00'}
MS_SCHEMA, S_SCHEMA = b'{"time_unit":"ms"}', b'{"time_unit":"s"}'
OPTIONS = {'alp-auto': {'decode_backend': 'scalar-unfused'}}
NEGATIVES = {'tv-to-t': 1, 'tv-to-v': 1, 'wrong-dtype-t': 1, 'wrong-dtype-v': 1,
             'wrong-unit-t': 1, 'v-frame-to-t': 5, 't-frame-to-v': 5}
POLICY = {'mode': 'fresh_isolated_process_per_column_block', 'chunk_rows': CHUNK,
          'conversion': 't_exact_original_unit_to_ms_and_inverse_v_preserve_bits',
          'format': 'bmk.m3-axis-role-bundle/1', 'verification': 'artifact_each_and_original_domain',
          'size_scope': 'manifest_plus_all_complete_frames', 'timing': 'per_child_diagnostic_not_full_pipeline'}


def file_ref(base, path):
    return {'path': path.relative_to(base).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)}


def binding(root):
    paths = ('src/tsbench/planner/m3_axis_roles.py', 'src/tsbench/application/m3_axis_roles.py',
             'src/tsbench/planner/comparison.py', 'schemas/comparison-contract.schema.json', 'src/tsbench/planner/tv.py',
             'src/tsbench/ingress.py', 'src/tsbench/recovery.py', 'src/tsbench/supervisor/isolated_worker.py',
             'src/tsbench/supervisor/process.py')
    return {'code': {p: digest(root / p) for p in paths}, 'launchers': launcher_lock()}


def projection_doc(root, ref):
    doc = load_json(verify_asset(root, ref))
    require(doc['schema'] == 'bmk.m3-tv-real-source-projections/1' and
            doc['projection_id'] == content_id({k: v for k, v in doc.items() if k != 'projection_id'}),
            'real projection identity differs')
    return doc


def source_cases(root, projection):
    for group, row in sorted(projection['groups'].items()):
        original = verify_asset(root, row['original_file'])
        require(original.stat().st_size == row['original_file']['bytes'] and
                set(row['manifests']) == {'csv', 'txt', 'npy'}, 'M3 axis original or provider set differs')
        group_id = None
        for fmt, ref in sorted(row['manifests'].items()):
            verify_asset(root, ref)
            lineage, raw = load_typed_source(root, ref['path'])
            require(lineage['ingestion']['plugin'] == fmt and lineage['source_column_sha256'] == row['projected_column_sha256'],
                    'projected provider does not match original-source lineage')
            require(group_id is None or group_id == lineage['canonical_dataset_hash'], 'axis source providers disagree')
            group_id = lineage['canonical_dataset_hash']
            spec = lineage['ingestion']['object']
            require(row['row_range'][1] - row['row_range'][0] == spec['rows'] and len(raw) == 1 + len(spec['values']),
                    'axis projection geometry differs')
            yield group, fmt, ref, lineage, raw


def units(task, spec, raw):
    is_t = task == 'timestamps_only'
    sources = raw[:1] if is_t else raw[1:]
    cols = [spec['timestamp']] if is_t else spec['values']
    for col, (meta, data) in enumerate(zip(cols, sources, strict=True)):
        for start in range(0, spec['rows'], CHUNK):
            end = min(start + CHUNK, spec['rows'])
            values = data[start*8:end*8]
            encoded = exact_ticks(values, meta['unit'], 'ms') if is_t else values
            schema = MS_SCHEMA if is_t else canonical_bytes({'role': 'value', 'dtype': 'f64', 'column': meta['name']})
            unit = {'column': col, 'range': [start, end], 'count': end-start, 'dtype': 7 if is_t else 10,
                    'original_sha256': sha(values), 'codec_input': {'bytes': len(encoded), 'sha256': sha(encoded)},
                    'schema': {'bytes': len(schema), 'sha256': sha(schema)}}
            yield unit, encoded, schema


def rejection_anchor(cases):
    timestamp = next(case for case in cases if case['task'] == 'timestamps_only')
    value = next(case for case in cases if case['task'] == 'values_only' and
                 (case['group'], case['format'], case['source_group_id']) ==
                 (timestamp['group'], timestamp['format'], timestamp['source_group_id']))
    return timestamp, value


def non_exact_probe(data):
    tick, = unpack_from('<q', data)
    require(tick % 1000 == 0 and tick < 2**63 - 1, 'M3 role rejection needs a second-aligned starting tick')
    return {'from': 'ms', 'to': 's', 'input_hex': pack('<q', tick + 1).hex()}


def _comparison(contract, task, spec, original_id, worker):
    is_t = task == 'timestamps_only'
    return freeze_comparison(contract, {
        'schema': 'bmk.comparison-contract/1', 'purpose': 'development_diagnostic', 'track': 'original_task',
        'original': {'object_id': original_id, 'schema_id': content_id(spec), 'logical_bytes': 8 * spec['rows'] * len(spec['columns'])},
        'representation': None, 'task': task, 'control': None,
        'quality': {'kind': 'bitwise_exact', 'exact_components': ['T' if is_t else 'V'],
                    'max_abs_by_column': {}, 'exception_policy': 'preserve_bits'},
        'access': {'mode': 'batch_whole', 'mechanism': 'any_qualified', 'stream': None,
                   'ingress_id': content_id('typed_projection_setup_outside_clock'), 'partition_id': content_id(CHUNK),
                   'workload_id': content_id(task)},
        'resource': {'hardware_group_id': None, 'physical_cores': None, 'peak_resident_bytes': None,
                     'participant_threads': 1, 'max_serialized_bytes': LIMITS['file_bytes'], 'deadline_ns': LIMITS['wall_seconds'] * 10**9},
        'boundary': {'direction': 'roundtrip', 'extent': 'pipeline_service', 'lifecycle': 'process', 'state': 'reset_per_message',
                     'state_protocol_id': content_id(POLICY['mode']), 'cache_policy_id': content_id('uncontrolled'),
                     'ownership': 'copied_return', 'completion': 'result_ready', 'output_boundary_id': worker,
                     'size_scope': 'bundle', 'size_accounting_id': content_id(POLICY['size_scope']),
                     'measurement_protocol_id': content_id(POLICY['timing'])},
        'validation': {'strength': 'artifact_each', 'placement': 'outside_extent', 'protocol_id': content_id(POLICY['verification'])},
        'retention': {'samples_per_case_method': 1, 'independent_restore': True, 'retain_failures': True,
                      'dependency_policy_id': content_id('sealed_elf_file_closure')}})


def plan_roles(root, proj_path, build_path):
    source = file_ref(root, proj_path)
    projection = projection_doc(root, source)
    build = load_json(build_path)
    methods, ids = {}, {p for routes in ROUTES.values() for p in routes}
    require(ids <= build['plugins'].keys(), 'M3 role build missing a required route; no fallback')
    registry = discover(root, selected=ids)
    for task, plugins in ROUTES.items():
        for plugin in plugins:
            role = 'timestamp' if task == 'timestamps_only' else 'value'
            native = resolve(root, plugin, OPTIONS.get(plugin, {}), registry=registry)
            manifest = registry[plugin]['manifest']
            require(role in manifest['roles'] and 'timestamp_value' not in manifest['roles'] and
                    all(build['plugins'][plugin][k] == native[k] for k in ('manifest_id', 'options_schema_id')),
                    'M3 role has wrong role or build identity')
            methods[plugin] = {'plugin': plugin, 'role': role, 'task': task, 'options': native['options'],
                               'configuration_id': native['configuration_id'], 'format_id': manifest['format_id'],
                               'manifest_id': native['manifest_id'], 'library': build['plugins'][plugin]['library'],
                               'kind': 'c11_parent_bit_io_derivative' if plugin.startswith('gorilla-') else 'independent_provider'}
    decoder = plan_recovery(root, build, methods)
    contract = load_contract(root, 'comparison-contract')
    cases, probe = [], None
    for group, fmt, manifest, data, raw in source_cases(root, projection):
        spec = data['ingestion']['object']
        if probe is None:
            probe = non_exact_probe(exact_ticks(raw[0][:8], spec['timestamp']['unit'], 'ms'))
        for task in ROUTES:
            is_t = task == 'timestamps_only'
            schema = {'rows': spec['rows'], 'columns': [spec['timestamp']] if is_t else spec['values'],
                      'byte_order': 'little_endian', 'row_order': 'preserve'}
            restored_sha = data['source_column_sha256'][:1] if is_t else data['source_column_sha256'][1:]
            object_id = content_id(['bmk.m3-axis-original/1', schema, restored_sha])
            case = {'group': group, 'format': fmt, 'task': task, 'manifest': manifest,
                    'ingestion_id': data['ingestion_id'], 'source_group_id': data['source_group_id'],
                    'object_id': object_id, 'schema': schema, 'original_columns_sha256': restored_sha,
                    'comparison': _comparison(contract, task, schema, object_id, build['worker']['sha256']),
                    'units': [u for u, _, _ in units(task, spec, raw)]}
            cases.append({**case, 'case_id': content_id(case)})
    require(cases, 'M3 role plan has no source cases')
    t, v = rejection_anchor(cases)
    body = {'schema': SCHEMA, 'projection': source, 'build': file_ref(root, build_path), 'policy': POLICY, 'limits': LIMITS,
            'protocol': binding(root), 'decoder': decoder, 'methods': methods, 'cases': cases,
            'negative_statuses': NEGATIVES, 'rejection_anchor': {'T': t['case_id'], 'V': v['case_id'], 'unit_index': 0},
            'non_exact_probe': probe, 'qualification_granted': False, 'stage_accepted': False}
    return {**body, 'plan_content_id': content_id(body)}


def check_plan(plan):
    require(plan['schema'] == SCHEMA and plan['policy'] == POLICY and plan['limits'] == LIMITS and
            plan['negative_statuses'] == NEGATIVES and plan['qualification_granted'] is False and plan['stage_accepted'] is False and
            content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}) == plan['plan_content_id'], 'M3 axis plan identity differs')
    t, v = rejection_anchor(plan['cases'])
    require(plan['rejection_anchor'] == {'T': t['case_id'], 'V': v['case_id'], 'unit_index': 0},
            'M3 role rejection anchor differs from plan cases')
