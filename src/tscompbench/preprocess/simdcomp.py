"""Independent scalar evidence for SIMDComp's fused D1/FOR and bitpacking stages."""

from __future__ import annotations

import hashlib
import json
import struct
from typing import Any

import numpy as np

from tscompbench.ids import canonical_json_bytes, stable_id

from .contracts import PreprocessContractError


def stages(coding: str) -> list[dict]:
    return [
        {
            "name": "ORIGINAL_SIMDCOMP_D1_MODULAR32"
            if coding == "DELTA"
            else "ORIGINAL_SIMDCOMP_FIXED_FOR_MODULAR32",
            "stage_class": "LOSSLESS_SEMANTIC",
            "stage_slot": "A",
            "parameters": {
                "width_bits": 32,
                "overflow": "MODULAR_2_32",
                "seed_parameter": "starting_point",
                "execution": "FUSED_ORIGINAL_SOURCE_API",
                "width32": "ORIGINAL_ABSOLUTE_VALUES",
            },
            "inverse_required": True,
            "accounting_components": ["metadata_bits"],
        },
        {
            "name": "ORIGINAL_SIMDCOMP_UINT32_BITPACK",
            "stage_class": "NONE",
            "stage_slot": "B",
            "parameters": {},
            "inverse_required": True,
            "accounting_components": ["value_bits", "padding_bits"],
        },
        {
            "name": "TSCB_SBP1_AND_CANONICAL_DESCRIPTOR",
            "stage_class": "NONE",
            "stage_slot": "D",
            "parameters": {},
            "inverse_required": True,
            "accounting_components": ["container_bits", "metadata_bits", "checksum_bits"],
        },
    ]


STAGE_SPECS = {
    key: stages(coding)
    for key, coding in (("delta-simdcomp-u32", "DELTA"), ("for-simdcomp-u32", "FOR"))
}
EXECUTOR_IDS = {
    key: stable_id(
        "pipeline-executor",
        {
            "version": "simdcomp-source-modular32-fused-stages-v1",
            "stages": spec,
            "disable_A": "SELECT_DISTINCT_SIMDCOMP_U32_P0_IDENTITY",
            "stage_C": "NO_BACKEND",
            "disable_D": "NOT_SELF_CONTAINED_REJECTED",
            "stage_timing": "A_AND_B_FUSED_SOURCE_API_INDIVIDUAL_TIMES_UNAVAILABLE",
        },
    )
    for key, spec in STAGE_SPECS.items()
}


