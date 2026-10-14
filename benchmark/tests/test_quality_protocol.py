import json

import numpy as np
import pytest

from tsbench.data import TimeSeriesObject
from tsbench.validate import verify


def obj(values, **components):
    parts = {"V": values, **components}
    return TimeSeriesObject(parts, {"roles": {k: k for k in parts}})


def test_original_domain_integer_error_does_not_wrap():
    original = obj(np.array([np.iinfo(np.int64).min], dtype=np.int64))
    restored = obj(np.array([np.iinfo(np.int64).max], dtype=np.int64))
    result = verify(original, restored, {"fidelity": "bounded_abs", "error_bound": "1"})
    assert not result["passed"]
    assert result["reason"] == "quality_violation"
    assert result["max_abs"] > 1e19
    json.dumps(result, allow_nan=False)


def test_abs_violation_and_empirical_quality_are_different_tasks():
    original = obj(np.array([1., 2., 3.]))
    restored = obj(np.array([1., 2.2, 3.]))
    bounded = verify(original, restored, {"fidelity": "bounded_abs", "error_bound": "0.1"})
    empirical = verify(original, restored, {"fidelity": "empirical_quality"})
    assert not bounded["passed"] and bounded["reason"] == "quality_violation"
    assert empirical["passed"] and empirical["max_abs"] > 0.19
    assert empirical["rmse"] > 0.11


def test_quality_mask_ignores_only_declared_invalid_values_and_restores_mask():
    original = obj(np.array([1., 99.]), mask=np.array([1, 0], dtype=np.uint8))
    restored = obj(np.array([1.01, 99.]), mask=np.array([1, 0], dtype=np.uint8))
    quality = verify(original, restored, {"fidelity": "bounded_abs", "error_bound": "0.02"})
    assert quality["passed"] and quality["quality_count"] == 1
    restored.components["V"][1] = -1e6
    assert not verify(original, restored, {"fidelity": "empirical_quality"})["passed"]
    restored.components["V"][1] = 99.
    restored.components["mask"][0] = 0
    assert not verify(original, restored, {"fidelity": "empirical_quality"})["passed"]


def test_signed_zero_preserves_declared_special_bits_under_lossy_task():
    original = obj(np.array([-0., 1.]))
    restored = obj(np.array([0., 1.01]))
    assert not verify(original, restored, {"fidelity": "empirical_quality"})["passed"]


def test_nonfinite_payload_and_timestamp_are_strict_under_lossy_task():
    bits = np.array([0x7FF8000000000001, 0x3FF0000000000000], dtype=np.uint64)
    original = obj(bits.view(np.float64), T=np.array([0, 1], dtype=np.int64))
    changed = bits.copy()
    changed[0] += np.uint64(1)
    restored = obj(changed.view(np.float64), T=np.array([0, 1], dtype=np.int64))
    assert verify(original, restored, {"fidelity": "empirical_quality"})["reason"] == "special_value_mismatch"
    restored = obj(bits.view(np.float64).copy(), T=np.array([0, 2], dtype=np.int64))
    assert verify(original, restored, {"fidelity": "empirical_quality"})["reason"] == "bitwise_mismatch"


def test_constant_zero_error_metrics_use_standard_json_null():
    original = obj(np.array([5., 5.]))
    result = verify(original, obj(np.array([5., 5.])), {"fidelity": "empirical_quality"})
    assert result["passed"]
    assert result["max_abs"] == 0 and result["rmse"] == 0
    assert result["nrmse"] is None and result["psnr_db"] is None
    json.dumps(result, allow_nan=False)


def test_point_relative_zero_denominator_policy_is_explicit():
    original = obj(np.array([0., 10.]))
    restored = obj(np.array([0.001, 10.01]))
    assert not verify(original, restored, {"fidelity": "point_relative", "error_bound": "0.01"})["passed"]
    assert verify(original, restored, {"fidelity": "point_relative", "error_bound": "0.01", "relative_floor": "1"})["passed"]


def test_point_relative_failure_keeps_actual_error_and_zero_denominator_evidence():
    original = obj(np.array([0., 10., 100.]))
    restored = obj(np.array([0.001, 10.01, 102.]))
    result = verify(original, restored, {'fidelity': 'point_relative', 'error_bound': '0.01'})
    assert not result['passed'] and result['reason'] == 'quality_violation'
    assert result['max_abs'] == 2 and result['rmse'] > 1
    assert result['quality_count'] == 3 and result['violation_count'] == 2
    assert result['requested_bound'] == '0.01' and result['relative_floor_requested'] == '0'
    point = result['point_relative_components'][0]
    assert point['denominator']['min'] == 0 and point['denominator']['max'] == 100
    assert point['absolute_threshold']['min'] == 0 and point['absolute_threshold']['max'] == 1
    assert point['zero_denominator_violation_count'] == 1
    assert point['finite_relative_error']['max'] == 0.02
    assert result['effective_absolute_bound'] is None
    assert 'pointwise_thresholds' in result['metric_null_reasons']['effective_absolute_bound']
    json.dumps(result, allow_nan=False)


