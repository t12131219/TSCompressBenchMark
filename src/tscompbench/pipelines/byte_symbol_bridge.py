"""Explicit BYTE_TO_RADIX4 bridge; v1 logical-object recipes remain unchanged."""

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
from .runtime import _MAX_HEADER, _MAX_PAYLOAD, decode_object, encode_object

_FRAME = struct.Struct("<8sIQ")
_MAGIC = b"TSCBBSV1"
_STAGES = ["BYTE_TO_RADIX4_MSB_FIRST", "EXISTING_CHILD_BLOCKS", "RADIX4_TO_BYTE_MSB_FIRST"]


@dataclass(frozen=True, init=False)
class ByteSymbolRecipe:
    serialized: bytes

    def __init__(self, child: ChildSpec, block_size_bytes: int = 1024) -> None:
        if not isinstance(child, ChildSpec) or child.codec_key != "deepzip":
            raise PipelineError("radix4 bridge requires the existing DeepZip child registration")
        if type(block_size_bytes) is not int or not 1 <= block_size_bytes <= 4_194_304:
            raise PipelineError("byte-symbol block size exceeds the frozen digit API limit")
        object.__setattr__(
            self,
            "serialized",
            canonical_json_bytes(
                {
                    "schema_version": "tscb.byte-symbol-recipe.v1",
                    "child": child.to_document(),
                    "block_size_bytes": block_size_bytes,
                    "mapping": "BYTE_TO_RADIX4",
                    "digit_order": "MSB_FIRST_6_4_2_0",
                    "digit_dtype": "|u1",
                    "digits_per_byte": 4,
                    "padding_digits": 0,
                    "tail_policy": "COMPRESS_TRUE_DIGIT_COUNT",
                    "stages": _STAGES,
                }
            ),
        )

    def to_document(self) -> dict[str, Any]:
        return json.loads(self.serialized)

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> ByteSymbolRecipe:
        try:
            recipe = cls(ChildSpec.from_document(document["child"]), document["block_size_bytes"])
        except (KeyError, TypeError) as error:
            raise PipelineError("invalid byte-symbol recipe fields") from error
        if recipe.to_document() != document:
            raise PipelineError("byte-symbol recipe fields/version/mapping differ")
        return recipe

    @property
    def recipe_id(self) -> str:
        return stable_id("byte-symbol-recipe", self.to_document(), version="v3")


def _validate_object(original: LogicalObject) -> None:
    document = original.schema.to_document()
    if (
        len(document["values"]) != 1
        or original.timestamp is not None
        or original.validity is not None
    ):
        raise PipelineError("byte-symbol v1 requires one byte buffer without T or validity")
    value = document["values"][0]
    if value["dtype"] != "|u1" or value["shape"] != [original.schema.n] or value["time_axis"] != 0:
        raise PipelineError("byte-symbol v1 requires the exact original uint8 UTS object")
    if original.schema.n * 4 > _MAX_PAYLOAD:
        raise PipelineError("byte-symbol transformed object exceeds allocation budget")


def _digit_schema(original_schema: LogicalObjectSchema) -> LogicalObjectSchema:
    document = original_schema.to_document()
    item = document["values"][0]
    item.update(
        name="radix4/digits",
        shape=[original_schema.n * 4],
        axes=["digit"],
        time_axis=0,
        unit="BYTE_RADIX4_DIGIT",
        feature="MSB_FIRST_6_4_2_0",
    )
    return LogicalObjectSchema.from_document(document)