def validate_stage_snapshot(snapshot: dict[str, Any]) -> dict:
    original, decoded, stream = snapshot["original"], snapshot["decoded"], snapshot["stream"]
    key, params = snapshot["algorithm"], snapshot["wire_parameters"]
    if (
        key not in EXECUTOR_IDS
        or original.dtype.str != "<u4"
        or original.ndim != 1
        or original.size > 16777216
        or decoded.dtype != original.dtype
        or decoded.shape != original.shape
        or decoded.tobytes() != original.tobytes()
    ):
        raise PreprocessContractError("SIMDComp stage A dtype/shape/inverse mismatch")
    prefix = struct.Struct("<8sI32s")
    if len(stream) < prefix.size:
        raise PreprocessContractError("SIMDComp stage D truncated prefix")
    magic, length, digest = prefix.unpack_from(stream)
    header = stream[prefix.size : prefix.size + length]
    if (
        magic != b"TSCBSCP1"
        or length > 4096
        or len(header) != length
        or hashlib.sha256(header).digest() != digest
    ):
        raise PreprocessContractError("SIMDComp stage D descriptor framing")
    info = json.loads(header)
    spec = STAGE_SPECS[key]
    if (
        header != canonical_json_bytes(info)
        or info.get("schema_version") != "tscb.simdcomp-container.v1"
        or info.get("algorithm") != key
        or info.get("track") != "VALUE"
        or info.get("count") != original.size
        or info.get("parameters") != params
        or info.get("buffer") != snapshot["buffer"]
        or info.get("value_units") != snapshot["value_units"]
        or info.get("timestamp_unit") != snapshot["timestamp_unit"]
        or info.get("timestamp_epoch") != snapshot["timestamp_epoch"]
        or info.get("codec_stages") != [s["name"] for s in spec[:2]]
    ):
        raise PreprocessContractError("SIMDComp stage D lost descriptor semantics")
    coding = "DELTA" if key == "delta-simdcomp-u32" else "FOR"
    if (
        params.get("coding") != coding
        or params.get("isa") != "SSE4_1"
        or params.get("api")
        not in (("MASKED", "WITHOUTMASK") if coding == "DELTA" else ("LENGTH", "FULL"))
        or type(params.get("starting_point")) is not int
        or not 0 <= params["starting_point"] < 2**32
    ):
        raise PreprocessContractError("SIMDComp stage A configuration mismatch")
    mode = 1 if coding == "DELTA" else 3 if params["api"] == "FULL" else 2
    seed, previous, body, residuals = (
        params["starting_point"],
        params["starting_point"],
        bytearray(),
        [],
    )
    value_bits = payload_bytes = 0
    for start in range(0, original.size, 128):
        logical = [int(x) for x in original[start : start + 128]]
        padded = mode in (1, 3)
        physical = logical + (
            [logical[-1] if mode == 1 else seed] * (128 - len(logical)) if padded else []
        )
        codes = []
        for x in physical:
            codes.append((x - (previous if mode == 1 else seed)) % 2**32)
            previous = x
        residuals.extend(codes[: len(logical)])
        width = max(codes, default=0).bit_length()
        wire = bytearray(
            ((len(physical) + 3) // 4 * width + 31) // 32 * 16 if width != 32 else len(physical) * 4
        )
        if width == 32:
            wire[:] = np.array(physical, dtype="<u4").tobytes()
        else:
            for i, code in enumerate(codes):
                for bit in range(width):
                    if code & (1 << bit):
                        position = i // 4 * width + bit
                        at = (position // 32 * 4 + i % 4) * 4 + position % 32 // 8
                        wire[at] |= 1 << (position % 8)
        body += struct.pack("<HBBI", len(logical), width, int(padded), len(wire)) + wire
        value_bits += len(logical) * width
        payload_bytes += len(wire)
        previous = logical[-1]
    blocks = (original.size + 127) // 128
    expected = (
        struct.pack("<8s6IQ", b"TSCBSBP1", original.size, seed, mode, 128, blocks, 0, len(body))
        + body
    )
    fnv = 14695981039346656037
    for byte in expected:
        fnv = ((fnv ^ byte) * 1099511628211) % 2**64
    expected += struct.pack("<Q", fnv)
    if stream[prefix.size + length :] != expected:
        raise PreprocessContractError("SIMDComp stage A/B scalar wire mismatch")
    previous, restored = seed, []
    for residual in residuals:
        previous = (residual + (previous if mode == 1 else seed)) % 2**32
        restored.append(previous)
    if restored != original.tolist():
        raise PreprocessContractError("SIMDComp stage A scalar inverse mismatch")
    return {
        "status": "PASS",
        "executor_id": EXECUTOR_IDS[key],
        "checked_stages": ["A", "B", "D"],
        "inverse_validation": "BIT_EXACT",
        "oracle": "PYTHON_MODULAR_UINT32_AND_FOUR_LANE_SCALAR_WIRE",
        "source_execution": "FUSED_ORIGINAL_D1_OR_FIXED_FOR_AND_BITPACK",
        "stage_A_wall_ns": None,
        "stage_B_wall_ns": None,
        "stage_timing_reason": "SOURCE_API_FUSES_A_AND_B",
        "stage_A_emitted_residuals_sha256": hashlib.sha256(
            np.array(residuals, dtype="<u4").tobytes()
        ).hexdigest(),
        "stage_B_payload_bytes": payload_bytes,
        "stage_B_logical_value_bits": value_bits,
        "stage_B_physical_padding_bits": payload_bytes * 8 - value_bits,
        "stage_D_physical_bytes": len(stream),
    }
