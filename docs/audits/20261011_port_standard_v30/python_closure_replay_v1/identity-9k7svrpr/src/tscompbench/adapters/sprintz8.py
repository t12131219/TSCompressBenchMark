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

from .lzsse8_raw import _Buffer, _buffer
from .native_timing import NativeTimingProbe

_PREFIX = struct.Struct("<8sI")
_MAGIC = {
    "sprintz-delta-u8": b"TSCBSD8\0",
    "sprintz-fire-u8": b"TSCBSF8\0",
}
_MAX = 131072


class _Library:
    def __init__(self, path: Path, algorithm: str):
        try:
            self.library = ctypes.CDLL(str(path))
        except OSError as exc:
            raise ExecutionContractError(f"cannot load Sprintz artifact: {exc}") from exc
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
        if lib.tscb_get_abi_version() != 1:
            raise ExecutionContractError("Sprintz ABI mismatch")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_manifest_json(ctypes.byref(pointer), ctypes.byref(length)):
            raise ExecutionContractError("Sprintz native manifest missing")
        manifest = json.loads(ctypes.string_at(pointer, length.value))
        if (manifest.get("algorithm") != algorithm
                or manifest.get("isa") != "AVX2_BMI2_LZCNT"
                or manifest.get("threading") != "SINGLE_THREAD"):
            raise ExecutionContractError("Sprintz binary does not match requested variant")


@dataclass(frozen=True)
class Sprintz8Adapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> Sprintz8Session:
        return Sprintz8Session(self.library_path, self.algorithm, parameters)


