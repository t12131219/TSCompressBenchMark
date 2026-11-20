"""Derive diagnostic metric details from one sealed M3 functional ledger.

Work-unit dispersion is not the M2 matched-repeat distribution. Missing clocks
are explicit, and an available process clock never fills a missing native clock.
"""
from collections import Counter, defaultdict
from fractions import Fraction
from math import ceil

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, parse_json, require
from ..planner.m3_fixed_batch import DRIVER as FIXED
from .m3_ledger_census import CORPUS_STATES

SCHEMA = 'bmk.m3-functional-metric-details/1'
COORDINATES = ('dataset_id', 'selection', 'route', 'operation')
BATCH_PROCESS = 'isolated_worker_wall_including_launch_and_transport'
PAGE_NATIVE = 'pcodec_native_operation_wall_and_cpu'
GORILLA_NATIVE = 'gorilla_native_calls_excluding_staging_framing_and_validation'
SPRINTZ_NATIVE = 'sprintz_native_calls_excluding_framing_io_and_oracle'
TITCHY_NATIVE = 'titchy_memory_push_pop_finish_or_archive_decode'
PROCESS = 'directional_process_wall_including_startup_and_io'
SESSION_DRIVER = 'session_driver_since_loop_start_including_span_file_io'
PBEPLA_EVENT = 'replay_call_start_to_first_sink_including_source_passes_and_temp_io'


def distribution(values):
    require(values and all(type(v) is int and v >= 0 for v in values), 'invalid M3 metric observations')
    values = sorted(values)
    n = len(values)
    return {'count': n, 'sum': sum(values), 'min': values[0], 'p50_nearest_rank': values[ceil(n / 2)-1],
            'p95_nearest_rank': values[ceil(n * .95)-1], 'max': values[-1],
            'sample_basis': 'distinct_work_units_not_independent_repeats'}


class Observations:
    def __init__(self):
        self.groups = defaultdict(lambda: {'wall': [], 'bytes': [], 'cpu': [], 'rss': [], 'threads': set(), 'fallback': []})

    def add(self, operation, scope, wall, *, backend=None, logical=None, cpu=None, rss=None,
            threads=None, fallback=None, resource_scope=None):
        g = self.groups[operation, scope, backend or 'not_recorded', resource_scope or 'not_recorded']
        g['wall'].append(wall)
        g['bytes'].append(logical)
        g['cpu'].append(cpu)
        g['rss'].append(rss)
        if threads is not None:
            require(type(threads) is int and threads > 0, 'invalid M3 observed thread count')
            g['threads'].add(threads)
        if fallback is not None:
            require(type(fallback) is bool, 'invalid M3 observed fallback')
            g['fallback'].append(fallback)

    def facts(self):
        out = []
        for (operation, scope, backend, resource_scope), data in sorted(self.groups.items()):
            wall = distribution(data['wall'])
            known = lambda key: all(type(x) is int and x >= 0 for x in data[key])
            logical = sum(data['bytes']) if known('bytes') else None
            kind = ('driver_event' if scope in (SESSION_DRIVER, PBEPLA_EVENT) else
                    'process' if scope in (PROCESS, BATCH_PROCESS) else 'native')
            out.append({'operation': operation, 'clock_scope': scope, 'backend': backend, 'resource_scope': resource_scope,
                        'clock_kind': kind,
                        'wall_ns': wall, 'logical_bytes_measured': logical,
                        'logical_mib_per_second_over_sum': (logical * 1_000_000_000 / (wall['sum'] * (1 << 20))
                                                            if logical is not None and wall['sum'] else None),
                        'cpu_ns': distribution(data['cpu']) if known('cpu') else None,
                        'max_process_rss_bytes': max(data['rss']) if known('rss') else None,
                        'threads_reported': sorted(data['threads']),
                        'fallback_units': sum(data['fallback']) if len(data['fallback']) == wall['count'] else None,
                        'repeated_measurement_distribution': None})
        return out


def _bill(logical, full, parts, description):
    require(type(logical) is int and logical >= 0 and type(full) is int and full > 0 and
            all(type(v) is int and v >= 0 for v in parts.values()) and sum(parts.values()) == full,
            'M3 metric byte accounting differs')
    return {'logical_bytes': logical, 'complete_artifact_bytes': full, 'components': parts, 'component_semantics': description,
            'logical_over_complete_ratio': logical / full}


