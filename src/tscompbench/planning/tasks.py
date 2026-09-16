from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from tscompbench.codecs import CodecManifest, CompatibilityPlan, DataDescriptor
from tscompbench.contracts import BenchmarkTrack, CapabilityStatus, RunStatus
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.preprocess import PreprocessPlan

from .models import BenchmarkTask, ComparabilityKeys, ExecutionResolution, ResolvedConfig


def create_task(
    *,
    descriptor: DataDescriptor,
    manifest: CodecManifest,
    config: ResolvedConfig,
    profile_id: str,
    compatibility: CompatibilityPlan,
    preprocess: PreprocessPlan,
    execution: ExecutionResolution,
    comparability: ComparabilityKeys,
    resource_limits: dict[str, Any],
) -> BenchmarkTask:
    identity = {
        "dataset_id": descriptor.dataset_id,
        "algorithm_id": manifest.algorithm_id,
        "config_id": config.config_id,
        "track": descriptor.track,
        "profile_id": profile_id,
    }
    status = RunStatus.PLANNED
    reason = "READY_FOR_PREFLIGHT"
    if config.status is RunStatus.SCHEMA_ERROR:
        status = config.status
        reason = config.reason_code
    elif compatibility.status is CapabilityStatus.UNSUPPORTED:
        status = RunStatus.UNSUPPORTED
        reason = compatibility.reason_code
    elif execution.status is not RunStatus.PLANNED:
        status = execution.status
        reason = execution.reason_code
    elif compatibility.status is CapabilityStatus.ADAPTER_LOSSY:
        status = RunStatus.ADAPTER_LOSSY_ROUTED
        reason = "LOSSY_TRACK_REQUIRED"
    return BenchmarkTask(
        task_id=stable_id("task", identity),
        dataset_id=descriptor.dataset_id,
        algorithm_id=manifest.algorithm_id,
        config_id=config.config_id,
        track=BenchmarkTrack(descriptor.track),
        profile_id=profile_id,
        status=status,
        reason_code=reason,
        expected_workload={
            "n": descriptor.n,
            "m": descriptor.m,
            "shape": descriptor.shape,
            "canonical_raw_bits": descriptor.canonical_raw_bits,
        },
        resource_limits=resource_limits,
        dependencies=(descriptor.dataset_id, manifest.source_artifact_id),
        compatibility=compatibility,
        preprocess=preprocess,
        execution=execution,
        comparability=comparability,
    )


def write_task_plan(path: Path, tasks: tuple[BenchmarkTask, ...]) -> None:
    ordered = tuple(sorted(tasks, key=lambda item: item.task_id))
    if len({task.task_id for task in ordered}) != len(ordered):
        raise ValueError("task plan contains duplicate TaskIDs")
    payload = b"".join(canonical_json_bytes(task.to_document()) + b"\n" for task in ordered)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError("existing task plan differs from deterministic rebuild")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
