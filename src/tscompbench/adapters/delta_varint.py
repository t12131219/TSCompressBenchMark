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

from .deflate_zlib import _Buffer
from .native_timing import NativeTimingProbe

_PREFIX = struct.Struct("<8sI")
_MAGIC = b"TSCBDV\x00\x00"
_OK = 0
_DST_TOO_SMALL = 3
_I64 = 7
_BYTES = 11
_MAX_RANK = 8


def _buffer(address: int, *, capacity: int, used: int, dtype: int) -> _Buffer:
    shape = (ctypes.c_uint64 * _MAX_RANK)()
    strides = (ctypes.c_int64 * _MAX_RANK)()
    itemsize = 8 if dtype == _I64 else 1
    shape[0] = capacity // itemsize
    strides[0] = itemsize
    return _Buffer(
        ctypes.c_void_p(address), capacity, used, dtype, 1, shape, strides,
        1, 0, 0
    )


class _Library:
    def __init__(self, path: Path):
        try:
            self.library = ctypes.CDLL(str(path))
        except OSError as error:
            raise ExecutionContractError(
                f"cannot load delta-varint adapter {path}: {error}"
            ) from error
        lib = self.library
        lib.tscb_get_abi_version.argtypes = []
        lib.tscb_get_abi_version.restype = ctypes.c_uint32
        lib.tscb_get_manifest_json.argtypes = [
            ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_uint64)
        ]
        lib.tscb_get_manifest_json.restype = ctypes.c_uint32
        lib.tscb_create.argtypes = [
            ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)
        ]
        lib.tscb_create.restype = ctypes.c_uint32
        lib.tscb_destroy.argtypes = [ctypes.c_void_p]
        lib.tscb_destroy.restype = ctypes.c_uint32
        lib.tscb_compress_bound.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(ctypes.c_uint64)
        ]
        lib.tscb_compress_bound.restype = ctypes.c_uint32
        for name in ("tscb_compress", "tscb_decompress"):
            function = getattr(lib, name)
            function.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(_Buffer)]
            function.restype = ctypes.c_uint32
        lib.tscb_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer)]
        lib.tscb_finalize.restype = ctypes.c_uint32
        lib.tscb_get_last_error.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_uint64)
        ]
        lib.tscb_get_last_error.restype = ctypes.c_uint32
        if int(lib.tscb_get_abi_version()) != 1:
            raise ExecutionContractError("delta-varint ABI version mismatch")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if int(lib.tscb_get_manifest_json(ctypes.byref(pointer), ctypes.byref(length))) != _OK:
            raise ExecutionContractError("delta-varint manifest unavailable")
        manifest = json.loads(ctypes.string_at(pointer, length.value))
        if manifest.get("algorithm") != "delta-varint":
            raise ExecutionContractError("wrong native algorithm loaded")


@dataclass(frozen=True)
class DeltaVarintAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> DeltaVarintSession:
        if parameters.get("isa", "SCALAR") != "SCALAR":
            raise ExecutionContractError("delta-varint only registers scalar execution")
        return DeltaVarintSession(self.library_path, parameters)


