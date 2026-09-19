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

from .deflate_zlib import _Buffer, _buffer
from .native_timing import NativeTimingProbe

_PREFIX = struct.Struct("<8sI")
_MAGICS = {"huff0": b"TSCBHUF\0", "fse": b"TSCBFSE\0"}


class _Library:
    def __init__(self, path: Path, algorithm: str):
        try:
            self.library = ctypes.CDLL(str(path))
        except OSError as exc:
            raise ExecutionContractError(f"cannot load {algorithm}: {exc}") from exc
        lib = self.library
        lib.tscb_get_abi_version.argtypes = []
        lib.tscb_get_abi_version.restype = ctypes.c_uint32
        lib.tscb_get_manifest_json.argtypes = [
            ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_uint64),
        ]
        lib.tscb_get_manifest_json.restype = ctypes.c_uint32
        lib.tscb_create.argtypes = [
            ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.tscb_create.restype = ctypes.c_uint32
        lib.tscb_destroy.argtypes = [ctypes.c_void_p]
        lib.tscb_destroy.restype = ctypes.c_uint32
        lib.tscb_compress_bound.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(ctypes.c_uint64),
        ]
        lib.tscb_compress_bound.restype = ctypes.c_uint32
        for name in ("tscb_compress", "tscb_decompress"):
            func = getattr(lib, name)
            func.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer), ctypes.POINTER(_Buffer)]
            func.restype = ctypes.c_uint32
        lib.tscb_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer)]
        lib.tscb_finalize.restype = ctypes.c_uint32
        if lib.tscb_get_abi_version() != 1:
            raise ExecutionContractError("entropy adapter ABI mismatch")
        pointer, length = ctypes.c_char_p(), ctypes.c_uint64()
        if lib.tscb_get_manifest_json(ctypes.byref(pointer), ctypes.byref(length)):
            raise ExecutionContractError("entropy adapter manifest missing")
        info = json.loads(ctypes.string_at(pointer, length.value))
        if info.get("algorithm") != algorithm or info.get("threading") != "SINGLE_THREAD":
            raise ExecutionContractError("entropy adapter variant mismatch")


@dataclass(frozen=True)
class EntropyAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]
    algorithm: str

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> EntropySession:
        return EntropySession(self.library_path, self.algorithm, parameters)


