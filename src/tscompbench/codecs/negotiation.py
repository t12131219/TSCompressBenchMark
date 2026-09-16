from __future__ import annotations

from dataclasses import asdict
from typing import Any

import numpy as np

from tscompbench.contracts import (
    AdapterOperationKind,
    BenchmarkTrack,
    CapabilityStatus,
    LossMode,
    PreprocessClass,
    Topology,
    ValidityShape,
)
from tscompbench.datasets import CanonicalDataset
from tscompbench.ids import stable_id

from .models import AdapterOperation, CodecManifest, CompatibilityPlan, DataDescriptor


def _alignment(array: np.ndarray[Any]) -> int:
    pointer = int(array.__array_interface__["data"][0])
    alignment = 1
    while alignment < 64 and pointer % (alignment * 2) == 0:
        alignment *= 2
    return alignment


def descriptor_from_dataset(dataset: CanonicalDataset, track: BenchmarkTrack) -> DataDescriptor:
    logical = dataset.logical_descriptor
    topology = Topology(logical["topology"])
    validity = ValidityShape(logical["validity_shape"])
    timestamp = dataset.timestamp
    has_duplicates = False
    has_out_of_order = False
    has_negative_delta = False
    if timestamp is not None and timestamp.size > 1:
        delta = np.diff(timestamp)
        has_duplicates = bool(np.any(delta == 0))
        has_out_of_order = bool(np.any(delta < 0))
        has_negative_delta = has_out_of_order

    if track is BenchmarkTrack.TIMESTAMP:
        if timestamp is None:
            dtype_vector = ("<i8",)
            shape = (dataset.n_rows,)
            layout = "NOT_APPLICABLE"
            alignment = 1
        else:
            dtype_vector = (timestamp.dtype.str,)
            shape = tuple(int(item) for item in timestamp.shape)
            physical = next(
                item
                for item in dataset.physical_descriptors
                if item["view_id"].startswith("timestamp")
            )
            layout = str(physical["layout"])
            alignment = _alignment(timestamp)
        raw_bits = dataset.timestamp_raw_bits
        m = 1
    elif track is BenchmarkTrack.VALUE:
        dtype_vector = tuple(item.array.dtype.str for item in dataset.values)
        shape = tuple(int(item) for item in logical["value_shape"])
        physical = next(
            item for item in dataset.physical_descriptors if item["view_id"].startswith("value")
        )
        layout = str(physical["layout"])
        alignment = min(_alignment(item.array) for item in dataset.values)
        raw_bits = dataset.value_raw_bits + dataset.validity_raw_bits
        m = len(dataset.values) if len(dataset.values) > 1 else (shape[1] if len(shape) > 1 else 1)
    else:
        dtype_vector = ((timestamp.dtype.str,) if timestamp is not None else ()) + tuple(
            item.array.dtype.str for item in dataset.values
        )
        shape = tuple(int(item) for item in logical["value_shape"])
        layout = "COMPOSITE_T_V"
        arrays = ([timestamp] if timestamp is not None else []) + [
            item.array for item in dataset.values
        ]
        alignment = min(_alignment(item) for item in arrays)
        raw_bits = dataset.canonical_raw_bits
        m = len(dataset.values) if len(dataset.values) > 1 else (shape[1] if len(shape) > 1 else 1)

    return DataDescriptor(
        dataset_id=dataset.dataset_id,
        track=track,
        topology=topology,
        n=dataset.n_rows,
        m=m,
        shape=shape,
        dtype_vector=dtype_vector,
        physical_layout=layout,
        endianness="little",
        alignment_bytes=alignment,
        canonical_raw_bits=raw_bits,
        validity_shape=validity,
        timestamp_present=timestamp is not None,
        preserve_order=logical.get("timestamp", {}).get("order_policy") == "PRESERVE",
        has_duplicates=has_duplicates,
        has_out_of_order=has_out_of_order,
        has_negative_delta=has_negative_delta,
        timestamp_unit=str(logical.get("timestamp", {}).get("unit", "NOT_APPLICABLE")),
        timestamp_epoch=str(logical.get("timestamp", {}).get("epoch", "NOT_APPLICABLE")),
        value_units=tuple(str(item.unit) for item in dataset.values),
    )


