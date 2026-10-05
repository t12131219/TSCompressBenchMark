from __future__ import annotations

import ctypes
import json
from collections.abc import Callable
from typing import Any

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.execution.protocol import (
    DecodedOutput,
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
)
from tscompbench.ids import canonical_json_bytes
from tscompbench.measurement.workloads import StreamPushResult

_STATUS_OK = 0
_STATUS_DST_TOO_SMALL = 3
_DTYPE_BYTES = 11
_OWNERSHIP_BORROWED = 0
_MAX_RANK = 8


def bind_stream_symbols(library: Any, buffer_type: Any) -> None:
    library.tscb_stream_update.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(buffer_type), ctypes.POINTER(buffer_type)
    ]
    library.tscb_stream_update.restype = ctypes.c_uint32
    library.tscb_stream_finalize.argtypes = [ctypes.c_void_p, ctypes.POINTER(buffer_type)]
    library.tscb_stream_finalize.restype = ctypes.c_uint32
    library.tscb_stream_decoder_reset.argtypes = [ctypes.c_void_p]
    library.tscb_stream_decoder_reset.restype = ctypes.c_uint32
    library.tscb_stream_decompress_update.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(buffer_type),
        ctypes.POINTER(buffer_type),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    library.tscb_stream_decompress_update.restype = ctypes.c_uint32
    library.tscb_stream_decoder_finish.argtypes = [ctypes.c_void_p]
    library.tscb_stream_decoder_finish.restype = ctypes.c_uint32
    library.tscb_stream_state_bytes.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64)]
    library.tscb_stream_state_bytes.restype = ctypes.c_uint32