def _map_bytes(original: np.ndarray[Any]) -> tuple[np.ndarray[Any], dict[str, Any]]:
    started = time.perf_counter_ns()
    digits = np.empty((original.size, 4), dtype=np.uint8)
    for column, shift in enumerate((6, 4, 2, 0)):
        np.right_shift(original, shift, out=digits[:, column])
        np.bitwise_and(digits[:, column], 3, out=digits[:, column])
    result = digits.reshape(-1)
    elapsed = time.perf_counter_ns() - started
    return result, {
        "stage": "BYTE_TO_RADIX4",
        "wall_ns": elapsed,
        "evidence_method": "MEASURED",
        "input_payload_bytes": original.size,
        "output_payload_bytes": result.size,
        "allocation_count": 1,
        "allocated_bytes": result.size,
        "allocation_evidence": "INSTRUMENTED_KNOWN_NUMPY_ARRAY_ALLOCATION",
        "read_bytes": original.size * 8,
        "write_bytes": original.size * 8,
        "access_evidence": "INSTRUMENTED_UFUNC_ELEMENT_OPERANDS_NOT_HARDWARE_TRAFFIC",
        "peak_live_bytes": original.size + result.size,
        "peak_evidence": "ESTIMATED_EXPLICIT_STAGE_ARRAYS_EXCLUDES_RUNTIME",
        "output_capacity_bytes": result.nbytes,
        "padding_bytes": 0,
    }


def _restore_bytes(digits: np.ndarray[Any], count: int) -> tuple[np.ndarray[Any], dict[str, Any]]:
    started = time.perf_counter_ns()
    if digits.dtype != np.uint8 or digits.shape != (4 * count,) or np.any(digits > 3):
        raise PipelineError("radix4 child changed exact count/dtype/alphabet")
    matrix = digits.reshape(count, 4)
    output, scratch = np.zeros(count, dtype=np.uint8), np.empty(count, dtype=np.uint8)
    for column, shift in enumerate((6, 4, 2, 0)):
        np.left_shift(matrix[:, column], shift, out=scratch)
        np.bitwise_or(output, scratch, out=output)
    elapsed = time.perf_counter_ns() - started
    output.flags.writeable = False
    return output, {
        "stage": "RADIX4_TO_BYTE",
        "wall_ns": elapsed,
        "evidence_method": "MEASURED",
        "input_payload_bytes": digits.size,
        "output_payload_bytes": count,
        "allocation_count": 2,
        "allocated_bytes": count * 2,
        "allocation_evidence": "INSTRUMENTED_KNOWN_NUMPY_ARRAY_ALLOCATION",
        "read_bytes": count * 16,
        "write_bytes": count * 9,
        "access_evidence": "INSTRUMENTED_UFUNC_ELEMENT_OPERANDS_NOT_HARDWARE_TRAFFIC",
        "peak_live_bytes": digits.size + 2 * count,
        "peak_evidence": "ESTIMATED_EXPLICIT_STAGE_ARRAYS_EXCLUDES_RUNTIME",
        "output_capacity_bytes": count,
        "padding_bytes": 0,
    }


@dataclass(frozen=True)
class ByteSymbolArtifact:
    stream: bytes
    ledger: PipelineLedger
    recipe_id: str
    logical_content_id: str
    execution_evidence: dict[str, Any]

    def __post_init__(self) -> None:
        if len(self.stream) * 8 != self.ledger.artifact_physical_bits:
            raise PipelineError("byte-symbol accounting differs from actual artifact bytes")


