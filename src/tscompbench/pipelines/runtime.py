"""Bounded P2 column/block trees using existing child codecs and public decoders."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import struct
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.adapters import create_adapter
from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.contracts import (
    BenchmarkTrack,
    CapabilityStatus,
    LossMode,
    Topology,
    ValidityShape,
)
from tscompbench.execution.preparation import prepare_execution_input
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput, SourceDomainError
from tscompbench.execution.recovery import DecodeContext, restore_decoded_output
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.planning.sweep import expand_sweep
from tscompbench.validation.lossy import validate_error_bound

from .models import (
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineArtifact,
    PipelineError,
    PipelineLedger,
    PipelineRecipe,
    RestoredObject,
    column_count,
    validate_loss_contract,
)

_FRAME = struct.Struct("<8sIQ")
_MAGIC = b"TSCBP2V1"
_MAX_HEADER = 16 * 1024 * 1024
_MAX_PAYLOAD = 512 * 1024 * 1024
_MAX_NODES = 100_000
_CANARY = b"TSCB_P2_OUTPUT_GUARD_V1"


def _registry(project_root: Path) -> CodecRegistry:
    return CodecRegistry(
        project_root / "registry/codecs", SourceRegistry(project_root / "registry/sources")
    )


def _prepare_child(
    project_root: Path,
    spec: ChildSpec,
    values: np.ndarray[Any],
    track: BenchmarkTrack,
    loss_contract: dict[str, str],
    timestamp_unit: str,
    timestamp_epoch: str,
    value_unit: str,
) -> tuple[Any, RoutedInput, Any, DecodeContext, dict[str, Any], Any]:
    values = np.array(values, order="C", copy=True)
    values.flags.writeable = False
    registry = _registry(project_root)
    if spec.codec_key not in registry.keys():
        raise PipelineError("child must name a current real registration, not an alias")
    scope = json.loads((project_root / "registry/algorithm_scope.json").read_text())
    if spec.codec_key not in scope["registered_codecs"]:
        raise PipelineError("child is outside the active algorithm scope")
    manifest = registry.get(spec.codec_key)
    resolved = expand_sweep(manifest, {key: [value] for key, value in spec.parameters.items()})
    if len(resolved) != 1 or resolved[0].status.value != "PLANNED":
        raise PipelineError("child configuration is invalid")
    parameters = resolved[0].parameters
    name = "timestamp" if track is BenchmarkTrack.TIMESTAMP else "value/000000"
    buffer = LogicalBuffer(name, np.ascontiguousarray(values), values.nbytes * 8)
    delta = (
        [int(b) - int(a) for a, b in zip(values[:-1], values[1:], strict=True)]
        if track is BenchmarkTrack.TIMESTAMP
        else []
    )
    descriptor = DataDescriptor(
        dataset_id="P2_CHILD",
        track=track,
        topology=Topology.UTS,
        n=values.size,
        m=1,
        shape=values.shape,
        dtype_vector=(values.dtype.str,),
        physical_layout="ROW_MAJOR_CONTIG",
        endianness="little" if values.dtype.byteorder != ">" else "big",
        alignment_bytes=1,
        canonical_raw_bits=values.nbytes * 8,
        validity_shape=ValidityShape.NONE,
        timestamp_present=track is BenchmarkTrack.TIMESTAMP,
        preserve_order=True,
        has_duplicates=track is BenchmarkTrack.TIMESTAMP and len(np.unique(values)) < values.size,
        has_out_of_order=any(d < 0 for d in delta),
        has_negative_delta=any(d < 0 for d in delta),
        timestamp_unit=timestamp_unit,
        timestamp_epoch=timestamp_epoch,
        value_units=() if track is BenchmarkTrack.TIMESTAMP else (value_unit,),
    )
    plan = negotiate(manifest, descriptor, parameters=parameters)
    if plan.status is CapabilityStatus.UNSUPPORTED:
        raise PipelineError(f"child source input is unsupported: {plan.reason_code}")
    loss = loss_contract.get("kind", "LOSSLESS")
    if track is BenchmarkTrack.TIMESTAMP or loss == "LOSSLESS":
        if plan.effective_loss_mode is not LossMode.LOSSLESS:
            raise PipelineError("lossy child cannot restore a lossless or timestamp task")
    elif plan.effective_loss_mode not in {LossMode.LOSSLESS, LossMode.ERROR_BOUNDED_LOSSY}:
        raise PipelineError("ABS pipeline requires a real bound-capable child")
    if loss == "ABS" and any(op.kind.value == "LOSSY_CAST" for op in plan.operations):
        raise PipelineError("unbudgeted lossy cast has no total original-domain ABS guarantee")
    if plan.effective_loss_mode is LossMode.ERROR_BOUNDED_LOSSY and (
        parameters.get("error_bound_type", "ABS").upper() not in {"ABS", "ABSOLUTE"}
        or Decimal(str(parameters.get("error_bound", "Infinity")))
        > Decimal(loss_contract["threshold"])
    ):
        raise PipelineError("child error budget exceeds the total original-domain ABS contract")
    routed = RoutedInput(
        "P2_CHILD",
        track,
        (buffer,),
        values if track is BenchmarkTrack.TIMESTAMP else None,
        None,
        values.size,
        1,
        values.nbytes * 8,
        hash_logical_buffers((buffer,)),
        timestamp_unit=timestamp_unit,
        timestamp_epoch=timestamp_epoch,
        value_units=() if track is BenchmarkTrack.TIMESTAMP else (value_unit,),
    )
    prepared = prepare_execution_input(routed, plan)
    context = DecodeContext.from_routed(
        routed, plan, adapter_id=spec.codec_key, parameters=parameters
    )
    return manifest, routed, prepared, context, parameters, plan


def _encode_child(
    project_root: Path,
    spec: ChildSpec,
    values: np.ndarray[Any],
    track: BenchmarkTrack,
    loss_contract: dict[str, str],
    timestamp_unit: str,
    timestamp_epoch: str,
    value_unit: str,
) -> tuple[bytes, dict[str, Any]]:
    manifest, routed, prepared, context, parameters, plan = _prepare_child(
        project_root,
        spec,
        values,
        track,
        loss_contract,
        timestamp_unit,
        timestamp_epoch,
        value_unit,
    )
    input_digest = routed.input_sha256
    buffer = routed.buffers[0]
    session = create_adapter(project_root, manifest, source_reject_fallback=False).create_session(
        parameters
    )
    try:
        try:
            bound = session.output_bound(prepared.codec_input)
        except SourceDomainError as error:
            # Preserve the typed source-domain refusal for a parent pipeline
            # that explicitly declares a RAW escape.
            error.rejection_atomic = True
            raise
        if type(bound) is not int or not 0 <= bound <= _MAX_PAYLOAD:
            raise PipelineError("child output bound exceeds the pipeline allocation budget")
        storage = bytearray(bound + len(_CANARY))
        storage[bound:] = _CANARY
        view = memoryview(storage)[:bound]
        try:
            updated = session.compress_update(prepared.codec_input, view)
        except SourceDomainError as error:
            if (
                hash_logical_buffers((buffer,)) != input_digest
                or any(storage[:bound])
                or bytes(storage[bound:]) != _CANARY
            ):
                raise PipelineError("source-domain rejection modified input/output") from error
            error.rejection_atomic = True
            raise
        if type(updated) is not int or not 0 <= updated <= bound:
            raise PipelineError("child update length violates its actual output bound")
        finalized = session.finalize(view[updated:])
        if type(finalized) is not int or not 0 <= finalized <= bound - updated:
            raise PipelineError("child finalization length violates its actual output bound")
        stream = bytes(storage[: updated + finalized])
        if bytes(storage[bound:]) != _CANARY:
            raise PipelineError("child write changed the output capacity canary")
        ledger = session.accounting(stream, prepared.codec_input)
    finally:
        session.close()
    if ledger.external_side_information_bits:
        raise PipelineError(
            "child external model/side information requires an explicit "
            "available dependency artifact"
        )
    if not isinstance(ledger.accounting_method, str) or len(ledger.accounting_method) > 128:
        raise PipelineError("child accounting method exceeds the metadata envelope")
    if hash_logical_buffers((buffer,)) != input_digest:
        raise PipelineError("child encoder changed its original input")
    return stream, {
        "codec_key": spec.codec_key,
        "algorithm_id": manifest.algorithm_id,
        "manifest": manifest.document,
        "parameters": parameters,
        "decode_context": context.to_document(),
        "accounting": ledger.to_document(),
        "compatibility_plan": plan.to_document(),
        "capability_origin": "EXISTING_CHILD_NATIVE_OR_EXPLICIT_COMPATIBILITY",
    }


def encode_object(
    project_root: Path, original: LogicalObject, recipe: PipelineRecipe
) -> PipelineArtifact:
    original_bytes_hash = original.underlying_bytes_sha256
    original_content_id = original.content_id
    original_raw_bits = original.canonical_raw_bits
    if set(recipe.value_children) != set(original.values):
        raise PipelineError("recipe must bind every ordered original value buffer")
    if original.timestamp is not None and recipe.timestamp_child is None:
        raise PipelineError("T+V requires a declared timestamp child")
    if any(
        column_count(v["shape"], v["time_axis"]) > _MAX_NODES
        for v in original.schema.to_document()["values"]
    ):
        raise PipelineError("pipeline column tree exceeds its declared node budget")
    if sum(v.nbytes for v in original.values.values()) + (
        0 if original.timestamp is None else original.timestamp.nbytes
    ) + (0 if original.validity is None else sum(m.nbytes for m in original.validity.values())) > (
        _MAX_PAYLOAD
    ):
        raise PipelineError("original object exceeds total allocation budget")
    nodes: list[dict[str, Any]] = []
    chunks: list[bytes] = []
    offset = 0

    def append(
        values: np.ndarray[Any],
        role: str,
        owner: str,
        column: int,
        start: int,
        child: ChildSpec | None,
        raw: bool,
        track: BenchmarkTrack,
    ) -> None:
        nonlocal offset
        stream, codec = (
            (values.tobytes(), None)
            if raw or child is None
            else _encode_child(
                project_root,
                child,
                values,
                track,
                {"kind": "LOSSLESS"} if role == "VALIDITY" else recipe.loss_contract,
                schema["timestamp"]["unit"],
                schema["timestamp"]["epoch"],
                "BOOLEAN"
                if role == "VALIDITY"
                else next(v["unit"] for v in schema["values"] if v["name"] == owner)
                if role == "VALUE"
                else "NOT_APPLICABLE",
            )
        )
        node = {
            "node_id": stable_id(
                "pipeline-child",
                {"role": role, "owner": owner, "column": column, "start": start},
                version="v3",
            ),
            "role": role,
            "owner": owner,
            "column": column,
            "start": start,
            "count": values.size,
            "dtype": values.dtype.str,
            "encoding": "RAW" if codec is None else "CODEC",
            "offset": offset,
            "length": len(stream),
            "sha256": hashlib.sha256(stream).hexdigest(),
            "child": codec,
        }
        nodes.append(node)
        chunks.append(stream)
        offset += len(stream)
        if len(nodes) > _MAX_NODES or offset > _MAX_PAYLOAD:
            raise PipelineError("pipeline tree exceeds its declared node/payload budget")

    schema = original.schema.to_document()
    for description in schema["values"]:
        name, axis = description["name"], description["time_axis"]
        values = np.array(original.values[name], copy=True)
        if schema["null_recovery_contract"] == "SEMANTIC" and original.validity is not None:
            values[~original.validity[name]] = 0
        count = column_count(description["shape"], axis)
        columns = np.moveaxis(values, axis, 0).reshape(original.schema.n, count)
        for column in range(count):
            for start in range(0, original.schema.n, recipe.block_size):
                block = np.ascontiguousarray(columns[start : start + recipe.block_size, column])
                raw = block.size < recipe.block_size and recipe.tail_policy == "RAW_TAIL"
                append(
                    block,
                    "VALUE",
                    name,
                    column,
                    start,
                    recipe.value_children[name],
                    raw,
                    BenchmarkTrack.VALUE,
                )
    if original.timestamp is not None:
        for start in range(0, original.schema.n, recipe.block_size):
            block = original.timestamp[start : start + recipe.block_size]
            raw = block.size < recipe.block_size and recipe.tail_policy == "RAW_TAIL"
            append(
                block,
                "TIMESTAMP",
                "timestamp",
                0,
                start,
                recipe.timestamp_child,
                raw,
                BenchmarkTrack.TIMESTAMP,
            )
    if original.validity is not None:
        for name, mask in original.validity.items():
            packed = np.packbits(mask.reshape(-1), bitorder="little")
            if packed.size:
                append(
                    packed, "VALIDITY", name, 0, 0, recipe.mask_child, False, BenchmarkTrack.VALUE
                )
    header = {
        "schema_version": "tscb.pipeline-artifact.v1",
        "logical_schema": schema,
        "logical_content_id": original_content_id,
        "underlying_bytes_sha256": original_bytes_hash,
        "recipe": recipe.to_document(),
        "recipe_id": recipe.recipe_id,
        "canonical_raw_bits": original_raw_bits,
        "validity_present": original.validity is not None,
        "nodes": nodes,
    }
    header_bytes = canonical_json_bytes(header)
    if len(header_bytes) > _MAX_HEADER:
        raise PipelineError("pipeline metadata exceeds its declared budget")
    stream = _FRAME.pack(_MAGIC, len(header_bytes), offset) + header_bytes + b"".join(chunks)
    if original.underlying_bytes_sha256 != original_bytes_hash:
        raise PipelineError("pipeline encoder changed the original object or validity/T pairing")
    ledger = PipelineLedger(
        original_raw_bits,
        offset * 8,
        (_FRAME.size + len(header_bytes)) * 8,
        len(stream) * 8,
        len(stream) * 8,
    )
    return PipelineArtifact(stream, ledger, recipe.recipe_id, original_content_id)


def object_output_bound(project_root: Path, original: LogicalObject, recipe: PipelineRecipe) -> int:
    """Bound each real child API plus the complete versioned metadata envelope.

    This performs negotiation/preparation and calls bound APIs, without encoding
    or retaining a previously encoded object. Work belongs to PIPELINE timing.
    """
    schema = original.schema.to_document()
    if set(recipe.value_children) != set(original.values):
        raise PipelineError("recipe must bind every original value")
    if original.timestamp is not None and recipe.timestamp_child is None:
        raise PipelineError("timestamp child is required")
    if sum(v.nbytes for v in original.values.values()) + (
        0 if original.timestamp is None else original.timestamp.nbytes
    ) + (0 if original.validity is None else sum(m.nbytes for m in original.validity.values())) > (
        _MAX_PAYLOAD
    ):
        raise PipelineError("original object exceeds total allocation budget")
    nodes, payload = [], 0

    def append(values, role, owner, column, start, child, raw, track, unit):
        nonlocal payload
        codec = None
        if raw or child is None:
            bound = values.nbytes
        else:
            manifest, routed, prepared, context, parameters, plan = _prepare_child(
                project_root,
                child,
                values,
                track,
                {"kind": "LOSSLESS"} if role == "VALIDITY" else recipe.loss_contract,
                schema["timestamp"]["unit"],
                schema["timestamp"]["epoch"],
                unit,
            )
            session = create_adapter(
                project_root, manifest, source_reject_fallback=False
            ).create_session(parameters)
            try:
                bound = session.output_bound(prepared.codec_input)
            finally:
                session.close()
            if type(bound) is not int or not 0 <= bound <= _MAX_PAYLOAD:
                raise PipelineError("child bound exceeds pipeline allocation budget")
            accounting = AccountingLedger.create(
                track=track, canonical_raw_bits=0, final_physical_bytes=0
            ).to_document()
            for key in accounting:
                if key.endswith("_bits") or key == "final_physical_bytes":
                    accounting[key] = 2**63 - 1
            for key in ("accounting_method", "compression_factor", "size_ratio"):
                accounting[key] = "\x01" * 128
            codec = {
                "codec_key": child.codec_key,
                "algorithm_id": manifest.algorithm_id,
                "manifest": manifest.document,
                "parameters": parameters,
                "decode_context": context.to_document(),
                "accounting": accounting,
                "compatibility_plan": plan.to_document(),
                "capability_origin": "EXISTING_CHILD_NATIVE_OR_EXPLICIT_COMPATIBILITY",
            }
        payload += bound
        nodes.append(
            {
                "node_id": stable_id(
                    "pipeline-child",
                    {"role": role, "owner": owner, "column": column, "start": start},
                    version="v3",
                ),
                "role": role,
                "owner": owner,
                "column": column,
                "start": start,
                "count": values.size,
                "dtype": values.dtype.str,
                "encoding": "RAW" if codec is None else "CODEC",
                "offset": _MAX_PAYLOAD,
                "length": _MAX_PAYLOAD,
                "sha256": "0" * 64,
                "child": codec,
            }
        )
        if len(nodes) > _MAX_NODES or payload > _MAX_PAYLOAD:
            raise PipelineError("pipeline output envelope exceeds node/payload budget")

    for item in schema["values"]:
        values = np.array(original.values[item["name"]], copy=True)
        if schema["null_recovery_contract"] == "SEMANTIC" and original.validity is not None:
            values[~original.validity[item["name"]]] = 0
        count = column_count(item["shape"], item["time_axis"])
        if count > _MAX_NODES:
            raise PipelineError("pipeline column tree exceeds its declared node budget")
        columns = np.moveaxis(values, item["time_axis"], 0).reshape(original.schema.n, count)
        for column in range(columns.shape[1]):
            for start in range(0, original.schema.n, recipe.block_size):
                block = np.ascontiguousarray(columns[start : start + recipe.block_size, column])
                append(
                    block,
                    "VALUE",
                    item["name"],
                    column,
                    start,
                    recipe.value_children[item["name"]],
                    block.size < recipe.block_size and recipe.tail_policy == "RAW_TAIL",
                    BenchmarkTrack.VALUE,
                    item["unit"],
                )
    if original.timestamp is not None:
        for start in range(0, original.schema.n, recipe.block_size):
            block = original.timestamp[start : start + recipe.block_size]
            append(
                block,
                "TIMESTAMP",
                "timestamp",
                0,
                start,
                recipe.timestamp_child,
                block.size < recipe.block_size and recipe.tail_policy == "RAW_TAIL",
                BenchmarkTrack.TIMESTAMP,
                "NOT_APPLICABLE",
            )
    if original.validity is not None:
        for name, mask in original.validity.items():
            packed = np.packbits(mask.reshape(-1), bitorder="little")
            if packed.size:
                append(
                    packed,
                    "VALIDITY",
                    name,
                    0,
                    0,
                    recipe.mask_child,
                    False,
                    BenchmarkTrack.VALUE,
                    "BOOLEAN",
                )
    header = {
        "schema_version": "tscb.pipeline-artifact.v1",
        "logical_schema": schema,
        "logical_content_id": original.content_id,
        "underlying_bytes_sha256": original.underlying_bytes_sha256,
        "recipe": recipe.to_document(),
        "recipe_id": recipe.recipe_id,
        "canonical_raw_bits": original.canonical_raw_bits,
        "validity_present": original.validity is not None,
        "nodes": nodes,
    }
    size = len(canonical_json_bytes(header))
    if size > _MAX_HEADER:
        raise PipelineError("pipeline metadata envelope exceeds allocation budget")
    return _FRAME.size + size + payload


def _parse(stream: bytes) -> tuple[dict[str, Any], bytes]:
    if len(stream) < _FRAME.size:
        raise PipelineError("truncated P2 artifact frame")
    magic, header_length, payload_length = _FRAME.unpack_from(stream)
    if (
        magic != _MAGIC
        or header_length > _MAX_HEADER
        or payload_length > _MAX_PAYLOAD
        or len(stream) != _FRAME.size + header_length + payload_length
    ):
        raise PipelineError("invalid/truncated P2 artifact frame or resource budget")
    raw = stream[_FRAME.size : _FRAME.size + header_length]
    try:
        header = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise PipelineError("invalid P2 metadata JSON") from error
    if (
        not isinstance(header, dict)
        or canonical_json_bytes(header) != raw
        or set(header)
        != {
            "schema_version",
            "logical_schema",
            "logical_content_id",
            "underlying_bytes_sha256",
            "recipe",
            "recipe_id",
            "canonical_raw_bits",
            "validity_present",
            "nodes",
        }
        or header["schema_version"] != "tscb.pipeline-artifact.v1"
    ):
        raise PipelineError("invalid P2 metadata fields/version/canonical encoding")
    if (
        not isinstance(header["nodes"], list)
        or len(header["nodes"]) > _MAX_NODES
        or type(header["validity_present"]) is not bool
        or type(header["canonical_raw_bits"]) is not int
        or header["canonical_raw_bits"] < 0
    ):
        raise PipelineError("invalid P2 tree size or validity declaration")
    return header, stream[_FRAME.size + header_length :]


def _decode_child(
    project_root: Path,
    node: dict[str, Any],
    stream: bytes,
    available: set[str] | None,
    loss_contract: dict[str, str],
) -> np.ndarray[Any]:
    if node["encoding"] == "RAW":
        if (
            node["child"] is not None
            or len(stream) != node["count"] * np.dtype(node["dtype"]).itemsize
        ):
            raise PipelineError("raw child length/dtype differs from descriptor")
        return np.frombuffer(stream, dtype=np.dtype(node["dtype"])).copy()
    child = node["child"]
    if node["encoding"] != "CODEC" or not isinstance(child, dict):
        raise PipelineError("missing or unknown child decoder")
    if set(child) != {
        "codec_key",
        "algorithm_id",
        "manifest",
        "parameters",
        "decode_context",
        "accounting",
        "compatibility_plan",
        "capability_origin",
    }:
        raise PipelineError("invalid child public dependency fields")
    key = child["codec_key"]
    if available is not None and key not in available:
        raise PipelineError("required public child decoder dependency is unavailable")
    registry = _registry(project_root)
    manifest = registry.get(key)
    if manifest.algorithm_id != child["algorithm_id"] or manifest.document != child["manifest"]:
        raise PipelineError("public child decoder identity differs from the saved artifact")
    if child["capability_origin"] != "EXISTING_CHILD_NATIVE_OR_EXPLICIT_COMPATIBILITY":
        raise PipelineError("child capability origin is unknown")
    document = child["accounting"]
    ledger = AccountingLedger(
        **{
            k: v
            for k, v in document.items()
            if k in AccountingLedger.__dataclass_fields__ and k not in {"_COMPONENTS", "track"}
        },
        track=BenchmarkTrack(document["track"]),
    )
    if (
        ledger.to_document() != document
        or ledger.track
        is not (BenchmarkTrack.TIMESTAMP if node["role"] == "TIMESTAMP" else BenchmarkTrack.VALUE)
        or ledger.final_physical_bytes != len(stream)
        or ledger.canonical_raw_bits != node["count"] * np.dtype(node["dtype"]).itemsize * 8
        or ledger.external_side_information_bits
    ):
        raise PipelineError("child accounting does not match the actual complete stream")
    context = DecodeContext(canonical_json_bytes(child["decode_context"]))
    recovery = context.to_document()
    if (
        recovery["parameters"] != child["parameters"]
        or recovery["adapter_id"] != key
        or recovery["track"] != ledger.track.value
        or recovery["canonical_raw_bits"] != ledger.canonical_raw_bits
        or recovery["n"] != node["count"]
        or recovery["m"] != 1
        or len(recovery["buffers"]) != 1
        or recovery["buffers"][0]["name"]
        != ("timestamp" if node["role"] == "TIMESTAMP" else "value/000000")
        or recovery["buffers"][0]["dtype"] != node["dtype"]
        or recovery["buffers"][0]["shape"] != [node["count"]]
        or recovery["buffers"][0]["logical_bits"] != ledger.canonical_raw_bits
    ):
        raise PipelineError("child public decoder parameters differ from its recovery context")
    saved_plan = child["compatibility_plan"]
    descriptor_doc = saved_plan["input_descriptor"]
    descriptor = DataDescriptor(
        **{
            **descriptor_doc,
            "track": BenchmarkTrack(descriptor_doc["track"]),
            "topology": Topology(descriptor_doc["topology"]),
            "validity_shape": ValidityShape(descriptor_doc["validity_shape"]),
            "shape": tuple(descriptor_doc["shape"]),
            "dtype_vector": tuple(descriptor_doc["dtype_vector"]),
            "value_units": tuple(descriptor_doc["value_units"]),
        }
    )
    if (
        descriptor.dataset_id != "P2_CHILD"
        or descriptor.track is not ledger.track
        or descriptor.topology is not Topology.UTS
        or descriptor.n != node["count"]
        or descriptor.m != 1
        or descriptor.shape != (node["count"],)
        or descriptor.dtype_vector != (node["dtype"],)
        or descriptor.canonical_raw_bits != ledger.canonical_raw_bits
        or descriptor.validity_shape is not ValidityShape.NONE
        or descriptor.timestamp_present != (ledger.track is BenchmarkTrack.TIMESTAMP)
        or descriptor.physical_layout != "ROW_MAJOR_CONTIG"
        or descriptor.endianness
        != ("big" if np.dtype(node["dtype"]).byteorder == ">" else "little")
        or descriptor.alignment_bytes != 1
        or descriptor.preserve_order is not True
        or descriptor.timestamp_unit != recovery["timestamp_unit"]
        or descriptor.timestamp_epoch != recovery["timestamp_epoch"]
        or list(descriptor.value_units) != recovery["value_units"]
        or any(
            type(descriptor_doc[k]) is not bool
            for k in ("has_duplicates", "has_out_of_order", "has_negative_delta")
        )
    ):
        raise PipelineError("child compatibility input differs from its logical slot")
    plan = negotiate(manifest, descriptor, parameters=child["parameters"])
    if json.loads(canonical_json_bytes(plan.to_document())) != saved_plan or (
        plan.status is CapabilityStatus.UNSUPPORTED
    ):
        raise PipelineError("saved child path differs from actual public compatibility negotiation")
    if (ledger.track is BenchmarkTrack.TIMESTAMP or loss_contract["kind"] == "LOSSLESS") and (
        plan.effective_loss_mode is not LossMode.LOSSLESS
    ):
        raise PipelineError("saved child path violates exact recovery")
    if loss_contract["kind"] == "ABS" and plan.effective_loss_mode not in {
        LossMode.LOSSLESS,
        LossMode.ERROR_BOUNDED_LOSSY,
    }:
        raise PipelineError("saved child path lacks the declared ABS guarantee")
    if loss_contract["kind"] == "ABS" and any(
        op.kind.value == "LOSSY_CAST" for op in plan.operations
    ):
        raise PipelineError("saved unbudgeted lossy cast has no total original-domain guarantee")
    if plan.effective_loss_mode is LossMode.ERROR_BOUNDED_LOSSY and (
        child["parameters"].get("error_bound_type", "ABS").upper() not in {"ABS", "ABSOLUTE"}
        or Decimal(str(child["parameters"].get("error_bound", "Infinity")))
        > Decimal(loss_contract["threshold"])
    ):
        raise PipelineError("saved child budget exceeds the total original-domain contract")
    dummy = np.empty(node["count"], dtype=np.dtype(node["dtype"]))
    expected_context = DecodeContext.from_routed(
        RoutedInput(
            "P2_CHILD",
            ledger.track,
            (LogicalBuffer(recovery["buffers"][0]["name"], dummy, ledger.canonical_raw_bits),),
            None,
            None,
            node["count"],
            1,
            ledger.canonical_raw_bits,
            "NOT_REQUIRED",
            timestamp_unit=descriptor.timestamp_unit,
            timestamp_epoch=descriptor.timestamp_epoch,
            value_units=descriptor.value_units,
        ),
        plan,
        adapter_id=key,
        parameters=child["parameters"],
    )
    if expected_context.serialized != context.serialized:
        raise PipelineError("saved child inverse differs from its negotiated public path")
    session = create_adapter(project_root, manifest, source_reject_fallback=False).create_session(
        child["parameters"]
    )
    try:
        decoded = restore_decoded_output(session.decompress(stream), context)
    finally:
        session.close()
    if len(decoded.buffers) != 1 or decoded.buffers[0].array.shape != (node["count"],):
        raise PipelineError("child reconstruction changed shape or buffer count")
    values = decoded.buffers[0].array
    if values.dtype.str != np.dtype(node["dtype"]).str:
        raise PipelineError("child reconstruction changed the original declared dtype")
    if ledger.track is BenchmarkTrack.TIMESTAMP:
        negative = any(int(b) < int(a) for a, b in zip(values[:-1], values[1:], strict=True))
        if (
            descriptor.has_duplicates != (np.unique(values).size < values.size)
            or descriptor.has_out_of_order != negative
            or descriptor.has_negative_delta != negative
        ):
            raise PipelineError("restored timestamp ordering differs from paid child evidence")
    return values


def decode_object(
    project_root: Path,
    artifact: PipelineArtifact | bytes,
    *,
    available_child_keys: set[str] | None = None,
) -> RestoredObject:
    stream = artifact.stream if isinstance(artifact, PipelineArtifact) else artifact
    header, payload = _parse(stream)
    schema = LogicalObjectSchema.from_document(header["logical_schema"])
    recipe = PipelineRecipe.from_document(header["recipe"])
    if set(recipe.value_children) != {v["name"] for v in schema.to_document()["values"]} or (
        schema.to_document()["timestamp"]["present"] and recipe.timestamp_child is None
    ):
        raise PipelineError("recipe does not cover the complete logical object")
    if recipe.recipe_id != header["recipe_id"]:
        raise PipelineError("saved recipe identity differs from its instructions")
    if isinstance(artifact, PipelineArtifact) and (
        artifact.recipe_id != header["recipe_id"]
        or artifact.logical_content_id != header["logical_content_id"]
        or artifact.ledger.canonical_raw_bits != header["canonical_raw_bits"]
        or artifact.ledger
        != PipelineLedger(
            header["canonical_raw_bits"],
            len(payload) * 8,
            (len(stream) - len(payload)) * 8,
            len(stream) * 8,
            len(stream) * 8,
        )
    ):
        raise PipelineError("artifact identities differ from the actual saved instructions")
    allocation = sum(
        int(np.prod(v["shape"], dtype=object)) * np.dtype(v["dtype"]).itemsize
        for v in schema.to_document()["values"]
    )
    allocation += schema.n * 8 if schema.to_document()["timestamp"]["present"] else 0
    allocation += (
        sum(int(np.prod(v["shape"], dtype=object)) for v in schema.to_document()["values"])
        if header["validity_present"]
        else 0
    )
    if (
        allocation > _MAX_PAYLOAD
        or any(
            column_count(v["shape"], v["time_axis"]) > _MAX_NODES
            for v in schema.to_document()["values"]
        )
        or sum(
            column_count(v["shape"], v["time_axis"])
            * ((schema.n + recipe.block_size - 1) // recipe.block_size)
            for v in schema.to_document()["values"]
        )
        > _MAX_NODES
    ):
        raise PipelineError("restored object exceeds total allocation budget")
    descriptions = {v["name"]: v for v in schema.to_document()["values"]}
    columns = {
        name: np.empty(
            (schema.n, column_count(v["shape"], v["time_axis"])), dtype=np.dtype(v["dtype"])
        )
        for name, v in descriptions.items()
    }
    timestamp = (
        np.empty(schema.n, dtype=np.dtype(schema.to_document()["timestamp"]["dtype"]))
        if schema.to_document()["timestamp"]["present"]
        else None
    )
    masks: dict[str, np.ndarray[Any]] | None = {} if header["validity_present"] else None
    expected_slots = [
        (role, name, col, start)
        for role, name, array in [("VALUE", name, array) for name, array in columns.items()]
        for col in range(array.shape[1])
        for start in range(0, schema.n, recipe.block_size)
    ]
    if timestamp is not None:
        expected_slots.extend(
            ("TIMESTAMP", "timestamp", 0, start) for start in range(0, schema.n, recipe.block_size)
        )
    if masks is not None:
        expected_slots.extend(
            ("VALIDITY", name, 0, 0)
            for name, v in descriptions.items()
            if np.prod(v["shape"], dtype=object)
        )
    expected = set(expected_slots)
    offset, seen = 0, set()
    for ordinal, node in enumerate(header["nodes"]):
        fields = {
            "node_id",
            "role",
            "owner",
            "column",
            "start",
            "count",
            "dtype",
            "encoding",
            "offset",
            "length",
            "sha256",
            "child",
        }
        if (
            not isinstance(node, dict)
            or set(node) != fields
            or any(
                type(node[k]) is not int or node[k] < 0
                for k in ("column", "start", "count", "offset", "length")
            )
        ):
            raise PipelineError("invalid P2 child descriptor")
        slot = node["role"], node["owner"], node["column"], node["start"]
        if (
            slot not in expected
            or slot in seen
            or ordinal >= len(expected_slots)
            or slot != expected_slots[ordinal]
            or node["offset"] != offset
            or offset + node["length"] > len(payload)
        ):
            raise PipelineError("duplicate/missing/reordered P2 child or overlapping payload")
        seen.add(slot)
        expected_node_id = stable_id(
            "pipeline-child",
            {
                "role": node["role"],
                "owner": node["owner"],
                "column": node["column"],
                "start": node["start"],
            },
            version="v3",
        )
        if node["node_id"] != expected_node_id:
            raise PipelineError("child identity differs from its tree slot")
        spec = (
            recipe.value_children[node["owner"]]
            if node["role"] == "VALUE"
            else recipe.timestamp_child
            if node["role"] == "TIMESTAMP"
            else recipe.mask_child
        )
        expected_dtype = (
            descriptions[node["owner"]]["dtype"]
            if node["role"] == "VALUE"
            else schema.to_document()["timestamp"]["dtype"]
            if node["role"] == "TIMESTAMP"
            else "|u1"
        )
        if np.dtype(node["dtype"]).str != np.dtype(expected_dtype).str:
            raise PipelineError("child dtype differs from its logical tree slot")
        raw_expected = spec is None or (
            node["role"] != "VALIDITY"
            and node["count"] < recipe.block_size
            and recipe.tail_policy == "RAW_TAIL"
        )
        if (node["encoding"] == "RAW") != raw_expected:
            raise PipelineError("hidden raw fallback differs from the frozen tail/child recipe")
        if not raw_expected:
            if (
                not isinstance(node["child"], dict)
                or node["child"].get("codec_key") != spec.codec_key
            ):
                raise PipelineError("actual child codec differs from the frozen recipe")
            normalized = expand_sweep(
                _registry(project_root).get(spec.codec_key),
                {key: [value] for key, value in spec.parameters.items()},
            )
            if len(normalized) != 1 or node["child"].get("parameters") != normalized[0].parameters:
                raise PipelineError("actual child parameters differ from the frozen recipe")
            recovery = node["child"].get("decode_context", {})
            if (
                recovery.get("timestamp_unit") != schema.to_document()["timestamp"]["unit"]
                or recovery.get("timestamp_epoch") != schema.to_document()["timestamp"]["epoch"]
                or recovery.get("value_units")
                != (
                    []
                    if node["role"] == "TIMESTAMP"
                    else [descriptions[node["owner"]]["unit"]]
                    if node["role"] == "VALUE"
                    else ["BOOLEAN"]
                )
            ):
                raise PipelineError("child recovery units differ from the logical schema")
        chunk = payload[offset : offset + node["length"]]
        offset += node["length"]
        if hashlib.sha256(chunk).hexdigest() != node["sha256"]:
            raise PipelineError("child payload digest differs")
        restored = _decode_child(
            project_root,
            node,
            chunk,
            available_child_keys,
            {"kind": "LOSSLESS"} if node["role"] == "VALIDITY" else recipe.loss_contract,
        )
        if node["role"] == "VALIDITY":
            shape = descriptions[node["owner"]]["shape"]
            size = int(np.prod(shape, dtype=object))
            if restored.dtype != np.uint8 or restored.size != (size + 7) // 8:
                raise PipelineError("packed validity child size differs")
            if size % 8 and int(restored[-1]) & ((0xFF << (size % 8)) & 0xFF):
                raise PipelineError("packed validity padding violates the declared LSB0 encoding")
            masks[node["owner"]] = (
                np.unpackbits(restored, bitorder="little")[:size]
                .astype(np.bool_)
                .reshape(shape)
                .copy()
            )
        else:
            length = min(recipe.block_size, schema.n - node["start"])
            if node["count"] != length:
                raise PipelineError("child block/tail true length differs")
            if node["role"] == "TIMESTAMP":
                timestamp[node["start"] : node["start"] + length] = restored
            else:
                columns[node["owner"]][node["start"] : node["start"] + length, node["column"]] = (
                    restored
                )
    if seen != expected or offset != len(payload):
        raise PipelineError("required child missing or unaccounted payload bytes")
    values = {}
    for name, description in descriptions.items():
        axis = description["time_axis"]
        moved_shape = [schema.n] + [n for i, n in enumerate(description["shape"]) if i != axis]
        values[name] = np.array(
            np.moveaxis(columns[name].reshape(moved_shape), 0, axis), order="C", copy=True
        )
        values[name].flags.writeable = False
        if masks is not None and name not in masks:
            masks[name] = np.empty(description["shape"], dtype=np.bool_)
    if timestamp is not None:
        timestamp.flags.writeable = False
    if masks is not None:
        for mask in masks.values():
            mask.flags.writeable = False
    restored_object = RestoredObject(schema, values, timestamp, masks)
    if restored_object.canonical_raw_bits != header["canonical_raw_bits"]:
        raise PipelineError("restored original denominator differs from artifact")
    if (
        recipe.to_document()["loss_contract"]["kind"] == "LOSSLESS"
        and restored_object.content_id != header["logical_content_id"]
    ):
        raise PipelineError("lossless reconstruction differs from saved original content identity")
    return restored_object


def _decode_worker(
    connection: Any, project_root: str, stream: bytes, available: set[str] | None
) -> None:
    try:
        restored = decode_object(Path(project_root), stream, available_child_keys=available)
        connection.send(
            (
                "PASS",
                restored,
                {
                    "start_method": "spawn",
                    "original_input_available": False,
                    "encoder_session_available": False,
                    "output_owned_in_worker": all(
                        v.flags.owndata
                        for v in [
                            *restored.values.values(),
                            *([] if restored.timestamp is None else [restored.timestamp]),
                            *([] if restored.validity is None else restored.validity.values()),
                        ]
                    ),
                    "schema_id": restored.schema.schema_id,
                },
            )
        )
    except BaseException as error:
        connection.send(("FAIL", f"{type(error).__name__}: {error}", {}))
    finally:
        connection.close()


def decode_in_fresh_process(
    project_root: Path,
    artifact: PipelineArtifact | bytes,
    *,
    available_child_keys: set[str] | None = None,
    timeout_seconds: float = 30,
) -> tuple[RestoredObject, dict[str, Any]]:
    stream = artifact.stream if isinstance(artifact, PipelineArtifact) else artifact
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(
        target=_decode_worker, args=(sending, str(project_root), stream, available_child_keys)
    )
    process.start()
    sending.close()
    try:
        if not receiving.poll(timeout_seconds):
            raise PipelineError("clean decoder process timed out")
        status, value, evidence = receiving.recv()
        process.join(min(timeout_seconds, 5))
        if status != "PASS" or process.is_alive() or process.exitcode != 0:
            raise PipelineError(f"clean decoder failed: {value}")
        evidence.update(
            {
                "worker_pid": process.pid,
                "exit_code": process.exitcode,
                "worker_exit_confirmed": True,
            }
        )
        # Multiprocessing transports owned copies; reinstate immutable consumer buffers.
        for array in [
            *value.values.values(),
            *([] if value.validity is None else value.validity.values()),
            *([] if value.timestamp is None else [value.timestamp]),
        ]:
            array.flags.writeable = False
        return value, evidence
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        receiving.close()
        process.close()


def validate_restored_object(
    original: LogicalObject,
    restored: RestoredObject,
    *,
    loss_contract: dict[str, str] | None = None,
) -> dict[str, Any]:
    if original.schema.serialized != restored.schema.serialized:
        return {"passed": False, "reason": "RESTORED_LOGICAL_SCHEMA_MISMATCH"}
    if (
        (original.validity is None) != (restored.validity is None)
        or original.validity is not None
        and any(
            not np.array_equal(mask, restored.validity[name])
            for name, mask in original.validity.items()
        )
    ):
        return {"passed": False, "reason": "VALIDITY_MISMATCH"}
    if (
        original.timestamp is not None
        and original.timestamp.tobytes() != restored.timestamp.tobytes()
    ):
        return {"passed": False, "reason": "TIMESTAMP_EXACT_PAIRING_MISMATCH"}
    loss = {"kind": "LOSSLESS"} if loss_contract is None else loss_contract
    validate_loss_contract(loss)
    if original.schema.to_document()["null_recovery_contract"] == "BITWISE" and (
        original.validity is not None
    ):
        for name, mask in original.validity.items():
            if original.values[name][~mask].tobytes() != restored.values[name][~mask].tobytes():
                return {"passed": False, "reason": "NULL_PAYLOAD_BITWISE_MISMATCH"}
    if loss == {"kind": "LOSSLESS"}:
        return {
            "passed": original.content_id == restored.content_id,
            "reason": None
            if original.content_id == restored.content_id
            else "ORIGINAL_CONTENT_MISMATCH",
            "schema_id": restored.schema.schema_id,
        }
    originals, reconstructed, masks, channel_map = {}, {}, {}, {}
    for item in original.schema.to_document()["values"]:
        name, axis = item["name"], item["time_axis"]
        non_time_shape = [n for i, n in enumerate(item["shape"]) if i != axis]
        columns = column_count(item["shape"], axis)
        before = np.moveaxis(original.values[name], axis, 0).reshape(original.schema.n, columns)
        after = np.moveaxis(restored.values[name], axis, 0).reshape(original.schema.n, columns)
        mask_columns = (
            None
            if original.validity is None
            else np.moveaxis(original.validity[name], axis, 0).reshape(original.schema.n, columns)
        )
        for column in range(columns):
            key = f"{name}/column/{column}"
            originals[key], reconstructed[key] = before[:, column], after[:, column]
            if mask_columns is not None:
                masks[key] = mask_columns[:, column]
            channel_map[key] = {
                "logical_buffer": name,
                "time_axis": axis,
                "unit": item["unit"],
                "axes": [a for i, a in enumerate(item["axes"]) if i != axis],
                "coordinates": [int(c) for c in np.unravel_index(column, non_time_shape)]
                if non_time_shape
                else [],
            }
    profile = validate_error_bound(
        originals,
        reconstructed,
        error_bound_type="ABS",
        error_bound=loss["threshold"],
        validity=None if original.validity is None else masks,
        timestamp=original.timestamp,
    )
    return {
        "passed": bool(profile.bound_passed),
        "reason": None if profile.bound_passed else "ORIGINAL_DOMAIN_BOUND_VIOLATION",
        "loss": profile.to_document(),
        "logical_channel_map": channel_map,
        "timestamp_unit": original.schema.to_document()["timestamp"]["unit"],
        "timestamp_epoch": original.schema.to_document()["timestamp"]["epoch"],
    }
