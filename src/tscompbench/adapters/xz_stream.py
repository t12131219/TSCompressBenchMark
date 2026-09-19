from __future__ import annotations

import ctypes
import json
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import (
    DecodedOutput,
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
)
from tscompbench.ids import canonical_json_bytes, stable_id

from .native_timing import NativeTimingProbe

_ABI_VERSION = 1
_STATUS_OK = 0
_STATUS_DST_TOO_SMALL = 3
_DTYPE_BYTES = 11
_OWNERSHIP_BORROWED = 0
_MAX_RANK = 8
_PREFIX = struct.Struct("<8sI")
_MAGIC = b"TSCBXZ0\x00"


class _Buffer(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("capacity_bytes", ctypes.c_uint64),
        ("used_bytes", ctypes.c_uint64),
        ("dtype", ctypes.c_uint32),
        ("rank", ctypes.c_uint32),
        ("shape", ctypes.c_uint64 * _MAX_RANK),
        ("strides_bytes", ctypes.c_int64 * _MAX_RANK),
        ("alignment_bytes", ctypes.c_uint64),
        ("ownership", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


def _alignment(address: int) -> int:
    value = 1
    while value < 64 and address % (value * 2) == 0:
        value *= 2
    return value


def _buffer(address: int, *, capacity: int, used: int) -> _Buffer:
    shape = (ctypes.c_uint64 * _MAX_RANK)()
    strides = (ctypes.c_int64 * _MAX_RANK)()
    shape[0] = used
    strides[0] = 1
    return _Buffer(
        ctypes.c_void_p(address),
        capacity,
        used,
        _DTYPE_BYTES,
        1,
        shape,
        strides,
        _alignment(address) if address > 1 else 1,
        _OWNERSHIP_BORROWED,
        0,
    )


class _NativeLibrary:
    def __init__(self, path: Path):
        try:
            self.library = ctypes.CDLL(str(path))
        except OSError as error:
            raise ExecutionContractError(
                f"cannot load xz LZMA2 adapter artifact {path}: {error}"
            ) from error
        self._bind()
        if int(self.library.tscb_get_abi_version()) != _ABI_VERSION:
            raise ExecutionContractError("xz LZMA2 adapter ABI version mismatch")
        manifest_pointer = ctypes.c_char_p()
        manifest_length = ctypes.c_uint64()
        status = int(
            self.library.tscb_get_manifest_json(
                ctypes.byref(manifest_pointer), ctypes.byref(manifest_length)
            )
        )
        if status != _STATUS_OK:
            raise ExecutionContractError(
                "xz LZMA2 adapter failed to expose its native manifest"
            )
        manifest = json.loads(ctypes.string_at(manifest_pointer, manifest_length.value))
        if manifest.get("algorithm") != "xz-stream":
            raise ExecutionContractError("loaded C ABI artifact is not the xz LZMA2 adapter")
        if (
            manifest.get("dictionary") != "NO_EXTERNAL_DICTIONARY"
            or manifest.get("stream") != "XZ_LZMA2"
            or manifest.get("data_check") != "NONE"
            or manifest.get("structural_check") != "CRC32"
            or manifest.get("threading") != "SINGLE_THREAD"
        ):
            raise ExecutionContractError(
                "xz LZMA2 artifact violates the registered execution mode"
            )

    def _bind(self) -> None:
        library = self.library
        library.tscb_get_abi_version.argtypes = []
        library.tscb_get_abi_version.restype = ctypes.c_uint32
        library.tscb_get_manifest_json.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        library.tscb_get_manifest_json.restype = ctypes.c_uint32
        library.tscb_create.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.tscb_create.restype = ctypes.c_uint32
        library.tscb_destroy.argtypes = [ctypes.c_void_p]
        library.tscb_destroy.restype = ctypes.c_uint32
        library.tscb_compress_bound.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        library.tscb_compress_bound.restype = ctypes.c_uint32
        library.tscb_compress.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(_Buffer),
        ]
        library.tscb_compress.restype = ctypes.c_uint32
        library.tscb_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer)]
        library.tscb_finalize.restype = ctypes.c_uint32
        library.tscb_decompress.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(_Buffer),
        ]
        library.tscb_decompress.restype = ctypes.c_uint32
        library.tscb_get_last_error.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        library.tscb_get_last_error.restype = ctypes.c_uint32


@dataclass(frozen=True)
class XzStreamAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> XzStreamSession:
        return XzStreamSession(self.library_path, parameters)


