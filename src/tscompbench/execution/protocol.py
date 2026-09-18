from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from tscompbench.accounting import AccountingLedger
from tscompbench.contracts import BenchmarkTrack


class ExecutionContractError(RuntimeError):
    """The adapter violated the versioned execution lifecycle."""


class OutputCapacityError(ExecutionContractError):
    """The supplied destination capacity cannot hold the finalized object."""


@dataclass(frozen=True)
class LogicalBuffer:
    name: str
    array: np.ndarray[Any]
    logical_bits: int

    def __post_init__(self) -> None:
        if not self.name or self.logical_bits < 0:
            raise ExecutionContractError("logical buffer name/bits are invalid")


@dataclass(frozen=True)
class RoutedInput:
    dataset_id: str
    track: BenchmarkTrack
    buffers: tuple[LogicalBuffer, ...]
    timestamp_reference: np.ndarray[Any] | None
    validity_reference: np.ndarray[Any] | None
    n: int
    m: int
    canonical_raw_bits: int
    input_sha256: str
    segment_plan_id: str | None = None
    timestamp_unit: str = "UNSPECIFIED"
    timestamp_epoch: str = "UNSPECIFIED"
    value_units: tuple[str, ...] = ()
    pairing_reference_sha256: str | None = None

    def __post_init__(self) -> None:
        names = [item.name for item in self.buffers]
        if len(names) != len(set(names)):
            raise ExecutionContractError("routed input contains duplicate buffer names")
        if self.n < 0 or self.m < 0 or self.canonical_raw_bits < 0:
            raise ExecutionContractError("routed input dimensions/bits cannot be negative")
        if self.track is BenchmarkTrack.TIMESTAMP and names != ["timestamp"]:
            raise ExecutionContractError("Timestamp track must route only T")
        if self.track is BenchmarkTrack.VALUE and any(name == "timestamp" for name in names):
            raise ExecutionContractError("Value track must not route T into the codec")
        if self.track is BenchmarkTrack.SYSTEM and self.segment_plan_id is None:
            raise ExecutionContractError("SYSTEM track requires a common SegmentPlanID")


@dataclass(frozen=True)
class DecodedOutput:
    buffers: tuple[LogicalBuffer, ...]

    def by_name(self) -> dict[str, LogicalBuffer]:
        result = {item.name: item for item in self.buffers}
        if len(result) != len(self.buffers):
            raise ExecutionContractError("decoder returned duplicate buffer names")
        return result


@dataclass(frozen=True)
class EncodedArtifact:
    stream: bytes
    update_bytes: int
    finalize_bytes: int
    output_capacity_bytes: int
    stream_sha256: str
    ledger: AccountingLedger
    native_encode_wall_ns: int | None = None

    def __post_init__(self) -> None:
        if self.update_bytes < 0 or self.finalize_bytes < 0:
            raise ExecutionContractError("encoded byte counts cannot be negative")
        if self.update_bytes + self.finalize_bytes != len(self.stream):
            raise ExecutionContractError("update/finalize byte counts do not match stream")
        if len(self.stream) > self.output_capacity_bytes:
            raise ExecutionContractError("adapter wrote beyond declared output capacity")
        if self.ledger.final_physical_bytes != len(self.stream):
            raise ExecutionContractError("ledger does not match finalized stream length")


class CodecSession(Protocol):
    """Narrow lifecycle shared by Python, FFI, subprocess, and future native runners."""

    def output_bound(self, routed: RoutedInput) -> int: ...

    def compress_update(self, routed: RoutedInput, destination: memoryview) -> int: ...

    def finalize(self, destination: memoryview) -> int: ...

    def accounting(self, stream: bytes, routed: RoutedInput) -> AccountingLedger: ...

    def decompress(self, stream: bytes) -> DecodedOutput: ...

    def close(self) -> None: ...


class CodecAdapter(Protocol):
    adapter_id: str
    deterministic: bool

    def create_session(self, parameters: dict[str, Any]) -> CodecSession: ...
