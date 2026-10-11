from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.codecs import CodecManifest, CompatibilityPlan
from tscompbench.contracts import LossMode
from tscompbench.ids import canonical_json_bytes

from .protocol import (
    DecodedOutput,
    EncodedArtifact,
    ExecutionContractError,
    LogicalBuffer,
    RoutedInput,
)

_SCHEMA = "tscb.decode-context.v1"
_NOOP_INVERSES = {
    "CONTIGUOUS_COPY",
    "GATHER_SCATTER",
    "ALIGNMENT_COPY",
    "SAFE_OVERREAD_PADDING",
}
_INVERSES = _NOOP_INVERSES | {
    "TRANSPOSE_COPY",
    "ENDIANNESS_CONVERSION",
    "EXACT_WIDEN",
    "LOSSY_CAST",
}


@dataclass(frozen=True)
class DecodeContext:
    """Serialized recovery instructions; contains no source values or encoder state."""

    serialized: bytes

    def __post_init__(self) -> None:
        doc = self.to_document()
        required = {
            "schema_version",
            "adapter_id",
            "parameters",
            "loss_mode",
            "track",
            "n",
            "m",
            "canonical_raw_bits",
            "timestamp_unit",
            "timestamp_epoch",
            "value_units",
            "buffers",
        }
        if set(doc) != required or doc["schema_version"] != _SCHEMA:
            raise ExecutionContractError("unsupported decode context schema")
        LossMode(doc["loss_mode"])
        if not isinstance(doc["adapter_id"], str) or not isinstance(doc["parameters"], dict):
            raise ExecutionContractError("invalid decoder identity/configuration")
        if any(
            type(doc[key]) is not int or doc[key] < 0 for key in ("n", "m", "canonical_raw_bits")
        ):
            raise ExecutionContractError("invalid recovery dimensions")
        names = []
        for buffer in doc["buffers"]:
            if set(buffer) != {"name", "dtype", "shape", "logical_bits", "inverse"}:
                raise ExecutionContractError("invalid recovery buffer schema")
            names.append(buffer["name"])
            dtype = np.dtype(buffer["dtype"])
            if dtype.kind not in "biuf" or dtype.hasobject or dtype.itemsize not in {1, 2, 4, 8}:
                raise ExecutionContractError("unsupported recovery dtype")
            if not isinstance(buffer["shape"], list) or any(
                type(value) is not int or value < 0 for value in buffer["shape"]
            ):
                raise ExecutionContractError("invalid recovery shape")
            if type(buffer["logical_bits"]) is not int or buffer["logical_bits"] < 0:
                raise ExecutionContractError("invalid recovery logical bits")
            for step in buffer["inverse"]:
                if set(step) != {"kind", "dtype"} or step["kind"] not in _INVERSES:
                    raise ExecutionContractError("unimplemented inverse operation")
                step_dtype = np.dtype(step["dtype"])
                if step_dtype.kind not in "biuf" or step_dtype.itemsize not in {1, 2, 4, 8}:
                    raise ExecutionContractError("unsupported inverse dtype")
        if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(
            names
        ):
            raise ExecutionContractError("invalid recovery buffer names")
        if canonical_json_bytes(doc) != self.serialized:
            raise ExecutionContractError("decode context must use canonical JSON")

    @classmethod
    def from_routed(
        cls,
        routed: RoutedInput,
        compatibility: CompatibilityPlan,
        *,
        adapter_id: str = "UNSPECIFIED",
        parameters: dict[str, Any] | None = None,
    ) -> DecodeContext:
        buffers = []
        channel_index = 0
        for item in routed.buffers:
            dtype = item.array.dtype
            forward = []
            if item.name != "validity":
                index = min(channel_index, len(compatibility.input_descriptor.dtype_vector) - 1)
                for operation in compatibility.operations:
                    kind = operation.kind.value
                    if kind not in _INVERSES:
                        raise ExecutionContractError(f"unimplemented recovery operation: {kind}")
                    forward.append({"kind": kind, "dtype": dtype.str})
                    if kind in {"EXACT_WIDEN", "LOSSY_CAST"}:
                        dtype = np.dtype(operation.after_descriptor["dtype_vector"][index])
                    elif kind == "ENDIANNESS_CONVERSION":
                        dtype = dtype.newbyteorder()
                channel_index += 1
            buffers.append(
                {
                    "name": item.name,
                    "dtype": item.array.dtype.str,
                    "shape": list(item.array.shape),
                    "logical_bits": item.logical_bits,
                    "inverse": list(reversed(forward)),
                }
            )
        return cls(
            canonical_json_bytes(
                {
                    "schema_version": _SCHEMA,
                    "adapter_id": adapter_id,
                    "parameters": {} if parameters is None else parameters,
                    "loss_mode": compatibility.effective_loss_mode,
                    "track": routed.track,
                    "n": routed.n,
                    "m": routed.m,
                    "canonical_raw_bits": routed.canonical_raw_bits,
                    "timestamp_unit": routed.timestamp_unit,
                    "timestamp_epoch": routed.timestamp_epoch,
                    "value_units": routed.value_units,
                    "buffers": buffers,
                }
            )
        )

    def to_document(self) -> dict[str, Any]:
        try:
            value = json.loads(self.serialized)
        except (ValueError, UnicodeError) as error:
            raise ExecutionContractError("invalid decode context JSON") from error
        if not isinstance(value, dict):
            raise ExecutionContractError("decode context must be an object")
        return value

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.serialized).hexdigest()


