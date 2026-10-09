"""Python control plane for unchanged FastPFOR Simple9/16 uint28 public APIs."""

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

KEYS = {"simple9-u28": "SIMPLE9", "simple9hacked-u28": "SIMPLE9HACKED", "simple16-u28": "SIMPLE16"}
PREFIX = struct.Struct("<8sI32s")
FRAME = struct.Struct("<8s6I")
MAGIC = b"TSCBSPC1"
MAX_COUNT = 16777216


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
        0,
        0,
    )


class _Library:
    EXPECTED_MANIFEST = {
        "abi_version": 1,
        "algorithm": "fastpfor-simple-source",
        "isa": "SCALAR",
        "frame": "SPF1",
        "encoder": "ORIGINAL_PUBLIC_API",
        "decoder": "ORIGINAL_PUBLIC_API_VALIDATED_GRAMMAR",
        "source_patch": "NONE",
        "value_bits_max": 28,
        "external_padding_bytes": 0,
    }

    def __init__(self, path: Path):
        try:
            self.library = lib = ctypes.CDLL(str(path))
            signatures = {
                "tscb_get_abi_version": [],
                "tscb_create": [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
                "tscb_destroy": [ctypes.c_void_p],
                "tscb_reset": [ctypes.c_void_p, ctypes.c_uint32],
                "tscb_compress_bound": [
                    ctypes.c_void_p,
                    ctypes.POINTER(_Buffer),
                    ctypes.POINTER(ctypes.c_uint64),
                ],
                "tscb_compress": [
                    ctypes.c_void_p,
                    ctypes.POINTER(_Buffer),
                    ctypes.POINTER(_Buffer),
                ],
                "tscb_decompress": [
                    ctypes.c_void_p,
                    ctypes.POINTER(_Buffer),
                    ctypes.POINTER(_Buffer),
                ],
                "tscb_finalize": [ctypes.c_void_p, ctypes.POINTER(_Buffer)],
                "tscb_get_manifest_json": [
                    ctypes.POINTER(ctypes.c_char_p),
                    ctypes.POINTER(ctypes.c_uint64),
                ],
            }
            for name in (
                "tscb_get_last_error",
                "tscb_get_accounting_json",
                "tscb_get_telemetry_json",
            ):
                signatures[name] = [
                    ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_char_p),
                    ctypes.POINTER(ctypes.c_uint64),
                ]
            for name, arguments in signatures.items():
                function = getattr(lib, name)
                function.argtypes, function.restype = arguments, ctypes.c_uint32
        except (OSError, AttributeError) as error:
            raise ExecutionContractError("Simple native ABI unavailable") from error
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_abi_version() != 1 or lib.tscb_get_manifest_json(
            ctypes.byref(pointer), ctypes.byref(length)
        ):
            raise ExecutionContractError("Simple native ABI/manifest mismatch")
        try:
            manifest = json.loads(ctypes.string_at(pointer, length.value))
        except (ValueError, UnicodeError) as error:
            raise ExecutionContractError("Simple native manifest invalid") from error
        if manifest != self.EXPECTED_MANIFEST:
            raise ExecutionContractError("Simple native source identity mismatch")


@dataclass(frozen=True)
class FastPFORSimpleAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str = "simple9-u28"

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> FastPFORSimpleSession:
        return FastPFORSimpleSession(self.library_path, self.algorithm, parameters)


