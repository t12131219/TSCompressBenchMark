"""Python control plane for five corrected original LittleIntPacker API pairs."""

from __future__ import annotations

import ctypes
import hashlib
import json
import shlex
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.codecs import CodecManifest
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

KEYS = {
    "littleintpacker-pack32-u32": ("PACK32", "SCALAR"),
    "littleintpacker-turbo-u32": ("TURBO", "SCALAR"),
    "littleintpacker-sc-u32": ("SC", "SCALAR"),
    "littleintpacker-bmi2-u32": ("BMI2", "AVX2_BMI2"),
    "littleintpacker-horizontal-u32": ("HORIZONTAL", "SSE4_1"),
}
PREFIX = struct.Struct("<8sI32s")
FRAME = struct.Struct("<8s4IQ")
MAGIC = b"TSCBLPC1"
MAX_COUNT = 16777216


def execution_artifacts(root: Path, manifest: CodecManifest) -> tuple[Path, tuple[Path, ...]]:
    adapter = manifest.document["adapter"]
    relative = "build/adapters/littleintpacker/release/libtscb_littleintpacker.so"
    if manifest.key not in KEYS or adapter.get("artifact_path") != relative:
        raise ExecutionContractError("LittleIntPacker artifact identity differs")
    artifact = root / relative
    record_path, command_path = (
        artifact.parent / "build-record.json",
        artifact.parent / "compile-command.json",
    )
    record = json.loads(record_path.read_text())
    command = json.loads(command_path.read_text())
    if (
        record.get("status") != "PASS"
        or record.get("profile") != "release"
        or record.get("algorithm") != "littleintpacker-source"
        or record.get("artifact") != relative
        or record.get("upstream_commit") != "8777f574a5ab3c653881371819383c986292843c"
        or record.get("runtime_fallback") is not False
        or len(record.get("objects", [])) != 7
        or len(record.get("translation_units", [])) != 7
        or len(record.get("patches", [])) != 1
        or not record.get("source_files")
        or not record.get("generated_sources")
        or not record.get("binding_sources")
        or not record.get("runtime_dependencies")
        or hashlib.sha256(canonical_json_bytes(command)).hexdigest()
        != record["compile_commands_sha256"]
        or command["commands"] != [r["command"] for r in record["commands"][:-3]]
    ):
        raise ExecutionContractError("LittleIntPacker completed source build evidence differs")
    python_closure = adapter.get("python_source_closure", [])
    required = {
        "src/tscompbench/adapters/littleintpacker.py",
        "src/tscompbench/adapters/factory.py",
        "src/tscompbench/adapters/native_timing.py",
        "src/tscompbench/planning/resolution.py",
        "src/tscompbench/execution/repetition.py",
    }
    if not required <= {item["path"] for item in python_closure}:
        raise ExecutionContractError("LittleIntPacker Python execution closure missing")
    entries = (
        record["source_files"]
        + record["binding_sources"]
        + record["generated_sources"]
        + record["patches"]
        + record["objects"]
        + record["runtime_dependencies"]
        + python_closure
    )
    for unit in record["translation_units"]:
        entries += [unit["source"], unit["object"], unit["dependency"]] + unit["compiler_closure"]
    directory = artifact.parent.relative_to(root)
    names = [
        "bitpacking32.c",
        "turbobitpacking32.c",
        "scpacking32.c",
        "bmipacking32.c",
        "horizontalpacking32.c",
        "util.c",
        "shim",
    ]
    flags = [[], [], [], ["-mavx2", "-mbmi2"], ["-mssse3", "-msse4.1"], [], []]
    for unit, shipped, name, isa in zip(
        record["translation_units"], record["objects"], names, flags, strict=True
    ):
        expected_source = (
            "adapters/littleintpacker/native/tscb_littleintpacker.cpp"
            if name == "shim"
            else str(directory / "generated/src" / name)
        )
        if (
            unit["source"]["path"] != expected_source
            or unit["object"] != shipped
            or shipped["path"] != str(directory / (name + ".o"))
            or unit["dependency"]["path"] != str(directory / (name + ".d"))
            or unit["required_isa_flags"] != isa
            or any(flag not in unit["command"] for flag in isa)
            or "-march=x86-64" not in unit["command"]
            or "-march=native" in unit["command"]
        ):
            raise ExecutionContractError("LittleIntPacker translation unit/ISA evidence differs")
        dep = (root / unit["dependency"]["path"]).read_text().replace("\\\n", " ").split(":", 1)[1]
        actual = {
            str(Path(p).relative_to(root)) if Path(p).is_relative_to(root) else p
            for p in shlex.split(dep)
        }
        if (
            len(unit["compiler_closure"]) != len(actual)
            or {p["path"] for p in unit["compiler_closure"]} != actual
            or expected_source not in actual
        ):
            raise ExecutionContractError("LittleIntPacker actual compiler closure differs")
    entries.append({"path": relative, "sha256": record["artifact_sha256"]})
    paths = [record_path, command_path]
    for item in entries:
        p = Path(item["path"])
        if ".." in p.parts:
            raise ExecutionContractError("LittleIntPacker evidence path escapes root")
        path = p if p.is_absolute() else root / p
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != item["sha256"]:
            raise ExecutionContractError("LittleIntPacker execution dependency drift: " + str(path))
        paths.append(path)
    return artifact, tuple(dict.fromkeys(paths))


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