def encode_byte_symbol_bridge(
    project_root: Path, original: LogicalObject, recipe: ByteSymbolRecipe
) -> ByteSymbolArtifact:
    _validate_object(original)
    before = original.underlying_bytes_sha256
    name = original.schema.to_document()["values"][0]["name"]
    digits, adaptation = _map_bytes(original.values[name])
    child_recipe = PipelineRecipe(
        {"radix4/digits": ChildSpec.from_document(recipe.to_document()["child"])},
        None,
        None,
        recipe.to_document()["block_size_bytes"] * 4,
        tail_policy="COMPRESS_TAIL",
    )
    child_start = time.perf_counter_ns()
    child = encode_object(
        project_root,
        LogicalObject(_digit_schema(original.schema), {"radix4/digits": digits}),
        child_recipe,
    )
    child_ns = time.perf_counter_ns() - child_start
    header = {
        "schema_version": "tscb.byte-symbol-artifact.v1",
        "logical_schema": original.schema.to_document(),
        "logical_content_id": original.content_id,
        "underlying_bytes_sha256": before,
        "canonical_raw_bits": original.canonical_raw_bits,
        "recipe": recipe.to_document(),
        "recipe_id": recipe.recipe_id,
        "child_recipe_id": child.recipe_id,
        "child_sha256": hashlib.sha256(child.stream).hexdigest(),
        "native_input_elements": digits.size,
        "native_input_bytes": digits.nbytes,
        "original_byte_count": original.schema.n,
        "padding_digits": 0,
    }
    raw = canonical_json_bytes(header)
    if len(raw) > _MAX_HEADER or len(child.stream) > _MAX_PAYLOAD:
        raise PipelineError("byte-symbol artifact exceeds framing resource budget")
    stream = _FRAME.pack(_MAGIC, len(raw), len(child.stream)) + raw + child.stream
    if original.underlying_bytes_sha256 != before:
        raise PipelineError("byte-symbol encoder changed the original input")
    ledger = PipelineLedger(
        original.canonical_raw_bits,
        child.ledger.payload_physical_bits,
        len(stream) * 8 - child.ledger.payload_physical_bits,
        len(stream) * 8,
        len(stream) * 8,
    )
    return ByteSymbolArtifact(
        stream,
        ledger,
        recipe.recipe_id,
        original.content_id,
        {
            "schema_version": "tscb.byte-symbol-execution.v1",
            "stages": [adaptation],
            "child_pipeline_wall_ns": child_ns,
            "child_timing_boundary": "FULL_EXISTING_CHILD_OBJECT_PIPELINE",
            "native_input_bytes": digits.nbytes,
            "canonical_raw_bits": original.canonical_raw_bits,
            "child_ledger": child.ledger.to_document(),
            "model_cost": "EMBEDDED_ALL_COMPLETE_CHILD_NATIVE_FRAMES",
            "native_path": "EXISTING_DEEPZIP_ALPHABET4",
            "quality": "LOSSLESS",
        },
    )