class NativeByteStreamingSession:
    """Shared block-major lifecycle for adapters exposing native stream symbols."""

    def __init__(
        self,
        owner: Any,
        buffer_type: Any,
        buffer_factory: Callable[..., Any],
        parameters: dict[str, Any],
    ) -> None:
        self._owner = owner
        self._buffer_type = buffer_type
        self._buffer = buffer_factory
        self._routed: RoutedInput | None = None
        self._header = b""
        self._block_size = int(parameters.get("block_size", 65536))
        self._decode_chunk_bytes = int(parameters.get("stream_decode_chunk_bytes", 16384))
        self._consumed_n = 0
        self._consumed_payload_bytes = 0
        self._preamble_emitted = False
        self._finalized = False
        self._updated = False
        self._owner._header = b""
        if self._block_size < 1 or self._decode_chunk_bytes < 1:
            raise ExecutionContractError("streaming block sizes must be positive")

    @property
    def _native(self) -> Any:
        return self._owner._native

    @property
    def _handle(self) -> Any:
        return self._owner._handle

    def _check(self, status: int, operation: str) -> None:
        if status == _STATUS_OK:
            return
        if status == _STATUS_DST_TOO_SMALL:
            raise OutputCapacityError(f"{operation}: destination is too small")
        raise ExecutionContractError(f"{operation} failed ({status}): {self._owner._last_error()}")

    def stream_start(self, routed: RoutedInput) -> None:
        if self._routed is not None:
            raise ExecutionContractError("stream_start may be called once per session")
        self._routed = routed
        header = json.loads(self._owner._descriptor_header(routed))
        header["payload_layout"] = "BLOCK_MAJOR_BUFFER_ORDER"
        header["stream_block_size"] = self._block_size
        self._header = canonical_json_bytes(header)
        self._owner._header = self._header

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
        if self._consumed_n + chunk.n > routed.n:
            raise ExecutionContractError("stream chunk exceeds the declared routed length")
        expected_rows = min(self._block_size, routed.n - self._consumed_n)
        if chunk.n != expected_rows:
            raise ExecutionContractError("stream chunk length does not match configured block size")
        for expected, observed in zip(routed.buffers, chunk.buffers, strict=True):
            lhs = np.asarray(expected.array)
            rhs = np.asarray(observed.array)
            if (
                expected.name != observed.name
                or lhs.dtype != rhs.dtype
                or lhs.ndim != rhs.ndim
                or lhs.shape[1:] != rhs.shape[1:]
                or rhs.shape[0] != chunk.n
                or observed.logical_bits != rhs.nbytes * 8
            ):
                raise ExecutionContractError(
                    "stream chunk buffer schema does not match the started object"
                )

    def _bytes_buffer(
        self, data: bytes | bytearray, *, used: int | None = None
    ) -> tuple[bytearray, Any, Any]:
        payload = bytes(data)
        storage = bytearray(payload) if payload else bytearray(1)
        array = (ctypes.c_ubyte * len(storage)).from_buffer(storage)
        buffer = self._buffer(
            ctypes.addressof(array),
            capacity=len(payload),
            used=len(payload) if used is None else used,
        )
        return storage, array, buffer

    def _state_bytes(self) -> int:
        value = ctypes.c_uint64()
        self._check(
            int(self._native.library.tscb_stream_state_bytes(self._handle, ctypes.byref(value))),
            "stream_state_bytes",
        )
        return int(value.value)

    def stream_push(self, chunk: RoutedInput) -> StreamPushResult:
        self._validate_chunk(chunk)
        payload = b"".join(item.array.tobytes(order="C") for item in chunk.buffers)
        input_storage, input_array, input_buffer = self._bytes_buffer(payload)
        bound = int(self._owner._native_bound(self._consumed_payload_bytes + len(payload)))
        output_storage = bytearray(max(1, bound))
        output_array = (ctypes.c_ubyte * len(output_storage)).from_buffer(output_storage)
        output_buffer = self._buffer(ctypes.addressof(output_array), capacity=bound, used=0)
        status = int(self._native.library.tscb_stream_update(
            self._handle, ctypes.byref(input_buffer), ctypes.byref(output_buffer)
        ))
        self._check(status, "stream_update")
        self._updated = True
        self._consumed_n += chunk.n
        self._consumed_payload_bytes += len(payload)
        prefix = b""
        if not self._preamble_emitted:
            prefix = self._owner._PREFIX.pack(self._owner._MAGIC, len(self._header)) + self._header
            self._preamble_emitted = True
        return StreamPushResult(
            emitted=prefix + bytes(output_storage[: int(output_buffer.used_bytes)]),
            state_bytes=self._state_bytes(),
            buffer_bytes=0,
            checkpoint_bits=0,
        )

    def stream_finalize(self) -> bytes:
        routed = self._require_started()
        if self._finalized:
            raise ExecutionContractError("repeated stream finalize is forbidden")
        if self._consumed_n != routed.n:
            raise ExecutionContractError("stream finalized before all declared rows were pushed")
        bound = int(self._owner._native_bound(self._consumed_payload_bytes))
        output_storage = bytearray(max(1, bound))
        output_array = (ctypes.c_ubyte * len(output_storage)).from_buffer(output_storage)
        output_buffer = self._buffer(ctypes.addressof(output_array), capacity=bound, used=0)
        self._check(
            int(
                self._native.library.tscb_stream_finalize(
                    self._handle, ctypes.byref(output_buffer)
                )
            ),
            "stream_finalize",
        )
        self._finalized = True
        self._owner._finalized = True
        prefix = b""
        if not self._preamble_emitted:
            prefix = self._owner._PREFIX.pack(self._owner._MAGIC, len(self._header)) + self._header
            self._preamble_emitted = True
        return prefix + bytes(output_storage[: int(output_buffer.used_bytes)])

    def stream_accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if routed is not self._require_started():
            raise ExecutionContractError("stream accounting used a different routed object")
        return self._owner.accounting(stream, routed)

    def stream_limits(self) -> dict[str, int]:
        self._require_started()
        return {"state_bytes": self._state_bytes(), "buffer_bytes": 0}

    @staticmethod
    def _decode_output(header: dict[str, Any], payload: memoryview) -> DecodedOutput:
        descriptors = header.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("stream container has no buffer descriptors")
        total_n = int(descriptors[0]["shape"][0]) if descriptors else 0
        block_size = int(header.get("stream_block_size", 0))
        if header.get("payload_layout") != "BLOCK_MAJOR_BUFFER_ORDER" or block_size < 1:
            raise ExecutionContractError("stream payload layout metadata is missing")
        separated = [bytearray() for _ in descriptors]
        cursor = 0
        for offset in range(0, total_n, block_size):
            rows = min(block_size, total_n - offset)
            for index, descriptor in enumerate(descriptors):
                dtype = np.dtype(str(descriptor["dtype"]))
                shape = tuple(int(value) for value in descriptor["shape"])
                row_width = int(np.prod(shape[1:], dtype=np.int64)) if len(shape) > 1 else 1
                length = rows * row_width * dtype.itemsize
                if cursor + length > len(payload):
                    raise ExecutionContractError("truncated stream payload")
                separated[index].extend(payload[cursor : cursor + length])
                cursor += length
        if cursor != len(payload):
            raise ExecutionContractError("stream payload has trailing bytes")
        decoded: list[LogicalBuffer] = []
        for descriptor, data in zip(descriptors, separated, strict=True):
            dtype = np.dtype(str(descriptor["dtype"]))
            shape = tuple(int(value) for value in descriptor["shape"])
            array = np.frombuffer(data, dtype=dtype).copy().reshape(shape)
            array.flags.writeable = False
            decoded.append(
                LogicalBuffer(str(descriptor["name"]), array, int(descriptor["logical_bits"]))
            )
        return DecodedOutput(tuple(decoded))

    def stream_decompress(self, stream: bytes) -> DecodedOutput:
        parsed = self._owner._parse_container(stream)
        header, frame = parsed[:2]
        descriptors = header.get("buffers")
        if not isinstance(descriptors, list):
            raise ExecutionContractError("stream container has no descriptors")
        output_bytes = sum(int(item["payload_bytes"]) for item in descriptors)
        self._check(
            int(self._native.library.tscb_stream_decoder_reset(self._handle)),
            "stream_decoder_reset",
        )
        output_storage = bytearray(max(1, output_bytes))
        output_cursor = 0
        ended = False
        for offset in range(0, len(frame), self._decode_chunk_bytes):
            compressed = frame[offset : offset + self._decode_chunk_bytes]
            input_storage, input_array, input_buffer = self._bytes_buffer(compressed)
            remaining = output_bytes - output_cursor
            output_view = (
                output_storage
                if remaining == 0
                else memoryview(output_storage)[output_cursor:]
            )
            output_array = (ctypes.c_ubyte * max(1, remaining)).from_buffer(output_view)
            output_buffer = self._buffer(ctypes.addressof(output_array), capacity=remaining, used=0)
            marker = ctypes.c_uint32()
            self._check(
                int(
                    self._native.library.tscb_stream_decompress_update(
                        self._handle,
                        ctypes.byref(input_buffer),
                        ctypes.byref(output_buffer),
                        ctypes.byref(marker),
                    )
                ),
                "stream_decompress_update",
            )
            output_cursor += int(output_buffer.used_bytes)
            ended = bool(marker.value)
            if ended and offset + len(compressed) != len(frame):
                raise ExecutionContractError("stream has trailing compressed bytes")
        self._check(
            int(self._native.library.tscb_stream_decoder_finish(self._handle)),
            "stream_decoder_finish",
        )
        if not ended or output_cursor != output_bytes:
            raise ExecutionContractError(
                "stream decode did not produce the exact descriptor length"
            )
        return self._decode_output(header, memoryview(output_storage)[:output_bytes])

    def close(self) -> None:
        self._owner.close()
