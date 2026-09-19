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
_NATIVE_ENVELOPE = struct.Struct("<4sBBHQ")
_HUFF0_ENVELOPE = struct.Struct("<4sBBHQQQ")
_MAGIC = {
    "sprintz-delta": b"TSCBSPD\0",
    "sprintz-fire": b"TSCBSPF\0",
    "sprintz-fire-huff0": b"TSCBSFH\0",
}
_ALLOWED_DTYPES = {"|i1", "|u1", "<i2", "<u2"}
_MAX_ELEMENTS = 16 * 1024 * 1024
_MAX_HUFF0_RAW_BYTES = 120 * 1024


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
            function.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(_Buffer)
            ]
            function.restype = ctypes.c_uint32
        lib.tscb_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer)]
        lib.tscb_finalize.restype = ctypes.c_uint32
        if lib.tscb_get_abi_version() != 1:
            raise ExecutionContractError("Sprintz ABI mismatch")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_manifest_json(ctypes.byref(pointer), ctypes.byref(length)):
            raise ExecutionContractError("Sprintz native manifest missing")
        manifest = json.loads(ctypes.string_at(pointer, length.value))
        if (
            manifest.get("algorithm") != algorithm
            or manifest.get("isa") != "AVX2_BMI2_LZCNT"
            or manifest.get("threading") != "SINGLE_THREAD"
        ):
            raise ExecutionContractError("Sprintz binary does not match requested algorithm")


@dataclass(frozen=True)
class SprintzAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> SprintzSession:
        return SprintzSession(self.library_path, self.algorithm, parameters)