class XzStreamSession:
    def __init__(self, library_path: Path, parameters: dict[str, Any]):
        self._native = _NativeLibrary(library_path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes(
            {
                "compression_level": int(parameters.get("compression_level", 6)),
            }
        )
        status = int(
            self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle))
        )
        if status != _STATUS_OK or not self._handle.value:
            raise ExecutionContractError(
                f"native xz LZMA2 adapter create failed with status {status}"
            )
        self._updated = False
        self._finalized = False
        self._header = b""
        try:
            self._native_timing = NativeTimingProbe(
                self._native.library, self._handle,
                enabled=bool(parameters.get("native_timing", True)),
            )
        except Exception:
            self.close()
            raise

    def native_timing(self) -> tuple[int, int] | None:
        if not self._handle.value:
            raise ExecutionContractError("native timing queried after session close")
        return self._native_timing.read()

    def _last_error(self) -> str:
        pointer = ctypes.c_char_p()
        length = ctypes.c_uint64()
        status = int(
            self._native.library.tscb_get_last_error(
                self._handle, ctypes.byref(pointer), ctypes.byref(length)
            )
        )
        if status != _STATUS_OK or not pointer:
            return "native adapter supplied no error detail"
        return ctypes.string_at(pointer, length.value).decode("utf-8", errors="replace")

    def _check(self, status: int, operation: str) -> None:
        if status == _STATUS_OK:
            return
        if status == _STATUS_DST_TOO_SMALL:
            raise OutputCapacityError(f"{operation}: destination is too small")
        raise ExecutionContractError(f"{operation} failed ({status}): {self._last_error()}")

    @staticmethod
    def _descriptor_header(routed: RoutedInput) -> bytes:
        descriptors = [
            {
                "dtype": item.array.dtype.str,
                "logical_bits": item.logical_bits,
                "name": item.name,
                "payload_bytes": item.array.nbytes,
                "shape": list(item.array.shape),
            }
            for item in routed.buffers
        ]
        return canonical_json_bytes(
            {
                "buffers": descriptors,
                "schema_version": "tscb.xz-stream-container.v1",
                "segment_plan_id": routed.segment_plan_id,
                "track": routed.track,
            }
        )

    def _native_bound(self, payload_bytes: int) -> int:
        input_buffer = _buffer(1, capacity=payload_bytes, used=payload_bytes)
        bound = ctypes.c_uint64()
        status = int(
            self._native.library.tscb_compress_bound(
                self._handle, ctypes.byref(input_buffer), ctypes.byref(bound)
            )
        )
        self._check(status, "compress_bound")
        return int(bound.value)

    def output_bound(self, routed: RoutedInput) -> int:
        header = self._descriptor_header(routed)
        payload_bytes = sum(item.array.nbytes for item in routed.buffers)
        return _PREFIX.size + len(header) + self._native_bound(payload_bytes)

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("compress_update may be called once per xz LZMA2")
        header = self._descriptor_header(routed)
        preamble = _PREFIX.pack(_MAGIC, len(header)) + header
        if len(destination) < len(preamble):
            raise OutputCapacityError("destination cannot hold the xz LZMA2 container header")
        destination[: len(preamble)] = preamble
        payload = bytearray().join(item.array.tobytes(order="C") for item in routed.buffers)
        input_storage = payload if payload else bytearray(1)
        input_array = (ctypes.c_ubyte * len(input_storage)).from_buffer(input_storage)
        native_destination = destination[len(preamble) :]
        output_array = (ctypes.c_ubyte * len(native_destination)).from_buffer(native_destination)
        input_buffer = _buffer(
            ctypes.addressof(input_array), capacity=len(payload), used=len(payload)
        )
        output_buffer = _buffer(
            ctypes.addressof(output_array), capacity=len(native_destination), used=0
        )
        status = int(
            self._native.library.tscb_compress(
                self._handle, ctypes.byref(input_buffer), ctypes.byref(output_buffer)
            )
        )
        self._check(status, "compress_update")
        self._header = header
        self._updated = True
        return len(preamble) + int(output_buffer.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated:
            raise ExecutionContractError("finalize requires a preceding compress_update")
        if self._finalized:
            raise ExecutionContractError("repeated finalize is forbidden")
        output_array = (ctypes.c_ubyte * len(destination)).from_buffer(destination)
        output_buffer = _buffer(ctypes.addressof(output_array), capacity=len(destination), used=0)
        status = int(self._native.library.tscb_finalize(self._handle, ctypes.byref(output_buffer)))
        self._check(status, "finalize")
        self._finalized = True
        return int(output_buffer.used_bytes)

    @staticmethod
    def _parse_container(stream: bytes) -> tuple[dict[str, Any], bytes]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated xz LZMA2 container")
        magic, header_length = _PREFIX.unpack_from(stream)
        if magic != _MAGIC:
            raise ExecutionContractError("invalid xz LZMA2 container magic")
        header_end = _PREFIX.size + header_length
        if header_end > len(stream):
            raise ExecutionContractError("truncated xz LZMA2 container metadata")
        try:
            header = json.loads(stream[_PREFIX.size : header_end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExecutionContractError("invalid xz LZMA2 container metadata") from error
        if header.get("schema_version") != "tscb.xz-stream-container.v1":
            raise ExecutionContractError("unsupported xz LZMA2 container version")
        return header, stream[header_end:]

    @staticmethod
    def _inspect_xz_stream(stream: bytes, expected_bytes: int) -> dict[str, int]:
        def crc(data: bytes, observed: bytes) -> None:
            if zlib.crc32(data) & 0xFFFFFFFF != int.from_bytes(observed, "little"):
                raise ExecutionContractError("xz structural CRC32 mismatch")

        def vli(data: bytes, position: int) -> tuple[int, int]:
            value = 0
            for index in range(9):
                if position >= len(data):
                    raise ExecutionContractError("truncated xz VLI")
                byte = data[position]
                position += 1
                value |= (byte & 0x7F) << (7 * index)
                if not byte & 0x80:
                    if index and byte == 0:
                        raise ExecutionContractError("noncanonical xz VLI")
                    return value, position
            raise ExecutionContractError("xz VLI exceeds 63 bits")

        if len(stream) < 32 or len(stream) % 4 or stream[:6] != b"\xfd7zXZ\x00":
            raise ExecutionContractError("invalid or truncated xz stream")
        if stream[6:8] != b"\x00\x00" or stream[-4:-2] != stream[6:8]:
            raise ExecutionContractError("xz check/version variant is not registered")
        if stream[-2:] != b"YZ":
            raise ExecutionContractError("invalid xz footer magic")
        crc(stream[6:8], stream[8:12])
        crc(stream[-8:-2], stream[-12:-8])
        index_size = (int.from_bytes(stream[-8:-4], "little") + 1) * 4
        index_start = len(stream) - 12 - index_size
        if index_size < 8 or index_start < 12:
            raise ExecutionContractError("xz backward index size is invalid")
        index = stream[index_start:-12]
        crc(index[:-4], index[-4:])
        if index[0] != 0:
            raise ExecutionContractError("xz index indicator is invalid")
        records, position = vli(index[:-4], 1)
        if records not in (0, 1):
            raise ExecutionContractError("one-shot xz object must contain zero or one block")
        components = {
            "container_bytes": 16, "block_metadata_bytes": 0,
            "checksum_bytes": 12, "index_bytes": index_size - 4,
            "payload_bytes": 0, "padding_bytes": 0,
        }
        cursor = 12
        uncompressed_total = 0
        # The physical block layout is reconstructed from the finalized xz index.
        for _ in range(records):
            unpadded, position = vli(index[:-4], position)
            uncompressed, position = vli(index[:-4], position)
            if cursor >= index_start or stream[cursor] == 0:
                raise ExecutionContractError("xz index references a missing block")
            header_size = (stream[cursor] + 1) * 4
            physical_size = (unpadded + 3) & ~3
            if unpadded <= header_size or cursor + physical_size > index_start:
                raise ExecutionContractError("xz block size does not match the index")
            block_header = stream[cursor:cursor + header_size]
            crc(block_header[:-4], block_header[-4:])
            flags = block_header[1]
            if flags & 0x3F:
                raise ExecutionContractError("xz block must have exactly one LZMA2 filter")
            offset = 2
            if flags & 0x40:
                declared, offset = vli(block_header[:-4], offset)
                if declared != unpadded - header_size:
                    raise ExecutionContractError("xz block compressed-size field is inconsistent")
            if flags & 0x80:
                declared, offset = vli(block_header[:-4], offset)
                if declared != uncompressed:
                    raise ExecutionContractError("xz block decoded-size field is inconsistent")
            filter_id, offset = vli(block_header[:-4], offset)
            property_size, offset = vli(block_header[:-4], offset)
            if (filter_id != 0x21 or property_size != 1 or offset >= header_size - 4
                    or block_header[offset] > 40):
                raise ExecutionContractError("xz block is not the registered LZMA2 filter")
            if any(block_header[offset + 1:-4]) or any(
                stream[cursor + unpadded:cursor + physical_size]
            ):
                raise ExecutionContractError("xz header/block padding is nonzero")
            components["payload_bytes"] += unpadded - header_size
            components["block_metadata_bytes"] += header_size - 4
            components["checksum_bytes"] += 4
            components["padding_bytes"] += physical_size - unpadded
            cursor += physical_size
            uncompressed_total += uncompressed
        if (cursor != index_start or any(index[position:-4])
                or len(index[position:-4]) > 3 or uncompressed_total != expected_bytes):
            raise ExecutionContractError(
                "xz block/index coverage or decoded length is inconsistent"
            )
        if sum(components.values()) != len(stream):
            raise ExecutionContractError("xz component accounting does not conserve physical bytes")
        return components

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("accounting before finalize is forbidden")
        header, xz_stream = self._parse_container(stream)
        if canonical_json_bytes(header) != self._header:
            raise ExecutionContractError(
                "xz LZMA2 descriptor metadata changed after compression"
            )
        parts = self._inspect_xz_stream(
            xz_stream, sum(item.array.nbytes for item in routed.buffers)
        )
        components: dict[str, int] = {
            "metadata_bits": (len(self._header) + parts["block_metadata_bytes"]) * 8,
            "container_bits": (_PREFIX.size + parts["container_bytes"]) * 8,
            "checksum_bits": parts["checksum_bytes"] * 8,
            "index_bits": parts["index_bytes"] * 8,
            "padding_bits": parts["padding_bytes"] * 8,
        }
        has_validity = any(item.name == "validity" for item in routed.buffers)
        if routed.track is BenchmarkTrack.TIMESTAMP:
            components["timestamp_bits"] = parts["payload_bytes"] * 8
        elif routed.track is BenchmarkTrack.VALUE and not has_validity:
            components["value_bits"] = parts["payload_bytes"] * 8
        else:
            components["unallocated_shared_bits"] = parts["payload_bytes"] * 8
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="EXACT_TSCB_XZ_BLOCK_INDEX_STRUCTURAL_CRC_AND_LENGTH",
            **components,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        header, frame = self._parse_container(stream)
        descriptors = header.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("xz LZMA2 container has no buffer descriptors")
        output_bytes = sum(int(item["payload_bytes"]) for item in descriptors)
        self._inspect_xz_stream(frame, output_bytes)
        input_storage = bytearray(frame) if frame else bytearray(1)
        output_storage = bytearray(max(1, output_bytes))
        input_array = (ctypes.c_ubyte * len(input_storage)).from_buffer(input_storage)
        output_array = (ctypes.c_ubyte * len(output_storage)).from_buffer(output_storage)
        input_buffer = _buffer(ctypes.addressof(input_array), capacity=len(frame), used=len(frame))
        output_buffer = _buffer(ctypes.addressof(output_array), capacity=output_bytes, used=0)
        status = int(
            self._native.library.tscb_decompress(
                self._handle, ctypes.byref(input_buffer), ctypes.byref(output_buffer)
            )
        )
        self._check(status, "decompress")
        if int(output_buffer.used_bytes) != output_bytes:
            raise ExecutionContractError("xz LZMA2 decoded byte count does not match metadata")
        payload = memoryview(output_storage)[:output_bytes]
        cursor = 0
        decoded: list[LogicalBuffer] = []
        for descriptor in descriptors:
            length = int(descriptor["payload_bytes"])
            dtype = np.dtype(str(descriptor["dtype"]))
            shape = tuple(int(value) for value in descriptor["shape"])
            expected = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
            if expected != length or cursor + length > output_bytes:
                raise ExecutionContractError("xz LZMA2 descriptor shape/dtype is inconsistent")
            array = np.frombuffer(payload[cursor : cursor + length], dtype=dtype).copy()
            array = array.reshape(shape)
            array.flags.writeable = False
            decoded.append(
                LogicalBuffer(
                    name=str(descriptor["name"]),
                    array=array,
                    logical_bits=int(descriptor["logical_bits"]),
                )
            )
            cursor += length
        if cursor != output_bytes:
            raise ExecutionContractError("xz LZMA2 container contains undeclared decoded bytes")
        return DecodedOutput(tuple(decoded))

    def close(self) -> None:
        if self._handle.value:
            status = int(self._native.library.tscb_destroy(self._handle))
            self._handle = ctypes.c_void_p()
            if status != _STATUS_OK:
                raise ExecutionContractError(
                    f"native xz LZMA2 adapter destroy failed ({status})"
                )
