from __future__ import annotations

import ctypes
import json
import struct
import zlib
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

from .native_timing import NativeTimingProbe

_ABI_VERSION = 1
_STATUS_OK = 0
_STATUS_DST_TOO_SMALL = 3
_DTYPE_BYTES = 11
_OWNERSHIP_BORROWED = 0
_MAX_RANK = 8
_PREFIX = struct.Struct("<8sI")
_MAGIC = b"TSCBDFL\x00"


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


def _alignment(address: int) -> int:
    value = 1
    while value < 64 and address % (value * 2) == 0:
        value *= 2
    return value


def _buffer(address: int, *, capacity: int, used: int) -> _Buffer:
    shape = (ctypes.c_uint64 * _MAX_RANK)()
    strides = (ctypes.c_int64 * _MAX_RANK)()
    shape[0] = used
    strides[0] = 1
    return _Buffer(
        ctypes.c_void_p(address),
        capacity,
        used,
        _DTYPE_BYTES,
        1,
        shape,
        strides,
        _alignment(address) if address > 1 else 1,
        _OWNERSHIP_BORROWED,
        0,
    )


class _NativeLibrary:
    def __init__(self, path: Path):
        try:
            self.library = ctypes.CDLL(str(path))
        except OSError as error:
            raise ExecutionContractError(
                f"cannot load zlib DEFLATE adapter artifact {path}: {error}"
            ) from error
        self._bind()
        if int(self.library.tscb_get_abi_version()) != _ABI_VERSION:
            raise ExecutionContractError("zlib DEFLATE adapter ABI version mismatch")
        manifest_pointer = ctypes.c_char_p()
        manifest_length = ctypes.c_uint64()
        status = int(
            self.library.tscb_get_manifest_json(
                ctypes.byref(manifest_pointer), ctypes.byref(manifest_length)
            )
        )
        if status != _STATUS_OK:
            raise ExecutionContractError(
                "zlib DEFLATE adapter failed to expose its native manifest"
            )
        manifest = json.loads(ctypes.string_at(manifest_pointer, manifest_length.value))
        if manifest.get("algorithm") != "deflate-zlib":
            raise ExecutionContractError("loaded C ABI artifact is not the zlib DEFLATE adapter")
        if (
            manifest.get("dictionary") != "NONE"
            or manifest.get("stream") != "RFC1950_ZLIB_WITH_RFC1951_DEFLATE"
            or manifest.get("checksum") != "ADLER32"
            or manifest.get("threading") != "SINGLE_THREAD"
            or manifest.get("streaming") != "PERSISTENT_UPDATE_AND_INFLATE_CONTEXTS"
        ):
            raise ExecutionContractError(
                "zlib DEFLATE artifact violates the registered execution mode"
            )

    def _bind(self) -> None:
        library = self.library
        library.tscb_get_abi_version.argtypes = []
        library.tscb_get_abi_version.restype = ctypes.c_uint32
        library.tscb_get_manifest_json.argtypes = [
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        library.tscb_get_manifest_json.restype = ctypes.c_uint32
        library.tscb_create.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint64,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        library.tscb_create.restype = ctypes.c_uint32
        library.tscb_destroy.argtypes = [ctypes.c_void_p]
        library.tscb_destroy.restype = ctypes.c_uint32
        library.tscb_compress_bound.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        library.tscb_compress_bound.restype = ctypes.c_uint32
        library.tscb_compress.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(_Buffer),
        ]
        library.tscb_compress.restype = ctypes.c_uint32
        library.tscb_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(_Buffer)]
        library.tscb_finalize.restype = ctypes.c_uint32
        library.tscb_decompress.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(_Buffer),
        ]
        library.tscb_decompress.restype = ctypes.c_uint32
        library.tscb_get_last_error.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        library.tscb_get_last_error.restype = ctypes.c_uint32
        library.tscb_zlib_stream_update.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(_Buffer),
        ]
        library.tscb_zlib_stream_update.restype = ctypes.c_uint32
        library.tscb_zlib_stream_finalize.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
        ]
        library.tscb_zlib_stream_finalize.restype = ctypes.c_uint32
        library.tscb_zlib_stream_decoder_reset.argtypes = [ctypes.c_void_p]
        library.tscb_zlib_stream_decoder_reset.restype = ctypes.c_uint32
        library.tscb_zlib_stream_decompress_update.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(_Buffer),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        library.tscb_zlib_stream_decompress_update.restype = ctypes.c_uint32
        library.tscb_zlib_stream_decoder_finish.argtypes = [ctypes.c_void_p]
        library.tscb_zlib_stream_decoder_finish.restype = ctypes.c_uint32
        library.tscb_zlib_stream_state_bytes.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint64),
        ]
        library.tscb_zlib_stream_state_bytes.restype = ctypes.c_uint32