class SprintzSession:
    def __init__(self, library_path: Path, algorithm: str, parameters: dict[str, Any]):
        if (
            algorithm not in _MAGIC
            or parameters.get("isa", "AVX2_BMI2_LZCNT") != "AVX2_BMI2_LZCNT"
            or type(parameters.get("native_timing", True)) is not bool
        ):
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
                self._native.library,
                self._handle,
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
    def _validate_routed(
        routed: RoutedInput,
    ) -> tuple[int, tuple[LogicalBuffer, ...], str]:
        if (
            routed.track is not BenchmarkTrack.VALUE
            or not 1 <= routed.m <= 128
        ):
            raise ExecutionContractError("Sprintz requires all channels of a VALUE UTS/MTS")
        if len(routed.buffers) == 1 and routed.buffers[0].array.ndim == 2:
            item = routed.buffers[0]
            if (
                item.array.shape != (routed.n, routed.m)
                or item.array.dtype.str not in _ALLOWED_DTYPES
                or item.logical_bits != item.array.nbytes * 8
                or routed.n * routed.m > _MAX_ELEMENTS
            ):
                raise ExecutionContractError(
                    "Sprintz native matrix shape, dtype, or accounting is unsupported"
                )
            return item.array.dtype.itemsize, routed.buffers, "NATIVE_2D_ROW_MAJOR"
        if len(routed.buffers) != routed.m:
            raise ExecutionContractError("Sprintz must receive every VALUE channel")
        itemsize = 0
        for item in routed.buffers:
            dtype = item.array.dtype.str
            if (
                dtype not in _ALLOWED_DTYPES
                or item.array.ndim != 1
                or item.array.size != routed.n
                or item.logical_bits != item.array.nbytes * 8
            ):
                raise ExecutionContractError(
                    "Sprintz input shape, dtype, or accounting is unsupported"
                )
            if itemsize and item.array.dtype.itemsize != itemsize:
                raise ExecutionContractError(
                    "Sprintz channels must have one homogeneous element width"
                )
            itemsize = item.array.dtype.itemsize
        if routed.n * routed.m > _MAX_ELEMENTS:
            raise ExecutionContractError("Sprintz input exceeds the registered element limit")
        return itemsize, routed.buffers, "SOA_COLUMNS_TO_ROW_MAJOR_INTERLEAVED"

    @staticmethod
    def _row_major(routed: RoutedInput) -> tuple[int, bytes]:
        itemsize, buffers, representation = SprintzSession._validate_routed(routed)
        if representation == "NATIVE_2D_ROW_MAJOR":
            return itemsize, np.ascontiguousarray(buffers[0].array).tobytes(order="C")
        unsigned = np.dtype("u1" if itemsize == 1 else "<u2")
        matrix = np.empty((routed.n, routed.m), dtype=unsigned)
        for index, item in enumerate(buffers):
            matrix[:, index] = np.ascontiguousarray(item.array).view(unsigned)
        return itemsize, matrix.tobytes(order="C")

    @staticmethod
    def _native_input(routed: RoutedInput) -> bytes:
        itemsize, payload = SprintzSession._row_major(routed)
        return _NATIVE_ENVELOPE.pack(
            b"TSI1", itemsize, 0, routed.m, routed.n * routed.m
        ) + payload

    def _descriptor(self, routed: RoutedInput) -> bytes:
        itemsize, buffers, representation = self._validate_routed(routed)
        return canonical_json_bytes({
            "schema_version": "tscb.sprintz-container.v2",
            "algorithm": self.algorithm,
            "track": routed.track,
            "rows": routed.n,
            "dimensions": routed.m,
            "element_bytes": itemsize,
            "layout_transform": representation,
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
            raise OutputCapacityError(f"Sprintz {operation}: destination too small")
        if status:
            raise ExecutionContractError(f"Sprintz {operation} failed ({status})")

    @staticmethod
    def _ctypes_store(data: bytes) -> tuple[bytearray, Any]:
        store = bytearray(data) or bytearray(1)
        return store, (ctypes.c_ubyte * len(store)).from_buffer(store)

    def output_bound(self, routed: RoutedInput) -> int:
        if (
            self.algorithm == "sprintz-fire-huff0"
            and routed.canonical_raw_bits > _MAX_HUFF0_RAW_BYTES * 8
        ):
            raise ExecutionContractError("SprintzFIRE+Huf input exceeds its Huff0 block limit")
        native_input = self._native_input(routed)
        store, source_array = self._ctypes_store(native_input)
        source = _buffer(
            ctypes.addressof(source_array), capacity=len(store), used=len(native_input)
        )
        bound = ctypes.c_uint64()
        self._check(self._native.library.tscb_compress_bound(
            self._handle, ctypes.byref(source), ctypes.byref(bound)
        ), "compress_bound")
        return _PREFIX.size + len(self._descriptor(routed)) + int(bound.value)

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("Sprintz update called twice")
        if (
            self.algorithm == "sprintz-fire-huff0"
            and routed.canonical_raw_bits > _MAX_HUFF0_RAW_BYTES * 8
        ):
            raise ExecutionContractError("SprintzFIRE+Huf input exceeds its Huff0 block limit")
        header = self._descriptor(routed)
        preamble = _PREFIX.pack(_MAGIC[self.algorithm], len(header)) + header
        native_input = self._native_input(routed)
        source_store, source_array = self._ctypes_store(native_input)
        source = _buffer(
            ctypes.addressof(source_array),
            capacity=len(source_store),
            used=len(native_input),
        )
        bound = ctypes.c_uint64()
        self._check(self._native.library.tscb_compress_bound(
            self._handle, ctypes.byref(source), ctypes.byref(bound)
        ), "compress_bound")
        if len(destination) < len(preamble) + bound.value:
            raise OutputCapacityError("Sprintz container destination too small")
        destination[:len(preamble)] = preamble
        frame_view = destination[len(preamble):]
        frame_array = (ctypes.c_ubyte * len(frame_view)).from_buffer(frame_view)
        target = _buffer(
            ctypes.addressof(frame_array), capacity=len(frame_view), used=0
        )
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
        if (
            magic != _MAGIC[self.algorithm]
            or size > 65536
            or size > len(stream) - _PREFIX.size
        ):
            raise ExecutionContractError("invalid Sprintz container prefix")
        header = stream[_PREFIX.size:_PREFIX.size + size]
        try:
            info = json.loads(header)
        except (UnicodeError, ValueError) as exc:
            raise ExecutionContractError("invalid Sprintz descriptor") from exc
        if (
            not isinstance(info, dict)
            or info.get("schema_version") != "tscb.sprintz-container.v2"
            or info.get("algorithm") != self.algorithm
            or info.get("track") != BenchmarkTrack.VALUE
            or info.get("layout_transform") not in {
                "SOA_COLUMNS_TO_ROW_MAJOR_INTERLEAVED", "NATIVE_2D_ROW_MAJOR"
            }
        ):
            raise ExecutionContractError("Sprintz descriptor identity mismatch")
        rows = info.get("rows")
        dimensions = info.get("dimensions")
        element_bytes = info.get("element_bytes")
        descriptors = info.get("buffers")
        if (
            type(rows) is not int
            or type(dimensions) is not int
            or type(element_bytes) is not int
            or rows < 0
            or not 1 <= dimensions <= 128
            or element_bytes not in (1, 2)
            or rows * dimensions > _MAX_ELEMENTS
            or not isinstance(descriptors, list)
        ):
            raise ExecutionContractError("invalid Sprintz dimensions")
        matrix_form = info["layout_transform"] == "NATIVE_2D_ROW_MAJOR"
        if len(descriptors) != (1 if matrix_form else dimensions):
            raise ExecutionContractError("Sprintz descriptor count does not match layout")
        names: set[str] = set()
        for item in descriptors:
            if not isinstance(item, dict):
                raise ExecutionContractError("invalid Sprintz buffer descriptor")
            dtype = item.get("dtype")
            name = item.get("name")
            if (
                dtype not in _ALLOWED_DTYPES
                or np.dtype(dtype).itemsize != element_bytes
                or item.get("shape") != ([rows, dimensions] if matrix_form else [rows])
                or item.get("logical_bits") != (
                    rows * dimensions * element_bytes * 8
                    if matrix_form else rows * element_bytes * 8
                )
                or not isinstance(name, str)
                or not name
                or name in names
            ):
                raise ExecutionContractError("invalid Sprintz buffer descriptor")
            names.add(name)
        frame = stream[_PREFIX.size + size:]
        minimum = _HUFF0_ENVELOPE.size if self.algorithm == "sprintz-fire-huff0" else (
            _NATIVE_ENVELOPE.size + 8
        )
        if len(frame) < minimum:
            raise ExecutionContractError("truncated Sprintz native frame")
        if self.algorithm == "sprintz-fire-huff0":
            (
                frame_magic,
                width,
                mode,
                native_dims,
                elements,
                native_bytes,
                payload_bytes,
            ) = (
                _HUFF0_ENVELOPE.unpack_from(frame)
            )
            invalid_frame = (
                frame_magic != b"TSH1"
                or mode not in (0, 1, 2)
                or not 8 <= native_bytes <= 128 * 1024
                or len(frame) != _HUFF0_ENVELOPE.size + payload_bytes
                or (mode == 0 and payload_bytes != native_bytes)
                or (mode == 1 and payload_bytes < 2)
                or (mode == 2 and payload_bytes != 1)
            )
            reserved = 0
        else:
            frame_magic, width, reserved, native_dims, elements = (
                _NATIVE_ENVELOPE.unpack_from(frame)
            )
            invalid_frame = frame_magic != b"TSF1" or bool(reserved)
        if (
            invalid_frame
            or width != element_bytes
            or native_dims != dimensions
            or elements != rows * dimensions
        ):
            raise ExecutionContractError("Sprintz native frame descriptor mismatch")
        return header, info, frame

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("Sprintz accounting before finalize")
        header, _, frame = self._parse(stream)
        if header != self._header:
            raise ExecutionContractError("Sprintz stream descriptor mismatch")
        if self.algorithm == "sprintz-fire-huff0":
            native_metadata = _HUFF0_ENVELOPE.size
            method = "EXACT_SPRINTZ_FIRE_RLE_HUFF0_AND_DESCRIPTOR_V1"
        else:
            native_metadata = _NATIVE_ENVELOPE.size + 8
            method = "EXACT_SPRINTZ_RLE_AND_DESCRIPTOR_V2"
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method=method,
            metadata_bits=(len(header) + native_metadata) * 8,
            container_bits=_PREFIX.size * 8,
            value_bits=(len(frame) - native_metadata) * 8,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, info, frame = self._parse(stream)
        rows = int(info["rows"])
        dimensions = int(info["dimensions"])
        element_bytes = int(info["element_bytes"])
        expected = rows * dimensions * element_bytes
        source_store, source_array = self._ctypes_store(frame)
        dest_store = bytearray(max(1, expected))
        dest_array = (ctypes.c_ubyte * len(dest_store)).from_buffer(dest_store)
        source = _buffer(
            ctypes.addressof(source_array), capacity=len(source_store), used=len(frame)
        )
        target = _buffer(
            ctypes.addressof(dest_array), capacity=expected, used=0
        )
        self._check(self._native.library.tscb_decompress(
            self._handle, ctypes.byref(source), ctypes.byref(target)
        ), "decompress")
        if int(target.used_bytes) != expected:
            raise ExecutionContractError("Sprintz decoded size mismatch")
        unsigned = np.dtype("u1" if element_bytes == 1 else "<u2")
        matrix = np.frombuffer(dest_store[:expected], dtype=unsigned).reshape(rows, dimensions)
        if info["layout_transform"] == "NATIVE_2D_ROW_MAJOR":
            descriptor = info["buffers"][0]
            array = np.ascontiguousarray(matrix).view(np.dtype(descriptor["dtype"]))
            array.flags.writeable = False
            return DecodedOutput((LogicalBuffer(
                descriptor["name"], array, int(descriptor["logical_bits"])
            ),))
        buffers = []
        for index, descriptor in enumerate(info["buffers"]):
            array = np.ascontiguousarray(matrix[:, index]).view(np.dtype(descriptor["dtype"]))
            array.flags.writeable = False
            buffers.append(LogicalBuffer(
                descriptor["name"], array, int(descriptor["logical_bits"])
            ))
        return DecodedOutput(tuple(buffers))

    def close(self) -> None:
        if self._handle.value:
            status = self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
            self._check(status, "destroy")