def descriptor_from_layer1_artifacts(
    metadata: dict[str, Any],
    characterization: dict[str, Any],
    track: BenchmarkTrack,
) -> DataDescriptor:
    """Build Layer 2 input facts only from frozen Layer 1 outputs."""

    logical = metadata["logical_descriptor"]
    physical_descriptors = metadata["physical_descriptors"]
    timestamp_stats = characterization.get("timestamp", {})
    timestamp_present = bool(timestamp_stats.get("present", False))
    if track is BenchmarkTrack.TIMESTAMP:
        shape = (int(logical["n_rows"]),)
        dtype_vector = ("<i8",)
        layout = next(
            (
                item["layout"]
                for item in physical_descriptors
                if item["view_id"].startswith("timestamp")
            ),
            "NOT_APPLICABLE",
        )
        raw_bits = int(metadata["accounting"]["timestamp_raw_bits"])
        m = 1
    elif track is BenchmarkTrack.VALUE:
        shape = tuple(int(item) for item in logical["value_shape"])
        dtype_vector = tuple(item["dtype"] for item in logical["value_columns"])
        layout = next(
            item["layout"] for item in physical_descriptors if item["view_id"].startswith("value")
        )
        raw_bits = int(metadata["accounting"]["value_raw_bits"]) + int(
            metadata["accounting"]["validity_raw_bits"]
        )
        m = len(dtype_vector) if len(dtype_vector) > 1 else (shape[1] if len(shape) > 1 else 1)
    else:
        shape = tuple(int(item) for item in logical["value_shape"])
        dtype_vector = (("<i8",) if timestamp_present else ()) + tuple(
            item["dtype"] for item in logical["value_columns"]
        )
        layout = "COMPOSITE_T_V"
        raw_bits = int(metadata["accounting"]["canonical_raw_bits"])
        m = len(logical["value_columns"])
    return DataDescriptor(
        dataset_id=str(metadata["dataset_id"]),
        track=track,
        topology=Topology(logical["topology"]),
        n=int(logical["n_rows"]),
        m=m,
        shape=shape,
        dtype_vector=dtype_vector,
        physical_layout=str(layout),
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=raw_bits,
        validity_shape=ValidityShape(logical["validity_shape"]),
        timestamp_present=timestamp_present,
        preserve_order=logical.get("timestamp", {}).get("order_policy") == "PRESERVE",
        has_duplicates=int(timestamp_stats.get("duplicate_count", 0)) > 0,
        has_out_of_order=int(timestamp_stats.get("out_of_order_count", 0)) > 0,
        has_negative_delta=int(timestamp_stats.get("negative_delta_count", 0)) > 0,
        timestamp_unit=str(logical.get("timestamp", {}).get("unit", "NOT_APPLICABLE")),
        timestamp_epoch=str(logical.get("timestamp", {}).get("epoch", "NOT_APPLICABLE")),
        value_units=tuple(
            str(item.get("unit", "UNSPECIFIED")) for item in logical["value_columns"]
        ),
    )


def _operation(
    *,
    kind: AdapterOperationKind,
    semantic_class: PreprocessClass,
    before: dict[str, Any],
    after: dict[str, Any],
    bytes_read: int,
    bytes_written: int,
    allocation_bytes: int,
    padding_bytes: int = 0,
    external_metadata_bits: int = 0,
    reverse_operation: str,
    validation_method: str,
) -> AdapterOperation:
    identity = {
        "kind": kind,
        "semantic_class": semantic_class,
        "before": before,
        "after": after,
        "reverse_operation": reverse_operation,
    }
    return AdapterOperation(
        operation_id=stable_id("adapter-operation", identity),
        kind=kind,
        semantic_class=semantic_class,
        before_descriptor=before,
        after_descriptor=after,
        bytes_read=bytes_read,
        bytes_written=bytes_written,
        allocation_bytes=allocation_bytes,
        padding_bytes=padding_bytes,
        external_metadata_bits=external_metadata_bits,
        timing_scopes=("PIPELINE", "E2E"),
        reverse_operation=reverse_operation,
        validation_method=validation_method,
    )


