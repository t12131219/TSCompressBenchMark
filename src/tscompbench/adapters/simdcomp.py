"""Direct SDK for frozen SIMDComp uint32 plain, modular D1 and fixed FOR APIs."""

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
from tscompbench.preprocess.simdcomp import EXECUTOR_IDS

from .deflate_zlib import _Buffer
from .maskedvbyte import _buffer
from .native_timing import NativeTimingProbe

KEYS = {"simdcomp-u32": "PLAIN", "delta-simdcomp-u32": "DELTA", "for-simdcomp-u32": "FOR"}
STAGES = {
    "PLAIN": ["ORIGINAL_SIMDCOMP_UINT32_BITPACK"],
    "DELTA": ["ORIGINAL_SIMDCOMP_D1_MODULAR32", "ORIGINAL_SIMDCOMP_UINT32_BITPACK"],
    "FOR": ["ORIGINAL_SIMDCOMP_FIXED_FOR_MODULAR32", "ORIGINAL_SIMDCOMP_UINT32_BITPACK"],
}
PREFIX = struct.Struct("<8sI32s")
FRAME = struct.Struct("<8s6IQ")
RECORD = struct.Struct("<HBBI")
MAGIC = b"TSCBSCP1"
LIMIT = 16777216


def parameters(coding: str, values: dict) -> dict:
    if type(values) is not dict or set(values) - {"api", "isa", "starting_point", "native_timing"}:
        raise ExecutionContractError("unknown SIMDComp parameters")
    result = {
        "api": values.get("api", "MASKED" if coding == "DELTA" else "LENGTH"),
        "coding": coding,
        "isa": values.get("isa", "SSE4_1"),
        "starting_point": values.get("starting_point", 0),
    }
    api, isa, seed = result["api"], result["isa"], result["starting_point"]
    if (
        type(api) is not str
        or type(isa) is not str
        or type(seed) is not int
        or not 0 <= seed < 2**32
        or type(values.get("native_timing", True)) is not bool
    ):
        raise ExecutionContractError("invalid SIMDComp API/ISA/seed/timer")
    legal = (
        coding == "PLAIN"
        and isa == "SSE4_1"
        and api in ("LENGTH", "MASKED", "WITHOUTMASK")
        or coding == "PLAIN"
        and isa == "AVX2"
        and api in ("MASKED", "WITHOUTMASK")
        or coding == "DELTA"
        and isa == "SSE4_1"
        and api in ("MASKED", "WITHOUTMASK")
        or coding == "FOR"
        and isa == "SSE4_1"
        and api in ("LENGTH", "FULL")
    )
    if (
        type(api) is not str
        or type(isa) is not str
        or not legal
        or type(seed) is not int
        or not 0 <= seed < 2**32
        or coding == "PLAIN"
        and seed != 0
        or type(values.get("native_timing", True)) is not bool
    ):
        raise ExecutionContractError("invalid SIMDComp API/ISA/seed/timer")
    return result


def wire_mode(params: dict) -> int:
    return (
        1
        if params["coding"] == "DELTA"
        else (3 if params["api"] == "FULL" else 2)
        if params["coding"] == "FOR"
        else 4
        if params["isa"] == "AVX2"
        else 0
    )


class _Library:
    def __init__(self, path: Path):
        try:
            self.library = lib = ctypes.CDLL(str(path))
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
            for name in (
                "tscb_get_last_error",
                "tscb_get_accounting_json",
                "tscb_get_telemetry_json",
            ):
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
                "tscb_get_manifest_json",
            ):
                getattr(lib, name).restype = ctypes.c_uint32
        except (OSError, AttributeError) as error:
            raise ExecutionContractError("SIMDComp native ABI unavailable") from error
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_abi_version() != 1 or lib.tscb_get_manifest_json(
            ctypes.byref(pointer), ctypes.byref(length)
        ):
            raise ExecutionContractError("SIMDComp ABI/manifest unavailable")
        try:
            manifest = json.loads(ctypes.string_at(pointer, length.value))
        except (ValueError, UnicodeError) as error:
            raise ExecutionContractError("SIMDComp native manifest invalid") from error
        if manifest != {
            "abi_version": 1,
            "algorithm": "simdcomp-source-u32",
            "frame": "SBP1",
            "source_widths": [0, 32],
            "external_overread": 0,
            "fallback": False,
        }:
            raise ExecutionContractError("SIMDComp native identity/path mismatch")