def _duplex_process(clock, units, backend, threads, get_logical):
    for u in units:
        for op, wall in u['process_wall_ns'].items():
            clock.add(op, PROCESS, wall, backend=backend, threads=threads,
                      logical=get_logical(u) if op in ('encode', 'decode') else None)


def _fixed(clock, e):
    full, schema_bytes, logical = 0, 0, 0
    for u in e['units']:
        n = u['input_bytes']
        logical += n
        full += u['artifact']['bytes']
        schema_bytes += u['original']['schema']['bytes']
        require(u['artifact']['bytes'] > 32 + u['original']['schema']['bytes'], 'M3 fixed-batch frame is missing encoded payload')
        # Encoder is counted once even when two processes decode the same bytes.
        for op, calls in [('encode', [u['encode']]), ('decode', u['decodes'].values())]:
            for call in calls:
                proc, native = call['process'], call['native']
                r = proc['child_usage']
                require(proc['status'] == 'completed' and proc['returncode'] == 0 and native['operation'] == op,
                        'M3 detached operation metadata disagrees with terminal state')
                clock.add(op, BATCH_PROCESS, proc['process_wall_ns'], backend=native['backend'],
                          logical=n, cpu=r['user_cpu_ns'] + r['system_cpu_ns'], rss=r['maxrss_bytes'], threads=native['threads'],
                          fallback=native.get('fallback'), resource_scope='wait4_isolated_child_process')
    headers = len(e['units']) * 32
    return _bill(logical, full, {'native_payload_bytes': full - schema_bytes - headers, 'embedded_schema_bytes': schema_bytes,
                                 'linear_frame_header_bytes': headers}, 'complete_linear_frames_without_external_deduplication')


def _pages(clock, e):
    units = e['units']
    _duplex_process(clock, units, e['lane'], None, lambda u: u['input_bytes'])
    for u in units:
        for op in ('encode', 'decode'):
            r = u[op]
            clock.add(op, PAGE_NATIVE, r['operation_wall_ns'], backend=e['lane'], logical=u['input_bytes'],
                      cpu=r['operation_cpu_ns'], rss=r['process_peak_rss_bytes'],
                      resource_scope='native_process_cpu_clock_and_entire_process_peak_rss')
    return _bill(e['input_bytes'], e['artifact_bytes'], {name: sum(u['encode'][name] for u in units)
                 for name in ('payload_bytes', 'meta_bytes', 'container_bytes')}, 'pcodec_page_payload_metadata_and_group_container')


def _gorilla(clock, e):
    for op, wall in e['process_wall_ns'].items():
        clock.add(op, PROCESS, wall, backend=e['backend'], threads=e['native_threads'])
    for u in e['units']:
        for op, wall in u['native_wall_ns'].items():
            # Native operation sees repeated T for every V column. This denominator
            # must not be replaced by the file's one-copy logical axis in a per-block clock.
            n = 16 * (u['row_range'][1] - u['row_range'][0]) if op in ('encode', 'decode', 'full_decode') else None
            clock.add(op, GORILLA_NATIVE, wall, backend=e['backend'], threads=e['native_threads'], logical=n)
    return _bill(e['unique_logical_axis_bytes'] + e['unique_logical_value_bytes'], e['artifact_bytes'],
                 {'complete_native_gorilla_frames_bytes': e['native_frame_bytes'], 'harness_framing_bytes': e['harness_framing_bytes']},
                 'one_logical_axis_native_frames_charge_repeated_t_and_native_headers')


def _titchy_stream(clock, e):
    units = e['units']
    _duplex_process(clock, units, None, None, lambda u: u['logical_input_bytes'])
    for u in units:
        for op in ('encode', 'decode'):
            clock.add(op, TITCHY_NATIVE, u[op]['wall_ns'], logical=u['logical_input_bytes'])
        clock.add('first_packet_' + u['first_packet_phase'], TITCHY_NATIVE, u['encode']['first_packet_ns'])
    return _bill(e['input_bytes'], e['artifact_bytes'], {q: sum(u[q] for u in units) for q in
                 ('payload_bytes', 'config_bytes', 'archive_framing_bytes')}, 'titchy_packet_archive_plus_config')


