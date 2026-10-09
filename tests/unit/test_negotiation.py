from dataclasses import replace
from pathlib import Path

import numpy as np

from tscompbench.adapters import apply_compatibility_plan, validate_prepared_input
from tscompbench.codecs import (
    CodecRegistry,
    DataDescriptor,
    SourceRegistry,
    negotiate,
)
from tscompbench.contracts import (
    BenchmarkTrack,
    CapabilityStatus,
    LossMode,
    Topology,
    ValidityShape,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _codecs() -> CodecRegistry:
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    return CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources)


def _descriptor() -> DataDescriptor:
    return DataDescriptor(
        dataset_id="v2:dataset:sha256:" + "0" * 64,
        track=BenchmarkTrack.VALUE,
        topology=Topology.SYNCHRONOUS_MTS,
        n=4,
        m=1,
        shape=(4,),
        dtype_vector=("<f8",),
        physical_layout="SOA_COLUMNS",
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=256,
        validity_shape=ValidityShape.NONE,
        timestamp_present=True,
        preserve_order=True,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )


def test_four_state_negotiation_and_adapter_validation() -> None:
    codecs = _codecs()
    descriptor = _descriptor()
    direct = negotiate(codecs.get("oracle-direct"), descriptor)
    assert direct.status is CapabilityStatus.DIRECT_SUPPORTED
    lossless = negotiate(codecs.get("oracle-lossless-adapter"), descriptor)
    lossy = negotiate(codecs.get("oracle-lossy-adapter"), descriptor)
    unsupported = negotiate(codecs.get("oracle-native-nd-only"), descriptor)
    assert lossless.status is CapabilityStatus.ADAPTER_LOSSLESS
    assert lossy.status is CapabilityStatus.ADAPTER_LOSSY
    assert unsupported.status is CapabilityStatus.UNSUPPORTED
    assert unsupported.missing_capabilities == ("rank", "topology")

    original = np.array([0.0, -0.0, 1.25, -3.5], dtype="<f8")
    original.flags.writeable = False
    prepared = apply_compatibility_plan(original, lossless)
    validate_prepared_input(original, prepared, lossless)
    assert prepared.telemetry.padding_bytes == 16
    assert prepared.telemetry.copied is True

    lossy_prepared = apply_compatibility_plan(original, lossy)
    validate_prepared_input(original, lossy_prepared, lossy, max_abs_error="0.000001")
    assert original.tobytes() == np.array([0.0, -0.0, 1.25, -3.5], dtype="<f8").tobytes()


def test_entropy_object_byte_limit_is_independent_of_row_and_column_limits() -> None:
    codecs = _codecs()
    for key in ("fse", "huff0"):
        manifest = codecs.get(key)
        at_limit = replace(
            _descriptor(),
            n=2048,
            m=8,
            shape=(2048, 8),
            dtype_vector=("<f8",) * 8,
            canonical_raw_bits=131072 * 8,
        )
        assert negotiate(manifest, at_limit).status is not CapabilityStatus.UNSUPPORTED
        over_limit = replace(at_limit, n=2049, shape=(2049, 8), canonical_raw_bits=2049 * 8 * 64)
        rejected = negotiate(manifest, over_limit)
        assert rejected.status is CapabilityStatus.UNSUPPORTED
        assert rejected.missing_capabilities == ("total_raw_bytes",)


def test_native_lossy_codec_uses_its_declared_loss_mode() -> None:
    manifest = _codecs().get("serf-qt")
    compatibility = negotiate(manifest, _descriptor())
    assert compatibility.status is CapabilityStatus.DIRECT_SUPPORTED
    assert compatibility.effective_loss_mode is LossMode.ERROR_BOUNDED_LOSSY

    unsupported = negotiate(
        manifest,
        _descriptor(),
        requested_loss_mode=LossMode.LOSSLESS,
    )
    assert unsupported.status is CapabilityStatus.UNSUPPORTED
    assert unsupported.reason_code == "LOSS_MODE_UNSUPPORTED"