class FastPFORSimpleSession:
    KEYS = KEYS
    MAGIC = MAGIC
    CONTAINER_SCHEMA = "tscb.simple-container.v1"
    VALUE_BITS = 28
    NATIVE_LIBRARY = _Library

    def __init__(self, path: Path, algorithm: str, parameters: dict[str, Any]):
        if (
            type(algorithm) is not str
            or algorithm not in self.KEYS
            or type(parameters) is not dict
            or set(parameters) - {"isa", "mark_length", "native_timing"}
        ):
            raise ExecutionContractError("unknown Simple identity/parameters")
        self.algorithm = algorithm
        self.parameters = {
            "codec": self.KEYS[algorithm],
            "isa": parameters.get("isa", "SCALAR"),
            "mark_length": parameters.get("mark_length", True),
        }
        timing = parameters.get("native_timing", True)
        if (
            type(self.parameters["isa"]) is not str
            or self.parameters["isa"] != "SCALAR"
            or type(self.parameters["mark_length"]) is not bool
            or type(timing) is not bool
        ):
            raise ExecutionContractError("invalid Simple ISA/marked/timer")
        self._native = self.NATIVE_LIBRARY(path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes(self.parameters)
        self._check(
            self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle)),
            "create",
        )
        try:
            # Apply the requested setting to native clock calls and Python observations.
            setter = self._native.library.tscb_set_native_timing
            setter.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            setter.restype = ctypes.c_uint32
            self._check(setter(self._handle, int(timing)), "native timing toggle")
            self._timing = NativeTimingProbe(self._native.library, self._handle, enabled=timing)
        except Exception:
            self.close()
            raise
        self._updated = self._finalized = False
        self._header = b""
        self._digest: bytes | None = None
        self._telemetry: dict[str, Any] = {}

    def _open(self) -> None:
        if not self._handle.value:
            raise ExecutionContractError("Simple context is closed")

    def _check(self, status: int, operation: str) -> None:
        if status == 0:
            return
        if status == 3:
            raise OutputCapacityError("Simple destination too small")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if self._handle.value:
            self._native.library.tscb_get_last_error(
                self._handle, ctypes.byref(pointer), ctypes.byref(length)
            )
        detail = ctypes.string_at(pointer, length.value).decode() if pointer else ""
        raise ExecutionContractError(f"Simple {operation} failed ({status}): {detail}")

    def _json(self, name: str) -> dict:
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        self._check(
            getattr(self._native.library, name)(
                self._handle, ctypes.byref(pointer), ctypes.byref(length)
            ),
            name,
        )
        document = json.loads(ctypes.string_at(pointer, length.value))
        if type(document) is not dict:
            raise ExecutionContractError("Simple native JSON contract")
        return document

    def native_timing(self) -> tuple[int, int] | None:
        self._open()
        return self._timing.read()

    def codec_telemetry(self) -> dict[str, Any]:
        self._open()
        return dict(self._telemetry)

    def _payload(self, routed: RoutedInput) -> tuple[bytes, np.ndarray]:
        self._open()
        if (not isinstance(routed, RoutedInput) or routed.track is not BenchmarkTrack.VALUE
                or type(routed.buffers) is not tuple or len(routed.buffers) != 1):
            raise ExecutionContractError("Simple requires VALUE/UTS unsigned integers")
        item = routed.buffers[0]
        if not isinstance(item, LogicalBuffer):
            raise ExecutionContractError("Simple logical buffer contract mismatch")
        array = item.array
        if (
            not isinstance(array, np.ndarray)
            or array.dtype.str != "<u4"
            or array.ndim != 1
            or array.size > MAX_COUNT
            or type(routed.n) is not int
            or routed.n != array.size
            or type(routed.m) is not int
            or routed.m != 1
            or type(item.name) is not str
            or not item.name.startswith("value/")
            or type(item.logical_bits) is not int
            or item.logical_bits != array.nbytes * 8
            or type(routed.canonical_raw_bits) is not int
            or routed.canonical_raw_bits < routed.n * routed.m * 8
            or routed.canonical_raw_bits % 8
            or routed.validity_reference is not None
            or type(routed.value_units) is not tuple
            or len(routed.value_units) > 1
            or any(type(unit) is not str for unit in routed.value_units)
            or type(routed.timestamp_unit) is not str
            or type(routed.timestamp_epoch) is not str
        ):
            raise ExecutionContractError("Simple dtype/shape/logical size mismatch")
        if self.VALUE_BITS < 32 and np.any(array >= 2**self.VALUE_BITS):
            error = SourceDomainError("SIMPLE_UINT28_VALUE_OUT_OF_RANGE")
            error.rejection_atomic = True
            raise error
        header = canonical_json_bytes(
            {
                "schema_version": self.CONTAINER_SCHEMA,
                "algorithm": self.algorithm,
                "track": "VALUE",
                "count": routed.n,
                "parameters": self.parameters,
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
                "value_units": list(routed.value_units),
                "buffer": {
                    "name": item.name,
                    "dtype": "<u4",
                    "shape": [routed.n],
                    "logical_bits": item.logical_bits,
                },
            }
        )
        if len(header) > 4096:
            raise ExecutionContractError("Simple descriptor resource limit")
        return header, array

    def output_bound(self, routed: RoutedInput) -> int:
        header, array = self._payload(routed)
        array = np.ascontiguousarray(array)
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
            evidence="ACTUAL_NATIVE_STAGING_ALLOCATION_AND_COPY_REQUESTS_LAST_SUCCESSFUL_OBJECT",
            cost_scope="CORE_PIPELINE",
            included_in_native_api_timing=False,
            is_peak_rss_measurement=False,
            python_payload_copy_bytes=0,
            **extra,
        )

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        self._open()
        if self._updated or self._finalized:
            raise ExecutionContractError("Simple update lifecycle")
        header, array = self._payload(routed)
        if (
            destination.readonly
            or not destination.c_contiguous
            or destination.format != "B"
            or destination.ndim != 1
        ):
            raise ExecutionContractError("Simple requires contiguous writable byte output")
        offset = PREFIX.size + len(header)
        if len(destination) < offset + 40:
            raise OutputCapacityError("Simple container capacity")
        if np.shares_memory(array, np.frombuffer(destination, dtype=np.uint8)):
            raise ExecutionContractError("Simple input/output alias")
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
            PREFIX.pack(self.MAGIC, len(header), hashlib.sha256(header).digest()) + header
        )
        used = offset + int(output.used_bytes)
        self._header, self._digest = header, hashlib.sha256(destination[:used]).digest()
        self._updated = True
        self._read_telemetry(gather_bytes=array.nbytes if gathered else 0)
        return used

    def finalize(self, destination: memoryview) -> int:
        self._open()
        if not self._updated or self._finalized:
            raise ExecutionContractError("Simple finalize lifecycle")
        output = _buffer(0, 0, 0, 11, source=False)
        self._check(
            self._native.library.tscb_finalize(self._handle, ctypes.byref(output)), "finalize"
        )
        self._finalized = True
        return int(output.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict, memoryview]:
        self._open()
        if type(stream) is not bytes or len(stream) < PREFIX.size:
            raise ExecutionContractError("truncated Simple container")
        magic, length, digest = PREFIX.unpack_from(stream)
        if magic != self.MAGIC or length > 4096 or length > len(stream) - PREFIX.size:
            raise ExecutionContractError("Simple container prefix")
        header = stream[PREFIX.size : PREFIX.size + length]
        if hashlib.sha256(header).digest() != digest:
            raise ExecutionContractError("Simple descriptor checksum")
        try:
            info = json.loads(header)
            canonical = canonical_json_bytes(info)
        except (ValueError, UnicodeError, TypeError, OverflowError) as error:
            raise ExecutionContractError("invalid Simple descriptor") from error
        if (
            type(info) is not dict
            or set(info)
            != {
                "schema_version",
                "algorithm",
                "track",
                "count",
                "parameters",
                "buffer",
                "timestamp_unit",
                "timestamp_epoch",
                "value_units",
            }
            or header != canonical
            or info["schema_version"] != self.CONTAINER_SCHEMA
            or info["algorithm"] != self.algorithm
            or info["track"] != "VALUE"
        ):
            raise ExecutionContractError("Simple descriptor identity")
        count, b, params = info["count"], info["buffer"], info["parameters"]
        if (
            type(count) is not int
            or not 0 <= count <= MAX_COUNT
            or type(b) is not dict
            or set(b) != {"name", "dtype", "shape", "logical_bits"}
            or type(b["name"]) is not str
            or not b["name"].startswith("value/")
            or b["dtype"] != "<u4"
            or type(b["shape"]) is not list
            or b["shape"] != [count]
            or type(b["shape"][0]) is not int
            or type(b["logical_bits"]) is not int
            or b["logical_bits"] != count * 32
            or type(params) is not dict
            or set(params) != {"codec", "isa", "mark_length"}
            or params["codec"] != self.KEYS[self.algorithm]
            or params["isa"] != "SCALAR"
            or type(params["mark_length"]) is not bool
            or type(info["timestamp_unit"]) is not str
            or type(info["timestamp_epoch"]) is not str
            or type(info["value_units"]) is not list
            or len(info["value_units"]) > 1
            or any(type(u) is not str for u in info["value_units"])
        ):
            raise ExecutionContractError("Simple descriptor geometry/parameters")
        frame = memoryview(stream)[PREFIX.size + length :]
        if len(frame) < 40:
            raise ExecutionContractError("truncated Simple native frame")
        self._validate_frame(frame, count, params)
        return header, info, frame

    def _validate_frame(self, frame: memoryview, count: int, params: dict) -> None:
        magic, n, kind, marked, words, reserved0, reserved1 = FRAME.unpack_from(frame)
        if (
            magic != b"TSCBSPF1"
            or n != count
            or kind != list(self.KEYS).index(self.algorithm)
            or marked != int(params["mark_length"])
            or reserved0
            or reserved1
            or not marked + (count + 27) // 28 <= words <= count + marked
            or len(frame) != 40 + 4 * words
        ):
            raise ExecutionContractError("Simple descriptor/native frame mismatch")

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        self._open()
        if not self._finalized:
            raise ExecutionContractError("Simple accounting before finalize")
        header, info, frame = self._parse(stream)
        expected, _ = self._payload(routed)
        if (
            header != self._header
            or header != expected
            or hashlib.sha256(stream).digest() != self._digest
        ):
            raise ExecutionContractError("Simple encoded object changed")
        native = self._json("tscb_get_accounting_json")
        marked = int(info["parameters"]["mark_length"])
        words = (len(frame) - 40) // 4
        fields = {
            "container_bits",
            "metadata_bits",
            "checksum_bits",
            "value_bits",
            "padding_bits",
            "final_bits",
            "count",
            "original_payload_bytes",
            "external_padding_bytes",
        }
        if (
            set(native) != fields
            or any(type(v) is not int or v < 0 for v in native.values())
            or any(
                native[k] != v
                for k, v in {
                    "container_bits": 64,
                    "metadata_bits": 192 + marked * 32 + (words - marked) * 4,
                    "checksum_bits": 64,
                    "final_bits": len(frame) * 8,
                    "count": info["count"],
                    "original_payload_bytes": words * 4,
                    "external_padding_bytes": 0,
                }.items()
            )
            or native["value_bits"] + native["padding_bits"] != (words - marked) * 28
        ):
            raise ExecutionContractError("Simple native ledger mismatch")
        return AccountingLedger.create(
            track=BenchmarkTrack.VALUE,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            value_bits=native["value_bits"],
            padding_bits=native["padding_bits"],
            metadata_bits=len(header) * 8 + native["metadata_bits"],
            container_bits=12 * 8 + native["container_bits"],
            checksum_bits=32 * 8 + native["checksum_bits"],
            accounting_method="EXACT_DESCRIPTOR_SPF1_SELECTORS_VALUES_TAIL_PADDING_AND_CHECKSUM",
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        header, info, frame = self._parse(stream)
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
            raise ExecutionContractError("Simple decoded length")
        self._read_telemetry(python_descriptor_copy_bytes=len(header))
        array.flags.writeable = False
        return DecodedOutput((LogicalBuffer(info["buffer"]["name"], array, array.nbytes * 8),))

    def reset(self) -> None:
        self._open()
        self._check(self._native.library.tscb_reset(self._handle, 0), "reset")
        self._updated = self._finalized = False
        self._header, self._digest, self._telemetry = b"", None, {}

    def close(self) -> None:
        if self._handle.value:
            self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
