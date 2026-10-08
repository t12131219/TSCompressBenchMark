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
)
from tscompbench.ids import canonical_json_bytes, stable_id

from .deflate_zlib import _Buffer
from .native_timing import NativeTimingProbe

KEY = "fast-differential-u32"
_PREFIX = struct.Struct("<8sI32s")
_MAGIC = b"TSCBFDP1"
_NATIVE_HEADER = struct.Struct("<8sIIII")
_LIMIT = 16777216
_STAGE = "ORIGINAL_FAST_DIFFERENTIAL_D1_MODULAR32"


def _buffer(address: int, capacity: int, used: int, dtype: int, *, source: bool) -> _Buffer:
    width = 4 if dtype == 6 else 1
    return _Buffer(
        ctypes.c_void_p(address),
        capacity,
        used,
        dtype,
        1,
        (ctypes.c_uint64 * 8)((used if source and dtype == 6 else capacity) // width),
        (ctypes.c_int64 * 8)(width),
        1,
        1,
        0,
    )


class _Library:
    """Bind the shared SDK ABI while checking this source's actual identity."""

    def __init__(self, path: Path):
        self.library = lib = ctypes.CDLL(str(path))
        lib.tscb_get_abi_version.argtypes = []
        lib.tscb_get_abi_version.restype = ctypes.c_uint32
        lib.tscb_get_manifest_json.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        lib.tscb_create.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.tscb_destroy.argtypes = [ctypes.c_void_p]
        lib.tscb_reset.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.tscb_compress_bound.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        for name in ("tscb_compress", "tscb_decompress"):
            getattr(lib, name).argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(_Buffer),
                ctypes.POINTER(_Buffer),
            ]
        lib.tscb_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer)]
        lib.tscb_get_last_error.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        for name in (
            "tscb_get_manifest_json",
            "tscb_create",
            "tscb_destroy",
            "tscb_reset",
            "tscb_compress_bound",
            "tscb_compress",
            "tscb_decompress",
            "tscb_finalize",
            "tscb_get_last_error",
        ):
            getattr(lib, name).restype = ctypes.c_uint32
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_abi_version() != 1 or lib.tscb_get_manifest_json(
            ctypes.byref(pointer),
            ctypes.byref(length),
        ):
            raise ExecutionContractError("FastDifferential ABI/manifest unavailable")
        manifest = json.loads(ctypes.string_at(pointer, length.value))
        if any(
            manifest.get(key) != value
            for key, value in {
                "algorithm": KEY,
                "isa": "SSE4_1",
                "padding": 0,
                "object_level": "P0_PRIMITIVE",
                "frame": "FDC1",
                "encoder": "ORIGINAL_FOUR_API_MODE_SELECTED",
                "decoder": "ORIGINAL_FOUR_API_MODE_SELECTED",
            }.items()
        ):
            raise ExecutionContractError("FastDifferential native identity/path mismatch")


@dataclass(frozen=True)
class FastDifferentialAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> FastDifferentialSession:
        return FastDifferentialSession(self.library_path, parameters)