def test_rewrite_capacity_limits_are_rejected_during_planning() -> None:
    manifest = _codecs().get("self-star")
    descriptor = replace(_descriptor(), n=1025, shape=(1025,), canonical_raw_bits=1025 * 64)
    small_blocks = negotiate(manifest, descriptor, parameters={"block_size": 1})
    assert small_blocks.status is CapabilityStatus.UNSUPPORTED
    assert small_blocks.missing_capabilities == ("blocks_per_column",)
    assert negotiate(manifest, descriptor, parameters={"block_size": 2}).status is not (
        CapabilityStatus.UNSUPPORTED
    )
    descriptor = replace(
        _descriptor(),
        n=8388609,
        m=2,
        shape=(8388609, 2),
        dtype_vector=("<f4", "<f4"),
        canonical_raw_bits=8388609 * 2 * 32,
    )
    too_many = negotiate(_codecs().get("chimp"), descriptor)
    assert too_many.status is CapabilityStatus.UNSUPPORTED
    assert too_many.missing_capabilities == ("total_elements",)


def test_nd_channel_count_and_widening_bytes_use_all_non_time_axes():
    from tscompbench.codecs import descriptor_from_dataset
    from tscompbench.datasets import DatasetRegistry, load_dataset
    from tscompbench.datasets.models import immutable

    dataset = load_dataset(
        DatasetRegistry(PROJECT_ROOT / "registry/datasets", PROJECT_ROOT).load("sprintz_i16_mts")
    )
    array = immutable(np.arange(24, dtype="<f4").reshape(2, 3, 4))
    buffer = replace(dataset.values[0], array=array)
    logical = {
        **dataset.logical_descriptor,
        "n_rows": 2,
        "topology": "NATIVE_ND_ARRAY",
        "value_shape": [2, 3, 4],
        "value_columns": [buffer.descriptor()],
    }
    dataset = replace(dataset, values=(buffer,), logical_descriptor=logical)
    descriptor = descriptor_from_dataset(dataset, BenchmarkTrack.VALUE)
    assert descriptor.m == 12
    # ND-only oracle widens float32 to float64; every element is charged.
    plan = negotiate(_codecs().get("oracle-native-nd-only"), descriptor)
    assert plan.status is not CapabilityStatus.UNSUPPORTED
    from tscompbench.contracts import AdapterOperationKind

    cast = next(op for op in plan.operations if op.kind is AdapterOperationKind.EXACT_WIDEN)
    assert cast.bytes_written == 24 * 8


def test_timestamp_order_facts_do_not_overflow_int64_delta():
    from tscompbench.codecs import descriptor_from_dataset
    from tscompbench.datasets import DatasetRegistry, load_dataset
    from tscompbench.datasets.models import immutable

    dataset = load_dataset(
        DatasetRegistry(PROJECT_ROOT / "registry/datasets", PROJECT_ROOT).load(
            "streamvbyte_u32_uts"
        )
    )
    timestamp = immutable(np.array([-(2**63), 2**63 - 1], dtype="<i8"))
    dataset = replace(dataset, timestamp=timestamp)
    descriptor = descriptor_from_dataset(dataset, BenchmarkTrack.SYSTEM)
    assert not descriptor.has_out_of_order
    assert not descriptor.has_negative_delta


def test_adapter_reports_each_output_allocation_and_zero_for_noop():
    from tscompbench.codecs.models import CompatibilityPlan
    from tscompbench.contracts import AdapterOperationKind, PreprocessClass

    descriptor = replace(_descriptor(), dtype_vector=("|u1",), canonical_raw_bits=32)
    before = {"dtype_vector": ["|u1"]}
    from tscompbench.codecs.negotiation import _operation

    operation = _operation(
        kind=AdapterOperationKind.CONTIGUOUS_COPY,
        semantic_class=PreprocessClass.LOSSLESS_LAYOUT,
        before=before,
        after=before,
        bytes_read=4,
        bytes_written=4,
        allocation_bytes=4,
        reverse_operation="IDENTITY",
        validation_method="BIT_EXACT",
    )
    plan = CompatibilityPlan.create(
        status=CapabilityStatus.ADAPTER_LOSSLESS,
        reason_code="TEST",
        missing_capabilities=(),
        input_descriptor=descriptor,
        output_descriptor=descriptor,
        operations=(operation,),
        effective_loss_mode=LossMode.LOSSLESS,
    )
    array = np.arange(4, dtype="u1")
    prepared = apply_compatibility_plan(array, plan)
    assert prepared.telemetry.allocation_bytes == 0
    assert prepared.telemetry.bytes_read == prepared.telemetry.bytes_written == 0
    assert prepared.telemetry.stages[0]["planned_allocation_bytes"] == 4
    assert not prepared.telemetry.copied


