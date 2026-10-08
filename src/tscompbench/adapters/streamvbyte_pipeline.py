"""Explicit A/B/C/D executor around the frozen lzbench Stream VByte APIs."""

from __future__ import annotations

import ctypes
import hashlib
import json
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.execution.protocol import (
    DecodedOutput,
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
    SourceDomainError,
)
from tscompbench.ids import canonical_json_bytes
from tscompbench.preprocess.streamvbyte import EXECUTOR_ID

from .deflate_zlib import _Buffer
from .streamvbyte import (
    _LIMIT,
    _MAGIC,
    _PREFIX,
    StreamVByteAdapter,
    StreamVByteSession,
    _buffer,
)

_FRAME = struct.Struct("<8sIq")
_SWITCHES = ("stage_a", "stage_b", "stage_c", "stage_d")


def _flags(parameters: dict[str, Any]) -> dict[str, bool]:
    flags = {key: parameters.get(key, True) for key in _SWITCHES}
    if any(type(value) is not bool for value in flags.values()):
        raise ExecutionContractError("pipeline switches must be boolean")
    if not flags["stage_d"]:
        raise ExecutionContractError("stage D is required for a self-contained P2 object")
    return flags


@dataclass(frozen=True)
class StreamVBytePipelineAdapter(StreamVByteAdapter):
    pipeline_executor_id = EXECUTOR_ID

    def create_session(self, parameters: dict[str, Any]) -> StreamVBytePipelineSession:
        if parameters.get("isa", "SSE4_1") != "SSE4_1":
            raise ExecutionContractError("Stream VByte requires the reviewed SSE4_1 path")
        return StreamVBytePipelineSession(self.library_path, self.algorithm, parameters)

    def inspect_preprocess(self, routed: RoutedInput, parameters: dict[str, Any]) -> dict:
        session = self.create_session(parameters)
        try:
            header, original = session._payload(routed)
            stream, snapshot = session._forward(header, original)
            _, inverses = session._decode(stream)
            return {
                **snapshot,
                **inverses,
                "original": original,
                "descriptor": header,
                "stream": stream,
                "timestamp_unit": routed.timestamp_unit,
                "timestamp_epoch": routed.timestamp_epoch,
            }
        finally:
            session.close()