class DeltaVarintSession:
    def __init__(self, library_path: Path, parameters: dict[str, Any]):
        self._native = _Library(library_path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes({"isa": parameters.get("isa", "SCALAR")})
        status = int(
            self._native.library.tscb_create(
                config, len(config), ctypes.byref(self._handle)
            )
        )
        if status != _OK or not self._handle.value:
            raise ExecutionContractError(f"delta-varint create failed ({status})")
        self._updated = False
        self._finalized = False
        self._header = b""
        self._timing = NativeTimingProbe(
            self._native.library, self._handle,
            enabled=bool(parameters.get("native_timing", True)),
        )

    def native_timing(self) -> tuple[int, int] | None:
        return self._timing.read()

    @staticmethod
    def _header_for(routed: RoutedInput) -> bytes:
        if routed.track is not BenchmarkTrack.TIMESTAMP or len(routed.buffers) != 1:
            raise ExecutionContractError("delta-varint requires one timestamp buffer")
        item = routed.buffers[0]
        if (
            item.array.dtype != np.dtype("<i8")
            or item.array.ndim != 1
            or not item.array.flags.c_contiguous
        ):
            raise ExecutionContractError(
                "delta-varint requires a contiguous little-endian int64 timestamp vector"
            )
        return canonical_json_bytes({
            "schema_version": "tscb.delta-varint-container.v1",
            "track": routed.track,
            "count": int(item.array.size),
            "buffer": {
                "name": item.name, "dtype": item.array.dtype.str,
                "shape": list(item.array.shape), "logical_bits": item.logical_bits,
                "payload_bytes": item.array.nbytes,
            },
        })

    def _check(self, status: int, operation: str) -> None:
        if status == _OK:
            return
        if status == _DST_TOO_SMALL:
            raise OutputCapacityError(f"{operation}: destination too small")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        self._native.library.tscb_get_last_error(
            self._handle, ctypes.byref(pointer), ctypes.byref(length)
        )
        detail = (
            ctypes.string_at(pointer, length.value).decode("utf-8", errors="replace")
            if pointer else ""
        )
        raise ExecutionContractError(f"delta-varint {operation} failed ({status}): {detail}")

    def _payload(self, routed: RoutedInput) -> tuple[bytes, np.ndarray]:
        header = self._header_for(routed)
        return header, routed.buffers[0].array

    def output_bound(self, routed: RoutedInput) -> int:
        header, array = self._payload(routed)
        storage = array if array.size else np.zeros(1, dtype="<i8")
        source = _buffer(storage.ctypes.data, capacity=array.nbytes, used=array.nbytes, dtype=_I64)
        bound = ctypes.c_uint64()
        self._check(self._native.library.tscb_compress_bound(
            self._handle, ctypes.byref(source), ctypes.byref(bound)
        ), "compress_bound")
        return _PREFIX.size + len(header) + int(bound.value)

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("delta-varint update called twice")
        header, array = self._payload(routed)
        preamble = _PREFIX.pack(_MAGIC, len(header)) + header
        if len(destination) < len(preamble):
            raise OutputCapacityError("delta-varint destination cannot hold descriptor")
        destination[:len(preamble)] = preamble
        storage = array if array.size else np.zeros(1, dtype="<i8")
        source = _buffer(storage.ctypes.data, capacity=array.nbytes, used=array.nbytes, dtype=_I64)
        target_view = destination[len(preamble):]
        if len(target_view) == 0:
            target_view = memoryview(bytearray(1))
        target = (ctypes.c_ubyte * len(target_view)).from_buffer(target_view)
        output = _buffer(ctypes.addressof(target), capacity=len(target_view), used=0, dtype=_BYTES)
        self._check(self._native.library.tscb_compress(
            self._handle, ctypes.byref(source), ctypes.byref(output)
        ), "compress")
        self._header = header
        self._updated = True
        return len(preamble) + int(output.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated or self._finalized:
            raise ExecutionContractError("delta-varint finalize lifecycle violation")
        storage = bytearray(max(1, len(destination)))
        output = (ctypes.c_ubyte * len(storage)).from_buffer(storage)
        buffer = _buffer(ctypes.addressof(output), capacity=len(storage), used=0, dtype=_BYTES)
        self._check(self._native.library.tscb_finalize(
            self._handle, ctypes.byref(buffer)
        ), "finalize")
        self._finalized = True
        return int(buffer.used_bytes)

    @staticmethod
    def _parse(stream: bytes) -> tuple[bytes, dict[str, Any], bytes]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated delta-varint container")
        magic, size = _PREFIX.unpack_from(stream)
        if magic != _MAGIC or size > len(stream) - _PREFIX.size:
            raise ExecutionContractError("invalid delta-varint container prefix")
        header = stream[_PREFIX.size:_PREFIX.size + size]
        try:
            descriptor = json.loads(header)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExecutionContractError("invalid delta-varint descriptor") from error
        if descriptor.get("schema_version") != "tscb.delta-varint-container.v1":
            raise ExecutionContractError("unsupported delta-varint container")
        return header, descriptor, stream[_PREFIX.size + size:]

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("accounting before finalize")
        header, _, payload = self._parse(stream)
        if header != self._header:
            raise ExecutionContractError("delta-varint descriptor changed")
        return AccountingLedger.create(
            track=BenchmarkTrack.TIMESTAMP,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            metadata_bits=len(header) * 8,
            container_bits=_PREFIX.size * 8,
            timestamp_bits=len(payload) * 8,
            accounting_method="EXACT_TSCB_DESCRIPTOR_PLUS_DELTA_VARINT_BYTES",
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, descriptor, payload = self._parse(stream)
        buffer_info = descriptor.get("buffer") or {}
        count = int(descriptor.get("count", -1))
        if (
            descriptor.get("track") != BenchmarkTrack.TIMESTAMP
            or count < 0
            or buffer_info.get("name") != "timestamp"
            or buffer_info.get("dtype") != "<i8"
            or buffer_info.get("shape") != [count]
            or int(buffer_info.get("logical_bits", -1)) != count * 64
            or int(buffer_info.get("payload_bytes", -1)) != count * 8
            or (count == 0 and payload)
            or (count > 0 and len(payload) < count * 2)
        ):
            raise ExecutionContractError("delta-varint descriptor count/size mismatch")
        input_storage = bytearray(payload) if payload else bytearray(1)
        input_array = (ctypes.c_ubyte * len(input_storage)).from_buffer(input_storage)
        output_array = np.empty(count, dtype="<i8")
        output = _buffer(output_array.ctypes.data, capacity=output_array.nbytes, used=0, dtype=_I64)
        source = _buffer(
            ctypes.addressof(input_array), capacity=len(payload),
            used=len(payload), dtype=_BYTES,
        )
        self._check(self._native.library.tscb_decompress(
            self._handle, ctypes.byref(source), ctypes.byref(output)
        ), "decompress")
        output_array.flags.writeable = False
        return DecodedOutput((LogicalBuffer(
            str(buffer_info["name"]), output_array, int(buffer_info["logical_bits"])
        ),))

    def close(self) -> None:
        if self._handle.value:
            status = int(self._native.library.tscb_destroy(self._handle))
            self._handle = ctypes.c_void_p()
            if status != _OK:
                raise ExecutionContractError(f"delta-varint destroy failed ({status})")
