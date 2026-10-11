"""Versioned asynchronous/ragged objects, with independently paid P2 channels.

The synchronous logical-object and canonical wires retain their identities.
Every channel keeps its own shape, T/V pairing, time unit, epoch and null policy.
No collection operation sorts, aligns, pads, resamples or fabricates time axes.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.execution.protocol import LogicalBuffer
from tscompbench.ids import canonical_json_bytes, stable_id

from .models import (
    LogicalObject,
    LogicalObjectSchema,
    PipelineArtifact,
    PipelineError,
    PipelineLedger,
    PipelineRecipe,
)
from .runtime import decode_object, encode_object, validate_restored_object

_FRAME = struct.Struct("<8sIQ")
_RAW_MAGIC = b"TSCBCRV1"
_P2_MAGIC = b"TSCBCPV1"
_MAX_HEADER = 16 * 1024 * 1024
_MAX_PAYLOAD = 512 * 1024 * 1024
_MAX_CHANNELS = 1024
_MAX_BUFFERS = 100_000


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _allocation(schema: LogicalObjectSchema, validity: bool = True) -> int:
    doc = schema.to_document()
    sizes = [math.prod(item["shape"]) for item in doc["values"]]
    return (
        sum(
            size * np.dtype(item["dtype"]).itemsize
            for size, item in zip(sizes, doc["values"], strict=True)
        )
        + (schema.n * 8 if doc["timestamp"]["present"] else 0)
        + (sum(sizes) if validity else 0)
    )


@dataclass(frozen=True)
class ChannelCollectionSchema:
    serialized: bytes

    def __post_init__(self) -> None:
        try:
            doc = json.loads(self.serialized)
        except (ValueError, UnicodeError) as error:
            raise PipelineError("invalid collection schema JSON") from error
        if (
            not isinstance(doc, dict)
            or set(doc) != {"schema_version", "topology", "channels"}
            or doc["schema_version"] != "tscb.channel-collection-schema.v1"
            or doc["topology"]
            not in (
                {"kind": "ASYNCHRONOUS_MTS", "alignment": "NONE", "time_pairing": "PER_CHANNEL"},
                {"kind": "RAGGED_CHANNELS", "alignment": "NONE", "time_pairing": "PER_CHANNEL"},
            )
            or not isinstance(doc["channels"], list)
            or not 2 <= len(doc["channels"]) <= _MAX_CHANNELS
        ):
            raise PipelineError("invalid ordered collection schema/topology")
        names, lengths, allocation, buffers = [], [], 0, 0
        for channel in doc["channels"]:
            if (
                not isinstance(channel, dict)
                or set(channel) != {"channel_id", "timestamp_origin", "logical_schema"}
                or not isinstance(channel["channel_id"], str)
                or not channel["channel_id"]
                or len(channel["channel_id"].encode()) > 4096
            ):
                raise PipelineError("invalid channel identity/schema")
            schema = LogicalObjectSchema.from_document(channel["logical_schema"])
            for item in schema.to_document()["values"]:
                if (
                    math.prod(max(1, size) for size in item["shape"])
                    * np.dtype(item["dtype"]).itemsize
                    > _MAX_PAYLOAD
                ):
                    raise PipelineError("channel shape exceeds checked addressable shape budget")
            present = schema.to_document()["timestamp"]["present"]
            if channel["timestamp_origin"] not in (
                {"SOURCE_COLUMN", "MANIFEST_CONSTRUCTED"} if present else {"NONE"}
            ):
                raise PipelineError("channel timestamp origin must match original T presence")
            if doc["topology"]["kind"] == "ASYNCHRONOUS_MTS" and not present:
                raise PipelineError("asynchronous channels require their own original time axes")
            names.append(channel["channel_id"])
            lengths.append(schema.n)
            allocation += _allocation(schema)
            buffers += len(schema.to_document()["values"]) * 2 + int(present)
        if len(set(names)) != len(names):
            raise PipelineError("collection channels must have unique ordered identities")
        if doc["topology"]["kind"] == "RAGGED_CHANNELS" and len(set(lengths)) < 2:
            raise PipelineError("ragged collection must retain differing original channel lengths")
        if allocation > _MAX_PAYLOAD or buffers > _MAX_BUFFERS:
            raise PipelineError("collection exceeds aggregate allocation/buffer budget")
        if len(self.serialized) > _MAX_HEADER or canonical_json_bytes(doc) != self.serialized:
            raise PipelineError("collection schema must be bounded canonical JSON")

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> ChannelCollectionSchema:
        return cls(canonical_json_bytes(document))

    def to_document(self) -> dict[str, Any]:
        return json.loads(self.serialized)

    @property
    def schema_id(self) -> str:
        return stable_id("channel-collection-schema", self.to_document(), version="v3")


@dataclass(frozen=True)
class ChannelBufferView:
    channel_id: str
    schema: LogicalObjectSchema
    n: int
    values: tuple[LogicalBuffer, ...]
    timestamp: LogicalBuffer | None
    validity: tuple[LogicalBuffer, ...] | None


@dataclass(frozen=True)
class ChannelCollection:
    schema: ChannelCollectionSchema
    channels: dict[str, LogicalObject]

    def __post_init__(self) -> None:
        descriptions = self.schema.to_document()["channels"]
        if tuple(self.channels) != tuple(row["channel_id"] for row in descriptions):
            raise PipelineError("collection channel order differs from its schema")
        for row in descriptions:
            child = self.channels[row["channel_id"]]
            if (
                not isinstance(child, LogicalObject)
                or child.schema.to_document() != row["logical_schema"]
            ):
                raise PipelineError("channel logical schema differs from collection declaration")

    @property
    def canonical_raw_bits(self) -> int:
        return sum(child.canonical_raw_bits for child in self.channels.values())

    @property
    def content_id(self) -> str:
        return stable_id(
            "channel-collection",
            {
                "schema_id": self.schema.schema_id,
                "channels": [
                    {"channel_id": name, "content_id": child.content_id}
                    for name, child in self.channels.items()
                ],
            },
            version="v3",
        )

    @property
    def underlying_bytes_sha256(self) -> str:
        return _sha(
            canonical_json_bytes(
                {
                    "schema_id": self.schema.schema_id,
                    "channels": [
                        {"channel_id": name, "sha256": child.underlying_bytes_sha256}
                        for name, child in self.channels.items()
                    ],
                }
            )
        )

    def buffer_views(self) -> tuple[ChannelBufferView, ...]:
        result = []
        for name, child in self.channels.items():
            semantic = child.schema.to_document()["null_recovery_contract"] == "SEMANTIC"
            values = tuple(
                LogicalBuffer(
                    key,
                    array,
                    (
                        int(np.count_nonzero(child.validity[key]))
                        if semantic and child.validity is not None
                        else array.size
                    )
                    * array.dtype.itemsize
                    * 8,
                )
                for key, array in child.values.items()
            )
            result.append(
                ChannelBufferView(
                    name,
                    child.schema,
                    child.schema.n,
                    values,
                    None
                    if child.timestamp is None
                    else LogicalBuffer("timestamp", child.timestamp, child.timestamp.nbytes * 8),
                    None
                    if child.validity is None
                    else tuple(
                        LogicalBuffer(key, mask, mask.size) for key, mask in child.validity.items()
                    ),
                )
            )
        return tuple(result)


def standalone_collection_rejection(collection: ChannelCollection) -> dict[str, Any]:
    """The current standalone ABI has one shared n/T and cannot express this input."""
    return {
        "status": "UNSUPPORTED",
        "reason": "COLLECTION_REQUIRES_EXPLICIT_P2_RECIPE",
        "origin": "FRAMEWORK_EXECUTION_ABI",
        "stage": "INPUT_NEGOTIATION",
        "topology": collection.schema.to_document()["topology"],
        "channel_lengths": {name: child.schema.n for name, child in collection.channels.items()},
        "source_domain_checked": False,
        "codec_called": False,
        "actual_input_observed": False,
    }


def _pack(magic: bytes, header: dict[str, Any], payload: bytes) -> bytes:
    encoded = canonical_json_bytes(header)
    if len(encoded) > _MAX_HEADER or len(payload) > _MAX_PAYLOAD:
        raise PipelineError("collection frame exceeds header/payload budget")
    return _FRAME.pack(magic, len(encoded), len(payload)) + encoded + payload


def _parse(stream: bytes, magic: bytes, fields: set[str]) -> tuple[dict[str, Any], bytes]:
    if not isinstance(stream, bytes) or len(stream) < _FRAME.size:
        raise PipelineError("truncated collection frame")
    observed, header_size, payload_size = _FRAME.unpack_from(stream)
    if observed != magic or header_size > _MAX_HEADER or payload_size > _MAX_PAYLOAD:
        raise PipelineError("invalid collection magic or bounded frame length")
    if len(stream) != _FRAME.size + header_size + payload_size:
        raise PipelineError("truncated collection frame or forbidden suffix")
    encoded = stream[_FRAME.size : _FRAME.size + header_size]
    try:
        header = json.loads(encoded)
    except (ValueError, UnicodeError) as error:
        raise PipelineError("invalid collection frame JSON") from error
    if not isinstance(header, dict) or set(header) != fields:
        raise PipelineError("invalid collection header fields")
    if canonical_json_bytes(header) != encoded:
        raise PipelineError("collection header must use canonical JSON")
    payload = stream[_FRAME.size + header_size :]
    if header["payload_sha256"] != _sha(payload):
        raise PipelineError("collection payload SHA mismatch")
    for key in ("underlying_bytes_sha256", "payload_sha256"):
        if (
            not isinstance(header[key], str)
            or len(header[key]) != 64
            or any(char not in "0123456789abcdef" for char in header[key])
        ):
            raise PipelineError("invalid original/payload hash spelling")
    return header, payload


def _slots(collection: ChannelCollection) -> list[tuple[str, str, str, np.ndarray[Any]]]:
    return [
        (channel, role, owner, array)
        for channel, child in collection.channels.items()
        for role, owner, array in (
            [("VALUE", name, value) for name, value in child.values.items()]
            + ([] if child.timestamp is None else [("TIMESTAMP", "timestamp", child.timestamp)])
            + (
                []
                if child.validity is None
                else [("VALIDITY", name, mask) for name, mask in child.validity.items()]
            )
        )
    ]


def prepare_collection_raw(collection: ChannelCollection) -> bytes:
    """Materialize only explicit C-order per-buffer serialization, retaining every bit."""
    rows, chunks, offset = [], [], 0
    for channel, role, owner, array in _slots(collection):
        data = (
            np.packbits(array.reshape(-1), bitorder="little").tobytes()
            if role == "VALIDITY"
            else array.tobytes(order="C")
        )
        rows.append(
            {
                "channel_id": channel,
                "role": role,
                "owner": owner,
                "offset": offset,
                "length": len(data),
                "sha256": _sha(data),
            }
        )
        chunks.append(data)
        offset += len(data)
    payload = b"".join(chunks)
    return _pack(
        _RAW_MAGIC,
        {
            "schema_version": "tscb.channel-collection-raw.v1",
            "collection_schema": collection.schema.to_document(),
            "logical_content_id": collection.content_id,
            "underlying_bytes_sha256": collection.underlying_bytes_sha256,
            "canonical_raw_bits": collection.canonical_raw_bits,
            "validity_present": [
                child.validity is not None for child in collection.channels.values()
            ],
            "buffers": rows,
            "payload_sha256": _sha(payload),
        },
        payload,
    )


def _chunk(row: dict[str, Any], payload: bytes, offset: int, fields: set[str]) -> bytes:
    if (
        not isinstance(row, dict)
        or set(row) != fields
        or type(row["offset"]) is not int
        or row["offset"] != offset
        or type(row["length"]) is not int
        or row["length"] < 0
        or offset + row["length"] > len(payload)
    ):
        raise PipelineError("invalid/reordered/overlapping collection payload descriptor")
    data = payload[offset : offset + row["length"]]
    if row["sha256"] != _sha(data):
        raise PipelineError("channel buffer/frame SHA mismatch")
    return data


def import_collection_raw(stream: bytes) -> ChannelCollection:
    header, payload = _parse(
        stream,
        _RAW_MAGIC,
        {
            "schema_version",
            "collection_schema",
            "logical_content_id",
            "underlying_bytes_sha256",
            "canonical_raw_bits",
            "validity_present",
            "buffers",
            "payload_sha256",
        },
    )
    if header["schema_version"] != "tscb.channel-collection-raw.v1":
        raise PipelineError("unsupported raw collection version")
    schema = ChannelCollectionSchema.from_document(header["collection_schema"])
    descriptions = schema.to_document()["channels"]
    present, rows = header["validity_present"], header["buffers"]
    if (
        not isinstance(present, list)
        or len(present) != len(descriptions)
        or any(type(value) is not bool for value in present)
        or not isinstance(rows, list)
        or len(rows) > _MAX_BUFFERS
    ):
        raise PipelineError("invalid per-channel validity/buffer inventory")
    channels, ordinal, offset = {}, 0, 0
    for description, masked in zip(descriptions, present, strict=True):
        logical = LogicalObjectSchema.from_document(description["logical_schema"])
        doc, name = logical.to_document(), description["channel_id"]
        slots = [("VALUE", item["name"], item["dtype"], item["shape"]) for item in doc["values"]]
        if doc["timestamp"]["present"]:
            slots.append(("TIMESTAMP", "timestamp", doc["timestamp"]["dtype"], [logical.n]))
        if masked:
            slots.extend(("VALIDITY", item["name"], "|b1", item["shape"]) for item in doc["values"])
        values, timestamp, validity = {}, None, {} if masked else None
        for role, owner, dtype, shape in slots:
            if ordinal >= len(rows):
                raise PipelineError("missing channel buffer")
            row = rows[ordinal]
            data = _chunk(
                row,
                payload,
                offset,
                {
                    "channel_id",
                    "role",
                    "owner",
                    "offset",
                    "length",
                    "sha256",
                },
            )
            if (row["channel_id"], row["role"], row["owner"]) != (name, role, owner):
                raise PipelineError("channel buffer order/ownership differs from schema")
            count = math.prod(shape)
            expected = (count + 7) // 8 if role == "VALIDITY" else count * np.dtype(dtype).itemsize
            if len(data) != expected:
                raise PipelineError("channel buffer length differs from original shape")
            if role == "VALIDITY":
                if count % 8 and data and data[-1] >> (count % 8):
                    raise PipelineError("nonzero packed validity padding")
                array = np.array(
                    np.unpackbits(np.frombuffer(data, np.uint8), bitorder="little")[:count].reshape(
                        shape
                    ),
                    dtype=np.bool_,
                    copy=True,
                )
                validity[owner] = array
            else:
                array = np.array(
                    np.frombuffer(data, dtype=dtype).reshape(shape), copy=True, order="C"
                )
                if role == "VALUE":
                    values[owner] = array
                else:
                    timestamp = array
            array.flags.writeable = False
            ordinal += 1
            offset += len(data)
        channels[name] = LogicalObject(logical, values, timestamp, validity)
    if ordinal != len(rows) or offset != len(payload):
        raise PipelineError("unused collection descriptors or hidden payload")
    result = ChannelCollection(schema, channels)
    if (
        type(header["canonical_raw_bits"]) is not int
        or result.canonical_raw_bits != header["canonical_raw_bits"]
        or result.content_id != header["logical_content_id"]
        or result.underlying_bytes_sha256 != header["underlying_bytes_sha256"]
    ):
        raise PipelineError("raw collection original identity/denominator mismatch")
    return result


@dataclass(frozen=True)
class ChannelCollectionRecipe:
    serialized: bytes

    def __post_init__(self) -> None:
        try:
            doc = json.loads(self.serialized)
        except (ValueError, UnicodeError) as error:
            raise PipelineError("invalid collection recipe JSON") from error
        if (
            not isinstance(doc, dict)
            or set(doc) != {"schema_version", "channels"}
            or doc["schema_version"] != "tscb.channel-collection-recipe.v1"
            or not isinstance(doc["channels"], list)
            or not 2 <= len(doc["channels"]) <= _MAX_CHANNELS
        ):
            raise PipelineError("invalid collection recipe fields/version")
        names = []
        for row in doc["channels"]:
            if (
                not isinstance(row, dict)
                or set(row) != {"channel_id", "recipe"}
                or not isinstance(row["channel_id"], str)
                or not row["channel_id"]
            ):
                raise PipelineError("invalid collection recipe channel")
            child = PipelineRecipe.from_document(row["recipe"])
            if child.loss_contract != {"kind": "LOSSLESS"}:
                raise PipelineError("collection v1 requires lossless original-channel recipes")
            names.append(row["channel_id"])
        if (
            len(names) != len(set(names))
            or len(self.serialized) > _MAX_HEADER
            or canonical_json_bytes(doc) != self.serialized
        ):
            raise PipelineError("collection recipe must be unique, bounded and canonical")

    @classmethod
    def from_recipes(cls, channels: dict[str, PipelineRecipe]) -> ChannelCollectionRecipe:
        return cls(
            canonical_json_bytes(
                {
                    "schema_version": "tscb.channel-collection-recipe.v1",
                    "channels": [
                        {"channel_id": name, "recipe": child.to_document()}
                        for name, child in channels.items()
                    ],
                }
            )
        )

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> ChannelCollectionRecipe:
        return cls(canonical_json_bytes(document))

    def to_document(self) -> dict[str, Any]:
        return json.loads(self.serialized)

    @property
    def channels(self) -> dict[str, PipelineRecipe]:
        return {
            row["channel_id"]: PipelineRecipe.from_document(row["recipe"])
            for row in self.to_document()["channels"]
        }

    @property
    def recipe_id(self) -> str:
        return stable_id("channel-collection-recipe", self.to_document(), version="v3")


@dataclass(frozen=True)
class ChannelCollectionArtifact:
    stream: bytes
    ledger: PipelineLedger
    recipe_id: str
    logical_content_id: str

    def __post_init__(self) -> None:
        if self.ledger.artifact_physical_bits != len(self.stream) * 8:
            raise PipelineError("collection ledger differs from actual stored bytes")


def encode_collection(
    project_root: Path, original: ChannelCollection, recipe: ChannelCollectionRecipe
) -> ChannelCollectionArtifact:
    recipes = recipe.channels
    if tuple(recipes) != tuple(original.channels):
        raise PipelineError("collection recipe must bind every channel in original order")
    content_id, original_hash = original.content_id, original.underlying_bytes_sha256
    rows, artifacts, offset = [], [], 0
    for name, child in original.channels.items():
        artifact = encode_object(project_root, child, recipes[name])
        rows.append(
            {
                "channel_id": name,
                "offset": offset,
                "length": len(artifact.stream),
                "sha256": _sha(artifact.stream),
                "ledger": artifact.ledger.to_document(),
                "recipe_id": artifact.recipe_id,
                "logical_content_id": artifact.logical_content_id,
            }
        )
        artifacts.append(artifact)
        offset += len(artifact.stream)
        if offset > _MAX_PAYLOAD:
            raise PipelineError("collection child frames exceed total payload budget")
    payload = b"".join(artifact.stream for artifact in artifacts)
    stream = _pack(
        _P2_MAGIC,
        {
            "schema_version": "tscb.channel-collection-artifact.v1",
            "collection_schema": original.schema.to_document(),
            "logical_content_id": content_id,
            "underlying_bytes_sha256": original_hash,
            "canonical_raw_bits": original.canonical_raw_bits,
            "recipe": recipe.to_document(),
            "recipe_id": recipe.recipe_id,
            "channels": rows,
            "payload_sha256": _sha(payload),
        },
        payload,
    )
    if original.content_id != content_id or original.underlying_bytes_sha256 != original_hash:
        raise PipelineError("collection encoder changed original channels/T/validity")
    payload_bits = sum(artifact.ledger.payload_physical_bits for artifact in artifacts)
    ledger = PipelineLedger(
        original.canonical_raw_bits,
        payload_bits,
        len(stream) * 8 - payload_bits,
        len(stream) * 8 + sum(a.ledger.required_external_bits for a in artifacts),
        len(stream) * 8,
        sum(a.ledger.required_external_bits for a in artifacts),
    )
    return ChannelCollectionArtifact(stream, ledger, recipe.recipe_id, content_id)


def decode_collection(
    project_root: Path,
    artifact: ChannelCollectionArtifact | bytes,
    *,
    available_child_keys: set[str] | None = None,
) -> ChannelCollection:
    stream = artifact.stream if isinstance(artifact, ChannelCollectionArtifact) else artifact
    header, payload = _parse(
        stream,
        _P2_MAGIC,
        {
            "schema_version",
            "collection_schema",
            "logical_content_id",
            "underlying_bytes_sha256",
            "canonical_raw_bits",
            "recipe",
            "recipe_id",
            "channels",
            "payload_sha256",
        },
    )
    if header["schema_version"] != "tscb.channel-collection-artifact.v1":
        raise PipelineError("unsupported collection artifact version")
    schema = ChannelCollectionSchema.from_document(header["collection_schema"])
    recipe = ChannelCollectionRecipe.from_document(header["recipe"])
    names = tuple(row["channel_id"] for row in schema.to_document()["channels"])
    if tuple(recipe.channels) != names or recipe.recipe_id != header["recipe_id"]:
        raise PipelineError("collection recipe order/identity differs from saved instructions")
    rows = header["channels"]
    if not isinstance(rows, list) or len(rows) != len(names):
        raise PipelineError("missing/extra collection channel frames")
    channels, offset, payload_bits, external_bits = {}, 0, 0, 0
    for name, row in zip(names, rows, strict=True):
        data = _chunk(
            row,
            payload,
            offset,
            {
                "channel_id",
                "offset",
                "length",
                "sha256",
                "ledger",
                "recipe_id",
                "logical_content_id",
            },
        )
        if row["channel_id"] != name or row["recipe_id"] != recipe.channels[name].recipe_id:
            raise PipelineError("channel identity/order or paid recipe mismatch")
        doc = row["ledger"]
        ledger_fields = {
            "canonical_raw_bits",
            "payload_physical_bits",
            "metadata_physical_bits",
            "final_bits",
            "artifact_physical_bits",
            "required_external_bits",
        }
        if (
            not isinstance(doc, dict)
            or set(doc) != ledger_fields | {"schema_version"}
            or doc["schema_version"] != "tscb.pipeline-ledger.v1"
        ):
            raise PipelineError("invalid paid channel ledger")
        ledger = PipelineLedger(**{key: doc[key] for key in ledger_fields})
        child_artifact = PipelineArtifact(data, ledger, row["recipe_id"], row["logical_content_id"])
        child = decode_object(
            project_root, child_artifact, available_child_keys=available_child_keys
        )
        channels[name] = child
        offset += len(data)
        payload_bits += ledger.payload_physical_bits
        external_bits += ledger.required_external_bits
    if offset != len(payload):
        raise PipelineError("hidden collection payload outside channel frames")
    result = ChannelCollection(schema, channels)
    if (
        type(header["canonical_raw_bits"]) is not int
        or result.canonical_raw_bits != header["canonical_raw_bits"]
        or result.content_id != header["logical_content_id"]
    ):
        raise PipelineError("restored collection content/RawBits differs from original")
    if all(
        child.schema.to_document()["null_recovery_contract"] == "BITWISE" or child.validity is None
        for child in channels.values()
    ) and (result.underlying_bytes_sha256 != header["underlying_bytes_sha256"]):
        raise PipelineError("restored collection underlying bytes differ from bitwise contract")
    # SEMANTIC null slots may normalize; BITWISE child identity binds all underlying bytes.
    expected = PipelineLedger(
        result.canonical_raw_bits,
        payload_bits,
        len(stream) * 8 - payload_bits,
        len(stream) * 8 + external_bits,
        len(stream) * 8,
        external_bits,
    )
    if isinstance(artifact, ChannelCollectionArtifact) and (
        artifact.recipe_id != recipe.recipe_id
        or artifact.logical_content_id != result.content_id
        or artifact.ledger != expected
    ):
        raise PipelineError("collection artifact wrapper identity/ledger mismatch")
    return result


def validate_restored_collection(
    original: ChannelCollection,
    restored: ChannelCollection,
) -> dict[str, Any]:
    if original.schema.serialized != restored.schema.serialized:
        return {"passed": False, "reason": "COLLECTION_TOPOLOGY_OR_SCHEMA_MISMATCH"}
    reports = {
        name: validate_restored_object(child, restored.channels[name])
        for name, child in original.channels.items()
    }
    passed = all(report["passed"] for report in reports.values())
    return {
        "passed": passed,
        "reason": None if passed else "CHANNEL_RECOVERY_MISMATCH",
        "channel_reports": reports,
        "schema_id": restored.schema.schema_id,
        "canonical_raw_bits": restored.canonical_raw_bits,
        "channel_lengths": {name: child.schema.n for name, child in restored.channels.items()},
        "alignment": "NONE",
    }


def _worker(
    connection: Any,
    root: str,
    artifact: ChannelCollectionArtifact | bytes,
    available: set[str] | None,
) -> None:
    try:
        stream = artifact.stream if isinstance(artifact, ChannelCollectionArtifact) else artifact
        result = decode_collection(Path(root), artifact, available_child_keys=available)
        owned = all(array.flags.owndata for _, _, _, array in _slots(result))
        connection.send(
            (
                "PASS",
                result,
                {
                    "start_method": "spawn",
                    "original_input_available": False,
                    "encoder_session_available": False,
                    "output_owned_in_worker": owned,
                    "stream_sha256": _sha(stream),
                    "schema_id": result.schema.schema_id,
                },
            )
        )
    except BaseException as error:
        connection.send(("FAIL", f"{type(error).__name__}: {error}", {}))
    finally:
        connection.close()


def decode_collection_in_fresh_process(
    project_root: Path,
    artifact: ChannelCollectionArtifact | bytes,
    *,
    available_child_keys: set[str] | None = None,
    timeout_seconds: float = 30,
) -> tuple[ChannelCollection, dict[str, Any]]:
    stream = artifact.stream if isinstance(artifact, ChannelCollectionArtifact) else artifact
    # Validate the envelope before transporting it; original inputs never enter the worker.
    _parse(
        stream,
        _P2_MAGIC,
        {
            "schema_version",
            "collection_schema",
            "logical_content_id",
            "underlying_bytes_sha256",
            "canonical_raw_bits",
            "recipe",
            "recipe_id",
            "channels",
            "payload_sha256",
        },
    )
    context = multiprocessing.get_context("spawn")
    receiving, sending = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker, args=(sending, str(project_root), artifact, available_child_keys)
    )
    process.start()
    sending.close()
    try:
        if not receiving.poll(timeout_seconds):
            raise PipelineError("clean collection decoder process timed out")
        status, result, evidence = receiving.recv()
        process.join(min(timeout_seconds, 5))
        if status != "PASS" or process.is_alive() or process.exitcode != 0:
            raise PipelineError(f"clean collection decoder failed: {result}")
        for _, _, _, array in _slots(result):
            array.flags.writeable = False
        evidence.update(
            worker_pid=process.pid, exit_code=process.exitcode, worker_exit_confirmed=True
        )
        return result, evidence
    finally:
        if process.is_alive():
            process.terminate()
            process.join(5)
        receiving.close()
        process.close()
