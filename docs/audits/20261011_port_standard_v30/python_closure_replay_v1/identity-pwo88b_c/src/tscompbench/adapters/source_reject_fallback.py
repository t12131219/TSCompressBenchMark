"""Explicit, bounded lossless source-domain/RAW composition for an existing codec."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Any

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import (
    CodecAdapter,
    CodecSession,
    DecodedOutput,
    EncodedArtifact,
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
    SourceDomainError,
)
from tscompbench.execution.routing import hash_logical_buffers, hash_reference_array
from tscompbench.ids import canonical_json_bytes, stable_id

_FRAME = struct.Struct("<8sIQ")
_MAGIC = b"TSCBRSV3"
_SCHEMA = "tscb.source-reject-composite.v3"
_MAX_HEADER = 16 * 1024 * 1024
_MAX_PAYLOAD = 512 * 1024 * 1024
_MAX_INPUT = 128 * 1024 * 1024
_MAX_INTEGER = 2**63 - 1
_MAX_TEXT = 1024
_BLOCK_ROWS = 102_400
_CANARY = b"TSCB_SOURCE_REJECTION_CANARY_V3"
_DTYPES = {"|i1", "|u1", "<i2", "<u2", "<i4", "<u4", "<i8", "<u8", "<f4", "<f8"}
_POLICY = "SOURCE_DOMAIN_ONLY_NO_OTHER_FAILURES"
_HEADER_FIELDS = {
    "schema_version",
    "child_key",
    "child_adapter_id",
    "parameters",
    "block_rows",
    "track",
    "n",
    "m",
    "buffers",
    "canonical_raw_bits",
    "input_sha256",
    "blocks",
    "recipe_id",
    "fallback_policy",
}
_BLOCK_FIELDS = {
    "start",
    "count",
    "encoding",
    "offset",
    "length",
    "sha256",
    "input_sha256",
    "child_key",
    "parameters",
    "rejection",
    "child_ledger",
    "raw_descriptors",
}
_BUFFER_FIELDS = {"name", "dtype", "shape", "logical_bits"}
_RAW_FIELDS = _BUFFER_FIELDS | {"offset", "length", "sha256"}


def _integer(value: Any, *, maximum: int = _MAX_INTEGER, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _text(value: Any, *, maximum: int = _MAX_TEXT) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    )


def _block_rows(value: Any) -> int:
    if not _integer(value, minimum=1, maximum=_BLOCK_ROWS):
        raise ExecutionContractError("source-reject composite block_rows is invalid")
    return value


def source_reject_composite_adapter_id(
    child_adapter_id: str, child_key: str, block_rows: int = _BLOCK_ROWS
) -> str:
    return stable_id(
        "source-reject-composite-adapter",
        {
            "schema_version": _SCHEMA,
            "child_key": child_key,
            "child_adapter_id": child_adapter_id,
            "block_rows": _block_rows(block_rows),
        },
        version="v3",
    )


def source_reject_composite_recipe_id(
    child_adapter_id: str,
    child_key: str,
    parameters: dict[str, Any],
    block_rows: int = _BLOCK_ROWS,
) -> str:
    return stable_id(
        "source-reject-composite-recipe",
        {
            "schema_version": _SCHEMA,
            "child_key": child_key,
            "child_adapter_id": child_adapter_id,
            "parameters": parameters,
            "block_rows": _block_rows(block_rows),
            "fallback_policy": _POLICY,
        },
        version="v3",
    )


def _slice_buffer(item: LogicalBuffer, start: int, stop: int) -> LogicalBuffer:
    array = np.ascontiguousarray(item.array[start:stop])
    return LogicalBuffer(item.name, array, array.nbytes * 8)


def _block_input(routed: RoutedInput, start: int, stop: int) -> RoutedInput:
    buffers = tuple(_slice_buffer(item, start, stop) for item in routed.buffers)
    timestamp = (
        None if routed.timestamp_reference is None else routed.timestamp_reference[start:stop]
    )
    validity = None if routed.validity_reference is None else routed.validity_reference[start:stop]
    return RoutedInput(
        dataset_id=routed.dataset_id,
        track=routed.track,
        buffers=buffers,
        timestamp_reference=timestamp,
        validity_reference=validity,
        n=stop - start,
        m=routed.m,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
        segment_plan_id=routed.segment_plan_id,
        timestamp_unit=routed.timestamp_unit,
        timestamp_epoch=routed.timestamp_epoch,
        value_units=routed.value_units,
        pairing_reference_sha256=hash_reference_array(timestamp),
    )


def _descriptors(routed: RoutedInput) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "dtype": item.array.dtype.str,
            "shape": list(item.array.shape),
            "logical_bits": item.logical_bits,
        }
        for item in routed.buffers
    ]


def _validate_buffers(items: Any, n: int, m: int) -> int:
    if not isinstance(items, list) or not items or len(items) > 65535:
        raise ExecutionContractError("invalid source-reject composite buffers")
    names, total, channels = set(), 0, 0
    for item in items:
        if (
            not isinstance(item, dict)
            or set(item) != _BUFFER_FIELDS
            or not _text(item["name"])
            or item["name"] in names
            or not isinstance(item["dtype"], str)
            or item["dtype"] not in _DTYPES
            or not isinstance(item["shape"], list)
            or len(item["shape"]) not in {1, 2}
            or any(not _integer(v, maximum=16 * 1024 * 1024) for v in item["shape"])
            or item["shape"][0] != n
        ):
            raise ExecutionContractError("invalid source-reject composite buffer descriptor")
        names.add(item["name"])
        bits = math.prod(item["shape"]) * np.dtype(item["dtype"]).itemsize * 8
        if not _integer(item["logical_bits"]) or item["logical_bits"] != bits:
            raise ExecutionContractError("source-reject composite logical bits mismatch")
        total += bits
        channels += item["shape"][1] if len(item["shape"]) == 2 else 1
    if channels != m or total > _MAX_INPUT * 8:
        raise ExecutionContractError("source-reject composite channel/input budget mismatch")
    return total


def _validate_input(routed: RoutedInput) -> None:
    if (
        routed.track is not BenchmarkTrack.VALUE
        or not _integer(routed.n, maximum=16 * 1024 * 1024)
        or not _integer(routed.m, maximum=65535, minimum=1)
        or routed.n * routed.m > 16 * 1024 * 1024
        or not _integer(routed.canonical_raw_bits)
        or _validate_buffers(_descriptors(routed), routed.n, routed.m) != routed.canonical_raw_bits
        or hash_logical_buffers(routed.buffers) != routed.input_sha256
    ):
        raise ExecutionContractError("invalid source-reject composite original input")


def _ledger(document: Any, *, raw_bits: int, length: int) -> AccountingLedger:
    template = AccountingLedger.create(
        track=BenchmarkTrack.VALUE, canonical_raw_bits=0, final_physical_bytes=0
    ).to_document()
    if not isinstance(document, dict) or set(document) != set(template):
        raise ExecutionContractError("invalid source-reject composite child ledger fields")
    fields = {
        key: document[key] for key in AccountingLedger.__dataclass_fields__ if key != "_COMPONENTS"
    }
    if (
        document["schema_version"] != "tscb.accounting-ledger.v2"
        or document["track"] != BenchmarkTrack.VALUE
        or not _text(document["accounting_method"], maximum=128)
        or any(
            not _integer(value)
            for key, value in fields.items()
            if key not in {"track", "accounting_method"}
        )
        or any(
            document[key] is not None and not _text(document[key], maximum=128)
            for key in ("compression_factor", "size_ratio")
        )
    ):
        raise ExecutionContractError("invalid source-reject composite child ledger values")
    try:
        ledger = AccountingLedger(**fields)
    except ValueError as error:
        raise ExecutionContractError(
            "source-reject composite child ledger does not close"
        ) from error
    if (
        ledger.canonical_raw_bits != raw_bits
        or ledger.final_physical_bytes != length
        or ledger.external_side_information_bits != 0
        or canonical_json_bytes(ledger.to_document()) != canonical_json_bytes(document)
    ):
        raise ExecutionContractError(
            "source-reject composite child is not self-contained/accounted"
        )
    return ledger


def _child_bound(child: CodecAdapter, parameters: dict[str, Any], routed: RoutedInput) -> int:
    session = child.create_session(parameters)
    try:
        bound = session.output_bound(routed)
        if not _integer(bound, maximum=_MAX_PAYLOAD):
            raise ExecutionContractError(
                "child output_bound is invalid or exceeds allocation budget"
            )
        return bound
    finally:
        session.close()


def _child_encode(
    child: CodecAdapter, parameters: dict[str, Any], routed: RoutedInput
) -> EncodedArtifact:
    session = child.create_session(parameters)
    try:
        bound = session.output_bound(routed)
        if not _integer(bound, maximum=_MAX_PAYLOAD):
            raise ExecutionContractError(
                "child output_bound is invalid or exceeds allocation budget"
            )
        storage = bytearray(bound + len(_CANARY))
        storage[bound:] = _CANARY
        before = hash_logical_buffers(routed.buffers)
        timestamp_before = hash_reference_array(routed.timestamp_reference)
        validity_before = hash_reference_array(routed.validity_reference)
        try:
            updated = session.compress_update(routed, memoryview(storage)[:bound])
        except SourceDomainError as error:
            atomic = (
                error.rejection_atomic is True
                and not any(storage[:bound])
                and bytes(storage[bound:]) == _CANARY
                and before == hash_logical_buffers(routed.buffers)
                and timestamp_before == hash_reference_array(routed.timestamp_reference)
                and validity_before == hash_reference_array(routed.validity_reference)
            )
            if not atomic:
                raise ExecutionContractError(
                    "child source rejection modified input/output or was not atomic"
                ) from error
            raise
        if not _integer(updated, maximum=bound):
            raise ExecutionContractError("child compress_update length is invalid")
        finalized = session.finalize(memoryview(storage)[updated:bound])
        if not _integer(finalized, maximum=bound - updated):
            raise ExecutionContractError("child finalize length is invalid")
        if (
            bytes(storage[bound:]) != _CANARY
            or before != hash_logical_buffers(routed.buffers)
            or timestamp_before != hash_reference_array(routed.timestamp_reference)
            or validity_before != hash_reference_array(routed.validity_reference)
        ):
            raise ExecutionContractError("child encoding modified input or output guard")
        stream = bytes(storage[: updated + finalized])
        ledger = session.accounting(stream, routed)
        _ledger(ledger.to_document(), raw_bits=routed.canonical_raw_bits, length=len(stream))
        return EncodedArtifact(
            stream, updated, finalized, bound, hashlib.sha256(stream).hexdigest(), ledger
        )
    finally:
        session.close()


def _raw_descriptors(routed: RoutedInput) -> tuple[list[dict[str, Any]], bytes]:
    descriptors, payload = [], bytearray()
    for item, descriptor in zip(routed.buffers, _descriptors(routed), strict=True):
        data = item.array.tobytes(order="C")
        descriptors.append(
            {
                **descriptor,
                "offset": len(payload),
                "length": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        payload.extend(data)
    return descriptors, bytes(payload)


@dataclass(frozen=True)
class SourceRejectCompositeAdapter(CodecAdapter):
    child: CodecAdapter
    child_key: str
    block_rows: int = _BLOCK_ROWS

    def __post_init__(self) -> None:
        _block_rows(self.block_rows)
        if not _text(self.child_key) or not _text(self.child.adapter_id):
            raise ExecutionContractError("invalid source-reject composite child identity")

    @property
    def adapter_id(self) -> str:
        return source_reject_composite_adapter_id(
            self.child.adapter_id, self.child_key, self.block_rows
        )

    @property
    def deterministic(self) -> bool:
        return self.child.deterministic

    def create_session(self, parameters: dict[str, Any]) -> CodecSession:
        return SourceRejectCompositeSession(self, parameters)


class SourceRejectCompositeSession(CodecSession):
    def __init__(self, adapter: SourceRejectCompositeAdapter, parameters: dict[str, Any]):
        self.adapter = adapter
        if not isinstance(parameters, dict) or len(canonical_json_bytes(parameters)) > 65536:
            raise ExecutionContractError("invalid source-reject composite parameters")
        self.parameters = json.loads(canonical_json_bytes(parameters))
        self.recipe_id = source_reject_composite_recipe_id(
            adapter.child.adapter_id, adapter.child_key, self.parameters, adapter.block_rows
        )
        self._artifact: EncodedArtifact | None = None
        self._closed = self._finalized = False

    def _ensure_open(self) -> None:
        if self._closed:
            raise ExecutionContractError("source-reject composite session is closed")

    def _header(self, routed: RoutedInput, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema_version": _SCHEMA,
            "child_key": self.adapter.child_key,
            "child_adapter_id": self.adapter.child.adapter_id,
            "parameters": self.parameters,
            "block_rows": self.adapter.block_rows,
            "track": routed.track,
            "n": routed.n,
            "m": routed.m,
            "buffers": _descriptors(routed),
            "canonical_raw_bits": routed.canonical_raw_bits,
            "input_sha256": routed.input_sha256,
            "blocks": blocks,
            "recipe_id": self.recipe_id,
            "fallback_policy": _POLICY,
        }

    def _block(self, routed: RoutedInput, start: int, count: int, offset: int, length: int) -> dict:
        return {
            "start": start,
            "count": count,
            "encoding": "CODEC",
            "offset": offset,
            "length": length,
            "sha256": "0" * 64,
            "input_sha256": routed.input_sha256,
            "child_key": self.adapter.child_key,
            "parameters": self.parameters,
            "rejection": None,
            "child_ledger": None,
            "raw_descriptors": None,
        }

    def output_bound(self, routed: RoutedInput) -> int:
        """Sum actual child bounds and a schema-derived worst-case metadata envelope."""
        self._ensure_open()
        _validate_input(routed)
        blocks, payload_bound = [], 0
        for start in range(0, max(1, routed.n), self.adapter.block_rows):
            count = min(self.adapter.block_rows, routed.n - start)
            block = _block_input(routed, start, start + count)
            child_bound = _child_bound(self.adapter.child, self.parameters, block)
            length = max(child_bound, sum(item.array.nbytes for item in block.buffers))
            maximum = self._block(block, start, count, _MAX_PAYLOAD, _MAX_PAYLOAD)
            descriptors = []
            for item in _descriptors(block):
                descriptors.append(
                    {**item, "offset": _MAX_PAYLOAD, "length": _MAX_PAYLOAD, "sha256": "0" * 64}
                )
            ledger = AccountingLedger.create(
                track=BenchmarkTrack.VALUE, canonical_raw_bits=0, final_physical_bytes=0
            ).to_document()
            for key in ledger:
                if key.endswith("_bits") or key == "final_physical_bytes":
                    ledger[key] = _MAX_INTEGER
            for key in ("accounting_method", "compression_factor", "size_ratio"):
                ledger[key] = "\x01" * 128
            maximum.update(
                rejection={"type": "SOURCE_DOMAIN_ONLY", "reason": "\x01" * _MAX_TEXT},
                child_ledger=ledger,
                raw_descriptors=descriptors,
            )
            blocks.append(maximum)
            payload_bound += length
            if payload_bound > _MAX_PAYLOAD:
                raise OutputCapacityError("source-reject composite payload bound exceeds budget")
        header_bound = len(canonical_json_bytes(self._header(routed, blocks)))
        if header_bound > _MAX_HEADER:
            raise OutputCapacityError("source-reject composite metadata bound exceeds budget")
        return _FRAME.size + header_bound + payload_bound

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        self._ensure_open()
        if self._artifact is not None or self._finalized:
            raise ExecutionContractError("source-reject composite update called twice")
        _validate_input(routed)
        chunks, blocks, payload_offset = [], [], 0
        for start in range(0, max(1, routed.n), self.adapter.block_rows):
            count = min(self.adapter.block_rows, routed.n - start)
            block_input = _block_input(routed, start, start + count)
            block = self._block(block_input, start, count, payload_offset, 0)
            try:
                child = _child_encode(self.adapter.child, self.parameters, block_input)
                chunk = child.stream
                block["child_ledger"] = child.ledger.to_document()
            except SourceDomainError as error:
                # ALP keeps the raised exception in its originating frame. Break
                # exception/traceback/frame cycles while the timed loop disables GC.
                reason, atomic = str(error), error.rejection_atomic
                error.__traceback__ = None
                if atomic is not True or not _text(reason) or count == 0:
                    raise ExecutionContractError(
                        "invalid or empty-input source rejection"
                    ) from None
                descriptors, chunk = _raw_descriptors(block_input)
                block.update(
                    encoding="RAW",
                    rejection={"type": "SOURCE_DOMAIN_ONLY", "reason": reason},
                    raw_descriptors=descriptors,
                )
            block.update(length=len(chunk), sha256=hashlib.sha256(chunk).hexdigest())
            chunks.append(chunk)
            blocks.append(block)
            payload_offset += len(chunk)
            if payload_offset > _MAX_PAYLOAD:
                raise OutputCapacityError("source-reject composite payload exceeds budget")
        header = self._header(routed, blocks)
        encoded_header = canonical_json_bytes(header)
        if len(encoded_header) > _MAX_HEADER:
            raise OutputCapacityError("source-reject composite metadata exceeds budget")
        stream = (
            _FRAME.pack(_MAGIC, len(encoded_header), payload_offset)
            + encoded_header
            + b"".join(chunks)
        )
        if len(stream) > len(destination):
            raise OutputCapacityError("source-reject composite destination too small")
        destination[: len(stream)] = stream
        ledger = AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            container_bits=(_FRAME.size + len(encoded_header)) * 8,
            value_bits=payload_offset * 8,
            accounting_method="EXACT_SOURCE_REJECT_COMPOSITE_V3",
        )
        self._artifact = EncodedArtifact(
            stream,
            len(stream),
            0,
            len(destination),
            hashlib.sha256(stream).hexdigest(),
            ledger,
            codec_telemetry={
                "schema_version": _SCHEMA,
                "recipe_id": self.recipe_id,
                "realized_artifact_recipe_id": stable_id(
                    "source-reject-realized-artifact", header, version="v3"
                ),
                "blocks": blocks,
                "raw_block_count": sum(b["encoding"] == "RAW" for b in blocks),
                "codec_block_count": sum(b["encoding"] == "CODEC" for b in blocks),
                "source_attempt_cost_boundary": (
                    "INCLUDED_IN_COMPOSITE_ENCODE_NO_SEPARATE_CLOCK_OBSERVATION"
                ),
            },
        )
        return len(stream)

    def finalize(self, destination: memoryview) -> int:
        self._ensure_open()
        del destination
        if self._artifact is None or self._finalized:
            raise ExecutionContractError(
                "source-reject composite finalize requires exactly one update"
            )
        self._finalized = True
        return 0

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        self._ensure_open()
        if (
            self._artifact is None
            or not self._finalized
            or self._artifact.stream != stream
            or self._artifact.ledger.canonical_raw_bits != routed.canonical_raw_bits
        ):
            raise ExecutionContractError("source-reject composite finalized accounting mismatch")
        return self._artifact.ledger

    def decompress(self, stream: bytes) -> DecodedOutput:
        self._ensure_open()
        if not isinstance(stream, bytes) or len(stream) < _FRAME.size:
            raise ExecutionContractError("truncated source-reject composite stream")
        magic, header_size, payload_size = _FRAME.unpack_from(stream)
        if (
            magic != _MAGIC
            or header_size > _MAX_HEADER
            or payload_size > _MAX_PAYLOAD
            or len(stream) != _FRAME.size + header_size + payload_size
        ):
            raise ExecutionContractError("invalid source-reject composite frame/length")
        raw_header = stream[_FRAME.size : _FRAME.size + header_size]
        try:
            header = json.loads(raw_header)
            canonical = canonical_json_bytes(header)
        except (ValueError, UnicodeError, TypeError, RecursionError) as error:
            raise ExecutionContractError("invalid source-reject composite header JSON") from error
        if (
            not isinstance(header, dict)
            or set(header) != _HEADER_FIELDS
            or canonical != raw_header
            or header["schema_version"] != _SCHEMA
            or header["child_key"] != self.adapter.child_key
            or header["child_adapter_id"] != self.adapter.child.adapter_id
            or header["parameters"] != self.parameters
            or header["recipe_id"] != self.recipe_id
            or not _integer(header["block_rows"], minimum=1, maximum=_BLOCK_ROWS)
            or header["block_rows"] != self.adapter.block_rows
            or header["fallback_policy"] != _POLICY
            or header["track"] != BenchmarkTrack.VALUE
            or not _integer(header["n"], maximum=16 * 1024 * 1024)
            or not _integer(header["m"], maximum=65535, minimum=1)
            or header["n"] * header["m"] > 16 * 1024 * 1024
            or not _sha(header["input_sha256"])
        ):
            raise ExecutionContractError("source-reject composite identity/domain mismatch")
        bits = _validate_buffers(header["buffers"], header["n"], header["m"])
        if not _integer(header["canonical_raw_bits"]) or bits != header["canonical_raw_bits"]:
            raise ExecutionContractError("source-reject composite original accounting mismatch")
        blocks = header["blocks"]
        count = max(1, (header["n"] + self.adapter.block_rows - 1) // self.adapter.block_rows)
        if not isinstance(blocks, list) or len(blocks) != count:
            raise ExecutionContractError("source-reject composite block coverage mismatch")
        payload, expected_start, expected_offset = stream[_FRAME.size + header_size :], 0, 0
        # Validate every block before original-object allocation or child calls.
        validated = []
        for block in blocks:
            wanted_count = min(self.adapter.block_rows, header["n"] - expected_start)
            if (
                not isinstance(block, dict)
                or set(block) != _BLOCK_FIELDS
                or not _integer(block["start"])
                or block["start"] != expected_start
                or not _integer(block["count"])
                or block["count"] != wanted_count
                or not _integer(block["offset"], maximum=payload_size)
                or block["offset"] != expected_offset
                or not _integer(block["length"], maximum=payload_size - expected_offset)
                or not _sha(block["sha256"])
                or not _sha(block["input_sha256"])
                or block["child_key"] != self.adapter.child_key
                or block["parameters"] != self.parameters
                or not isinstance(block["encoding"], str)
                or block["encoding"] not in {"CODEC", "RAW"}
            ):
                raise ExecutionContractError("invalid source-reject composite block metadata")
            chunk = payload[expected_offset : expected_offset + block["length"]]
            if hashlib.sha256(chunk).hexdigest() != block["sha256"]:
                raise ExecutionContractError("source-reject composite block digest mismatch")
            expected = [
                {
                    **item,
                    "shape": [wanted_count, *item["shape"][1:]],
                    "logical_bits": math.prod([wanted_count, *item["shape"][1:]])
                    * np.dtype(item["dtype"]).itemsize
                    * 8,
                }
                for item in header["buffers"]
            ]
            if block["encoding"] == "CODEC":
                if block["rejection"] is not None or block["raw_descriptors"] is not None:
                    raise ExecutionContractError("CODEC block contains RAW rejection metadata")
                _ledger(
                    block["child_ledger"],
                    raw_bits=sum(i["logical_bits"] for i in expected),
                    length=len(chunk),
                )
            else:
                rejection, descriptors = block["rejection"], block["raw_descriptors"]
                if (
                    wanted_count == 0
                    or block["child_ledger"] is not None
                    or not isinstance(rejection, dict)
                    or set(rejection) != {"type", "reason"}
                    or rejection["type"] != "SOURCE_DOMAIN_ONLY"
                    or not _text(rejection["reason"])
                    or not isinstance(descriptors, list)
                    or len(descriptors) != len(expected)
                ):
                    raise ExecutionContractError("invalid RAW source-rejection metadata")
                raw_offset = 0
                for descriptor, wanted in zip(descriptors, expected, strict=True):
                    if (
                        not isinstance(descriptor, dict)
                        or set(descriptor) != _RAW_FIELDS
                        or any(descriptor[key] != wanted[key] for key in _BUFFER_FIELDS)
                        or not _integer(descriptor["offset"])
                        or descriptor["offset"] != raw_offset
                        or not _integer(descriptor["length"])
                        or descriptor["length"] != wanted["logical_bits"] // 8
                        or descriptor["length"] > len(chunk) - raw_offset
                        or not _sha(descriptor["sha256"])
                    ):
                        raise ExecutionContractError("invalid RAW buffer descriptor/coverage")
                    data = chunk[raw_offset : raw_offset + descriptor["length"]]
                    if hashlib.sha256(data).hexdigest() != descriptor["sha256"]:
                        raise ExecutionContractError("source-reject composite raw digest mismatch")
                    raw_offset += descriptor["length"]
                if raw_offset != len(chunk):
                    raise ExecutionContractError("RAW payload contains uncovered bytes")
            validated.append((block, expected, chunk))
            expected_start += wanted_count
            expected_offset += block["length"]
        if expected_start != header["n"] or expected_offset != len(payload):
            raise ExecutionContractError("source-reject composite object/payload coverage mismatch")
        output = [np.empty(tuple(item["shape"]), dtype=item["dtype"]) for item in header["buffers"]]
        for block, expected, chunk in validated:
            if block["encoding"] == "CODEC":
                child_session = self.adapter.child.create_session(self.parameters)
                try:
                    decoded = child_session.decompress(chunk)
                finally:
                    child_session.close()
                if not isinstance(decoded, DecodedOutput):
                    raise ExecutionContractError("child returned invalid decoded output")
                restored = decoded.buffers
            else:
                restored = []
                for descriptor, wanted in zip(block["raw_descriptors"], expected, strict=True):
                    data = chunk[descriptor["offset"] : descriptor["offset"] + descriptor["length"]]
                    array = np.frombuffer(data, dtype=wanted["dtype"]).reshape(
                        tuple(wanted["shape"])
                    )
                    restored.append(LogicalBuffer(wanted["name"], array, wanted["logical_bits"]))
            if len(restored) != len(expected):
                raise ExecutionContractError(
                    "source-reject composite decoded buffer count mismatch"
                )
            for item, wanted in zip(restored, expected, strict=True):
                if (
                    not isinstance(item, LogicalBuffer)
                    or item.name != wanted["name"]
                    or item.array.dtype.str != wanted["dtype"]
                    or list(item.array.shape) != wanted["shape"]
                    or item.logical_bits != wanted["logical_bits"]
                ):
                    raise ExecutionContractError(
                        "source-reject composite decoded buffer identity mismatch"
                    )
            if hash_logical_buffers(tuple(restored)) != block["input_sha256"]:
                raise ExecutionContractError("source-reject composite restored block hash mismatch")
            for target, item in zip(output, restored, strict=True):
                target[block["start"] : block["start"] + block["count"]] = item.array
        result = tuple(
            LogicalBuffer(item["name"], array, item["logical_bits"])
            for item, array in zip(header["buffers"], output, strict=True)
        )
        if hash_logical_buffers(result) != header["input_sha256"]:
            raise ExecutionContractError("source-reject composite restored object hash mismatch")
        for item in result:
            item.array.flags.writeable = False
        return DecodedOutput(result)

    def close(self) -> None:
        self._closed = True
        self._artifact = None
