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
from tscompbench.measurement.workloads import QueryRequest, QueryResult

from .lzsse8_raw import _Buffer, _buffer
from .native_timing import NativeTimingProbe

_PREFIX = struct.Struct("<8sI")
_INPUT = struct.Struct("<4sBBHI")
_FRAME = struct.Struct("<4sBBBBHHI")
_RECORD = struct.Struct("<qQQ")
_MAGIC = {
    "neats-lossless-i64": b"TSCBNTS\0",
    "leats-lossless-i64": b"TSCBLTS\0",
}
_FRAME_MAGIC = {
    "neats-lossless-i64": b"NTS1",
    "leats-lossless-i64": b"LTS1",
}
_MODEL = {
    "neats-lossless-i64": "PIECEWISE_NONLINEAR",
    "leats-lossless-i64": "PIECEWISE_LINEAR",
}
_DTYPES = {"|i1", "<i2", "<i4", "<i8"}
_MAX_ELEMENTS = 262144


class _Library:
    def __init__(self, path: Path, algorithm: str):
        try:
            self.library = ctypes.CDLL(str(path))
        except OSError as error:
            raise ExecutionContractError(f"cannot load {algorithm} artifact: {error}") from error
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
            function.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(_Buffer)
            ]
            function.restype = ctypes.c_uint32
        lib.tscb_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer)]
        lib.tscb_finalize.restype = ctypes.c_uint32
        lib.tscb_neats_query_i64.argtypes = [
            ctypes.POINTER(ctypes.c_uint8), ctypes.c_uint64, ctypes.c_uint16,
            ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_int64),
            ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64),
        ]
        lib.tscb_neats_query_i64.restype = ctypes.c_uint32
        if lib.tscb_get_abi_version() != 1:
            raise ExecutionContractError(f"{algorithm} adapter ABI version mismatch")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_manifest_json(ctypes.byref(pointer), ctypes.byref(length)):
            raise ExecutionContractError(f"{algorithm} native manifest is unavailable")
        manifest = json.loads(ctypes.string_at(pointer, length.value))
        if (
            manifest.get("algorithm") != algorithm
            or manifest.get("model") != _MODEL[algorithm]
            or manifest.get("isa") != "SCALAR"
            or manifest.get("threading") != "SINGLE_THREAD"
        ):
            raise ExecutionContractError(f"{algorithm} binary identity mismatch")


@dataclass(frozen=True)
class NeatsAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> NeatsSession:
        return NeatsSession(self.library_path, self.algorithm, parameters)


