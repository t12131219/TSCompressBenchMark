"""Reviewed stage contract and an independent mathematical/byte-stream validator."""

from __future__ import annotations

import hashlib
import json
import struct
from typing import Any

import numpy as np

from tscompbench.ids import stable_id

from .contracts import PreprocessContractError

STAGE_SPEC = [
    {
        "name": "CHECKED_DELTA_I64_ZIGZAG_U64",
        "stage_class": "LOSSLESS_LAYOUT",
        "stage_slot": "A",
        "parameters": {"overflow": "CHECKED_I64", "seed": "FIRST_I64"},
        "inverse_required": True,
        "accounting_components": ["timestamp_bits"],
        "enable_parameter": "stage_a",
    },
    {
        "name": "INTERLEAVED_LOW_HIGH_U32",
        "stage_class": "LOSSLESS_LAYOUT",
        "stage_slot": "B",
        "parameters": {"limb_bits": 32, "order": "LOW_HIGH"},
        "inverse_required": True,
        "accounting_components": [],
        "enable_parameter": "stage_b",
    },
    {
        "name": "LZBENCH_STREAM_VBYTE",
        "stage_class": "NONE",
        "stage_slot": "C",
        "parameters": {},
        "inverse_required": True,
        "accounting_components": ["timestamp_bits", "metadata_bits"],
        "enable_parameter": "stage_c",
    },
    {
        "name": "TSCB_DESCRIPTOR_AND_NATIVE_FRAMING",
        "stage_class": "NONE",
        "stage_slot": "D",
        "parameters": {},
        "inverse_required": True,
        "accounting_components": ["container_bits", "metadata_bits", "checksum_bits"],
        "enable_parameter": "stage_d",
    },
]
EXECUTOR_ID = stable_id(
    "pipeline-executor",
    {
        "version": "streamvbyte-stages-v1",
        "stages": STAGE_SPEC,
        "disabled_A": "ORIGINAL_INT64_BITS",
        "disabled_B": "BYTE_PRESERVING_LE_U32_VIEW",
        "disabled_C": "COUNT_U32_AND_RAW_LE_WORDS",
        "disabled_D": "NOT_SELF_CONTAINED_REJECTED",
    },
)


def validate_stage_snapshot(
    snapshot: dict[str, Any], *, executor_id: str = EXECUTOR_ID
) -> dict[str, Any]:
    """Validate each forward representation/inverse without using its implementation."""
    original = snapshot["original"]
    a, b, c = snapshot["A"], snapshot["B"], snapshot["C"]
    flags = snapshot["flags"]
    seed = snapshot["seed"]
    if flags["stage_a"]:
        expected = []
        for previous, current in zip(original[:-1], original[1:], strict=True):
            delta = int(current) - int(previous)
            if not -(1 << 63) <= delta < (1 << 63):
                raise PreprocessContractError("stage A accepted checked int64 overflow")
            expected.append((delta << 1) ^ (delta >> 63))
        expected_a = np.array(expected, dtype="<u8")
        if seed != (int(original[0]) if original.size else 0):
            raise PreprocessContractError("stage A seed does not preserve original epoch")
    else:
        expected_a = original.view("<u8")
        if seed != 0:
            raise PreprocessContractError("disabled stage A seed must be zero")
    if a.dtype.str != "<u8" or a.tobytes() != expected_a.tobytes():
        raise PreprocessContractError("stage A mathematical oracle mismatch")
    expected_b = np.array(
        [limb for value in expected_a for limb in (int(value) & 0xFFFFFFFF, int(value) >> 32)],
        dtype="<u4",
    )
    if b.dtype.str != "<u4" or b.tobytes() != expected_b.tobytes():
        raise PreprocessContractError("stage B low/high limb oracle mismatch")
    if len(c) < 4 or struct.unpack_from("<I", c)[0] != b.size:
        raise PreprocessContractError("stage C count mismatch")
    expected_words = []
    if flags["stage_c"]:
        controls = (b.size + 3) // 4
        offset = 4 + controls
        if len(c) < offset:
            raise PreprocessContractError("stage C truncated controls")
        for i in range(b.size):
            width = ((c[4 + i // 4] >> (2 * (i % 4))) & 3) + 1
            if offset + width > len(c):
                raise PreprocessContractError("stage C truncated word")
            expected_words.append(int.from_bytes(c[offset : offset + width], "little"))
            offset += width
        if offset != len(c):
            raise PreprocessContractError("stage C unexpected trailing bytes")
    else:
        if c[4:] != expected_b.tobytes():
            raise PreprocessContractError("disabled stage C changed raw words")
        expected_words = expected_b.tolist()
    if expected_words != expected_b.tolist():
        raise PreprocessContractError("stage C independent scalar decoder mismatch")
    for slot, expected_array in [("A", original), ("B", expected_a), ("C", expected_b)]:
        restored = snapshot["inverse_" + slot]
        if (
            restored.dtype != expected_array.dtype
            or restored.shape != expected_array.shape
            or restored.tobytes() != expected_array.tobytes()
        ):
            raise PreprocessContractError(f"stage {slot} inverse is not bit-exact")
    header = snapshot["descriptor"]
    stream = snapshot["stream"]
    prefix = struct.Struct("<8sI32s")
    magic, length, digest = prefix.unpack_from(stream)
    if magic != b"TSCBSVB1" or length != len(header) or digest != hashlib.sha256(header).digest():
        raise PreprocessContractError("stage D descriptor/framing mismatch")
    info = json.loads(header)
    if (
        info.get("count") != original.size
        or info.get("stage_flags") != flags
        or info.get("pipeline_executor_id") != executor_id
        or info.get("timestamp_unit") != snapshot["timestamp_unit"]
        or info.get("timestamp_epoch") != snapshot["timestamp_epoch"]
        or info.get("buffer")
        != {
            "name": "timestamp",
            "dtype": "<i8",
            "shape": [original.size],
            "logical_bits": original.size * 64,
        }
    ):
        raise PreprocessContractError("stage D lost original descriptor semantics")
    expected_frame = struct.pack("<8sIq", b"TSCBS641", original.size, seed) + c
    if stream[prefix.size + length :] != expected_frame:
        raise PreprocessContractError("stage D seed/count/backend framing mismatch")
    return {
        "status": "PASS",
        "executor_id": executor_id,
        "checked_stages": ["A", "B", "C", "D"],
        "inverse_validation": "BIT_EXACT",
        "oracle": "PYTHON_UNBOUNDED_INT_ARITHMETIC_AND_SCALAR_BYTE_DECODER",
        "original_unit": snapshot["timestamp_unit"],
        "original_epoch": snapshot["timestamp_epoch"],
    }
