from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np

from tscompbench.codecs import CodecContractError, CompatibilityPlan
from tscompbench.contracts import AdapterOperationKind, CapabilityStatus


@dataclass(frozen=True)
class AdapterTelemetry:
    bytes_read: int
    bytes_written: int
    allocation_bytes: int
    padding_bytes: int
    copied: bool


@dataclass(frozen=True)
class PreparedInput:
    logical_array: np.ndarray[Any]
    storage: np.ndarray[Any]
    telemetry: AdapterTelemetry
    original_sha256: str
    channel_index: int


def _sha256(array: np.ndarray[Any]) -> str:
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(str(tuple(array.shape)).encode("ascii"))
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _aligned_copy(
    array: np.ndarray[Any], alignment: int
) -> tuple[np.ndarray[Any], np.ndarray[Any]]:
    storage = np.empty(array.nbytes + alignment - 1, dtype=np.uint8)
    offset = (-int(storage.ctypes.data)) % alignment
    aligned_bytes = storage[offset : offset + array.nbytes]
    aligned = aligned_bytes.view(array.dtype).reshape(array.shape)
    aligned[...] = array
    if int(aligned.ctypes.data) % alignment:
        raise CodecContractError("failed to create aligned adapter buffer")
    return aligned, storage


def apply_compatibility_plan(
    array: np.ndarray[Any], plan: CompatibilityPlan, *, channel_index: int = 0
) -> PreparedInput:
    """Apply only the operations already authorized by a CompatibilityPlan.

    This function does not negotiate, sort, fill, interpolate, or select channels.
    The independent validator below decides whether the resulting view is valid.
    """

    if plan.status is CapabilityStatus.UNSUPPORTED:
        raise CodecContractError("an UNSUPPORTED plan cannot be applied")
    original_hash = _sha256(array)
    current = array
    storage: np.ndarray[Any] = current
    copied = False
    for operation in plan.operations:
        if operation.kind in {
            AdapterOperationKind.CONTIGUOUS_COPY,
            AdapterOperationKind.GATHER_SCATTER,
        }:
            current = np.ascontiguousarray(current)
            storage = current
            copied = copied or current is not array
        elif operation.kind is AdapterOperationKind.TRANSPOSE_COPY:
            if current.ndim < 2:
                current = np.ascontiguousarray(current)
            else:
                current = np.ascontiguousarray(current.T)
            storage = current
            copied = True
        elif operation.kind in {
            AdapterOperationKind.EXACT_WIDEN,
            AdapterOperationKind.LOSSY_CAST,
        }:
            targets = operation.after_descriptor["dtype_vector"]
            if channel_index >= len(targets):
                raise CodecContractError("channel_index exceeds adapter dtype vector")
            current = current.astype(np.dtype(targets[channel_index]), copy=True)
            storage = current
            copied = True
        elif operation.kind is AdapterOperationKind.ENDIANNESS_CONVERSION:
            current = current.byteswap().view(current.dtype.newbyteorder())
            storage = current
            copied = True
        elif operation.kind is AdapterOperationKind.ALIGNMENT_COPY:
            alignment = int(operation.after_descriptor["alignment_bytes"])
            current, storage = _aligned_copy(current, alignment)
            copied = True
        elif operation.kind is AdapterOperationKind.SAFE_OVERREAD_PADDING:
            padding = operation.padding_bytes
            byte_view = np.ascontiguousarray(current).view(np.uint8).reshape(-1)
            padded = np.zeros(byte_view.size + padding, dtype=np.uint8)
            padded[: byte_view.size] = byte_view
            current = padded[: byte_view.size].view(current.dtype).reshape(current.shape)
            storage = padded
            copied = True
        elif operation.kind in {
            AdapterOperationKind.NULL_MATERIALIZATION,
            AdapterOperationKind.DEVICE_STAGING,
        }:
            raise CodecContractError(
                f"operation requires a backend-specific adapter: {operation.kind}"
            )
        else:
            raise CodecContractError(f"unsupported compatibility operation: {operation.kind}")
    if _sha256(array) != original_hash:
        raise CodecContractError("compatibility adapter modified canonical input")
    return PreparedInput(
        logical_array=current,
        storage=storage,
        telemetry=AdapterTelemetry(
            bytes_read=sum(item.bytes_read for item in plan.operations),
            bytes_written=sum(item.bytes_written for item in plan.operations),
            allocation_bytes=sum(item.allocation_bytes for item in plan.operations),
            padding_bytes=sum(item.padding_bytes for item in plan.operations),
            copied=copied,
        ),
        original_sha256=original_hash,
        channel_index=channel_index,
    )


def validate_prepared_input(
    original: np.ndarray[Any],
    prepared: PreparedInput,
    plan: CompatibilityPlan,
    *,
    max_abs_error: str | None = None,
) -> None:
    """Independently validate logical content after adapter application."""

    if _sha256(original) != prepared.original_sha256:
        raise CodecContractError("canonical input changed after adapter execution")
    reconstructed = prepared.logical_array
    transpose_count = sum(
        item.kind is AdapterOperationKind.TRANSPOSE_COPY for item in plan.operations
    )
    if transpose_count % 2 and reconstructed.ndim >= 2:
        reconstructed = reconstructed.T
    if reconstructed.shape != original.shape:
        raise CodecContractError("adapter changed logical shape")
    if plan.status is CapabilityStatus.ADAPTER_LOSSY:
        if max_abs_error is None:
            raise CodecContractError("lossy adapter validation requires a declared error bound")
        error = np.abs(reconstructed.astype(np.longdouble) - original.astype(np.longdouble))
        observed = np.max(error, initial=np.longdouble(0))
        if observed > np.longdouble(max_abs_error):
            raise CodecContractError(
                f"lossy adapter bound violated: observed={observed}, bound={max_abs_error}"
            )
        return
    restored = reconstructed.astype(original.dtype, copy=False)
    if restored.tobytes(order="C") != original.tobytes(order="C"):
        raise CodecContractError("lossless adapter failed bit-exact post-adapter validation")