def _sprintz_query(clock, e):
    for op, wall in e['process_wall_ns'].items():
        clock.add(op, PROCESS, wall, logical=e['input_bytes'] if op in ('encode', 'decode') else None)
    for u in e['units']:
        for op, wall in u['native_wall_ns'].items():
            clock.add(op, SPRINTZ_NATIVE, wall, backend=u[op]['backend'] if op in ('auto', 'scalar') else None,
                      logical=u['raw_bytes'] if op in ('encode', 'decode') else None, threads=e['native_threads'])
    return _bill(e['input_bytes'], e['artifact_bytes'], {k: e[k] for k in ('payload_bytes', 'frame_header_bytes')},
                 'sfb1_bitsliced_f64_representation_not_original_value_statistics')


def _selfstar(clock, e):
    _duplex_process(clock, e['units'], e['backend'], e['threads'], lambda u: u['input_bytes'])
    return _bill(e['input_bytes'], e['artifact_bytes'], {k: e[k] for k in
                 ('native_payload_bytes', 'block_header_bytes', 'object_envelope_bytes')}, 'selfstar_column_envelope_and_native_blocks')


def _sprintz_batch(clock, e):
    _duplex_process(clock, e['units'], 'fire_generic_rle', e['native_threads'], lambda u: u['raw_bytes'])
    return _bill(e['input_bytes'], e['artifact_bytes'], {k: e[k] for k in ('sfb1_bytes', 'abi_envelope_bytes')},
                 'complete_sfb1_native_frames_and_abi_envelope')


def _titchy_access(clock, e):
    units = e['units']
    _duplex_process(clock, units, None, None, lambda u: u['logical_input_bytes'])
    scope = 'titchy_individual_native_calls_not_whole_query_process'
    for u in units:
        n = u['logical_input_bytes']
        for op, fact in [('encode', u['encode']), ('decode', u['access']['restore'])]:
            clock.add(op, scope, fact['wall_ns'], backend=fact['entry'], logical=n)
        access = u['access']
        if access.get('entry') == 'titchy_c_range':
            clock.add('range', scope, access['wall_ns'], backend=access['entry'])
        else:
            # A callback's requested bytes are not OS file-I/O metrics and
            # callback and file paths are distinct operations even on one frame.
            for mode in ('callback', 'file'):
                q = access[f'{mode}_queries']
                clock.add(f'{mode}_open', scope, access[f'{mode}_open']['wall_ns'])
                clock.add(f'{mode}_range', scope, q['range_observation']['wall_ns'])
                for key in ('point', 'bit'):
                    for obs in q[f'{key}_observations']:
                        clock.add(f'{mode}_{key}', scope, obs['wall_ns'])
    return _bill(e['input_bytes'], e['artifact_bytes'], {k: sum(u[k] for u in units) for k in
                 ('header_bytes', 'index_bytes', 'dictionary_and_payload_bytes')}, 'tchy_header_index_dictionary_and_payload')


def _huff0_fec1(clock, e):
    return _bill(e['input']['bytes'], e['complete_bytes'], e['byte_cost'], 'fec1_abi_and_native_subblock_charges')


def _session(clock, e):
    for op in ('encode', 'decode'):
        clock.add(f'{op}_first_output', SESSION_DRIVER, e[op]['first_output_driver_wall_ns'], backend=e['codec'])
    return _bill(e['source']['bytes'], e['frame']['bytes'], {'complete_native_frame_bytes': e['frame']['bytes']},
                 'complete_native_session_frame_has_no_extra_framework_container')


def _titchy_batch(clock, e):
    units = e['units']
    _duplex_process(clock, units, e['backend'], e['native_threads'], lambda u: u['logical_input_bytes'])
    return _bill(e['input_bytes'], e['artifact_bytes'], {k: sum(u[k] for u in units) for k in
                 ('abi_envelope_bytes', 'header_bytes', 'index_bytes', 'dictionary_and_payload_bytes')},
                 'abi_envelope_plus_tchy_header_index_dictionary_and_payload')