@dataclass(frozen=True)
class SIMDCompAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str = "simdcomp-u32"

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, values: dict[str, Any]) -> SIMDCompSession:
        return SIMDCompSession(self.library_path, self.algorithm, values)

    @property
    def pipeline_executor_id(self) -> str | None:
        return EXECUTOR_IDS.get(self.algorithm)

    def inspect_preprocess(self, routed: RoutedInput, values: dict[str, Any]) -> dict:
        if self.algorithm not in EXECUTOR_IDS:
            raise ExecutionContractError("plain SIMDComp has no semantic preprocess")
        session = self.create_session({**values, "native_timing": False})
        try:
            destination = bytearray(session.output_bound(routed))
            used = session.compress_update(routed, memoryview(destination))
            session.finalize(memoryview(bytearray()))
            stream = bytes(destination[:used])
            original = routed.buffers[0]
            return {
                "algorithm": self.algorithm,
                "original": np.ascontiguousarray(original.array),
                "decoded": session.decompress(stream).buffers[0].array,
                "stream": stream,
                "wire_parameters": session.parameters,
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


class SIMDCompSession:
    def __init__(self, path: Path, algorithm: str, values: dict[str, Any]):
        if type(algorithm) is not str or algorithm not in KEYS:
            raise ExecutionContractError("unknown SIMDComp identity")
        self.algorithm, self.coding = algorithm, KEYS[algorithm]
        self.parameters = parameters(self.coding, values)
        self._native = _Library(path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes(self.parameters)
        self._check(
            self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle)),
            "create",
        )
        try:
            self._timing = NativeTimingProbe(
                self._native.library, self._handle, enabled=values.get("native_timing", True)
            )
        except Exception:
            self.close()
            raise
        self._updated = self._finalized = False
        self._header = b""
        self._stream_sha256 = None
        self._telemetry: dict[str, Any] = {}

    def _open(self) -> None:
        if not self._handle.value:
            raise ExecutionContractError("SIMDComp context is closed")

    def _check(self, status: int, operation: str) -> None:
        if not status:
            return
        if status == 3:
            raise OutputCapacityError("SIMDComp destination too small")
        pointer, size = ctypes.c_char_p(), ctypes.c_uint64()
        if self._handle.value:
            self._native.library.tscb_get_last_error(
                self._handle, ctypes.byref(pointer), ctypes.byref(size)
            )
        detail = ctypes.string_at(pointer, size.value).decode() if pointer else ""
        raise ExecutionContractError(f"SIMDComp {operation} failed ({status}): {detail}")

    def _json(self, name: str) -> dict:
        pointer, size = ctypes.c_char_p(), ctypes.c_uint64()
        self._check(
            getattr(self._native.library, name)(
                self._handle, ctypes.byref(pointer), ctypes.byref(size)
            ),
            name,
        )
        result = json.loads(ctypes.string_at(pointer, size.value))
        if not isinstance(result, dict):
            raise ExecutionContractError("SIMDComp native JSON contract")
        return result

    def native_timing(self) -> tuple[int, int] | None:
        self._open()
        return self._timing.read()

    def codec_telemetry(self) -> dict[str, Any]:
        self._open()
        return dict(self._telemetry)

    def _payload(self, routed: RoutedInput) -> tuple[bytes, np.ndarray]:
        self._open()
        if routed.track is not BenchmarkTrack.VALUE or len(routed.buffers) != 1:
            raise ExecutionContractError("SIMDComp requires VALUE/UTS uint32")
        item = routed.buffers[0]
        array = item.array
        if (
            not isinstance(array, np.ndarray)
            or array.dtype.str != "<u4"
            or array.ndim != 1
            or array.size > LIMIT
            or type(routed.n) is not int
            or routed.n != array.size
            or type(routed.m) is not int
            or routed.m != 1
            or not isinstance(item.name, str)
            or not item.name.startswith("value/")
            or type(item.logical_bits) is not int
            or item.logical_bits != array.nbytes * 8
            or type(routed.canonical_raw_bits) is not int
            or routed.canonical_raw_bits != item.logical_bits
            or routed.validity_reference is not None
            or not isinstance(routed.timestamp_unit, str)
            or not isinstance(routed.timestamp_epoch, str)
            or len(routed.value_units) > 1
            or any(not isinstance(unit, str) for unit in routed.value_units)
        ):
            raise ExecutionContractError("SIMDComp dtype/shape/logical size mismatch")
        header = canonical_json_bytes(
            {
                "schema_version": "tscb.simdcomp-container.v1",
                "algorithm": self.algorithm,
                "track": "VALUE",
                "count": int(array.size),
                "parameters": self.parameters,
                "buffer": {
                    "name": item.name,
                    "dtype": "<u4",
                    "shape": [int(array.size)],
                    "logical_bits": item.logical_bits,
                },
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
                "value_units": list(routed.value_units),
                "codec_stages": STAGES[self.coding],
            }
        )
        if len(header) > 4096:
            raise ExecutionContractError("SIMDComp descriptor exceeds 4096 bytes")
        return header, array

    def output_bound(self, routed: RoutedInput) -> int:
        header, array = self._payload(routed)
        # Bound only inspects the descriptor; it must not read a strided array.
        source = _buffer(array.ctypes.data, array.nbytes, array.nbytes, 6, source=True)
        bound = ctypes.c_uint64()
        self._check(
            self._native.library.tscb_compress_bound(
                self._handle, ctypes.byref(source), ctypes.byref(bound)
            ),
            "bound",
        )
        return PREFIX.size + len(header) + int(bound.value)

    def _read_telemetry(self, **extra: Any) -> None:
        self._telemetry = self._json("tscb_get_telemetry_json")
        self._telemetry.update(
            evidence="ACTUAL_NATIVE_ALLOCATION_AND_COPY_REQUESTS_LAST_SUCCESSFUL_OBJECT",
            cost_scope="CORE_PIPELINE",
            included_in_native_api_timing=False,
            is_peak_rss_measurement=False,
            **extra,
        )

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        self._open()
        if self._updated or self._finalized:
            raise ExecutionContractError("SIMDComp update lifecycle")
        header, array = self._payload(routed)
        if (
            destination.readonly
            or not destination.c_contiguous
            or destination.format != "B"
            or destination.ndim != 1
        ):
            raise ExecutionContractError("SIMDComp requires contiguous writable byte output")
        offset = PREFIX.size + len(header)
        if len(destination) < offset + 48:
            raise OutputCapacityError("SIMDComp frame capacity")
        if np.shares_memory(array, np.frombuffer(destination, dtype=np.uint8)):
            raise ExecutionContractError("SIMDComp input/output alias")
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
            PREFIX.pack(MAGIC, len(header), hashlib.sha256(header).digest()) + header
        )
        self._header, self._updated = header, True
        total = offset + int(output.used_bytes)
        self._stream_sha256 = hashlib.sha256(destination[:total]).digest()
        self._read_telemetry(
            gather_bytes=array.nbytes if gathered else 0,
            python_payload_copy_bytes=0,
            python_descriptor_copy_bytes=len(header),
        )
        return total

    def finalize(self, destination: memoryview) -> int:
        self._open()
        if not self._updated or self._finalized:
            raise ExecutionContractError("SIMDComp finalize lifecycle")
        output = _buffer(0, 0, 0, 11, source=False)
        self._check(
            self._native.library.tscb_finalize(self._handle, ctypes.byref(output)), "finalize"
        )
        self._finalized = True
        return int(output.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict, memoryview, dict]:
        self._open()
        if not isinstance(stream, bytes) or len(stream) < PREFIX.size:
            raise ExecutionContractError("truncated SIMDComp container")
        magic, length, digest = PREFIX.unpack_from(stream)
        if magic != MAGIC or length > 4096 or length > len(stream) - PREFIX.size:
            raise ExecutionContractError("SIMDComp container prefix")
        header = stream[PREFIX.size : PREFIX.size + length]
        if hashlib.sha256(header).digest() != digest:
            raise ExecutionContractError("SIMDComp descriptor checksum")
        try:
            info = json.loads(header)
            canonical = canonical_json_bytes(info)
        except (ValueError, UnicodeError, TypeError, OverflowError) as error:
            raise ExecutionContractError("invalid SIMDComp descriptor") from error
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
            or canonical != header
            or info["schema_version"] != "tscb.simdcomp-container.v1"
            or info["algorithm"] != self.algorithm
            or info["track"] != "VALUE"
            or info["codec_stages"] != STAGES[self.coding]
        ):
            raise ExecutionContractError("SIMDComp descriptor identity")
        count, b, params = info["count"], info["buffer"], info["parameters"]
        if (
            type(count) is not int
            or not 0 <= count <= LIMIT
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
            or set(params) != {"api", "coding", "isa", "starting_point"}
            or params["coding"] != self.coding
            or not isinstance(info["timestamp_unit"], str)
            or not isinstance(info["timestamp_epoch"], str)
            or not isinstance(info["value_units"], list)
            or len(info["value_units"]) > 1
            or any(not isinstance(unit, str) for unit in info["value_units"])
        ):
            raise ExecutionContractError("SIMDComp descriptor geometry/parameters")
        validated = parameters(self.coding, {k: v for k, v in params.items() if k != "coding"})
        if wire_mode(validated) != wire_mode(self.parameters):
            raise ExecutionContractError("SIMDComp decoder wire mode mismatch")
        frame = memoryview(stream)[PREFIX.size + length :]
        if len(frame) < 48:
            raise ExecutionContractError("truncated SIMDComp native frame")
        magic, native_count, seed, mode, block, blocks, reserved, body = FRAME.unpack_from(frame)
        if (
            magic != b"TSCBSBP1"
            or native_count != count
            or seed != params["starting_point"]
            or mode != wire_mode(params)
            or block != (256 if mode == 4 else 128)
            or blocks != (count + block - 1) // block
            or reserved
            or body != len(frame) - 48
        ):
            raise ExecutionContractError("SIMDComp descriptor/native frame mismatch")
        at, payload, value_bits = 40, 0, 0
        for index in range(blocks):
            if at > len(frame) - 16:
                raise ExecutionContractError("SIMDComp truncated record")
            n, width, layout, size = RECORD.unpack_from(frame, at)
            expected_n = min(block, count - index * block)
            expected_layout = 1 if mode in (1, 3) else 2 if mode == 4 and n == 256 else 0
            physical = 128 if layout == 1 else 256 if layout == 2 else n
            lanes = 8 if layout == 2 else 4
            expected_size = (
                physical * 4
                if width == 32
                else (((physical + lanes - 1) // lanes * width + 31) // 32) * lanes * 4
            )
            if (
                n != expected_n
                or width > 32
                or layout != expected_layout
                or size != expected_size
                or size > len(frame) - at - 16
            ):
                raise ExecutionContractError("SIMDComp record geometry")
            at += 8 + size
            payload += size
            value_bits += n * width
        if at != len(frame) - 8:
            raise ExecutionContractError("SIMDComp trailing frame bytes")
        native = {
            "container_bytes": 8,
            "metadata_bytes": 32 + blocks * 8,
            "checksum_bytes": 8,
            "payload_bytes": payload,
            "value_bits": value_bits,
            "padding_bits": payload * 8 - value_bits,
            "count": count,
            "blocks": blocks,
        }
        return header, info, frame, native

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        self._open()
        if not self._finalized:
            raise ExecutionContractError("SIMDComp accounting before finalize")
        header, _, _, native = self._parse(stream)
        expected, _ = self._payload(routed)
        if (
            header != expected
            or header != self._header
            or hashlib.sha256(stream).digest() != self._stream_sha256
        ):
            raise ExecutionContractError("SIMDComp encoded object changed")
        if self._json("tscb_get_accounting_json") != native:
            raise ExecutionContractError("SIMDComp native ledger mismatch")
        self._telemetry["padding_stream_bits"] = native["padding_bits"]
        return AccountingLedger.create(
            track=BenchmarkTrack.VALUE,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            value_bits=native["value_bits"],
            padding_bits=native["padding_bits"],
            metadata_bits=(len(header) + native["metadata_bytes"]) * 8,
            container_bits=20 * 8,
            checksum_bits=40 * 8,
            accounting_method="EXACT_DESCRIPTOR_SBP1_LOGICAL_WIDTHS_PHYSICAL_PADDING_AND_CHECKSUMS",
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        header, info, frame, native = self._parse(stream)
        storage = ctypes.c_char_p(stream)
        address = ctypes.cast(storage, ctypes.c_void_p).value
        array = np.empty(info["count"], dtype="<u4")
        source = _buffer(
            address + PREFIX.size + len(header), len(frame), len(frame), 11, source=True
        )
        output = _buffer(array.ctypes.data, array.nbytes, 0, 6, source=False)
        self._check(
            self._native.library.tscb_decompress(
                self._handle, ctypes.byref(source), ctypes.byref(output)
            ),
            "decompress",
        )
        if output.used_bytes != array.nbytes:
            raise ExecutionContractError("SIMDComp decoded length")
        self._read_telemetry(
            python_payload_copy_bytes=0,
            python_descriptor_copy_bytes=len(header),
            padding_stream_bits=native["padding_bits"],
        )
        array.flags.writeable = False
        return DecodedOutput((LogicalBuffer(info["buffer"]["name"], array, info["count"] * 32),))

    def reset(self) -> None:
        self._open()
        self._check(self._native.library.tscb_reset(self._handle, 0), "reset")
        self._updated = self._finalized = False
        self._header, self._stream_sha256, self._telemetry = b"", None, {}

    def close(self) -> None:
        if self._handle.value:
            self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
