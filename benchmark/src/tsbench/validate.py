"""Recovery and quality measured in the original typed domain."""
import math
import numpy as np
from .data import array_order


QUALITY_FIDELITIES = {'numeric_equivalent', 'bounded_abs', 'range_relative',
                      'point_relative', 'empirical_quality'}


def verify(original, restored, task):
    fidelity = task.get('fidelity', 'bitwise')
    result = {'passed': False, 'fidelity': fidelity, 'reason': None,
              'max_abs': None, 'rmse': None, 'nrmse': None, 'psnr_db': None,
              'quality_count': 0, 'violation_count': 0,
              'special_values_policy': task.get('special_values', 'bitwise'),
              'invalid_values_policy': task.get('invalid_values', 'preserve'),
              'quality_scope': 'original valid finite V positions; T/mask/special bits checked separately',
              'normalization_policy': 'range of all original valid finite V positions in this task object',
              'nrmse_denominator': None, 'psnr_denominator': None,
              'psnr_policy': 'null_for_zero_error_or_constant_range',
              'effective_absolute_bound': None, 'task_absolute_bound': None,
              'effective_bound_scope': 'task constraint; legacy alias of task_absolute_bound, not native codec tolerance',
              'comparison_policy': 'strict original-domain comparison; no added error tolerance',
              'comparison_precision': {'dtype': np.dtype(np.longdouble).str,
                                       'significand_bits': int(np.finfo(np.longdouble).nmant + 1)},
              'metric_null_reasons': {name: 'not_evaluated' for name in
                                     ('max_abs', 'rmse', 'nrmse', 'psnr_db',
                                      'nrmse_denominator', 'psnr_denominator', 'effective_absolute_bound')}}

    def fail(reason):
        if result['reason'] is None:
            result['reason'] = reason

    def abort(reason):
        fail(reason)
        for name, value in result['metric_null_reasons'].items():
            if value == 'not_evaluated':
                result['metric_null_reasons'][name] = reason
        return result

    def number(name, value):
        """Standard JSON number plus the extended precision diagnostic string."""
        result[name + '_extended'] = str(value)
        converted = float(value)
        result[name] = converted if math.isfinite(converted) else None
        result['metric_null_reasons'][name] = None if math.isfinite(converted) else 'outside_finite_float64_range'
        if name == 'effective_absolute_bound':
            result['task_absolute_bound'] = result[name]
            result['task_absolute_bound_extended'] = result[name + '_extended']

    eps = floor = None
    if fidelity in {'bounded_abs', 'range_relative', 'point_relative'}:
        result['requested_bound'] = str(task['error_bound'])
        result['task_requested_bound'] = result['requested_bound']
        eps = np.longdouble(str(task['error_bound']))
        if fidelity == 'bounded_abs':
            number('effective_absolute_bound', eps)
        elif fidelity == 'point_relative':
            floor = np.longdouble(str(task.get('relative_floor', 0)))
            result.update(relative_floor_requested=str(task.get('relative_floor', 0)),
                          relative_floor_effective=float(floor),
                          point_relative_denominator_policy='max(abs(original_value), relative_floor)',
                          zero_denominator_policy='zero error satisfies zero threshold; positive error violates',
                          point_relative_components=[])
            result['metric_null_reasons']['effective_absolute_bound'] = 'pointwise_thresholds; see component threshold ranges'
    else:
        result['metric_null_reasons']['effective_absolute_bound'] = 'no bounded quality constraint'

    if original.schema != restored.schema or set(original.components) != set(restored.components):
        return abort('schema_mismatch')
    if fidelity not in QUALITY_FIDELITIES | {'bitwise'}:
        return abort('unknown_fidelity')
    roles = original.schema.get('roles', {})
    mask = next((a.astype(bool) for k, a in original.components.items() if roles.get(k, k) == 'mask'), None)
    errors, originals = [], []
    invalid_reconstruction = False
    for name, a in original.components.items():
        b = restored.components[name]
        if a.dtype != b.dtype or a.shape != b.shape or array_order(a) != array_order(b):
            return abort('dtype_shape_order_mismatch')
        role = roles.get(name, name)
        same = a.tobytes(order=array_order(a)) == b.tobytes(order=array_order(b))
        if fidelity == 'bitwise' or role != 'V':
            if not same:
                fail('bitwise_mismatch')
            continue
        if a.dtype.kind == 'f':
            finite = np.isfinite(a)
            special = ~finite | ((a == 0) & np.signbit(a))
            if a[special].tobytes() != b[special].tobytes():
                fail('special_value_mismatch')
        else:
            finite = np.ones(a.shape, dtype=bool)
        if mask is not None:
            if mask.shape != a.shape:
                return abort('mask_shape_mismatch')
            if a[~mask].tobytes() != b[~mask].tobytes():
                fail('invalid_value_bits_mismatch')
            finite &= mask
        result['quality_count'] += int(np.count_nonzero(finite))
        if a.dtype.kind == 'f' and not np.isfinite(b[finite]).all():
            fail('nonfinite_reconstruction')
            invalid_reconstruction = True
            continue
        aa = a[finite].astype(np.longdouble)
        bb = b[finite].astype(np.longdouble)
        err = (np.fromiter((abs(int(x) - int(y)) for x, y in zip(a[finite], b[finite])),
                           dtype=np.longdouble, count=len(aa)) if a.dtype.kind in 'iu' else np.abs(aa - bb))
        errors.append(err)
        originals.append(aa)
        if fidelity == 'numeric_equivalent':
            count = int(np.count_nonzero(err != 0))
            result['violation_count'] += count
            if count:
                fail('numeric_mismatch')
        if fidelity == 'point_relative':
            denominator = np.maximum(np.abs(aa), floor)
            thresholds = eps * denominator
            violations = err > thresholds
            count = int(np.count_nonzero(violations))
            result['violation_count'] += count
            positive = denominator > 0
            relative = err[positive] / denominator[positive]

            def finite_summary(values):
                if not len(values):
                    return {'min': None, 'max': None, 'null_reason': 'no_valid_finite_values'}
                lower, upper = np.min(values), np.max(values)
                return {'min': float(lower) if math.isfinite(float(lower)) else None,
                        'max': float(upper) if math.isfinite(float(upper)) else None,
                        'min_extended': str(lower), 'max_extended': str(upper),
                        'null_reason': None if math.isfinite(float(lower)) and math.isfinite(float(upper))
                        else 'outside_finite_float64_range'}

            result['point_relative_components'].append({
                'component': name, 'quality_count': len(aa), 'violation_count': count,
                'denominator': finite_summary(denominator), 'absolute_threshold': finite_summary(thresholds),
                'zero_denominator_count': int(np.count_nonzero(~positive)),
                'zero_denominator_violation_count': int(np.count_nonzero((~positive) & (err > 0))),
                'finite_relative_error': finite_summary(relative),
                'relative_error_scope': 'positions with positive denominator; zero-denominator violations recorded separately'})
            if count:
                fail('quality_violation')

    if invalid_reconstruction:
        return abort('nonfinite_reconstruction')
    if errors:
        e = np.concatenate(errors)
        a = np.concatenate(originals)
        max_abs = np.max(e) if len(e) else np.longdouble(0)
        # Scaling avoids squaring large original-domain differences.
        rmse = max_abs * np.sqrt(np.mean((e / max_abs) ** 2)) if max_abs > 0 else np.longdouble(0)
        value_range = np.max(a) - np.min(a) if len(a) else np.longdouble(0)
        number('max_abs', max_abs)
        number('rmse', rmse)
        number('nrmse_denominator', value_range)
        number('psnr_denominator', value_range)
        if value_range > 0:
            number('nrmse', rmse / value_range)
            if rmse > 0:
                number('psnr_db', 20 * (np.log10(value_range) - np.log10(rmse)))
            else:
                result['metric_null_reasons']['psnr_db'] = 'zero_error'
        else:
            null_reason = 'no_valid_finite_values' if not len(a) else 'constant_original_range'
            result['metric_null_reasons']['nrmse'] = null_reason
            result['metric_null_reasons']['psnr_db'] = null_reason
        if fidelity in {'bounded_abs', 'range_relative'}:
            bound = eps * value_range if fidelity == 'range_relative' else eps
            number('effective_absolute_bound', bound)
            result['violation_count'] = int(np.count_nonzero(e > bound))
            if result['violation_count']:
                fail('quality_violation')
        result['task_value_range'] = result['nrmse_denominator']
        result['task_value_range_extended'] = result['nrmse_denominator_extended']
    else:
        reason = 'bitwise_task' if fidelity == 'bitwise' else 'no_V_components'
        for name, value in result['metric_null_reasons'].items():
            if value == 'not_evaluated':
                result['metric_null_reasons'][name] = reason
    result['passed'] = result['reason'] is None
    return result