class FastDifferentialSession:
    def __init__(self, path: Path, parameters: dict[str, Any]):
        if set(parameters) - {"api_mode", "isa", "starting_point", "native_timing"}:
            raise ExecutionContractError("unknown FastDifferential parameters")
        self.parameters = {
            "api_mode": parameters.get("api_mode", "DISTINCT"),
            "isa": parameters.get("isa", "SSE4_1"),
            "starting_point": parameters.get("starting_point", 0),
        }
        seed, mode = self.parameters["starting_point"], self.parameters["api_mode"]
        timing = parameters.get("native_timing", True)
        if (
            type(seed) is not int
            or not 0 <= seed <= 2**32 - 1
            or mode not in ("DISTINCT", "INPLACE")
            or self.parameters["isa"] != "SSE4_1"
            or type(timing) is not bool
        ):
            raise ExecutionContractError("invalid FastDifferential mode/seed/ISA/timer")
        self._native = _Library(path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes(self.parameters)
        self._check(
            self._native.library.tscb_create(
                config,
                len(config),
                ctypes.byref(self._handle),
            ),
            "create",
        )
        try:
            self._timing = NativeTimingProbe(self._native.library, self._handle, enabled=timing)
        except Exception:
            self.close()
            raise
        self._updated = self._finalized = False
        self._header = b""
        self._stream_sha256: bytes | None = None
        self._telemetry: dict[str, Any] = {}

    def _open(self) -> None:
        if not self._handle.value:
            raise ExecutionContractError("FastDifferential context is closed")

    def _check(self, status: int, operation: str) -> None:
        if status == 0:
            return
        if status == 3:
            raise OutputCapacityError("FastDifferential destination too small")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if self._handle.value:
            self._native.library.tscb_get_last_error(
                self._handle,
                ctypes.byref(pointer),
                ctypes.byref(length),
            )
        detail = ctypes.string_at(pointer, length.value).decode() if pointer else ""
        raise ExecutionContractError(f"FastDifferential {operation} failed ({status}): {detail}")

    def native_timing(self) -> tuple[int, int] | None:
        self._open()
        return self._timing.read()

    def codec_telemetry(self) -> dict[str, Any]:
        self._open()
        return dict(self._telemetry)

    def _payload(self, routed: RoutedInput) -> tuple[bytes, np.ndarray]:
        self._open()
        if routed.track is not BenchmarkTrack.VALUE or len(routed.buffers) != 1:
            raise ExecutionContractError("FastDifferential requires VALUE/UTS uint32")
        item = routed.buffers[0]
        array = item.array
        if (
            array.dtype.str != "<u4"
            or array.ndim != 1
            or array.size > _LIMIT
            or routed.n != array.size
            or routed.m != 1
            or not item.name.startswith("value/")
            or item.logical_bits != array.nbytes * 8
            or routed.canonical_raw_bits != item.logical_bits
            or routed.validity_reference is not None
            or len(routed.value_units) > 1
        ):
            raise ExecutionContractError("FastDifferential dtype/shape/logical size mismatch")
        header = canonical_json_bytes(
            {
                "schema_version": "tscb.fast-differential-container.v1",
                "algorithm": KEY,
                "track": "VALUE",
                "count": int(array.size),
                "parameters": self.parameters,
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
                "value_units": list(routed.value_units),
                "codec_stages": [_STAGE],
                "buffer": {
                    "name": item.name,
                    "dtype": "<u4",
                    "shape": [int(array.size)],
                    "logical_bits": item.logical_bits,
                },
            }
        )
        if len(header) > 4096:
            raise ExecutionContractError("FastDifferential descriptor exceeds 4096 bytes")
        return header, array

    def output_bound(self, routed: RoutedInput) -> int:
        header, array = self._payload(routed)
        source = _buffer(array.ctypes.data, array.nbytes, array.nbytes, 6, source=True)
        bound = ctypes.c_uint64()
        # Strided inputs are gathered only when executing. Bound checks describe the
        # future physical vector and never dereference source data in the C shim.
        self._check(
            self._native.library.tscb_compress_bound(
                self._handle,
                ctypes.byref(source),
                ctypes.byref(bound),
            ),
            "bound",
        )
        return _PREFIX.size + len(header) + int(bound.value)

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        self._open()
        if self._updated or self._finalized:
            raise ExecutionContractError("FastDifferential update lifecycle")
        header, array = self._payload(routed)
        bound = _PREFIX.size + len(header) + 32 + array.nbytes
        if len(destination) < bound:
            raise OutputCapacityError("FastDifferential bound capacity")
        if destination.readonly or not destination.c_contiguous or destination.format != "B":
            raise ExecutionContractError(
                "FastDifferential requires contiguous writable byte output"
            )
        if np.shares_memory(array, np.frombuffer(destination, dtype=np.uint8)):
            raise ExecutionContractError("FastDifferential input/output alias")
        gathered = not array.flags.c_contiguous
        array = np.ascontiguousarray(array)
        offset = _PREFIX.size + len(header)
        target = (ctypes.c_ubyte * (len(destination) - offset)).from_buffer(destination[offset:])
        source = _buffer(array.ctypes.data, array.nbytes, array.nbytes, 6, source=True)
        output = _buffer(ctypes.addressof(target), len(target), 0, 11, source=False)
        self._check(
            self._native.library.tscb_compress(
                self._handle,
                ctypes.byref(source),
                ctypes.byref(output),
            ),
            "compress",
        )
        destination[:offset] = (
            _PREFIX.pack(_MAGIC, len(header), hashlib.sha256(header).digest()) + header
        )
        self._header = header
        self._updated = True
        self._stream_sha256 = hashlib.sha256(destination[: offset + output.used_bytes]).digest()
        self._telemetry = self._allocation_telemetry(
            array.size, self.parameters["api_mode"], "ENCODE"
        )
        self._telemetry.update(
            gather_bytes=array.nbytes if gathered else 0, python_payload_copy_bytes=0
        )
        return offset + int(output.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        self._open()
        if not self._updated or self._finalized:
            raise ExecutionContractError("FastDifferential finalize lifecycle")
        output = _buffer(0, 0, 0, 11, source=False)
        self._check(
            self._native.library.tscb_finalize(self._handle, ctypes.byref(output)), "finalize"
        )
        self._finalized = True
        return int(output.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict[str, Any], bytes]:
        self._open()
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated FastDifferential container")
        magic, length, digest = _PREFIX.unpack_from(stream)
        if magic != _MAGIC or length > 4096 or length > len(stream) - _PREFIX.size:
            raise ExecutionContractError("FastDifferential container prefix")
        header = stream[_PREFIX.size : _PREFIX.size + length]
        if hashlib.sha256(header).digest() != digest:
            raise ExecutionContractError("FastDifferential descriptor checksum")
        try:
            info = json.loads(header)
            canonical = canonical_json_bytes(info)
        except (ValueError, UnicodeError, TypeError, OverflowError) as error:
            raise ExecutionContractError("invalid FastDifferential descriptor") from error
        fields = {
            "schema_version",
            "algorithm",
            "track",
            "count",
            "parameters",
            "buffer",
            "timestamp_unit",
            "timestamp_epoch",
            "value_units",
            "codec_stages",
        }
        if (
            not isinstance(info, dict)
            or set(info) != fields
            or header != canonical
            or info["schema_version"] != "tscb.fast-differential-container.v1"
            or info["algorithm"] != KEY
            or info["track"] != "VALUE"
            or info["codec_stages"] != [_STAGE]
        ):
            raise ExecutionContractError("FastDifferential descriptor identity")
        count, b, params = info["count"], info["buffer"], info["parameters"]
        if (
            type(count) is not int
            or not 0 <= count <= _LIMIT
            or not isinstance(b, dict)
            or set(b) != {"name", "dtype", "shape", "logical_bits"}
            or not isinstance(b["name"], str)
            or not b["name"].startswith("value/")
            or b["dtype"] != "<u4"
            or b["shape"] != [count]
            or type(b["shape"][0]) is not int
            or type(b["logical_bits"]) is not int
            or b["logical_bits"] != count * 32
            or not isinstance(params, dict)
            or set(params) != {"api_mode", "isa", "starting_point"}
            or params["api_mode"] not in ("DISTINCT", "INPLACE")
            or params["isa"] != "SSE4_1"
            or type(params["starting_point"]) is not int
            or not 0 <= params["starting_point"] < 2**32
            or not isinstance(info["timestamp_unit"], str)
            or not isinstance(info["timestamp_epoch"], str)
            or not isinstance(info["value_units"], list)
            or len(info["value_units"]) > 1
            or any(not isinstance(unit, str) for unit in info["value_units"])
        ):
            raise ExecutionContractError("FastDifferential descriptor geometry/parameters")
        payload = stream[_PREFIX.size + length :]
        if len(payload) != 32 + count * 4:
            raise ExecutionContractError("FastDifferential payload/count size")
        expected = (
            b"TSCBFDC1",
            count,
            params["starting_point"],
            int(params["api_mode"] == "INPLACE"),
            0,
        )
        if _NATIVE_HEADER.unpack_from(payload) != expected:
            raise ExecutionContractError("FastDifferential descriptor/native frame mismatch")
        return header, info, payload

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        self._open()
        if not self._finalized:
            raise ExecutionContractError("FastDifferential accounting before finalize")
        header, info, _ = self._parse(stream)
        expected, _ = self._payload(routed)
        if (
            header != self._header
            or header != expected
            or hashlib.sha256(stream).digest() != self._stream_sha256
        ):
            raise ExecutionContractError("FastDifferential encoded object changed")
        return AccountingLedger.create(
            track=BenchmarkTrack.VALUE,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            value_bits=info["count"] * 32,
            metadata_bits=(len(header) + 16) * 8,
            container_bits=(12 + 8) * 8,
            checksum_bits=(32 + 8) * 8,
            accounting_method="EXACT_DESCRIPTOR_FDC1_HEADER_CHECKSUM_AND_D1_WORDS",
        )

    @staticmethod
    def _allocation_telemetry(count: int, mode: str, operation: str) -> dict[str, Any]:
        return {
            "evidence": "FIXED_ALLOCATION_REQUESTS_DERIVED_FROM_FROZEN_SHIM_SUCCESS_PATH",
            "scope": "ONE_" + operation + "_OBJECT",
            "api_mode": mode,
            "actual_original_api": (
                "compute_deltas" if operation == "ENCODE" else "compute_prefix_sum"
            )
            + ("_inplace" if mode == "INPLACE" else ""),
            "native_staging_allocation_count": 1 if mode == "INPLACE" else 2,
            "native_staging_allocation_bytes": 4 * max(count, 1) * (1 if mode == "INPLACE" else 2),
            "native_staging_input_copy_bytes": 4 * count,
            "native_staging_output_copy_bytes": 4 * count,
            "internal_padding_bytes": 0,
            "padding_stream_bits": 0,
            "cost_scope": "CORE_PIPELINE",
            "included_in_native_api_timing": False,
            "is_peak_rss_measurement": False,
        }

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, info, payload = self._parse(stream)
        storage = bytearray(payload)
        src = (ctypes.c_ubyte * len(storage)).from_buffer(storage)
        array = np.empty(info["count"], dtype="<u4")
        source = _buffer(ctypes.addressof(src), len(storage), len(storage), 11, source=True)
        output = _buffer(array.ctypes.data, array.nbytes, 0, 6, source=False)
        self._check(
            self._native.library.tscb_decompress(
                self._handle,
                ctypes.byref(source),
                ctypes.byref(output),
            ),
            "decompress",
        )
        if output.used_bytes != array.nbytes:
            raise ExecutionContractError("FastDifferential decoded length")
        self._telemetry = self._allocation_telemetry(
            array.size,
            info["parameters"]["api_mode"],
            "DECODE",
        )
        self._telemetry["python_payload_copy_bytes"] = len(payload)
        array.flags.writeable = False
        return DecodedOutput((LogicalBuffer(info["buffer"]["name"], array, info["count"] * 32),))

    def reset(self) -> None:
        self._open()
        self._check(self._native.library.tscb_reset(self._handle, 0), "reset")
        self._updated = self._finalized = False
        self._header = b""
        self._stream_sha256 = None
        self._telemetry = {}

    def close(self) -> None:
        if self._handle.value:
            self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
