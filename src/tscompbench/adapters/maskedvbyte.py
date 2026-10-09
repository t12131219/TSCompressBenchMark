"""Python SDK for frozen plain/modular-delta MaskedVByte uint32 source APIs."""

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
from tscompbench.preprocess.maskedvbyte import EXECUTOR_ID

from .deflate_zlib import _Buffer
from .native_timing import NativeTimingProbe

KEYS = {"maskedvbyte-u32": "PLAIN", "delta-maskedvbyte-u32": "DELTA"}
_PREFIX = struct.Struct("<8sI32s")
_MAGIC = b"TSCBMVP1"
_FRAME = struct.Struct("<8sIIIIQ")
_LIMIT = 16777216
_STAGES = {
    "PLAIN": ["ORIGINAL_MASKEDVBYTE_LEB128_UINT32"],
    "DELTA": ["ORIGINAL_MASKEDVBYTE_D1_MODULAR32", "ORIGINAL_MASKEDVBYTE_LEB128_UINT32"],
}


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
    def __init__(self, path: Path):
        try:
            self.library = lib = ctypes.CDLL(str(path))
        except OSError as error:
            raise ExecutionContractError("MaskedVByte native build unavailable") from error
        lib.tscb_get_abi_version.argtypes = []
        lib.tscb_get_abi_version.restype = ctypes.c_uint32
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
        for name in ("tscb_get_last_error", "tscb_get_accounting_json", "tscb_get_telemetry_json"):
            getattr(lib, name).argtypes = [
                ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_char_p),
                ctypes.POINTER(ctypes.c_uint64),
            ]
        lib.tscb_get_manifest_json.argtypes = [
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
            "tscb_get_accounting_json",
            "tscb_get_telemetry_json",
        ):
            getattr(lib, name).restype = ctypes.c_uint32
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_abi_version() != 1 or lib.tscb_get_manifest_json(
            ctypes.byref(pointer), ctypes.byref(length)
        ):
            raise ExecutionContractError("MaskedVByte ABI/manifest unavailable")
        manifest = json.loads(ctypes.string_at(pointer, length.value))
        if any(
            manifest.get(key) != value
            for key, value in {
                "algorithm": "maskedvbyte-source-u32",
                "isa": "SSE4_1",
                "padding": 0,
                "encoder": "ORIGINAL_PLAIN_OR_DELTA",
                "decoder": "ORIGINAL_COUNT_OR_COMPRESSED_SIZE",
                "frame": "MVB1",
                "source_patch": "UNSIGNED_SHIFTS_ONLY",
            }.items()
        ):
            raise ExecutionContractError("MaskedVByte native identity/path mismatch")


@dataclass(frozen=True)
class MaskedVByteAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str = "maskedvbyte-u32"

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> MaskedVByteSession:
        return MaskedVByteSession(self.library_path, self.algorithm, parameters)

    @property
    def pipeline_executor_id(self) -> str | None:
        return EXECUTOR_ID if self.algorithm == "delta-maskedvbyte-u32" else None

    def inspect_preprocess(self, routed: RoutedInput, parameters: dict[str, Any]) -> dict:
        if self.algorithm != "delta-maskedvbyte-u32":
            raise ExecutionContractError("plain MaskedVByte has no delta preprocess")
        session = self.create_session({**parameters, "native_timing": False})
        try:
            destination = bytearray(session.output_bound(routed))
            used = session.compress_update(routed, memoryview(destination))
            session.finalize(memoryview(bytearray()))
            stream = bytes(destination[:used])
            decoded = session.decompress(stream).buffers[0].array
            original = routed.buffers[0]
            return {
                "original": np.ascontiguousarray(original.array),
                "decoded": decoded,
                "stream": stream,
                "wire_parameters": {
                    "coding": "DELTA",
                    "starting_point": session.parameters["starting_point"],
                },
                "buffer": {
                    "name": original.name,
                    "dtype": "<u4",
                    "shape": [routed.n],
                    "logical_bits": original.logical_bits,
                },
                "value_units": list(routed.value_units),
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
            }
        finally:
            session.close()


