from __future__ import annotations

import ctypes
import json
import struct
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

_ABI_VERSION = 1
_STATUS_OK = 0
_STATUS_DST_TOO_SMALL = 3
_DTYPE_BYTES = 11
_OWNERSHIP_BORROWED = 0
_MAX_RANK = 8
_PREFIX = struct.Struct("<8sI")
_MAGIC = b"TSCBZST\x00"
_ZSTD_FRAME_MAGIC = 0xFD2FB528


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
                f"cannot load Zstd adapter artifact {path}: {error}"
            ) from error
        self._bind()
        if int(self.library.tscb_get_abi_version()) != _ABI_VERSION:
            raise ExecutionContractError("Zstd adapter ABI version mismatch")
        manifest_pointer = ctypes.c_char_p()
        manifest_length = ctypes.c_uint64()
        status = int(
            self.library.tscb_get_manifest_json(
                ctypes.byref(manifest_pointer), ctypes.byref(manifest_length)
            )
        )
        if status != _STATUS_OK:
            raise ExecutionContractError("Zstd adapter failed to expose its native manifest")
        manifest = json.loads(ctypes.string_at(manifest_pointer, manifest_length.value))
        if manifest.get("algorithm") != "zstd-frame":
            raise ExecutionContractError("loaded C ABI artifact is not the Zstd frame adapter")
        if manifest.get("dictionary") != "NONE" or manifest.get("threading") != "SINGLE_THREAD":
            raise ExecutionContractError("Zstd artifact violates the registered execution mode")

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
class ZstdFrameAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> ZstdFrameSession:
        return ZstdFrameSession(self.library_path, parameters)


class ZstdFrameSession:
    def __init__(self, library_path: Path, parameters: dict[str, Any]):
        self._native = _NativeLibrary(library_path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes(
            {
                "compression_level": int(parameters.get("compression_level", 3)),
                "content_checksum": bool(parameters.get("content_checksum", True)),
            }
        )
        status = int(
            self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle))
        )
        if status != _STATUS_OK or not self._handle.value:
            raise ExecutionContractError(f"native Zstd adapter create failed with status {status}")
        self._updated = False
        self._finalized = False
        self._header = b""

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
                "schema_version": "tscb.zstd-frame-container.v1",
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
            raise ExecutionContractError("compress_update may be called once per Zstd frame")
        header = self._descriptor_header(routed)
        preamble = _PREFIX.pack(_MAGIC, len(header)) + header
        if len(destination) < len(preamble):
            raise OutputCapacityError("destination cannot hold the Zstd container header")
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
            raise ExecutionContractError("truncated Zstd container")
        magic, header_length = _PREFIX.unpack_from(stream)
        if magic != _MAGIC:
            raise ExecutionContractError("invalid Zstd container magic")
        header_end = _PREFIX.size + header_length
        if header_end > len(stream):
            raise ExecutionContractError("truncated Zstd container metadata")
        try:
            header = json.loads(stream[_PREFIX.size : header_end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExecutionContractError("invalid Zstd container metadata") from error
        if header.get("schema_version") != "tscb.zstd-frame-container.v1":
            raise ExecutionContractError("unsupported Zstd container version")
        return header, stream[header_end:]

    @staticmethod
    def _inspect_frame(frame: bytes) -> tuple[int, int, int]:
        if len(frame) < 9 or int.from_bytes(frame[:4], "little") != _ZSTD_FRAME_MAGIC:
            raise ExecutionContractError("invalid Zstd frame")
        descriptor = frame[4]
        if descriptor & 0x18:
            raise ExecutionContractError("reserved Zstd frame header bits are set")
        content_size_flag = descriptor >> 6
        single_segment = bool(descriptor & 0x20)
        content_checksum = bool(descriptor & 0x04)
        dictionary_flag = descriptor & 0x03
        dictionary_lengths = (0, 1, 2, 4)
        content_size_lengths = (1 if single_segment else 0, 2, 4, 8)
        frame_header_bytes = (
            5
            + (0 if single_segment else 1)
            + dictionary_lengths[dictionary_flag]
            + content_size_lengths[content_size_flag]
        )
        if frame_header_bytes > len(frame):
            raise ExecutionContractError("truncated Zstd frame header")
        cursor = frame_header_bytes
        payload_bytes = 0
        container_bytes = frame_header_bytes
        while True:
            if cursor + 3 > len(frame):
                raise ExecutionContractError("truncated Zstd block header")
            block_header = int.from_bytes(frame[cursor : cursor + 3], "little")
            cursor += 3
            container_bytes += 3
            last_block = bool(block_header & 1)
            block_type = (block_header >> 1) & 0x03
            block_size = block_header >> 3
            if block_type == 3:
                raise ExecutionContractError("reserved Zstd block type")
            physical_payload = 1 if block_type == 1 else block_size
            if cursor + physical_payload > len(frame):
                raise ExecutionContractError("truncated Zstd block payload")
            cursor += physical_payload
            payload_bytes += physical_payload
            if last_block:
                break
        checksum_bytes = 4 if content_checksum else 0
        if cursor + checksum_bytes != len(frame):
            raise ExecutionContractError("truncated or trailing bytes in Zstd frame")
        return payload_bytes, container_bytes, checksum_bytes

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("accounting before finalize is forbidden")
        header, frame = self._parse_container(stream)
        if canonical_json_bytes(header) != self._header:
            raise ExecutionContractError("Zstd descriptor metadata changed after compression")
        payload_bytes, frame_container_bytes, checksum_bytes = self._inspect_frame(frame)
        components: dict[str, int] = {
            "metadata_bits": len(self._header) * 8,
            "container_bits": (_PREFIX.size + frame_container_bytes) * 8,
            "checksum_bits": checksum_bytes * 8,
        }
        has_validity = any(item.name == "validity" for item in routed.buffers)
        if routed.track is BenchmarkTrack.TIMESTAMP:
            components["timestamp_bits"] = payload_bytes * 8
        elif routed.track is BenchmarkTrack.VALUE and not has_validity:
            components["value_bits"] = payload_bytes * 8
        else:
            components["unallocated_shared_bits"] = payload_bytes * 8
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="EXACT_TSCB_CONTAINER_AND_ZSTD_FRAME_INSPECTION",
            **components,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        header, frame = self._parse_container(stream)
        descriptors = header.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("Zstd container has no buffer descriptors")
        output_bytes = sum(int(item["payload_bytes"]) for item in descriptors)
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
            raise ExecutionContractError("Zstd decoded byte count does not match metadata")
        payload = memoryview(output_storage)[:output_bytes]
        cursor = 0
        decoded: list[LogicalBuffer] = []
        for descriptor in descriptors:
            length = int(descriptor["payload_bytes"])
            dtype = np.dtype(str(descriptor["dtype"]))
            shape = tuple(int(value) for value in descriptor["shape"])
            expected = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
            if expected != length or cursor + length > output_bytes:
                raise ExecutionContractError("Zstd descriptor shape/dtype is inconsistent")
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
            raise ExecutionContractError("Zstd container contains undeclared decoded bytes")
        return DecodedOutput(tuple(decoded))

    def close(self) -> None:
        if self._handle.value:
            status = int(self._native.library.tscb_destroy(self._handle))
            self._handle = ctypes.c_void_p()
            if status != _STATUS_OK:
                raise ExecutionContractError(f"native Zstd adapter destroy failed ({status})")
