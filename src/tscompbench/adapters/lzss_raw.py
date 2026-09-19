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

from .native_timing import NativeTimingProbe

_ABI_VERSION = 1
_STATUS_OK = 0
_STATUS_DST_TOO_SMALL = 3
_DTYPE_BYTES = 11
_OWNERSHIP_BORROWED = 0
_MAX_RANK = 8
_PREFIX = struct.Struct("<8sI")
_MAGIC = b"TSCBLZS\x00"


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
                f"cannot load LZSS adapter artifact {path}: {error}"
            ) from error
        self._bind()
        if int(self.library.tscb_get_abi_version()) != _ABI_VERSION:
            raise ExecutionContractError("LZSS adapter ABI version mismatch")
        manifest_pointer = ctypes.c_char_p()
        manifest_length = ctypes.c_uint64()
        status = int(
            self.library.tscb_get_manifest_json(
                ctypes.byref(manifest_pointer), ctypes.byref(manifest_length)
            )
        )
        if status != _STATUS_OK:
            raise ExecutionContractError(
                "LZSS adapter failed to expose its native manifest"
            )
        manifest = json.loads(ctypes.string_at(manifest_pointer, manifest_length.value))
        if manifest.get("algorithm") != "lzss-raw":
            raise ExecutionContractError("loaded C ABI artifact is not the LZSS adapter")
        if (
            manifest.get("dictionary") != "NONE"
            or manifest.get("stream") != "LZSS_EI10_EJ4_C32"
            or manifest.get("checksum") != "NONE"
            or manifest.get("threading") != "SINGLE_THREAD"
        ):
            raise ExecutionContractError(
                "LZSS artifact violates the registered execution mode"
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
class LzssRawAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> LzssRawSession:
        return LzssRawSession(self.library_path, parameters)


class LzssRawSession:
    def __init__(self, library_path: Path, parameters: dict[str, Any]):
        self._native = _NativeLibrary(library_path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes(
            {
                "ei": parameters.get("ei", 10),
                "ej": parameters.get("ej", 4),
                "initial_byte": parameters.get("initial_byte", 32),
            }
        )
        status = int(
            self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle))
        )
        if status != _STATUS_OK or not self._handle.value:
            raise ExecutionContractError(
                f"native LZSS adapter create failed with status {status}"
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
                "schema_version": "tscb.lzss-raw-container.v1",
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
            raise ExecutionContractError("compress_update may be called once per LZSS")
        header = self._descriptor_header(routed)
        preamble = _PREFIX.pack(_MAGIC, len(header)) + header
        if len(destination) < len(preamble):
            raise OutputCapacityError("destination cannot hold the LZSS container header")
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
            raise ExecutionContractError("truncated LZSS container")
        magic, header_length = _PREFIX.unpack_from(stream)
        if magic != _MAGIC:
            raise ExecutionContractError("invalid LZSS container magic")
        header_end = _PREFIX.size + header_length
        if header_end > len(stream):
            raise ExecutionContractError("truncated LZSS container metadata")
        try:
            header = json.loads(stream[_PREFIX.size : header_end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExecutionContractError("invalid LZSS container metadata") from error
        if not isinstance(header, dict):
            raise ExecutionContractError("invalid LZSS metadata object")
        if header.get("schema_version") != "tscb.lzss-raw-container.v1":
            raise ExecutionContractError("unsupported LZSS container version")
        return header, stream[header_end:]

    @staticmethod
    def _inspect_lzss_stream(stream: bytes, expected_bytes: int) -> dict[str, int]:
        if expected_bytes < 0 or expected_bytes > 0xFFFFFFFF:
            raise ExecutionContractError("LZSS decoded length exceeds registered limit")
        bit = 0
        produced = 0

        def read(count: int) -> int:
            nonlocal bit
            if bit + count > len(stream) * 8:
                raise ExecutionContractError("truncated LZSS token")
            value = 0
            for _ in range(count):
                value = (value << 1) | ((stream[bit // 8] >> (7 - bit % 8)) & 1)
                bit += 1
            return value

        while produced < expected_bytes:
            literal = read(1)
            token = read(8 if literal else 14)
            produced += 1 if literal else (token & 15) + 2
            if produced > expected_bytes:
                raise ExecutionContractError("LZSS token exceeds decoded length")
        padding = len(stream) * 8 - bit
        if padding > 7 or read(padding) != 0:
            raise ExecutionContractError("LZSS trailing bytes or nonzero padding")
        return {"payload_bits": bit - padding, "padding_bits": padding}

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("accounting before finalize is forbidden")
        header, xz_stream = self._parse_container(stream)
        if canonical_json_bytes(header) != self._header:
            raise ExecutionContractError(
                "LZSS descriptor metadata changed after compression"
            )
        parts = self._inspect_lzss_stream(
            xz_stream, sum(item.array.nbytes for item in routed.buffers)
        )
        components: dict[str, int] = {
            "metadata_bits": len(self._header) * 8,
            "container_bits": _PREFIX.size * 8,
            "padding_bits": parts["padding_bits"],
        }
        has_validity = any(item.name == "validity" for item in routed.buffers)
        if routed.track is BenchmarkTrack.TIMESTAMP:
            components["timestamp_bits"] = parts["payload_bits"]
        elif routed.track is BenchmarkTrack.VALUE and not has_validity:
            components["value_bits"] = parts["payload_bits"]
        else:
            components["unallocated_shared_bits"] = parts["payload_bits"]
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="EXACT_TSCB_LZSS_TOKEN_BITS_AND_ZERO_PADDING",
            **components,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        header, frame = self._parse_container(stream)
        descriptors = header.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("LZSS container has no buffer descriptors")
        output_bytes = 0
        names: set[str] = set()
        for item in descriptors:
            try:
                dtype = np.dtype(item["dtype"])
                shape = item["shape"]
                length = item["payload_bytes"]
                if (dtype.str not in {"<i8", "<i4", "<i2", "|i1", "<u8", "<u4",
                                      "<u2", "|u1", "<f8", "<f4"}
                        or not isinstance(shape, list) or not 1 <= len(shape) <= 4
                        or any(type(n) is not int or n < 0 for n in shape)
                        or type(length) is not int or length < 0
                        or type(item["logical_bits"]) is not int
                        or item["logical_bits"] != length * 8
                        or not isinstance(item["name"], str) or item["name"] in names):
                    raise ValueError("descriptor outside registered contract")
                size = dtype.itemsize
                for n in shape:
                    size *= n
                if size != length:
                    raise ValueError("shape/length mismatch")
                output_bytes += length
                names.add(item["name"])
            except (KeyError, ValueError, TypeError) as error:
                raise ExecutionContractError("invalid LZSS buffer descriptor") from error
        self._inspect_lzss_stream(frame, output_bytes)
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
            raise ExecutionContractError("LZSS decoded byte count does not match metadata")
        payload = memoryview(output_storage)[:output_bytes]
        cursor = 0
        decoded: list[LogicalBuffer] = []
        for descriptor in descriptors:
            length = int(descriptor["payload_bytes"])
            dtype = np.dtype(str(descriptor["dtype"]))
            shape = tuple(int(value) for value in descriptor["shape"])
            expected = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
            if expected != length or cursor + length > output_bytes:
                raise ExecutionContractError("LZSS descriptor shape/dtype is inconsistent")
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
            raise ExecutionContractError("LZSS container contains undeclared decoded bytes")
        return DecodedOutput(tuple(decoded))

    def close(self) -> None:
        if self._handle.value:
            status = int(self._native.library.tscb_destroy(self._handle))
            self._handle = ctypes.c_void_p()
            if status != _STATUS_OK:
                raise ExecutionContractError(
                    f"native LZSS adapter destroy failed ({status})"
                )