def decode_byte_symbol_bridge(
    project_root: Path,
    artifact: ByteSymbolArtifact | bytes,
    *,
    available_child_keys: set[str] | None = None,
) -> tuple[RestoredObject, dict[str, Any]]:
    stream = artifact.stream if isinstance(artifact, ByteSymbolArtifact) else artifact
    if len(stream) < _FRAME.size:
        raise PipelineError("truncated byte-symbol frame")
    magic, header_size, child_size = _FRAME.unpack_from(stream)
    if (
        magic != _MAGIC
        or header_size > _MAX_HEADER
        or child_size > _MAX_PAYLOAD
        or len(stream) != _FRAME.size + header_size + child_size
    ):
        raise PipelineError("invalid/truncated byte-symbol frame or resource budget")
    raw = stream[_FRAME.size : _FRAME.size + header_size]
    try:
        header = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise PipelineError("invalid byte-symbol JSON") from error
    if (
        not isinstance(header, dict)
        or set(header)
        != {
            "schema_version",
            "logical_schema",
            "logical_content_id",
            "underlying_bytes_sha256",
            "canonical_raw_bits",
            "recipe",
            "recipe_id",
            "child_recipe_id",
            "child_sha256",
            "native_input_elements",
            "native_input_bytes",
            "original_byte_count",
            "padding_digits",
        }
        or header["schema_version"] != "tscb.byte-symbol-artifact.v1"
        or canonical_json_bytes(header) != raw
    ):
        raise PipelineError("invalid byte-symbol header fields/version/encoding")
    recipe = ByteSymbolRecipe.from_document(header["recipe"])
    schema = LogicalObjectSchema.from_document(header["logical_schema"])
    if schema.n * 4 > _MAX_PAYLOAD or len(schema.to_document()["values"]) != 1:
        raise PipelineError("byte-symbol original shape exceeds budget")
    description = schema.to_document()["values"][0]
    if (
        description["dtype"] != "|u1"
        or description["shape"] != [schema.n]
        or description["time_axis"] != 0
        or schema.to_document()["timestamp"]["present"]
        or header["recipe_id"] != recipe.recipe_id
        or header["canonical_raw_bits"] != schema.n * 8
        or header["original_byte_count"] != schema.n
        or header["native_input_elements"] != schema.n * 4
        or header["native_input_bytes"] != schema.n * 4
        or header["padding_digits"] != 0
    ):
        raise PipelineError(
            "byte-symbol mapping/count/dtype/order differs from frozen original task"
        )
    child_stream = stream[_FRAME.size + header_size :]
    if hashlib.sha256(child_stream).hexdigest() != header["child_sha256"]:
        raise PipelineError("byte-symbol child digest differs")
    child_recipe = PipelineRecipe(
        {"radix4/digits": ChildSpec.from_document(recipe.to_document()["child"])},
        None,
        None,
        recipe.to_document()["block_size_bytes"] * 4,
        tail_policy="COMPRESS_TAIL",
    )
    if child_recipe.recipe_id != header["child_recipe_id"]:
        raise PipelineError("byte-symbol child recipe differs from frozen branch")
    # Check the child's actual header identity, not only a redundant outer label.
    from .runtime import _parse

    child_header, child_payload = _parse(child_stream)
    if (
        child_header["recipe_id"] != child_recipe.recipe_id
        or child_header["logical_schema"] != _digit_schema(schema).to_document()
    ):
        raise PipelineError("actual byte-symbol child descriptor differs")
    child_start = time.perf_counter_ns()
    digits = decode_object(project_root, child_stream, available_child_keys=available_child_keys)
    child_ns = time.perf_counter_ns() - child_start
    values, inverse = _restore_bytes(digits.values["radix4/digits"], schema.n)
    restored = RestoredObject(schema, {description["name"]: values})
    if (
        restored.content_id != header["logical_content_id"]
        or restored.underlying_bytes_sha256 != header["underlying_bytes_sha256"]
    ):
        raise PipelineError("byte-symbol original byte identity differs after inverse")
    ledger = PipelineLedger(
        schema.n * 8,
        len(child_payload) * 8,
        (len(stream) - len(child_payload)) * 8,
        len(stream) * 8,
        len(stream) * 8,
    )
    if isinstance(artifact, ByteSymbolArtifact) and (
        artifact.ledger != ledger
        or artifact.recipe_id != recipe.recipe_id
        or artifact.logical_content_id != restored.content_id
    ):
        raise PipelineError("byte-symbol public artifact metadata differs from actual saved bytes")
    return restored, {
        "schema_version": "tscb.byte-symbol-execution.v1",
        "stages": [inverse],
        "child_pipeline_wall_ns": child_ns,
        "ledger": ledger.to_document(),
    }


def _worker(connection: Any, root: str, stream: bytes, available: set[str] | None) -> None:
    try:
        restored, evidence = decode_byte_symbol_bridge(
            Path(root), stream, available_child_keys=available
        )
        connection.send(
            (
                "PASS",
                restored,
                {
                    **evidence,
                    "start_method": "spawn",
                    "original_input_available": False,
                    "encoder_session_available": False,
                },
            )
        )
    except BaseException as error:
        connection.send(("FAIL", f"{type(error).__name__}: {error}", {}))
    finally:
        connection.close()


def decode_byte_symbol_in_fresh_process(
    project_root: Path,
    artifact: ByteSymbolArtifact | bytes,
    *,
    available_child_keys: set[str] | None = None,
    timeout_seconds: float = 30,
) -> tuple[RestoredObject, dict[str, Any]]:
    stream = artifact.stream if isinstance(artifact, ByteSymbolArtifact) else artifact
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker, args=(sending, str(project_root), stream, available_child_keys)
    )
    process.start()
    sending.close()
    try:
        if not receiving.poll(timeout_seconds):
            raise PipelineError("clean byte-symbol decoder timed out")
        status, result, evidence = receiving.recv()
        process.join(min(timeout_seconds, 5))
        if status != "PASS" or process.is_alive() or process.exitcode != 0:
            raise PipelineError(f"clean byte-symbol decoder failed: {result}")
        for name, value in result.values.items():
            owned = np.array(value, order="C", copy=True)
            owned.flags.writeable = False
            result.values[name] = owned
        return result, {
            **evidence,
            "worker_pid": process.pid,
            "worker_exit_confirmed": True,
            "exit_code": process.exitcode,
        }
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        receiving.close()
        process.close()