class MaskedVByteSession:
    def __init__(self, path: Path, algorithm: str, parameters: dict[str, Any]):
        if (
            type(algorithm) is not str
            or algorithm not in KEYS
            or type(parameters) is not dict
            or set(parameters)
            - {
                "decoder_api",
                "isa",
                "starting_point",
                "native_timing",
            }
        ):
            raise ExecutionContractError("unknown MaskedVByte identity/parameters")
        self.algorithm, self.coding = algorithm, KEYS[algorithm]
        self.parameters = {
            "coding": self.coding,
            "decoder_api": parameters.get("decoder_api", "COUNT"),
            "isa": parameters.get("isa", "SSE4_1"),
            "starting_point": parameters.get("starting_point", 0),
        }
        seed, timing = self.parameters["starting_point"], parameters.get("native_timing", True)
        if (
            type(seed) is not int
            or not 0 <= seed < 2**32
            or (self.coding == "PLAIN" and seed != 0)
            or type(self.parameters["decoder_api"]) is not str
            or self.parameters["decoder_api"] not in ("COUNT", "COMPRESSED_SIZE")
            or type(self.parameters["isa"]) is not str
            or self.parameters["isa"] != "SSE4_1"
            or type(timing) is not bool
        ):
            raise ExecutionContractError("invalid MaskedVByte seed/decoder/ISA/timer")
        self._native = _Library(path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes(self.parameters)
        self._check(
            self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle)),
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
            raise ExecutionContractError("MaskedVByte context is closed")

    def _check(self, status: int, operation: str) -> None:
        if status == 0:
            return
        if status == 3:
            raise OutputCapacityError("MaskedVByte destination too small")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if self._handle.value:
            self._native.library.tscb_get_last_error(
                self._handle, ctypes.byref(pointer), ctypes.byref(length)
            )
        detail = ctypes.string_at(pointer, length.value).decode() if pointer else ""
        raise ExecutionContractError(f"MaskedVByte {operation} failed ({status}): {detail}")

    def _json(self, name: str) -> dict[str, Any]:
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        self._check(
            getattr(self._native.library, name)(
                self._handle, ctypes.byref(pointer), ctypes.byref(length)
            ),
            name,
        )
        document = json.loads(ctypes.string_at(pointer, length.value))
        if not isinstance(document, dict):
            raise ExecutionContractError("MaskedVByte native JSON contract")
        return document

    def native_timing(self) -> tuple[int, int] | None:
        self._open()
        return self._timing.read()

    def codec_telemetry(self) -> dict[str, Any]:
        self._open()
        return dict(self._telemetry)

    def _payload(self, routed: RoutedInput) -> tuple[bytes, np.ndarray]:
        self._open()
        if routed.track is not BenchmarkTrack.VALUE or len(routed.buffers) != 1:
            raise ExecutionContractError("MaskedVByte requires VALUE/UTS uint32")
        item = routed.buffers[0]
        array = item.array
        if not isinstance(array, np.ndarray):
            raise ExecutionContractError("MaskedVByte requires a NumPy vector")
        if (
            array.dtype.str != "<u4"
            or array.ndim != 1
            or array.size > _LIMIT
            or type(routed.n) is not int
            or routed.n != array.size
            or type(routed.m) is not int
            or routed.m != 1
            or not isinstance(item.name, str)
            or not item.name.startswith("value/")
            or type(item.logical_bits) is not int
            or item.logical_bits != array.nbytes * 8
            or type(routed.canonical_raw_bits) is not int
            or routed.canonical_raw_bits < routed.n * routed.m * 8
            or routed.canonical_raw_bits % 8
            or routed.validity_reference is not None
            or len(routed.value_units) > 1
            or any(not isinstance(unit, str) for unit in routed.value_units)
            or not isinstance(routed.timestamp_unit, str)
            or not isinstance(routed.timestamp_epoch, str)
        ):
            raise ExecutionContractError("MaskedVByte dtype/shape/logical size mismatch")
        header = canonical_json_bytes(
            {
                "schema_version": "tscb.maskedvbyte-container.v1",
                "algorithm": self.algorithm,
                "track": "VALUE",
                "count": int(array.size),
                "parameters": {
                    "coding": self.coding,
                    "starting_point": self.parameters["starting_point"],
                },
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
                "value_units": list(routed.value_units),
                "codec_stages": _STAGES[self.coding],
                "buffer": {
                    "name": item.name,
                    "dtype": "<u4",
                    "shape": [int(array.size)],
                    "logical_bits": item.logical_bits,
                },
                **({"pipeline_executor_id": EXECUTOR_ID} if self.coding == "DELTA" else {}),
            }
        )
        if len(header) > 4096:
            raise ExecutionContractError("MaskedVByte descriptor exceeds 4096 bytes")
        return header, array

    def output_bound(self, routed: RoutedInput) -> int:
        header, array = self._payload(routed)
        source = _buffer(array.ctypes.data, array.nbytes, array.nbytes, 6, source=True)
        bound = ctypes.c_uint64()
        self._check(
            self._native.library.tscb_compress_bound(
                self._handle, ctypes.byref(source), ctypes.byref(bound)
            ),
            "bound",
        )
        return _PREFIX.size + len(header) + int(bound.value)

    def _read_telemetry(self, **extra: Any) -> None:
        self._telemetry = self._json("tscb_get_telemetry_json")
        self._telemetry.update(
            evidence="ACTUAL_NATIVE_ALLOCATION_AND_COPY_REQUESTS_LAST_SUCCESSFUL_OBJECT",
            cost_scope="CORE_PIPELINE",
            included_in_native_api_timing=False,
            is_peak_rss_measurement=False,
            padding_stream_bits=0,
            **extra,
        )

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        self._open()
        if self._updated or self._finalized:
            raise ExecutionContractError("MaskedVByte update lifecycle")
        header, array = self._payload(routed)
        if (
            destination.readonly
            or not destination.c_contiguous
            or destination.format != "B"
            or destination.ndim != 1
        ):
            raise ExecutionContractError("MaskedVByte requires contiguous writable byte output")
        offset = _PREFIX.size + len(header)
        if len(destination) < offset + 40:
            raise OutputCapacityError("MaskedVByte frame capacity")
        if np.shares_memory(array, np.frombuffer(destination, dtype=np.uint8)):
            raise ExecutionContractError("MaskedVByte input/output alias")
        gathered = not array.flags.c_contiguous
        array = np.ascontiguousarray(array)
        target = (ctypes.c_ubyte * (len(destination) - offset)).from_buffer(destination[offset:])
        source = _buffer(array.ctypes.data, array.nbytes, array.nbytes, 6, source=True)
        output = _buffer(ctypes.addressof(target), len(target), 0, 11, source=False)
        self._check(
            self._native.library.tscb_compress(
                self._handle, ctypes.byref(source), ctypes.byref(output)
            ),
            "compress",
        )
        destination[:offset] = (
            _PREFIX.pack(_MAGIC, len(header), hashlib.sha256(header).digest()) + header
        )
        self._header = header
        self._updated = True
        self._stream_sha256 = hashlib.sha256(destination[: offset + output.used_bytes]).digest()
        self._read_telemetry(
            gather_bytes=array.nbytes if gathered else 0, python_payload_copy_bytes=0
        )
        return offset + int(output.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        self._open()
        if not self._updated or self._finalized:
            raise ExecutionContractError("MaskedVByte finalize lifecycle")
        output = _buffer(0, 0, 0, 11, source=False)
        self._check(
            self._native.library.tscb_finalize(self._handle, ctypes.byref(output)), "finalize"
        )
        self._finalized = True
        return int(output.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict[str, Any], memoryview]:
        self._open()
        if not isinstance(stream, bytes) or len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated MaskedVByte container")
        magic, length, digest = _PREFIX.unpack_from(stream)
        if magic != _MAGIC or length > 4096 or length > len(stream) - _PREFIX.size:
            raise ExecutionContractError("MaskedVByte container prefix")
        header = stream[_PREFIX.size : _PREFIX.size + length]
        if hashlib.sha256(header).digest() != digest:
            raise ExecutionContractError("MaskedVByte descriptor checksum")
        try:
            info = json.loads(header)
            canonical = canonical_json_bytes(info)
        except (ValueError, UnicodeError, TypeError, OverflowError) as error:
            raise ExecutionContractError("invalid MaskedVByte descriptor") from error
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
        if self.coding == "DELTA":
            fields.add("pipeline_executor_id")
        if (
            not isinstance(info, dict)
            or set(info) != fields
            or header != canonical
            or info["schema_version"] != "tscb.maskedvbyte-container.v1"
            or info["algorithm"] != self.algorithm
            or info["track"] != "VALUE"
            or info["codec_stages"] != _STAGES[self.coding]
            or (self.coding == "DELTA" and info.get("pipeline_executor_id") != EXECUTOR_ID)
        ):
            raise ExecutionContractError("MaskedVByte descriptor identity")
        count, b, params = info["count"], info["buffer"], info["parameters"]
        if (
            type(count) is not int
            or not 0 <= count <= _LIMIT
            or not isinstance(b, dict)
            or set(b) != {"name", "dtype", "shape", "logical_bits"}
            or not isinstance(b["name"], str)
            or not b["name"].startswith("value/")
            or b["dtype"] != "<u4"
            or not isinstance(b["shape"], list)
            or b["shape"] != [count]
            or type(b["shape"][0]) is not int
            or type(b["logical_bits"]) is not int
            or b["logical_bits"] != count * 32
            or not isinstance(params, dict)
            or set(params) != {"coding", "starting_point"}
            or params["coding"] != self.coding
            or type(params["starting_point"]) is not int
            or not 0 <= params["starting_point"] < 2**32
            or (self.coding == "PLAIN" and params["starting_point"] != 0)
            or not isinstance(info["timestamp_unit"], str)
            or not isinstance(info["timestamp_epoch"], str)
            or not isinstance(info["value_units"], list)
            or len(info["value_units"]) > 1
            or any(not isinstance(unit, str) for unit in info["value_units"])
        ):
            raise ExecutionContractError("MaskedVByte descriptor geometry/parameters")
        frame = memoryview(stream)[_PREFIX.size + length :]
        if len(frame) < 40:
            raise ExecutionContractError("truncated MaskedVByte native frame")
        magic, native_count, seed, coding, reserved, payload = _FRAME.unpack_from(frame)
        if (
            magic != b"TSCBMVB1"
            or native_count != count
            or seed != params["starting_point"]
            or coding != int(self.coding == "DELTA")
            or reserved
            or payload < count
            or payload > 5 * count
            or len(frame) != 40 + payload
        ):
            raise ExecutionContractError("MaskedVByte descriptor/native frame mismatch")
        return header, info, frame

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        self._open()
        if not self._finalized:
            raise ExecutionContractError("MaskedVByte accounting before finalize")
        header, info, frame = self._parse(stream)
        expected, _ = self._payload(routed)
        if (
            header != self._header
            or header != expected
            or hashlib.sha256(stream).digest() != self._stream_sha256
        ):
            raise ExecutionContractError("MaskedVByte encoded object changed")
        native = self._json("tscb_get_accounting_json")
        if native != {
            "container_bytes": 8,
            "metadata_bytes": 24,
            "checksum_bytes": 8,
            "payload_bytes": len(frame) - 40,
            "count": info["count"],
            "external_padding_bytes": 0,
        }:
            raise ExecutionContractError("MaskedVByte native ledger mismatch")
        return AccountingLedger.create(
            track=BenchmarkTrack.VALUE,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            value_bits=(len(frame) - 40) * 8,
            metadata_bits=(len(header) + 24) * 8,
            container_bits=(12 + 8) * 8,
            checksum_bits=(32 + 8) * 8,
            accounting_method="EXACT_DESCRIPTOR_MVB1_HEADER_CHECKSUM_AND_VBYTE_PAYLOAD",
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        header, info, frame = self._parse(stream)
        # c_char_p retains the immutable bytes object through the synchronous call.
        # Borrow the frame in place; no Python payload copy or external padding.
        storage = ctypes.c_char_p(stream)
        address = ctypes.cast(storage, ctypes.c_void_p).value
        array = np.empty(info["count"], dtype="<u4")
        source = _buffer(
            address + _PREFIX.size + len(header), len(frame), len(frame), 11, source=True
        )
        output = _buffer(array.ctypes.data, array.nbytes, 0, 6, source=False)
        self._check(
            self._native.library.tscb_decompress(
                self._handle, ctypes.byref(source), ctypes.byref(output)
            ),
            "decompress",
        )
        if output.used_bytes != array.nbytes:
            raise ExecutionContractError("MaskedVByte decoded length")
        self._read_telemetry(python_payload_copy_bytes=0, python_descriptor_copy_bytes=len(header))
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