def _holdout_dictionary(clock, e):
    details = {'train_bytes': e['train_bytes'], 'holdout_bytes': e['holdout']['bytes'], 'phase': e['phase'],
               'failed_units': e['failed_units'], 'test_attempted': e['test_attempted']}
    if 'dictionary' not in e:
        return {}, details
    clock.add('train', 'zstd_dictionary_native_trainer_wall', e['training_native_ns'], logical=e['train_bytes'])
    parts = {'native_heldout_frame_bytes': sum(f['bytes'] for f in e['frames'] if f['status'] == 'verified'),
             'shared_dictionary_bytes': e['dictionary']['bytes']}
    require(parts['native_heldout_frame_bytes'] == e['verified_frame_bytes'] and
            sum(parts.values()) == e['verified_frame_bytes_plus_shared_dictionary_once'], 'Zstd held-out product charges differ')
    complete = not e['failed_units'] and sum(f['logical_bytes'] for f in e['frames'] if f['status'] == 'verified') == details['holdout_bytes']
    details.update(parts)
    return ({'dictionary_once': _bill(details['holdout_bytes'], sum(parts.values()), parts, 'heldout_only_training_cost_separate')}
            if complete else {}), details


def _huff0_table(clock, e):
    bills = {}
    for layout, p in e['profiles'].items():
        if p['status'] != 'verified':
            continue
        bills[f'{layout}X'] = _bill(e['holdout']['bytes'], p['complete_bytes'],
                                    {f'{k}_bytes': p[k]['bytes'] for k in ('model', 'frame', 'binding')},
                                    'heldout_blocks_with_one_serialized_model_and_binding')
    return bills, {'train_bytes': e['training']['bytes'], 'holdout_bytes': e['holdout']['bytes'],
                   'profile_statuses': {v: p['status'] for v, p in e['profiles'].items()}}


def _workers(clock, e):
    bills = {f'encode_lane:{lane}': _bill(e['source']['bytes'], r['frame']['bytes'],
             {'complete_native_frame_bytes': r['frame']['bytes']}, 'one_native_frame_per_encoder_configuration')
             for lane, r in e['encode'].items()}
    return bills, {'codec': e['codec'], 'unmet_worker_observations': e['unmet_worker_observations'],
                   'lanes': {kind: {k: {'jobs': r['observed']['jobs'], 'entry': r['observed']['entry'],
                                        'effective_parameters': r['observed']['effective_parameters']}
                                     for k, r in e[kind].items()}
                             for kind in ('encode', 'decode_own', 'decode_shared')},
                   'shared_and_own_decode_labels_can_reference_same_invocation': e['codec'] == 'xz'}


def _zfp(clock, e):
    bills, units = {}, e['units']
    n = e['input_bytes_one_pass']
    if isinstance(e['artifact_bytes'], dict):
        for lane, total in e['artifact_bytes'].items():
            parts = {f'{k}_bytes': sum(u['profiles'][lane][k]['bytes'] for u in units) for k in ('frame', 'metadata')}
            bills[f'field:{lane}'] = _bill(n, total, parts, 'reversible_field_payload_and_shape_metadata')
        configs = {lane: {k: units[0]['profiles'][lane]['encode'][k] for k in ('execution', 'configured_threads', 'chunk_blocks')}
                   for lane in e['artifact_bytes']}
        return bills, {'encoder_configurations': configs, 'worker_evidence': e['worker_evidence']}
    parts = {'mutated_array_bytes': sum(u['after_frame']['bytes'] for u in units),
             'shape_metadata_bytes': sum(u['metadata']['bytes'] for u in units)}
    bills['mutated_array'] = _bill(n, e['artifact_bytes'], parts, 'mutated_array_and_metadata_not_both_before_and_after')
    return bills, {'quality_rejected_units': e['quality_rejected_units'], 'windows': len(units),
                  'before_control_bytes': sum(u['before_frame']['bytes'] for u in units),
                  'rate_pairs': [list(x) for x in sorted({(u['config']['requested_rate'], u['config']['effective_rate']) for u in units})]}


