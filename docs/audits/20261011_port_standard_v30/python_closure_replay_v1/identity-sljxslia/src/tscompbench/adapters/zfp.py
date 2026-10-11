from __future__ import annotations

import ctypes
import json
import math
import struct
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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

_PREFIX = struct.Struct("<8sI")
_INPUT = struct.Struct("<4sBBHQd")
_FRAME = struct.Struct("<4sBBBBHQddI")
_MAGIC = b"TSCBZFA\0"
_ALLOWED_DTYPES = {"<f4", "<f8"}
_MAX_ELEMENTS = 16 * 1024 * 1024
_MAX_RANK = 8


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


def _buffer(address: int, *, capacity: int, used: int) -> _Buffer:
    shape = (ctypes.c_uint64 * _MAX_RANK)()
    strides = (ctypes.c_int64 * _MAX_RANK)()
    shape[0] = used
    strides[0] = 1
    return _Buffer(
        ctypes.c_void_p(address), capacity, used, 11, 1, shape, strides, 1, 0, 0
    )


class _Library:
    def __init__(self, path: Path):
        try:
            self.library = ctypes.CDLL(str(path))
        except OSError as error:
            raise ExecutionContractError(f"cannot load zfp artifact: {error}") from error
        lib = self.library
        lib.tscb_get_abi_version.argtypes = []
        lib.tscb_get_abi_version.restype = ctypes.c_uint32
        lib.tscb_get_manifest_json.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        lib.tscb_get_manifest_json.restype = ctypes.c_uint32
        lib.tscb_create.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.tscb_create.restype = ctypes.c_uint32
        lib.tscb_destroy.argtypes = [ctypes.c_void_p]
        lib.tscb_destroy.restype = ctypes.c_uint32
        lib.tscb_compress_bound.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        lib.tscb_compress_bound.restype = ctypes.c_uint32
        for name in ("tscb_compress", "tscb_decompress"):
            function = getattr(lib, name)
            function.argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_Buffer),
                ctypes.POINTER(_Buffer),
            ]
            function.restype = ctypes.c_uint32
        lib.tscb_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer)]
        lib.tscb_finalize.restype = ctypes.c_uint32
        if lib.tscb_get_abi_version() != 1:
            raise ExecutionContractError("zfp adapter ABI version mismatch")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_manifest_json(ctypes.byref(pointer), ctypes.byref(length)):
            raise ExecutionContractError("zfp native manifest is unavailable")
        manifest = json.loads(ctypes.string_at(pointer, length.value))
        if (
            manifest.get("algorithm") != "zfp-accuracy-1d"
            or manifest.get("mode") != "FIXED_ACCURACY"
            or manifest.get("topology") != "1D_PER_COLUMN"
            or manifest.get("header") != "ZFP_HEADER_FULL_PER_COLUMN"
            or manifest.get("dtypes") != ["float32", "float64"]
        ):
            raise ExecutionContractError("zfp binary does not match registered identity")


@dataclass(frozen=True)
class ZfpAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    @property
    def native_timing_boundary(self) -> str:
        return str(self.manifest_adapter["native_timing_capability"]["boundary"])

    def create_session(self, parameters: dict[str, Any]) -> ZfpSession:
        return ZfpSession(self.library_path, parameters)


