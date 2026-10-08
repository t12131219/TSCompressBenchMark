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

from .deflate_zlib import _Buffer
from .native_timing import NativeTimingProbe

_PREFIX = struct.Struct("<8sI32s")
_MAGIC = b"TSCBSVB1"
_LIMIT = 16777216
_CONFIG = b'{"isa":"SSE4_1"}'


def _buffer(address: int, capacity: int, used: int, dtype: int) -> _Buffer:
    width = {6: 4, 7: 8, 8: 8, 11: 1}[dtype]
    return _Buffer(
        ctypes.c_void_p(address),
        capacity,
        used,
        dtype,
        1,
        (ctypes.c_uint64 * 8)(used // width if used else capacity // width),
        (ctypes.c_int64 * 8)(width),
        1,
        0,
        0,
    )


class _Library:
    def __init__(self, path: Path, algorithm: str):
        self.library = ctypes.CDLL(str(path))
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
            raise ExecutionContractError("Stream VByte ABI/manifest unavailable")
        manifest = json.loads(ctypes.string_at(pointer, length.value))
        if manifest.get("algorithm") != algorithm or manifest.get("isa") != "SSE4_1":
            raise ExecutionContractError("Stream VByte native identity mismatch")
        self.manifest = manifest


@dataclass(frozen=True)
class StreamVByteAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> StreamVByteSession:
        if parameters.get("isa", "SSE4_1") != "SSE4_1":
            raise ExecutionContractError("Stream VByte requires the reviewed SSE4_1 path")
        return StreamVByteSession(self.library_path, self.algorithm, parameters)


class StreamVByteSession:
    primitive_key = "streamvbyte-u32"
    pipeline_key = "delta-zigzag-streamvbyte64"
    backend_stage_name = "LZBENCH_STREAM_VBYTE"
    expected_encoder = "UPSTREAM_SCALAR"

    def __init__(self, path: Path, algorithm: str, parameters: dict[str, Any]):
        self.algorithm = algorithm
        self.delta = algorithm == self.pipeline_key
        if algorithm not in (self.primitive_key, self.pipeline_key):
            raise ExecutionContractError("unknown Stream VByte identity")
        self.track = BenchmarkTrack.TIMESTAMP if self.delta else BenchmarkTrack.VALUE
        self.dtype = np.dtype("<i8" if self.delta else "<u4")
        self.code = 7 if self.delta else 6
        self._native = _Library(path, algorithm)
        if (
            self._native.manifest.get("encoder") != self.expected_encoder
            or self._native.manifest.get("decoder") != "UPSTREAM_SSE4_1_WITH_SCALAR_TAIL"
            or self._native.manifest.get("padding") != 16
        ):
            raise ExecutionContractError("Stream VByte native execution path mismatch")
        self._handle = ctypes.c_void_p()
        self._check(
            self._native.library.tscb_create(
                _CONFIG,
                len(_CONFIG),
                ctypes.byref(self._handle),
            ),
            "create",
        )
        self._timing = NativeTimingProbe(
            self._native.library,
            self._handle,
            enabled=bool(parameters.get("native_timing", True)),
        )
        self._updated = self._finalized = False
        self._header = b""
        self._telemetry: dict[str, Any] = {}

    def codec_telemetry(self) -> dict[str, Any]:
        return dict(self._telemetry)

    def _check(self, status: int, operation: str) -> None:
        if status == 0:
            return
        if status == 3:
            raise OutputCapacityError("Stream VByte destination too small")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if self._handle.value:
            self._native.library.tscb_get_last_error(
                self._handle,
                ctypes.byref(pointer),
                ctypes.byref(length),
            )
        detail = ctypes.string_at(pointer, length.value).decode() if pointer else ""
        if status == 2 and detail == "checked int64 delta overflow":
            raise SourceDomainError(detail)
        raise ExecutionContractError(f"Stream VByte {operation} failed ({status}): {detail}")

    def native_timing(self) -> tuple[int, int] | None:
        return self._timing.read()

    def _payload(self, routed: RoutedInput) -> tuple[bytes, np.ndarray]:
        if routed.track is not self.track or len(routed.buffers) != 1:
            raise ExecutionContractError("Stream VByte track/buffer mismatch")
        item = routed.buffers[0]
        array = item.array
        if array.dtype != self.dtype or array.ndim != 1:
            raise ExecutionContractError("Stream VByte requires its declared vector dtype")
        valid_name = item.name == "timestamp" if self.delta else item.name.startswith("value/")
        if (
            array.size > _LIMIT
            or item.logical_bits != array.nbytes * 8
            or array.size != routed.n
            or routed.m != 1
            or not valid_name
            or routed.validity_reference is not None
        ):
            raise ExecutionContractError("Stream VByte count/logical size mismatch")
        header = canonical_json_bytes(
            {
                "schema_version": "tscb.streamvbyte-container.v1",
                "algorithm": self.algorithm,
                "track": self.track,
                "count": int(array.size),
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
                "value_units": list(routed.value_units),
                "buffer": {
                    "name": item.name,
                    "dtype": array.dtype.str,
                    "shape": list(array.shape),
                    "logical_bits": item.logical_bits,
                },
                "codec_stages": (
                    [
                        "CHECKED_DELTA_I64",
                        "ZIGZAG_U64",
                        "INTERLEAVED_LOW_HIGH_U32",
                        self.backend_stage_name,
                    ]
                    if self.delta
                    else [self.backend_stage_name]
                ),
            }
        )
        if len(header) > 4096:
            raise ExecutionContractError("Stream VByte descriptor exceeds 4096-byte limit")
        return header, array

    def output_bound(self, routed: RoutedInput) -> int:
        header, array = self._payload(routed)
        source = _buffer(array.ctypes.data, array.nbytes, array.nbytes, self.code)
        bound = ctypes.c_uint64()
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
        if self._updated or self._finalized:
            raise ExecutionContractError("Stream VByte update lifecycle")
        header, array = self._payload(routed)
        if len(destination) < self.output_bound(routed):
            raise OutputCapacityError("Stream VByte bound capacity")
        gathered = not array.flags.c_contiguous
        # Physical gather only, inside CORE/PIPELINE. No dtype or semantic conversion.
        array = np.ascontiguousarray(array)
        offset = _PREFIX.size + len(header)
        target = (ctypes.c_ubyte * (len(destination) - offset)).from_buffer(destination[offset:])
        source = _buffer(array.ctypes.data, array.nbytes, array.nbytes, self.code)
        output = _buffer(ctypes.addressof(target), len(target), 0, 11)
        before = hashlib.sha256(destination).digest() if self.delta else None
        input_before = hashlib.sha256(array.tobytes()).digest() if self.delta else None
        try:
            self._check(
                self._native.library.tscb_compress(
                    self._handle,
                    ctypes.byref(source),
                    ctypes.byref(output),
                ),
                "compress",
            )
        except SourceDomainError as error:
            error.rejection_atomic = (
                before == hashlib.sha256(destination).digest()
                and input_before == hashlib.sha256(array.tobytes()).digest()
            )
            raise
        destination[:offset] = (
            _PREFIX.pack(_MAGIC, len(header), hashlib.sha256(header).digest()) + header
        )
        self._header = header
        self._updated = True
        words = 2 * max(0, array.size - 1) if self.delta else array.size
        native_bound = (20 if self.delta else 0) + 4 + (words + 3) // 4 + 4 * words
        self._telemetry = {
            "evidence": "FIXED_ALLOCATION_REQUESTS_DERIVED_FROM_FROZEN_SHIM_SUCCESS_PATH",
            "scope": "ONE_ENCODE_OBJECT",
            "gather_bytes": array.nbytes if gathered else 0,
            "native_staging_allocation_bytes": 4 * max(1, words) + native_bound + 16,
            "native_staging_input_copy_bytes": 0 if self.delta else array.nbytes,
            "native_staging_output_copy_bytes": int(output.used_bytes),
            "internal_padding_bytes": 16,
            "padding_stream_bits": 0,
            "cost_scope": "CORE_PIPELINE",
            "included_in_native_api_timing": False,
            "is_peak_rss_measurement": False,
        }
        return offset + int(output.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated or self._finalized:
            raise ExecutionContractError("Stream VByte finalize lifecycle")
        output = _buffer(0, 0, 0, 11)
        self._check(
            self._native.library.tscb_finalize(
                self._handle,
                ctypes.byref(output),
            ),
            "finalize",
        )
        self._finalized = True
        return int(output.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict[str, Any], bytes]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated Stream VByte container")
        magic, length, digest = _PREFIX.unpack_from(stream)
        if magic != _MAGIC or length > len(stream) - _PREFIX.size or length > 4096:
            raise ExecutionContractError("invalid Stream VByte container prefix")
        header = stream[_PREFIX.size : _PREFIX.size + length]
        if hashlib.sha256(header).digest() != digest:
            raise ExecutionContractError("Stream VByte descriptor checksum")
        try:
            info = json.loads(header)
        except (ValueError, UnicodeError) as error:
            raise ExecutionContractError("invalid Stream VByte descriptor") from error
        if (
            not isinstance(info, dict)
            or info.get("schema_version") != "tscb.streamvbyte-container.v1"
            or info.get("algorithm") != self.algorithm
        ):
            raise ExecutionContractError("Stream VByte descriptor identity")
        count = info.get("count")
        b = info.get("buffer")
        name = b.get("name") if isinstance(b, dict) else None
        valid_name = (
            name == "timestamp"
            if self.delta
            else isinstance(name, str) and name.startswith("value/")
        )
        stages = (
            ["CHECKED_DELTA_I64", "ZIGZAG_U64", "INTERLEAVED_LOW_HIGH_U32", self.backend_stage_name]
            if self.delta
            else [self.backend_stage_name]
        )
        if (
            type(count) is not int
            or not 0 <= count <= _LIMIT
            or not isinstance(b, dict)
            or info.get("track") != self.track
            or info.get("codec_stages") != stages
            or not valid_name
            or b.get("dtype") != self.dtype.str
            or b.get("shape") != [count]
            or type(b["shape"][0]) is not int
            or type(b.get("logical_bits")) is not int
            or b.get("logical_bits") != count * self.dtype.itemsize * 8
            or not isinstance(info.get("timestamp_unit"), str)
            or not isinstance(info.get("timestamp_epoch"), str)
            or not isinstance(info.get("value_units"), list)
            or any(not isinstance(unit, str) for unit in info["value_units"])
        ):
            raise ExecutionContractError("Stream VByte descriptor geometry")
        payload = stream[_PREFIX.size + length :]
        words = 2 * max(0, count - 1) if self.delta else count
        minimum = (20 if self.delta else 0) + 4 + (words + 3) // 4 + words
        maximum = (20 if self.delta else 0) + 4 + (words + 3) // 4 + 4 * words
        if not minimum <= len(payload) <= maximum:
            raise ExecutionContractError("Stream VByte payload/count size")
        return header, info, payload

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("Stream VByte accounting before finalize")
        header, _, payload = self._parse(stream)
        if header != self._header:
            raise ExecutionContractError("Stream VByte descriptor changed")
        native_metadata = 16 if self.delta else 4
        return AccountingLedger.create(
            track=self.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            metadata_bits=(len(header) + native_metadata) * 8,
            container_bits=12 * 8,
            checksum_bits=32 * 8,
            **{
                ("timestamp_bits" if self.delta else "value_bits"): (len(payload) - native_metadata)
                * 8
            },
            accounting_method="EXACT_DESCRIPTOR_NATIVE_HEADER_AND_STREAM_VBYTE_BYTES",
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, info, payload = self._parse(stream)
        storage = bytearray(payload)
        src = (ctypes.c_ubyte * len(storage)).from_buffer(storage)
        array = np.empty(info["count"], dtype=self.dtype)
        source = _buffer(ctypes.addressof(src), len(storage), len(storage), 11)
        output = _buffer(array.ctypes.data, array.nbytes, 0, self.code)
        self._check(
            self._native.library.tscb_decompress(
                self._handle,
                ctypes.byref(source),
                ctypes.byref(output),
            ),
            "decompress",
        )
        if output.used_bytes != array.nbytes:
            raise ExecutionContractError("Stream VByte decoded length")
        words = 2 * max(0, array.size - 1) if self.delta else array.size
        self._telemetry = {
            "evidence": "FIXED_ALLOCATION_REQUESTS_DERIVED_FROM_FROZEN_SHIM_SUCCESS_PATH",
            "scope": "ONE_DECODE_OBJECT",
            "python_payload_copy_bytes": len(payload),
            "native_staging_allocation_bytes": len(payload)
            + 16
            + 4 * max(1, words)
            + self.dtype.itemsize * max(1, array.size),
            "native_staging_input_copy_bytes": len(payload),
            "native_staging_output_copy_bytes": array.nbytes,
            "internal_padding_bytes": 16,
            "padding_stream_bits": 0,
            "cost_scope": "CORE_PIPELINE",
            "included_in_native_api_timing": False,
            "is_peak_rss_measurement": False,
        }
        array.flags.writeable = False
        return DecodedOutput(
            (LogicalBuffer(info["buffer"]["name"], array, info["buffer"]["logical_bits"]),)
        )

    def close(self) -> None:
        if self._handle.value:
            self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