class EntropySession:
    def __init__(self, library_path: Path, algorithm: str, parameters: dict[str, Any]):
        if (algorithm not in _MAGICS or parameters.get("isa", "SCALAR") != "SCALAR"
                or type(parameters.get("native_timing", True)) is not bool):
            raise ExecutionContractError("unregistered entropy variant or timing")
        self.algorithm = algorithm
        self._native = _Library(library_path, algorithm)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes({"algorithm": algorithm})
        status = self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle))
        if status or not self._handle.value:
            raise ExecutionContractError(f"entropy adapter create failed ({status})")
        self._updated = self._finalized = False
        self._header = b""
        try:
            self._timing = NativeTimingProbe(
                self._native.library, self._handle,
                enabled=parameters.get("native_timing", True),
            )
        except Exception:
            self.close()
            raise

    def native_timing(self) -> tuple[int, int] | None:
        if not self._handle.value:
            raise ExecutionContractError("native timing queried after close")
        return self._timing.read()

    @staticmethod
    def _header_for(routed: RoutedInput, algorithm: str) -> bytes:
        return canonical_json_bytes({
            "schema_version": f"tscb.{algorithm}-container.v1",
            "track": routed.track,
            "segment_plan_id": routed.segment_plan_id,
            "buffers": [{
                "name": item.name, "dtype": item.array.dtype.str,
                "shape": list(item.array.shape), "logical_bits": item.logical_bits,
                "payload_bytes": item.array.nbytes,
            } for item in routed.buffers],
        })

    def _check(self, status: int, operation: str) -> None:
        if status == 0:
            return
        if status == 3:
            raise OutputCapacityError(f"{operation}: destination too small")
        raise ExecutionContractError(f"{self.algorithm} {operation} failed ({status})")

    def output_bound(self, routed: RoutedInput) -> int:
        total = sum(item.array.nbytes for item in routed.buffers)
        buffer, bound = _buffer(1, capacity=total, used=total), ctypes.c_uint64()
        self._check(self._native.library.tscb_compress_bound(
            self._handle, ctypes.byref(buffer), ctypes.byref(bound)), "compress_bound")
        return _PREFIX.size + len(self._header_for(routed, self.algorithm)) + bound.value

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("entropy update called twice")
        header = self._header_for(routed, self.algorithm)
        preamble = _PREFIX.pack(_MAGICS[self.algorithm], len(header)) + header
        if len(destination) < len(preamble) + 9:
            raise OutputCapacityError("entropy container destination too small")
        destination[:len(preamble)] = preamble
        payload = bytearray().join(item.array.tobytes(order="C") for item in routed.buffers)
        input_store = payload or bytearray(1)
        input_array = (ctypes.c_ubyte * len(input_store)).from_buffer(input_store)
        native_out = destination[len(preamble):]
        out_array = (ctypes.c_ubyte * len(native_out)).from_buffer(native_out)
        src = _buffer(ctypes.addressof(input_array), capacity=len(payload), used=len(payload))
        dst = _buffer(ctypes.addressof(out_array), capacity=len(native_out), used=0)
        self._check(self._native.library.tscb_compress(
            self._handle, ctypes.byref(src), ctypes.byref(dst)), "compress")
        self._header = header
        self._updated = True
        return len(preamble) + int(dst.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated or self._finalized:
            raise ExecutionContractError("entropy finalize requires one update")
        if len(destination) == 0:
            destination = memoryview(bytearray(1))
        out_array = (ctypes.c_ubyte * len(destination)).from_buffer(destination)
        dst = _buffer(ctypes.addressof(out_array), capacity=len(destination), used=0)
        self._check(self._native.library.tscb_finalize(self._handle, ctypes.byref(dst)), "finalize")
        self._finalized = True
        return int(dst.used_bytes)

    def _parse(self, stream: bytes) -> tuple[bytes, list[dict[str, Any]], bytes]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated entropy container")
        magic, size = _PREFIX.unpack_from(stream)
        if magic != _MAGICS[self.algorithm] or size > len(stream) - _PREFIX.size:
            raise ExecutionContractError("invalid entropy container prefix")
        header = stream[_PREFIX.size:_PREFIX.size + size]
        try:
            info = json.loads(header)
        except (UnicodeError, ValueError) as exc:
            raise ExecutionContractError("invalid entropy descriptor") from exc
        if info.get("schema_version") != f"tscb.{self.algorithm}-container.v1":
            raise ExecutionContractError("entropy descriptor version mismatch")
        descriptors = info.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("entropy descriptor missing buffers")
        return header, descriptors, stream[_PREFIX.size + size:]

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("accounting before finalize")
        header, _, frame = self._parse(stream)
        if header != self._header or len(frame) < 9:
            raise ExecutionContractError("entropy stream does not match its descriptor")
        components = {"metadata_bits": len(header) * 8,
                      "container_bits": (_PREFIX.size + 9) * 8}
        if routed.track is BenchmarkTrack.TIMESTAMP:
            components["timestamp_bits"] = (len(frame) - 9) * 8
        elif routed.track is BenchmarkTrack.VALUE:
            components["value_bits"] = (len(frame) - 9) * 8
        else:
            components["unallocated_shared_bits"] = (len(frame) - 9) * 8
        return AccountingLedger.create(
            track=routed.track, canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="EXACT_ENTROPY_MODE_LENGTH_AND_DESCRIPTOR_V1", **components)

    def decompress(self, stream: bytes) -> DecodedOutput:
        _, descriptors, frame = self._parse(stream)
        try:
            lengths = [int(item["payload_bytes"]) for item in descriptors]
            if any(length < 0 for length in lengths) or sum(lengths) > 128 * 1024:
                raise ValueError("bad output length")
            total = sum(lengths)
            if len(frame) < 9 or int.from_bytes(frame[1:9], "little") != total:
                raise ValueError("encoded size mismatch")
            input_store = bytearray(frame)
            output_store = bytearray(max(1, total))
            input_array = (ctypes.c_ubyte * len(input_store)).from_buffer(input_store)
            output_array = (ctypes.c_ubyte * len(output_store)).from_buffer(output_store)
            src = _buffer(ctypes.addressof(input_array), capacity=len(frame), used=len(frame))
            dst = _buffer(ctypes.addressof(output_array), capacity=total, used=0)
            self._check(self._native.library.tscb_decompress(
                self._handle, ctypes.byref(src), ctypes.byref(dst)), "decompress")
            if dst.used_bytes != total:
                raise ValueError("decoded size mismatch")
            cursor, buffers = 0, []
            for item, length in zip(descriptors, lengths, strict=True):
                dtype = np.dtype(item["dtype"])
                shape = tuple(int(size) for size in item["shape"])
                if (any(size < 0 for size in shape)
                        or int(np.prod(shape, dtype=np.int64)) * dtype.itemsize != length):
                    raise ValueError("invalid shape")
                array = np.frombuffer(
                    output_store[cursor:cursor + length], dtype=dtype
                ).copy().reshape(shape)
                array.flags.writeable = False
                buffers.append(LogicalBuffer(item["name"], array, int(item["logical_bits"])))
                cursor += length
            return DecodedOutput(tuple(buffers))
        except (KeyError, TypeError, OverflowError, ValueError) as exc:
            raise ExecutionContractError(f"invalid entropy stream: {exc}") from exc

    def close(self) -> None:
        if self._handle.value:
            status = self._native.library.tscb_destroy(self._handle)
            self._handle = ctypes.c_void_p()
            self._check(status, "destroy")
