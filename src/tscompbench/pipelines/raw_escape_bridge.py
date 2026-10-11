"""Explicit source-domain reject to deterministic RAW block fallback (recipe v2)."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.execution.protocol import SourceDomainError
from tscompbench.ids import canonical_json_bytes, stable_id

from .models import (
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineError,
    PipelineLedger,
    PipelineRecipe,
    RestoredObject,
)
from .runtime import _parse, decode_object, encode_object

_FRAME = struct.Struct("<8sIQ")
_MAGIC = b"TSCBRSV1"
_SCHEMA = "tscb.source-reject-raw-recipe.v2"
_ARTIFACT = "tscb.source-reject-raw-artifact.v2"
_MAX_HEADER = 16 * 1024 * 1024
_MAX_PAYLOAD = 512 * 1024 * 1024


@dataclass(frozen=True, init=False)
class SourceRejectRawRecipe:
    serialized: bytes

    def __init__(self, child: ChildSpec, block_size: int = 1024) -> None:
        if not isinstance(child, ChildSpec) or not child.codec_key:
            raise PipelineError("raw escape requires an existing child codec")
        if type(block_size) is not int or not 1 <= block_size <= 16_777_216:
            raise PipelineError("raw escape block size is outside the bounded v2 contract")
        object.__setattr__(
            self,
            "serialized",
            canonical_json_bytes(
                {
                    "schema_version": _SCHEMA,
                    "child": child.to_document(),
                    "block_size": block_size,
                    "tail_policy": "SOURCE_REJECT_TO_RAW_BLOCK",
                    "allowed_rejection": "SOURCE_DOMAIN_ONLY",
                    "stages": ["SOURCE_ATTEMPT", "CODEC_OR_RAW_BLOCK", "ASSEMBLY"],
                }
            ),
        )

    def to_document(self) -> dict[str, Any]:
        return json.loads(self.serialized)

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> SourceRejectRawRecipe:
        required = {
            "schema_version",
            "child",
            "block_size",
            "tail_policy",
            "allowed_rejection",
            "stages",
        }
        if (
            not isinstance(document, dict)
            or set(document) != required
            or document["schema_version"] != _SCHEMA
        ):
            raise PipelineError("invalid source-reject raw recipe")
        recipe = cls(ChildSpec.from_document(document["child"]), document["block_size"])
        if recipe.to_document() != document:
            raise PipelineError("source-reject raw recipe is not canonical/frozen")
        return recipe

    @property
    def recipe_id(self) -> str:
        return stable_id("source-reject-raw-recipe", self.to_document(), version="v3")


def _schema_for_block(
    schema: LogicalObjectSchema, owner: str, count: int
) -> LogicalObjectSchema:
    document = schema.to_document()
    items = [item for item in document["values"] if item["name"] == owner]
    if len(items) != 1:
        raise PipelineError("source-reject raw block owner is not in the logical schema")
    item = items[0].copy()
    item["shape"] = [count]
    item["axes"] = ["time"]
    item["time_axis"] = 0
    document["values"] = [item]
    return LogicalObjectSchema.from_document(document)


def _validate(original: LogicalObject) -> tuple[tuple[dict[str, Any], ...], int]:
    document = original.schema.to_document()
    if (
        not document["values"]
        or original.timestamp is not None
        or original.validity is not None
    ):
        raise PipelineError(
            "source-reject raw v2 currently requires value buffers without T or validity"
        )
    items = tuple(document["values"])
    if any(
        item["time_axis"] != 0
        or item["shape"] != [original.schema.n]
        or item["dtype"] not in {"<f4", "<f8"}
        for item in items
    ):
        raise PipelineError(
            "source-reject raw v2 requires one-dimensional synchronous f32/f64 values"
        )
    return items, original.schema.n


@dataclass(frozen=True)
class SourceRejectRawArtifact:
    stream: bytes
    ledger: PipelineLedger
    recipe_id: str
    logical_content_id: str
    execution_evidence: dict[str, Any]

    def __post_init__(self) -> None:
        if self.ledger.artifact_physical_bits != len(self.stream) * 8:
            raise PipelineError("raw escape ledger differs from artifact bytes")


def encode_source_reject_raw(
    project_root: Path, original: LogicalObject, recipe: SourceRejectRawRecipe
) -> SourceRejectRawArtifact:
    items, n = _validate(original)
    before = original.underlying_bytes_sha256
    chunks: list[bytes] = []
    blocks: list[dict[str, Any]] = []
    evidence_blocks: list[dict[str, Any]] = []
    offset = 0
    recipe_document = recipe.to_document()
    child = ChildSpec.from_document(recipe_document["child"])
    block_size = recipe_document["block_size"]
    for column, item in enumerate(items):
        name = item["name"]
        values = original.values[name]
        for start in range(0, n, block_size):
            block = np.ascontiguousarray(values[start : start + block_size])
            block_schema = _schema_for_block(original.schema, name, block.size)
            block_object = LogicalObject(block_schema, {name: block})
            input_hash = hashlib.sha256(block.tobytes()).hexdigest()
            attempt_started = time.perf_counter_ns()
            chosen = "CODEC"
            rejection: dict[str, str] | None = None
            try:
                child_recipe = PipelineRecipe(
                    {name: child}, None, None, block.size, tail_policy="COMPRESS_TAIL"
                )
                child_artifact = encode_object(project_root, block_object, child_recipe)
                chunk = child_artifact.stream
                child_id = child_recipe.recipe_id
            except SourceDomainError as error:
                # A RAW block is legal only for the typed source-domain refusal.
                # Capacity, memory, malformed input and all other failures escape.
                if error.rejection_atomic is not True:
                    raise PipelineError(
                        "source-domain rejection did not prove atomic input/output state"
                    ) from error
                chosen = "RAW"
                rejection = {"type": "SOURCE_DOMAIN_ONLY", "reason": str(error)}
                chunk = block.tobytes(order="C")
                child_id = None
            attempt_ns = time.perf_counter_ns() - attempt_started
            chunks.append(chunk)
            blocks.append(
                {
                    "owner": name,
                    "column": column,
                    "start": start,
                    "count": block.size,
                    "dtype": block.dtype.str,
                    "encoding": chosen,
                    "offset": offset,
                    "length": len(chunk),
                    "sha256": hashlib.sha256(chunk).hexdigest(),
                    "child_recipe_id": child_id,
                    "source_attempt": {
                        "child_key": child.codec_key,
                        "parameters": child.parameters,
                        "input_sha256": input_hash,
                        "outcome": chosen,
                        "rejection": rejection,
                    },
                }
            )
            evidence_blocks.append(
                {
                    "owner": name,
                    "column": column,
                    "start": start,
                    "count": block.size,
                    "outcome": chosen,
                    "source_attempt_wall_ns": attempt_ns,
                    "source_attempt_evidence": "MEASURED_CONTROL_CLOCK",
                    "source_attempt_not_in_wire": True,
                    "input_sha256": input_hash,
                    "raw_bytes": len(chunk) if chosen == "RAW" else 0,
                    "child_artifact_bytes": len(chunk) if chosen == "CODEC" else 0,
                    "rejection": rejection,
                }
            )
            offset += len(chunk)
    header = {
        "schema_version": _ARTIFACT,
        "logical_schema": original.schema.to_document(),
        "logical_content_id": original.content_id,
        "underlying_bytes_sha256": before,
        "canonical_raw_bits": original.canonical_raw_bits,
        "recipe": recipe_document,
        "recipe_id": recipe.recipe_id,
        "blocks": blocks,
        "raw_escape_policy": "SOURCE_DOMAIN_ONLY_NO_OTHER_FAILURES",
    }
    raw_header = canonical_json_bytes(header)
    if len(raw_header) > _MAX_HEADER or offset > _MAX_PAYLOAD:
        raise PipelineError("source-reject raw artifact exceeds resource budget")
    stream = _FRAME.pack(_MAGIC, len(raw_header), offset) + raw_header + b"".join(chunks)
    if original.underlying_bytes_sha256 != before:
        raise PipelineError("raw escape encoder changed original input")
    ledger = PipelineLedger(
        original.canonical_raw_bits,
        offset * 8,
        (_FRAME.size + len(raw_header)) * 8,
        len(stream) * 8,
        len(stream) * 8,
    )
    return SourceRejectRawArtifact(
        stream,
        ledger,
        recipe.recipe_id,
        original.content_id,
        {
            "schema_version": "tscb.source-reject-raw-execution.v2",
            "blocks": evidence_blocks,
            "raw_escape_policy": "SOURCE_DOMAIN_ONLY",
            "encode_timing_boundary": "BLOCK_ATTEMPT_AND_SELECTED_FINALIZED_CHILD",
            "raw_block_count": sum(b["outcome"] == "RAW" for b in evidence_blocks),
            "codec_block_count": sum(b["outcome"] == "CODEC" for b in evidence_blocks),
            "final_bits": ledger.final_bits,
            "method_identity": child.codec_key,
        },
    )


def decode_source_reject_raw(
    project_root: Path,
    artifact: SourceRejectRawArtifact | bytes,
    *,
    available_child_keys: set[str] | None = None,
) -> RestoredObject:
    stream = artifact.stream if isinstance(artifact, SourceRejectRawArtifact) else artifact
    if len(stream) < _FRAME.size:
        raise PipelineError("truncated source-reject raw frame")
    magic, header_size, payload_size = _FRAME.unpack_from(stream)
    if (
        magic != _MAGIC
        or header_size > _MAX_HEADER
        or payload_size > _MAX_PAYLOAD
        or len(stream) != _FRAME.size + header_size + payload_size
    ):
        raise PipelineError("invalid/truncated source-reject raw frame")
    raw_header = stream[_FRAME.size : _FRAME.size + header_size]
    try:
        header = json.loads(raw_header)
    except (ValueError, UnicodeError) as error:
        raise PipelineError("invalid source-reject raw header JSON") from error
    required = {
        "schema_version",
        "logical_schema",
        "logical_content_id",
        "underlying_bytes_sha256",
        "canonical_raw_bits",
        "recipe",
        "recipe_id",
        "blocks",
        "raw_escape_policy",
    }
    if (
        not isinstance(header, dict)
        or set(header) != required
        or header["schema_version"] != _ARTIFACT
        or canonical_json_bytes(header) != raw_header
    ):
        raise PipelineError("invalid source-reject raw header fields/version/canonical encoding")
    recipe = SourceRejectRawRecipe.from_document(header["recipe"])
    schema = LogicalObjectSchema.from_document(header["logical_schema"])
    items, n = _validate(
        LogicalObject(
            schema,
            {
                item["name"]: np.empty(schema.n, dtype=np.dtype(item["dtype"]))
                for item in schema.to_document()["values"]
            },
        )
    )
    expected_bits = sum(n * np.dtype(item["dtype"]).itemsize * 8 for item in items)
    if header["recipe_id"] != recipe.recipe_id or header["canonical_raw_bits"] != expected_bits:
        raise PipelineError("source-reject raw identity or denominator differs")
    values = {item["name"]: np.empty(n, dtype=np.dtype(item["dtype"])) for item in items}
    payload = stream[_FRAME.size + header_size :]
    offset = 0
    expected_starts = {item["name"]: 0 for item in items}
    expected_columns = {item["name"]: column for column, item in enumerate(items)}
    expected_dtypes = {item["name"]: item["dtype"] for item in items}
    for block in header["blocks"]:
        owner = block.get("owner")
        count = block.get("count")
        if (
            owner not in values
            or block.get("column") != expected_columns[owner]
            or type(count) is not int
            or count <= 0
            or block.get("start") != expected_starts[owner]
            or block.get("offset") != offset
            or block.get("dtype") != expected_dtypes[owner]
        ):
            raise PipelineError("source-reject raw block order/count differs")
        length = block.get("length")
        if type(length) is not int or length < 0 or offset + length > len(payload):
            raise PipelineError("source-reject raw block length differs")
        chunk = payload[offset : offset + length]
        if hashlib.sha256(chunk).hexdigest() != block.get("sha256"):
            raise PipelineError("source-reject raw block digest differs")
        dtype = values[owner].dtype
        if block.get("encoding") == "RAW":
            if block.get("child_recipe_id") is not None or len(chunk) != count * dtype.itemsize:
                raise PipelineError("raw escape block length/dtype differs")
            restored = np.frombuffer(chunk, dtype=dtype).copy()
        elif block.get("encoding") == "CODEC":
            child_header, _ = _parse(chunk)
            child = decode_object(project_root, chunk, available_child_keys=available_child_keys)
            if (
                block.get("child_recipe_id") is None
                or child_header.get("recipe_id") != block["child_recipe_id"]
                or owner not in child.values
                or child.values[owner].shape != (count,)
                or child.values[owner].dtype.str != dtype.str
            ):
                raise PipelineError("source-reject child block descriptor differs")
            restored = child.values[owner]
        else:
            raise PipelineError("unknown source-reject raw block encoding")
        values[owner][block["start"] : block["start"] + count] = restored
        offset += length
        expected_starts[owner] += count
    if any(start != n for start in expected_starts.values()) or offset != len(payload):
        raise PipelineError("source-reject raw blocks do not cover payload")
    for array in values.values():
        array.flags.writeable = False
    restored = RestoredObject(schema, values)
    if (
        restored.content_id != header["logical_content_id"]
        or restored.underlying_bytes_sha256 != header["underlying_bytes_sha256"]
    ):
        raise PipelineError("source-reject raw reconstructed identity differs")
    if (
        isinstance(artifact, SourceRejectRawArtifact)
        and artifact.ledger.artifact_physical_bits != len(stream) * 8
    ):
        raise PipelineError("source-reject raw public accounting differs")
    return restored


def decode_source_reject_raw_in_fresh_process(
    project_root: Path,
    artifact: SourceRejectRawArtifact | bytes,
    *,
    available_child_keys: set[str] | None = None,
    timeout_seconds: float = 30,
) -> RestoredObject:
    stream = artifact.stream if isinstance(artifact, SourceRejectRawArtifact) else artifact
    context = multiprocessing.get_context("spawn")
    recv, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_raw_worker, args=(send, str(project_root), stream, available_child_keys)
    )
    process.start()
    send.close()
    try:
        if not recv.poll(timeout_seconds):
            raise PipelineError("source-reject raw clean decoder timed out")
        status, result = recv.recv()
        process.join(min(timeout_seconds, 5))
        if status != "PASS" or process.is_alive() or process.exitcode != 0:
            raise PipelineError(f"source-reject raw clean decoder failed: {result}")
        for array in result.values.values():
            array.flags.writeable = False
        return result
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        recv.close()
        process.close()


def _raw_worker(connection: Any, root: str, stream: bytes, available: set[str] | None) -> None:
    try:
        connection.send(
            ("PASS", decode_source_reject_raw(Path(root), stream, available_child_keys=available))
        )
    except BaseException as error:
        connection.send(("FAIL", f"{type(error).__name__}: {error}"))
    finally:
        connection.close()
