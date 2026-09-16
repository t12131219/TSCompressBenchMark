from __future__ import annotations

import hashlib
import json
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
        metadata_bytes = _read_exact(handle, metadata_length)
        digest.update(metadata_bytes)
        try:
            metadata = json.loads(metadata_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DatasetContractError("invalid canonical metadata JSON") from error
        if canonical_json_bytes(metadata) != metadata_bytes:
            raise DatasetContractError("canonical metadata is not canonical JSON")
        buffer_descriptors = metadata.get("buffers")
        if not isinstance(buffer_descriptors, list):
            raise DatasetContractError("canonical metadata lacks buffer descriptors")
        if len(buffer_descriptors) != buffer_count:
            raise DatasetContractError("canonical header buffer count does not match metadata")
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
            payload = _read_exact(handle, payload_length)
            digest.update(payload)
            if name != descriptor.get("name"):
                raise DatasetContractError("canonical buffer order/name mismatch")
            if payload_length != descriptor.get("payload_bytes"):
                raise DatasetContractError("canonical buffer size mismatch")
            if hashlib.sha256(payload).hexdigest() != descriptor.get("payload_sha256"):
                raise DatasetContractError("canonical buffer hash mismatch")
            if name in buffers:
                raise DatasetContractError("duplicate canonical buffer name")
            if include_buffers:
                buffers[name] = payload
        if handle.read(1):
            raise DatasetContractError("canonical artifact has undeclared trailing bytes")
    return CanonicalArtifact(
        path=path,
        sha256=digest.hexdigest(),
        metadata=metadata,
        buffers=buffers,
    )
