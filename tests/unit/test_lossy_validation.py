from dataclasses import replace
from hashlib import sha256

import numpy as np
import pytest

from tscompbench.accounting import AccountingLedger
from tscompbench.codecs import CompatibilityPlan, DataDescriptor
from tscompbench.contracts import (
    BenchmarkTrack,
    CapabilityStatus,
    LossMode,
    RunStatus,
    Topology,
    ValidityShape,
)
from tscompbench.execution.protocol import (
    DecodedOutput,
    EncodedArtifact,
    LogicalBuffer,
    RoutedInput,
)
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation.correctness import validate_common_correctness
from tscompbench.validation.lossy import (
    LossValidationError,
    profile_unbounded_loss,
    validate_error_bound,
)
from tscompbench.validation.task_validators import (
    TaskValidationError,
    TaskValidationRequest,
    TaskValidationResult,
    TaskValidatorSpec,
    register_task_validator,
    validate_registered_task,
)

QUALITY_FIELDS = (
    "mae",
    "rmse",
    "nrmse_range",
    "max_ae",
    "p50_ae",
    "p95_ae",
    "p99_ae",
    "bias",
    "psnr_range_db",
)


def test_integer_extremes_use_exact_decimal_bound_gate():
    original = np.array([2**63 - 2, 2**63 - 1], dtype=np.int64)
    restored = np.array([2**63 - 1, 2**63 - 1], dtype=np.int64)
    report = validate_error_bound(
        {"v": original},
        {"v": restored},
        error_bound_type="ABS",
        error_bound="0.99999999999999999999999999999",
    )
    assert report.raw_violation_count == 1
    assert report.channels[0].error_comparison_method == "EXACT_RATIONAL_V1"
    assert report.channels[0].max_ae == "1"
    assert report.to_document()["numeric_precision"]["longdouble_mantissa_bits"] >= 53


def test_unsigned_extreme_and_float_reconstruction_gate_are_exact():
    report = validate_error_bound(
        {"v": np.array([2**64 - 1], dtype=np.uint64)},
        {"v": np.array([float(2**64)], dtype=np.float64)},
        error_bound_type="ABS",
        error_bound="0",
    )
    assert report.raw_violation_count == 1
    assert report.channels[0].max_ae == "1"


def test_integer_gate_remains_exact_on_binary64_longdouble_platform(monkeypatch):
    monkeypatch.setattr(np, "longdouble", np.float64)
    report = validate_error_bound(
        {"v": np.array([2**63 - 2, 2**63 - 1], dtype=np.int64)},
        {"v": np.array([2**63 - 1, 2**63 - 1], dtype=np.int64)},
        error_bound_type="ABS",
        error_bound="0.999999999999999999999",
    )
    assert report.raw_violation_count == 1
    assert report.channels[0].max_ae == "1"
    assert report.channels[0].bias == "0.5"
    assert report.to_document()["numeric_precision"]["longdouble_mantissa_bits"] == 53


def test_global_matrix_relative_integer_gate_uses_all_channels():
    report = validate_error_bound(
        {"i": np.array([0, 1], dtype=np.int64), "f": np.array([0.0, 100.0])},
        {"i": np.array([1, 2], dtype=np.int64), "f": np.array([0.0, 100.0])},
        error_bound_type="RANGE_REL",
        error_bound="0.01",
        error_aggregation_mode="GLOBAL_MATRIX",
    )
    assert report.bound_passed is True
    assert report.channels[0].error_comparison_method == "EXACT_RATIONAL_V1"


def test_rate_block_rounding_keeps_tail_budget_and_denominator():
    contract = _rate_contract()
    contract["target_bits_per_value"] = "0.5"
    contract["block_size_values"] = 3
    values = {"v": np.arange(5)}
    artifact = _rate_artifact(payload_bits=3, metadata_bits=5)
    result = validate_registered_task(
        "tscb.validator.rate-budget.v1",
        "RATE_CONTROLLED_LOSSY",
        TaskValidationRequest(values, values, contract, artifact),
    )
    assert result.passed
    assert result.diagnostics["budget_bits_exact"] == "3"
    contract["rounding"] = "NONE"
    assert not validate_registered_task(
        "tscb.validator.rate-budget.v1",
        "RATE_CONTROLLED_LOSSY",
        TaskValidationRequest(values, values, contract, artifact),
    ).passed


