from __future__ import annotations

import ctypes
import hashlib
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
    SourceDomainError,
)
from tscompbench.ids import canonical_json_bytes, stable_id

_KINDS = {
    "chimp": 1,
    "chimp128": 2,
    "elf-plus": 3,
    "self-star": 4,
    "prometheus-xor-chunk": 5,
    "elf": 6,
    "elf-star": 7,
}
_SOURCE_DOMAIN_REASONS = {
    "chimp": {"canonical NaN is END"},
    "chimp128": {"canonical NaN is END"},
    "elf": {
        "invalid source erasure scale",
        "original source recovery is not lossless",
        "source significance search does not terminate",
        "NaN is the source END marker",
    },
    "elf-plus": {
        "invalid source erasure scale",
        "NaN is the source END marker",
        "original source recovery is not lossless",
        "source rejects negative decimal scale",
        "source significance search does not terminate",
    },
    "elf-star": {
        "source rejects decimal scale",
        "source significance loop does not terminate",
        "source decimal recovery is not lossless",
        "NaN is END, outside lossless domain",
        "source beta symbol outside table",
    },
    "self-star": {
        "source rejects decimal scale",
        "source significance loop does not terminate",
        "source decimal recovery is not lossless for value",
        "NaN outside source lossless domain",
        "source beta symbol outside table",
    },
}
_PREFIX = struct.Struct("<8sI32s")
_INPUT = struct.Struct("<4sBBHIQ")
_FRAME = struct.Struct("<4sBBHIQQ")
_MAGIC = b"TSCBRW1\0"
_MAX_ELEMENTS = 16777216


class _Buffer(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("capacity_bytes", ctypes.c_uint64),
        ("used_bytes", ctypes.c_uint64),
        ("dtype", ctypes.c_uint32),
        ("rank", ctypes.c_uint32),
        ("shape", ctypes.c_uint64 * 8),
        ("strides_bytes", ctypes.c_int64 * 8),
        ("alignment_bytes", ctypes.c_uint64),
        ("ownership", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32),
    ]


def _buffer(address: int, capacity: int, used: int = 0) -> _Buffer:
    shape, strides = (ctypes.c_uint64 * 8)(), (ctypes.c_int64 * 8)()
    shape[0], strides[0] = used, 1
    return _Buffer(address, capacity, used, 11, 1, shape, strides, 1, 0, 0)


def _storage(data: bytes) -> tuple[bytearray, Any]:
    value = bytearray(data) or bytearray(1)
    return value, (ctypes.c_ubyte * len(value)).from_buffer(value)


class _Library:
    def __init__(self, path: Path, algorithm: str):
        try:
            self.lib = ctypes.CDLL(str(path))
        except OSError as error:
            raise ExecutionContractError(f"cannot load {algorithm}: {error}") from error
        lib = self.lib
        signatures = {
            "tscb_get_abi_version": ([], ctypes.c_uint32),
            "tscb_get_manifest_json": (
                [ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_uint64)],
                ctypes.c_uint32,
            ),
            "tscb_create": (
                [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
                ctypes.c_uint32,
            ),
            "tscb_destroy": ([ctypes.c_void_p], ctypes.c_uint32),
            "tscb_reset": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_uint32),
            "tscb_compress_bound": (
                [ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(ctypes.c_uint64)],
                ctypes.c_uint32,
            ),
            "tscb_compress": (
                [ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(_Buffer)],
                ctypes.c_uint32,
            ),
            "tscb_decompress": (
                [ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(_Buffer)],
                ctypes.c_uint32,
            ),
            "tscb_finalize": ([ctypes.c_void_p, ctypes.POINTER(_Buffer)], ctypes.c_uint32),
            "tscb_get_last_error": (
                [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_uint64)],
                ctypes.c_uint32,
            ),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, result
        p, n = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_abi_version() != 1 or lib.tscb_get_manifest_json(
            ctypes.byref(p), ctypes.byref(n)
        ):
            raise ExecutionContractError("rewrite adapter ABI/manifest unavailable")
        manifest = json.loads(ctypes.string_at(p, n.value))
        if manifest != {
            "algorithm": algorithm,
            "scheme": "FROZEN_REWRITE_RWF1",
            "safe_overread_bytes": 0,
        }:
            raise ExecutionContractError("rewrite adapter binary identity mismatch")


@dataclass(frozen=True)
class RewriteLosslessAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> RewriteLosslessSession:
        return RewriteLosslessSession(self.library_path, self.algorithm, parameters)


