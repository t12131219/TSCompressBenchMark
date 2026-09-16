from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from tscompbench.contracts import (
    AdapterOperationKind,
    BenchmarkTrack,
    CapabilityStatus,
    ImplementationClass,
    LossMode,
    ObjectLevel,
    PreprocessClass,
    ReconstructionMode,
    Topology,
    ValidityShape,
    ValueCouplingMode,
)
from tscompbench.ids import stable_id


class CodecContractError(ValueError):
    """A Layer 2 manifest, capability, or compatibility plan is invalid."""


@dataclass(frozen=True)
class DataDescriptor:
    dataset_id: str
    track: BenchmarkTrack
    topology: Topology
    n: int
    m: int
    shape: tuple[int, ...]
    dtype_vector: tuple[str, ...]
    physical_layout: str
    endianness: str
    alignment_bytes: int
    canonical_raw_bits: int
    validity_shape: ValidityShape
    timestamp_present: bool
    preserve_order: bool
    has_duplicates: bool
    has_out_of_order: bool
    has_negative_delta: bool
    timestamp_unit: str = "UNSPECIFIED"
    timestamp_epoch: str = "UNSPECIFIED"
    value_units: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.n < 0 or self.m < 0 or self.alignment_bytes < 1:
            raise CodecContractError("descriptor dimensions cannot be negative")
        if self.canonical_raw_bits < 0:
            raise CodecContractError("canonical_raw_bits cannot be negative")
        if not self.dtype_vector:
            raise CodecContractError("descriptor must declare at least one dtype")
        if not self.timestamp_unit or not self.timestamp_epoch:
            raise CodecContractError("timestamp unit and epoch must use explicit null semantics")

    def identity_document(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CodecManifest:
    key: str
    document: dict[str, Any]
    algorithm_id: str

    @property
    def source_artifact_id(self) -> str:
        return str(self.document["identity"]["source_artifact_id"])

    @property
    def object_level(self) -> ObjectLevel:
        return ObjectLevel(self.document["classification"]["object_level"])

    @property
    def implementation_class(self) -> ImplementationClass:
        return ImplementationClass(self.document["classification"]["implementation_class"])

    @property
    def tracks(self) -> tuple[BenchmarkTrack, ...]:
        return tuple(BenchmarkTrack(item) for item in self.document["classification"]["tracks"])

    @property
    def loss_modes(self) -> tuple[LossMode, ...]:
        return tuple(LossMode(item) for item in self.document["semantics"]["loss_modes"])

    @property
    def reconstruction_modes(self) -> tuple[ReconstructionMode, ...]:
        return tuple(
            ReconstructionMode(item) for item in self.document["semantics"]["reconstruction_modes"]
        )

    @property
    def preprocess_class(self) -> PreprocessClass:
        return PreprocessClass(self.document["semantics"]["preprocess_class"])

    @property
    def value_coupling_mode(self) -> ValueCouplingMode:
        return ValueCouplingMode(self.document["input"]["value_coupling_mode"])


@dataclass(frozen=True)
class AdapterOperation:
    operation_id: str
    kind: AdapterOperationKind
    semantic_class: PreprocessClass
    before_descriptor: dict[str, Any]
    after_descriptor: dict[str, Any]
    bytes_read: int
    bytes_written: int
    allocation_bytes: int
    padding_bytes: int
    external_metadata_bits: int
    timing_scopes: tuple[str, ...]
    reverse_operation: str
    validation_method: str

    def __post_init__(self) -> None:
        for value in (
            self.bytes_read,
            self.bytes_written,
            self.allocation_bytes,
            self.padding_bytes,
            self.external_metadata_bits,
        ):
            if value < 0:
                raise CodecContractError("adapter accounting values cannot be negative")
        if "CORE" in self.timing_scopes:
            raise CodecContractError("compatibility adapters cannot be charged to CORE")


@dataclass(frozen=True)
class CompatibilityPlan:
    status: CapabilityStatus
    reason_code: str
    missing_capabilities: tuple[str, ...]
    input_descriptor: DataDescriptor
    output_descriptor: dict[str, Any] | None
    operations: tuple[AdapterOperation, ...]
    effective_loss_mode: LossMode
    compatibility_plan_id: str

    @classmethod
    def create(
        cls,
        *,
        status: CapabilityStatus,
        reason_code: str,
        missing_capabilities: tuple[str, ...],
        input_descriptor: DataDescriptor,
        output_descriptor: dict[str, Any] | None,
        operations: tuple[AdapterOperation, ...],
        effective_loss_mode: LossMode,
    ) -> CompatibilityPlan:
        payload = {
            "schema_version": "tscb.compatibility-plan.v2",
            "status": status,
            "reason_code": reason_code,
            "missing_capabilities": missing_capabilities,
            "input_descriptor": input_descriptor,
            "output_descriptor": output_descriptor,
            "operations": operations,
            "effective_loss_mode": effective_loss_mode,
        }
        return cls(
            status=status,
            reason_code=reason_code,
            missing_capabilities=missing_capabilities,
            input_descriptor=input_descriptor,
            output_descriptor=output_descriptor,
            operations=operations,
            effective_loss_mode=effective_loss_mode,
            compatibility_plan_id=stable_id("compatibility-plan", payload),
        )

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.compatibility-plan.v2",
            "compatibility_plan_id": self.compatibility_plan_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "missing_capabilities": self.missing_capabilities,
            "input_descriptor": self.input_descriptor,
            "output_descriptor": self.output_descriptor,
            "operations": self.operations,
            "effective_loss_mode": self.effective_loss_mode,
        }
