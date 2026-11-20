"""Bound ordered CORAD cohorts; training and held-out use distinct dependencies."""
from fractions import Fraction
import math
import struct

from ..assets import content_id, require

C, SOURCE, INFERENCE = 'corad-c-training', 'corad-source-training', 'corad-inference'
TRAINERS = (C, SOURCE)


def _sentinel_union(columns, index, start, end):
    holes = []
    for lo, hi in sorted((max(lo, start), min(hi, end)) for col in columns for lo, hi in index.get(col, ())
                         if lo < end and hi > start):
        if holes and holes[-1][1] >= lo:
            holes[-1][1] = max(holes[-1][1], hi)
        else:
            holes.append([lo, hi])
    return holes


def _gaps(start, end, holes):
    result = []
    for lo, hi in [*holes, [end, end]]:
        if start < lo:
            result.append([start, lo])
        start = hi
    return result


def plan_cohorts(entry, policy, sentinel_columns):
    """Bind all ordered columns without joining rows across an excluded interval."""
    n = entry['value_count']
    require(n >= 2 and entry['axis_observations']['decreases'] == 0, 'CORAD requires a nondecreasing ordered source')
    require(sum(hi-lo for v in sentinel_columns.values() for lo, hi in v) == entry['retained_sentinel_values'],
            'CORAD needs verified per-column sentinel spans')
    train, dev, test = entry['partitions']
    require(train['end'] <= dev['start'] < dev['end'] <= test['start'], 'CORAD partition roles overlap')
    count = (n + policy['max_columns'] - 1) // policy['max_columns']
    width, extra = divmod(n, count)
    require(width >= 2, 'CORAD cohort shape too narrow')
    cohorts = []
    c0 = 0
    for i in range(count):
        c1 = c0 + width + int(i < extra)
        size = c1 - c0
        cols = range(c0, c1)
        train_holes = _sentinel_union(cols, sentinel_columns, train['start'], train['end'])
        test_holes = _sentinel_union(cols, sentinel_columns, test['start'], test['end'])
        available_train = _gaps(train['start'], train['end'], train_holes)
        required = policy['train_rows']
        train_rows = next(([lo, lo + required] for lo, hi in available_train if hi - lo >= required), None)
        evaluation = _gaps(test['start'], test['end'], test_holes)
        unit_rows = min(policy['max_test_rows_per_frame'], policy['max_values_per_frame'] // size)
        eligible = train_rows is not None and bool(evaluation)
        body = {'source_object_id': entry['canonical']['object_id'], 'columns': [c0, c1],
                'ordered_column_names': entry['columns'][c0+1:c1+1], 'shape': 'f64_column_major',
                'train': {'source_id': train['canonical']['object_id'], 'rows': train_rows, 'sentinel_rows': train_holes,
                          'excluded_nonselected_train_rows': _gaps(train['start'], train['end'], [train_rows])
                          if train_rows else [[train['start'], train['end']]],
                          'complete_tricklets_per_column': required // policy['tricklet'] if train_rows else None,
                          'tail_rows_not_a_training_vector': required % policy['tricklet'] if train_rows else None},
                'development_not_consumed': [dev['start'], dev['end']],
                'test': {'source_id': test['canonical']['object_id'], 'eligible_row_spans': evaluation,
                         'excluded_sentinel_rows': test_holes, 'max_rows_per_frame': unit_rows},
                'require_train_last_time_strictly_before_test_first_time_at_binding': True,
                'training_mask': (1 << size) - 1,
                'state': 'eligible' if eligible else 'outside_declared_extent',
                'reasons': ([] if train_rows else ['no_sentinel_free_129_row_train_extent']) +
                           ([] if evaluation else ['no_sentinel_free_test_rows'])}
        cid = content_id(body)
        model = {trainer: content_id({'cohort_id': cid, 'trainer': trainer, 'config': policy}) for trainer in TRAINERS}
        cohorts.append({**body, 'cohort_id': cid, 'producer_binding_ids': model if eligible else {}})
        c0 = c1
    require(c0 == n, 'CORAD dropped ordered columns')
    return cohorts


def apply_corpus_profile(entry, rule, candidate, sentinel_columns):
    layout = rule['corad_layout']
    cohorts = plan_cohorts(entry, layout, sentinel_columns)
    allowed = [c for c in cohorts if c['state'] == 'eligible']
    route = rule['route']
    training = route in TRAINERS
    candidate.update(full_extent_of_file_rows_and_value_columns=False,
                     column_grouping='ordered_disjoint_multicolumn_cohorts',
                     slice_extent={'unit': 'one_ordered_cohort_train_window_or_test_frame', 'max_per_unit': layout['max_test_rows_per_frame']},
                     shape=['rows', 'cohort_column_count'], corad_contract={
        'layout': layout, 'cohorts': cohorts,
        'quality': {'reference': 'per_column_train_only_exact_mean_constant_predictor',
                    'accept': 'all_columns_exact_max_abs_error_and_mse_le_train_calibration_bounds',
                    'calibrate_before_heldout': True, 'native_threshold_is_not_an_error_bound': True,
                    'failure': 'quality_rejected_keep_valid_restore_and_metrics_no_retune'},
        'deployment': {'mode': 'require_matching_model_loaded_from_same_run_train_only_product',
                       'eligible_producers': [route] if training else list(TRAINERS),
                       'on_missing_or_failure': 'dependency_terminal_never_substitute_old_model',
                       'require_identity': 'producer_binding_train_digest_ordered_schema_and_model_digest',
                       'evaluation_artifact_counted_once_in_inference_even_when_referenced_by_training_obligation': True,
                       'distinct_from_historical_deployments': True},
        'training_access': 'no_test_mount_no_test_driven_selection',
        'recovery_access': 'new_process_only_complete_frame_and_decode_runtime',
    })
    ibytes = units = peak = unique = 0
    for cohort in allowed:
        width = cohort['columns'][1] - cohort['columns'][0]
        if training:
            # Training consumers reference, not rerun, the inference products.
            arg = 8 * width * layout['train_rows']
            units += 1
            ibytes += arg
            unique += arg
        else:
            cap = cohort['test']['max_rows_per_frame']
            rows = [hi - lo for lo, hi in cohort['test']['eligible_row_spans']]
            units += len(TRAINERS) * sum((n + cap - 1) // cap for n in rows)
            unique += 8 * width * sum(rows)
            ibytes += len(TRAINERS) * 8 * width * sum(rows)
            arg = 8 * width * min(cap, max(rows))
        peak = max(peak, arg)
    candidate['size_estimate'].update(unique_logical_value_bytes=unique, native_input_bytes_one_pass=ibytes,
                                     largest_input_unit_bytes=peak, input_units=units)
    # row_ranges describes role envelopes, not exact argument sizes; cohort rows
    # above are authoritative. Training never includes the evaluation bytes.
    if training:
        candidate['row_ranges'] = [r for r in candidate['row_ranges'] if r['partition'] == 'train']
        test = entry['partitions'][2]
        candidate['skipped_row_ranges'].append({'partition': 'test', 'start': test['start'], 'end': test['end'],
                                               'reason': 'heldout_handled_by_separate_inference_products'})


def calibrate_quality(train, *, count, width):
    """Exact empirical comparison gates, derived exclusively from training bytes."""
    require(count > 0 and width >= 2 and len(train) == count*width*8, 'CORAD calibration has wrong extent')
    columns = []
    for col in range(width):
        values = [x for x, in struct.iter_unpack('<d', train[col*count*8:(col+1)*count*8])]
        require(all(map(math.isfinite, values)), 'nonfinite CORAD calibration input')
        xs = list(map(Fraction, values))
        mean = sum(xs, Fraction(0)) / count
        errors = [abs(x-mean) for x in xs]
        columns.append({'constant_predictor': str(mean), 'max_abs_error': str(max(errors)),
                        'mse': str(sum((e*e for e in errors), Fraction(0))/count)})
    return columns
