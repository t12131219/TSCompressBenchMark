"""Freeze the 2.8 real-input scope; domain matches are not execution/admission."""
from collections import Counter
from pathlib import Path

from ..assets import canonical_bytes, content_id, digest, load_json, local_file, require
from ..contracts import load_contract
from ..corpus_ingress import CONTRACT as CORPUS_CONTRACT, MANIFEST, load_full_manifest
from .corad_corpus import C, INFERENCE, SOURCE, apply_corpus_profile
from .native_admission import plan_native_admission

POLICY = 'configs/suites/m3_first_batch_native_v3/real_input_policy_v5.json'
REUSE = ('docs/contracts/first-batch-unique-evidence.md', 'docs/contracts/first-batch-unique-builds.md')
SCHEMA = 'bmk.native-corpus-plan/1'
ENGINE = ('src/tsbench/corpus_ingress.py', 'src/tsbench/planner/native_corpus.py',
          'src/tsbench/planner/corad_corpus.py', 'src/tsbench/planner/corad_corpus_execution.py',
          'src/tsbench/qualification/corad_wire.py')
V3, V4, V5 = (f'bmk.native-corpus-policy/{i}' for i in (3, 4, 5))


def _key(row):
    return row['selection'], row['route']


def _id(row, key):
    return {**row, key: content_id(row)}


def _row_ranges(entry, partition):
    if partition == 'full':
        return [{'partition': 'full', 'start': 0, 'end': entry['rows'], 'object_id': entry['canonical']['object_id']}]
    chosen = {'test'} if partition == 'test' else {'train', 'test'}
    return [{'partition': p['name'], 'start': p['start'], 'end': p['end'], 'object_id': p['canonical']['object_id']}
            for p in entry['partitions'] if p['name'] in chosen]