@dataclass(frozen=True)
class DeflateZlibAdapter:
    library_path: Path
    manifest_adapter: dict[str, Any]

    @property
    def adapter_id(self) -> str:
        return stable_id("adapter", self.manifest_adapter)

    @property
    def deterministic(self) -> bool:
        return True

    def create_session(self, parameters: dict[str, Any]) -> DeflateZlibSession:
        return DeflateZlibSession(self.library_path, parameters)

    def create_stream_session(self, parameters: dict[str, Any]) -> DeflateZlibStreamSession:
        return DeflateZlibStreamSession(self.library_path, parameters)


class DeflateZlibSession:
    def __init__(self, library_path: Path, parameters: dict[str, Any]):
        self._native = _NativeLibrary(library_path)
        self._handle = ctypes.c_void_p()
        config = canonical_json_bytes(
            {
                "compression_level": int(parameters.get("compression_level", 6)),
                "window_bits": int(parameters.get("window_bits", 15)),
            }
        )
        status = int(
            self._native.library.tscb_create(config, len(config), ctypes.byref(self._handle))
        )
        if status != _STATUS_OK or not self._handle.value:
            raise ExecutionContractError(
                f"native zlib DEFLATE adapter create failed with status {status}"
            )
        self._updated = False
        self._finalized = False
        self._header = b""
        self._window_bits = int(parameters.get("window_bits", 15))
        try:
            self._native_timing = NativeTimingProbe(
                self._native.library, self._handle,
                enabled=bool(parameters.get("native_timing", True)),
            )
        except Exception:
            self.close()
            raise

    def native_timing(self) -> tuple[int, int] | None:
        if not self._handle.value:
            raise ExecutionContractError("native timing queried after session close")
        return self._native_timing.read()

    def _last_error(self) -> str:
        pointer = ctypes.c_char_p()
        length = ctypes.c_uint64()
        status = int(
            self._native.library.tscb_get_last_error(
                self._handle, ctypes.byref(pointer), ctypes.byref(length)
            )
        )
        if status != _STATUS_OK or not pointer:
            return "native adapter supplied no error detail"
        return ctypes.string_at(pointer, length.value).decode("utf-8", errors="replace")

    def _check(self, status: int, operation: str) -> None:
        if status == _STATUS_OK:
            return
        if status == _STATUS_DST_TOO_SMALL:
            raise OutputCapacityError(f"{operation}: destination is too small")
        raise ExecutionContractError(f"{operation} failed ({status}): {self._last_error()}")

    @staticmethod
    def _descriptor_header(routed: RoutedInput) -> bytes:
        descriptors = [
            {
                "dtype": item.array.dtype.str,
                "logical_bits": item.logical_bits,
                "name": item.name,
                "payload_bytes": item.array.nbytes,
                "shape": list(item.array.shape),
            }
            for item in routed.buffers
        ]
        return canonical_json_bytes(
            {
                "buffers": descriptors,
                "schema_version": "tscb.deflate-zlib-container.v1",
                "segment_plan_id": routed.segment_plan_id,
                "track": routed.track,
            }
        )

    def _native_bound(self, payload_bytes: int) -> int:
        input_buffer = _buffer(1, capacity=payload_bytes, used=payload_bytes)
        bound = ctypes.c_uint64()
        status = int(
            self._native.library.tscb_compress_bound(
                self._handle, ctypes.byref(input_buffer), ctypes.byref(bound)
            )
        )
        self._check(status, "compress_bound")
        return int(bound.value)

    def output_bound(self, routed: RoutedInput) -> int:
        header = self._descriptor_header(routed)
        payload_bytes = sum(item.array.nbytes for item in routed.buffers)
        return _PREFIX.size + len(header) + self._native_bound(payload_bytes)

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("compress_update may be called once per zlib DEFLATE")
        header = self._descriptor_header(routed)
        preamble = _PREFIX.pack(_MAGIC, len(header)) + header
        if len(destination) < len(preamble):
            raise OutputCapacityError("destination cannot hold the zlib DEFLATE container header")
        destination[: len(preamble)] = preamble
        payload = bytearray().join(item.array.tobytes(order="C") for item in routed.buffers)
        input_storage = payload if payload else bytearray(1)
        input_array = (ctypes.c_ubyte * len(input_storage)).from_buffer(input_storage)
        native_destination = destination[len(preamble) :]
        output_array = (ctypes.c_ubyte * len(native_destination)).from_buffer(native_destination)
        input_buffer = _buffer(
            ctypes.addressof(input_array), capacity=len(payload), used=len(payload)
        )
        output_buffer = _buffer(
            ctypes.addressof(output_array), capacity=len(native_destination), used=0
        )
        status = int(
            self._native.library.tscb_compress(
                self._handle, ctypes.byref(input_buffer), ctypes.byref(output_buffer)
            )
        )
        self._check(status, "compress_update")
        self._header = header
        self._updated = True
        return len(preamble) + int(output_buffer.used_bytes)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated:
            raise ExecutionContractError("finalize requires a preceding compress_update")
        if self._finalized:
            raise ExecutionContractError("repeated finalize is forbidden")
        output_array = (ctypes.c_ubyte * len(destination)).from_buffer(destination)
        output_buffer = _buffer(ctypes.addressof(output_array), capacity=len(destination), used=0)
        status = int(self._native.library.tscb_finalize(self._handle, ctypes.byref(output_buffer)))
        self._check(status, "finalize")
        self._finalized = True
        return int(output_buffer.used_bytes)

    @staticmethod
    def _parse_container(stream: bytes) -> tuple[dict[str, Any], bytes]:
        if len(stream) < _PREFIX.size:
            raise ExecutionContractError("truncated zlib DEFLATE container")
        magic, header_length = _PREFIX.unpack_from(stream)
        if magic != _MAGIC:
            raise ExecutionContractError("invalid zlib DEFLATE container magic")
        header_end = _PREFIX.size + header_length
        if header_end > len(stream):
            raise ExecutionContractError("truncated zlib DEFLATE container metadata")
        try:
            header = json.loads(stream[_PREFIX.size : header_end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExecutionContractError("invalid zlib DEFLATE container metadata") from error
        if header.get("schema_version") != "tscb.deflate-zlib-container.v1":
            raise ExecutionContractError("unsupported zlib DEFLATE container version")
        return header, stream[header_end:]

    @staticmethod
    def _serialized_payload(routed: RoutedInput, header: dict[str, Any]) -> bytes:
        if header.get("payload_layout") != "BLOCK_MAJOR_BUFFER_ORDER":
            return b"".join(item.array.tobytes(order="C") for item in routed.buffers)
        block_size = int(header.get("stream_block_size", 0))
        if block_size < 1:
            raise ExecutionContractError("invalid streaming payload block size")
        return b"".join(
            item.array[offset : min(routed.n, offset + block_size)].tobytes(order="C")
            for offset in range(0, routed.n, block_size)
            for item in routed.buffers
        )

    def _inspect_zlib_stream(
        self, stream: bytes, routed: RoutedInput, header: dict[str, Any]
    ) -> bytes:
        if len(stream) < 6:
            raise ExecutionContractError("truncated RFC 1950 zlib stream")
        cmf, flg = stream[0], stream[1]
        if cmf & 0x0F != 8 or cmf >> 4 > 7 or ((cmf << 8) | flg) % 31 != 0:
            raise ExecutionContractError("invalid RFC 1950 zlib header")
        if flg & 0x20:
            raise ExecutionContractError("preset-dictionary zlib stream is not registered")
        if cmf >> 4 != self._window_bits - 8:
            raise ExecutionContractError("zlib stream window does not match the registered config")
        payload = self._serialized_payload(routed, header)
        expected_adler = zlib.adler32(payload) & 0xFFFFFFFF
        observed_adler = int.from_bytes(stream[-4:], "big")
        if observed_adler != expected_adler:
            raise ExecutionContractError("zlib Adler-32 footer does not match routed bytes")
        return stream[2:-4]

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("accounting before finalize is forbidden")
        header, zlib_stream = self._parse_container(stream)
        if canonical_json_bytes(header) != self._header:
            raise ExecutionContractError(
                "zlib DEFLATE descriptor metadata changed after compression"
            )
        deflate_payload = self._inspect_zlib_stream(zlib_stream, routed, header)
        components: dict[str, int] = {
            "metadata_bits": len(self._header) * 8,
            "container_bits": (_PREFIX.size + 2) * 8,
            "checksum_bits": 32,
        }
        has_validity = any(item.name == "validity" for item in routed.buffers)
        if routed.track is BenchmarkTrack.TIMESTAMP:
            components["timestamp_bits"] = len(deflate_payload) * 8
        elif routed.track is BenchmarkTrack.VALUE and not has_validity:
            components["value_bits"] = len(deflate_payload) * 8
        else:
            components["unallocated_shared_bits"] = len(deflate_payload) * 8
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            accounting_method="EXACT_TSCB_CONTAINER_ZLIB_ENVELOPE_AND_DEFLATE_LENGTH",
            **components,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        header, frame = self._parse_container(stream)
        descriptors = header.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("zlib DEFLATE container has no buffer descriptors")
        output_bytes = sum(int(item["payload_bytes"]) for item in descriptors)
        input_storage = bytearray(frame) if frame else bytearray(1)
        output_storage = bytearray(max(1, output_bytes))
        input_array = (ctypes.c_ubyte * len(input_storage)).from_buffer(input_storage)
        output_array = (ctypes.c_ubyte * len(output_storage)).from_buffer(output_storage)
        input_buffer = _buffer(ctypes.addressof(input_array), capacity=len(frame), used=len(frame))
        output_buffer = _buffer(ctypes.addressof(output_array), capacity=output_bytes, used=0)
        status = int(
            self._native.library.tscb_decompress(
                self._handle, ctypes.byref(input_buffer), ctypes.byref(output_buffer)
            )
        )
        self._check(status, "decompress")
        if int(output_buffer.used_bytes) != output_bytes:
            raise ExecutionContractError("zlib DEFLATE decoded byte count does not match metadata")
        return self._decoded_output(header, memoryview(output_storage)[:output_bytes])

    @staticmethod
    def _decoded_output(header: dict[str, Any], payload: memoryview) -> DecodedOutput:
        descriptors = header.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("zlib DEFLATE container has no buffer descriptors")
        output_bytes = len(payload)
        if header.get("payload_layout") == "BLOCK_MAJOR_BUFFER_ORDER":
            block_size = int(header.get("stream_block_size", 0))
            total_n = int(descriptors[0]["shape"][0]) if descriptors else 0
            if block_size < 1 or any(int(item["shape"][0]) != total_n for item in descriptors):
                raise ExecutionContractError("invalid streaming block-layout descriptor")
            separated = [bytearray() for _ in descriptors]
            payload_cursor = 0
            for offset in range(0, total_n, block_size):
                rows = min(block_size, total_n - offset)
                for index, descriptor in enumerate(descriptors):
                    dtype = np.dtype(str(descriptor["dtype"]))
                    shape = tuple(int(value) for value in descriptor["shape"])
                    row_width = int(np.prod(shape[1:], dtype=np.int64)) if len(shape) > 1 else 1
                    length = rows * row_width * dtype.itemsize
                    if payload_cursor + length > output_bytes:
                        raise ExecutionContractError("truncated streaming block-layout payload")
                    separated[index].extend(payload[payload_cursor : payload_cursor + length])
                    payload_cursor += length
            if payload_cursor != output_bytes:
                raise ExecutionContractError("streaming block-layout payload has trailing bytes")
            payload = memoryview(bytearray().join(separated))
        cursor = 0
        decoded: list[LogicalBuffer] = []
        for descriptor in descriptors:
            length = int(descriptor["payload_bytes"])
            dtype = np.dtype(str(descriptor["dtype"]))
            shape = tuple(int(value) for value in descriptor["shape"])
            expected = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize
            if expected != length or cursor + length > output_bytes:
                raise ExecutionContractError("zlib DEFLATE descriptor shape/dtype is inconsistent")
            array = np.frombuffer(payload[cursor : cursor + length], dtype=dtype).copy()
            array = array.reshape(shape)
            array.flags.writeable = False
            decoded.append(
                LogicalBuffer(
                    name=str(descriptor["name"]),
                    array=array,
                    logical_bits=int(descriptor["logical_bits"]),
                )
            )
            cursor += length
        if cursor != output_bytes:
            raise ExecutionContractError("zlib DEFLATE container contains undeclared decoded bytes")
        return DecodedOutput(tuple(decoded))

    def close(self) -> None:
        if self._handle.value:
            status = int(self._native.library.tscb_destroy(self._handle))
            self._handle = ctypes.c_void_p()
            if status != _STATUS_OK:
                raise ExecutionContractError(
                    f"native zlib DEFLATE adapter destroy failed ({status})"
                )


class DeflateZlibStreamSession(DeflateZlibSession):
    """One persistent zlib encoder and decoder context for a routed object."""

    def __init__(self, library_path: Path, parameters: dict[str, Any]):
        super().__init__(library_path, parameters)
        self._routed: RoutedInput | None = None
        self._consumed_n = 0
        self._consumed_payload_bytes = 0
        self._preamble_emitted = False
        self._decode_chunk_bytes = int(parameters.get("stream_decode_chunk_bytes", 16384))
        self._block_size = int(parameters.get("block_size", 65536))
        if self._decode_chunk_bytes < 1 or self._block_size < 1:
            self.close()
            raise ExecutionContractError("streaming block sizes must be positive")

    def stream_start(self, routed: RoutedInput) -> None:
        if self._routed is not None:
            raise ExecutionContractError("stream_start may be called once per stream session")
        self._routed = routed
        header = json.loads(self._descriptor_header(routed))
        header["payload_layout"] = "BLOCK_MAJOR_BUFFER_ORDER"
        header["stream_block_size"] = self._block_size
        self._header = canonical_json_bytes(header)

    def _require_started(self) -> RoutedInput:
        if self._routed is None:
            raise ExecutionContractError("stream_start must precede stream updates")
        return self._routed

    def _validate_chunk(self, chunk: RoutedInput) -> None:
        routed = self._require_started()
        if self._finalized:
            raise ExecutionContractError("stream update after finalize is forbidden")
        if chunk.track is not routed.track or len(chunk.buffers) != len(routed.buffers):
            raise ExecutionContractError("stream chunk routing does not match the started object")
        if chunk.n < 0 or self._consumed_n + chunk.n > routed.n:
            raise ExecutionContractError("stream chunk exceeds the declared routed length")
        expected_rows = min(self._block_size, routed.n - self._consumed_n)
        if chunk.n != expected_rows:
            raise ExecutionContractError("stream chunk length does not match configured block size")
        for expected, observed in zip(routed.buffers, chunk.buffers, strict=True):
            expected_array = np.asarray(expected.array)
            observed_array = np.asarray(observed.array)
            if (
                observed.name != expected.name
                or observed_array.dtype != expected_array.dtype
                or observed_array.ndim != expected_array.ndim
                or observed_array.shape[1:] != expected_array.shape[1:]
                or (observed_array.ndim > 0 and observed_array.shape[0] != chunk.n)
                or observed.logical_bits != observed_array.nbytes * 8
            ):
                raise ExecutionContractError(
                    "stream chunk buffer schema does not match the started object"
                )

    @staticmethod
    def _storage_buffer(data: bytes | bytearray) -> tuple[bytearray, Any, _Buffer]:
        storage = bytearray(data) if data else bytearray(1)
        array = (ctypes.c_ubyte * len(storage)).from_buffer(storage)
        return storage, array, _buffer(
            ctypes.addressof(array), capacity=len(data), used=len(data)
        )

    def _stream_state_bytes(self) -> int:
        state = ctypes.c_uint64()
        status = int(
            self._native.library.tscb_zlib_stream_state_bytes(
                self._handle, ctypes.byref(state)
            )
        )
        self._check(status, "stream_state_bytes")
        return int(state.value)

    def stream_push(self, chunk: RoutedInput) -> Any:
        from tscompbench.measurement.workloads import StreamPushResult

        self._validate_chunk(chunk)
        payload = b"".join(item.array.tobytes(order="C") for item in chunk.buffers)
        input_storage, input_array, input_buffer = self._storage_buffer(payload)
        del input_storage
        bound = self._native_bound(self._consumed_payload_bytes + len(payload))
        output_storage = bytearray(max(1, bound))
        output_array = (ctypes.c_ubyte * len(output_storage)).from_buffer(output_storage)
        output_buffer = _buffer(ctypes.addressof(output_array), capacity=bound, used=0)
        status = int(
            self._native.library.tscb_zlib_stream_update(
                self._handle, ctypes.byref(input_buffer), ctypes.byref(output_buffer)
            )
        )
        self._check(status, "stream_update")
        self._updated = True
        self._consumed_n += chunk.n
        self._consumed_payload_bytes += len(payload)
        prefix = b""
        if not self._preamble_emitted:
            prefix = _PREFIX.pack(_MAGIC, len(self._header)) + self._header
            self._preamble_emitted = True
        emitted = prefix + bytes(output_storage[: int(output_buffer.used_bytes)])
        return StreamPushResult(
            emitted=emitted,
            state_bytes=self._stream_state_bytes(),
            buffer_bytes=0,
            checkpoint_bits=0,
        )

    def stream_finalize(self) -> bytes:
        routed = self._require_started()
        if self._finalized:
            raise ExecutionContractError("repeated stream finalize is forbidden")
        if self._consumed_n != routed.n:
            raise ExecutionContractError("stream finalized before all declared rows were pushed")
        bound = self._native_bound(self._consumed_payload_bytes)
        output_storage = bytearray(max(1, bound))
        output_array = (ctypes.c_ubyte * len(output_storage)).from_buffer(output_storage)
        output_buffer = _buffer(ctypes.addressof(output_array), capacity=bound, used=0)
        status = int(
            self._native.library.tscb_zlib_stream_finalize(
                self._handle, ctypes.byref(output_buffer)
            )
        )
        self._check(status, "stream_finalize")
        self._finalized = True
        prefix = b""
        if not self._preamble_emitted:
            prefix = _PREFIX.pack(_MAGIC, len(self._header)) + self._header
            self._preamble_emitted = True
        return prefix + bytes(output_storage[: int(output_buffer.used_bytes)])

    def stream_accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if routed is not self._require_started():
            raise ExecutionContractError("stream accounting used a different routed object")
        return self.accounting(stream, routed)

    def stream_limits(self) -> dict[str, int]:
        self._require_started()
        return {
            "state_bytes": self._stream_state_bytes(),
            "buffer_bytes": 0,
        }

    def stream_decompress(self, stream: bytes) -> DecodedOutput:
        header, frame = self._parse_container(stream)
        descriptors = header.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("zlib DEFLATE container has no buffer descriptors")
        output_bytes = sum(int(item["payload_bytes"]) for item in descriptors)
        status = int(self._native.library.tscb_zlib_stream_decoder_reset(self._handle))
        self._check(status, "stream_decoder_reset")
        output_storage = bytearray(max(1, output_bytes))
        output_cursor = 0
        stream_ended = False
        for offset in range(0, len(frame), self._decode_chunk_bytes):
            compressed = frame[offset : offset + self._decode_chunk_bytes]
            input_storage, input_array, input_buffer = self._storage_buffer(compressed)
            del input_storage
            remaining = output_bytes - output_cursor
            output_view = (
                output_storage
                if remaining == 0
                else memoryview(output_storage)[output_cursor:]
            )
            output_array = (ctypes.c_ubyte * max(1, remaining)).from_buffer(output_view)
            output_buffer = _buffer(
                ctypes.addressof(output_array), capacity=remaining, used=0
            )
            ended = ctypes.c_uint32()
            status = int(
                self._native.library.tscb_zlib_stream_decompress_update(
                    self._handle,
                    ctypes.byref(input_buffer),
                    ctypes.byref(output_buffer),
                    ctypes.byref(ended),
                )
            )
            self._check(status, "stream_decompress_update")
            output_cursor += int(output_buffer.used_bytes)
            stream_ended = bool(ended.value)
            if stream_ended and offset + len(compressed) != len(frame):
                raise ExecutionContractError("zlib stream has trailing compressed bytes")
        status = int(self._native.library.tscb_zlib_stream_decoder_finish(self._handle))
        self._check(status, "stream_decoder_finish")
        if not stream_ended or output_cursor != output_bytes:
            raise ExecutionContractError("zlib streaming decode length is not exact")
        return self._decoded_output(header, memoryview(output_storage)[:output_bytes])
