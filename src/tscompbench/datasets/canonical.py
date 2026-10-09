from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import numpy as np

from tscompbench.ids import canonical_json_bytes

from .models import CanonicalDataset, DatasetContractError

MAGIC = b"TSCB2\x00\x00\x00"
FORMAT_MAJOR = 1
FORMAT_MINOR = 0
_FILE_HEADER = struct.Struct("<8sHHQI")
_BUFFER_HEADER = struct.Struct("<HQ")
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_BUFFERS = 100_000


def semantic_content_sha256(metadata: dict[str, object]) -> str:
    """Transport-independent identity; physical strides and embedded IDs are excluded.

    Payload hashes are verified by read_canonical before this fingerprint is used.
    This is a new identity policy, not a reinterpretation of legacy content IDs.
    """
    logical = json.loads(json.dumps(metadata["logical_descriptor"]))
    for column in logical["value_columns"]:
        column.pop("strides", None)
    payload = {
        "policy": "tscb.dataset-content.v1",
        "logical": logical,
        "buffers": [
            {key: item[key] for key in ("name", "dtype", "shape", "logical_bits", "payload_sha256")}
            for item in metadata["buffers"]
        ],
    }
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _validate_metadata(metadata: object, buffer_count: int) -> list[dict[str, object]]:
    if not isinstance(metadata, dict) or metadata.get("format") != "tscb-canonical-v1":
        raise DatasetContractError("invalid canonical metadata root/format")
    descriptors = metadata.get("buffers")
    if not isinstance(descriptors, list) or len(descriptors) != buffer_count:
        raise DatasetContractError("canonical header buffer count does not match metadata")
    names: set[str] = set()
    totals = {"timestamp_raw_bits": 0, "value_raw_bits": 0, "validity_raw_bits": 0}
    for item in descriptors:
        if not isinstance(item, dict):
            raise DatasetContractError("invalid canonical buffer descriptor")
        name, shape, dtype_text = item.get("name"), item.get("shape"), item.get("dtype")
        if not isinstance(name, str) or name in names:
            raise DatasetContractError("duplicate/invalid canonical buffer name")
        names.add(name)
        if (
            not isinstance(shape, list)
            or not shape
            or len(shape) > 32
            or any(type(n) is not int or n < 0 or n > 2**63 - 1 for n in shape)
        ):
            raise DatasetContractError("invalid canonical buffer shape")
        count = math.prod(shape)
        if dtype_text == "bitmap-lsb0":
            if name != "validity":
                raise DatasetContractError("bitmap is only valid for validity")
            bits = count
            payload_bytes = (bits + 7) // 8
        else:
            try:
                dtype = np.dtype(dtype_text)
            except (TypeError, ValueError) as error:
                raise DatasetContractError("invalid canonical dtype") from error
            if (
                dtype.str != dtype_text
                or dtype.kind not in "iuf"
                or dtype.itemsize not in (1, 2, 4, 8)
                or dtype.byteorder == ">"
            ):
                raise DatasetContractError(
                    "canonical requires primitive little-endian numeric dtype"
                )
            bits = count * dtype.itemsize * 8
            payload_bytes = bits // 8
        if (
            type(item.get("logical_bits")) is not int
            or item["logical_bits"] != bits
            or item.get("payload_bytes") != payload_bytes
        ):
            raise DatasetContractError("canonical dtype/shape/size mismatch")
        if name == "timestamp":
            if dtype_text != "<i8" or len(shape) != 1:
                raise DatasetContractError("canonical timestamp must be rank-1 int64")
            totals["timestamp_raw_bits"] += bits
        elif name == "validity":
            if dtype_text != "bitmap-lsb0":
                raise DatasetContractError("canonical validity must use bitmap-lsb0")
            totals["validity_raw_bits"] += bits
        elif name.startswith("value/"):
            totals["value_raw_bits"] += bits
        else:
            raise DatasetContractError("unknown canonical buffer role")
    logical = metadata.get("logical_descriptor")
    if (
        not isinstance(logical, dict)
        or type(logical.get("n_rows")) is not int
        or logical["n_rows"] < 0
    ):
        raise DatasetContractError("invalid canonical logical row count")
    columns = logical.get("value_columns")
    value_descriptors = [item for item in descriptors if item["name"].startswith("value/")]
    if not isinstance(columns, list) or not columns or len(columns) != len(value_descriptors):
        raise DatasetContractError("canonical logical value columns mismatch")
    expected_names = [f"value/{i:06d}" for i in range(len(columns))]
    if [item["name"] for item in value_descriptors] != expected_names:
        raise DatasetContractError("canonical value order mismatch")
    for column, item in zip(columns, value_descriptors, strict=True):
        if (
            not isinstance(column, dict)
            or column.get("dtype") != item["dtype"]
            or column.get("shape") != item["shape"]
            or item["shape"][0] != logical["n_rows"]
        ):
            raise DatasetContractError("canonical logical/physical value descriptor mismatch")
        if not all(
            isinstance(column.get(k), str)
            for k in ("name", "display_name", "unit", "entity", "feature")
        ):
            raise DatasetContractError("canonical value semantics missing")
    shape = logical.get("value_shape")
    valid_shapes = [value_descriptors[0]["shape"]] if len(columns) == 1 else []
    if all(len(item["shape"]) == 1 for item in value_descriptors):
        valid_shapes.append([logical["n_rows"], len(columns)])
    if shape not in valid_shapes:
        raise DatasetContractError("canonical logical value shape mismatch")
    timestamp = logical.get("timestamp")
    if not isinstance(timestamp, dict) or timestamp.get("present") is not ("timestamp" in names):
        raise DatasetContractError("canonical timestamp presence mismatch")
    for item in descriptors:
        if item["name"] == "timestamp" and item["shape"] != [logical["n_rows"]]:
            raise DatasetContractError("canonical timestamp row count mismatch")
        if item["name"] == "validity":
            validity_shape = logical.get("validity_shape")
            expected_shape = (
                [logical["n_rows"]]
                if validity_shape == "ROW"
                else shape
                if validity_shape == "CELL"
                else None
            )
            if item["shape"] != expected_shape:
                raise DatasetContractError("canonical validity shape mismatch")
    if (logical.get("validity_shape") == "NONE") != ("validity" not in names):
        raise DatasetContractError("canonical validity presence mismatch")
    accounting = metadata.get("accounting")
    totals["canonical_raw_bits"] = sum(totals.values())
    if not isinstance(accounting, dict) or any(
        type(accounting.get(k)) is not int or accounting[k] != n for k, n in totals.items()
    ):
        raise DatasetContractError("canonical accounting disagrees with payloads")
    return descriptors


