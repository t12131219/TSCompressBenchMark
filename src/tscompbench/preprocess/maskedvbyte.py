"""Independent stage validation for the source's fused modular-D1/VByte API."""

from __future__ import annotations

import hashlib
import json
import struct
from typing import Any

import numpy as np

from tscompbench.ids import canonical_json_bytes, stable_id

from .contracts import PreprocessContractError

STAGE_SPEC = [
    {
        "name": "ORIGINAL_MASKEDVBYTE_D1_MODULAR32",
        "stage_class": "LOSSLESS_SEMANTIC",
        "stage_slot": "A",
        "parameters": {
            "width_bits": 32,
            "overflow": "MODULAR_2_32",
            "seed_parameter": "starting_point",
            "execution": "FUSED_ORIGINAL_VBYTE_ENCODE_DELTA",
        },
        "inverse_required": True,
        "accounting_components": ["metadata_bits"],
    },
    {
        "name": "ORIGINAL_MASKEDVBYTE_LEB128_UINT32",
        "stage_class": "NONE",
        "stage_slot": "B",
        "parameters": {},
        "inverse_required": True,
        "accounting_components": ["value_bits"],
    },
    {
        "name": "TSCB_MVB1_AND_CANONICAL_DESCRIPTOR",
        "stage_class": "NONE",
        "stage_slot": "D",
        "parameters": {},
        "inverse_required": True,
        "accounting_components": ["container_bits", "metadata_bits", "checksum_bits"],
    },
]
EXECUTOR_ID = stable_id(
    "pipeline-executor",
    {
        "version": "maskedvbyte-source-modular32-fused-stages-v1",
        "stages": STAGE_SPEC,
        "disable_A": "SELECT_DISTINCT_MASKEDVBYTE_U32_P0_IDENTITY",
        "stage_C": "NO_BACKEND",
        "disable_D": "NOT_SELF_CONTAINED_REJECTED",
        "stage_timing": "A_AND_B_FUSED_SOURCE_API_INDIVIDUAL_TIMES_UNAVAILABLE",
    },
)


def validate_stage_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    original, decoded, stream = snapshot["original"], snapshot["decoded"], snapshot["stream"]
    if (
        original.dtype.str != "<u4"
        or original.ndim != 1
        or original.size > 16777216
        or decoded.dtype != original.dtype
        or decoded.shape != original.shape
    ):
        raise PreprocessContractError("MaskedVByte stage dtype/shape mismatch")
    prefix = struct.Struct("<8sI32s")
    if len(stream) < prefix.size:
        raise PreprocessContractError("MaskedVByte stage D truncated prefix")
    magic, length, digest = prefix.unpack_from(stream)
    header = stream[prefix.size : prefix.size + length]
    if (
        magic != b"TSCBMVP1"
        or length > 4096
        or len(header) != length
        or hashlib.sha256(header).digest() != digest
    ):
        raise PreprocessContractError("MaskedVByte stage D descriptor framing")
    info = json.loads(header)
    if (
        header != canonical_json_bytes(info)
        or info.get("algorithm") != "delta-maskedvbyte-u32"
        or info.get("pipeline_executor_id") != EXECUTOR_ID
        or info.get("count") != original.size
        or info.get("parameters") != snapshot["wire_parameters"]
        or info.get("buffer") != snapshot["buffer"]
        or info.get("value_units") != snapshot["value_units"]
        or info.get("timestamp_unit") != snapshot["timestamp_unit"]
        or info.get("timestamp_epoch") != snapshot["timestamp_epoch"]
        or info.get("codec_stages") != [s["name"] for s in STAGE_SPEC[:2]]
    ):
        raise PreprocessContractError("MaskedVByte stage D lost descriptor semantics")
    frame = memoryview(stream)[prefix.size + length :]
    if len(frame) < 40:
        raise PreprocessContractError("MaskedVByte stage D truncated MVB1")
    magic, count, seed, coding, reserved, size = struct.unpack_from("<8sIIIIQ", frame)
    if (
        magic != b"TSCBMVB1"
        or count != original.size
        or seed != snapshot["wire_parameters"]["starting_point"]
        or coding != 1
        or reserved
        or size != len(frame) - 40
    ):
        raise PreprocessContractError("MaskedVByte stage D native identity/count/seed")
    fnv = 14695981039346656037
    for byte in frame[:-8]:
        fnv = ((fnv ^ byte) * 1099511628211) % 2**64
    if struct.unpack_from("<Q", frame, len(frame) - 8)[0] != fnv:
        raise PreprocessContractError("MaskedVByte stage D native checksum")
    payload = frame[32:-8]
    residuals, at = [], 0
    for _ in range(count):
        value = 0
        for width in range(5):
            if at == len(payload):
                raise PreprocessContractError("MaskedVByte stage B truncated LEB128")
            byte = payload[at]
            at += 1
            if width == 4 and byte > 15:
                raise PreprocessContractError("MaskedVByte stage B uint32 overflow")
            value |= (byte & 127) << (7 * width)
            if byte < 128:
                if width and byte == 0:
                    raise PreprocessContractError("MaskedVByte stage B nonminimal LEB128")
                residuals.append(value)
                break
        else:
            raise PreprocessContractError("MaskedVByte stage B overlong LEB128")
    if at != len(payload):
        raise PreprocessContractError("MaskedVByte stage B trailing payload")
    expected, reconstructed, previous = [], [], seed
    for number in original:
        expected.append((int(number) - previous) % 2**32)
        previous = int(number)
    previous = seed
    for residual in residuals:
        previous = (previous + residual) % 2**32
        reconstructed.append(previous)
    if (
        residuals != expected
        or reconstructed != original.tolist()
        or decoded.tobytes() != original.tobytes()
    ):
        raise PreprocessContractError("MaskedVByte stage A modular delta/inverse mismatch")
    return {
        "status": "PASS",
        "executor_id": EXECUTOR_ID,
        "checked_stages": ["A", "B", "D"],
        "inverse_validation": "BIT_EXACT",
        "oracle": "PYTHON_INTEGER_MODULAR_ARITHMETIC_AND_SCALAR_LEB128",
        "source_execution": "FUSED_ORIGINAL_VBYTE_ENCODE_DELTA",
        "stage_A_wall_ns": None,
        "stage_B_wall_ns": None,
        "stage_timing_reason": "SOURCE_API_FUSES_A_AND_B",
        "stage_A_emitted_residuals_sha256": hashlib.sha256(
            np.array(residuals, dtype="<u4").tobytes()
        ).hexdigest(),
        "stage_B_payload_bytes": len(payload),
        "stage_D_physical_bytes": len(stream),
    }
