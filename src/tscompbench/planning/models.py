from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from tscompbench.codecs import CompatibilityPlan
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.preprocess import PreprocessPlan


@dataclass(frozen=True)
class ResolvedConfig:
    algorithm_id: str
    parameters: dict[str, Any]
    framework_parameters: dict[str, Any]
    status: RunStatus
    reason_code: str
    config_id: str


@dataclass(frozen=True)
class ExecutionResolution:
    status: RunStatus
    reason_code: str
    algorithm_id: str
    source_artifact_id: str
    adapter_id: str
    backend: str
    artifact_sha256: str
    toolchain_profile_id: str
    requested_isa: str
    actual_isa: str
    runtime_dispatch: bool
    required_alignment_bytes: int
    input_alignment_bytes: int
    tail_elements: int
    tail_path: str
    fallback_used: bool
    fallback_reason: str
    cpu_affinity: tuple[int, ...]
    threads: int
    processes: int
    device: str
    runner_implementation: str
    runner_version: str
    environment_id: str
    allocation_policy: str
    cache_policy: str
    state_policy: str
    gc_policy: str
    jit_policy: str
    execution_path_hash: str

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": "tscb.execution-resolution.v2", **asdict(self)}


@dataclass(frozen=True)
class ComparabilityKeys:
    semantic_key: str
    execution_key: str
    resource_key: str
    semantic_document: dict[str, Any]
    execution_document: dict[str, Any]
    resource_document: dict[str, Any]

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": "tscb.comparability-keys.v2", **asdict(self)}


@dataclass(frozen=True)
class BenchmarkTask:
    task_id: str
    dataset_id: str
    algorithm_id: str
    config_id: str
    track: BenchmarkTrack
    profile_id: str
    status: RunStatus
    reason_code: str
    expected_workload: dict[str, Any]
    resource_limits: dict[str, Any]
    dependencies: tuple[str, ...]
    compatibility: CompatibilityPlan
    preprocess: PreprocessPlan
    execution: ExecutionResolution
    comparability: ComparabilityKeys

    def to_document(self) -> dict[str, Any]:
        document = asdict(self)
        document["schema_version"] = "tscb.benchmark-task.v2"
        document["compatibility"] = self.compatibility.to_document()
        document["preprocess"] = self.preprocess.to_document()
        document["execution"] = self.execution.to_document()
        document["comparability"] = self.comparability.to_document()
        return document
