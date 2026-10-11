"""CodecAdapter/session facade for standalone P2 pipelines.

The facade is deliberately separate from the codec factory. A caller supplies a
frozen logical schema and recipe as public parameters; no original object is
captured by the decoder session.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.execution.protocol import (
    CodecAdapter,
    CodecSession,
    DecodedOutput,
    EncodedArtifact,
    ExecutionContractError,
    LogicalBuffer,
    RoutedInput,
)
from tscompbench.ids import canonical_json_bytes, stable_id

from .models import LogicalObject, LogicalObjectSchema, PipelineRecipe
from .runtime import decode_object, encode_object, object_output_bound


class PipelineAdapterError(ExecutionContractError):
    pass


def _document(
    parameters: dict[str, Any],
) -> tuple[LogicalObjectSchema, PipelineRecipe, tuple[str, ...]]:
    required = {"logical_schema", "recipe", "value_buffer_names"}
    if not isinstance(parameters, dict) or set(parameters) != required:
        raise PipelineAdapterError(
            "pipeline adapter parameters require logical_schema, recipe and value_buffer_names"
        )
    schema = LogicalObjectSchema.from_document(parameters["logical_schema"])
    recipe = PipelineRecipe.from_document(parameters["recipe"])
    names = parameters["value_buffer_names"]
    if (
        not isinstance(names, list)
        or len(names) != len(schema.to_document()["values"])
        or any(not isinstance(name, str) or not name for name in names)
        or len(set(names)) != len(names)
    ):
        raise PipelineAdapterError("value buffer names must match the ordered logical schema")
    return schema, recipe, tuple(names)


def _logical_input(
    routed: RoutedInput, schema: LogicalObjectSchema, names: tuple[str, ...]
) -> LogicalObject:
    value_buffers = [
        item
        for item in routed.buffers
        if item.name != "timestamp" and not item.name.startswith("validity/")
    ]
    if len(value_buffers) != len(names):
        raise PipelineAdapterError("routed value buffers differ from the frozen logical schema")
    schema_names = tuple(item["name"] for item in schema.to_document()["values"])
    values = {
        name: np.array(item.array, order="C", copy=True)
        for name, item in zip(schema_names, value_buffers, strict=True)
    }
    timestamp = routed.timestamp_reference
    if timestamp is None:
        timestamp_item = next((item for item in routed.buffers if item.name == "timestamp"), None)
        timestamp = None if timestamp_item is None else timestamp_item.array
    validity: dict[str, np.ndarray[Any]] | None = None
    masks = [item for item in routed.buffers if item.name.startswith("validity/")]
    if routed.validity_reference is not None and len(masks) == 0:
        if len(values) != 1:
            raise PipelineAdapterError(
                "multi-value validity requires explicit validity/name buffers"
            )
        masks = [
            LogicalBuffer("validity/0", routed.validity_reference, routed.validity_reference.size)
        ]
    if masks:
        if len(masks) != len(names):
            raise PipelineAdapterError("validity buffers must cover all logical values")
        validity = {
            name: np.asarray(mask.array, dtype=np.bool_).copy()
            for name, mask in zip(schema_names, masks, strict=True)
        }
    return LogicalObject(schema, values, timestamp, validity)


def _routed_output(restored: Any, names: tuple[str, ...]) -> DecodedOutput:
    schema_names = tuple(restored.values)
    buffers = [
        LogicalBuffer(name, restored.values[schema_name], restored.values[schema_name].nbytes * 8)
        for name, schema_name in zip(names, schema_names, strict=True)
    ]
    if restored.timestamp is not None:
        buffers.append(
            LogicalBuffer("timestamp", restored.timestamp, restored.timestamp.nbytes * 8)
        )
    if restored.validity is not None:
        buffers.extend(
            LogicalBuffer(
                f"validity/{index}",
                restored.validity[schema_name],
                restored.validity[schema_name].size,
            )
            for index, schema_name in enumerate(schema_names)
        )
    return DecodedOutput(tuple(buffers))


class PipelineCodecSession(CodecSession):
    def __init__(self, project_root: Path, parameters: dict[str, Any]) -> None:
        self.project_root = project_root
        self.parameters = json.loads(canonical_json_bytes(parameters))
        self.schema, self.recipe, self.names = _document(self.parameters)
        self._closed = False
        self._finalized = False
        self._artifact: EncodedArtifact | None = None

    def _ensure_open(self) -> None:
        if self._closed:
            raise PipelineAdapterError("pipeline session is closed")

    def output_bound(self, routed: RoutedInput) -> int:
        self._ensure_open()
        return object_output_bound(
            self.project_root, _logical_input(routed, self.schema, self.names), self.recipe
        )

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        self._ensure_open()
        if self._artifact is not None or self._finalized:
            raise PipelineAdapterError("pipeline update requires a fresh session")
        original = _logical_input(routed, self.schema, self.names)
        artifact = encode_object(self.project_root, original, self.recipe)
        if len(artifact.stream) > len(destination):
            raise PipelineAdapterError("pipeline output exceeds declared adapter capacity")
        destination[: len(artifact.stream)] = artifact.stream
        stream_hash = hashlib.sha256(artifact.stream).hexdigest()
        ledger = AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=artifact.ledger.canonical_raw_bits,
            final_physical_bytes=len(artifact.stream),
            container_bits=artifact.ledger.artifact_physical_bits,
            accounting_method="EXACT_P2_PIPELINE_FRAME_AND_CHILD_STREAM",
        )
        self._artifact = EncodedArtifact(
            artifact.stream,
            len(artifact.stream),
            0,
            len(destination),
            stream_hash,
            ledger,
            codec_telemetry={
                "pipeline_ledger": artifact.ledger.to_document(),
                "recipe_id": self.recipe.recipe_id,
            },
        )
        return len(artifact.stream)

    def finalize(self, destination: memoryview) -> int:
        self._ensure_open()
        if self._artifact is None or self._finalized:
            raise PipelineAdapterError("pipeline finalize requires exactly one update")
        self._finalized = True
        return 0

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        self._ensure_open()
        if self._artifact is None or not self._finalized or self._artifact.stream != stream:
            raise PipelineAdapterError(
                "pipeline accounting requires the finalized session artifact"
            )
        return self._artifact.ledger

    def decompress(self, stream: bytes) -> DecodedOutput:
        self._ensure_open()
        restored = decode_object(self.project_root, stream)
        return _routed_output(restored, self.names)

    def close(self) -> None:
        self._closed = True
        self._artifact = None


class PipelineCodecAdapter(CodecAdapter):
    deterministic = True

    def __init__(
        self,
        project_root: Path,
        schema: LogicalObjectSchema,
        recipe: PipelineRecipe,
        value_buffer_names: tuple[str, ...],
    ) -> None:
        if len(value_buffer_names) != len(schema.to_document()["values"]):
            raise PipelineAdapterError("value_buffer_names must match logical schema")
        self.project_root = project_root
        self.parameters = {
            "logical_schema": schema.to_document(),
            "recipe": recipe.to_document(),
            "value_buffer_names": list(value_buffer_names),
        }
        self.adapter_id = stable_id("pipeline-adapter", self.parameters, version="v3")

    def create_session(self, parameters: dict[str, Any] | None = None) -> PipelineCodecSession:
        selected = self.parameters if parameters is None else parameters
        return PipelineCodecSession(self.project_root, selected)
