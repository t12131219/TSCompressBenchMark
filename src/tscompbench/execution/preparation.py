from __future__ import annotations

from dataclasses import dataclass

from tscompbench.adapters.compatibility import (
    AdapterTelemetry,
    apply_compatibility_plan,
    validate_prepared_input,
)
from tscompbench.codecs import CompatibilityPlan

from .protocol import LogicalBuffer, RoutedInput
from .routing import hash_logical_buffers


@dataclass(frozen=True)
class PreparedExecutionInput:
    original: RoutedInput
    codec_input: RoutedInput
    telemetry: AdapterTelemetry


def prepare_execution_input(
    routed: RoutedInput,
    compatibility: CompatibilityPlan,
    *,
    max_abs_error: str | None = None,
) -> PreparedExecutionInput:
    buffers: list[LogicalBuffer] = []
    read = written = allocated = padding = 0
    copied = False
    channel_index = 0
    for item in routed.buffers:
        if item.name == "validity":
            buffers.append(item)
            continue
        prepared = apply_compatibility_plan(
            item.array,
            compatibility,
            channel_index=min(
                channel_index,
                len(compatibility.input_descriptor.dtype_vector) - 1,
            ),
        )
        validate_prepared_input(
            item.array,
            prepared,
            compatibility,
            max_abs_error=max_abs_error,
        )
        prepared.logical_array.flags.writeable = False
        buffers.append(
            LogicalBuffer(item.name, prepared.logical_array, prepared.logical_array.nbytes * 8)
        )
        read += item.array.nbytes if prepared.telemetry.copied else 0
        written += prepared.logical_array.nbytes if prepared.telemetry.copied else 0
        allocated += int(prepared.storage.nbytes) if prepared.telemetry.copied else 0
        padding += prepared.telemetry.padding_bytes
        copied = copied or prepared.telemetry.copied
        channel_index += 1
    codec_buffers = tuple(buffers)
    codec_input = RoutedInput(
        dataset_id=routed.dataset_id,
        track=routed.track,
        buffers=codec_buffers,
        timestamp_reference=routed.timestamp_reference,
        validity_reference=routed.validity_reference,
        n=routed.n,
        m=routed.m,
        canonical_raw_bits=routed.canonical_raw_bits,
        input_sha256=hash_logical_buffers(codec_buffers),
        segment_plan_id=routed.segment_plan_id,
        timestamp_unit=routed.timestamp_unit,
        timestamp_epoch=routed.timestamp_epoch,
        value_units=routed.value_units,
        pairing_reference_sha256=routed.pairing_reference_sha256,
    )
    return PreparedExecutionInput(
        original=routed,
        codec_input=codec_input,
        telemetry=AdapterTelemetry(read, written, allocated, padding, copied),
    )
