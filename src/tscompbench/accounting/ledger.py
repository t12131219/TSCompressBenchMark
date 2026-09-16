from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from tscompbench.contracts import BenchmarkTrack


class AccountingContractError(ValueError):
    """A finalized stream cannot be reconciled with its bit ledger."""


@dataclass(frozen=True)
class AccountingLedger:
    """Bit-first accounting for one finalized, independently decodable object.

    Component fields are mutually exclusive physical-bit ownership buckets.  Byte
    rounding is checked exactly once, at the complete serialized-object boundary.
    External side information is decodability cost but is not part of physical bytes.
    """

    track: BenchmarkTrack
    timestamp_bits: int = 0
    value_bits: int = 0
    shared_bits: int = 0
    unallocated_shared_bits: int = 0
    metadata_bits: int = 0
    validity_bits: int = 0
    dictionary_bits: int = 0
    model_bits: int = 0
    index_bits: int = 0
    checkpoint_bits: int = 0
    checksum_bits: int = 0
    padding_bits: int = 0
    container_bits: int = 0
    external_side_information_bits: int = 0
    serialized_bits: int = 0
    final_bits: int = 0
    final_physical_bytes: int = 0
    canonical_raw_bits: int = 0
    accounting_method: str = "EXACT_STREAM_INSPECTION"

    _COMPONENTS: ClassVar[tuple[str, ...]] = (
        "timestamp_bits",
        "value_bits",
        "shared_bits",
        "unallocated_shared_bits",
        "metadata_bits",
        "validity_bits",
        "dictionary_bits",
        "model_bits",
        "index_bits",
        "checkpoint_bits",
        "checksum_bits",
        "padding_bits",
        "container_bits",
    )

    def __post_init__(self) -> None:
        numeric = self._COMPONENTS + (
            "external_side_information_bits",
            "serialized_bits",
            "final_bits",
            "final_physical_bytes",
            "canonical_raw_bits",
        )
        for name in numeric:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise AccountingContractError(f"{name} must be a non-negative integer")
        component_sum = sum(getattr(self, name) for name in self._COMPONENTS)
        if component_sum != self.serialized_bits:
            raise AccountingContractError(
                f"serialized component sum {component_sum} != SerializedBits {self.serialized_bits}"
            )
        if self.final_physical_bytes != (self.serialized_bits + 7) // 8:
            raise AccountingContractError("FinalPhysicalBytes must equal ceil(SerializedBits / 8)")
        expected_final = self.serialized_bits + self.external_side_information_bits
        if self.final_bits != expected_final:
            raise AccountingContractError(
                "FinalBits must equal SerializedBits + ExternalSideInformationBits"
            )
        if self.track is BenchmarkTrack.TIMESTAMP and self.value_bits:
            raise AccountingContractError("Timestamp track cannot own ValueBits")
        if self.track is BenchmarkTrack.VALUE and self.timestamp_bits:
            raise AccountingContractError("Value track cannot own TimestampBits")
        if not self.accounting_method:
            raise AccountingContractError("accounting_method must be explicit")

    @classmethod
    def create(
        cls,
        *,
        track: BenchmarkTrack,
        canonical_raw_bits: int,
        final_physical_bytes: int,
        external_side_information_bits: int = 0,
        accounting_method: str = "EXACT_STREAM_INSPECTION",
        **components: int,
    ) -> AccountingLedger:
        unknown = set(components) - set(cls._COMPONENTS)
        if unknown:
            raise AccountingContractError(f"unknown accounting components: {sorted(unknown)}")
        values = {name: int(components.get(name, 0)) for name in cls._COMPONENTS}
        serialized_bits = sum(values.values())
        if (serialized_bits + 7) // 8 != final_physical_bytes:
            raise AccountingContractError(
                "component bits do not close against the finalized physical stream"
            )
        return cls(
            track=track,
            **values,
            external_side_information_bits=external_side_information_bits,
            serialized_bits=serialized_bits,
            final_bits=serialized_bits + external_side_information_bits,
            final_physical_bytes=final_physical_bytes,
            canonical_raw_bits=canonical_raw_bits,
            accounting_method=accounting_method,
        )

    @property
    def compression_factor(self) -> str | None:
        if self.final_bits == 0:
            return None
        return format(self.canonical_raw_bits / self.final_bits, ".17g")

    @property
    def size_ratio(self) -> str | None:
        if self.canonical_raw_bits == 0:
            return None
        return format(self.final_bits / self.canonical_raw_bits, ".17g")

    def to_document(self) -> dict[str, Any]:
        document = asdict(self)
        document.update(
            {
                "schema_version": "tscb.accounting-ledger.v2",
                "compression_factor": self.compression_factor,
                "size_ratio": self.size_ratio,
            }
        )
        return document