def test_point_relative_floor_and_mask_set_only_actual_quality_positions():
    original = obj(np.array([0., 10., 999.]), mask=np.array([1, 1, 0], dtype=np.uint8))
    restored = obj(np.array([0.005, 10.01, 999.]), mask=np.array([1, 1, 0], dtype=np.uint8))
    result = verify(original, restored, {'fidelity': 'point_relative', 'error_bound': '0.01', 'relative_floor': '1'})
    assert result['passed'] and result['quality_count'] == 2 and result['violation_count'] == 0
    assert result['nrmse_denominator'] == 10 and result['psnr_denominator'] == 10
    assert result['relative_floor_effective'] == 1
    assert result['point_relative_components'][0]['denominator']['min'] == 1
    assert result['point_relative_components'][0]['zero_denominator_count'] == 0


def test_range_relative_reports_normalization_and_violation_without_discarding_metrics():
    original = obj(np.array([0., 10., 1000.]), mask=np.array([1, 1, 0], dtype=np.uint8))
    restored = obj(np.array([0., 11., 1000.]), mask=np.array([1, 1, 0], dtype=np.uint8))
    result = verify(original, restored, {'fidelity': 'range_relative', 'error_bound': '0.05'})
    assert not result['passed'] and result['reason'] == 'quality_violation'
    assert result['requested_bound'] == '0.05' and result['effective_absolute_bound'] == 0.5
    assert result['max_abs'] == 1 and result['violation_count'] == 1
    assert result['nrmse_denominator'] == 10 and result['psnr_denominator'] == 10
    assert result['nrmse'] == pytest.approx(result['rmse'] / 10)
    assert 'task constraint' in result['effective_bound_scope']


@pytest.mark.parametrize('values, expected_reason', [([5., 5.], 'constant_original_range'), ([], 'no_valid_finite_values')])
def test_quality_nulls_explain_actual_denominator(values, expected_reason):
    original = obj(np.array(values, dtype=np.float64))
    result = verify(original, obj(np.array(values, dtype=np.float64)), {'fidelity': 'empirical_quality'})
    assert result['passed'] and result['nrmse_denominator'] == 0
    assert result['max_abs'] == 0 and result['rmse'] == 0
    assert result['metric_null_reasons']['nrmse'] == expected_reason
    assert result['metric_null_reasons']['psnr_db'] == expected_reason
    json.dumps(result, allow_nan=False)


def test_zero_error_nonconstant_psnr_has_its_own_null_reason():
    original = obj(np.array([0., 10.]))
    result = verify(original, obj(np.array([0., 10.])), {'fidelity': 'bounded_abs', 'error_bound': '0'})
    assert result['passed'] and result['nrmse'] == 0 and result['psnr_db'] is None
    assert result['metric_null_reasons']['psnr_db'] == 'zero_error'
    assert result['effective_absolute_bound'] == 0


def test_special_bit_failure_still_retains_eligible_finite_quality():
    original = obj(np.array([-0., 1., 2.]))
    restored = obj(np.array([0., 1.01, 2.01]))
    result = verify(original, restored, {'fidelity': 'empirical_quality'})
    assert not result['passed'] and result['reason'] == 'special_value_mismatch'
    assert result['quality_count'] == 3 and result['max_abs'] > 0.009
    assert result['special_values_policy'] == 'bitwise'


def test_nonfinite_reconstruction_does_not_publish_conditional_finite_subset_metrics():
    original = obj(np.array([1., 2.]))
    result = verify(original, obj(np.array([np.inf, 2.1])), {'fidelity': 'empirical_quality'})
    assert not result['passed'] and result['reason'] == 'nonfinite_reconstruction'
    assert result['quality_count'] == 2 and result['max_abs'] is None
    assert result['metric_null_reasons']['max_abs'] == 'nonfinite_reconstruction'
    json.dumps(result, allow_nan=False)


def test_extended_original_range_is_retained_when_standard_json_number_overflows():
    if np.finfo(np.longdouble).max <= np.finfo(np.float64).max:
        pytest.skip('this interpreter has no extended floating exponent range')
    largest = np.finfo(np.float64).max
    original = obj(np.array([-largest, largest]))
    result = verify(original, obj(np.array([0., 0.])), {'fidelity': 'empirical_quality'})
    assert result['passed'] and result['nrmse_denominator'] is None
    assert result['nrmse'] == 0.5 and result['psnr_db'] == pytest.approx(20 * np.log10(2))
    assert result['metric_null_reasons']['nrmse_denominator'] == 'outside_finite_float64_range'
    assert np.longdouble(result['nrmse_denominator_extended']) > np.longdouble(largest)
    json.dumps(result, allow_nan=False)