class NeatsSession:
    def __init__(self, library_path: Path, algorithm: str, parameters: dict[str, Any]):
        max_bpc = parameters.get("max_bpc", 16)
        if (
            algorithm not in _MAGIC
            or max_bpc not in {16, 32}
            or parameters.get("isa", "SCALAR") != "SCALAR"
            or type(parameters.get("native_timing", True)) is not bool
        ):
            raise ExecutionContractError("unregistered NeaTS/LeaTS execution parameters")
        self.algorithm = algorithm
        self.max_bpc = max_bpc
        self._native = _Library(library_path, algorithm)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes({"algorithm": algorithm, "max_bpc": max_bpc})
        status = self._native.library.tscb_create(
            config, len(config), ctypes.byref(self._handle)
        )
        if status or not self._handle.value:
            raise ExecutionContractError(f"{algorithm} create failed ({status})")
        self._updated = self._finalized = False
        self._header = b""
        try:
            self._timing = NativeTimingProbe(
                self._native.library,
                self._handle,
                enabled=parameters.get("native_timing", True),
            )
        except Exception:
            self.close()
            raise

    def native_timing(self) -> tuple[int, int] | None:
        if not self._handle.value:
            raise ExecutionContractError("NeaTS/LeaTS timing queried after close")
        return self._timing.read()

    @staticmethod
    def _validate(
        routed: RoutedInput,
    ) -> tuple[np.dtype[Any], tuple[LogicalBuffer, ...], str]:
        if (
            routed.track is not BenchmarkTrack.VALUE
            or not 1 <= routed.n <= 65536
            or not 1 <= routed.m <= 64
            or routed.n * routed.m > _MAX_ELEMENTS
        ):
            raise ExecutionContractError("NeaTS/LeaTS requires a bounded integer VALUE UTS/MTS")
        if len(routed.buffers) == 1 and routed.buffers[0].array.ndim == 2:
            item = routed.buffers[0]
            if (
                item.array.shape != (routed.n, routed.m)
                or item.array.dtype.str not in _DTYPES
                or item.logical_bits != item.array.nbytes * 8
            ):
                raise ExecutionContractError("unsupported NeaTS/LeaTS matrix descriptor")
            return item.array.dtype, routed.buffers, "ROW_MAJOR_TO_COLUMN_MAJOR"
        if len(routed.buffers) != routed.m:
            raise ExecutionContractError("NeaTS/LeaTS must receive every VALUE channel")
        dtype: np.dtype[Any] | None = None
        for item in routed.buffers:
            if (
                item.array.ndim != 1
                or item.array.size != routed.n
                or item.array.dtype.str not in _DTYPES
                or item.logical_bits != item.array.nbytes * 8
            ):
                raise ExecutionContractError("unsupported NeaTS/LeaTS column descriptor")
            if dtype is not None and item.array.dtype != dtype:
                raise ExecutionContractError("NeaTS/LeaTS columns must have one dtype")
            dtype = item.array.dtype
        assert dtype is not None
        return dtype, routed.buffers, "SOA_COLUMNS"

    @classmethod
    def _native_input(cls, routed: RoutedInput) -> bytes:
        dtype, buffers, representation = cls._validate(routed)
        if representation == "ROW_MAJOR_TO_COLUMN_MAJOR":
            matrix = np.ascontiguousarray(buffers[0].array)
            payload = b"".join(
                np.ascontiguousarray(matrix[:, index]).tobytes()
                for index in range(routed.m)
            )
        else:
            payload = b"".join(
                np.ascontiguousarray(item.array).tobytes() for item in buffers
            )
        return _INPUT.pack(b"NTI1", dtype.itemsize, 0, routed.m, routed.n) + payload

    def _descriptor(self, routed: RoutedInput) -> bytes:
        dtype, buffers, representation = self._validate(routed)
        return canonical_json_bytes({
            "schema_version": "tscb.neats-container.v1",
            "algorithm": self.algorithm,
            "track": routed.track,
            "rows": routed.n,
            "columns": routed.m,
            "dtype": dtype.str,
            "layout_transform": representation,
            "normalization": "PER_COLUMN_MIN_SHIFT_TO_NONNEGATIVE_I64",
            "max_bpc": self.max_bpc,
            "buffers": [{
                "name": item.name,
                "dtype": item.array.dtype.str,
                "shape": list(item.array.shape),
                "logical_bits": item.logical_bits,
            } for item in buffers],
        })

    @staticmethod
    def _check(status: int, operation: str) -> None:
        if status == 3:
            raise OutputCapacityError(f"NeaTS/LeaTS {operation}: destination too small")
        if status:
            raise ExecutionContractError(f"NeaTS/LeaTS {operation} failed ({status})")

    @staticmethod
    def _storage(data: bytes) -> tuple[bytearray, Any]:
        storage = bytearray(data) or bytearray(1)
        return storage, (ctypes.c_ubyte * len(storage)).from_buffer(storage)

    def output_bound(self, routed: RoutedInput) -> int:
        native = self._native_input(routed)
        storage, array = self._storage(native)
        source = _buffer(ctypes.addressof(array), capacity=len(storage), used=len(native))
        bound = ctypes.c_uint64()
        self._check(self._native.library.tscb_compress_bound(
            self._handle, ctypes.byref(source), ctypes.byref(bound)
        ), "compress_bound")
        return _PREFIX.size + len(self._descriptor(routed)) + int(bound.value)

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("NeaTS/LeaTS update called twice")
        header = self._descriptor(routed)
        preamble = _PREFIX.pack(_MAGIC[self.algorithm], len(header)) + header
        native = self._native_input(routed)
        source_storage, source_array = self._storage(native)
        source = _buffer(
            ctypes.addressof(source_array), capacity=len(source_storage), used=len(native)
        )
        if len(destination) < len(preamble):
            raise OutputCapacityError("NeaTS/LeaTS container destination too small")
        destination[:len(preamble)] = preamble
        frame_view = destination[len(preamble):]
        frame_array = (ctypes.c_ubyte * len(frame_view)).from_buffer(frame_view)
        target = _buffer(ctypes.addressof(frame_array), capacity=len(frame_view), used=0)
        self._check(self._native.library.tscb_compress(
            self._handle, ctypes.byref(source), ctypes.byref(target)
        ), "compress")
        self._updated = True
        self._header = header
        return len(preamble) + int(target.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated or self._finalized:
            raise ExecutionContractError("NeaTS/LeaTS finalize requires exactly one update")
        del destination
        target = _buffer(1, capacity=0, used=0)
        self._check(self._native.library.tscb_finalize(
            self._handle, ctypes.byref(target)
        ), "finalize")
        self._finalized = True
        return int(target.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict[str, Any], bytes, list[int]]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated NeaTS/LeaTS container")
        magic, header_size = _PREFIX.unpack_from(stream)
        if magic != _MAGIC[self.algorithm] or header_size > len(stream) - _PREFIX.size:
            raise ExecutionContractError("invalid NeaTS/LeaTS container prefix")
        header = stream[_PREFIX.size:_PREFIX.size + header_size]
        try:
            info = json.loads(header)
        except (UnicodeError, ValueError) as error:
            raise ExecutionContractError("invalid NeaTS/LeaTS descriptor") from error
        if (
            not isinstance(info, dict)
            or info.get("schema_version") != "tscb.neats-container.v1"
            or info.get("algorithm") != self.algorithm
            or info.get("track") != BenchmarkTrack.VALUE
            or info.get("dtype") not in _DTYPES
            or info.get("layout_transform") not in {"SOA_COLUMNS", "ROW_MAJOR_TO_COLUMN_MAJOR"}
            or info.get("normalization") != "PER_COLUMN_MIN_SHIFT_TO_NONNEGATIVE_I64"
            or info.get("max_bpc") != self.max_bpc
        ):
            raise ExecutionContractError("NeaTS/LeaTS descriptor identity mismatch")
        rows, columns, descriptors = info.get("rows"), info.get("columns"), info.get("buffers")
        matrix = info["layout_transform"] == "ROW_MAJOR_TO_COLUMN_MAJOR"
        if (
            type(rows) is not int or type(columns) is not int
            or not 1 <= rows <= 65536 or not 1 <= columns <= 64
            or rows * columns > _MAX_ELEMENTS
            or not isinstance(descriptors, list)
            or len(descriptors) != (1 if matrix else columns)
        ):
            raise ExecutionContractError("invalid NeaTS/LeaTS dimensions")
        dtype = np.dtype(info["dtype"])
        names: set[str] = set()
        for descriptor in descriptors:
            shape = [rows, columns] if matrix else [rows]
            bits = rows * dtype.itemsize * 8 * (columns if matrix else 1)
            if (
                not isinstance(descriptor, dict)
                or descriptor.get("dtype") != dtype.str
                or descriptor.get("shape") != shape
                or descriptor.get("logical_bits") != bits
                or not isinstance(descriptor.get("name"), str)
                or not descriptor["name"] or descriptor["name"] in names
            ):
                raise ExecutionContractError("invalid NeaTS/LeaTS buffer descriptor")
            names.add(descriptor["name"])
        frame = stream[_PREFIX.size + header_size:]
        if len(frame) < _FRAME.size + 8:
            raise ExecutionContractError("truncated NeaTS/LeaTS native frame")
        frame_magic, version, width, bpc, reserved, native_m, reserved2, native_n = (
            _FRAME.unpack_from(frame)
        )
        if (
            frame_magic != _FRAME_MAGIC[self.algorithm] or version != 1
            or width != dtype.itemsize or bpc != self.max_bpc or reserved or reserved2
            or native_m != columns or native_n != rows
        ):
            raise ExecutionContractError("NeaTS/LeaTS native frame identity mismatch")
        offset = _FRAME.size
        payload_sizes = []
        for _ in range(columns):
            if len(frame) - 8 - offset < _RECORD.size:
                raise ExecutionContractError("truncated NeaTS/LeaTS record")
            _, payload_size, _ = _RECORD.unpack_from(frame, offset)
            offset += _RECORD.size
            if payload_size > len(frame) - 8 - offset:
                raise ExecutionContractError("truncated NeaTS/LeaTS model payload")
            payload_sizes.append(payload_size)
            offset += payload_size
        if offset != len(frame) - 8:
            raise ExecutionContractError("trailing NeaTS/LeaTS frame bytes")
        return header, info, frame, payload_sizes

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("NeaTS/LeaTS accounting requested before finalize")
        header, _, frame, payload_sizes = self._parse(stream)
        if header != self._header:
            raise ExecutionContractError("NeaTS/LeaTS descriptor changed after compression")
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="EXACT_SERIALIZED_MODEL_INDEX_FRAME_V1",
            metadata_bits=(len(header) + len(payload_sizes) * _RECORD.size) * 8,
            model_bits=sum(payload_sizes) * 8,
            checksum_bits=64,
            container_bits=(_PREFIX.size + _FRAME.size) * 8,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, info, frame, _ = self._parse(stream)
        rows, columns = int(info["rows"]), int(info["columns"])
        dtype = np.dtype(info["dtype"])
        expected = rows * columns * dtype.itemsize
        source_storage, source_array = self._storage(frame)
        output_storage = bytearray(max(1, expected))
        output_array = (ctypes.c_ubyte * len(output_storage)).from_buffer(output_storage)
        source = _buffer(
            ctypes.addressof(source_array), capacity=len(source_storage), used=len(frame)
        )
        target = _buffer(ctypes.addressof(output_array), capacity=expected, used=0)
        self._check(self._native.library.tscb_decompress(
            self._handle, ctypes.byref(source), ctypes.byref(target)
        ), "decompress")
        if int(target.used_bytes) != expected:
            raise ExecutionContractError("NeaTS/LeaTS decoded byte count mismatch")
        matrix = np.frombuffer(output_storage[:expected], dtype=dtype).reshape(columns, rows).T
        if info["layout_transform"] == "ROW_MAJOR_TO_COLUMN_MAJOR":
            descriptor = info["buffers"][0]
            array = np.ascontiguousarray(matrix)
            array.flags.writeable = False
            return DecodedOutput((LogicalBuffer(
                descriptor["name"], array, int(descriptor["logical_bits"])
            ),))
        result = []
        for index, descriptor in enumerate(info["buffers"]):
            array = np.ascontiguousarray(matrix[:, index])
            array.flags.writeable = False
            result.append(LogicalBuffer(
                descriptor["name"], array, int(descriptor["logical_bits"])
            ))
        return DecodedOutput(tuple(result))

    def query(self, stream: bytes, request: QueryRequest) -> QueryResult:
        _, info, frame, _ = self._parse(stream)
        rows, columns = int(info["rows"]), int(info["columns"])
        dtype = np.dtype(info["dtype"])
        if (
            request.start < 0 or request.length < 0
            or request.start + request.length > rows
            or any(index < 0 or index >= columns for index in request.channel_indices)
        ):
            raise ExecutionContractError("invalid NeaTS/LeaTS query range")
        frame_storage, frame_array = self._storage(frame)
        outputs = []
        bytes_touched = 0
        descriptors = info["buffers"]
        for index in request.channel_indices:
            raw = (ctypes.c_int64 * max(1, request.length))()
            touched = ctypes.c_uint64()
            self._check(self._native.library.tscb_neats_query_i64(
                frame_array, len(frame_storage), index, request.start, request.length,
                raw, request.length, ctypes.byref(touched),
            ), "query")
            values64 = np.ctypeslib.as_array(raw)[:request.length]
            limits = np.iinfo(dtype)
            if np.any(values64 < limits.min) or np.any(values64 > limits.max):
                raise ExecutionContractError("NeaTS/LeaTS query value exceeds source dtype")
            values = values64.astype(dtype, casting="unsafe", copy=True)
            values.flags.writeable = False
            descriptor = (
                descriptors[0]
                if info["layout_transform"] == "ROW_MAJOR_TO_COLUMN_MAJOR"
                else descriptors[index]
            )
            outputs.append(LogicalBuffer(
                descriptor["name"], values, request.length * dtype.itemsize * 8
            ))
            bytes_touched += int(touched.value)
        return QueryResult(
            buffers=tuple(outputs),
            decoded_elements=request.length * len(request.channel_indices),
            bytes_touched=bytes_touched,
        )

    def close(self) -> None:
        if self._handle.value:
            status = self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
            self._check(status, "destroy")