def _conversion(source: str, supported: tuple[str, ...]) -> tuple[str, bool] | None:
    source_dtype = np.dtype(source)
    for target in supported:
        if source_dtype == np.dtype(target):
            return np.dtype(target).str, False
    lossless: list[np.dtype[Any]] = []
    lossy: list[np.dtype[Any]] = []
    for value in supported:
        target = np.dtype(value)
        if (
            source_dtype.kind == target.kind
            and source_dtype.kind in "iu"
            and target.itemsize >= source_dtype.itemsize
        ):
            lossless.append(target)
        elif source_dtype.kind == target.kind == "f" and target.itemsize >= source_dtype.itemsize:
            lossless.append(target)
        else:
            lossy.append(target)
    if lossless:
        return min(lossless, key=lambda item: item.itemsize).str, False
    if lossy:
        return lossy[0].str, True
    return None


def negotiate(
    manifest: CodecManifest,
    descriptor: DataDescriptor,
    *,
    requested_loss_mode: LossMode = LossMode.LOSSLESS,
) -> CompatibilityPlan:
    contract = manifest.document["input"]
    missing: list[str] = []
    if descriptor.track not in manifest.tracks:
        missing.append("track")
    if descriptor.topology.value not in contract["topologies"]:
        missing.append("topology")
    if not contract["min_n"] <= descriptor.n <= contract["max_n"]:
        missing.append("n")
    if not contract["min_m"] <= descriptor.m <= contract["max_m"]:
        missing.append("m")
    if len(descriptor.shape) not in contract["ranks"]:
        missing.append("rank")
    if descriptor.validity_shape.value not in contract["validity_shapes"]:
        missing.append("validity_shape")
    timestamp_contract = contract["timestamp_semantics"]
    if descriptor.track in {BenchmarkTrack.TIMESTAMP, BenchmarkTrack.SYSTEM}:
        if not descriptor.timestamp_present:
            missing.append("timestamp_present")
        if descriptor.has_duplicates and not timestamp_contract["duplicates"]:
            missing.append("timestamp_duplicates")
        if descriptor.has_out_of_order and not timestamp_contract["out_of_order"]:
            missing.append("timestamp_out_of_order")
        if descriptor.has_negative_delta and not timestamp_contract["negative_delta"]:
            missing.append("timestamp_negative_delta")
        if descriptor.preserve_order and not timestamp_contract["preserve_order"]:
            missing.append("timestamp_preserve_order")
        if timestamp_contract["overflow_policy"] == "UNSPECIFIED":
            missing.append("timestamp_overflow_policy")
    if missing:
        return CompatibilityPlan.create(
            status=CapabilityStatus.UNSUPPORTED,
            reason_code="CAPABILITY_MISMATCH",
            missing_capabilities=tuple(sorted(set(missing))),
            input_descriptor=descriptor,
            output_descriptor=None,
            operations=(),
            effective_loss_mode=requested_loss_mode,
        )

    current = asdict(descriptor)
    operations: list[AdapterOperation] = []
    logical_bytes = (descriptor.canonical_raw_bits + 7) // 8
    if descriptor.physical_layout not in contract["layouts"]:
        target_layout = contract["layouts"][0]
        before = dict(current)
        current["physical_layout"] = target_layout
        kind = (
            AdapterOperationKind.TRANSPOSE_COPY
            if {descriptor.physical_layout, target_layout}
            & {"ROW_MAJOR_CONTIG", "COLUMN_MAJOR_CONTIG", "SOA_COLUMNS"}
            else AdapterOperationKind.CONTIGUOUS_COPY
        )
        operations.append(
            _operation(
                kind=kind,
                semantic_class=PreprocessClass.LOSSLESS_LAYOUT,
                before=before,
                after=dict(current),
                bytes_read=logical_bytes,
                bytes_written=logical_bytes,
                allocation_bytes=logical_bytes,
                reverse_operation="RESTORE_LOGICAL_AXES",
                validation_method="BIT_EXACT_LOGICAL_VIEW",
            )
        )

    supported_dtypes = tuple(contract["dtypes"])
    converted: list[str] = []
    lossy_conversion = False
    for source in descriptor.dtype_vector:
        conversion = _conversion(source, supported_dtypes)
        if conversion is None:
            return CompatibilityPlan.create(
                status=CapabilityStatus.UNSUPPORTED,
                reason_code="DTYPE_UNSUPPORTED",
                missing_capabilities=(f"dtype:{source}",),
                input_descriptor=descriptor,
                output_descriptor=None,
                operations=tuple(operations),
                effective_loss_mode=requested_loss_mode,
            )
        target, lossy = conversion
        converted.append(target)
        lossy_conversion = lossy_conversion or lossy
    if tuple(converted) != descriptor.dtype_vector:
        before = dict(current)
        current["dtype_vector"] = converted
        target_bytes = sum(np.dtype(item).itemsize for item in converted) * descriptor.n
        operations.append(
            _operation(
                kind=(
                    AdapterOperationKind.LOSSY_CAST
                    if lossy_conversion
                    else AdapterOperationKind.EXACT_WIDEN
                ),
                semantic_class=(
                    PreprocessClass.LOSSY_PREPROCESS
                    if lossy_conversion
                    else PreprocessClass.LOSSLESS_LAYOUT
                ),
                before=before,
                after=dict(current),
                bytes_read=logical_bytes,
                bytes_written=target_bytes,
                allocation_bytes=target_bytes,
                reverse_operation="CAST_TO_CANONICAL_DTYPE",
                validation_method=(
                    "DECLARED_ERROR_BOUND" if lossy_conversion else "BIT_EXACT_AFTER_INVERSE"
                ),
            )
        )

    if descriptor.endianness not in contract["endianness"]:
        if "little" not in contract["endianness"] and "big" not in contract["endianness"]:
            return CompatibilityPlan.create(
                status=CapabilityStatus.UNSUPPORTED,
                reason_code="ENDIANNESS_UNSUPPORTED",
                missing_capabilities=("endianness",),
                input_descriptor=descriptor,
                output_descriptor=None,
                operations=tuple(operations),
                effective_loss_mode=requested_loss_mode,
            )
        before = dict(current)
        current["endianness"] = contract["endianness"][0]
        operations.append(
            _operation(
                kind=AdapterOperationKind.ENDIANNESS_CONVERSION,
                semantic_class=PreprocessClass.LOSSLESS_LAYOUT,
                before=before,
                after=dict(current),
                bytes_read=logical_bytes,
                bytes_written=logical_bytes,
                allocation_bytes=logical_bytes,
                reverse_operation="BYTE_SWAP",
                validation_method="BIT_EXACT_AFTER_INVERSE",
            )
        )

    required_alignment = int(contract["alignment_bytes"])
    if descriptor.alignment_bytes < required_alignment:
        before = dict(current)
        current["alignment_bytes"] = required_alignment
        operations.append(
            _operation(
                kind=AdapterOperationKind.ALIGNMENT_COPY,
                semantic_class=PreprocessClass.LOSSLESS_LAYOUT,
                before=before,
                after=dict(current),
                bytes_read=logical_bytes,
                bytes_written=logical_bytes,
                allocation_bytes=logical_bytes + required_alignment - 1,
                reverse_operation="IDENTITY_LOGICAL_VIEW",
                validation_method="BIT_EXACT_LOGICAL_VIEW",
            )
        )

    padding = int(manifest.document["lifecycle"]["safe_overread_bytes"])
    if padding:
        before = dict(current)
        current["safe_overread_padding_bytes"] = padding
        operations.append(
            _operation(
                kind=AdapterOperationKind.SAFE_OVERREAD_PADDING,
                semantic_class=PreprocessClass.LOSSLESS_LAYOUT,
                before=before,
                after=dict(current),
                bytes_read=logical_bytes,
                bytes_written=logical_bytes + padding,
                allocation_bytes=logical_bytes + padding,
                padding_bytes=padding,
                reverse_operation="DROP_UNAUTHORIZED_PADDING",
                validation_method="LOGICAL_PREFIX_AND_CANARY",
            )
        )

    is_lossy = lossy_conversion or manifest.preprocess_class is PreprocessClass.LOSSY_PREPROCESS
    effective_loss = requested_loss_mode
    if is_lossy:
        effective_loss = next(
            (item for item in manifest.loss_modes if item is not LossMode.LOSSLESS),
            LossMode.ERROR_BOUNDED_LOSSY,
        )
    status = (
        CapabilityStatus.ADAPTER_LOSSY
        if is_lossy
        else CapabilityStatus.ADAPTER_LOSSLESS
        if operations
        else CapabilityStatus.DIRECT_SUPPORTED
    )
    return CompatibilityPlan.create(
        status=status,
        reason_code="COMPATIBLE",
        missing_capabilities=(),
        input_descriptor=descriptor,
        output_descriptor=current,
        operations=tuple(operations),
        effective_loss_mode=effective_loss,
    )
