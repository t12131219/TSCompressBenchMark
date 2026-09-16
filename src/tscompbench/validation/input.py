from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from tscompbench.execution.protocol import RoutedInput
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.planning import BenchmarkTask


class InputValidationError(ValueError):
    """Actual routed buffers disagree with the frozen Layer 2 task contract."""


@dataclass(frozen=True)
class InputValidationReport:
    input_sha256: str
    buffer_count: int
    buffer_names: tuple[str, ...]
    observed_dtypes: tuple[str, ...]
    observed_shapes: tuple[tuple[int, ...], ...]
    timestamp_unit: str | None
    timestamp_epoch: str | None
    value_units: tuple[str | None, ...]
    special_values: dict[str, int]

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.input-validation.v2",
            "input_sha256": self.input_sha256,
            "buffer_count": self.buffer_count,
            "buffer_names": self.buffer_names,
            "observed_dtypes": self.observed_dtypes,
            "observed_shapes": self.observed_shapes,
            "timestamp_unit": self.timestamp_unit,
            "timestamp_epoch": self.timestamp_epoch,
            "value_units": self.value_units,
            "special_values": self.special_values,
        }


def validate_routed_input(routed: RoutedInput, task: BenchmarkTask) -> InputValidationReport:
    if routed.dataset_id != task.dataset_id:
        raise InputValidationError("DatasetID changed between planning and execution")
    if routed.track is not task.track:
        raise InputValidationError("Track changed between planning and execution")
    expected = task.expected_workload
    if routed.n != int(expected["n"]) or routed.m != int(expected["m"]):
        raise InputValidationError("N/M changed between planning and execution")
    if routed.canonical_raw_bits != int(expected["canonical_raw_bits"]):
        raise InputValidationError("CanonicalRawBits changed between planning and execution")
    descriptor = task.compatibility.input_descriptor
    if (
        routed.timestamp_unit != descriptor.timestamp_unit
        or routed.timestamp_epoch != descriptor.timestamp_epoch
    ):
        raise InputValidationError("timestamp unit/epoch changed between planning and execution")
    if routed.value_units != descriptor.value_units:
        raise InputValidationError("value unit semantics changed between planning and execution")
    actual_hash = hash_logical_buffers(routed.buffers)
    if actual_hash != routed.input_sha256:
        raise InputValidationError("routed input hash does not match its frozen hash")

    special = {"nan": 0, "positive_inf": 0, "negative_inf": 0, "negative_zero": 0}
    for item in routed.buffers:
        array = item.array
        if array.flags.writeable:
            raise InputValidationError(f"canonical routed buffer is mutable: {item.name}")
        if array.dtype.hasobject:
            raise InputValidationError(f"object dtype is forbidden: {item.name}")
        if array.dtype.byteorder == ">" or (array.dtype.byteorder == "=" and not np.little_endian):
            raise InputValidationError(f"non-little-endian canonical input: {item.name}")
        if array.ndim == 0 or (array.shape and int(array.shape[0]) != routed.n):
            raise InputValidationError(f"buffer row count disagrees with N: {item.name}")
        if np.issubdtype(array.dtype, np.floating):
            special["nan"] += int(np.isnan(array).sum())
            special["positive_inf"] += int(np.isposinf(array).sum())
            special["negative_inf"] += int(np.isneginf(array).sum())
            special["negative_zero"] += int(np.count_nonzero((array == 0) & np.signbit(array)))
    return InputValidationReport(
        input_sha256=actual_hash,
        buffer_count=len(routed.buffers),
        buffer_names=tuple(item.name for item in routed.buffers),
        observed_dtypes=tuple(item.array.dtype.str for item in routed.buffers),
        observed_shapes=tuple(
            tuple(int(value) for value in item.array.shape) for item in routed.buffers
        ),
        timestamp_unit=routed.timestamp_unit,
        timestamp_epoch=routed.timestamp_epoch,
        value_units=routed.value_units,
        special_values=special,
    )