def restore_decoded_output(decoded: DecodedOutput, context: DecodeContext) -> DecodedOutput:
    """Restore and fully materialize owned buffers using only declared metadata."""
    doc = context.to_document()
    observed = decoded.by_name()
    if tuple(observed) != tuple(item["name"] for item in doc["buffers"]):
        raise ExecutionContractError("recovery buffer order/names differ from context")
    output = []
    for schema in doc["buffers"]:
        current = observed[schema["name"]].array
        for step in schema["inverse"]:
            kind = step["kind"]
            if kind == "TRANSPOSE_COPY" and current.ndim >= 2:
                current = current.T
            elif kind == "ENDIANNESS_CONVERSION":
                current = current.byteswap().view(current.dtype.newbyteorder())
            elif kind in {"EXACT_WIDEN", "LOSSY_CAST"} and doc["loss_mode"] == "LOSSLESS":
                current = current.astype(np.dtype(step["dtype"]), copy=False)
        if list(current.shape) != schema["shape"]:
            raise ExecutionContractError("recovered shape differs from decode context")
        # Preserve fractional lossy reconstructions for original-domain validation.
        if doc["loss_mode"] == "LOSSLESS" and current.dtype.str != schema["dtype"]:
            raise ExecutionContractError("recovered dtype differs from decode context")
        owned = np.array(current, order="C", copy=True)
        owned.flags.writeable = False
        output.append(LogicalBuffer(schema["name"], owned, schema["logical_bits"]))
    return DecodedOutput(tuple(output))


def bind_decode_context(artifact: EncodedArtifact, context: DecodeContext) -> EncodedArtifact:
    if artifact.recovery_context is not None:
        raise ExecutionContractError("decode context was already charged")
    bits = len(context.serialized) * 8
    ledger = replace(
        artifact.ledger,
        external_side_information_bits=artifact.ledger.external_side_information_bits + bits,
        final_bits=artifact.ledger.final_bits + bits,
        accounting_method=artifact.ledger.accounting_method + "+PERSISTED_DECODE_CONTEXT_V1",
    )
    return replace(artifact, ledger=ledger, recovery_context=context.serialized)


def decode_in_fresh_worker(
    project_root: Path,
    manifest_document: dict[str, Any],
    codec_key: str,
    context_bytes: bytes,
    stream: bytes,
    stream_sha256: str,
    source_reject_fallback: bool = False,
) -> tuple[DecodedOutput, dict[str, Any]]:
    """Spawn target: reconstruct the decoder; never receive an adapter or original input."""
    from tscompbench.adapters.factory import create_adapter

    if hashlib.sha256(stream).hexdigest() != stream_sha256:
        raise ExecutionContractError("recovery artifact checksum mismatch")
    context = DecodeContext(context_bytes)
    doc = context.to_document()
    manifest = CodecManifest(codec_key, manifest_document, "RECOVERY_DEPENDENCY")
    adapter = create_adapter(
        project_root,
        manifest,
        source_reject_fallback=source_reject_fallback,
    )
    if adapter.adapter_id != doc["adapter_id"]:
        raise ExecutionContractError("recovery decoder identity mismatch")
    session = adapter.create_session(doc["parameters"])
    try:
        restored = restore_decoded_output(session.decompress(stream), context)
    finally:
        session.close()
    return restored, {
        "schema_version": "tscb.independent-recovery-evidence.v1",
        "worker_pid": os.getpid(),
        "start_method": "spawn",
        "original_input_available": False,
        "encoder_session_available": False,
        "decode_context_sha256": context.sha256,
        "stream_sha256": stream_sha256,
        "required_external_bits": len(context_bytes) * 8,
        "output_materialization": "OWNED_CANONICAL_BUFFERS",
        "output_owned_in_worker": all(item.array.flags.owndata for item in restored.buffers),
        "dependency_scope": "DECLARED_DECODER_AND_CONFIGURATION",
    }