class Sprintz8Session:
    def __init__(self, library_path: Path, algorithm: str, parameters: dict[str, Any]):
        if (algorithm not in _MAGIC or parameters.get("isa", "AVX2_BMI2_LZCNT")
                != "AVX2_BMI2_LZCNT" or type(parameters.get("native_timing", True)) is not bool):
            raise ExecutionContractError("unregistered Sprintz execution parameters")
        self.algorithm = algorithm
        self._native = _Library(library_path, algorithm)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes({"algorithm": algorithm})
        status = self._native.library.tscb_create(
            config, len(config), ctypes.byref(self._handle)
        )
        if status or not self._handle.value:
            raise ExecutionContractError(f"Sprintz create failed ({status})")
        self._updated = self._finalized = False
        self._header = b""
        try:
            self._timing = NativeTimingProbe(
                self._native.library, self._handle,
                enabled=parameters.get("native_timing", True),
            )
        except Exception:
            self.close()
            raise

    def native_timing(self) -> tuple[int, int] | None:
        if not self._handle.value:
            raise ExecutionContractError("Sprintz timing queried after close")
        return self._timing.read()

    @staticmethod
    def _validate_routed(routed: RoutedInput) -> LogicalBuffer:
        if (routed.track is not BenchmarkTrack.VALUE or routed.m != 1
                or len(routed.buffers) != 1):
            raise ExecutionContractError("Sprintz u8 requires one VALUE channel")
        item = routed.buffers[0]
        if (item.array.dtype.str != "|u1" or item.array.ndim != 1
                or item.array.size != routed.n or routed.n > _MAX
                or item.logical_bits != item.array.nbytes * 8):
            raise ExecutionContractError("Sprintz u8 input shape/dtype is unsupported")
        return item

    def _descriptor(self, routed: RoutedInput) -> bytes:
        item = self._validate_routed(routed)
        return canonical_json_bytes({
            "schema_version": "tscb.sprintz-u8-container.v1",
            "algorithm": self.algorithm,
            "track": routed.track,
            "buffers": [{
                "name": item.name, "dtype": "|u1", "shape": [routed.n],
                "logical_bits": item.logical_bits, "payload_bytes": item.array.nbytes,
            }],
        })

    @staticmethod
    def _check(status: int, operation: str) -> None:
        if status == 3:
            raise OutputCapacityError(f"Sprintz {operation}: destination too small")
        if status:
            raise ExecutionContractError(f"Sprintz {operation} failed ({status})")

    def output_bound(self, routed: RoutedInput) -> int:
        item = self._validate_routed(routed)
        source = _buffer(1, capacity=item.array.nbytes, used=item.array.nbytes)
        bound = ctypes.c_uint64()
        self._check(self._native.library.tscb_compress_bound(
            self._handle, ctypes.byref(source), ctypes.byref(bound)
        ), "compress_bound")
        return _PREFIX.size + len(self._descriptor(routed)) + int(bound.value)

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("Sprintz update called twice")
        item = self._validate_routed(routed)
        header = self._descriptor(routed)
        preamble = _PREFIX.pack(_MAGIC[self.algorithm], len(header)) + header
        native_bound = 8 + 4 * routed.n + 64
        if len(destination) < len(preamble) + native_bound:
            raise OutputCapacityError("Sprintz container destination too small")
        destination[:len(preamble)] = preamble
        payload = bytearray(item.array.tobytes(order="C")) or bytearray(1)
        source_array = (ctypes.c_ubyte * len(payload)).from_buffer(payload)
        frame_view = destination[len(preamble):]
        frame_array = (ctypes.c_ubyte * len(frame_view)).from_buffer(frame_view)
        source = _buffer(ctypes.addressof(source_array), capacity=routed.n, used=routed.n)
        target = _buffer(ctypes.addressof(frame_array), capacity=len(frame_view), used=0)
        self._check(self._native.library.tscb_compress(
            self._handle, ctypes.byref(source), ctypes.byref(target)
        ), "compress")
        self._header = header
        self._updated = True
        return len(preamble) + int(target.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated or self._finalized:
            raise ExecutionContractError("Sprintz finalize requires one update")
        del destination
        target = _buffer(1, capacity=0, used=0)
        self._check(self._native.library.tscb_finalize(
            self._handle, ctypes.byref(target)
        ), "finalize")
        self._finalized = True
        return int(target.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict[str, Any], bytes]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated Sprintz container")
        magic, size = _PREFIX.unpack_from(stream)
        if (magic != _MAGIC[self.algorithm] or size > 4096
                or size > len(stream) - _PREFIX.size):
            raise ExecutionContractError("invalid Sprintz container prefix")
        header = stream[_PREFIX.size:_PREFIX.size + size]
        try:
            info = json.loads(header)
        except (UnicodeError, ValueError) as exc:
            raise ExecutionContractError("invalid Sprintz descriptor") from exc
        if (not isinstance(info, dict)
                or info.get("schema_version") != "tscb.sprintz-u8-container.v1"
                or info.get("algorithm") != self.algorithm
                or info.get("track") != BenchmarkTrack.VALUE):
            raise ExecutionContractError("Sprintz descriptor variant mismatch")
        descriptors = info.get("buffers")
        if not isinstance(descriptors, list) or len(descriptors) != 1:
            raise ExecutionContractError("Sprintz requires exactly one buffer")
        item = descriptors[0]
        if not isinstance(item, dict):
            raise ExecutionContractError("invalid Sprintz buffer descriptor")
        n = item.get("payload_bytes")
        if (type(n) is not int or n < 0 or n > _MAX or item.get("dtype") != "|u1"
                or item.get("shape") != [n] or item.get("logical_bits") != 8 * n
                or not isinstance(item.get("name"), str) or not item["name"]):
            raise ExecutionContractError("Sprintz decoded length/dtype mismatch")
        return header, item, stream[_PREFIX.size + size:]

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("Sprintz accounting before finalize")
        header, _, frame = self._parse(stream)
        if header != self._header or len(frame) < 8:
            raise ExecutionContractError("Sprintz stream descriptor mismatch")
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="EXACT_SPRINTZ_U8_RLE_AND_DESCRIPTOR_V1",
            metadata_bits=(len(header) + 8) * 8,
            container_bits=_PREFIX.size * 8,
            value_bits=(len(frame) - 8) * 8,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, item, frame = self._parse(stream)
        n = int(item["payload_bytes"])
        if len(frame) < 8 or len(frame) > 8 + 4 * n + 64:
            raise ExecutionContractError("invalid Sprintz frame length")
        source_store = bytearray(frame)
        dest_store = bytearray(max(1, n))
        source_array = (ctypes.c_ubyte * len(source_store)).from_buffer(source_store)
        dest_array = (ctypes.c_ubyte * len(dest_store)).from_buffer(dest_store)
        source = _buffer(ctypes.addressof(source_array), capacity=len(frame), used=len(frame))
        target = _buffer(ctypes.addressof(dest_array), capacity=n, used=0)
        self._check(self._native.library.tscb_decompress(
            self._handle, ctypes.byref(source), ctypes.byref(target)
        ), "decompress")
        if int(target.used_bytes) != n:
            raise ExecutionContractError("Sprintz decoded size mismatch")
        array = np.frombuffer(dest_store[:n], dtype=np.uint8).copy()
        array.flags.writeable = False
        return DecodedOutput((LogicalBuffer(item["name"], array, 8 * n),))

    def close(self) -> None:
        if self._handle.value:
            status = self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
            self._check(status, "destroy")