def test_signaling_nan_widening_rejects_without_mutating_canonical_bits():
    import pytest

    from tscompbench.adapters.compatibility import CompatibilityDomainError
    from tscompbench.codecs.models import CompatibilityPlan
    from tscompbench.codecs.negotiation import _operation
    from tscompbench.contracts import AdapterOperationKind, PreprocessClass

    descriptor = replace(
        _descriptor(), dtype_vector=("<f4",), shape=(2,), n=2, canonical_raw_bits=64
    )
    op = _operation(
        kind=AdapterOperationKind.EXACT_WIDEN,
        semantic_class=PreprocessClass.LOSSLESS_LAYOUT,
        before={"dtype_vector": ["<f4"]},
        after={"dtype_vector": ["<f8"]},
        bytes_read=8,
        bytes_written=16,
        allocation_bytes=16,
        reverse_operation="CAST_TO_CANONICAL_DTYPE",
        validation_method="BIT_EXACT_AFTER_INVERSE",
    )
    plan = CompatibilityPlan.create(
        status=CapabilityStatus.ADAPTER_LOSSLESS,
        reason_code="TEST",
        missing_capabilities=(),
        input_descriptor=descriptor,
        output_descriptor=replace(descriptor, dtype_vector=("<f8",)),
        operations=(op,),
        effective_loss_mode=LossMode.LOSSLESS,
    )
    original = np.array([0x7F800001, 0x80000000], dtype="<u4").view("<f4")
    original.flags.writeable = False
    before = original.tobytes()
    prepared = apply_compatibility_plan(original, plan)
    with pytest.raises(CompatibilityDomainError):
        validate_prepared_input(original, prepared, plan)
    assert original.tobytes() == before

    # A broken conversion of a supported finite value is an implementation
    # error, not an unsupported IEEE subdomain.
    from tscompbench.codecs import CodecContractError

    finite = np.array([1.0, 2.0], dtype="<f4")
    finite.flags.writeable = False
    valid = apply_compatibility_plan(finite, plan)
    validate_prepared_input(finite, valid, plan)
    broken = replace(valid, logical_array=np.array([1.0, 3.0], dtype="<f8"))
    with pytest.raises(CodecContractError) as failure:
        validate_prepared_input(finite, broken, plan)
    assert not isinstance(failure.value, CompatibilityDomainError)


def test_bounded_cast_rejects_unrepresentable_input_but_not_adapter_corruption():
    import pytest

    from tscompbench.adapters.compatibility import LossyCompatibilityDomainError
    from tscompbench.codecs import CodecContractError

    plan = negotiate(_codecs().get("oracle-lossy-adapter"), _descriptor())
    for original in (
        np.array([np.nan, np.inf, -np.inf, 1.0], dtype="<f8"),
        np.array([1e300, 0.0, 1.0, 2.0], dtype="<f8"),
        np.array([16777217.0, 0.0, 1.0, 2.0], dtype="<f8"),
    ):
        original.flags.writeable = False
        before = original.tobytes()
        with np.errstate(all="ignore"):
            prepared = apply_compatibility_plan(original, plan)
            with pytest.raises(LossyCompatibilityDomainError):
                validate_prepared_input(original, prepared, plan, max_abs_error="0.01")
        assert original.tobytes() == before
    original = np.array([1.0, 2.0, 3.0, 4.0], dtype="<f8")
    valid = apply_compatibility_plan(original, plan)
    validate_prepared_input(original, valid, plan, max_abs_error="0.01")
    broken = replace(valid, logical_array=np.array([9.0, 2.0, 3.0, 4.0], dtype="<f4"))
    with pytest.raises(CodecContractError) as failure:
        validate_prepared_input(original, broken, plan, max_abs_error="0.01")
    assert not isinstance(failure.value, LossyCompatibilityDomainError)
