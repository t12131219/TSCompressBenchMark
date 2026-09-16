from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from tscompbench.contracts import BenchmarkTrack
from tscompbench.datasets.canonical import CanonicalArtifact
from tscompbench.ids import canonical_json_bytes, stable_id

from .protocol import ExecutionContractError, LogicalBuffer, RoutedInput


def _array_from_payload(descriptor: dict[str, Any], payload: bytes) -> np.ndarray[Any]:
    shape = tuple(int(value) for value in descriptor["shape"])
    if descriptor["dtype"] == "bitmap-lsb0":
        size = int(np.prod(shape, dtype=np.int64))
        array = np.unpackbits(np.frombuffer(payload, dtype=np.uint8), bitorder="little")[:size]
        result = array.astype(np.bool_, copy=False).reshape(shape)
    else:
        dtype = np.dtype(descriptor["dtype"])
        expected = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
        if expected != len(payload):
            raise ExecutionContractError("canonical payload does not match dtype/shape")
        result = np.frombuffer(payload, dtype=dtype).reshape(shape)
    result.flags.writeable = False
    return result


def hash_logical_buffers(buffers: tuple[LogicalBuffer, ...]) -> str:
    digest = hashlib.sha256()
    for item in buffers:
        digest.update(item.name.encode("utf-8"))
        digest.update(item.array.dtype.str.encode("ascii"))
        digest.update(canonical_json_bytes(list(item.array.shape)))
        digest.update(item.array.tobytes(order="C"))
    return digest.hexdigest()


def hash_reference_array(array: np.ndarray[Any] | None) -> str | None:
    if array is None:
        return None
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(canonical_json_bytes(list(array.shape)))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def route_canonical_artifact(
    artifact: CanonicalArtifact,
    track: BenchmarkTrack,
    *,
    segment_plan: dict[str, Any] | None = None,
) -> RoutedInput:
    if not artifact.buffers:
        raise ExecutionContractError("routing requires canonical payload buffers")
    descriptors = {item["name"]: item for item in artifact.metadata["buffers"]}
    arrays = {
        name: _array_from_payload(descriptors[name], payload)
        for name, payload in artifact.buffers.items()
    }
    timestamp = arrays.get("timestamp")
    validity = arrays.get("validity")
    values = sorted(name for name in arrays if name.startswith("value/"))
    accounting = artifact.metadata["accounting"]
    segment_plan_id: str | None = None

    if track is BenchmarkTrack.TIMESTAMP:
        if timestamp is None:
            raise ExecutionContractError("TIMESTAMP_UNAVAILABLE")
        selected = ("timestamp",)
        canonical_raw_bits = int(accounting["timestamp_raw_bits"])
        m = 1
    elif track is BenchmarkTrack.VALUE:
        if not values:
            raise ExecutionContractError("VALUE_UNAVAILABLE")
        selected = tuple(values) + (("validity",) if validity is not None else ())
        canonical_raw_bits = int(accounting["value_raw_bits"]) + int(
            accounting["validity_raw_bits"]
        )
        logical = artifact.metadata["logical_descriptor"]
        shape = tuple(int(value) for value in logical["value_shape"])
        m = len(values) if len(values) > 1 else (shape[1] if len(shape) > 1 else 1)
    else:
        if timestamp is None or not values:
            raise ExecutionContractError("SYSTEM_REQUIRES_T_AND_V")
        if segment_plan is None:
            segment_plan = {
                "schema_version": "tscb.segment-plan.v2",
                "mode": "ONE_CANONICAL_SEGMENT",
                "n": int(artifact.metadata["logical_descriptor"]["n_rows"]),
                "buffer_order": ["timestamp", *values]
                + (["validity"] if validity is not None else []),
            }
        segment_plan_id = stable_id("segment-plan", segment_plan)
        selected = ("timestamp", *values) + (("validity",) if validity is not None else ())
        canonical_raw_bits = int(accounting["canonical_raw_bits"])
        m = len(values)

    buffers = tuple(
        LogicalBuffer(
            name=name,
            array=arrays[name],
            logical_bits=int(descriptors[name]["logical_bits"]),
        )
        for name in selected
    )
    timestamp_semantics = artifact.metadata["logical_descriptor"].get("timestamp", {})
    value_units = tuple(
        str(item.get("unit", "UNSPECIFIED"))
        for item in artifact.metadata["logical_descriptor"]["value_columns"]
    )
    return RoutedInput(
        dataset_id=str(artifact.metadata["dataset_id"]),
        track=track,
        buffers=buffers,
        timestamp_reference=timestamp,
        validity_reference=validity,
        n=int(artifact.metadata["logical_descriptor"]["n_rows"]),
        m=m,
        canonical_raw_bits=canonical_raw_bits,
        input_sha256=hash_logical_buffers(buffers),
        segment_plan_id=segment_plan_id,
        timestamp_unit=str(timestamp_semantics.get("unit", "NOT_APPLICABLE")),
        timestamp_epoch=str(timestamp_semantics.get("epoch", "NOT_APPLICABLE")),
        value_units=value_units,
        pairing_reference_sha256=hash_reference_array(timestamp),
    )