@dataclass(frozen=True)
class CanonicalArtifact:
    path: Path
    sha256: str
    metadata: dict[str, object]
    buffers: dict[str, bytes]


def _buffer_payload(name: str, array: np.ndarray[object]) -> tuple[bytes, dict[str, object]]:
    if name == "validity":
        flattened = np.asarray(array, dtype=np.bool_).reshape(-1)
        payload = np.packbits(flattened, bitorder="little").tobytes()
        dtype = "bitmap-lsb0"
        logical_bits = int(flattened.size)
    else:
        if array.dtype.byteorder == ">" or (array.dtype.byteorder == "=" and not np.little_endian):
            raise DatasetContractError(f"canonical buffer {name} is not little-endian")
        payload = array.tobytes(order="C")
        dtype = array.dtype.str
        logical_bits = int(array.size * array.itemsize * 8)
    descriptor: dict[str, object] = {
        "name": name,
        "dtype": dtype,
        "shape": list(array.shape),
        "logical_bits": logical_bits,
        "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }
    return payload, descriptor


def write_canonical(dataset: CanonicalDataset, path: Path) -> CanonicalArtifact:
    """Write an atomic, sequential, little-endian cross-language canonical stream."""

    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payloads: list[tuple[str, bytes]] = []
    descriptors: list[dict[str, object]] = []
    for name, array in dataset.named_arrays():
        payload, descriptor = _buffer_payload(name, array)
        payloads.append((name, payload))
        descriptors.append(descriptor)
    metadata: dict[str, object] = {
        "format": "tscb-canonical-v1",
        "dataset_id": dataset.dataset_id,
        "dataset_content_sha256": dataset.content_sha256(),
        "logical_descriptor": dataset.logical_descriptor,
        "physical_descriptors": list(dataset.physical_descriptors),
        "accounting": {
            "timestamp_raw_bits": dataset.timestamp_raw_bits,
            "value_raw_bits": dataset.value_raw_bits,
            "validity_raw_bits": dataset.validity_raw_bits,
            "canonical_raw_bits": dataset.canonical_raw_bits,
            "source_file_bytes_provenance_only": dataset.manifest.document["file"]["bytes"],
        },
        "buffers": descriptors,
    }
    metadata_bytes = canonical_json_bytes(metadata)

    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            handle.write(
                _FILE_HEADER.pack(
                    MAGIC,
                    FORMAT_MAJOR,
                    FORMAT_MINOR,
                    len(metadata_bytes),
                    len(payloads),
                )
            )
            handle.write(metadata_bytes)
            for name, payload in payloads:
                name_bytes = name.encode("utf-8")
                if len(name_bytes) > 65_535:
                    raise DatasetContractError("canonical buffer name is too long")
                handle.write(_BUFFER_HEADER.pack(len(name_bytes), len(payload)))
                handle.write(name_bytes)
                handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    return read_canonical(path, include_buffers=False)


def _read_exact(handle: BinaryIO, length: int) -> bytes:
    # Check before allocating, even for malicious 64-bit lengths.
    if length < 0 or length > os.fstat(handle.fileno()).st_size - handle.tell():
        raise DatasetContractError("truncated canonical artifact")
    value = handle.read(length)
    if len(value) != length:
        raise DatasetContractError("truncated canonical artifact")
    return value


def read_canonical(path: Path, *, include_buffers: bool = True) -> CanonicalArtifact:
    path = path.resolve()
    digest = hashlib.sha256()
    buffers: dict[str, bytes] = {}
    with path.open("rb") as handle:
        header_bytes = _read_exact(handle, _FILE_HEADER.size)
        digest.update(header_bytes)
        magic, major, minor, metadata_length, buffer_count = _FILE_HEADER.unpack(header_bytes)
        if magic != MAGIC or (major, minor) != (FORMAT_MAJOR, FORMAT_MINOR):
            raise DatasetContractError("unsupported canonical artifact header")
        if metadata_length > MAX_METADATA_BYTES or buffer_count > MAX_BUFFERS:
            raise DatasetContractError("canonical metadata/buffer count exceeds reader limits")
        metadata_bytes = _read_exact(handle, metadata_length)
        digest.update(metadata_bytes)
        try:
            metadata = json.loads(metadata_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DatasetContractError("invalid canonical metadata JSON") from error
        if canonical_json_bytes(metadata) != metadata_bytes:
            raise DatasetContractError("canonical metadata is not canonical JSON")
        buffer_descriptors = _validate_metadata(metadata, buffer_count)
        seen_names: set[str] = set()
        for descriptor in buffer_descriptors:
            record_header = _read_exact(handle, _BUFFER_HEADER.size)
            digest.update(record_header)
            name_length, payload_length = _BUFFER_HEADER.unpack(record_header)
            name_bytes = _read_exact(handle, name_length)
            digest.update(name_bytes)
            try:
                name = name_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise DatasetContractError("canonical buffer name is not UTF-8") from error
            if name != descriptor.get("name"):
                raise DatasetContractError("canonical buffer order/name mismatch")
            if payload_length != descriptor.get("payload_bytes"):
                raise DatasetContractError("canonical buffer size mismatch")
            payload_digest = hashlib.sha256()
            remaining = payload_length
            chunks = []
            last_byte = 0
            while remaining:
                chunk = _read_exact(handle, min(remaining, 1024 * 1024))
                digest.update(chunk)
                payload_digest.update(chunk)
                last_byte = chunk[-1]
                if include_buffers:
                    chunks.append(chunk)
                remaining -= len(chunk)
            if payload_digest.hexdigest() != descriptor.get("payload_sha256"):
                raise DatasetContractError("canonical buffer hash mismatch")
            if (
                descriptor["dtype"] == "bitmap-lsb0"
                and descriptor["logical_bits"] % 8
                and last_byte >> (descriptor["logical_bits"] % 8)
            ):
                raise DatasetContractError("canonical validity has nonzero padding bits")
            if name in seen_names:
                raise DatasetContractError("duplicate canonical buffer name")
            seen_names.add(name)
            if include_buffers:
                buffers[name] = b"".join(chunks)
        if handle.read(1):
            raise DatasetContractError("canonical artifact has undeclared trailing bytes")
    return CanonicalArtifact(
        path=path,
        sha256=digest.hexdigest(),
        metadata=metadata,
        buffers=buffers,
    )