class RewriteLosslessSession:
    def __init__(self, path: Path, algorithm: str, parameters: dict[str, Any]):
        self.algorithm = algorithm
        self.block_size = parameters.get("block_size", 1000)
        if (
            algorithm not in _KINDS
            or set(parameters) - {"block_size", "isa"}
            or parameters.get("isa", "SCALAR") != "SCALAR"
            or type(self.block_size) is not int
            or not 1
            <= self.block_size
            <= (
                16384
                if algorithm in {"self-star", "elf"}
                else 1000
                if algorithm == "elf-star"
                else 65535
            )
        ):
            raise ExecutionContractError("unregistered rewrite parameters")
        self._native = _Library(path, algorithm)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes({"algorithm": algorithm})
        self._check(
            self._native.lib.tscb_create(config, len(config), ctypes.byref(self._handle)), "create"
        )
        self._updated = self._finalized = False
        self._header = b""

    def _check(self, status: int, operation: str) -> None:
        if status == 3:
            raise OutputCapacityError(f"{self.algorithm} {operation}: output capacity")
        if status:
            pointer, size = ctypes.c_char_p(), ctypes.c_uint64()
            detail = ""
            if self._handle.value and not self._native.lib.tscb_get_last_error(
                self._handle, ctypes.byref(pointer), ctypes.byref(size)
            ):
                detail = ctypes.string_at(pointer, size.value).decode(errors="replace")
            if (
                status == 4
                and operation == "compress"
                and detail in _SOURCE_DOMAIN_REASONS.get(self.algorithm, set())
            ):
                raise SourceDomainError(detail)
            raise ExecutionContractError(
                f"{self.algorithm} {operation} failed ({status}): {detail}"
            )

    def _validate(
        self, routed: RoutedInput
    ) -> tuple[np.dtype[Any], tuple[LogicalBuffer, ...], bool]:
        system = self.algorithm == "prometheus-xor-chunk"
        if (
            routed.track is not (BenchmarkTrack.SYSTEM if system else BenchmarkTrack.VALUE)
            or not 1 <= routed.m <= 65535
            or routed.n * routed.m > _MAX_ELEMENTS
            or routed.validity_reference is not None
        ):
            raise ExecutionContractError("unsupported rewrite track/dimensions/validity")
        buffers = routed.buffers
        if system:
            if (
                not buffers
                or buffers[0].name != "timestamp"
                or buffers[0].array.dtype.str != "<i8"
                or buffers[0].array.shape != (routed.n,)
                or buffers[0].logical_bits != routed.n * 64
            ):
                raise ExecutionContractError("Prometheus requires paired signed int64 timestamps")
            if routed.timestamp_reference is not None and not np.array_equal(
                routed.timestamp_reference, buffers[0].array
            ):
                raise ExecutionContractError("timestamp pairing reference mismatch")
            buffers = buffers[1:]
        matrix = len(buffers) == 1 and buffers[0].array.ndim == 2
        if system and matrix:
            raise ExecutionContractError("Prometheus requires SOA value columns")
        if not buffers or len(buffers) != (1 if matrix else routed.m):
            raise ExecutionContractError("rewrite requires all value columns")
        dtype = buffers[0].array.dtype
        if dtype.str not in ({"<f8"} if system else {"<f4", "<f8"}):
            raise ExecutionContractError("unsupported rewrite dtype")
        for item in buffers:
            if (
                item.array.dtype != dtype
                or item.array.shape != ((routed.n, routed.m) if matrix else (routed.n,))
                or item.logical_bits != item.array.nbytes * 8
            ):
                raise ExecutionContractError("rewrite buffer shape/dtype/accounting mismatch")
        if self.algorithm == "self-star" and (
            (routed.n + self.block_size - 1) // self.block_size > 1024
            or routed.n * dtype.itemsize > 16777216
        ):
            raise ExecutionContractError("SElfStar session exceeds frozen standalone limits")
        if routed.canonical_raw_bits != sum(b.logical_bits for b in routed.buffers):
            raise ExecutionContractError("rewrite raw bit accounting mismatch")
        return dtype, buffers, matrix

    def _input(self, routed: RoutedInput) -> bytes:
        dtype, buffers, matrix = self._validate(routed)
        columns = (
            [np.ascontiguousarray(buffers[0].array[:, i]).tobytes() for i in range(routed.m)]
            if matrix
            else [np.ascontiguousarray(b.array).tobytes() for b in buffers]
        )
        timestamp = (
            np.ascontiguousarray(routed.buffers[0].array).tobytes()
            if self.algorithm == "prometheus-xor-chunk"
            else b""
        )
        return (
            _INPUT.pack(
                b"RWI1", dtype.itemsize, _KINDS[self.algorithm], routed.m, self.block_size, routed.n
            )
            + timestamp
            + b"".join(columns)
        )

    def _descriptor(self, routed: RoutedInput) -> bytes:
        dtype, _, matrix = self._validate(routed)
        return canonical_json_bytes(
            {
                "schema_version": "tscb.rewrite-container.v1",
                "algorithm": self.algorithm,
                "track": routed.track,
                "rows": routed.n,
                "columns": routed.m,
                "dtype": dtype.str,
                "matrix": matrix,
                "block_size": self.block_size,
                "segment_plan_id": routed.segment_plan_id,
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
                "buffers": [
                    {
                        "name": b.name,
                        "dtype": b.array.dtype.str,
                        "shape": list(b.array.shape),
                        "logical_bits": b.logical_bits,
                    }
                    for b in routed.buffers
                ],
            }
        )

    def output_bound(self, routed: RoutedInput) -> int:
        source_bytes = self._input(routed)
        storage, arr = _storage(source_bytes)
        source = _buffer(ctypes.addressof(arr), len(source_bytes), len(source_bytes))
        n = ctypes.c_uint64()
        self._check(
            self._native.lib.tscb_compress_bound(
                self._handle, ctypes.byref(source), ctypes.byref(n)
            ),
            "bound",
        )
        return _PREFIX.size + len(self._descriptor(routed)) + n.value

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated or self._finalized:
            raise ExecutionContractError("rewrite update requires fresh session")
        header = self._descriptor(routed)
        preamble = _PREFIX.pack(_MAGIC, len(header), hashlib.sha256(header).digest()) + header
        if len(destination) < len(preamble):
            raise OutputCapacityError("rewrite descriptor capacity")
        data = self._input(routed)
        storage, arr = _storage(data)
        source = _buffer(ctypes.addressof(arr), len(data), len(data))
        frame = destination[len(preamble) :]
        frame_arr = (ctypes.c_ubyte * len(frame)).from_buffer(frame)
        target = _buffer(ctypes.addressof(frame_arr), len(frame))
        self._check(
            self._native.lib.tscb_compress(
                self._handle, ctypes.byref(source), ctypes.byref(target)
            ),
            "compress",
        )
        destination[: len(preamble)] = preamble
        self._header, self._updated = header, True
        return len(preamble) + target.used_bytes

    def finalize(self, destination: memoryview) -> int:
        if not self._updated or self._finalized:
            raise ExecutionContractError("rewrite finalize requires exactly one update")
        output = _buffer(0, 0)
        self._check(self._native.lib.tscb_finalize(self._handle, ctypes.byref(output)), "finalize")
        self._finalized = True
        return 0

    def _parse(self, stream: bytes) -> tuple[bytes, dict[str, Any], bytes, int]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated rewrite prefix")
        magic, size, digest = _PREFIX.unpack_from(stream)
        if magic != _MAGIC or size > min(16 * 1024 * 1024, len(stream) - _PREFIX.size):
            raise ExecutionContractError("rewrite prefix mismatch")
        header = stream[_PREFIX.size : _PREFIX.size + size]
        if hashlib.sha256(header).digest() != digest:
            raise ExecutionContractError("rewrite descriptor checksum mismatch")
        try:
            info = json.loads(header)
        except (ValueError, UnicodeError) as error:
            raise ExecutionContractError("rewrite descriptor invalid") from error
        system = self.algorithm == "prometheus-xor-chunk"
        if (
            not isinstance(info, dict)
            or info.get("schema_version") != "tscb.rewrite-container.v1"
            or info.get("algorithm") != self.algorithm
            or info.get("track") != ("SYSTEM" if system else "VALUE")
            or info.get("dtype") not in ({"<f8"} if system else {"<f4", "<f8"})
            or info.get("block_size") != self.block_size
            or type(info.get("matrix")) is not bool
            or (system and (info["matrix"] or not isinstance(info.get("segment_plan_id"), str)))
        ):
            raise ExecutionContractError("rewrite descriptor identity mismatch")
        n, m, descriptors = info.get("rows"), info.get("columns"), info.get("buffers")
        if (
            type(n) is not int
            or type(m) is not int
            or n < 0
            or not 1 <= m <= 65535
            or n * m > _MAX_ELEMENTS
            or not isinstance(descriptors, list)
            or len(descriptors) != (1 if info["matrix"] else m) + int(system)
        ):
            raise ExecutionContractError("rewrite descriptor dimensions invalid")
        names: set[str] = set()
        for i, b in enumerate(descriptors):
            timestamp = system and i == 0
            shape = [n, m] if info["matrix"] else [n]
            dtype = "<i8" if timestamp else info["dtype"]
            bits = n * (m if info["matrix"] else 1) * np.dtype(dtype).itemsize * 8
            if (
                not isinstance(b, dict)
                or b.get("dtype") != dtype
                or b.get("shape") != shape
                or b.get("logical_bits") != bits
                or not isinstance(b.get("name"), str)
                or not b["name"]
                or b["name"] in names
                or (timestamp and b["name"] != "timestamp")
                or (not timestamp and b["name"] in {"timestamp", "validity"})
            ):
                raise ExecutionContractError("rewrite logical buffer descriptor invalid")
            names.add(b["name"])
        frame = stream[_PREFIX.size + size :]
        if len(frame) < 36:
            raise ExecutionContractError("truncated rewrite native frame")
        native_magic, width, kind, cols, block, rows, records = _FRAME.unpack_from(frame)
        expected_records = (
            (m if n else 0)
            if self.algorithm == "self-star"
            else m * ((n + block - 1) // block)
            if block
            else -1
        )
        if (native_magic, width, kind, cols, block, rows, records) != (
            b"RWF1",
            np.dtype(info["dtype"]).itemsize,
            _KINDS[self.algorithm],
            m,
            self.block_size,
            n,
            expected_records,
        ):
            raise ExecutionContractError("rewrite native/descriptor geometry mismatch")
        pos, payload = _FRAME.size, 0
        for _ in range(records):
            if pos > len(frame) - 8 - 12:
                raise ExecutionContractError("truncated rewrite block record")
            _, size = struct.unpack_from("<IQ", frame, pos)
            pos += 12
            if size > len(frame) - 8 - pos:
                raise ExecutionContractError("rewrite block length invalid")
            payload += size
            pos += size
        if pos != len(frame) - 8:
            raise ExecutionContractError("rewrite frame trailing bytes")
        return header, info, frame, payload

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("rewrite accounting before finalize")
        header, _, frame, payload = self._parse(stream)
        if header != self._header:
            raise ExecutionContractError("rewrite descriptor changed after encode")
        component = (
            "unallocated_shared_bits" if self.algorithm == "prometheus-xor-chunk" else "value_bits"
        )
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="OPAQUE_STANDALONE_CODEC_BYTES_WITH_EXACT_WRAPPER_ACCOUNTING_V1",
            metadata_bits=len(header) * 8,
            checksum_bits=(32 + 8) * 8,
            container_bits=(_PREFIX.size - 32 + len(frame) - payload - 8) * 8,
            **{component: payload * 8},
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, info, frame, _ = self._parse(stream)
        system = self.algorithm == "prometheus-xor-chunk"
        n, m = info["rows"], info["columns"]
        dtype = np.dtype(info["dtype"])
        expected = n * (m + int(system)) * dtype.itemsize
        storage, arr = _storage(frame)
        source = _buffer(ctypes.addressof(arr), len(frame), len(frame))
        output = bytearray(max(1, expected))
        outarr = (ctypes.c_ubyte * len(output)).from_buffer(output)
        target = _buffer(ctypes.addressof(outarr), expected)
        self._check(
            self._native.lib.tscb_decompress(
                self._handle, ctypes.byref(source), ctypes.byref(target)
            ),
            "decompress",
        )
        if target.used_bytes != expected:
            raise ExecutionContractError("rewrite decoded length mismatch")
        buffers = []
        pos = n * 8 if system else 0
        matrix = np.frombuffer(output, dtype=dtype, count=n * m, offset=pos).reshape(m, n).T
        for i, descriptor in enumerate(info["buffers"]):
            if system and i == 0:
                array = np.frombuffer(output, dtype="<i8", count=n).copy()
            elif info["matrix"]:
                array = np.ascontiguousarray(matrix)
            else:
                array = np.ascontiguousarray(matrix[:, i - int(system)])
            array.flags.writeable = False
            buffers.append(LogicalBuffer(descriptor["name"], array, descriptor["logical_bits"]))
        return DecodedOutput(tuple(buffers))

    def close(self) -> None:
        if self._handle.value:
            self._native.lib.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
