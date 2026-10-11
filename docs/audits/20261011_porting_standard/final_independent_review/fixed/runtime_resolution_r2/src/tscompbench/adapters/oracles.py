from __future__ import annotations

import json
import os
import struct
import time
import zlib
from dataclasses import dataclass
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
from tscompbench.ids import canonical_json_bytes, stable_id

_START = b"TSCBOR2\x00"
_END = b"TSCBEND2"
_PREFIX = struct.Struct("<8sI")
_FOOTER = struct.Struct("<8sI")


def _frame_parts(routed: RoutedInput, *, nonce: str | None) -> tuple[bytes, bytes]:
    descriptors: list[dict[str, Any]] = []
    payload = bytearray()
    for item in routed.buffers:
        raw = item.array.tobytes(order="C")
        descriptors.append(
            {
                "name": item.name,
                "dtype": item.array.dtype.str,
                "shape": list(item.array.shape),
                "payload_bytes": len(raw),
                "logical_bits": item.logical_bits,
            }
        )
        payload.extend(raw)
    header = canonical_json_bytes(
        {
            "schema_version": "tscb.oracle-frame.v2",
            "track": routed.track,
            "segment_plan_id": routed.segment_plan_id,
            "buffers": descriptors,
            "nonce": nonce,
        }
    )
    return _PREFIX.pack(_START, len(header)) + header + bytes(payload), header


@dataclass(frozen=True)
class OracleAdapter:
    """Batch-0 lifecycle oracle; it is never a leaderboard algorithm."""

    mode: str = "IDENTITY"
    delay_seconds: float = 0.0
    error_delta: float = 0.0
    manifest_adapter: dict[str, Any] | None = None

    @property
    def adapter_id(self) -> str:
        if self.manifest_adapter is not None:
            return stable_id("adapter", self.manifest_adapter)
        return stable_id(
            "adapter",
            {
                "kind": "BATCH_0_ORACLE",
                "version": "2",
                "mode": self.mode,
                "delay_seconds": format(self.delay_seconds, ".17g"),
                "error_delta": format(self.error_delta, ".17g"),
            },
        )

    @property
    def deterministic(self) -> bool:
        return self.mode != "NONDETERMINISTIC"

    def create_session(self, parameters: dict[str, Any]) -> OracleSession:
        return OracleSession(self, parameters)


class OracleSession:
    def __init__(self, adapter: OracleAdapter, parameters: dict[str, Any]):
        self.adapter = adapter
        self.parameters = dict(parameters)
        self._updated = False
        self._finalized = False
        self._body = b""
        self._header = b""

    def _nonce(self) -> str | None:
        if self.adapter.mode in {"NONDETERMINISTIC", "FALSE_DETERMINISM"}:
            return os.urandom(8).hex()
        return None

    def output_bound(self, routed: RoutedInput) -> int:
        uses_nonce = self.adapter.mode in {"NONDETERMINISTIC", "FALSE_DETERMINISM"}
        body, _ = _frame_parts(routed, nonce="0" * 16 if uses_nonce else None)
        bound = len(body) + _FOOTER.size
        return bound - 1 if self.adapter.mode == "CAPACITY_LIE" else bound

    @property
    def deterministic(self) -> bool:
        return self.adapter.deterministic

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int:
        if self._updated:
            raise ExecutionContractError("compress_update may be called once per oracle frame")
        if self.adapter.mode == "OOM":
            raise MemoryError("deliberate Batch-0 OOM oracle")
        if self.adapter.delay_seconds:
            time.sleep(self.adapter.delay_seconds)
        body, header = _frame_parts(routed, nonce=self._nonce())
        if len(destination) < len(body):
            raise OutputCapacityError("destination is smaller than compress_update output")
        destination[: len(body)] = body
        self._body = body
        self._header = header
        self._updated = True
        return len(body)

    def finalize(self, destination: memoryview) -> int:
        if not self._updated:
            raise ExecutionContractError("finalize requires a preceding update")
        if self._finalized:
            raise ExecutionContractError("repeated finalize is forbidden by this adapter")
        footer = _FOOTER.pack(_END, zlib.crc32(self._body) & 0xFFFFFFFF)
        if len(destination) < len(footer):
            raise OutputCapacityError("destination is smaller than finalize output")
        destination[: len(footer)] = footer
        self._finalized = True
        return len(footer)

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger:
        if not self._finalized:
            raise ExecutionContractError("accounting before finalize is forbidden")
        timestamp_bits = 0
        value_bits = 0
        validity_bits = 0
        for item in routed.buffers:
            physical_bits = item.array.nbytes * 8
            if item.name == "timestamp":
                timestamp_bits += physical_bits
            elif item.name == "validity":
                validity_bits += physical_bits
            else:
                value_bits += physical_bits
        container_bits = (_PREFIX.size + len(_END)) * 8
        checksum_bits = 32
        metadata_bits = len(self._header) * 8
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            timestamp_bits=timestamp_bits,
            value_bits=value_bits,
            validity_bits=validity_bits,
            metadata_bits=metadata_bits,
            checksum_bits=checksum_bits,
            container_bits=container_bits,
        )

    def decompress(self, stream: bytes) -> DecodedOutput:
        if len(stream) < _PREFIX.size + _FOOTER.size:
            raise ExecutionContractError("truncated oracle frame")
        start, header_length = _PREFIX.unpack_from(stream)
        if start != _START:
            raise ExecutionContractError("invalid oracle frame magic")
        footer_offset = len(stream) - _FOOTER.size
        end, expected_crc = _FOOTER.unpack_from(stream, footer_offset)
        if end != _END or zlib.crc32(stream[:footer_offset]) & 0xFFFFFFFF != expected_crc:
            raise ExecutionContractError("oracle frame checksum/finalize validation failed")
        header_start = _PREFIX.size
        header_end = header_start + header_length
        try:
            header = json.loads(stream[header_start:header_end].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExecutionContractError("invalid oracle frame header") from error
        cursor = header_end
        decoded: list[LogicalBuffer] = []
        for descriptor in header["buffers"]:
            length = int(descriptor["payload_bytes"])
            payload = stream[cursor : cursor + length]
            if len(payload) != length or cursor + length > footer_offset:
                raise ExecutionContractError("truncated oracle payload")
            dtype = np.dtype(descriptor["dtype"])
            shape = tuple(int(value) for value in descriptor["shape"])
            array = np.frombuffer(payload, dtype=dtype).copy().reshape(shape)
            cursor += length
            decoded.append(
                LogicalBuffer(
                    name=str(descriptor["name"]),
                    array=array,
                    logical_bits=int(descriptor["logical_bits"]),
                )
            )
        if cursor != footer_offset:
            raise ExecutionContractError("oracle frame contains undeclared payload bytes")
        if self.adapter.mode == "CORRUPT" and decoded and decoded[0].array.size:
            raw = decoded[0].array.view(np.uint8).reshape(-1)
            raw[0] ^= np.uint8(1)
        if self.adapter.mode == "BOUND_VIOLATION" and decoded:
            for item in decoded:
                if item.name.startswith("value/") and np.issubdtype(item.array.dtype, np.floating):
                    item.array.reshape(-1)[0] += self.adapter.error_delta or 1.0
                    break
        for item in decoded:
            item.array.flags.writeable = False
        return DecodedOutput(tuple(decoded))

    def close(self) -> None:
        self._body = b""
        self._header = b""
