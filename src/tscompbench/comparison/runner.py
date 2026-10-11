"""Frozen comparison execution, sharing the existing canonical and codec gates."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, is_dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tscompbench.adapters import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, descriptor_from_layer1_artifacts, negotiate
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.datasets.canonical import read_canonical, semantic_content_sha256
from tscompbench.datasets.prepare import load_preparation_result, prepare_dataset
from tscompbench.datasets.registry import DatasetRegistry
from tscompbench.environment import capture_environment
from tscompbench.execution.cold_driver import (
    ColdPilotProbe,
    measure_cold_object,
    run_cold_pilot,
    validate_cold_pilot_evidence,
)
from tscompbench.execution.orchestrator import execute_task
from tscompbench.execution.preflight import preflight_task
from tscompbench.execution.recovery import DecodeContext
from tscompbench.execution.repetition import perform_declared_worker_measurement
from tscompbench.execution.routing import route_canonical_artifact
from tscompbench.execution.schedule import FrozenSchedule, build_schedule, write_frozen_schedule
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.measurement import MeasurementPolicy
from tscompbench.measurement.v32_protocol import MeasurementProtocol, run_pilot
from tscompbench.planning import build_comparability_keys, create_task, resolve_execution
from tscompbench.planning.models import ResolvedConfig
from tscompbench.preprocess import build_preprocess_plan
from tscompbench.runner import _replace_json, _write_or_verify_bytes, _write_or_verify_json
from tscompbench.storage import RunRecord, append_event, append_run_record
from tscompbench.version import __version__

from .analysis import AnalysisPolicy, analyze_comparison, trial_issues
from .decision import (
    comparison_decision,
    freeze_experiment_decision,
    validate_experiment_decision,
)
from .models import (
    ComparisonContract,
    CorpusSpec,
    ExecutionJob,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    TaskSpec,
)
from .planning import PlannedComparisonCell, compile_group_plan, validate_job_for_cell
from .projection import public_projection


def _uses_source_reject_fallback(cell: dict[str, Any]) -> bool:
    """A source fallback is a predeclared recipe, never a codec-key default."""
    return "SOURCE_REJECT_RAW" in cell["allowed_paths"]


def _source_reject_recipe_id(manifest: Any, parameters: dict[str, Any]) -> str:
    from tscompbench.adapters.source_reject_fallback import source_reject_composite_recipe_id

    return source_reject_composite_recipe_id(
        stable_id("adapter", manifest.document["adapter"]), manifest.key, parameters
    )


def _comparison_content_sha256(run: ComparisonRun, metadata: dict[str, Any]) -> str:
    return semantic_content_sha256(
        metadata,
        policy=run.corpus.to_document().get("content_identity_policy", "tscb.dataset-content.v1"),
    )


def _actual_codec_input_identity(
    artifact: Any, task: Any, parameters: dict[str, Any]
) -> tuple[str, str]:
    from tscompbench.execution.preparation import prepare_execution_input
    from tscompbench.execution.routing import hash_logical_buffers

    if task.status not in {RunStatus.PLANNED, RunStatus.ADAPTER_LOSSY_ROUTED}:
        unavailable = {
            "boundary": "NOT_ROUTED_AFTER_ADMISSION_REJECTION",
            "track": task.track.value,
            "dataset_id": task.dataset_id,
            "status": task.status.value,
            "reason": task.reason_code,
            "actual_input_observed": False,
        }
        schema_id = stable_id("unavailable-codec-input-schema", unavailable, version="v3")
        return stable_id("unavailable-codec-input", unavailable, version="v3"), schema_id
    original = route_canonical_artifact(artifact, task.track)
    actual = prepare_execution_input(
        original, task.compatibility, max_abs_error=parameters.get("error_bound")
    ).codec_input
    schema = {
        "boundary": "CODEC_SESSION_PUBLIC_ARRAY_API",
        "track": actual.track,
        "n": actual.n,
        "m": actual.m,
        "buffers": [
            {
                "name": item.name,
                "dtype": item.array.dtype.str,
                "shape": list(item.array.shape),
                "strides": list(item.array.strides),
                "logical_bits": item.logical_bits,
            }
            for item in actual.buffers
        ],
    }
    schema_id = stable_id("codec-input-schema", schema, version="v3")
    return stable_id(
        "codec-input",
        {"schema_id": schema_id, "sha256": hash_logical_buffers(actual.buffers)},
        version="v3",
    ), schema_id


def _comparison_adapter(project_root: Path, manifest: Any, cell: dict[str, Any]) -> Any:
    """Create a frozen comparison adapter, including explicit P2 source fallback."""
    return create_adapter(
        project_root,
        manifest,
        source_reject_fallback=_uses_source_reject_fallback(cell),
    )


def evidence_document(value: Any) -> Any:
    """Canonical decimal observations, with unavailable values explicitly null."""
    if isinstance(value, float):
        number = Decimal(str(value))
        return format(number, "f") if number.is_finite() else None
    if isinstance(value, dict):
        return {key: evidence_document(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [evidence_document(item) for item in value]
    if hasattr(value, "to_document"):
        return evidence_document(value.to_document())
    if hasattr(value, "identity_document"):
        return evidence_document(value.identity_document())
    if is_dataclass(value) and not isinstance(value, type):
        return evidence_document(asdict(value))
    return value


def control_plane_snapshot(project_root: Path) -> dict[str, Any]:
    files = [
        {
            "path": str(path.relative_to(project_root)),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted((project_root / "src" / "tscompbench").rglob("*.py"))
    ]
    return {
        "schema_version": "tscb.comparison-control-plane.v1",
        "files": files,
        "sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
    }


@dataclass
class ComparisonRun:
    path: Path
    project_root: Path
    bundle: dict[str, Any]
    protocol: MeasurementProtocol
    analysis_policy: AnalysisPolicy
    contract: ComparisonContract
    corpus: CorpusSpec
    group: GroupSpec
    tasks: dict[str, Any]
    cells: dict[str, dict[str, Any]]
    artifacts: dict[str, Any]
    manifests: dict[str, Any]
    policy: MeasurementPolicy
    schedule: Any
    plan: dict[str, Any]


def load_comparison_bundle(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "contract",
        "corpus",
        "group",
        "config_map",
        "expected_matrix",
        "protocol",
        "analysis_policy",
        "dataset_bindings",
        "cpu_affinity",
        "seed",
        "development_dataset",
        "qualification_datasets",
    }
    if set(document) != required or document["schema_version"] != "tscb.comparison-bundle.v1":
        raise ValueError("comparison bundle has unknown/missing fields or version")
    if type(document["seed"]) is not int or document["seed"] < 0:
        raise ValueError("comparison seed must be a nonnegative integer")
    if not isinstance(document["development_dataset"], str) or not document["development_dataset"]:
        raise ValueError("a separate development dataset must be frozen before measurement")
    if (
        not isinstance(document["qualification_datasets"], list)
        or len(set(document["qualification_datasets"])) < 4
    ):
        raise ValueError("freeze at least four qualification patterns")
    cpus = document["cpu_affinity"]
    if (
        not isinstance(cpus, list)
        or not cpus
        or any(type(c) is not int or c < 0 for c in cpus)
        or len(set(cpus)) != len(cpus)
    ):
        raise ValueError("comparison needs an explicit CPU affinity")
    if not isinstance(document["dataset_bindings"], dict) or any(
        not isinstance(k, str) or not isinstance(v, str)
        for k, v in document["dataset_bindings"].items()
    ):
        raise ValueError("dataset bindings must map content DatasetIDs to registry keys")
    canonical_json_bytes(document)
    return document


def _profile(
    protocol: MeasurementProtocol, resources: dict[str, Any], affinity: list[int]
) -> dict[str, Any]:
    return {
        "runner_version": __version__,
        "measurement_protocol_id": protocol.protocol_id,
        "measurement_mode": "FORMAL",
        "timing_scope": protocol.timing_scope,
        "resource_scope": "PROCESS",
        "memory_accounting_scope": "PROCESS_RSS",
        "counter_method": "NOT_COLLECTED",
        "energy_method": "NOT_COLLECTED",
        "sampling_policy": "PROCESS_BOUNDARY",
        "allocation_policy": "PER_REPETITION",
        "cache_policy": protocol.cache_policy,
        "state_policy": "RESET_PER_REPETITION",
        "gc_policy": "DISABLED_DURING_TIMING",
        "jit_policy": "NOT_APPLICABLE",
        "warmup_min_count": protocol.warmup_min_count,
        "warmup_min_seconds": format(Decimal(protocol.warmup_min_ns) / Decimal(10**9), "f"),
        "repetitions": protocol.outer_repetitions,
        "min_repetition_seconds": format(
            Decimal(min(protocol.encode_min_ns, protocol.decode_min_ns)) / Decimal(10**9), "f"
        ),
        "max_inner_iterations": protocol.max_inner_iterations,
        "iteration_semantics": "INDEPENDENT_OBJECT",
        "threads": resources["threads"],
        "processes": resources["processes"],
        "device": resources["device"],
        "cpu_affinity": affinity,
        "query_workload": False,
        "streaming_workload": False,
        "query_count": 1000,
    }


def prepare_comparison(
    bundle_path: Path,
    output_path: Path,
    project_root: Path,
    dataset_registry: DatasetRegistry,
    codec_registry: CodecRegistry,
    *,
    run_set_id: str,
    resume: bool = False,
    decision_workload_protocol: dict[str, Any] | None = None,
) -> ComparisonRun:
    """Freeze all member/config/dataset cells before pilot, qualification or timing."""
    if Path(run_set_id).name != run_set_id or run_set_id in {"", ".", ".."}:
        raise ValueError("run_set_id must be a safe path component")
    bundle = load_comparison_bundle(bundle_path)
    protocol = MeasurementProtocol.from_document(bundle["protocol"])
    contract = ComparisonContract.from_document(bundle["contract"])
    native_api = contract.to_document()["mode"] == "COMMON_NATIVE_API"
    if native_api:
        supported = protocol.profile == "STEADY_PROCESS" and protocol.timing_scope == "CORE"
    else:
        supported = protocol.profile in {"STEADY_PROCESS", "COLD_PROCESS"} and (
            protocol.timing_scope == "PIPELINE"
        )
    if not supported:
        raise ValueError(
            "complete objects require steady/cold PIPELINE; common native API components "
            "require STEADY_PROCESS CORE"
        )
    if protocol.stop_mode != "FIXED_REPETITIONS" or protocol.max_retries != 0:
        raise ValueError("this executor requires fixed repetitions with no automatic retries")
    if protocol.profile == "COLD_PROCESS" and protocol.max_inner_iterations != 1:
        raise ValueError("cold comparison measures exactly one independent object per direction")
    if protocol.collector_mode != "ENABLED":
        raise ValueError("CPU formal comparison requires the validated PROCESS collector")
    policy = AnalysisPolicy.from_document(bundle["analysis_policy"])
    corpus = CorpusSpec.from_document(bundle["corpus"])
    group = GroupSpec.from_document(bundle["group"])
    if native_api:
        for member in group.to_document()["members"]:
            manifest = codec_registry.get(member["codec_key"])
            document = manifest.document
            if (
                "SOURCE_REJECT_RAW" in member["allowed_paths"]
                or document["classification"]["object_level"]
                not in {"P0_PRIMITIVE", "P1_STANDALONE_CODEC"}
                or document["semantics"]["loss_modes"] != ["LOSSLESS"]
            ):
                raise ValueError(
                    "common native API lane requires registered lossless P0/P1 components "
                    "without composite source fallback"
                )
    config_map = MethodConfigMap.from_document(bundle["config_map"])
    expected = ExpectedOutcomeMatrix.from_document(bundle["expected_matrix"])
    c = contract.to_document()
    if c["measurement_protocol_id"] != protocol.protocol_id or c["analysis_policy_id"] != policy.id:
        raise ValueError("comparison contract does not bind the measurement/analysis policies")
    if c["resources"]["processes"] != 1 or c["resources"]["device"] != "CPU":
        raise ValueError("CPU comparison executor supports one process per trial")
    scope = json.loads((project_root / "registry" / "algorithm_scope.json").read_text())
    compiled = compile_group_plan(
        group,
        contract,
        corpus,
        config_map,
        expected,
        codec_registry=codec_registry,
        active_codec_keys=set(scope["registered_codecs"]),
    )
    destination = output_path.resolve() / run_set_id
    if destination.exists() and not resume:
        raise FileExistsError("comparison run exists; use resume with identical frozen inputs")
    destination.mkdir(parents=True, exist_ok=True)
    environment = capture_environment()
    _write_or_verify_json(destination / "bundle.json", bundle)
    environment_path = destination / "environment.json"
    if environment_path.exists():
        frozen_environment = json.loads(environment_path.read_text())
        if environment["environment_id"] != frozen_environment.get("environment_id"):
            raise ValueError("comparison resume environment identity changed")
        # Available memory and swap are observations, not environment identity.
        # Preserve the original capture; each trial also records fresh boundaries.
        environment = frozen_environment
    else:
        _write_or_verify_json(environment_path, environment)
    closure = control_plane_snapshot(project_root)
    _write_or_verify_json(destination / "control_plane.json", closure)
    decision = comparison_decision(
        bundle,
        environment_id=environment["environment_id"],
        control_plane_sha256=closure["sha256"],
        workload_protocol=decision_workload_protocol,
    )
    freeze_experiment_decision(destination, decision, resume=resume)
    _write_or_verify_json(destination / "comparison_plan.json", compiled.to_document())
    for key in {
        *bundle["dataset_bindings"].values(),
        bundle["development_dataset"],
        *bundle["qualification_datasets"],
    }:
        _write_or_verify_json(
            destination / "dataset_manifests" / (key + ".json"), dataset_registry.load(key).document
        )
    profile = _profile(protocol, c["resources"], bundle["cpu_affinity"])
    measurement = MeasurementPolicy(
        **{
            name: profile[name]
            for name, field in MeasurementPolicy.__dataclass_fields__.items()
            if name in profile
        },
        seed=bundle["seed"],
        encode_min_ns=protocol.encode_min_ns,
        decode_min_ns=protocol.decode_min_ns,
        worker_start_method=protocol.start_method,
        thread_monitor_interval_ns=protocol.thread_monitor_interval_ns,
    )
    artifacts = {}
    characterizations = {}
    datasets = {d["dataset_id"]: d for d in corpus.to_document()["datasets"]}
    if set(bundle["dataset_bindings"]) != set(datasets):
        raise ValueError("dataset bindings must cover exactly the frozen corpus")
    for dataset_id, key in bundle["dataset_bindings"].items():
        if (destination / "datasets" / key / "preparation-record.json").exists():
            prepared = load_preparation_result(dataset_registry, key, destination / "datasets")
        else:
            prepared = prepare_dataset(dataset_registry, key, destination / "datasets")
        artifact = read_canonical(prepared.canonical.path)
        row = datasets[dataset_id]
        if (
            prepared.dataset_id != dataset_id
            or artifact.sha256 != row["artifact_sha256"]
            or semantic_content_sha256(
                artifact.metadata,
                policy=corpus.to_document().get(
                    "content_identity_policy", "tscb.dataset-content.v1"
                ),
            )
            != row["logical_content_id"]
        ):
            raise ValueError("prepared canonical dataset differs from frozen corpus")
        artifacts[dataset_id] = artifact
        characterizations[dataset_id] = json.loads(prepared.characterization_path.read_text())
    tasks = {}
    cells = {}
    manifests = {}
    equivalence = {
        mid: item["class_id"]
        for item in group.to_document()["method_equivalence"]
        for mid in item["members"]
    }
    method_jobs: dict[str, dict[str, str]] = {}
    for cell in compiled.cells:
        row = cell.to_document()
        manifest = codec_registry.get(row["codec_key"])
        manifests[row["codec_key"]] = manifest
        _write_or_verify_json(destination / "codecs" / (manifest.key + ".json"), manifest.document)
        _write_or_verify_json(
            destination / "sources" / (manifest.source_artifact_id.rsplit(":", 1)[-1] + ".json"),
            codec_registry.sources.get(manifest.source_artifact_id),
        )
        config = ResolvedConfig(
            manifest.algorithm_id,
            row["parameters"],
            row["framework_parameters"],
            RunStatus.PLANNED,
            "FROZEN_METHOD_CONFIG",
            row["legacy_config_id"],
        )
        artifact = artifacts[row["dataset_id"]]
        descriptor = descriptor_from_layer1_artifacts(
            artifact.metadata, characterizations[row["dataset_id"]], BenchmarkTrack(c["track"])
        )
        compatibility = negotiate(manifest, descriptor, parameters=config.parameters)
        adapter_artifact, supporting = adapter_artifacts(project_root, manifest)
        execution = resolve_execution(
            manifest,
            config,
            compatibility,
            environment,
            artifact_path=adapter_artifact,
            supporting_artifact_paths=supporting,
            profile=profile,
            source_reject_fallback=_uses_source_reject_fallback(row),
        )
        task = create_task(
            descriptor=descriptor,
            manifest=manifest,
            config=config,
            profile_id=protocol.protocol_id,
            compatibility=compatibility,
            preprocess=build_preprocess_plan(manifest.document, config.parameters),
            execution=execution,
            comparability=build_comparability_keys(
                manifest, descriptor, config, compatibility, execution, profile=profile
            ),
            resource_limits={
                "timeout_seconds": protocol.max_trial_wall_ns / 10**9,
                "memory_limit_bytes": c["resources"]["memory_limit_bytes"],
            },
        )
        logical = artifact.metadata["logical_descriptor"]
        task_spec = TaskSpec.from_document(
            {
                "schema_version": "tscb.task-spec.v1",
                "dataset_id": descriptor.dataset_id,
                "logical_content_id": row["logical_content_id"],
                "cost_boundary": c["cost_boundary"],
                "fidelity": c["fidelity"],
                "recovery": c["recovery"],
                "workload": c["workload"],
                "state": c["state"],
                "logical_schema": {
                    "axes": logical["axes"],
                    "shape": list(descriptor.shape),
                    "channel_ids": [column["name"] for column in logical["value_columns"]],
                    "dtypes": list(descriptor.dtype_vector),
                    "units": list(descriptor.value_units),
                    "order": "PRESERVE_ORIGINAL",
                    "pairing": "NOT_APPLICABLE" if c["track"] == "VALUE" else "PRESERVE_T_V",
                    "timestamp_epoch": descriptor.timestamp_epoch,
                    "timestamp_unit": descriptor.timestamp_unit,
                    "topology": descriptor.topology.value,
                    "track": c["track"],
                    "validity": descriptor.validity_shape.value,
                },
            }
        )
        composite = _uses_source_reject_fallback(row)
        if composite:
            path = "SOURCE_REJECT_RAW"
        elif (
            manifest.document["semantics"]["rebuild_protocol"]
            == "TSCB_BUFFER_DESCRIPTOR_CONTAINER_V1"
        ):
            path = "BYTE_SERIALIZATION"
        elif compatibility.operations:
            path = (
                "LOSSY_CAST"
                if any(op.kind.value == "LOSSY_CAST" for op in compatibility.operations)
                else "EXACT_WIDEN"
                if any(op.kind.value == "EXACT_WIDEN" for op in compatibility.operations)
                else "DIRECT"
            )
        elif manifest.document["input"]["value_coupling_mode"] == "COLUMN_INDEPENDENT":
            path = "COLUMN_INDEPENDENT"
        elif manifest.document["input"]["value_coupling_mode"] == "FULL_MATRIX":
            path = "JOINT"
        else:
            path = "DIRECT"
        if path not in row["allowed_paths"]:
            raise ValueError("actual planned path not allowed by frozen group")
        actual_input_id, actual_input_schema_id = _actual_codec_input_identity(
            artifact, task, config.parameters
        )
        job = ExecutionJob.from_document(
            {
                "schema_version": "tscb.execution-job.v1",
                "task_spec_id": task_spec.id,
                "member_id": row["member_id"],
                "method_id": row["method_id"],
                "implementation_id": row["implementation_id"],
                "algorithm_id": manifest.algorithm_id,
                "config_id": row["config_id"],
                "recipe_id": _source_reject_recipe_id(manifest, config.parameters)
                if composite
                else task.preprocess.preprocess_plan_id
                if hasattr(task.preprocess, "preprocess_plan_id")
                else stable_id("recipe", task.preprocess.to_document()),
                "view_id": compatibility.compatibility_plan_id,
                "execution_path_hash": execution.execution_path_hash,
                "source_artifact_id": manifest.source_artifact_id,
                "build_id": execution.artifact_sha256,
                "runtime_id": environment["environment_id"],
                "actual_input_id": actual_input_id,
                "actual_input_schema_id": actual_input_schema_id,
                "original_content_id": row["logical_content_id"],
                "path": path,
                "backend": execution.backend,
                "actual_isa": execution.actual_isa,
                "loss_mode": row["loss_mode"],
                "guarantee": row["guarantee"],
                "resources": c["resources"],
                "state": c["state"],
                "timing_boundary": c["timing_boundary"],
            }
        )
        projection = public_projection(contract, task_spec, job)
        validate_job_for_cell(group, cell, task_spec, job)
        tasks[cell.id] = task
        _write_or_verify_json(
            destination / "jobs" / (cell.id.rsplit(":", 1)[-1] + ".json"),
            {
                "task_spec": task_spec.to_document(),
                "execution_job": job.to_document(),
                "legacy_execution_task": evidence_document(task.to_document()),
                "projection": projection.document,
                "disclosures": projection.disclosures,
            },
        )
        cells[cell.id] = {
            **row,
            "cell_id": cell.id,
            "method_equivalence_class": equivalence[row["member_id"]],
            "config_label": row["config_key"],
            "role": "CORE" if row["dataset_role"] == row["member_role"] == "CORE" else "EXTENSION",
            "expected_outcome": row["expected"]["outcome"],
            "canonical_raw_bits": descriptor.canonical_raw_bits,
            "execution_job_id": job.id,
            "public_projection_key": projection.key,
            "task_id": task.task_id,
            "execution_path_hash": execution.execution_path_hash,
            "input_sha256": (
                route_canonical_artifact(artifact, task.track).input_sha256
                if task.status in {RunStatus.PLANNED, RunStatus.ADAPTER_LOSSY_ROUTED}
                else None
            ),
            "track": task.track.value,
            "cost_boundary": c["cost_boundary"],
            "actual_input_id": actual_input_id,
            "actual_input_schema_id": actual_input_schema_id,
            "actual_input_observed": task.status
            in {RunStatus.PLANNED, RunStatus.ADAPTER_LOSSY_ROUTED},
            "path": path,
            "resources": c["resources"],
        }
        method_jobs.setdefault(row["dataset_id"], {})[
            row["member_id"] + "/" + row["config_key"]
        ] = job.id
    if native_api:
        for dataset_id in artifacts:
            native_core = [
                cell
                for cell in cells.values()
                if cell["dataset_id"] == dataset_id and cell["role"] == "CORE"
            ]
            if len({cell["public_projection_key"] for cell in native_core}) != 1:
                raise ValueError(
                    "common native API core members must receive identical "
                    "actual input schemas and bytes"
                )
    comparison_id = stable_id(
        "comparison-execution",
        {
            "group_plan": compiled.id,
            "protocol_id": protocol.protocol_id,
            "analysis_policy_id": policy.id,
            "environment_id": environment["environment_id"],
            "control_plane_sha256": closure["sha256"],
            "decision_id": decision["decision_id"],
            "run_set_id": run_set_id,
            "cpu_affinity": bundle["cpu_affinity"],
        },
    )
    schedule = build_schedule(
        run_set_id=run_set_id,
        dataset_methods=method_jobs,
        protocol_id=protocol.protocol_id,
        seed=bundle["seed"],
        blocks=protocol.outer_repetitions,
        max_retries=protocol.max_retries,
    )
    write_frozen_schedule(destination / "schedule.json", schedule)
    plan = {
        "schema_version": "tscb.comparison-execution-plan.v1",
        "comparison_id": comparison_id,
        "decision_id": decision["decision_id"],
        "decision": decision,
        "decision_workload_protocol": decision_workload_protocol,
        "protocol_id": protocol.protocol_id,
        "protocol": protocol.to_document(),
        "schedule_id": schedule.schedule_id,
        "schedule": schedule.to_document(),
        "analysis_policy_id": policy.id,
        "contract": c,
        "cells": list(cells.values()),
        "planned_repetitions_per_cell": protocol.outer_repetitions,
        "independent_real_source_count": compiled.denominators["independent_real_sources"],
        "denominators": compiled.denominators,
        "pilot_eligible": False,
    }
    _write_or_verify_json(destination / "execution_plan.json", plan)
    return ComparisonRun(
        destination,
        project_root,
        bundle,
        protocol,
        policy,
        contract,
        corpus,
        group,
        tasks,
        cells,
        artifacts,
        manifests,
        measurement,
        schedule,
        plan,
    )


def _read_trials(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_bytes().splitlines(keepends=True)
    if any(not line.endswith(b"\n") for line in lines):
        raise ValueError("comparison trials contain an interrupted append")
    rows = [json.loads(line) for line in lines]
    if len({row["trial_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate comparison TrialID")
    return rows


def _append_trial(path: Path, trial: dict[str, Any]) -> None:
    payload = canonical_json_bytes(trial) + b"\n"
    with path.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _auxiliary_input(
    run: ComparisonRun, registry: DatasetRegistry, key: str, cell: dict[str, Any]
) -> tuple[Any, Any]:
    output = run.path / "auxiliary_datasets"
    if (output / key / "preparation-record.json").exists():
        prepared = load_preparation_result(registry, key, output)
    else:
        prepared = prepare_dataset(registry, key, output)
    artifact = read_canonical(prepared.canonical.path)
    core_contents = {row["logical_content_id"] for row in run.corpus.to_document()["datasets"]}
    if _comparison_content_sha256(run, artifact.metadata) in core_contents:
        raise ValueError("development/qualification data overlaps frozen test content")
    manifest = run.manifests[cell["codec_key"]]
    descriptor = descriptor_from_layer1_artifacts(
        artifact.metadata,
        json.loads(prepared.characterization_path.read_text()),
        BenchmarkTrack(run.contract.to_document()["track"]),
    )
    config = ResolvedConfig(
        manifest.algorithm_id,
        cell["parameters"],
        cell["framework_parameters"],
        RunStatus.PLANNED,
        "FROZEN_AUXILIARY_CONFIG",
        cell["legacy_config_id"],
    )
    compatibility = negotiate(manifest, descriptor, parameters=config.parameters)
    profile = _profile(
        run.protocol, run.contract.to_document()["resources"], run.bundle["cpu_affinity"]
    )
    base = run.tasks[cell["cell_id"]]
    adapter_artifact, supporting = adapter_artifacts(run.project_root, manifest)
    execution = resolve_execution(
        manifest,
        config,
        compatibility,
        json.loads((run.path / "environment.json").read_text()),
        artifact_path=adapter_artifact,
        supporting_artifact_paths=supporting,
        profile=profile,
        source_reject_fallback=_uses_source_reject_fallback(cell),
    )
    task = create_task(
        descriptor=descriptor,
        manifest=manifest,
        config=config,
        profile_id=run.protocol.protocol_id,
        compatibility=compatibility,
        preprocess=build_preprocess_plan(manifest.document, config.parameters),
        execution=execution,
        comparability=build_comparability_keys(
            manifest, descriptor, config, compatibility, execution, profile=profile
        ),
        resource_limits=base.resource_limits,
    )
    _write_or_verify_json(
        run.path / "auxiliary_jobs" / (task.task_id.rsplit(":", 1)[-1] + ".json"),
        evidence_document(task.to_document()),
    )
    return task, artifact


def _qualified_expectation(expected: dict[str, Any], preflight: dict[str, Any]) -> bool:
    status = preflight.get("status")
    if expected["outcome"] == "PASS":
        recovery = preflight.get("diagnostics", {}).get("independent_recovery", {})
        return (
            status == "PASS"
            and preflight.get("eligible_for_formal_repetitions") is True
            and preflight.get("correctness", {}).get("status") == "PASS"
            and recovery.get("start_method") == "spawn"
            and recovery.get("original_input_available") is False
            and recovery.get("encoder_session_available") is False
            and recovery.get("output_owned_in_worker") is True
        )
    if expected["outcome"] == "REJECT":
        return (
            status in {"UNSUPPORTED", "SCHEMA_ERROR", "INCOMPARABLE", "ISA_UNSUPPORTED"}
            and preflight.get("reason_code") == expected["reason"]
            and expected["stage"] in {"INPUT_NEGOTIATION", "CONFIG_VALIDATION", "PREFLIGHT"}
        )
    return (
        status in {"SOURCE_INCOMPLETE", "LICENSE_RESTRICTED", "BUILD_UNAVAILABLE"}
        and preflight.get("reason_code") == expected["reason"]
        and expected["outcome"] == "BLOCKED"
    )


def _qualification_capture_directory(run, cell, scope, key=None):
    label = scope + ("-" + key if key is not None else "")
    return run.path / "qualification_artifacts" / label / cell["cell_id"].rsplit(":", 1)[-1]


def _saved_preflight_inputs(run, cell, key=None):
    """Read actual frozen objects and tasks, without constructing a codec."""
    auxiliary = key is not None
    key = key if auxiliary else run.bundle["dataset_bindings"][cell["dataset_id"]]
    directory = run.path / ("auxiliary_datasets" if auxiliary else "datasets") / key
    record = json.loads((directory / "preparation-record.json").read_text())
    artifact = read_canonical(directory / record["canonical_artifact"])
    if artifact.sha256 != record["canonical_artifact_sha256"]:
        raise ValueError("qualification original artifact changed")
    if auxiliary:
        candidates = [
            json.loads(path.read_text()) for path in (run.path / "auxiliary_jobs").glob("*.json")
        ]
        candidates = [
            task
            for task in candidates
            if task["dataset_id"] == artifact.metadata["dataset_id"]
            and task["algorithm_id"] == cell["algorithm_id"]
            and task["config_id"] == cell["legacy_config_id"]
        ]
        if len(candidates) != 1:
            raise ValueError("qualification auxiliary task identity is missing or ambiguous")
        task = candidates[0]
    else:
        task = json.loads(
            (run.path / "jobs" / (cell["cell_id"].rsplit(":", 1)[-1] + ".json")).read_text()
        )["legacy_execution_task"]
        if task["task_id"] != cell["task_id"]:
            raise ValueError("qualification task differs from frozen cell")
    if (
        task["dataset_id"] != artifact.metadata["dataset_id"]
        or task["algorithm_id"] != cell["algorithm_id"]
        or task["config_id"] != cell["legacy_config_id"]
        or task["profile_id"] != run.protocol.protocol_id
        or task["track"] != run.bundle["contract"]["track"]
    ):
        raise ValueError("qualification task codec/configuration/fixture/profile differs")
    routed = route_canonical_artifact(artifact, BenchmarkTrack(task["track"]))
    compatibility = task["compatibility"]
    context = DecodeContext.from_routed(
        routed,
        SimpleNamespace(
            effective_loss_mode=compatibility["effective_loss_mode"],
            input_descriptor=SimpleNamespace(**compatibility["input_descriptor"]),
            operations=tuple(
                SimpleNamespace(
                    kind=SimpleNamespace(value=op["kind"]),
                    after_descriptor=op["after_descriptor"],
                )
                for op in compatibility["operations"]
            ),
        ),
        adapter_id=task["execution"]["adapter_id"],
        parameters=cell["parameters"],
    )
    return task, routed, context


def _validate_preflight_artifacts(run, cell, preflight, scope, key=None):
    task, routed, context = _saved_preflight_inputs(run, cell, key)
    diagnostics = preflight.get("diagnostics") or {}
    captured = diagnostics.get("qualification_artifacts") or {}
    expected_binding = {
        name: task[name] for name in ("task_id", "dataset_id", "algorithm_id", "config_id")
    }
    expected_binding.update(
        execution_path_hash=task["execution"]["execution_path_hash"],
        track=task["track"],
        input_sha256=routed.input_sha256,
        canonical_raw_bits=routed.canonical_raw_bits,
        adapter_id=task["execution"]["adapter_id"],
        parameters=cell["parameters"],
    )
    if captured.get("binding") != expected_binding:
        raise ValueError("qualification actual task/codec/configuration/fixture binding differs")
    capture_directory = _qualification_capture_directory(run, cell, scope, key).resolve()
    payloads = {}
    for role, name in (("stream", "stream.bin"), ("context", "context.json")):
        reference = captured.get(role) or {}
        path = Path(reference.get("path", "")).resolve()
        if path != capture_directory / name or not path.is_relative_to(run.path.resolve()):
            raise ValueError("qualification artifact path belongs to another observation")
        payload = path.read_bytes()
        if reference != {
            "path": str(path),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }:
            raise ValueError("qualification saved artifact hash/size changed")
        payloads[role] = payload
    if json.loads((capture_directory / "binding.json").read_text()) != captured:
        raise ValueError("qualification artifact binding file changed")
    recovery = diagnostics.get("independent_recovery") or {}
    lifecycle = diagnostics.get("independent_recovery_worker_lifecycle") or {}
    ledger = preflight.get("accounting") or {}
    if (
        payloads["context"] != context.serialized
        or preflight.get("input_validation", {}).get("input_sha256") != routed.input_sha256
        or recovery.get("decode_context_sha256") != context.sha256
        or recovery.get("required_external_bits") != len(context.serialized) * 8
        or recovery.get("stream_sha256") != captured["stream"]["sha256"]
        or preflight.get("bitstream_sha256") != captured["stream"]["sha256"]
        or ledger.get("canonical_raw_bits") != routed.canonical_raw_bits
        or ledger.get("serialized_bits") != len(payloads["stream"]) * 8
        or ledger.get("external_side_information_bits") != len(context.serialized) * 8
        or ledger.get("final_bits") != (len(payloads["stream"]) + len(context.serialized)) * 8
        or lifecycle.get("start_method") != "spawn"
        or lifecycle.get("worker_exit_confirmed") is not True
        or lifecycle.get("exit_code") != 0
        or lifecycle.get("worker_pid") != recovery.get("worker_pid")
    ):
        raise ValueError(
            "qualification actual input/recovery/artifact/cost/worker evidence differs"
        )


def validate_qualification_evidence(run: ComparisonRun, document: dict[str, Any]) -> None:
    body = {key: value for key, value in document.items() if key != "qualification_id"}
    if (
        document.get("schema_version") != "tscb.comparison-qualification.v1"
        or document.get("comparison_id") != run.plan["comparison_id"]
        or document.get("qualification_id") != stable_id("comparison-qualification", body)
    ):
        raise ValueError("qualification evidence identity differs from the frozen comparison")
    real_rows = {e["cell_id"]: e for e in document["evidence"] if e["scope"] == "CORE_OR_EXTENSION"}
    real_count = sum(e["scope"] == "CORE_OR_EXTENSION" for e in document["evidence"])
    if set(real_rows) != set(run.cells) or real_count != len(run.cells):
        raise ValueError("qualification omits or duplicates a frozen matrix cell")
    for cell_id, cell in run.cells.items():
        row = real_rows[cell_id]
        if row["expected"] != cell["expected"] or not _qualified_expectation(
            cell["expected"], row["preflight"]
        ):
            raise ValueError("qualification does not satisfy the independently frozen expectation")
        if cell["expected"]["outcome"] == "PASS":
            _validate_preflight_artifacts(run, cell, row["preflight"], "core")
    wanted = {
        (c["member_id"], c["config_label"], key)
        for c in run.cells.values()
        for key in run.bundle["qualification_datasets"]
    }
    actual = []
    for row in document["evidence"]:
        if row["scope"] != "FOUR_PATTERN_QUALIFICATION":
            continue
        cell = run.cells[row["cell_id"]]
        actual.append((cell["member_id"], cell["config_label"], row["dataset_key"]))
        if not _qualified_expectation({"outcome": "PASS"}, row["preflight"]):
            raise ValueError("qualification pattern failed original-object recovery")
        _validate_preflight_artifacts(run, cell, row["preflight"], "pattern", row["dataset_key"])
    if set(actual) != wanted or len(actual) != len(wanted):
        raise ValueError("qualification pattern/member/config coverage differs from frozen scope")
    if document.get("status") != "PASS" or document.get("failure_count") != 0:
        raise ValueError("qualification is incomplete")


def qualify_comparison(run: ComparisonRun, registry: DatasetRegistry) -> dict[str, Any]:
    """Check the frozen real matrix and four independent qualification patterns."""
    from tscompbench.codecs import SourceRegistry
    from tscompbench.measurement.resource_lease import ResourceLease

    validate_frozen_comparison(run.path, run.bundle, run.plan)
    sources = SourceRegistry(run.project_root / "registry" / "sources")
    resources = run.contract.to_document()["resources"]
    evidence = []
    representatives = {}
    with ResourceLease(
        run_set_id=run.schedule.run_set_id + "-qualification",
        logical_cpus=run.bundle["cpu_affinity"],
        threads=resources["threads"],
        memory_limit_bytes=resources["memory_limit_bytes"],
    ):
        for cell in run.cells.values():
            task = run.tasks[cell["cell_id"]]
            manifest = run.manifests[cell["codec_key"]]
            source = sources.get(manifest.source_artifact_id)
            preflight, _ = preflight_task(
                task,
                manifest,
                source,
                run.artifacts[cell["dataset_id"]],
                _comparison_adapter(run.project_root, manifest, cell),
                cell["parameters"],
                cpu_affinity=task.execution.cpu_affinity,
                capture_directory=_qualification_capture_directory(run, cell, "core"),
            )
            evidence.append(
                {
                    "cell_id": cell["cell_id"],
                    "scope": "CORE_OR_EXTENSION",
                    "expected": cell["expected"],
                    "preflight": evidence_document(preflight.to_document()),
                }
            )
            representatives[(cell["member_id"], cell["config_label"])] = cell
        for cell in representatives.values():
            manifest = run.manifests[cell["codec_key"]]
            source = sources.get(manifest.source_artifact_id)
            for key in run.bundle["qualification_datasets"]:
                task, artifact = _auxiliary_input(run, registry, key, cell)
                preflight, _ = preflight_task(
                    task,
                    manifest,
                    source,
                    artifact,
                    _comparison_adapter(run.project_root, manifest, cell),
                    cell["parameters"],
                    cpu_affinity=task.execution.cpu_affinity,
                    capture_directory=_qualification_capture_directory(run, cell, "pattern", key),
                )
                evidence.append(
                    {
                        "cell_id": cell["cell_id"],
                        "dataset_key": key,
                        "scope": "FOUR_PATTERN_QUALIFICATION",
                        "expected": {"outcome": "PASS"},
                        "preflight": evidence_document(preflight.to_document()),
                    }
                )
    failures = [e for e in evidence if not _qualified_expectation(e["expected"], e["preflight"])]
    document = {
        "schema_version": "tscb.comparison-qualification.v1",
        "comparison_id": run.plan["comparison_id"],
        "status": "PASS" if not failures else "INCOMPLETE",
        "evidence": evidence,
        "failure_count": len(failures),
        "measurement_qualification": False,
    }
    document["qualification_id"] = stable_id("comparison-qualification", document)
    _write_or_verify_json(run.path / "qualification.json", document)
    return document


@dataclass(frozen=True)
class DeclaredPilotProbe:
    project_root: Path
    codec_key: str
    manifest: dict[str, Any]
    algorithm_id: str
    routed: Any
    compatibility: Any
    parameters: dict[str, Any]
    policy: MeasurementPolicy
    source_reject_fallback: bool = False
    binding_directory: Path | None = None

    def __call__(self) -> dict[str, int]:
        if self.binding_directory is not None:
            _write_or_verify_json(
                self.binding_directory / (str(os.getpid()) + ".json"),
                {
                    "schema_version": "tscb.comparison-pilot-probe-binding.v1",
                    "worker_pid": os.getpid(),
                    "codec_key": self.codec_key,
                    "algorithm_id": self.algorithm_id,
                    "dataset_id": self.routed.dataset_id,
                    "input_sha256": self.routed.input_sha256,
                    "canonical_raw_bits": self.routed.canonical_raw_bits,
                    "track": self.routed.track.value,
                    "parameters": self.parameters,
                    "compatibility_plan_id": self.compatibility.compatibility_plan_id,
                    "source_reject_fallback": self.source_reject_fallback,
                },
            )
        measured = perform_declared_worker_measurement(
            self.project_root,
            self.codec_key,
            self.manifest,
            self.algorithm_id,
            self.routed,
            self.compatibility,
            self.parameters,
            self.policy,
            self.source_reject_fallback,
        )
        return {
            "encode_ns": measured.observation.timing.selected_encode_wall_ns,
            "decode_ns": measured.observation.timing.selected_decode_wall_ns,
            "inner_iterations": measured.observation.timing.inner_iterations,
        }


def pilot_harness_probe() -> None:
    """Empty external clock/dispatch driver, disclosed rather than subtracted."""
    time.perf_counter_ns()
    time.perf_counter_ns()


def _saved_auxiliary_artifact(run: ComparisonRun, key: str) -> Any:
    directory = run.path / "auxiliary_datasets" / key
    record = json.loads((directory / "preparation-record.json").read_text())
    artifact = read_canonical(directory / record["canonical_artifact"])
    if artifact.sha256 != record["canonical_artifact_sha256"]:
        raise ValueError("saved auxiliary artifact differs from its preparation evidence")
    return artifact


def validate_comparison_pilots(run: ComparisonRun, document: dict[str, Any]) -> None:
    from tscompbench.measurement.v32_protocol import validate_pilot_evidence

    body = {key: value for key, value in document.items() if key != "pilot_id"}
    if (
        document.get("schema_version") != "tscb.comparison-pilot-set.v1"
        or document.get("comparison_id") != run.plan["comparison_id"]
        or document.get("protocol_id") != run.protocol.protocol_id
        or document.get("test_corpus_id") != run.corpus.id
        or document.get("pilot_id") != stable_id("comparison-pilot-set", body)
        or document.get("status") != "PASS"
    ):
        raise ValueError("development pilot identity or status differs from frozen comparison")
    representatives = {(c["member_id"], c["config_label"]): c for c in run.cells.values()}
    wanted = set(representatives)
    actual = [(row["member_id"], row["config_label"]) for row in document["members"]]
    if set(actual) != wanted or len(actual) != len(wanted):
        raise ValueError("pilot omits or duplicates a frozen member/config")
    artifact = _saved_auxiliary_artifact(run, run.bundle["development_dataset"])
    development_id = _comparison_content_sha256(run, artifact.metadata)
    other_content = {c["logical_content_id"] for c in run.cells.values()}
    other_content.update(
        _comparison_content_sha256(run, _saved_auxiliary_artifact(run, key).metadata)
        for key in run.bundle["qualification_datasets"]
    )
    if development_id in other_content:
        raise ValueError("pilot development content overlaps evaluation or qualification")
    for row in document["members"]:
        pilot = row["pilot"]
        cell = representatives[row["member_id"], row["config_label"]]
        if (
            pilot.get("development_corpus_id") != development_id
            or pilot.get("test_corpus_id") != run.corpus.id
            or not _qualified_expectation({"outcome": "PASS"}, row["development_preflight"])
        ):
            raise ValueError("pilot workload lacks separate original-object recovery qualification")
        _validate_preflight_artifacts(
            run,
            cell,
            row["development_preflight"],
            "development",
            run.bundle["development_dataset"],
        )
        task, routed, _ = _saved_preflight_inputs(run, cell, run.bundle["development_dataset"])
        if run.protocol.profile == "COLD_PROCESS":
            expected_probe = {
                "dataset_id": routed.dataset_id,
                "algorithm_id": cell["algorithm_id"],
                "codec_key": cell["codec_key"],
                "parameters": cell["parameters"],
                "logical_cpus": list(run.bundle["cpu_affinity"]),
                "threads": cell["resources"]["threads"],
                "memory_limit_bytes": cell["resources"]["memory_limit_bytes"],
                "source_reject_fallback": _uses_source_reject_fallback(cell),
            }
            if pilot.get("probe_identity") != expected_probe:
                raise ValueError("cold pilot actual codec/configuration/fixture binding differs")
        else:
            _validate_saved_pilot_probe(run, cell, pilot, row.get("probe_binding"), task, routed)
        validator = (
            validate_cold_pilot_evidence
            if run.protocol.profile == "COLD_PROCESS"
            else validate_pilot_evidence
        )
        if not validator(run.protocol, pilot)["eligible"]:
            raise ValueError("pilot raw observations do not satisfy the frozen protocol gates")


def _validate_saved_pilot_probe(run, cell, pilot, reference, task, routed):
    pid = (pilot.get("lifecycle") or {}).get("worker_pid")
    path = (run.path / "pilot_probes" / (str(pid) + ".json")).resolve()
    if not isinstance(reference, dict) or reference.get("path") != str(path):
        raise ValueError("pilot probe artifact belongs to another worker")
    payload = path.read_bytes()
    if reference != {
        "path": str(path),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }:
        raise ValueError("pilot probe artifact bytes changed")
    if json.loads(payload) != {
        "schema_version": "tscb.comparison-pilot-probe-binding.v1",
        "worker_pid": pid,
        "codec_key": cell["codec_key"],
        "algorithm_id": cell["algorithm_id"],
        "dataset_id": routed.dataset_id,
        "input_sha256": routed.input_sha256,
        "canonical_raw_bits": routed.canonical_raw_bits,
        "track": routed.track.value,
        "parameters": cell["parameters"],
        "compatibility_plan_id": task["compatibility"]["compatibility_plan_id"],
        "source_reject_fallback": _uses_source_reject_fallback(cell),
    }:
        raise ValueError("pilot actual codec/configuration/fixture binding differs")


def pilot_comparison(run: ComparisonRun, registry: DatasetRegistry) -> dict[str, Any]:
    from tscompbench.codecs import SourceRegistry
    from tscompbench.measurement.resource_lease import ResourceLease

    validate_frozen_comparison(run.path, run.bundle, run.plan)
    resources = run.contract.to_document()["resources"]
    sources = SourceRegistry(run.project_root / "registry" / "sources")
    representatives = {(c["member_id"], c["config_label"]): c for c in run.cells.values()}
    pilots = []
    with ResourceLease(
        run_set_id=run.schedule.run_set_id + "-pilot",
        logical_cpus=run.bundle["cpu_affinity"],
        threads=resources["threads"],
        memory_limit_bytes=resources["memory_limit_bytes"],
    ):
        for cell in representatives.values():
            manifest = run.manifests[cell["codec_key"]]
            task, artifact = _auxiliary_input(
                run, registry, run.bundle["development_dataset"], cell
            )
            preflight, prepared = preflight_task(
                task,
                manifest,
                sources.get(manifest.source_artifact_id),
                artifact,
                _comparison_adapter(run.project_root, manifest, cell),
                cell["parameters"],
                cpu_affinity=task.execution.cpu_affinity,
                capture_directory=_qualification_capture_directory(
                    run, cell, "development", run.bundle["development_dataset"]
                ),
            )
            if preflight.status is not RunStatus.PASS or prepared is None:
                raise ValueError("development workload failed independent recovery qualification")
            if run.protocol.profile == "COLD_PROCESS":
                probe = ColdPilotProbe(
                    run.project_root,
                    manifest,
                    prepared.original,
                    task.compatibility,
                    cell["parameters"],
                    tuple(run.bundle["cpu_affinity"]),
                    resources["memory_limit_bytes"],
                    threads=resources["threads"],
                    source_reject_fallback=_uses_source_reject_fallback(cell),
                )
                pilot = run_cold_pilot(
                    run.protocol,
                    probe,
                    development_corpus_id=_comparison_content_sha256(run, artifact.metadata),
                    test_corpus_id=run.corpus.id,
                )
            else:
                base = DeclaredPilotProbe(
                    run.project_root,
                    manifest.key,
                    manifest.document,
                    manifest.algorithm_id,
                    prepared.original,
                    task.compatibility,
                    cell["parameters"],
                    replace(run.policy, resource_collector_enabled=False),
                    _uses_source_reject_fallback(cell),
                    run.path / "pilot_probes",
                )
                enabled = replace(base, policy=replace(run.policy, resource_collector_enabled=True))
                pilot = run_pilot(
                    run.protocol,
                    base,
                    development_corpus_id=_comparison_content_sha256(run, artifact.metadata),
                    test_corpus_id=run.corpus.id,
                    harness_probe=pilot_harness_probe,
                    collector_enabled_probe=enabled,
                )
            row = {
                "member_id": cell["member_id"],
                "config_label": cell["config_label"],
                "development_preflight": evidence_document(preflight.to_document()),
                "pilot": pilot,
            }
            if run.protocol.profile != "COLD_PROCESS":
                probe_path = (
                    run.path / "pilot_probes" / (str(pilot["lifecycle"]["worker_pid"]) + ".json")
                )
                payload = probe_path.read_bytes()
                row["probe_binding"] = {
                    "path": str(probe_path.resolve()),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }
            pilots.append(row)
    document = {
        "schema_version": "tscb.comparison-pilot-set.v1",
        "protocol_id": run.protocol.protocol_id,
        "comparison_id": run.plan["comparison_id"],
        "test_corpus_id": run.corpus.id,
        "status": "PASS" if all(p["pilot"]["status"] == "PASS" for p in pilots) else "INCONCLUSIVE",
        "members": pilots,
        "harness_boundary": (
            "PARENT_EXTERNAL_CLOCK_PAIR_NOT_PROCESS_STARTUP_BASELINE"
            if run.protocol.profile == "COLD_PROCESS"
            else "EMPTY_EXTERNAL_CLOCK_DISPATCH_DRIVER"
        ),
        "collector_control": "PROCESS_BOUNDARY_PROC_DISABLED_BASIC_RUSAGE_RETAINED",
        "overhead_subtracted": False,
    }
    document = evidence_document(document)
    document["pilot_id"] = stable_id("comparison-pilot-set", document)
    _write_or_verify_json(run.path / "pilot.json", document)
    return document


def _execute_cold_trial(
    run: ComparisonRun,
    cell: dict[str, Any],
    repetition_index: int,
    deadline_ns: int,
) -> tuple[RunRecord, bytes | None]:
    """Measure one cold object after frozen qualification, without a warmup worker."""
    from tscompbench.measurement.workloads import unavailable_workloads

    task = run.tasks[cell["cell_id"]]
    manifest = run.manifests[cell["codec_key"]]
    routed = route_canonical_artifact(run.artifacts[cell["dataset_id"]], task.track)
    observation = measure_cold_object(
        run.project_root,
        manifest,
        routed,
        task.compatibility,
        cell["parameters"],
        run.protocol,
        logical_cpus=tuple(run.bundle["cpu_affinity"]),
        memory_limit_bytes=cell["resources"]["memory_limit_bytes"],
        threads=cell["resources"]["threads"],
        trial_deadline_ns=deadline_ns,
        source_reject_fallback=_uses_source_reject_fallback(cell),
    )
    encoded = observation.encoded
    if (
        encoded is not None
        and DecodeContext(encoded.recovery_context).to_document()["adapter_id"]
        != task.execution.adapter_id
    ):
        raise ValueError("measured cold decoder identity differs from the frozen execution path")
    correctness = observation.correctness
    if (
        correctness is not None
        and correctness.status is not observation.status
        and (
            observation.status
            not in {RunStatus.RESOURCE_PRESSURE, RunStatus.OVERSUBSCRIBED, RunStatus.INCOMPARABLE}
        )
    ):
        correctness = None
    record = RunRecord.create(
        run_set_id=run.schedule.run_set_id,
        task_id=task.task_id,
        dataset_id=task.dataset_id,
        algorithm_id=task.algorithm_id,
        config_id=task.config_id,
        execution_path_hash=task.execution.execution_path_hash,
        semantic_comparability_key=task.comparability.semantic_key,
        execution_comparability_key=task.comparability.execution_key,
        resource_profile_key=task.comparability.resource_key,
        track=task.track,
        record_kind="FORMAL_REPETITION",
        repetition_index=repetition_index,
        status=observation.status,
        reason_code=observation.reason,
        input_sha256=routed.input_sha256,
        bitstream_sha256=None if encoded is None else encoded.stream_sha256,
        finalize_bytes=None if encoded is None else encoded.finalize_bytes,
        timing=None if observation.timing is None else observation.timing.to_document(),
        resources=None if observation.resources is None else observation.resources.to_document(),
        workloads=unavailable_workloads(
            features=manifest.document["features"],
            query_requested=False,
            streaming_requested=False,
            query_workload_id=None,
        ).to_document(),
        accounting=None if encoded is None else encoded.ledger,
        correctness=correctness,
        diagnostics={
            **observation.diagnostics,
            "cold_observation": observation.to_document(),
            "qualification_evidence_scope": "FROZEN_ORIGINAL_OBJECT_QUALIFICATION",
            "lifecycle_trace": list(observation.lifecycle_trace),
        },
        benchmark_eligible=observation.status is RunStatus.PASS,
    )
    # Incomplete decode does not provide the independently verified context chain
    # needed for formal saved-dependency audit; retain that failure in its record.
    stream = (
        encoded.stream
        if encoded is not None and "independent_recovery" in observation.diagnostics
        else None
    )
    return record, stream


def execute_comparison(run: ComparisonRun, pilot_evidence: dict[str, Any]) -> dict[str, Any]:
    """Run actual randomized independent processes under a host resource lease."""
    from tscompbench.measurement.resource_lease import ResourceLease, environment_gate

    validate_frozen_comparison(run.path, run.bundle, run.plan)
    validate_qualification_evidence(run, json.loads((run.path / "qualification.json").read_text()))
    validate_comparison_pilots(run, pilot_evidence)
    if control_plane_snapshot(run.project_root) != json.loads(
        (run.path / "control_plane.json").read_text()
    ):
        raise ValueError("execution source changed after freeze; use a new RunSet")
    if (
        capture_environment()["environment_id"]
        != json.loads((run.path / "environment.json").read_text())["environment_id"]
    ):
        raise ValueError("execution environment changed after freeze; use a new RunSet")
    _write_or_verify_json(run.path / "pilot.json", pilot_evidence)
    _write_or_verify_json(
        run.path / "qualified_execution_plan.json",
        {**run.plan, "pilot_eligible": True, "pilot_id": pilot_evidence["pilot_id"]},
    )
    plan = {**run.plan, "pilot_eligible": True, "pilot_id": pilot_evidence["pilot_id"]}
    executor_started = time.perf_counter_ns()
    descriptor = os.open(run.path / ".execution.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        existing = _read_trials(run.path / "comparison_trials.jsonl")
        completed = {t["scheduled_trial_id"] for t in existing}
        budget_path = run.path / "budget.json"
        prior_budget = (
            json.loads(budget_path.read_text())["used_active_executor_wall_ns"]
            if budget_path.exists()
            else 0
        )
        job_cells = {cell["execution_job_id"]: cell for cell in run.cells.values()}
        stopped = {
            t["cell_id"]: t["trial_id"]
            for t in existing
            if not t.get("formal_eligible") and (t.get("record") or {}).get("status") != "PASS"
        }
        event_path = run.path / "events.jsonl"
        events = (
            [json.loads(line) for line in event_path.read_text().splitlines()]
            if event_path.exists()
            else []
        )
        attempted = {
            e["payload"]["trial_id"]
            for e in events
            if e["event_type"] == "COMPARISON_TRIAL_STARTED"
        }
        unresolved_attempts = attempted - completed
        resources = run.contract.to_document()["resources"]
        with ResourceLease(
            run_set_id=run.schedule.run_set_id,
            logical_cpus=tuple(run.bundle["cpu_affinity"]),
            threads=resources["threads"],
            memory_limit_bytes=resources["memory_limit_bytes"],
        ) as lease:
            for scheduled in run.schedule.trials:
                if scheduled.trial_id in completed:
                    continue
                used_budget = prior_budget + time.perf_counter_ns() - executor_started
                if used_budget >= run.protocol.max_total_wall_ns:
                    append_event(
                        run.path / "events.jsonl",
                        "COMPARISON_BUDGET_EXHAUSTED",
                        {"used_wall_ns": used_budget},
                    )
                    break
                cell = job_cells[scheduled.job_id]
                task = run.tasks[cell["cell_id"]]
                manifest = run.manifests[cell["codec_key"]]

                source = json.loads(
                    (
                        run.path
                        / "sources"
                        / (manifest.source_artifact_id.rsplit(":", 1)[-1] + ".json")
                    ).read_text()
                )
                started = time.perf_counter_ns()
                lease_before = lease.to_document()
                if unresolved_attempts or cell["cell_id"] in stopped:
                    reason = (
                        "INTERRUPTED_ATTEMPT_RETAINED_NO_AUTOMATIC_RETRY"
                        if scheduled.trial_id in attempted
                        else "RUN_STOPPED_AFTER_UNRESOLVED_INTERRUPTED_ATTEMPT"
                        if unresolved_attempts
                        else "PATH_STOPPED_AFTER_FAILED_ATTEMPT"
                    )
                    trial = {
                        **scheduled.to_document(),
                        "schema_version": "tscb.comparison-trial.v1",
                        "scheduled_trial_id": scheduled.trial_id,
                        "block_id": str(scheduled.block_index),
                        "comparison_id": plan["comparison_id"],
                        "protocol_id": run.protocol.protocol_id,
                        "schedule_id": run.schedule.schedule_id,
                        "cell_id": cell["cell_id"],
                        "public_projection_key": cell["public_projection_key"],
                        "status": "INTERRUPTED" if scheduled.trial_id in attempted else "STOPPED",
                        "reason": reason,
                        "failed_trial_id": stopped.get(cell["cell_id"])
                        or (min(unresolved_attempts) if unresolved_attempts else None),
                        "started_ns": started,
                        "finished_ns": time.perf_counter_ns(),
                        "formal_eligible": False,
                        "record": None,
                    }
                    _append_trial(run.path / "comparison_trials.jsonl", trial)
                    stopped[cell["cell_id"]] = scheduled.trial_id
                    append_event(event_path, "COMPARISON_SLOT_STOPPED", trial)
                    continue
                allocated_trial_ns = min(
                    run.protocol.max_trial_wall_ns, run.protocol.max_total_wall_ns - used_budget
                )
                deadline = started + allocated_trial_ns
                # A killed owner cannot supply an exact final duration. Reserve
                # the entire allowed attempt before launch; resume retains this
                # conservative budget and never repeats the unresolved attempt.
                _replace_json(
                    budget_path,
                    {
                        "schema_version": "tscb.comparison-budget.v1",
                        "used_active_executor_wall_ns": used_budget + allocated_trial_ns,
                        "actual_used_before_attempt_ns": used_budget,
                        "reserved_attempt_ns": allocated_trial_ns,
                        "accounting_status": "CONSERVATIVE_PENDING_ATTEMPT_RESERVATION",
                        "max_total_wall_ns": run.protocol.max_total_wall_ns,
                        "scope": "ACTIVE_EXECUTOR_INCLUDING_LEASE_SETUP_SCHEDULING_AND_TRIALS",
                        "paused_time_included": False,
                        "trial_id": scheduled.trial_id,
                        "deadline_ns": deadline,
                    },
                )
                append_event(
                    run.path / "events.jsonl",
                    "COMPARISON_TRIAL_STARTED",
                    {
                        **scheduled.to_document(),
                        "started_ns": started,
                        "deadline_ns": deadline,
                        "owner_pid": os.getpid(),
                        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                    },
                )
                try:
                    if run.protocol.profile == "COLD_PROCESS":
                        record, stream = _execute_cold_trial(
                            run, cell, scheduled.repetition_index, deadline
                        )
                        records = (record,)
                        bitstreams = () if stream is None else ((record.run_id, stream),)
                        qualification_status = "PASS"
                    else:
                        result = execute_task(
                            run_set_id=run.schedule.run_set_id,
                            task=task,
                            manifest=manifest,
                            source=source,
                            artifact=run.artifacts[cell["dataset_id"]],
                            adapter=_comparison_adapter(run.project_root, manifest, cell),
                            parameters=cell["parameters"],
                            measurement_policy=run.policy,
                            repetitions=run.protocol.outer_repetitions,
                            repetition_indices=(scheduled.repetition_index,),
                            trial_deadline_ns=deadline,
                        )
                        records, bitstreams = result.records, result.bitstreams
                        qualification_status = result.preflight.status.value
                    if len(records) != 1:
                        raise ValueError(
                            "one scheduled process slot must produce one terminal record"
                        )
                except Exception as error:
                    failed = {
                        **scheduled.to_document(),
                        "schema_version": "tscb.comparison-trial.v1",
                        "scheduled_trial_id": scheduled.trial_id,
                        "block_id": str(scheduled.block_index),
                        "comparison_id": plan["comparison_id"],
                        "protocol_id": run.protocol.protocol_id,
                        "schedule_id": run.schedule.schedule_id,
                        "cell_id": cell["cell_id"],
                        "public_projection_key": cell["public_projection_key"],
                        "status": "DRIVER_FAILED",
                        "started_ns": started,
                        "finished_ns": time.perf_counter_ns(),
                        "exception_type": type(error).__name__,
                        "message": str(error),
                        "formal_eligible": False,
                        "record": None,
                    }
                    _append_trial(run.path / "comparison_trials.jsonl", failed)
                    stopped[cell["cell_id"]] = scheduled.trial_id
                    append_event(event_path, "COMPARISON_DRIVER_FAILED", failed)
                    continue
                finished = time.perf_counter_ns()
                used_budget = prior_budget + finished - executor_started
                gate = environment_gate(run.protocol, lease_before, lease.to_document())
                stream_by_id = dict(bitstreams)
                for record in records:
                    stream = stream_by_id.get(record.run_id)
                    verified = False
                    if stream is not None:
                        recovery = record.diagnostics["independent_recovery"]
                        context = DecodeContext(canonical_json_bytes(recovery["context_document"]))
                        if (
                            context.sha256 != recovery["context_sha256"]
                            or len(context.serialized) * 8 != recovery["required_external_bits"]
                        ):
                            raise ValueError(
                                "actual paid recovery context differs from worker evidence"
                            )
                        name = record.run_id.rsplit(":", 1)[-1]
                        _write_or_verify_bytes(run.path / "artifacts" / (name + ".bin"), stream)
                        _write_or_verify_bytes(
                            run.path / "artifacts" / (name + ".decode.json"), context.serialized
                        )
                        _write_or_verify_json(
                            run.path / "artifacts" / (name + ".decoder.json"),
                            {
                                "schema_version": "tscb.decoder-dependency.v1",
                                "codec_key": manifest.key,
                                "manifest": manifest.document,
                                "execution_path_hash": task.execution.execution_path_hash,
                                "artifact_sha256": task.execution.artifact_sha256,
                                "cost_role": "DECLARED_PUBLIC_DECODER_PROGRAM",
                            },
                        )
                        verified = hashlib.sha256(stream).hexdigest() == record.bitstream_sha256
                    append_run_record(run.path, record)
                    trial = {
                        "schema_version": "tscb.comparison-trial.v1",
                        "trial_id": scheduled.trial_id,
                        "scheduled_trial_id": scheduled.trial_id,
                        "pair_id": scheduled.pair_id,
                        "block_id": str(scheduled.block_index),
                        "sequence_index": scheduled.sequence_index,
                        "repetition_index": scheduled.repetition_index,
                        "round_index": scheduled.round_index,
                        "comparison_id": plan["comparison_id"],
                        "protocol_id": run.protocol.protocol_id,
                        "schedule_id": run.schedule.schedule_id,
                        "cell_id": cell["cell_id"],
                        "execution_job_id": cell["execution_job_id"],
                        "public_projection_key": cell["public_projection_key"],
                        "started_ns": started,
                        "finished_ns": finished,
                        "lease_held": True,
                        "resource_lease_id": lease_before["lease_id"],
                        "resource_lease": lease_before,
                        "environment_gate": evidence_document(gate),
                        "qualification_status": qualification_status,
                        "artifacts_verified": verified,
                        "formal_eligible": True,
                        "record": evidence_document(record.to_document()),
                    }
                    issues = trial_issues(trial, cell, plan)
                    trial["formal_eligible"] = not issues
                    trial["exclusion_reasons"] = issues
                    _append_trial(run.path / "comparison_trials.jsonl", trial)
                    if record.status is not RunStatus.PASS or not verified:
                        stopped[cell["cell_id"]] = scheduled.trial_id
                        # Correctness, safety and dependency failure suspends this
                        # method/config across the frozen corpus; retain all slots.
                        if record.status in {RunStatus.CORRECTNESS_FAIL, RunStatus.CRASHED} or (
                            record.status is RunStatus.PASS and not verified
                        ):
                            for other in run.cells.values():
                                if (other["algorithm_id"], other["legacy_config_id"]) == (
                                    cell["algorithm_id"],
                                    cell["legacy_config_id"],
                                ):
                                    stopped[other["cell_id"]] = scheduled.trial_id
                append_event(
                    run.path / "events.jsonl",
                    "COMPARISON_TRIAL_FINISHED",
                    {
                        "trial_id": scheduled.trial_id,
                        "started_ns": started,
                        "finished_ns": finished,
                        "used_budget_ns": used_budget,
                    },
                )
                _replace_json(
                    budget_path,
                    {
                        "schema_version": "tscb.comparison-budget.v1",
                        "used_active_executor_wall_ns": used_budget,
                        "max_total_wall_ns": run.protocol.max_total_wall_ns,
                        "scope": "ACTIVE_EXECUTOR_INCLUDING_LEASE_SETUP_SCHEDULING_AND_TRIALS",
                        "paused_time_included": False,
                    },
                )
        _replace_json(
            budget_path,
            {
                "schema_version": "tscb.comparison-budget.v1",
                "used_active_executor_wall_ns": prior_budget
                + time.perf_counter_ns()
                - executor_started,
                "max_total_wall_ns": run.protocol.max_total_wall_ns,
                "scope": "ACTIVE_EXECUTOR_INCLUDING_LEASE_SETUP_SCHEDULING_AND_TRIALS",
                "paused_time_included": False,
            },
        )
        return report_comparison(run.path)
    finally:
        os.close(descriptor)


def audit_trial_artifacts(run_path: Path, trials: list[dict], plan: dict) -> dict[str, Any]:
    cells = {c["cell_id"]: c for c in plan["cells"]}
    observations = []
    for trial in trials:
        record = trial.get("record") or {}
        name = str(record.get("run_id", "")).rsplit(":", 1)[-1]
        verified = False
        observation = {"trial_id": trial["trial_id"], "files": [], "reasons": []}
        try:
            if len(name) != 64 or any(c not in "0123456789abcdef" for c in name):
                raise ValueError("no finalized RunID artifact")
            cell = cells[trial["cell_id"]]
            payloads = []
            for suffix in (".bin", ".decode.json", ".decoder.json"):
                path = run_path / "artifacts" / (name + suffix)
                payload = path.read_bytes()
                payloads.append(payload)
                observation["files"].append(
                    {
                        "path": str(path.relative_to(run_path)),
                        "bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                )
            stream, context_bytes, dependency_bytes = payloads
            context = DecodeContext(context_bytes)
            dependency = json.loads(dependency_bytes)
            manifest = json.loads((run_path / "codecs" / (cell["codec_key"] + ".json")).read_text())
            job = json.loads(
                (run_path / "jobs" / (cell["cell_id"].rsplit(":", 1)[-1] + ".json")).read_text()
            )["execution_job"]
            expected_dependency = {
                "schema_version": "tscb.decoder-dependency.v1",
                "codec_key": cell["codec_key"],
                "manifest": manifest,
                "execution_path_hash": cell["execution_path_hash"],
                "artifact_sha256": job["build_id"],
                "cost_role": "DECLARED_PUBLIC_DECODER_PROGRAM",
            }
            ledger = record["accounting"]
            recovery = record["diagnostics"]["independent_recovery"]
            component_bits = sum(
                ledger[key]
                for key in (
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
            )
            verified = (
                hashlib.sha256(stream).hexdigest() == record["bitstream_sha256"]
                and ledger["serialized_bits"] == component_bits == len(stream) * 8
                and ledger["final_physical_bytes"] == len(stream)
                and context.sha256 == recovery["context_sha256"]
                and len(context.serialized) * 8
                == recovery["required_external_bits"]
                == ledger["external_side_information_bits"]
                and ledger["final_bits"] == len(stream) * 8 + len(context.serialized) * 8
                and context.to_document()["parameters"] == cell["parameters"]
                and context.to_document()["canonical_raw_bits"] == cell["canonical_raw_bits"]
                and context.to_document() == recovery["context_document"]
                and dependency == expected_dependency
            )
            if not verified:
                observation["reasons"].append("SAVED_DEPENDENCY_OR_PHYSICAL_COST_MISMATCH")
        except (OSError, ValueError, KeyError, TypeError) as error:
            observation["reasons"].append(type(error).__name__ + ": " + str(error))
        observation["verified"] = verified
        trial["artifacts_verified"] = verified
        observations.append(observation)
    return {
        "schema_version": "tscb.comparison-artifact-audit.v1",
        "scope": "SAVED_STREAM_CONTEXT_AND_PUBLIC_DECODER_DECLARATION_PHYSICAL_HASH_AND_COST",
        "codec_invoked": False,
        "observations": observations,
        "sha256": hashlib.sha256(canonical_json_bytes(observations)).hexdigest(),
    }


def validate_frozen_comparison(run_path: Path, bundle: dict, plan: dict) -> None:
    """Verify the frozen identity chain without loading or invoking a codec."""
    contract = ComparisonContract.from_document(bundle["contract"])
    corpus = CorpusSpec.from_document(bundle["corpus"])
    group = GroupSpec.from_document(bundle["group"])
    config_map = MethodConfigMap.from_document(bundle["config_map"])
    expected = ExpectedOutcomeMatrix.from_document(bundle["expected_matrix"])
    protocol = MeasurementProtocol.from_document(bundle["protocol"])
    policy = AnalysisPolicy.from_document(bundle["analysis_policy"])
    schedule = FrozenSchedule.from_document(plan["schedule"])
    if (
        plan["protocol_id"] != protocol.protocol_id
        or plan["analysis_policy_id"] != policy.id
        or plan["protocol"] != protocol.to_document()
        or plan["schedule_id"] != schedule.schedule_id
        or plan["schedule"] != json.loads((run_path / "schedule.json").read_text())
        or schedule.blocks * schedule.rounds_per_block != plan["planned_repetitions_per_cell"]
    ):
        raise ValueError("frozen execution and measurement/analysis/schedule identities differ")
    compiled = json.loads((run_path / "comparison_plan.json").read_text())
    for key, identity in (
        ("group_id", group.id),
        ("contract_id", contract.id),
        ("corpus_id", corpus.id),
        ("config_map_id", config_map.id),
        ("expected_matrix_id", expected.id),
    ):
        if compiled[key] != identity:
            raise ValueError("frozen plan specification identity differs: " + key)
    expected_cells = {row["cell_id"]: row for row in compiled["cells"]}
    cells = {row["cell_id"]: row for row in plan["cells"]}
    if len(cells) != len(plan["cells"]) or set(cells) != set(expected_cells):
        raise ValueError("frozen execution matrix differs from planned fixed denominator")
    equivalence = {
        mid: item["class_id"]
        for item in bundle["group"]["method_equivalence"]
        for mid in item["members"]
    }
    if plan["independent_real_source_count"] != len(corpus.independent_real_source_groups()):
        raise ValueError("frozen real source denominator differs from corpus derivation closure")
    for cell_id, row in expected_cells.items():
        execution_cell = cells[cell_id]
        if any(execution_cell.get(key) != value for key, value in row.items()):
            raise ValueError("frozen execution cell differs from specification")
        if execution_cell["method_equivalence_class"] != equivalence[row["member_id"]]:
            raise ValueError("frozen method denominator differs from declared equivalence")
        cell = PlannedComparisonCell(
            canonical_json_bytes({k: v for k, v in row.items() if k != "cell_id"})
        )
        if cell.id != cell_id:
            raise ValueError("frozen cell identity differs from its definition")
        job_doc = json.loads(
            (run_path / "jobs" / (cell_id.rsplit(":", 1)[-1] + ".json")).read_text()
        )
        task = TaskSpec.from_document(job_doc["task_spec"])
        job = ExecutionJob.from_document(job_doc["execution_job"])
        codec_doc = json.loads((run_path / "codecs" / (row["codec_key"] + ".json")).read_text())
        if stable_id("algorithm", codec_doc) != row["algorithm_id"]:
            raise ValueError("frozen codec definition differs from AlgorithmID")
        validate_job_for_cell(group, cell, task, job)
        projection = public_projection(contract, task, job)
        if (
            job.id != execution_cell["execution_job_id"]
            or projection.key != execution_cell["public_projection_key"]
        ):
            raise ValueError("frozen public projection or execution job identity differs")
    environment = json.loads((run_path / "environment.json").read_text())
    closure = json.loads((run_path / "control_plane.json").read_text())
    decision = comparison_decision(
        bundle,
        environment_id=environment["environment_id"],
        control_plane_sha256=closure["sha256"],
        workload_protocol=plan.get("decision_workload_protocol"),
    )
    validate_experiment_decision(run_path, plan, decision)
    expected_id = stable_id(
        "comparison-execution",
        {
            "group_plan": stable_id("comparison-plan", compiled, version="v3"),
            "protocol_id": protocol.protocol_id,
            "analysis_policy_id": policy.id,
            "environment_id": environment["environment_id"],
            "control_plane_sha256": closure["sha256"],
            "decision_id": decision["decision_id"],
            "run_set_id": schedule.run_set_id,
            "cpu_affinity": bundle["cpu_affinity"],
        },
    )
    if expected_id != plan["comparison_id"]:
        raise ValueError("frozen comparison identity differs from its complete input chain")


def report_comparison(run_path: Path) -> dict[str, Any]:
    """Rebuild human and machine reports exclusively from frozen plan and raw."""
    bundle = load_comparison_bundle(run_path / "bundle.json")
    policy = AnalysisPolicy.from_document(bundle["analysis_policy"])
    plan_path = run_path / "qualified_execution_plan.json"
    plan = json.loads(
        (plan_path if plan_path.exists() else run_path / "execution_plan.json").read_text()
    )
    validate_frozen_comparison(run_path, bundle, plan)
    trials = _read_trials(run_path / "comparison_trials.jsonl")
    artifact_audit = audit_trial_artifacts(run_path, trials, plan)
    raw_path = run_path / "comparison_trials.jsonl"
    analysis = analyze_comparison(
        plan,
        trials,
        policy,
        raw_file_sha256=hashlib.sha256(
            raw_path.read_bytes() if raw_path.exists() else b""
        ).hexdigest(),
        artifact_audit=artifact_audit,
    )
    analysis["decision_id"] = plan["decision_id"]
    analysis["decision"] = plan["decision"]
    _replace_json(run_path / "analysis.json", analysis)
    from .analysis_extensions import augment_analysis
    from .report_renderer import render_comparison_report

    extensions = augment_analysis(analysis, plan, trials, bundle["corpus"])
    _replace_json(run_path / "analysis_extensions.json", extensions)
    disclosures = {
        cell["cell_id"]: json.loads(
            (run_path / "jobs" / (cell["cell_id"].rsplit(":", 1)[-1] + ".json")).read_text()
        )["disclosures"]
        for cell in plan["cells"]
    }
    page = render_comparison_report(
        analysis,
        plan=plan,
        bundle=bundle,
        extensions=extensions,
        disclosures=disclosures,
        raw_links={
            "Analysis and paired intervals": "analysis.json",
            "Quality, Pareto, source balance and coverage": "analysis_extensions.json",
            "Immutable raw trials": "comparison_trials.jsonl",
            "Frozen contracts": "bundle.json",
            "Pre-measurement decision contract": "experiment_decision.json",
            "Independent uncompressed cost reference (not FORMAL)": "uncompressed_reference.json",
            "Uncompressed reference boundaries": "uncompressed_reference.md",
            "Schedule": "schedule.json",
            "Original-object qualification": "qualification.json",
            "Development pilot": "pilot.json",
            "Events": "events.jsonl",
            "Decoder artifacts": "artifacts/",
        },
    )
    (run_path / "report.html").write_text(page, encoding="utf-8")
    return {
        "status": analysis["status"],
        "analysis_id": analysis["analysis_id"],
        "coverage": analysis["coverage"],
        "path": str(run_path),
        "report": str(run_path / "report.html"),
    }