class StreamVBytePipelineSession(StreamVByteSession):
    pipeline_executor_id = EXECUTOR_ID

    def __init__(self, path: Path, algorithm: str, parameters: dict[str, Any]):
        if algorithm != self.pipeline_key:
            raise ExecutionContractError("stage executor requires the declared P2 identity")
        self.flags = _flags(parameters)
        if type(parameters.get("stage_timing", True)) is not bool:
            raise ExecutionContractError("stage_timing must be boolean")
        self.stage_timing_enabled = parameters.get("stage_timing", True)
        self._last_c = self.flags["stage_c"]
        super().__init__(path, algorithm, parameters)
        if self._native.manifest.get("stage_api_version") != 1:
            self.close()
            raise ExecutionContractError("native library has no reviewed stage API")
        lib = self._native.library
        common = [ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(_Buffer)]
        lib.tscb_svb_stage_a.argtypes = [
            *common,
            ctypes.POINTER(ctypes.c_int64),
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        for name in ("tscb_svb_stage_b", "tscb_svb_stage_c"):
            getattr(lib, name).argtypes = [*common, ctypes.c_uint32, ctypes.c_uint32]
        for name in ("tscb_svb_stage_a", "tscb_svb_stage_b", "tscb_svb_stage_c"):
            getattr(lib, name).restype = ctypes.c_uint32

    def native_timing(self) -> tuple[int, int] | None:
        return super().native_timing() if self._last_c else None

    def _payload(self, routed: RoutedInput) -> tuple[bytes, np.ndarray]:
        header, original = super()._payload(routed)
        info = json.loads(header)
        info.update(
            schema_version="tscb.streamvbyte-pipeline-container.v1",
            pipeline_executor_id=self.pipeline_executor_id,
            stage_flags=self.flags,
        )
        header = canonical_json_bytes(info)
        if len(header) > 4096:
            raise ExecutionContractError("Stream VByte descriptor exceeds 4096-byte limit")
        return header, original

    def output_bound(self, routed: RoutedInput) -> int:
        header, array = self._payload(routed)
        elements = max(0, array.size - 1) if self.flags["stage_a"] else array.size
        words = 2 * elements
        return (
            _PREFIX.size
            + len(header)
            + _FRAME.size
            + 4
            + 4 * words
            + ((words + 3) // 4 if self.flags["stage_c"] else 0)
        )

    def _stage(
        self,
        slot: str,
        source: np.ndarray | bytes,
        target: np.ndarray | bytearray,
        *,
        inverse: bool,
        enabled: bool,
        seed: ctypes.c_int64 | None = None,
    ) -> int | None:
        # Copies, allocation and FFI around C belong to the stage wall boundary.
        start = time.perf_counter_ns() if self.stage_timing_enabled and enabled else None
        if isinstance(source, bytes):
            storage = bytearray(source)
            src_ref = (ctypes.c_ubyte * len(storage)).from_buffer(storage)
            src = _buffer(ctypes.addressof(src_ref), len(storage), len(storage), 11)
        else:
            src = _buffer(
                source.ctypes.data,
                source.nbytes,
                source.nbytes,
                8
                if source.dtype.itemsize == 8 and source.dtype.kind == "u"
                else 7
                if source.dtype.itemsize == 8
                else 6,
            )
        if isinstance(target, bytearray):
            dst_ref = (ctypes.c_ubyte * len(target)).from_buffer(target)
            dst = _buffer(ctypes.addressof(dst_ref), len(target), 0, 11)
        else:
            dst = _buffer(
                target.ctypes.data,
                target.nbytes,
                0,
                8
                if target.dtype.itemsize == 8 and target.dtype.kind == "u"
                else 7
                if target.dtype.itemsize == 8
                else 6,
            )
        args = [self._handle, ctypes.byref(src), ctypes.byref(dst)]
        if slot == "A":
            args.append(ctypes.byref(seed))
        args += [int(inverse), int(enabled)]
        self._check(
            getattr(self._native.library, "tscb_svb_stage_" + slot.lower())(*args), "stage " + slot
        )
        if isinstance(target, bytearray):
            del dst_ref  # Release ctypes' buffer export before shrinking to used bytes.
            del target[int(dst.used_bytes) :]
        elif dst.used_bytes != target.nbytes:
            raise ExecutionContractError("stage output length mismatch")
        return None if start is None else time.perf_counter_ns() - start

    def _observations(
        self,
        direction: str,
        timings: dict[str, int | None],
        sizes: dict[str, tuple[int, int]],
        flags: dict[str, bool],
        contributions: dict[str, int] | None = None,
    ) -> None:
        self._telemetry = {
            "scope": "ONE_" + direction.upper() + "_OBJECT",
            "internal_padding_bytes": 16,
            "padding_stream_bits": 0,
            "cost_scope": "CORE_PIPELINE",
            "is_peak_rss_measurement": False,
            "pipeline_stages": {
                "schema_version": "tscb.pipeline-stage-observation.v1",
                "executor_id": self.pipeline_executor_id,
                "timing_enabled": self.stage_timing_enabled,
                "timing_boundary": "PYTHON_STAGE_FFI_AND_NATIVE_WORK_EXCLUDES_CONTEXT_LIFECYCLE",
                "stages": {
                    slot: {
                        "enabled": flags["stage_" + slot.lower()],
                        "wall_ns": timings[slot],
                        "input_bytes": sizes[slot][0],
                        "output_bytes": sizes[slot][1],
                        "final_contribution_bits": None
                        if contributions is None
                        else contributions[slot],
                    }
                    for slot in "ABCD"
                },
            },
            "native_input_bytes_per_iteration": sizes["C"][1 if direction == "decode" else 0],
        }

    def _forward(self, header: bytes, original: np.ndarray) -> tuple[bytes, dict]:
        original = np.ascontiguousarray(original)
        flags = self.flags
        a_count = max(0, original.size - 1) if flags["stage_a"] else original.size
        a = np.empty(a_count, dtype="<u8")
        seed = ctypes.c_int64()
        timings = {
            "A": self._stage("A", original, a, inverse=False, enabled=flags["stage_a"], seed=seed)
        }
        b = np.empty(2 * a_count, dtype="<u4")
        timings["B"] = self._stage("B", a, b, inverse=False, enabled=flags["stage_b"])
        c = bytearray(4 + b.nbytes + ((b.size + 3) // 4 if flags["stage_c"] else 0))
        timings["C"] = self._stage("C", b, c, inverse=False, enabled=flags["stage_c"])
        start = time.perf_counter_ns() if self.stage_timing_enabled else None
        stream = (
            _PREFIX.pack(_MAGIC, len(header), hashlib.sha256(header).digest())
            + header
            + _FRAME.pack(b"TSCBS641", original.size, seed.value)
            + c
        )
        timings["D"] = None if start is None else time.perf_counter_ns() - start
        seed_bytes = 8 if flags["stage_a"] and original.size else 0
        self._observations(
            "encode",
            timings,
            {
                "A": (original.nbytes, a.nbytes),
                "B": (a.nbytes, b.nbytes),
                "C": (b.nbytes, len(c)),
                "D": (len(c), len(stream)),
            },
            flags,
            {
                "A": seed_bytes * 8,
                "B": 0,
                "C": len(c) * 8,
                "D": (len(stream) - len(c) - seed_bytes) * 8,
            },
        )
        return stream, {"A": a, "B": b, "C": bytes(c), "seed": seed.value, "flags": flags}

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated or self._finalized:
            raise ExecutionContractError("Stream VByte update lifecycle")
        header, original = self._payload(routed)
        if len(destination) < self.output_bound(routed):
            raise OutputCapacityError("Stream VByte bound capacity")
        try:
            stream, _ = self._forward(header, original)
        except SourceDomainError as error:
            # Forward stages only write their own allocations; destination is untouched.
            error.rejection_atomic = True
            raise
        destination[: len(stream)] = stream
        self._header, self._updated = header, True
        return len(stream)

    def _parse(self, stream: bytes) -> tuple[bytes, dict[str, Any], bytes]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated Stream VByte container")
        magic, length, digest = _PREFIX.unpack_from(stream)
        if magic != _MAGIC or length > 4096 or length > len(stream) - _PREFIX.size:
            raise ExecutionContractError("invalid pipeline container prefix")
        header = stream[_PREFIX.size : _PREFIX.size + length]
        if hashlib.sha256(header).digest() != digest:
            raise ExecutionContractError("pipeline descriptor checksum")
        try:
            info = json.loads(header)
            if not isinstance(info, dict):
                raise ValueError("descriptor is not an object")
            flags = _flags(info.get("stage_flags", {}))
        except (ValueError, UnicodeError, TypeError, AttributeError) as error:
            raise ExecutionContractError("invalid pipeline descriptor") from error
        count, buffer = info.get("count"), info.get("buffer")
        if (
            info.get("schema_version") != "tscb.streamvbyte-pipeline-container.v1"
            or info.get("algorithm") != self.algorithm
            or info.get("pipeline_executor_id") != self.pipeline_executor_id
            or info.get("stage_flags") != flags
            or set(flags) != set(info.get("stage_flags", {}))
            or info.get("track") != self.track
            or info.get("codec_stages")
            != [
                "CHECKED_DELTA_I64",
                "ZIGZAG_U64",
                "INTERLEAVED_LOW_HIGH_U32",
                self.backend_stage_name,
            ]
            or type(count) is not int
            or not 0 <= count <= _LIMIT
            or not isinstance(buffer, dict)
            or buffer.get("name") != "timestamp"
            or buffer.get("dtype") != "<i8"
            or buffer.get("shape") != [count]
            or type(buffer["shape"][0]) is not int
            or type(buffer.get("logical_bits")) is not int
            or buffer.get("logical_bits") != count * 64
            or not isinstance(info.get("timestamp_unit"), str)
            or not isinstance(info.get("timestamp_epoch"), str)
            or not isinstance(info.get("value_units"), list)
            or any(not isinstance(unit, str) for unit in info["value_units"])
        ):
            raise ExecutionContractError("pipeline descriptor identity/geometry")
        payload = stream[_PREFIX.size + length :]
        words = 2 * (max(0, count - 1) if flags["stage_a"] else count)
        controls = (words + 3) // 4 if flags["stage_c"] else 0
        minimum = _FRAME.size + 4 + controls + (words if flags["stage_c"] else 4 * words)
        maximum = _FRAME.size + 4 + controls + 4 * words
        if not minimum <= len(payload) <= maximum:
            raise ExecutionContractError("pipeline payload/count size")
        identity, n, seed = _FRAME.unpack_from(payload)
        if (
            identity != b"TSCBS641"
            or n != count
            or ((not flags["stage_a"] or not count) and seed != 0)
        ):
            raise ExecutionContractError("pipeline native identity/count/seed")
        return header, info, payload

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("Stream VByte accounting before finalize")
        header, info, payload = self._parse(stream)
        if header != self._header:
            raise ExecutionContractError("pipeline descriptor changed")
        seed_bytes = 8 if info["stage_flags"]["stage_a"] and info["count"] else 0
        metadata_bytes = _FRAME.size + 4 - seed_bytes
        return AccountingLedger.create(
            track=self.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            container_bits=12 * 8,
            checksum_bits=32 * 8,
            metadata_bits=(len(header) + metadata_bytes) * 8,
            timestamp_bits=(len(payload) - metadata_bytes) * 8,
            accounting_method="EXACT_STAGE_DESCRIPTOR_SEED_COUNT_AND_BACKEND_BYTES",
        )

    def _decode(self, stream: bytes) -> tuple[DecodedOutput, dict]:
        start = time.perf_counter_ns() if self.stage_timing_enabled else None
        _, info, payload = self._parse(stream)
        flags = info["stage_flags"]
        self._last_c = flags["stage_c"]
        count = info["count"]
        _, _, seed_value = _FRAME.unpack_from(payload)
        c = payload[_FRAME.size :]
        timings = {"D": None if start is None else time.perf_counter_ns() - start}
        a_count = max(0, count - 1) if flags["stage_a"] else count
        b = np.empty(2 * a_count, dtype="<u4")
        timings["C"] = self._stage("C", c, b, inverse=True, enabled=flags["stage_c"])
        a = np.empty(a_count, dtype="<u8")
        timings["B"] = self._stage("B", b, a, inverse=True, enabled=flags["stage_b"])
        original = np.empty(count, dtype="<i8")
        seed = ctypes.c_int64(seed_value)
        timings["A"] = self._stage(
            "A", a, original, inverse=True, enabled=flags["stage_a"], seed=seed
        )
        self._observations(
            "decode",
            timings,
            {
                "D": (len(stream), len(c)),
                "C": (len(c), b.nbytes),
                "B": (b.nbytes, a.nbytes),
                "A": (a.nbytes, original.nbytes),
            },
            flags,
        )
        original.flags.writeable = False
        return (
            DecodedOutput((LogicalBuffer("timestamp", original, count * 64),)),
            {"inverse_A": original, "inverse_B": a, "inverse_C": b},
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        return self._decode(stream)[0]
