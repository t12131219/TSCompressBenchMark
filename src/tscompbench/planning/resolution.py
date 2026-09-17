from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tscompbench.codecs import CodecManifest, CompatibilityPlan, DataDescriptor
from tscompbench.contracts import CapabilityStatus, RunStatus
from tscompbench.ids import canonical_json_bytes, stable_id

from .models import ComparabilityKeys, ExecutionResolution, ResolvedConfig

_ISA_FLAGS = {
    "SSE2": "sse2",
    "SSE4_2": "sse4_2",
    "AVX": "avx",
    "AVX2": "avx2",
    "AVX512": "avx512f",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_execution(
    manifest: CodecManifest,
    config: ResolvedConfig,
    compatibility: CompatibilityPlan,
    environment: dict[str, Any],
    *,
    artifact_path: Path,
    profile: dict[str, Any],
    supporting_artifact_paths: tuple[Path, ...] = (),
) -> ExecutionResolution:
    execution = manifest.document["execution"]
    requested = str(config.parameters.get("isa", execution["isa"][0]))
    available_flags = set(environment["cpu"].get("flags", []))
    manifest_isas = set(execution["isa"])
    cpu_supports = requested == "SCALAR" or _ISA_FLAGS.get(requested) in available_flags
    status = RunStatus.PLANNED
    reason = "RESOLVED"
    actual = requested
    fallback_used = False
    fallback_reason = "NOT_APPLICABLE"
    if compatibility.status is CapabilityStatus.UNSUPPORTED:
        status = RunStatus.UNSUPPORTED
        reason = compatibility.reason_code
        actual = "NOT_EXECUTED"
    elif requested not in manifest_isas:
        status = RunStatus.ISA_UNSUPPORTED
        reason = "REQUESTED_ISA_NOT_DECLARED_BY_CODEC"
        actual = "NOT_EXECUTED"
    elif not cpu_supports:
        if execution["fallback_policy"] == "SCALAR_ALLOWED" and "SCALAR" in manifest_isas:
            actual = "SCALAR"
            fallback_used = True
            fallback_reason = "CPU_MISSING_REQUESTED_ISA"
        else:
            status = RunStatus.ISA_UNSUPPORTED
            reason = "CPU_MISSING_REQUESTED_ISA"
            actual = "NOT_EXECUTED"
    affinity = tuple(int(item) for item in environment["cpu"].get("affinity") or ())
    requested_affinity = profile.get("cpu_affinity")
    if requested_affinity is not None:
        requested_set = tuple(int(item) for item in requested_affinity)
        if not set(requested_set).issubset(affinity):
            status = RunStatus.UNSUPPORTED
            reason = "CPU_AFFINITY_UNAVAILABLE"
        affinity = requested_set
    threads = int(profile["threads"])
    processes = int(profile.get("processes", 1))
    if threads < 1 or processes < 1:
        raise ValueError("thread and process budgets must be positive")
    python_environment = environment.get("python", {})
    toolchain_document = {
        "tools": {
            name: {
                key: value
                for key, value in facts.items()
                if key in {"status", "version_line", "returncode"}
            }
            for name, facts in environment.get("tools", {}).items()
        },
        "python": {
            key: python_environment.get(key)
            for key in ("version", "implementation", "executable_sha256", "packages")
        },
    }
    artifact_available = artifact_path.is_file() and all(
        path.is_file() for path in supporting_artifact_paths
    )
    if not artifact_available:
        primary_artifact_sha256 = "UNSPECIFIED"
        artifact_sha256 = "UNSPECIFIED"
        if status is RunStatus.PLANNED:
            status = RunStatus.BUILD_UNAVAILABLE
            reason = "EXECUTION_ARTIFACT_MISSING"
    else:
        primary_artifact_sha256 = sha256_file(artifact_path)
    if artifact_available and supporting_artifact_paths:
        artifact_components = (
            {"role": "PRIMARY_ADAPTER", "sha256": primary_artifact_sha256},
            *(
                {
                    "role": f"SUPPORTING_COMPONENT_{index}",
                    "sha256": sha256_file(path),
                }
                for index, path in enumerate(supporting_artifact_paths)
            ),
        )
        artifact_sha256 = hashlib.sha256(canonical_json_bytes(artifact_components)).hexdigest()
    elif artifact_available:
        artifact_sha256 = primary_artifact_sha256
    identity = {
        "algorithm_id": manifest.algorithm_id,
        "source_artifact_id": manifest.source_artifact_id,
        "adapter_id": stable_id("adapter", manifest.document["adapter"]),
        "backend": execution["backends"][0],
        "artifact_sha256": artifact_sha256,
        "toolchain_profile_id": stable_id("toolchain-profile", toolchain_document),
        "requested_isa": requested,
        "actual_isa": actual,
        "runtime_dispatch": bool(execution["runtime_dispatch"]),
        "required_alignment_bytes": int(manifest.document["input"]["alignment_bytes"]),
        "input_alignment_bytes": int(
            (compatibility.output_descriptor or {}).get(
                "alignment_bytes", compatibility.input_descriptor.alignment_bytes
            )
        ),
        "tail_elements": 0,
        "tail_path": manifest.document["lifecycle"]["tail_policy"],
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "cpu_affinity": affinity,
        "threads": threads,
        "processes": processes,
        "device": profile.get("device", execution["devices"][0]),
        "runner_implementation": "python",
        "runner_version": profile["runner_version"],
        "environment_id": environment["environment_id"],
        "allocation_policy": profile["allocation_policy"],
        "cache_policy": profile["cache_policy"],
        "state_policy": profile["state_policy"],
        "gc_policy": profile["gc_policy"],
        "jit_policy": profile["jit_policy"],
    }
    return ExecutionResolution(
        status=status,
        reason_code=reason,
        execution_path_hash=stable_id("execution-path", identity),
        **identity,
    )


def build_comparability_keys(
    manifest: CodecManifest,
    descriptor: DataDescriptor,
    config: ResolvedConfig,
    compatibility: CompatibilityPlan,
    execution: ExecutionResolution,
    *,
    profile: dict[str, Any],
) -> ComparabilityKeys:
    semantics = manifest.document["semantics"]
    lifecycle = manifest.document["lifecycle"]
    semantic_document = {
        "track": descriptor.track,
        "object_level": manifest.object_level,
        "loss_mode": compatibility.effective_loss_mode,
        "reconstruction_modes": semantics["reconstruction_modes"],
        "topology": descriptor.topology,
        "dtype_semantics": descriptor.dtype_vector,
        "timestamp_unit": descriptor.timestamp_unit,
        "timestamp_epoch": descriptor.timestamp_epoch,
        "value_unit_semantics": descriptor.value_units,
        "validity_shape": descriptor.validity_shape,
        "order_profile": "PRESERVE" if descriptor.preserve_order else "UNSPECIFIED",
        "decodability_profile": semantics["decodability_profile"],
        "bitstream_separability": semantics["bitstream_separability"],
        "value_coupling_mode": manifest.value_coupling_mode,
        "adapter_semantic_class": tuple(
            operation.semantic_class for operation in compatibility.operations
        ),
        "preprocess_class": manifest.preprocess_class,
        "block_semantics": lifecycle["block_semantics"],
        "state_semantics": lifecycle["state_semantics"],
        "error_bound_type": config.parameters.get("error_bound_type", "NOT_APPLICABLE"),
        "error_bound_value": config.parameters.get("error_bound", "NOT_APPLICABLE"),
    }
    semantic_key = stable_id("semantic-comparability", semantic_document)
    execution_document = {
        "semantic_key": semantic_key,
        "measurement_mode": profile["measurement_mode"],
        "timing_scope": profile["timing_scope"],
        "e2e_input_mode": "CANONICAL_MEMORY_ROUTED_VIEW",
        "warmup_min_count": profile["warmup_min_count"],
        "warmup_min_seconds": profile["warmup_min_seconds"],
        "repetitions": profile["repetitions"],
        "min_repetition_seconds": profile["min_repetition_seconds"],
        "iteration_semantics": profile["iteration_semantics"],
        "query_workload": profile["query_workload"],
        "query_count": profile["query_count"],
        "streaming_workload": profile["streaming_workload"],
        "allocation_policy": execution.allocation_policy,
        "cache_policy": execution.cache_policy,
        "gc_policy": execution.gc_policy,
        "jit_policy": execution.jit_policy,
        "actual_isa": execution.actual_isa,
        "input_alignment_bytes": execution.input_alignment_bytes,
        "tail_elements": execution.tail_elements,
        "tail_path": execution.tail_path,
        "device": execution.device,
        "threads": execution.threads,
        "processes": execution.processes,
        "fallback_used": execution.fallback_used,
        "backend": execution.backend,
        "adapter_boundary": manifest.document["adapter"]["timing_boundary"],
    }
    execution_key = stable_id("execution-comparability", execution_document)
    resource_document = {
        "execution_key": execution_key,
        "resource_scope": profile["resource_scope"],
        "memory_accounting_scope": profile["memory_accounting_scope"],
        "counter_method": profile["counter_method"],
        "energy_method": profile["energy_method"],
        "sampling_policy": profile["sampling_policy"],
    }
    resource_key = stable_id("resource-profile", resource_document)
    return ComparabilityKeys(
        semantic_key=semantic_key,
        execution_key=execution_key,
        resource_key=resource_key,
        semantic_document=semantic_document,
        execution_document=execution_document,
        resource_document=resource_document,
    )