def test_multichannel_time_weighted_and_derivative_metrics_are_per_channel():
    report = validate_error_bound(
        {"a": np.array([0.0, 1.0, 2.0]), "b": np.array([10.0, 11.0, 12.0])},
        {"a": np.array([1.0, 1.0, 3.0]), "b": np.array([12.0, 13.0, 14.0])},
        error_bound_type="ABS",
        error_bound="2",
        timestamp=np.array([0, 1, 3]),
    )
    assert float(report.channels[0].time_weighted_rmse) == pytest.approx(np.sqrt(0.5))
    assert report.channels[1].time_weighted_rmse == "2"
    assert report.channels[1].derivative_rmse == "0"
    assert report.temporal_fidelity["status"] == "PER_CHANNEL"
    assert report.time_weighted_rmse is None


@pytest.mark.parametrize(
    "timestamp,reason",
    [
        (None, "TIMESTAMP_UNAVAILABLE"),
        (np.array([0, 1]), "TIMESTAMP_SHAPE_MISMATCH"),
        (np.array([0, 1, 1]), "DUPLICATE_TIMESTAMP"),
        (np.array([0, 2, 1]), "OUT_OF_ORDER_TIMESTAMP"),
        (np.array([0.0, 1.0, np.inf]), "NONFINITE_TIMESTAMP"),
    ],
)
def test_temporal_metrics_have_explicit_applicability_reasons(timestamp, reason):
    values = {"a": np.array([0.0, 1.0, 2.0]), "b": np.array([4.0, 5.0, 6.0])}
    report = profile_unbounded_loss(values, values, timestamp=timestamp)
    assert all(
        c.time_weighted_rmse is None and c.time_weighted_rmse_reason == reason
        for c in report.channels
    )
    assert all(
        c.derivative_rmse is None and c.derivative_rmse_reason == reason for c in report.channels
    )


def test_validity_masks_exclude_null_payload_without_treating_nan_as_null():
    report = validate_error_bound(
        {"v": np.array([0.0, np.nan, np.inf])},
        {"v": np.array([1.0, 99.0, -np.inf])},
        error_bound_type="ABS",
        error_bound="1",
        validity={"v": np.array([True, False, True])},
    )
    assert report.channels[0].valid_element_count == 2
    assert report.channels[0].null_element_count == 1
    assert report.nonfinite_mismatch_count == 1
    assert report.bound_passed is False


def test_lossless_semantic_null_preserves_validity_and_valid_slot_bits():
    routed, plan = _correctness_case([1.0, np.nan, 3.0], LossMode.LOSSLESS)
    mask = np.array([True, False, True])
    validity_buffer = LogicalBuffer("validity", mask, 3)
    routed = replace(routed, buffers=(*routed.buffers, validity_buffer), validity_reference=mask)
    decoded = DecodedOutput(
        (LogicalBuffer("value/000000", np.array([1.0, 99.0, 3.0]), 192), validity_buffer)
    )
    common = dict(
        loss_mode=LossMode.LOSSLESS,
        parameters={},
        deterministic_match=True,
        input_immutable=True,
        canary_intact=True,
    )
    assert (
        validate_common_correctness(routed, decoded, plan, **common).status
        is RunStatus.CORRECTNESS_FAIL
    )
    assert (
        validate_common_correctness(
            routed, decoded, plan, null_recovery_contract="SEMANTIC", **common
        ).status
        is RunStatus.PASS
    )
    changed_mask = DecodedOutput((decoded.buffers[0], LogicalBuffer("validity", ~mask, 3)))
    assert (
        validate_common_correctness(
            routed, changed_mask, plan, null_recovery_contract="SEMANTIC", **common
        ).first_failure_stage
        == "VALIDITY_EXACT"
    )


def _summary_contract():
    return {
        "schema_version": "tscb.summary-property-contract.v1",
        "properties": [
            {
                "input": "value/000000",
                "output": "summary/mean",
                "operation": "MEAN",
                "absolute_tolerance": "0",
            },
        ],
    }


@pytest.mark.parametrize("value,passed", [(2.0, True), (3.0, False)])
def test_summary_correctness_requires_independent_property_acceptance(value, passed):
    routed, plan = _correctness_case([1.0, 2.0, 3.0], LossMode.SUMMARY_ONLY)
    decoded = DecodedOutput((LogicalBuffer("summary/mean", np.array([value]), 64),))
    report = validate_common_correctness(
        routed,
        decoded,
        plan,
        loss_mode=LossMode.SUMMARY_ONLY,
        parameters={},
        deterministic_match=True,
        input_immutable=True,
        canary_intact=True,
        task_validator_id="tscb.validator.summary-scalars.v1",
        validation_contract=_summary_contract(),
    )
    assert (report.status is RunStatus.PASS) is passed
    assert "INDEPENDENT_OUTPUT_PROPERTY_VALIDATOR" in report.checks