def _progressive(clock, e):
    units = e['units']
    by_layer = defaultdict(list)
    for u in units:
        for layer in u.get('layers', []):
            require(layer['bytes'] == layer['header_bytes'] + layer['payload_bytes'], 'PBEP layer full cost differs')
            by_layer[layer['layer']].append((u['logical_input_bytes'], layer))
        if u.get('replay'):
            clock.add('first_sink', PBEPLA_EVENT, u['replay']['first_sink_ns'])
    bills, levels = {}, {}
    for layer, entries in sorted(by_layer.items()):
        n = sum(x[0] for x in entries)
        views = [x[1] for x in entries]
        parts = {k: sum(v[k] for v in views) for k in ('header_bytes', 'payload_bytes')}
        if len(views) == len(units):
            bills[f'prefix:{layer}'] = _bill(n, sum(parts.values()), parts, 'standalone_prefix_not_sum_of_all_prefixes')
        levels[str(layer)] = {'restored_windows': len(views), 'quality_passed_windows': sum(v['quality_passed'] for v in views),
                              'standalone_prefix_bytes': sum(parts.values()), 'incremental_payload_bytes': sum(v['layer_payload_bytes'] for v in views),
                              'max_exact_abs_error': str(max(Fraction(v['exact_max_abs_error']) for v in views))}
    replay = [u['replay'] for u in units if u.get('replay')]
    return bills, {'failed_units': e['failed_units'], 'quality_rejected_units': e['quality_rejected_units'], 'prefixes': levels,
                   'replay_io': None if not replay else {k: sum(row[k] for row in replay) for k in
                         ('native_passes', 'source_bytes_read', 'temp_bytes_read', 'temp_bytes_written', 'sink_bytes')}}


def _corad(clock, e):
    def process(op, proc, producer, logical=None):
        if proc['status'] != 'completed':
            return
        usage = proc['child_usage']
        clock.add(op, BATCH_PROCESS, proc['process_wall_ns'], backend=producer, logical=logical,
                  cpu=usage['user_cpu_ns'] + usage['system_cpu_ns'], rss=usage['maxrss_bytes'], resource_scope='wait4_isolated_child_process')

    if e['operation'] != 'heldout':
        for fit in e['fits']:
            for op, proc in fit['processes'].items():
                process(op, proc, e['producer'])  # NPY staging bytes are not a training throughput denominator.
        return {}, {k: e[k] for k in ('expected_fits', 'fit_statuses', 'model_bytes', 'deployment_metadata_bytes',
                                      'diagnostic_training_asset_bytes', 'heldout_statuses', 'heldout_product_charge')}
    bills, counts = {}, {}
    for producer, rows in e['evaluations'].items():
        parts = Counter()
        restored = 0
        complete = 0
        for row in rows:
            for op, proc in row['processes'].items():
                process(op.split('-')[0], proc, producer, row.get('logical_value_bytes'))
            if 'frame' in row:
                require(row['frame']['bytes'] == sum(row['frame_accounting'].values()), 'CORAD full frame cost differs')
                parts.update(row['frame_accounting'])
            if 'frame' in row and row['status'] in ('verified', 'quality_rejected'):
                restored += row['logical_value_bytes']
                complete += 1
        counts[producer] = {'frame_statuses': e['frame_statuses'][producer], 'produced_frame_bytes': sum(parts.values()),
                            'restored_value_bytes': restored}
        if complete and complete * len(e['evaluations']) == e['expected_frames'] and complete == len(rows):
            bills[f'producer:{producer}'] = _bill(restored, sum(parts.values()), dict(parts), 'heldout_frames_with_embedded_model_each')
    require(sum(p['produced_frame_bytes'] for p in counts.values()) == e['complete_frame_bytes'] and
            sum(p['restored_value_bytes'] for p in counts.values()) == e['logical_restored_value_bytes'], 'CORAD aggregate observed costs differ')
    return bills, {'per_producer': counts, 'training_decisions': e['training_decisions']}


ADAPTERS = {FIXED: _fixed, 'pcodec-pages-control/1': _pages, 'gorilla-corpus-control/1': _gorilla,
            'sprintz-corpus-query/1': _sprintz_query, 'selfstar-public-abi-column/1': _selfstar,
            'selfstar-native-finalized-column/1': _selfstar, 'titchy-stream-control/1': _titchy_stream,
            'sprintz-corpus-batch-abi/1': _sprintz_batch, 'titchy-access-control/1': _titchy_access,
            'huff0-fec1-corpus/1': _huff0_fec1, 'lzbench-corpus-session/1': _session,
            'titchy-corpus-batch-abi/1': _titchy_batch}