def normalized_parameters(algorithm: str, parameters: dict) -> dict:
    if type(algorithm) is not str or algorithm not in KEYS or type(parameters) is not dict:
        raise ExecutionContractError("unknown LittleIntPacker identity/parameters")
    if set(parameters) - {"isa", "bit_width", "width_mode", "native_timing"}:
        raise ExecutionContractError("unknown LittleIntPacker parameters")
    codec, isa = KEYS[algorithm]
    result = {
        "codec": codec,
        "isa": parameters.get("isa", isa),
        "bit_width": parameters.get("bit_width", 32),
        "width_mode": parameters.get("width_mode", "AUTO"),
    }
    if (
        type(result["isa"]) is not str
        or result["isa"] != isa
        or type(result["bit_width"]) is not int
        or not 0 <= result["bit_width"] <= 32
        or type(result["width_mode"]) is not str
        or result["width_mode"] not in {"AUTO", "FIXED"}
        or (result["width_mode"] == "AUTO" and result["bit_width"] != 32)
        or type(parameters.get("native_timing", True)) is not bool
    ):
        raise ExecutionContractError("invalid LittleIntPacker width/mode/ISA/timer")
    return result


class _Library:
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
                "tscb_set_native_timing": [ctypes.c_void_p, ctypes.c_uint32],
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
            for name, args in signatures.items():
                fn = getattr(lib, name)
                fn.argtypes, fn.restype = args, ctypes.c_uint32
        except (OSError, AttributeError) as error:
            raise ExecutionContractError("LittleIntPacker native ABI unavailable") from error
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_abi_version() != 1 or lib.tscb_get_manifest_json(
            ctypes.byref(pointer), ctypes.byref(length)
        ):
            raise ExecutionContractError("LittleIntPacker native ABI/manifest mismatch")
        try:
            manifest = json.loads(ctypes.string_at(pointer, length.value))
        except (ValueError, UnicodeError) as error:
            raise ExecutionContractError("LittleIntPacker native manifest invalid") from error
        if manifest != {
            "abi_version": 1,
            "algorithm": "littleintpacker-source",
            "frame": "LIP1",
            "encoder": "PATCHED_ORIGINAL_PUBLIC_API",
            "decoder": "PATCHED_ORIGINAL_PUBLIC_API",
            "variants": ["PACK32", "TURBO", "SC", "BMI2", "HORIZONTAL"],
            "external_padding_bytes": 0,
            "max_count": MAX_COUNT,
            "bit_width_min": 0,
            "bit_width_max": 32,
        }:
            raise ExecutionContractError("LittleIntPacker native source identity mismatch")


@dataclass(frozen=True)
class LittleIntPackerAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str = "littleintpacker-pack32-u32"

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> LittleIntPackerSession:
        return LittleIntPackerSession(self.library_path, self.algorithm, parameters)