def _rate_contract(layer="PAYLOAD_BITS"):
    return {
        "schema_version": "tscb.rate-contract.v1",
        "accounting_layer": layer,
        "denominator": "ALL_VALUE_SLOTS",
        "target_bits_per_value": "4",
        "rounding": "CEIL_PER_BLOCK",
        "block_size_values": 2,
        "tolerance_bits": "0",
        "constraint": "MAXIMUM",
        "quality": {"type": "PROFILE_ONLY"},
    }


def _rate_artifact(payload_bits=12, metadata_bits=4):
    stream = bytes((payload_bits + metadata_bits + 7) // 8)
    ledger = AccountingLedger.create(
        track=BenchmarkTrack.VALUE,
        canonical_raw_bits=192,
        final_physical_bytes=len(stream),
        value_bits=payload_bits,
        metadata_bits=metadata_bits,
    )
    return EncodedArtifact(stream, len(stream), 0, len(stream), sha256(stream).hexdigest(), ledger)


@pytest.mark.parametrize(
    "layer,payload_bits,passed",
    [
        ("PAYLOAD_BITS", 12, True),
        ("FINAL_BITS", 12, False),
        ("PAYLOAD_BITS", 13, False),
    ],
)
def test_rate_validator_uses_real_artifact_and_discloses_full_final_bits(
    layer, payload_bits, passed
):
    routed, plan = _correctness_case([1.0, 2.0, 3.0], LossMode.RATE_CONTROLLED_LOSSY)
    report = validate_common_correctness(
        routed,
        DecodedOutput(routed.buffers),
        plan,
        loss_mode=LossMode.RATE_CONTROLLED_LOSSY,
        parameters={"actual_bits": 0},
        deterministic_match=True,
        input_immutable=True,
        canary_intact=True,
        task_validator_id="tscb.validator.rate-budget.v1",
        validation_contract=_rate_contract(layer),
        encoded_artifact=_rate_artifact(payload_bits),
    )
    assert (report.status is RunStatus.PASS) is passed
    assert report.diagnostics["final_bits"] == payload_bits + 4
    assert report.diagnostics["denominator_value_count"] == 3


def test_rate_validator_cannot_hide_special_value_or_quality_failures():
    values = {"v": np.array([1.0, 2.0, 3.0])}
    request = TaskValidationRequest(
        values, {"v": np.array([1.0, 2.0, np.inf])}, _rate_contract(), _rate_artifact()
    )
    result = validate_registered_task(
        "tscb.validator.rate-budget.v1", "RATE_CONTROLLED_LOSSY", request
    )
    assert not result.passed and result.reason == "RATE_QUALITY_VIOLATION"
    assert result.loss.nonfinite_mismatch_count == 1
    contract = _rate_contract()
    contract["quality"] = {
        "type": "ERROR_BOUND",
        "error_bound_type": "ABS",
        "error_bound": "0.1",
        "relative_error_zero_threshold": "0",
        "error_aggregation_mode": "PER_CHANNEL",
    }
    request = replace(request, outputs={"v": np.array([1.0, 2.0, 3.2])}, contract=contract)
    assert not validate_registered_task(
        "tscb.validator.rate-budget.v1", "RATE_CONTROLLED_LOSSY", request
    ).passed


@pytest.mark.parametrize(
    "change",
    [
        "missing_artifact",
        "unknown_validator",
        "wrong_version",
        "wrong_mode",
        "negative_tolerance",
        "digest_drift",
    ],
)
def test_task_validator_contract_rejects_missing_or_invalid_evidence(change):
    values = {"v": np.array([1.0, 2.0, 3.0])}
    contract = _rate_contract()
    artifact = _rate_artifact()
    validator_id, mode = "tscb.validator.rate-budget.v1", "RATE_CONTROLLED_LOSSY"
    if change == "missing_artifact":
        artifact = None
    elif change == "unknown_validator":
        validator_id = "missing"
    elif change == "wrong_version":
        contract["schema_version"] = "future"
    elif change == "wrong_mode":
        mode = "SUMMARY_ONLY"
    elif change == "negative_tolerance":
        contract["tolerance_bits"] = "-1"
    elif change == "digest_drift":
        artifact = replace(artifact, stream_sha256="0" * 64)
    with pytest.raises(TaskValidationError):
        validate_registered_task(
            validator_id, mode, TaskValidationRequest(values, values, contract, artifact)
        )


def test_independent_task_validator_registration_is_versioned_and_mode_checked():
    spec = TaskValidatorSpec(
        "test.output-property.v1",
        "SUMMARY_ONLY",
        "test.contract.v1",
        lambda request: TaskValidationResult(
            True, None, ("CUSTOM_PROPERTY",), {"property": request.contract["value"]}
        ),
    )
    register_task_validator(spec)
    result = validate_registered_task(
        spec.validator_id,
        "SUMMARY_ONLY",
        TaskValidationRequest({}, {}, {"schema_version": "test.contract.v1", "value": "accepted"}),
    )
    assert result.passed and result.diagnostics["property"] == "accepted"
    with pytest.raises(TaskValidationError, match="already registered"):
        register_task_validator(spec)


@pytest.mark.parametrize("bound_type", ["ABS", "RANGE_REL", "POINTWISE_REL"])
@pytest.mark.parametrize(
    "before,after",
    [(0.0, np.nan), (0.0, np.inf), (np.inf, 0.0), (np.inf, -np.inf), (np.nan, 0.0)],
)
def test_nonfinite_mismatch_fails_bound_and_invalidates_quality(bound_type, before, after):
    report = validate_error_bound(
        {"value/000000": np.array([0.0, 1.0, before])},
        {"value/000000": np.array([0.0, 1.0, after])},
        error_bound_type=bound_type,
        error_bound="0.1",
        timestamp=np.array([0, 1, 2]),
    )
    assert report.bound_passed is False
    assert report.raw_violation_count == report.numerical_violation_count == 1
    assert report.nonfinite_mismatch_count == 1
    assert report.finite_pair_count == 2
    assert report.element_count == 3
    assert report.quality_valid is False
    assert report.quality_invalid_reason == "NONFINITE_VALUE_MISMATCH"
    assert report.time_weighted_rmse is None
    channel = report.to_document()["channels"][0]
    assert channel["nonfinite_mismatch_count"] == 1
    assert channel["quality_invalid_reason"] == "NONFINITE_VALUE_MISMATCH"
    assert all(channel[field] is None for field in QUALITY_FIELDS)


def test_unbounded_profile_preserves_failure_counts_without_claiming_a_bound():
    report = profile_unbounded_loss(
        {"value/000000": np.array([0.0, np.inf, -np.inf, np.nan])},
        {"value/000000": np.array([0.0, -np.inf, 0.0, np.nan])},
    )
    assert report.bound_passed is None
    assert report.raw_violation_count is None
    assert report.numerical_violation_count is None
    assert report.nonfinite_mismatch_count == 2
    assert report.matching_nonfinite_count == 1
    assert report.element_count == 4
    assert report.quality_valid is False
    assert report.channels[0].rmse is None
    document = report.to_document()
    assert document["schema_version"] == "tscb.loss-validation.v3"
    assert document["nonfinite_mismatch_count"] == 2
    assert document["quality_invalid_reason"] == "NONFINITE_VALUE_MISMATCH"


def test_matching_special_values_are_counted_and_do_not_dilute_numeric_rmse():
    report = validate_error_bound(
        {"value/000000": np.array([0.0, 2.0, np.inf, -np.inf, np.nan])},
        {"value/000000": np.array([1.0, 1.0, np.inf, -np.inf, np.nan])},
        error_bound_type="ABS",
        error_bound="1",
    )
    assert report.bound_passed is True
    assert report.element_count == 5
    assert report.finite_pair_count == 2
    assert report.matching_nonfinite_count == 3
    assert report.nonfinite_mismatch_count == 0
    assert report.quality_valid is True
    assert float(report.channels[0].rmse) == 1.0
    assert float(report.channels[0].mae) == 1.0


@pytest.mark.parametrize("special", [np.nan, np.inf, -np.inf])
def test_range_bound_uses_original_finite_range_and_keeps_strict_gate(special):
    report = validate_error_bound(
        {"value/000000": np.array([0.0, 1.0, special])},
        {"value/000000": np.array([0.0, 1.2, special])},
        error_bound_type="RANGE_REL",
        error_bound="0.1",
    )
    assert report.bound_passed is False
    assert report.raw_violation_count == 1
    assert report.nonfinite_mismatch_count == 0


@pytest.mark.parametrize("values", [[], [np.inf, -np.inf, np.nan]])
def test_no_finite_pairs_has_explicit_quality_reason(values):
    report = profile_unbounded_loss(
        {"value/000000": np.array(values)},
        {"value/000000": np.array(values)},
    )
    assert report.finite_pair_count == report.nonfinite_mismatch_count == 0
    assert report.quality_valid is False
    assert report.quality_invalid_reason == "NO_FINITE_VALUE_PAIRS"
    assert all(getattr(report.channels[0], field) is None for field in QUALITY_FIELDS)


@pytest.mark.parametrize("parameter", ["error_bound", "relative_error_zero_threshold"])
@pytest.mark.parametrize("value", ["NaN", "Inf", "-Inf", "not-a-number", "-0.1"])
def test_bound_and_relative_zero_threshold_reject_invalid_values(parameter, value):
    parameters = {"error_bound": "0.1", "relative_error_zero_threshold": "0"}
    parameters[parameter] = value
    with pytest.raises(LossValidationError, match="finite|non-negative"):
        validate_error_bound(
            {"value/000000": np.array([0.0, 1.0])},
            {"value/000000": np.array([0.0, 1.0])},
            error_bound_type="ABS",
            **parameters,
        )


def test_raw_bound_violation_is_not_relaxed_by_ulp_diagnostic():
    report = validate_error_bound(
        {"value/000000": np.array([0.0, 1.0])},
        {"value/000000": np.array([np.nextafter(0.1, np.inf), 1.0])},
        error_bound_type="ABS",
        error_bound="0.1",
    )
    assert report.bound_passed is False
    assert report.raw_violation_count == 1
    assert report.numerical_violation_count == 0


def test_mts_report_keeps_healthy_channel_quality_and_counts_failed_channel():
    report = profile_unbounded_loss(
        {"value/000000": np.array([0.0, 1.0]), "value/000001": np.array([0.0, 1.0])},
        {"value/000000": np.array([0.0, 1.0]), "value/000001": np.array([0.0, np.nan])},
    )
    assert report.channels[0].quality_valid is True
    assert report.channels[0].rmse == "0"
    assert report.channels[1].quality_valid is False
    assert report.channels[1].rmse is None
    assert report.nonfinite_mismatch_count == 1
    assert report.element_count == 4
    assert report.finite_pair_count == 3
    assert report.quality_valid is False


def _correctness_case(values, loss_mode):
    values = np.asarray(values, dtype="<f8")
    descriptor = DataDescriptor(
        dataset_id="test:loss-correctness",
        track=BenchmarkTrack.VALUE,
        topology=Topology.UTS,
        n=values.size,
        m=1,
        shape=values.shape,
        dtype_vector=(values.dtype.str,),
        physical_layout="SOA_COLUMNS",
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=values.nbytes * 8,
        validity_shape=ValidityShape.NONE,
        timestamp_present=False,
        preserve_order=True,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )
    plan = CompatibilityPlan.create(
        status=CapabilityStatus.DIRECT_SUPPORTED,
        reason_code="DIRECT_TEST_DOMAIN",
        missing_capabilities=(),
        input_descriptor=descriptor,
        output_descriptor=None,
        operations=(),
        effective_loss_mode=loss_mode,
    )
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    routed = RoutedInput(
        dataset_id=descriptor.dataset_id,
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=values.size,
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )
    return routed, plan


@pytest.mark.parametrize(
    "loss_mode,expected_stage",
    [
        (LossMode.SUMMARY_ONLY, "OUTPUT_PROPERTY_VALIDATOR_UNAVAILABLE"),
        (LossMode.RATE_CONTROLLED_LOSSY, "RATE_VALIDATOR_UNAVAILABLE"),
    ],
)
def test_special_task_without_validator_cannot_pass(loss_mode, expected_stage):
    routed, plan = _correctness_case([0.0, 1.0, 2.0], loss_mode)
    # Even exact roundtrip data and successful safety checks prove neither a
    # summary property nor an actual rate budget.
    report = validate_common_correctness(
        routed,
        DecodedOutput(routed.buffers),
        plan,
        loss_mode=loss_mode,
        parameters={"target_rate": "8"},
        deterministic_match=True,
        input_immutable=True,
        canary_intact=True,
    )
    assert report.status is RunStatus.UNSUPPORTED
    assert report.first_failure_stage == expected_stage
    assert report.loss is None
    assert "RATE_TARGET_RECORDED" not in report.checks
    assert "SUMMARY_TRACK_CONFIRMED" not in report.checks


@pytest.mark.parametrize("before,after", [(np.inf, -np.inf), (np.nan, 0.0), (0.0, np.inf)])
def test_unbounded_correctness_rejects_nonfinite_mismatch_and_keeps_quality_report(before, after):
    routed, plan = _correctness_case([0.0, 1.0, before], LossMode.UNBOUNDED_LOSSY)
    restored = np.asarray([0.0, 1.0, after], dtype="<f8")
    decoded = DecodedOutput((LogicalBuffer("value/000000", restored, restored.nbytes * 8),))
    report = validate_common_correctness(
        routed,
        decoded,
        plan,
        loss_mode=LossMode.UNBOUNDED_LOSSY,
        parameters={},
        deterministic_match=True,
        input_immutable=True,
        canary_intact=True,
    )
    assert report.status is RunStatus.CORRECTNESS_FAIL
    assert report.first_failure_stage == "NONFINITE_VALUE_MISMATCH"
    assert report.diagnostics["nonfinite_mismatch_count"] == 1
    assert report.loss.nonfinite_mismatch_count == 1
    assert report.loss.channels[0].rmse is None
    assert report.to_document()["loss"]["quality_invalid_reason"] == "NONFINITE_VALUE_MISMATCH"


def test_unbounded_correctness_accepts_matching_special_value_semantics():
    routed, plan = _correctness_case([0.0, np.inf, np.nan], LossMode.UNBOUNDED_LOSSY)
    report = validate_common_correctness(
        routed,
        DecodedOutput(routed.buffers),
        plan,
        loss_mode=LossMode.UNBOUNDED_LOSSY,
        parameters={},
        deterministic_match=True,
        input_immutable=True,
        canary_intact=True,
    )
    assert report.status is RunStatus.PASS
    assert report.loss.nonfinite_mismatch_count == 0
    assert report.loss.matching_nonfinite_count == 2
    assert report.loss.finite_pair_count == 1


def test_bounded_correctness_keeps_special_value_violation_as_bound_failure():
    routed, plan = _correctness_case([0.0, 1.0, np.inf], LossMode.ERROR_BOUNDED_LOSSY)
    restored = np.asarray([0.0, 1.0, 0.0], dtype="<f8")
    decoded = DecodedOutput((LogicalBuffer("value/000000", restored, restored.nbytes * 8),))
    report = validate_common_correctness(
        routed,
        decoded,
        plan,
        loss_mode=LossMode.ERROR_BOUNDED_LOSSY,
        parameters={"error_bound_type": "RANGE_REL", "error_bound": "0.1"},
        deterministic_match=True,
        input_immutable=True,
        canary_intact=True,
    )
    assert report.status is RunStatus.BOUND_VIOLATION
    assert report.loss.nonfinite_mismatch_count == report.loss.raw_violation_count == 1
    assert report.loss.channels[0].max_ae is None


@pytest.mark.parametrize("restored_dtype", ["<f8", "<u8", ">i8"])
def test_timestamp_exactness_cannot_use_numpy_cross_dtype_numeric_equality(restored_dtype):
    routed, plan = _correctness_case([1.0], LossMode.LOSSLESS)
    timestamp = np.array([2**53 + 1], dtype="<i8")
    routed = replace(
        routed,
        track=BenchmarkTrack.TIMESTAMP,
        buffers=(LogicalBuffer("timestamp", timestamp, timestamp.nbytes * 8),),
        timestamp_reference=timestamp,
    )
    plan = replace(
        plan, input_descriptor=replace(plan.input_descriptor, track=BenchmarkTrack.TIMESTAMP)
    )
    restored = timestamp.astype(restored_dtype)
    report = validate_common_correctness(
        routed,
        DecodedOutput((LogicalBuffer("timestamp", restored, restored.nbytes * 8),)),
        plan,
        loss_mode=LossMode.LOSSLESS,
        parameters={},
        deterministic_match=True,
        input_immutable=True,
        canary_intact=True,
    )
    assert report.status is RunStatus.CORRECTNESS_FAIL
    assert report.first_failure_stage == "TIMESTAMP_EXACT_ORDER_UNIT_EPOCH"