VARIANTS = {'zstd-dictionary-corpus/1': _holdout_dictionary, 'huff0-etb1-corpus/1': _huff0_table,
            'lzbench-corpus-workers/1': _workers, 'zfp-corpus-control/1': _zfp,
            'pbepla-corpus-control/1': _progressive, 'corad-same-run-corpus/1': _corad}


def _workload_details(driver, e):
    if driver == 'titchy-access-control/1':
        units = e['units']
        if e['read_counter_scope'] is None:
            return {'range_values': sum(u['access']['range_count'] for u in units), 'read_counter_scope': None}
        callback = defaultdict(list)
        for u in units:
            a = u['access']
            q = a['callback_queries']
            for label, rows in [('open', [a['callback_open']]), ('range', [q['range_observation']]),
                                ('point', q['point_observations']), ('bit', q['bit_observations'])]:
                callback[label].extend(rows)
        return {'read_counter_scope': e['read_counter_scope'], 'callback_only': {k: {
            'requested_bytes': distribution([r['requested_bytes'] for r in rows]),
            'calls': distribution([r['calls'] for r in rows])} for k, rows in sorted(callback.items())},
            'file_reader_io_bytes': None}
    if driver == 'titchy-stream-control/1':
        return {'first_packet_phase': dict(Counter(u['first_packet_phase'] for u in e['units'])),
                **{k: sum(u[k] for u in e['units']) for k in ('packets_before_finish', 'finish_chunks', 'padding_samples')}}
    if driver == 'gorilla-corpus-control/1':
        snaps = [u['snapshot'] for u in e['units'] if 'snapshot' in u]
        return {'native_input_bytes_including_repeated_t': e['input_bytes'], 'unique_axis_bytes': e['unique_logical_axis_bytes'],
                'snapshot_artifact_bytes_distinct_from_final': e['snapshot_artifact_bytes'],
                'resume_input_bytes': sum(u['resume_input_bytes'] for u in snaps) if snaps else None}
    if driver == 'lzbench-corpus-session/1':
        return {op: {k: e[op][k] for k in ('first_output_call', 'first_output_after_consumed_bytes',
                                            'first_output_bytes', 'finish_calls', 'effective_parameters')}
                for op in ('encode', 'decode')}
    return {}


def metric_row(item, observation, line):
    for k in (*COORDINATES, 'work_item_id', 'applicability'):
        require(observation[k] == item[k], 'M3 metric observation identity differs from plan')
    status = observation['status']
    if item['applicability'] == 'input_domain_matches':
        require(status in CORPUS_STATES, 'invalid applicable M3 metric status')
    else:
        require(status == item['applicability'] and not observation['evidence'], 'M3 domain exclusion has unexpected measurement')
    e = observation['evidence'] or {}
    driver = e.get('driver')
    clock = Observations()
    eligible = status == 'verified' and driver in ADAPTERS
    accounting = ADAPTERS[driver](clock, e) if eligible else None
    variants, specialized = VARIANTS[driver](clock, e) if driver in VARIANTS else ({}, {})
    if eligible:
        specialized.update(_workload_details(driver, e))
    timings = clock.facts()
    reason = ('non_verified_outcome_raw_evidence_retained' if e and status != 'verified' else
              'complete_recovery_product_not_established' if driver in VARIANTS else
              'not_normalized_for_this_evidence_driver' if e else 'no_terminal_measurement_evidence')
    absent = {}
    if not accounting and not variants:
        absent['byte_accounting'] = reason
    for kind in ('native', 'process'):
        found = any(r['clock_kind'] == kind for r in timings)
        if not found:
            absent[f'{kind}_timing'] = 'clock_not_available_in_observed_functional_evidence' if driver in VARIANTS else (
                'clock_not_recorded_by_functional_driver' if eligible else reason)
    absent['pipeline_full_timing'] = 'no_source_to_output_clock_in_this_diagnostic_view'
    absent['repeated_measurements'] = 'functional_work_units_are_not_m2_repeats'
    if accounting or variants:
        native_input = item['input']['size_estimate']
        wanted = native_input['unique_logical_axis_bytes'] + native_input['unique_logical_value_bytes']
        if driver in ('zstd-dictionary-corpus/1', 'huff0-etb1-corpus/1'):
            start, end = item['input']['training']['consumed_byte_range']
            require(specialized['train_bytes'] == end - start and specialized['holdout_bytes'] + end - start == wanted,
                    'M3 training/held-out denominator differs from the frozen split')
            wanted -= end - start  # Model production is not evaluated as compressed held-out data.
        require(all(b['logical_bytes'] == wanted for b in ([accounting] if accounting else variants.values())),
                'M3 metric logical bytes differ from the frozen domain')
    return {**{k: item[k] for k in (*COORDINATES, 'work_item_id', 'view', 'operation_config_id', 'route_contract_id',
                                    'canonical_object_id', 'applicability')},
            'status': status, 'reason': observation['reason'], 'driver': driver, 'ledger_line': line,
            'accounting': accounting, 'variant_accounting': variants, 'specialized_metrics': specialized,
            'alternate_costs_are_not_summed': bool(variants), 'rejected_evidence_not_timing_admitted': bool(e and status != 'verified'),
            'operations': timings, 'missing_metrics': absent, 'timing_admitted': False}