class LittleIntPackerSession:
    def __init__(self, path: Path, algorithm: str, parameters: dict[str, Any]):
        self.parameters = normalized_parameters(algorithm, parameters)
        self.algorithm = algorithm
        self._native = _Library(path)
        self._handle = ctypes.c_void_p()
        native_config = {
            "bit_width": "AUTO"
            if self.parameters["width_mode"] == "AUTO"
            else self.parameters["bit_width"],
            "codec": self.parameters["codec"],
            "isa": self.parameters["isa"],
        }
        config = canonical_json_bytes(native_config)
        self._check(
            self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle)),
            "create",
        )
        try:
            enabled = parameters.get("native_timing", True)
            self._check(
                self._native.library.tscb_set_native_timing(self._handle, int(enabled)),
                "timing toggle",
            )
            self._timing = NativeTimingProbe(self._native.library, self._handle, enabled=enabled)
        except Exception:
            self.close()
            raise
        self._updated = self._finalized = False
        self._header = b""
        self._digest: bytes | None = None
        self._telemetry: dict = {}

    def _open(self) -> None:
        if not self._handle.value:
            raise ExecutionContractError("LittleIntPacker context is closed")

    def _check(self, status: int, operation: str) -> None:
        if status == 0:
            return
        if status == 3:
            raise OutputCapacityError("LittleIntPacker destination too small")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if self._handle.value:
            self._native.library.tscb_get_last_error(
                self._handle, ctypes.byref(pointer), ctypes.byref(length)
            )
        detail = ctypes.string_at(pointer, length.value).decode() if pointer else ""
        if status == 2 and "value exceeds supplied bit width" in detail:
            error = SourceDomainError("LITTLEINTPACKER_SUPPLIED_WIDTH_OUT_OF_RANGE")
            error.rejection_atomic = True
            raise error
        raise ExecutionContractError(f"LittleIntPacker {operation} failed ({status}): {detail}")

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
            raise ExecutionContractError("LittleIntPacker native JSON contract")
        return document

    def native_timing(self) -> tuple[int, int] | None:
        self._open()
        return self._timing.read()

    def codec_telemetry(self) -> dict:
        self._open()
        return dict(self._telemetry)

    def _payload(self, routed: RoutedInput) -> tuple[bytes, np.ndarray]:
        self._open()
        if routed.track is not BenchmarkTrack.VALUE or len(routed.buffers) != 1:
            raise ExecutionContractError("LittleIntPacker requires VALUE/UTS uint32")
        item, array = routed.buffers[0], routed.buffers[0].array
        if (
            not isinstance(array, np.ndarray)
            or array.dtype.str != "<u4"
            or array.ndim != 1
            or array.size > MAX_COUNT
            or type(routed.n) is not int
            or routed.n != array.size
            or type(routed.m) is not int
            or routed.m != 1
            or not item.name.startswith("value/")
            or type(item.logical_bits) is not int
            or item.logical_bits != array.nbytes * 8
            or type(routed.canonical_raw_bits) is not int
            or routed.canonical_raw_bits < routed.n * routed.m * 8
            or routed.canonical_raw_bits % 8
            or routed.validity_reference is not None
            or len(routed.value_units) > 1
            or any(type(u) is not str for u in routed.value_units)
            or type(routed.timestamp_unit) is not str
            or type(routed.timestamp_epoch) is not str
        ):
            raise ExecutionContractError("LittleIntPacker dtype/shape/logical size mismatch")
        header = canonical_json_bytes(
            {
                "schema_version": "tscb.littleintpacker-container.v1",
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
            raise ExecutionContractError("LittleIntPacker descriptor resource limit")
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
            raise ExecutionContractError("LittleIntPacker update lifecycle")
        header, array = self._payload(routed)
        if (
            destination.readonly
            or not destination.c_contiguous
            or destination.format != "B"
            or destination.ndim != 1
        ):
            raise ExecutionContractError("LittleIntPacker requires contiguous writable byte output")
        offset = PREFIX.size + len(header)
        if len(destination) < offset + 40:
            raise OutputCapacityError("LittleIntPacker container capacity")
        if np.shares_memory(array, np.frombuffer(destination, dtype=np.uint8)):
            raise ExecutionContractError("LittleIntPacker input/output alias")
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
        used = offset + int(output.used_bytes)
        self._header, self._digest = header, hashlib.sha256(destination[:used]).digest()
        self._updated = True
        self._read_telemetry(gather_bytes=array.nbytes if gathered else 0)
        return used

    def finalize(self, destination: memoryview) -> int:
        self._open()
        if not self._updated or self._finalized:
            raise ExecutionContractError("LittleIntPacker finalize lifecycle")
        output = _buffer(0, 0, 0, 11, source=False)
        self._check(
            self._native.library.tscb_finalize(self._handle, ctypes.byref(output)), "finalize"
        )
        self._finalized = True
        return int(output.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, dict, memoryview]:
        self._open()
        if type(stream) is not bytes or len(stream) < PREFIX.size:
            raise ExecutionContractError("truncated LittleIntPacker container")
        magic, length, digest = PREFIX.unpack_from(stream)
        if magic != MAGIC or length > 4096 or length > len(stream) - PREFIX.size:
            raise ExecutionContractError("LittleIntPacker container prefix")
        header = stream[PREFIX.size : PREFIX.size + length]
        if hashlib.sha256(header).digest() != digest:
            raise ExecutionContractError("LittleIntPacker descriptor checksum")
        try:
            info = json.loads(header)
            canonical = canonical_json_bytes(info)
        except (ValueError, UnicodeError, TypeError, OverflowError) as error:
            raise ExecutionContractError("invalid LittleIntPacker descriptor") from error
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
            or info["schema_version"] != "tscb.littleintpacker-container.v1"
            or info["algorithm"] != self.algorithm
            or info["track"] != "VALUE"
        ):
            raise ExecutionContractError("LittleIntPacker descriptor identity")
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
            or set(params) != {"codec", "isa", "bit_width", "width_mode"}
            or params["codec"] != KEYS[self.algorithm][0]
            or type(info["timestamp_unit"]) is not str
            or type(info["timestamp_epoch"]) is not str
            or type(info["value_units"]) is not list
            or len(info["value_units"]) > 1
            or any(type(u) is not str for u in info["value_units"])
        ):
            raise ExecutionContractError("LittleIntPacker descriptor geometry/parameters")
        normalized_parameters(self.algorithm, {k: v for k, v in params.items() if k != "codec"})
        frame = memoryview(stream)[PREFIX.size + length :]
        if len(frame) < 40:
            raise ExecutionContractError("truncated LittleIntPacker native frame")
        magic, n, kind, width, mode, payload = FRAME.unpack_from(frame)
        if (
            magic != b"TSCBLIP1"
            or n != count
            or kind != list(KEYS).index(self.algorithm)
            or width > 32
            or mode != int(params["width_mode"] == "AUTO")
            or (not mode and width != params["bit_width"])
            or payload != (count * width + 7) // 8
            or len(frame) != 40 + payload
        ):
            raise ExecutionContractError("LittleIntPacker descriptor/native frame mismatch")
        return header, info, frame

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        self._open()
        if not self._finalized:
            raise ExecutionContractError("LittleIntPacker accounting before finalize")
        header, info, frame = self._parse(stream)
        expected, _ = self._payload(routed)
        if (
            header != self._header
            or header != expected
            or hashlib.sha256(stream).digest() != self._digest
        ):
            raise ExecutionContractError("LittleIntPacker encoded object changed")
        native = self._json("tscb_get_accounting_json")
        width = FRAME.unpack_from(frame)[3]
        bits, payload = info["count"] * width, len(frame) - 40
        expected_native = {
            "container_bits": 64,
            "metadata_bits": 192,
            "checksum_bits": 64,
            "value_bits": bits,
            "padding_bits": payload * 8 - bits,
            "final_bits": len(frame) * 8,
            "count": info["count"],
            "bit_width": width,
            "codec_variant": KEYS[self.algorithm][0],
            "width_mode": info["parameters"]["width_mode"],
            "original_payload_bytes": payload,
            "external_padding_bytes": 0,
        }
        if native != expected_native or any(
            type(native[k]) is not type(v) for k, v in expected_native.items()
        ):
            raise ExecutionContractError("LittleIntPacker native ledger mismatch")
        return AccountingLedger.create(
            track=BenchmarkTrack.VALUE,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            value_bits=bits,
            padding_bits=native["padding_bits"],
            metadata_bits=len(header) * 8 + 192,
            container_bits=160,
            checksum_bits=320,
            accounting_method="EXACT_DESCRIPTOR_LIP1_FIXED_WIDTH_VALUES_TAIL_AND_CHECKSUM",
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
            raise ExecutionContractError("LittleIntPacker decoded length")
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