class ZfpSession:
    def __init__(self, library_path: Path, parameters: dict[str, Any]):
        try:
            requested_decimal = Decimal(str(parameters.get("error_bound", "0.001")))
        except InvalidOperation as error:
            raise ExecutionContractError("zfp error_bound must be a decimal string") from error
        requested = float(requested_decimal)
        if (
            parameters.get("mode", "FIXED_ACCURACY") != "FIXED_ACCURACY"
            or parameters.get("error_bound_type", "ABSOLUTE") != "ABSOLUTE"
            or not requested_decimal.is_finite()
            or requested_decimal <= 0
            or not math.isfinite(requested)
            or parameters.get("dimensionality", "1D_PER_COLUMN") != "1D_PER_COLUMN"
            or parameters.get("header", "FULL") != "FULL"
            or parameters.get("backend", "SERIAL") != "SERIAL"
            or parameters.get("isa", "SCALAR") != "SCALAR"
            or type(parameters.get("native_timing", True)) is not bool
        ):
            raise ExecutionContractError("unregistered zfp execution parameters")
        _, exponent = math.frexp(requested)
        actual = math.ldexp(1.0, exponent - 1)
        if not math.isfinite(actual) or actual <= 0 or actual > requested:
            raise ExecutionContractError("zfp cannot normalize the requested error bound")
        self.requested_error_bound_text = format(requested_decimal.normalize(), "f")
        self.requested_error_bound = requested
        self.actual_error_bound = actual
        self.actual_error_bound_hex = actual.hex()
        self._native = _Library(library_path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes({"algorithm": "zfp-accuracy-1d"})
        status = self._native.library.tscb_create(
            config, len(config), ctypes.byref(self._handle)
        )
        if status or not self._handle.value:
            raise ExecutionContractError(f"zfp create failed ({status})")
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
            raise ExecutionContractError("zfp timing queried after close")
        return self._timing.read()

    @staticmethod
    def _validate(
        routed: RoutedInput,
    ) -> tuple[np.dtype[Any], tuple[LogicalBuffer, ...], str]:
        if routed.track is not BenchmarkTrack.VALUE or not 1 <= routed.m <= 65535:
            raise ExecutionContractError("zfp requires all channels of a VALUE UTS/MTS")
        if routed.n * routed.m > _MAX_ELEMENTS:
            raise ExecutionContractError("zfp input exceeds the registered element limit")
        if len(routed.buffers) == 1 and routed.buffers[0].array.ndim == 2:
            item = routed.buffers[0]
            if (
                item.array.shape != (routed.n, routed.m)
                or item.array.dtype.str not in _ALLOWED_DTYPES
                or item.logical_bits != item.array.nbytes * 8
            ):
                raise ExecutionContractError("unsupported zfp matrix shape, dtype, or accounting")
            return item.array.dtype, routed.buffers, "ROW_MAJOR_TO_COLUMN_MAJOR"
        if len(routed.buffers) != routed.m:
            raise ExecutionContractError("zfp must receive every VALUE channel")
        dtype: np.dtype[Any] | None = None
        for item in routed.buffers:
            if (
                item.array.ndim != 1
                or item.array.size != routed.n
                or item.array.dtype.str not in _ALLOWED_DTYPES
                or item.logical_bits != item.array.nbytes * 8
            ):
                raise ExecutionContractError("unsupported zfp column shape, dtype, or accounting")
            if dtype is not None and item.array.dtype != dtype:
                raise ExecutionContractError("zfp columns must have one homogeneous float dtype")
            dtype = item.array.dtype
        assert dtype is not None
        return dtype, routed.buffers, "SOA_COLUMNS"

    def _native_input(self, routed: RoutedInput) -> bytes:
        dtype, buffers, representation = self._validate(routed)
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
        return _INPUT.pack(
            b"ZFI1", dtype.itemsize, 0, routed.m, routed.n, self.requested_error_bound
        ) + payload

    def _descriptor(self, routed: RoutedInput) -> bytes:
        dtype, buffers, representation = self._validate(routed)
        return canonical_json_bytes(
            {
                "schema_version": "tscb.zfp-accuracy-1d-container.v1",
                "algorithm": "zfp-accuracy-1d",
                "track": routed.track,
                "rows": routed.n,
                "columns": routed.m,
                "dtype": dtype.str,
                "layout_transform": representation,
                "mode": "FIXED_ACCURACY",
                "error_bound_type": "ABSOLUTE",
                "requested_error_bound": self.requested_error_bound_text,
                "actual_error_bound_hex": self.actual_error_bound_hex,
                "dimensionality": "1D_PER_COLUMN",
                "backend": "SERIAL_CPU",
                "zfp_header": "FULL_PER_COLUMN",
                "special_value_policy": "RAW_COLUMN_IEEE_EXCEPTIONS_V1",
                "buffers": [
                    {
                        "name": item.name,
                        "dtype": item.array.dtype.str,
                        "shape": list(item.array.shape),
                        "logical_bits": item.logical_bits,
                    }
                    for item in buffers
                ],
            }
        )

    @staticmethod
    def _check(status: int, operation: str) -> None:
        if status == 3:
            raise OutputCapacityError(f"zfp {operation}: destination too small")
        if status:
            raise ExecutionContractError(f"zfp {operation} failed ({status})")

    @staticmethod
    def _storage(data: bytes) -> tuple[bytearray, Any]:
        storage = bytearray(data) or bytearray(1)
        return storage, (ctypes.c_ubyte * len(storage)).from_buffer(storage)

    def output_bound(self, routed: RoutedInput) -> int:
        source_bytes = self._native_input(routed)
        storage, source_array = self._storage(source_bytes)
        source = _buffer(
            ctypes.addressof(source_array), capacity=len(source_bytes), used=len(source_bytes)
        )
        bound = ctypes.c_uint64()
        self._check(
            self._native.library.tscb_compress_bound(
                self._handle, ctypes.byref(source), ctypes.byref(bound)
            ),
            "compress_bound",
        )
        return _PREFIX.size + len(self._descriptor(routed)) + int(bound.value)

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("zfp update called twice")
        header = self._descriptor(routed)
        preamble = _PREFIX.pack(_MAGIC, len(header)) + header
        native_input = self._native_input(routed)
        source_storage, source_array = self._storage(native_input)
        source = _buffer(
            ctypes.addressof(source_array), capacity=len(native_input), used=len(native_input)
        )
        if len(destination) < len(preamble):
            raise OutputCapacityError("zfp container destination too small")
        destination[: len(preamble)] = preamble
        frame_view = destination[len(preamble) :]
        frame_array = (ctypes.c_ubyte * len(frame_view)).from_buffer(frame_view)
        target = _buffer(ctypes.addressof(frame_array), capacity=len(frame_view), used=0)
        self._check(
            self._native.library.tscb_compress(
                self._handle, ctypes.byref(source), ctypes.byref(target)
            ),
            "compress",
        )
        self._updated = True
        self._header = header
        return len(preamble) + int(target.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated or self._finalized:
            raise ExecutionContractError("zfp finalize requires exactly one update")
        del destination
        target = _buffer(1, capacity=0, used=0)
        self._check(
            self._native.library.tscb_finalize(self._handle, ctypes.byref(target)),
            "finalize",
        )
        self._finalized = True
        return int(target.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict[str, Any], bytes]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated zfp container")
        magic, header_size = _PREFIX.unpack_from(stream)
        if magic != _MAGIC or header_size > len(stream) - _PREFIX.size:
            raise ExecutionContractError("invalid zfp container prefix")
        header = stream[_PREFIX.size : _PREFIX.size + header_size]
        try:
            info = json.loads(header)
        except (UnicodeError, ValueError) as error:
            raise ExecutionContractError("invalid zfp descriptor") from error
        if (
            not isinstance(info, dict)
            or info.get("schema_version") != "tscb.zfp-accuracy-1d-container.v1"
            or info.get("algorithm") != "zfp-accuracy-1d"
            or info.get("track") != BenchmarkTrack.VALUE
            or info.get("dtype") not in _ALLOWED_DTYPES
            or info.get("layout_transform")
            not in {"SOA_COLUMNS", "ROW_MAJOR_TO_COLUMN_MAJOR"}
            or info.get("mode") != "FIXED_ACCURACY"
            or info.get("error_bound_type") != "ABSOLUTE"
            or info.get("requested_error_bound") != self.requested_error_bound_text
            or info.get("actual_error_bound_hex") != self.actual_error_bound_hex
            or info.get("dimensionality") != "1D_PER_COLUMN"
            or info.get("backend") != "SERIAL_CPU"
            or info.get("zfp_header") != "FULL_PER_COLUMN"
            or info.get("special_value_policy") != "RAW_COLUMN_IEEE_EXCEPTIONS_V1"
        ):
            raise ExecutionContractError("zfp descriptor identity mismatch")
        rows, columns, descriptors = info.get("rows"), info.get("columns"), info.get("buffers")
        matrix = info["layout_transform"] == "ROW_MAJOR_TO_COLUMN_MAJOR"
        if (
            type(rows) is not int
            or type(columns) is not int
            or rows < 0
            or not 1 <= columns <= 65535
            or rows * columns > _MAX_ELEMENTS
            or not isinstance(descriptors, list)
            or len(descriptors) != (1 if matrix else columns)
        ):
            raise ExecutionContractError("invalid zfp dimensions or descriptors")
        dtype = np.dtype(info["dtype"])
        names: set[str] = set()
        for descriptor in descriptors:
            expected_shape = [rows, columns] if matrix else [rows]
            expected_bits = rows * dtype.itemsize * 8 * (columns if matrix else 1)
            if (
                not isinstance(descriptor, dict)
                or descriptor.get("dtype") != dtype.str
                or descriptor.get("shape") != expected_shape
                or descriptor.get("logical_bits") != expected_bits
                or not isinstance(descriptor.get("name"), str)
                or not descriptor["name"]
                or descriptor["name"] in names
            ):
                raise ExecutionContractError("invalid zfp buffer descriptor")
            names.add(descriptor["name"])
        frame = stream[_PREFIX.size + header_size :]
        if len(frame) < _FRAME.size + 8:
            raise ExecutionContractError("truncated zfp native frame")
        (
            frame_magic,
            version,
            width,
            mode,
            header_policy,
            native_columns,
            native_rows,
            requested,
            actual,
            record_count,
        ) = _FRAME.unpack_from(frame)
        if (
            frame_magic != b"ZFA1"
            or version != 1
            or width != dtype.itemsize
            or mode != 4
            or header_policy != 7
            or native_columns != columns
            or native_rows != rows
            or struct.pack("<d", requested)
            != struct.pack("<d", self.requested_error_bound)
            or struct.pack("<d", actual) != struct.pack("<d", self.actual_error_bound)
            or record_count != columns
        ):
            raise ExecutionContractError("zfp native frame descriptor mismatch")
        return header, info, frame

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("zfp accounting requested before finalize")
        header, _, frame = self._parse(stream)
        if header != self._header:
            raise ExecutionContractError("zfp descriptor changed after compression")
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="EXACT_COMPLETE_ZFP_ACCURACY_1D_FRAME_V1",
            metadata_bits=len(header) * 8,
            container_bits=_PREFIX.size * 8,
            checksum_bits=64,
            value_bits=(len(frame) - 8) * 8,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, info, frame = self._parse(stream)
        rows, columns = int(info["rows"]), int(info["columns"])
        dtype = np.dtype(info["dtype"])
        expected = rows * columns * dtype.itemsize
        source_storage, source_array = self._storage(frame)
        output_storage = bytearray(max(1, expected))
        output_array = (ctypes.c_ubyte * len(output_storage)).from_buffer(output_storage)
        source = _buffer(
            ctypes.addressof(source_array), capacity=len(frame), used=len(frame)
        )
        target = _buffer(ctypes.addressof(output_array), capacity=expected, used=0)
        self._check(
            self._native.library.tscb_decompress(
                self._handle, ctypes.byref(source), ctypes.byref(target)
            ),
            "decompress",
        )
        if int(target.used_bytes) != expected:
            raise ExecutionContractError("zfp decoded byte count mismatch")
        matrix = np.frombuffer(output_storage[:expected], dtype=dtype).reshape(columns, rows).T
        if info["layout_transform"] == "ROW_MAJOR_TO_COLUMN_MAJOR":
            descriptor = info["buffers"][0]
            array = np.ascontiguousarray(matrix)
            array.flags.writeable = False
            return DecodedOutput(
                (LogicalBuffer(descriptor["name"], array, int(descriptor["logical_bits"])),)
            )
        result = []
        for index, descriptor in enumerate(info["buffers"]):
            array = np.ascontiguousarray(matrix[:, index])
            array.flags.writeable = False
            result.append(
                LogicalBuffer(descriptor["name"], array, int(descriptor["logical_bits"]))
            )
        return DecodedOutput(tuple(result))

    def close(self) -> None:
        if self._handle.value:
            status = self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
            self._check(status, "destroy")