def extract(plan, run, output):
    """Stream one decision at a time; the detailed report need not fit in memory with the ledger."""
    seal, ledger, report = (local_file(run, n) for n in ('completion.json', 'ledger.jsonl', 'report.json'))
    id_ = plan['plan_content_id']
    require(id_ == content_id({k: v for k, v in plan.items() if k != 'plan_content_id'}), 'M3 metric plan identity differs')
    seal = load_json(seal)
    body = {'schema': 'bmk.m3-real-corpus-run-seal/1', 'run_id': run.name, 'plan_content_id': id_,
            'report_sha256': digest(report), 'ledger_sha256': digest(ledger)}
    require(seal == {**body, 'seal_id': content_id(body)}, 'M3 metric source seal differs')
    expected = {i['work_item_id']: i for i in plan['work_items']}
    seen, status, protocols, per_route = set(), Counter(), Counter(), defaultdict(Counter)
    with ledger.open(encoding='utf-8') as stream:
        for index, text in enumerate(stream, 1):
            entry = parse_json(text, f'M3 main ledger line {index}')
            if entry.get('entry_kind') is not None:
                # Specialist products and obligations are accounted for in the main
                # census and left in the same ledger, not interpreted as file metrics.
                continue
            sid = entry['work_item_id']
            require(sid in expected and sid not in seen, 'M3 metric ledger has duplicate or unknown corpus ID')
            seen.add(sid)
            row = metric_row(expected[sid], entry, index)
            output.write(canonical_bytes(row) + b'\n')
            status[row['status']] += 1
            protocols.update({g['clock_scope'] for g in row['operations']})
            group = per_route[row['selection'], row['route'], row['view'], row['operation'], row['operation_config_id']]
            group['decisions'] += 1
            group['with_byte_accounting'] += row['accounting'] is not None or bool(row['variant_accounting'])
            group['with_specialized_metrics'] += bool(row['specialized_metrics'])
            group['with_native_timing'] += 'native_timing' not in row['missing_metrics']
            group['with_process_timing'] += 'process_timing' not in row['missing_metrics']
    require(seen, 'M3 metric ledger has no corpus decision')
    return {'schema': SCHEMA, 'run_id': run.name, 'seal_id': seal['seal_id'], 'plan_content_id': id_,
            'work_items_in_plan': len(expected), 'decision_rows': len(seen), 'includes_all_plan_decisions': seen == expected.keys(),
            'decision_statuses': dict(status), 'decisions_by_observed_clock': dict(protocols),
            'routes': [{'selection': n, 'route': r, 'view': v, 'operation': o, 'operation_config_id': c, **counts}
                       for (n, r, v, o, c), counts in sorted(per_route.items())],
            'stage_accepted': False, 'qualification_granted': False, 'timing_admitted': False}