def _input_view(entry, rule):
    width = entry['value_count']
    view = rule['view']
    shared = view in {'v_bytes_interleaved', 'f64_multicolumn'}
    ranges = _row_ranges(entry, rule['partition'])
    ms = view == 'tv_per_value_column_ms'
    # Caller-defined units; neither source loader batches nor internal codec blocks.
    cohort = width if shared else 1
    unit_row_bytes = 8 * (cohort + ms)
    unique_rows = sum(p['end'] - p['start'] for p in ranges)
    caps = [rule[k] for k in ('rows_per_unit', 'bytes_per_unit') if k in rule]
    # Byte sessions (e.g. 64 KiB V objects) may cut through the byte representation
    # of a row. Recovery covers the full ordered byte extent, not a projection.
    unit_kind = 'byte_span' if 'bytes_per_unit' in rule else 'row_span'
    limit = caps[0] if caps else None
    if limit is not None:
        mult = unit_row_bytes if unit_kind == 'byte_span' else 1
        units_per_group = sum(((p['end'] - p['start']) * mult + limit - 1) // limit for p in ranges)
        peak_input = limit * (1 if unit_kind == 'byte_span' else unit_row_bytes)
        peak_input = min(peak_input, max((p['end'] - p['start']) * unit_row_bytes for p in ranges))
    else:
        units_per_group = len(ranges)
        peak_input = max((p['end'] - p['start']) * unit_row_bytes for p in ranges)
    dtype, shape = {
        'f64_columns': ('<f8', ['rows']),
        'v_bytes_interleaved': ('byte', ['bytes']),
        'tv_per_value_column_ms': ('i64_ms+f64', ['rows', 2]),
        'f64_multicolumn': ('<f8', ['rows', width]),
        'u16_le_limbs_per_f64_column': ('<u2', ['rows', 4]),
        'u64_bitcast_per_f64_column': ('<u8', ['rows']),
    }[view]
    skipped = [{'start': p['start'], 'end': p['end'], 'reason': 'outside_operation_partition', 'partition': p['name']}
               for p in entry['partitions'] if rule['partition'] != 'full' and p['name'] not in {r['partition'] for r in ranges}]
    return {'row_ranges': ranges, 'skipped_row_ranges': skipped, 'value_column_range': [0, width],
            'column_grouping': 'all_values_interleaved' if shared else 'one_work_unit_series_per_value_column',
            'full_extent_of_file_rows_and_value_columns': rule['partition'] == 'full',
            'source_bytes_recovery': False, 'covers_time_axis': ms, 'representation': view, 'dtype': dtype, 'shape': shape,
            'planned_transforms': {
                'u16_le_limbs_per_f64_column': ['f64_bitcast_to_u16_le_limb0_to_limb3'],
                'u64_bitcast_per_f64_column': ['f64_bitcast_to_le_u64'],
                'tv_per_value_column_ms': ['checked_i64_seconds_to_ms_keep_civil_coordinate'],
                'v_bytes_interleaved': ['byte_view_of_ordered_f64_V_only'],
            }.get(view, []),
            'slice_extent': {'unit': unit_kind, 'max_per_unit': limit, 'units_per_column_group': units_per_group},
            'size_estimate': {
                'scope': 'unique_input_extent_and_single_pass_native_argument_not_total_IO_or_memory',
                'unique_logical_axis_bytes': 8 * unique_rows if ms else 0,
                'unique_logical_value_bytes': 8 * unique_rows * width,
                'native_input_bytes_one_pass': unit_row_bytes * unique_rows * (1 if shared else width),
                'largest_input_unit_bytes': peak_input,
                'input_units': units_per_group * (1 if shared else width),
                'total_workspace_bytes': None, 'workspace_reason': 'native_driver_and_resource_contract_not_frozen',
            }}


def _bounded_training(entry, rule):
    """Freeze exact byte spans from a single project's canonical train partition."""
    config = rule['training']
    train, _, test = entry['partitions']
    width = 8 * entry['value_count']
    available = (train['end'] - train['start']) * width
    capacity = None
    if config['profile'] in {'zstd_bounded_train_v1', 'zstd_two_extents_train_v1'}:
        require(rule['route'] == 'zstd-dictionary' and rule['options']['capacity_bytes'] == 2048,
                'Zstd sample policy does not bind the locked dictionary configuration')
        capacity = rule['options']['capacity_bytes']
        tier = 'standard'
        if available < config['min_total_bytes']:
            if 'short_train' not in config:
                return None
            short = config['short_train']
            capacity, size, tier = short['capacity_bytes'], short['sample_bytes'], 'short'
            count = min(config['max_samples'], available // size)
            if count < short['min_samples']:
                return None
        else:
            size = min(config['max_sample_bytes'], available // (config['min_samples'] * 8) * 8)
            count = min(config['max_samples'], available // size)
            if size * count < config['min_total_bytes']:
                return None
    else:
        require(rule['route'] == 'huff0-shared-table', 'Huff0 table profile bound to the wrong native route')
        size, count = min(config['max_train_bytes'], available), 1
    require(size > 0 and size * count <= available and train['end'] <= test['start'],
            'training and test input extents overlap or exceed budget')
    return {
        **({'dictionary_capacity_bytes': capacity, 'extent_tier': tier,
            'selection_basis': 'pre_run_train_extent_only_never_retry_a_different_tier'} if capacity is not None else {}),
        'profile': config,
        'origin': 'same_file_only',
        'partition': 'train', 'partition_object_id': train['canonical']['object_id'],
        'coordinate': 'canonical_row_major_v_bytes_relative_to_train_partition',
        'sample_geometry': {'first_byte': 0, 'count': count, 'bytes_each': size, 'stride_bytes': size},
        'consumed_byte_range': [0, size * count], 'unconsumed_train_byte_range': [size * count, available],
        'evaluation': {'partition': 'test', 'partition_object_id': test['canonical']['object_id'],
                       'absolute_rows': [test['start'], test['end']],
                       'frame_input_limit_bytes': rule['bytes_per_unit']},
        'training_success_assumed': False, 'failure_policy': 'record_native_failure_do_not_fallback',
        'accounting': 'charge_serialized_table_or_dictionary_and_binding_assets_no_free_shared_model',
    }


def _lossy_column_input(entry, layout, candidate, sentinel_columns, *, short_reason, sentinel_reason):
    """Bind compact, exact per-column extents; codec workspace is not inferred."""
    n, width = entry['rows'], entry['value_count']
    require(sum(end - start for spans in sentinel_columns.values() for start, end in spans) ==
            entry['retained_sentinel_values'], 'lossy column input needs verified per-column sentinel spans')

    def partition(holes):
        cursor, extents, gaps = 0, [], []
        for start, end in [*holes, [n, n]]:
            require(cursor <= start <= end <= n, 'invalid sentinel span order or extent')
            size = start - cursor
            if size < layout['min_rows']:
                if size:
                    gaps.append({'rows': [cursor, start], 'reason': short_reason})
            else:
                # Equalize pieces so a short final fragment does not silently disappear.
                count = (size + layout['max_rows'] - 1) // layout['max_rows']
                each, extra = divmod(size, count)
                require(each >= layout['min_rows'], 'column split leaves a short work unit')
                extents.append({'rows': [cursor, start], 'windows': count, 'base_rows': each,
                                'first_windows_with_one_extra_row': extra})
            if end > start:
                gaps.append({'rows': [start, end], 'reason': sentinel_reason})
            cursor = end
        return {'accepted_spans': extents, 'excluded_spans': gaps}

    common = partition([])
    overrides = []
    for col, spans in sorted(sentinel_columns.items()):
        require(0 <= col < width, 'sentinel column index out of range')
        overrides.append({'value_column_index': col, **partition(spans)})
    groups = [(width - len(overrides), common), *((1, x) for x in overrides)]
    nbytes = 8 * sum(cols * (r['rows'][1] - r['rows'][0]) for cols, g in groups for r in g['accepted_spans'])
    units = sum(cols * r['windows'] for cols, g in groups for r in g['accepted_spans'])
    peak = 8 * max((r['base_rows'] + bool(r['first_windows_with_one_extra_row'])
                    for cols, g in groups if cols for r in g['accepted_spans']), default=0)
    candidate.update(
        full_extent_of_file_rows_and_value_columns=nbytes == 8 * n * width,
        slice_extent={'unit': 'single_column_balanced_row_window', 'max_per_unit': layout['max_rows']})
    candidate['size_estimate'].update(unique_logical_value_bytes=nbytes, native_input_bytes_one_pass=nbytes,
                                      largest_input_unit_bytes=peak, input_units=units)
    return {'layout': layout, 'row_coordinates': 'absolute_zero_based_half_open',
            'default_column': common, 'column_overrides': overrides}


def _array_input(entry, rule, candidate, sentinel_columns):
    extent = _lossy_column_input(entry, rule['array_layout'], candidate, sentinel_columns,
                                 short_reason='too_short_for_cross_block_mutation',
                                 sentinel_reason='retained_missing_sentinel_no_lossy_mutation')
    candidate['array_contract'] = {**extent,
        'mutation': {'point': {'index': 1, 'copy_original_index': -1},
                     'range': {'rows': [3, 7], 'copy_original_rows': [0, 4]},
                     'source': 'unmodified_input_window_zero_based_negative_index_counts_from_end',
                     'untouched_blocks': 'verify_unchanged_native_bytes_and_restored_values'},
        'verification': {'before': 'compare_finite_restored_values_with_unmodified_f64_input',
                         'after': 'compare_finite_restored_values_with_exact_mutated_f64_reference',
                         'rule': 'abs_error_le_max_absolute_floor_or_relative_times_abs_expected',
                         'scope': 'every_value_in_each_independent_reopen_not_a_rate_guarantee'},
        'restore': 'separate_trusted_array_payload_and_rank1_f64_shape_rate_binding_no_source_mount'}


def _pbepla_input(entry, rule, candidate, sentinel_columns):
    layout = rule['prefix_layout']
    require(layout['max_rows'] * len(layout['requested_eps']) <= layout['value_layer_budget'],
            'PBEPLA corpus layout exceeds the value-layer budget')
    extent = _lossy_column_input(entry, layout, candidate, sentinel_columns, short_reason='empty_series',
                                 sentinel_reason='retained_missing_sentinel_outside_progressive_quality_domain')
    candidate['pbepla_contract'] = {**extent,
        'representation': 'finite_unscaled_original_binary64_no_missing_replacement',
        'prefixes': 'seal_and_independently_restore_all_requested_layers',
        'verification': 'for_each_layer_exact_original_domain_max_absolute_error_le_effective_eps_le_requested_eps',
        'quality_failure': 'record_rejection_do_not_change_epsilon_or_drop_layers',
        'replay': {'native_same_window_as_batch': True, 'verify_identical_full_frame': True,
                   'online_input': False, 'observe_actual_passes_retries_first_sink_and_logical_temp_traffic': True}
                  if rule['route'] == 'pbepla-replay' else None}


def _decide(entry, rule, route, sentinel_columns=None):
    view = rule['view']
    axis = entry['axis_observations']
    signs, unresolved = [], list(rule['prerequisites'])
    if view == 'native_unsigned_integers_only':
        signs.append('native_unsigned_integer_semantics_required_no_implicit_cast')
    if view == 'tv_per_value_column_ms':
        if entry['axis']['unit'] != 'second':
            signs.append('source_index_has_no_defined_mapping_to_ms')
        if not (-2**63 <= axis['min'] * 1000 <= axis['max'] * 1000 < 2**63):
            signs.append('timestamp_scaling_overflow')
        if axis['decreases']:
            signs.append('declared_profile_requires_nondecreasing_axis_no_sort')
    if view == 'f64_multicolumn' and entry['value_count'] < 2:
        signs.append('frozen_corad_profile_requires_multivariate_values')
    if 'corad_layout' in rule and axis['decreases']:
        signs.append('corad_profile_requires_nondecreasing_source_no_sort')
    has_lossy_layout = 'array_layout' in rule or 'prefix_layout' in rule
    if (rule['missing'] == 'require_no_retained_sentinel' and entry['retained_sentinel_values'] and
            not has_lossy_layout and 'corad_layout' not in rule):
        unresolved.append('resolve_sentinel_columns_and_ranges_before_lossy_operation')
    if signs:
        state, reason, candidate, open_items = 'outside_declared_domain', signs, None, []
    else:
        candidate = _input_view(entry, rule)
        if 'array_layout' in rule:
            _array_input(entry, rule, candidate, sentinel_columns or {})
        if 'prefix_layout' in rule:
            _pbepla_input(entry, rule, candidate, sentinel_columns or {})
        if 'corad_layout' in rule:
            apply_corpus_profile(entry, rule, candidate, sentinel_columns or {})
        if 'training' in rule:
            training = _bounded_training(entry, rule)
            candidate['training'] = training
            if training is None:
                if rule['training']['profile'] != 'zstd_two_extents_train_v1':
                    unresolved.append('train_extent_below_frozen_profile_requires_explicit_short_profile')
            else:
                extent = candidate['size_estimate']
                assert rule['view'] == 'v_bytes_interleaved'
                train_bytes = training['consumed_byte_range'][1]
                test_rows = training['evaluation']['absolute_rows']
                test_bytes = (test_rows[1] - test_rows[0]) * entry['value_count'] * 8
                test_blocks = (test_bytes + rule['bytes_per_unit'] - 1) // rule['bytes_per_unit']
                extent.update(unique_logical_value_bytes=train_bytes + test_bytes,
                              native_input_bytes_one_pass=train_bytes + test_bytes,
                              largest_input_unit_bytes=max(train_bytes, min(test_bytes, rule['bytes_per_unit'])),
                              input_units=1 + test_blocks)
        open_items = ['new_corpus_driver_resource_and_validator_binding', *unresolved]
        if 'corad_layout' in rule and not candidate['size_estimate']['input_units']:
            state, reason, open_items = 'outside_declared_domain', ['no_cohort_meets_train_and_test_extent'], []
        elif ('training' in rule and candidate['training'] is None and
                rule['training']['profile'] == 'zstd_two_extents_train_v1'):
            state, reason, candidate, open_items = ('outside_declared_domain',
                ['below_frozen_short_dictionary_sample_floor_no_padding'], None, [])
        elif has_lossy_layout and not candidate['size_estimate']['input_units']:
            state, reason, open_items = 'outside_declared_domain', ['no_sentinel_free_window_meets_native_layout'], []
        elif 'min_payload' in rule and candidate['size_estimate']['native_input_bytes_one_pass'] < rule['min_payload']:
            state, reason = 'condition_not_triggered', ['smaller_than_frozen_worker_probe_extent_no_padding']
        elif unresolved:
            state, reason = 'unresolved_contract', unresolved
        else:
            state, reason = 'input_domain_matches', ['declared_representation_and_input_extent_available']
    return _id({'dataset_id': entry['id'], 'source_cluster': entry['source_cluster'],
                'canonical_object_id': entry['canonical']['object_id'], 'route_contract_id': route['route_contract_id'],
                'selection': rule['selection'], 'route': rule['route'], 'view': view,
                'operation': rule['operation'], 'operation_config_id': content_id(rule),
                'state': state, 'reasons': reason, 'input': candidate, 'open_execution_bindings': open_items,
                'execution_state': 'not_run', 'qualification_granted': False}, 'decision_id')


def _compile(corpus, policy, native, bindings, sentinel_index=None):
    routes = {_key(route): route for route in native['routes']}
    rules = {_key(rule): rule for rule in policy['routes']}
    require(len(rules) == len(policy['routes']) == len(routes) == 36 and rules.keys() == routes.keys(),
            'native corpus policy must bind each of the 36 native route identities exactly once')
    version = policy['schema']
    if version != 'bmk.native-corpus-policy/1':
        training_rules = {key for key, rule in rules.items() if 'training' in rule}
        require(training_rules == {(29, 'huff0-shared-table'), (40, 'zstd-dictionary')},
                'native dictionary and table input profiles must both be bound')
    array_rules = {key for key, rule in rules.items() if 'array_layout' in rule}
    if version in {V3, V4, V5}:
        require(array_rules == {(31, 'fixed-rate-array')}, 'missing or misplaced fixed-rate array input layout')
        array = rules[31, 'fixed-rate-array']
        require((array['view'], array['partition'], array['operation'], array['missing'], array['options']) ==
                ('f64_columns', 'full', 'mutate_flush_reopen', 'require_no_retained_sentinel',
                 {'schema': 'distinct_array_format'}) and 'rows_per_unit' not in array,
                'fixed-rate array layout conflicts with native route scope')
    else:
        require(not array_rules, 'fixed-rate array input layout requires policy/3')
    prefix_rules = {key: rule for key, rule in rules.items() if 'prefix_layout' in rule}
    if version in {V4, V5}:
        operations = {'pbepla-progressive': 'each_prefix_restore', 'pbepla-replay': 'bounded_source_rewind_and_prefix_restore'}
        require(prefix_rules.keys() == {(87, name) for name in operations}, 'PBEPLA needs both bound prefix layouts')
        batch, replay = (prefix_rules[87, name] for name in operations)
        require(batch['prefix_layout'] == replay['prefix_layout'] and all(
            (rule['view'], rule['operation'], rule['partition'], rule['missing'], rule['options'], rule['prerequisites']) ==
            ('f64_columns', operations[rule['route']], 'full', 'require_no_retained_sentinel', {}, []) and
            'rows_per_unit' not in rule for rule in prefix_rules.values()), 'PBEPLA progressive/replay extent or quality differs')
    else:
        require(not prefix_rules, 'PBEPLA prefix input layout requires policy/4')
    corads = {rule['route']: rule for rule in rules.values() if 'corad_layout' in rule}
    if version == V5:
        require(corads.keys() == {C, SOURCE, INFERENCE}, 'CORAD needs all deployment and training bindings')
        layout = corads[INFERENCE]['corad_layout']
        for name, rule in corads.items():
            training = name != INFERENCE
            require((rule['selection'], rule['view'], rule['partition'], rule['operation'], rule['missing'],
                     rule['prerequisites'], rule['options'], rule['corad_layout']) ==
                    (80, 'f64_multicolumn', 'train_test' if training else 'test',
                     'train_validate_and_separate_heldout_inference' if training else 'model_roundtrip',
                     'require_no_retained_sentinel', [], {}, layout) and 'rows_per_unit' not in rule,
                    'CORAD deployment and training scope/configuration differ')
        require(rules[40, 'zstd-dictionary']['training']['profile'] == 'zstd_two_extents_train_v1',
                'Zstd short dictionary extent must be bound')
    else:
        require(not corads and all(rule.get('training', {}).get('profile') != 'zstd_two_extents_train_v1'
                                   for rule in rules.values()), 'CORAD and short dictionary profiles require policy/5')
    decisions, obligations, route_plans = [], [], []
    for key, route in routes.items():
        rule = rules[key]
        file_bindings = [_decide(entry, rule, route, (sentinel_index or {}).get(entry['id']))
                         for entry in corpus['datasets']]
        decisions.extend(file_bindings)
        route_plans.append({'binding': rule, 'original_contract': route, 'new_data_semantics_only': True})
        for obligation in native['obligations']:
            if _key(obligation) != key:
                continue
            item = {**obligation, 'evidence_status': 'not_run_on_updated_contract',
                    'corpus_route_binding': content_id(rule),
                    'specialized_binding_policy': 'existing_input_and_condition_definitions_must_run_where_applicable_no_reuse_of_results',
                    'corpus_cases_replace_specialized_checks': False}
            obligations.append(item)
    kinds = Counter(item['kind'] for item in obligations)
    require(kinds == {'required': 180, 'conditional': 6} and
            len({item['obligation_id'] for item in obligations}) == 186 and
            all(r.get('planned_case_inputs') for r in obligations if r['kind'] == 'required') and
            all(r.get('condition_case') for r in obligations if r['kind'] == 'conditional'),
            'native corpus obligation or specialized input denominator drift')
    states = Counter(row['state'] for row in decisions)
    nonblocked = [d for d in decisions if d['state'] == 'input_domain_matches']
    plan = {'schema': SCHEMA, 'definition_stage': 'M0', 'target_execution_stage': 'M3',
                'runnable': False, 'qualification_granted': False, 'stage_accepted': False,
                'coverage': {'datasets': len(corpus['datasets']), 'routes': len(routes),
                             'selections': len({i[0] for i in routes}), 'file_route_decisions': len(decisions),
                             'decision_states': dict(sorted(states.items())), 'required_obligations': kinds['required'],
                             'conditional_obligations': kinds['conditional'], 'executed': 0, 'qualified': 0,
                             'selections_with_input_domain_match': len({r['selection'] for r in nonblocked})},
                'estimates': {'scope': 'eligible_input_only_excludes_additional_passes_outputs_and_unbound_contracts',
                              'native_argument_units': sum(d['input']['size_estimate']['input_units'] for d in nonblocked),
                              'native_argument_bytes_one_pass': sum(d['input']['size_estimate']['native_input_bytes_one_pass'] for d in nonblocked),
                              'peak_native_argument_bytes': max((d['input']['size_estimate']['largest_input_unit_bytes']
                                                                 for d in nonblocked), default=0)},
                'bindings': bindings, 'routes': route_plans, 'decisions': decisions, 'obligations': obligations,
                'execution_policy': {'submit': 'one_frozen_plan_one_run_one_main_ledger', 'verification': 'artifact_each',
                                     'external_support_scope': 'declared_thin_representation_only_no_M5_fallback',
                                     'new_input_per_selection': 'requires_new_same_entry_execution_presently_unverified',
                                     'condition_resolution': 'actual_build_runtime_and_native_work_not_inferred_from_definitions',
                                     'cross_file_training': 'not_admitted_without_a_source_lineage_disjointness_check'}}
    return _id(plan, 'plan_content_id')


def plan_native_corpus(root: Path, manifest: str = MANIFEST, policy_path: str = POLICY) -> dict:
    contract = load_contract(root, 'native-corpus-policy')
    policy = load_json(local_file(root, policy_path))
    contract.validate(policy, policy_path)
    native = plan_native_admission(root)
    # All eligibility metadata, including axis ordering and sentinel counts,
    # must be checked against the source rather than trusting a resealed manifest.
    sentinel_index = {} if policy['schema'] in {V3, V4, V5} else None
    corpus = load_full_manifest(root, manifest, parse=True, sentinel_index=sentinel_index)
    references = sorted({*REUSE, *(f"docs/contracts/{row['evidence_contract']}.md" for row in policy['routes'])})
    return _compile(corpus, policy, native, {
        'manifest': manifest, 'manifest_id': content_id(corpus), 'raw_and_canonical_inputs_recomputed': True,
        'manifest_schema_id': load_contract(root, CORPUS_CONTRACT).document_id,
        'policy': policy_path, 'policy_id': content_id(policy), 'policy_schema_id': contract.document_id,
        'native_admission_plan_id': native['plan_content_id'],
        'unique_and_local_evidence_references_not_execution': {p: digest(local_file(root, p)) for p in references},
        'code': {p: digest(local_file(root, p)) for p in ENGINE},
    }, sentinel_index=sentinel_index)


def verify_native_corpus_plan(root: Path, document: dict) -> dict:
    require(isinstance(document, dict) and document.get('schema') == SCHEMA, 'not a native corpus definition plan')
    require(isinstance(document.get('bindings'), dict), 'missing native corpus plan bindings')
    references = document['bindings']
    expected = plan_native_corpus(root, references['manifest'], references['policy'])
    require(canonical_bytes(expected) == canonical_bytes(document), 'native corpus plan differs from the full rederived definition')
    return {'plan_content_id': expected['plan_content_id'], 'definition_verified': True, 'runnable': False,
            'stage_accepted': False, 'qualification_granted': False, 'coverage': expected['coverage']}
