"""Frozen P2 object comparisons with existing children and independent recovery.

This lane is separate from P1/core codec comparisons. The measured PIPELINE
boundary includes preparation, each real child bound/allocation/API, the complete
public tree, hashes and owned output materialization. File loading and fresh
process qualification are outside steady timing and remain explicit evidence.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from tscompbench.adapters import create_adapter
from tscompbench.adapters.factory import adapter_artifacts
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.comparison.analysis import AnalysisPolicy, _description, _effect
from tscompbench.comparison.decision import (
    freeze_experiment_decision,
    pipeline_decision,
    validate_experiment_decision,
)
from tscompbench.comparison.runner import control_plane_snapshot, evidence_document
from tscompbench.contracts import RunStatus
from tscompbench.datasets.canonical import read_canonical
from tscompbench.execution.isolation import run_isolated
from tscompbench.execution.schedule import FrozenSchedule, build_schedule
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.measurement.resource_lease import ResourceLease, environment_gate
from tscompbench.measurement.resources import ResourceSampler
from tscompbench.measurement.thread_monitor import thread_budget_evidence
from tscompbench.measurement.v32_protocol import (
    MeasurementProtocol,
    run_pilot,
    validate_pilot_evidence,
)
from tscompbench.pipelines import (
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineRecipe,
    decode_object,
    encode_object,
    validate_restored_object,
)
from tscompbench.pipelines.models import PipelineLedger
from tscompbench.pipelines.runtime import _parse, object_output_bound

VERSION = "tscb.pipeline-comparison.v3.2"
METHODS = ("lz4-frame", "zstd-frame")
BOUNDARY = "BOUND_PREPARE_CHILD_APIS_PUBLIC_TREE_HASHES_OWNED_MATERIALIZATION"
SCOPE = "P2_LOSSLESS_DERIVED_OBJECTS_FIXED_CORPUS_CPU_ONLY"
ATTEMPT_POLICY = {
    "schema_version": "tscb.pipeline-attempt-policy.v1",
    "max_attempts_per_slot": 1,
    "event_log": "pipeline_events.jsonl",
    "event_integrity": "SHA256_CHAIN_BOUND_TO_FROZEN_PLAN_AND_RAW_TERMINAL",
    "interruption_policy": "BLOCK_UNKNOWN_STARTED_ATTEMPT_NEVER_AUTOMATICALLY_RETRY",
    "budget_policy": "RESERVE_BEFORE_WORKER_RETAIN_RESERVATION_UNTIL_DURABLE_TERMINAL",
    "artifact_policy": "EXCLUSIVE_CREATE_AND_PRESERVE_EXISTING_BYTES",
}


class PipelineComparisonError(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, document: Any, *, immutable: bool = True) -> None:
    value = canonical_json_bytes(evidence_document(document))
    if path.exists() and immutable:
        if path.read_bytes() != value:
            raise PipelineComparisonError(f"frozen document drift: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(value)
    temporary.replace(path)


def save_pipeline_input(path: Path, original: LogicalObject) -> dict[str, Any]:
    """Save only typed owned arrays and schema; object loading disallows pickle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {f"value_{i}": a for i, a in enumerate(original.values.values())}
    if original.timestamp is not None:
        arrays["timestamp"] = original.timestamp
    if original.validity is not None:
        arrays.update({f"mask_{i}": a for i, a in enumerate(original.validity.values())})
    if not path.exists():
        with path.open("wb") as handle:
            np.savez(handle, **arrays)
    document = {
        "schema": original.schema.to_document(),
        "logical_content_id": original.content_id,
        "underlying_bytes_sha256": original.underlying_bytes_sha256,
        "canonical_raw_bits": original.canonical_raw_bits,
        "validity_present": original.validity is not None,
        "path": str(path.resolve()),
        "file_sha256": _sha(path),
    }
    loaded = load_pipeline_input(document)
    if loaded.underlying_bytes_sha256 != original.underlying_bytes_sha256:
        raise PipelineComparisonError("existing pipeline input differs from the frozen object")
    return document


def load_pipeline_input(document: dict[str, Any]) -> LogicalObject:
    path = Path(document["path"])
    if _sha(path) != document["file_sha256"]:
        raise PipelineComparisonError("pipeline input file drift")
    schema = LogicalObjectSchema.from_document(document["schema"])
    names = [v["name"] for v in schema.to_document()["values"]]
    with np.load(path, allow_pickle=False) as arrays:
        expected = {f"value_{i}" for i in range(len(names))}
        timestamp = None
        validity = None
        if schema.to_document()["timestamp"]["present"]:
            expected.add("timestamp")
            timestamp = arrays["timestamp"].copy()
        if document["validity_present"]:
            expected.update(f"mask_{i}" for i in range(len(names)))
            validity = {name: arrays[f"mask_{i}"].copy() for i, name in enumerate(names)}
        if set(arrays.files) != expected:
            raise PipelineComparisonError("pipeline input buffer set differs from schema")
        values = {name: arrays[f"value_{i}"].copy() for i, name in enumerate(names)}
    original = LogicalObject(schema, values, timestamp, validity)
    for array in [
        *values.values(),
        *([] if timestamp is None else [timestamp]),
        *([] if validity is None else validity.values()),
    ]:
        array.flags.writeable = False
    if (
        original.content_id != document["logical_content_id"]
        or original.underlying_bytes_sha256 != document["underlying_bytes_sha256"]
        or original.canonical_raw_bits != document["canonical_raw_bits"]
    ):
        raise PipelineComparisonError("pipeline input content/schema/denominator drift")
    return original


def _child_closure(project_root: Path, keys: tuple[str, ...]) -> dict[str, Any]:
    sources = SourceRegistry(project_root / "registry/sources")
    registry = CodecRegistry(project_root / "registry/codecs", sources)
    children = {}
    for key in keys:
        manifest = registry.get(key)
        adapter = create_adapter(project_root, manifest, source_reject_fallback=False)
        artifact, support = adapter_artifacts(project_root, manifest)
        paths = list(dict.fromkeys([artifact, *support]))
        # Byte children have local native build/source evidence next to the .so.
        record = artifact.parent / "build-record.json"
        if record.is_file() and record not in paths:
            paths.append(record)
        source = sources.get(manifest.document["identity"]["source_artifact_id"])
        for unit in source.get("build", {}).get("translation_units", []):
            unit_path = Path(unit)
            if len(unit_path.parts) >= 2 and unit_path.parts[0] == "adapters":
                source_root = project_root / Path(*unit_path.parts[:2])
                paths.extend(
                    p
                    for p in source_root.rglob("*")
                    if p.is_file() and p.suffix in {".c", ".h", ".cc", ".cpp", ".hpp", ".cxx"}
                )
        paths = sorted(set(paths))
        children[key] = {
            "manifest": manifest.document,
            "adapter_id": adapter.adapter_id,
            "source": source,
            "files": [{"path": str(p.resolve()), "sha256": _sha(p)} for p in paths],
        }
    return {"children": children, "control_plane": control_plane_snapshot(project_root)}


def prepare_pipeline_comparison(
    project_root: Path,
    run_path: Path,
    datasets: list[dict[str, Any]],
    *,
    protocol: MeasurementProtocol,
    policy: AnalysisPolicy,
    resources: dict[str, Any],
    block_size: int = 256,
    seed: int = 20261010,
) -> dict[str, Any]:
    if (run_path / "plan.json").exists() and not (run_path / "experiment_decision.json").is_file():
        raise PipelineComparisonError("P2 resume requires its pre-measurement experiment decision")
    if (
        protocol.profile != "STEADY_PROCESS"
        or protocol.timing_scope != "PIPELINE"
        or protocol.collector_mode != "ENABLED"
        or protocol.start_method != "spawn"
        or protocol.max_retries != 0
        or protocol.stop_mode != "FIXED_REPETITIONS"
    ):
        raise PipelineComparisonError(
            "P2 lane requires the implemented fixed steady PIPELINE protocol"
        )
    if not protocol.thread_monitor_interval_ns:
        raise PipelineComparisonError("P2 formal lane requires parent thread observations")
    if (
        set(resources) != {"logical_cpus", "threads", "memory_limit_bytes"}
        or resources["threads"] != 1
        or len(resources["logical_cpus"]) != 1
    ):
        raise PipelineComparisonError("this lane supports one serial worker on one declared CPU")
    if not datasets or len({d["dataset_key"] for d in datasets}) != len(datasets):
        raise PipelineComparisonError("datasets require unique fixed identities")
    cells = []
    dataset_methods = {}
    closure = _child_closure(project_root, METHODS)
    implementation_id = stable_id("pipeline-implementation-v32", closure)
    for dataset in datasets:
        test = load_pipeline_input(dataset["test"])
        development = load_pipeline_input(dataset["development"])
        if test.content_id == development.content_id:
            raise PipelineComparisonError("development and test objects must be disjoint")
        dataset_methods[dataset["dataset_key"]] = {}
        for key in METHODS:
            recipe = PipelineRecipe(
                {name: ChildSpec(key, {"native_timing": False}) for name in test.values},
                None if test.timestamp is None else ChildSpec(key, {"native_timing": False}),
                None if test.validity is None else ChildSpec(key, {"native_timing": False}),
                block_size,
                "RAW_TAIL",
            )
            identity = {
                "object": test.content_id,
                "recipe_id": recipe.recipe_id,
                "protocol_id": protocol.protocol_id,
                "resources": resources,
                "implementation_id": implementation_id,
            }
            job = stable_id("pipeline-job-v32", identity)
            dataset_methods[dataset["dataset_key"]][key] = job
            cells.append(
                {
                    "cell_id": stable_id("pipeline-cell-v32", identity),
                    "dataset_key": dataset["dataset_key"],
                    "method_id": key,
                    "execution_job_id": job,
                    "recipe": recipe.to_document(),
                    "recipe_id": recipe.recipe_id,
                    "canonical_raw_bits": test.canonical_raw_bits,
                }
            )
    decision = pipeline_decision(
        datasets=datasets,
        protocol=protocol.to_document(),
        analysis_policy=policy.to_document(),
        resources=resources,
        closure=closure,
        boundary=BOUNDARY,
        scope=SCOPE,
    )
    try:
        freeze_experiment_decision(run_path, decision, resume=(run_path / "plan.json").exists())
    except ValueError as error:
        raise PipelineComparisonError(str(error)) from error
    identity = {
        "schema_version": VERSION,
        "decision_id": decision["decision_id"],
        "datasets": datasets,
        "cells": cells,
        "protocol": protocol.to_document(),
        "analysis_policy": policy.to_document(),
        "resources": resources,
        "closure": closure,
    }
    run_id = stable_id("pipeline-run-v32", identity)
    schedule = build_schedule(
        run_set_id=run_id,
        dataset_methods=dataset_methods,
        protocol_id=protocol.protocol_id,
        seed=seed,
        blocks=protocol.outer_repetitions,
        max_retries=0,
    )
    plan = {
        **identity,
        "decision": decision,
        "project_root": str(project_root.resolve()),
        "run_set_id": run_id,
        "schedule": schedule.to_document(),
        "schedule_id": schedule.schedule_id,
        "boundary": BOUNDARY,
        "scope": SCOPE,
        "denominator_policy": "FIXED_LOGICAL_OBJECT_INCLUDING_T_AND_VALIDITY",
        "resource_scope": (
            "BATCH_PROCESS_BOUNDARIES_AFTER_WARMUP_RSS_HIGH_WATER_INCLUDES_IMPORT_AND_WARMUP"
        ),
        "memory_limit_policy": "RLIMIT_AS_WITH_EXISTING_VM_HEADROOM_AND_OBSERVED_RSS_GATE",
        "attempt_policy": ATTEMPT_POLICY,
    }
    _write(run_path / "plan.json", plan)
    return plan


def validate_pipeline_plan(plan: dict[str, Any], run_path: Path | None = None) -> None:
    if not isinstance(plan.get("decision"), dict) or not isinstance(plan.get("decision_id"), str):
        raise PipelineComparisonError("P2 plan requires its pre-measurement experiment decision")
    protocol = MeasurementProtocol.from_document(plan["protocol"])
    AnalysisPolicy.from_document(plan["analysis_policy"])
    schedule = FrozenSchedule.from_document(plan["schedule"])
    if plan["schema_version"] != VERSION or schedule.schedule_id != plan["schedule_id"]:
        raise PipelineComparisonError("P2 plan or schedule identity drift")
    if _child_closure(Path(plan["project_root"]), METHODS) != plan["closure"]:
        raise PipelineComparisonError("P2 source/build/registry/control closure drift")
    identity = {
        key: plan[key]
        for key in (
            "schema_version",
            "decision_id",
            "datasets",
            "cells",
            "protocol",
            "analysis_policy",
            "resources",
            "closure",
        )
    }
    if stable_id("pipeline-run-v32", identity) != plan["run_set_id"]:
        raise PipelineComparisonError("P2 frozen plan identity drift")
    if schedule.run_set_id != plan["run_set_id"] or schedule.protocol_id != protocol.protocol_id:
        raise PipelineComparisonError("P2 schedule belongs to another run/protocol")
    if plan["boundary"] != BOUNDARY or plan["scope"] != SCOPE:
        raise PipelineComparisonError("P2 implemented measurement boundary mismatch")
    if plan.get("attempt_policy") != ATTEMPT_POLICY:
        raise PipelineComparisonError("P2 durable attempt/budget policy mismatch")
    expected_decision = pipeline_decision(
        datasets=plan["datasets"],
        protocol=plan["protocol"],
        analysis_policy=plan["analysis_policy"],
        resources=plan["resources"],
        closure=plan["closure"],
        boundary=plan["boundary"],
        scope=plan["scope"],
    )
    if (
        plan.get("decision") != expected_decision
        or plan.get("decision_id") != expected_decision["decision_id"]
    ):
        raise PipelineComparisonError("P2 experiment decision/frozen input identity drift")
    if run_path is not None:
        try:
            validate_experiment_decision(run_path, plan, expected_decision)
        except ValueError as error:
            raise PipelineComparisonError(str(error)) from error
    for dataset in plan["datasets"]:
        load_pipeline_input(dataset["test"])
        load_pipeline_input(dataset["development"])
        for source in dataset.get("source_files", []):
            if _sha(Path(source["path"])) != source["sha256"]:
                raise PipelineComparisonError("P2 input provenance drift")
    expected = {(d["dataset_key"], key) for d in plan["datasets"] for key in METHODS}
    actual = {(c["dataset_key"], c["method_id"]) for c in plan["cells"]}
    if actual != expected or len(actual) != len(plan["cells"]):
        raise PipelineComparisonError("P2 fixed denominator/cell coverage drift")
    for cell in plan["cells"]:
        dataset = next(d for d in plan["datasets"] if d["dataset_key"] == cell["dataset_key"])
        recipe = PipelineRecipe.from_document(cell["recipe"])
        identity = {
            "object": dataset["test"]["logical_content_id"],
            "recipe_id": recipe.recipe_id,
            "protocol_id": protocol.protocol_id,
            "resources": plan["resources"],
            "implementation_id": stable_id("pipeline-implementation-v32", plan["closure"]),
        }
        if (
            recipe.recipe_id != cell["recipe_id"]
            or cell["execution_job_id"] != stable_id("pipeline-job-v32", identity)
            or cell["cell_id"] != stable_id("pipeline-cell-v32", identity)
            or cell["canonical_raw_bits"] != dataset["test"]["canonical_raw_bits"]
        ):
            raise PipelineComparisonError("P2 recipe/job/original denominator identity drift")
    methods = {
        d["dataset_key"]: {
            c["method_id"]: c["execution_job_id"]
            for c in plan["cells"]
            if c["dataset_key"] == d["dataset_key"]
        }
        for d in plan["datasets"]
    }
    expected_schedule = build_schedule(
        run_set_id=plan["run_set_id"],
        dataset_methods=methods,
        protocol_id=protocol.protocol_id,
        seed=schedule.seed,
        blocks=protocol.outer_repetitions,
        max_retries=0,
    )
    if schedule.to_document() != expected_schedule.to_document():
        raise PipelineComparisonError("P2 complete frozen method/outer schedule coverage drift")


def _encode(project_root: Path, original: LogicalObject, recipe: PipelineRecipe):
    bound = object_output_bound(project_root, original, recipe)
    artifact = encode_object(project_root, original, recipe)
    if len(artifact.stream) > bound:
        raise PipelineComparisonError("P2 artifact exceeds its real child metadata bound")
    return artifact


def _independent_decode(project_root: str, stream: bytes) -> dict[str, Any]:
    restored = decode_object(Path(project_root), stream)
    owned = all(a.flags.owndata for a in restored.values.values())
    owned = owned and (restored.timestamp is None or restored.timestamp.flags.owndata)
    owned = owned and (
        restored.validity is None or all(a.flags.owndata for a in restored.validity.values())
    )
    return {
        "restored": restored,
        "worker_pid": os.getpid(),
        "owned": owned,
        "original_available": False,
        "encoder_session_available": False,
        "only_arguments": ["public_decoder_program_root", "artifact_bytes"],
        "stream_sha256": hashlib.sha256(stream).hexdigest(),
        "actual_affinity": sorted(os.sched_getaffinity(0)),
    }


def _recovery(
    plan: dict[str, Any], original: LogicalObject, stream: bytes, deadline_ns: int | None = None
) -> dict[str, Any]:
    result = run_isolated(
        _independent_decode,
        plan["project_root"],
        stream,
        timeout_seconds=30,
        start_method="spawn",
        cpu_affinity=tuple(plan["resources"]["logical_cpus"]),
        memory_limit_bytes=plan["resources"]["memory_limit_bytes"],
        thread_monitor_interval_ns=plan["protocol"]["thread_monitor_interval_ns"],
        deadline_ns=deadline_ns,
    )
    if result.status is not RunStatus.PASS:
        raise PipelineComparisonError(f"fresh public decoder failed: {result.message}")
    value = result.value
    evidence = validate_restored_object(
        original, value["restored"], loss_contract={"kind": "LOSSLESS"}
    )
    if not evidence["passed"] or not value["owned"] or value["worker_pid"] == os.getpid():
        raise PipelineComparisonError("fresh decoder failed original-domain owned recovery")
    threads = thread_budget_evidence(result.thread_observation, thread_budget=1)
    if threads["observed_excess"]:
        raise PipelineComparisonError("fresh decoder exceeded thread budget")
    return {
        **{k: v for k, v in value.items() if k != "restored"},
        "correctness": evidence,
        "lifecycle": result.lifecycle_document(),
        "thread_budget": threads,
    }


def qualify_pipeline_comparison(run_path: Path) -> dict[str, Any]:
    run_path = run_path.resolve()
    with _pipeline_lock(run_path):
        return _qualify_pipeline_locked(run_path)


def _qualify_pipeline_locked(run_path: Path) -> dict[str, Any]:
    plan = _json(run_path / "plan.json")
    validate_pipeline_plan(plan, run_path)
    if (run_path / "qualification.json").exists():
        saved = _json(run_path / "qualification.json")
        _validate_auxiliary(plan, saved, "qualification")
        return saved
    intent_path = run_path / "qualification_intent.json"
    failure_path = run_path / "qualification_failure.json"
    artifacts = sorted((run_path / "qualification_artifacts").glob("*"))
    if intent_path.exists() or failure_path.exists() or artifacts:
        _durable_json(
            run_path / "qualification_interruption_audit.json",
            {
                "schema_version": "tscb.pipeline-qualification-interruption-audit.v1",
                "status": "BLOCKED_UNCOMMITTED_QUALIFICATION",
                "run_set_id": plan["run_set_id"],
                "frozen_plan_sha256": _sha(run_path / "plan.json"),
                "intent_sha256": _sha(intent_path) if intent_path.exists() else None,
                "failure_sha256": _sha(failure_path) if failure_path.exists() else None,
                "artifacts": [
                    {
                        "path": str(path.resolve()),
                        "sha256": _sha(path) if path.is_file() else None,
                        "physical_bytes": path.stat().st_size if path.is_file() else None,
                    }
                    for path in artifacts
                ],
                "automatic_retry_permitted": False,
                "scope": "AUXILIARY_QUALIFICATION_NOT_PERFORMANCE",
            },
        )
        raise PipelineComparisonError(
            "P2 uncommitted qualification; no automatic retry permitted; "
            "retain original artifacts and inspect qualification_interruption_audit.json"
        )
    _durable_json(
        intent_path,
        {
            "schema_version": "tscb.pipeline-qualification-intent.v1",
            "run_set_id": plan["run_set_id"],
            "frozen_plan_sha256": _sha(run_path / "plan.json"),
            "started_ns": time.perf_counter_ns(),
            "cell_ids": [cell["cell_id"] for cell in plan["cells"]],
            "automatic_retry_permitted": False,
            "scope": "AUXILIARY_QUALIFICATION_NOT_PERFORMANCE",
        },
    )
    cases = []
    for cell in plan["cells"]:
        path = run_path / "qualification_artifacts" / (cell["cell_id"].rsplit(":", 1)[-1] + ".p2")
        try:
            dataset = next(d for d in plan["datasets"] if d["dataset_key"] == cell["dataset_key"])
            original = load_pipeline_input(dataset["test"])
            artifact = _encode(
                Path(plan["project_root"]), original, PipelineRecipe.from_document(cell["recipe"])
            )
            _save_artifact(path, artifact.stream)
            recovery = _recovery(plan, original, artifact.stream)
        except Exception as error:
            _durable_json(
                failure_path,
                {
                    "schema_version": "tscb.pipeline-qualification-failure.v1",
                    "run_set_id": plan["run_set_id"],
                    "frozen_plan_sha256": _sha(run_path / "plan.json"),
                    "intent_sha256": _sha(intent_path),
                    "cell_id": cell["cell_id"],
                    "status": "FAILED",
                    "exception_type": type(error).__name__,
                    "message": str(error),
                    "artifact_path": str(path.resolve()) if path.exists() else None,
                    "artifact_sha256": _sha(path) if path.exists() else None,
                    "automatic_retry_permitted": False,
                    "scope": "AUXILIARY_QUALIFICATION_NOT_PERFORMANCE",
                },
            )
            raise
        cases.append(
            {
                "cell_id": cell["cell_id"],
                "status": "PASS",
                "recovery": recovery,
                "artifact_path": str(path.resolve()),
                "artifact_sha256": _sha(path),
                "ledger": artifact.ledger.to_document(),
                "recipe_id": artifact.recipe_id,
            }
        )
    document = evidence_document(
        {
            "schema_version": "tscb.pipeline-qualification.v3.2",
            "run_set_id": plan["run_set_id"],
            "cases": cases,
            "status": "PASS",
        }
    )
    _durable_json(run_path / "qualification.json", document)
    return document


def _sampler(original: LogicalObject, enabled: bool) -> ResourceSampler:
    return ResourceSampler(
        requested_scope="PROCESS",
        memory_accounting_scope="PROCESS_RSS",
        counter_method="NOT_COLLECTED",
        energy_method="NOT_COLLECTED",
        allocated_logical_cpus=1,
        canonical_bytes=(original.canonical_raw_bits + 7) // 8,
        enabled=enabled,
    )


def _measure(
    project_root: str,
    input_document: dict[str, Any],
    recipe_document: dict[str, Any],
    protocol_document: dict[str, Any],
    collector: bool = True,
) -> dict[str, Any]:
    original = load_pipeline_input(input_document)
    recipe = PipelineRecipe.from_document(recipe_document)
    protocol = MeasurementProtocol.from_document(protocol_document)
    root = Path(project_root)
    before = original.underlying_bytes_sha256
    started = time.perf_counter_ns()
    warmups = 0
    while (
        warmups < protocol.warmup_min_count
        or time.perf_counter_ns() - started < protocol.warmup_min_ns
    ):
        artifact = _encode(root, original, recipe)
        if not validate_restored_object(
            original, decode_object(root, artifact.stream), loss_contract={"kind": "LOSSLESS"}
        )["passed"]:
            raise PipelineComparisonError("P2 worker-local warmup recovery failed")
        warmups += 1
        if warmups >= protocol.max_inner_iterations:
            raise PipelineComparisonError("P2 warmup budget exhausted")
    warmup_ns = time.perf_counter_ns() - started
    times, counts, resources = {}, {}, {}
    stream = None
    for direction, minimum in (
        ("encode", protocol.encode_min_ns),
        ("decode", protocol.decode_min_ns),
    ):
        sampler = _sampler(original, collector)
        sampler.start(time.perf_counter_ns())
        elapsed = count = 0
        while elapsed < minimum:
            begin = time.perf_counter_ns()
            if direction == "encode":
                artifact = _encode(root, original, recipe)
                result = artifact.stream
            else:
                result = decode_object(root, stream)
            elapsed += time.perf_counter_ns() - begin
            if direction == "encode":
                if stream is not None and result != stream:
                    raise PipelineComparisonError("P2 deterministic stream changed between objects")
                stream = result
            else:
                if result.content_id != original.content_id:
                    raise PipelineComparisonError("P2 measured original-domain recovery failed")
            count += 1
            del result
            if (
                count >= protocol.max_inner_iterations
                or time.perf_counter_ns() - started >= protocol.max_trial_wall_ns
            ):
                raise PipelineComparisonError("P2 batch minimum duration budget exhausted")
        resources[direction] = sampler.stop(time.perf_counter_ns()).to_document()
        times[direction] = elapsed
        counts[direction] = count
    if before != original.underlying_bytes_sha256:
        raise PipelineComparisonError("P2 original buffers changed")
    return {
        "encode_ns": times["encode"],
        "decode_ns": times["decode"],
        "inner_iterations": min(counts.values()),
        "direction_counts": counts,
        "warmup_count": warmups,
        "warmup_ns": warmup_ns,
        "warmup_worker_pid": os.getpid(),
        "resources": resources,
        "stream": stream,
        "ledger": artifact.ledger.to_document(),
        "input_immutable": True,
        "collector_enabled": collector,
        "actual_affinity": sorted(os.sched_getaffinity(0)),
    }


@dataclass(frozen=True)
class PipelinePilotProbe:
    project_root: str
    input_document: dict[str, Any]
    recipe_document: dict[str, Any]
    protocol_document: dict[str, Any]
    collector: bool
    logical_cpus: tuple[int, ...]

    def __call__(self):
        os.sched_setaffinity(0, set(self.logical_cpus))
        result = _measure(
            self.project_root,
            self.input_document,
            self.recipe_document,
            self.protocol_document,
            self.collector,
        )
        # Pilot's public format has a common count. Normalize one object;
        # formal batches preserve their separate actual direction counts.
        return {
            "encode_ns": result["encode_ns"] // result["direction_counts"]["encode"],
            "decode_ns": result["decode_ns"] // result["direction_counts"]["decode"],
            "inner_iterations": 1,
        }


def pipeline_harness_probe():
    return None


def pilot_pipeline_comparison(run_path: Path) -> dict[str, Any]:
    plan = _json(run_path / "plan.json")
    validate_pipeline_plan(plan, run_path)
    _validate_auxiliary(plan, _json(run_path / "qualification.json"), "qualification")
    if (run_path / "pilot.json").exists():
        saved = _json(run_path / "pilot.json")
        _validate_auxiliary(plan, saved, "pilot")
        return saved
    protocol = MeasurementProtocol.from_document(plan["protocol"])
    cases = []
    with _lease(plan):
        for cell in plan["cells"]:
            dataset = next(d for d in plan["datasets"] if d["dataset_key"] == cell["dataset_key"])
            common = (
                plan["project_root"],
                dataset["development"],
                cell["recipe"],
                plan["protocol"],
            )
            off = PipelinePilotProbe(*common, False, tuple(plan["resources"]["logical_cpus"]))
            on = PipelinePilotProbe(*common, True, tuple(plan["resources"]["logical_cpus"]))
            evidence = run_pilot(
                protocol,
                off,
                development_corpus_id=dataset["development"]["logical_content_id"],
                test_corpus_id=dataset["test"]["logical_content_id"],
                harness_probe=pipeline_harness_probe,
                collector_enabled_probe=on,
            )
            cases.append({"cell_id": cell["cell_id"], "evidence": evidence})
    document = {
        "schema_version": "tscb.pipeline-pilots.v3.2",
        "run_set_id": plan["run_set_id"],
        "cases": cases,
    }
    _write(run_path / "pilot.json", document)
    _validate_auxiliary(plan, document, "pilot")
    return document


def _validate_auxiliary(plan: dict[str, Any], document: dict[str, Any], kind: str):
    version = "tscb.pipeline-pilots.v3.2" if kind == "pilot" else "tscb.pipeline-qualification.v3.2"
    if document.get("schema_version") != version:
        raise PipelineComparisonError("P2 auxiliary schema version invalid")
    if document["run_set_id"] != plan["run_set_id"]:
        raise PipelineComparisonError("P2 auxiliary evidence belongs to another plan")
    cases = {case["cell_id"]: case for case in document["cases"]}
    if len(cases) != len(document["cases"]) or set(cases) != {c["cell_id"] for c in plan["cells"]}:
        raise PipelineComparisonError("P2 auxiliary cell coverage is incomplete")
    for cell in plan["cells"]:
        case = cases[cell["cell_id"]]
        if kind == "pilot":
            evidence = case["evidence"]
            dataset = next(d for d in plan["datasets"] if d["dataset_key"] == cell["dataset_key"])
            if (
                evidence["development_corpus_id"] != dataset["development"]["logical_content_id"]
                or evidence["test_corpus_id"] != dataset["test"]["logical_content_id"]
                or not validate_pilot_evidence(
                    MeasurementProtocol.from_document(plan["protocol"]), evidence
                )["eligible"]
            ):
                raise PipelineComparisonError("P2 development pilot is ineligible")
        elif (
            case["status"] != "PASS"
            or _sha(Path(case["artifact_path"])) != case["artifact_sha256"]
            or case["recipe_id"] != cell["recipe_id"]
            or not case["recovery"]["correctness"]["passed"]
        ):
            raise PipelineComparisonError("P2 qualification failed or artifact drifted")
        else:
            header, _ = _parse(Path(case["artifact_path"]).read_bytes())
            dataset = next(d for d in plan["datasets"] if d["dataset_key"] == cell["dataset_key"])
            recovery = case["recovery"]
            if (
                header["recipe"] != cell["recipe"]
                or header["logical_content_id"] != dataset["test"]["logical_content_id"]
                or recovery["stream_sha256"] != case["artifact_sha256"]
                or recovery["original_available"]
                or recovery["encoder_session_available"]
                or not recovery["owned"]
                or recovery["worker_pid"] == recovery["lifecycle"]["parent_pid"]
                or not recovery["lifecycle"]["worker_exit_confirmed"]
                or recovery["lifecycle"]["exit_code"] != 0
            ):
                raise PipelineComparisonError("P2 qualification public decoder identity drift")


def _lease(plan: dict[str, Any]):
    return ResourceLease(
        run_set_id=plan["run_set_id"],
        logical_cpus=plan["resources"]["logical_cpus"],
        threads=1,
        memory_limit_bytes=plan["resources"]["memory_limit_bytes"],
        require_physical_core_evidence=True,
    )


def _trials(path: Path):
    if not path.exists():
        return []
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise PipelineComparisonError("P2 terminal log truncated; preserve interrupted evidence")
    try:
        trials = [json.loads(line) for line in raw.splitlines()]
    except (ValueError, UnicodeError) as error:
        raise PipelineComparisonError(
            "P2 invalid terminal log; preserve interrupted evidence"
        ) from error
    if any(not isinstance(trial, dict) for trial in trials):
        raise PipelineComparisonError("P2 terminal records must be JSON objects")
    return trials


def _append(path: Path, document: dict[str, Any]):
    created = not path.exists()
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(evidence_document(document)) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    if created:
        _sync_directory(path.parent)


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(canonical_json_bytes(evidence_document(document)) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    _sync_directory(path.parent)


def _artifact_path(run_path: Path, trial_id: str) -> Path:
    return run_path / "artifacts" / (trial_id.rsplit(":", 1)[-1] + ".p2")


def _save_artifact(path: Path, stream: bytes) -> None:
    created_directory = not path.parent.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if created_directory:
        _sync_directory(path.parent.parent)
    # A prior uncommitted artifact is evidence of an interrupted attempt. Never
    # silently reuse or overwrite it as a new performance observation.
    with path.open("xb") as handle:
        handle.write(stream)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_directory(path.parent)


def _attempt_id(plan: dict[str, Any], plan_sha: str, trial_id: str) -> str:
    return stable_id(
        "pipeline-attempt-v32",
        {
            "run_set_id": plan["run_set_id"],
            "schedule_id": plan["schedule_id"],
            "frozen_plan_sha256": plan_sha,
            "trial_id": trial_id,
            "attempt_index": 0,
        },
    )


def _attempt_state(run_path: Path, plan: dict[str, Any], trials: list[dict]) -> dict[str, Any]:
    path = run_path / ATTEMPT_POLICY["event_log"]
    plan_sha = _sha(run_path / "plan.json")
    protocol = MeasurementProtocol.from_document(plan["protocol"])
    slots = {s["trial_id"]: s for s in plan["schedule"]["trials"]}
    cells = {c["execution_job_id"]: c for c in plan["cells"]}
    if any(
        not isinstance(trial, dict)
        or not isinstance(trial.get("trial_id"), str)
        or type(trial.get("started_ns")) is not int
        or type(trial.get("finished_ns")) is not int
        or trial["finished_ns"] < trial["started_ns"]
        or not isinstance(trial.get("status"), str)
        for trial in trials
    ):
        raise PipelineComparisonError("P2 terminal attempt identity/timestamp/status invalid")
    records = {t["trial_id"]: t for t in trials}
    if len(records) != len(trials):
        raise PipelineComparisonError("P2 duplicate terminal attempt records")
    raw = b"" if not path.exists() else path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise PipelineComparisonError(
            "P2 attempt event log truncated; no automatic retry permitted"
        )
    try:
        events = [json.loads(line) for line in raw.splitlines()]
    except (ValueError, UnicodeError) as error:
        raise PipelineComparisonError(
            "P2 invalid attempt event log; preserve interrupted evidence"
        ) from error
    previous = None
    starts: dict[str, dict] = {}
    committed: set[str] = set()
    used_ns = 0
    active = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise PipelineComparisonError("P2 attempt event must be an object")
        common_fields = {
            "schema_version",
            "event_index",
            "previous_event_sha256",
            "event_sha256",
            "frozen_plan_sha256",
            "run_set_id",
            "schedule_id",
            "protocol_id",
            "trial_id",
            "attempt_index",
            "attempt_id",
            "execution_job_id",
            "cell_id",
            "event_type",
        }
        type_fields = {
            "STARTED": {
                "started_ns",
                "reserved_wall_ns",
                "budget_prior_ns",
                "budget_reserved_total_ns",
            },
            "TERMINAL_COMMITTED": {
                "started_event_sha256",
                "terminal_trial_sha256",
                "terminal_status",
                "actual_wall_ns",
                "budget_actual_total_ns",
            },
        }
        if set(event) != common_fields | type_fields.get(event.get("event_type"), set()):
            raise PipelineComparisonError("P2 attempt event fields/version invalid")
        body = {k: v for k, v in event.items() if k != "event_sha256"}
        trial_id = event.get("trial_id")
        slot = slots.get(trial_id)
        digest = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        if (
            slot is None
            or event.get("schema_version") != "tscb.pipeline-attempt-event.v1"
            or type(event.get("event_index")) is not int
            or event["event_index"] != index
            or event.get("previous_event_sha256") != previous
            or event.get("event_sha256") != digest
            or event.get("frozen_plan_sha256") != plan_sha
            or event.get("run_set_id") != plan["run_set_id"]
            or event.get("schedule_id") != plan["schedule_id"]
            or event.get("protocol_id") != plan["protocol"]["protocol_id"]
            or type(event.get("attempt_index")) is not int
            or event["attempt_index"] != 0
            or event.get("attempt_id") != _attempt_id(plan, plan_sha, trial_id)
            or event.get("execution_job_id") != slot["execution_job_id"]
            or event.get("cell_id") != cells[slot["execution_job_id"]]["cell_id"]
        ):
            raise PipelineComparisonError("P2 attempt event hash/plan/slot identity drift")
        if event.get("event_type") == "STARTED":
            reserve = min(protocol.max_trial_wall_ns, protocol.max_total_wall_ns - used_ns)
            if (
                active is not None
                or trial_id in starts
                or len(starts) >= len(plan["schedule"]["trials"])
                or trial_id != plan["schedule"]["trials"][len(starts)]["trial_id"]
                or type(event.get("reserved_wall_ns")) is not int
                or event["reserved_wall_ns"] != reserve
                or reserve <= 0
                or event.get("budget_prior_ns") != used_ns
                or type(event.get("budget_prior_ns")) is not int
                or event.get("budget_reserved_total_ns") != used_ns + reserve
                or type(event.get("budget_reserved_total_ns")) is not int
                or type(event.get("started_ns")) is not int
                or event["started_ns"] <= 0
            ):
                raise PipelineComparisonError(
                    "P2 repeated/overlapping attempt or reservation drift"
                )
            starts[trial_id] = event
            active = trial_id
            used_ns += reserve
        elif event.get("event_type") == "TERMINAL_COMMITTED":
            trial = records.get(trial_id)
            start = starts.get(trial_id)
            actual_ns = None if trial is None else trial["finished_ns"] - trial["started_ns"]
            if (
                active != trial_id
                or start is None
                or trial is None
                or trial_id in committed
                or event.get("started_event_sha256") != start["event_sha256"]
                or event.get("terminal_trial_sha256")
                != hashlib.sha256(canonical_json_bytes(trial)).hexdigest()
                or event.get("terminal_status") != trial["status"]
                or actual_ns < 0
                or type(event.get("actual_wall_ns")) is not int
                or event.get("actual_wall_ns") != actual_ns
                or type(event.get("budget_actual_total_ns")) is not int
                or event.get("budget_actual_total_ns") != start["budget_prior_ns"] + actual_ns
            ):
                raise PipelineComparisonError("P2 terminal event/raw/budget drift")
            committed.add(trial_id)
            active = None
            used_ns = start["budget_prior_ns"] + actual_ns
        else:
            raise PipelineComparisonError("P2 unknown attempt event type")
        previous = digest
    for trial_id, trial in records.items():
        start = starts.get(trial_id)
        if start is None or (
            trial.get("attempt_id") != start["attempt_id"]
            or trial.get("started_event_sha256") != start["event_sha256"]
            or trial.get("reserved_wall_ns") != start["reserved_wall_ns"]
            or trial.get("started_ns") != start["started_ns"]
        ):
            raise PipelineComparisonError("P2 raw terminal lacks its durable started attempt")
    unresolved = sorted(set(starts) - set(records))
    orphans = [
        s["trial_id"]
        for s in plan["schedule"]["trials"]
        if s["trial_id"] not in starts and _artifact_path(run_path, s["trial_id"]).exists()
    ]
    return {
        "events": events,
        "starts": starts,
        "committed": committed,
        "unresolved": unresolved,
        "orphan_artifacts": orphans,
        "uncommitted_terminals": sorted(set(records) - committed),
        "budget_used_ns": used_ns,
        "budget_accounting_status": (
            "UNKNOWN_UNBOUND_ARTIFACT_COST_RUN_BLOCKED"
            if orphans
            else "DURABLE_ATTEMPT_RESERVATIONS_AND_COMMITTED_ACTUAL_WALL"
        ),
        "frozen_plan_sha256": plan_sha,
        "event_log_sha256": None if not path.exists() else _sha(path),
        "raw_trials_sha256": (
            None if not (run_path / "trials.jsonl").exists() else _sha(run_path / "trials.jsonl")
        ),
    }


def _attempt_event(
    run_path: Path, plan: dict, state: dict, slot: dict, kind: str, **fields
) -> dict:
    trial_id = slot["trial_id"]
    cell = next(c for c in plan["cells"] if c["execution_job_id"] == slot["execution_job_id"])
    events = state["events"]
    event = {
        "schema_version": "tscb.pipeline-attempt-event.v1",
        "event_index": len(events),
        "previous_event_sha256": None if not events else events[-1]["event_sha256"],
        "frozen_plan_sha256": state["frozen_plan_sha256"],
        "run_set_id": plan["run_set_id"],
        "protocol_id": plan["protocol"]["protocol_id"],
        "schedule_id": plan["schedule_id"],
        "trial_id": trial_id,
        "execution_job_id": slot["execution_job_id"],
        "cell_id": cell["cell_id"],
        "attempt_index": 0,
        "attempt_id": _attempt_id(plan, state["frozen_plan_sha256"], trial_id),
        "event_type": kind,
        **fields,
    }
    event["event_sha256"] = hashlib.sha256(canonical_json_bytes(event)).hexdigest()
    _append(run_path / ATTEMPT_POLICY["event_log"], event)
    return event


def _commit_attempt(run_path: Path, plan: dict, state: dict, trial: dict) -> None:
    slot = next(s for s in plan["schedule"]["trials"] if s["trial_id"] == trial["trial_id"])
    start = state["starts"][trial["trial_id"]]
    actual = trial["finished_ns"] - trial["started_ns"]
    _attempt_event(
        run_path,
        plan,
        state,
        slot,
        "TERMINAL_COMMITTED",
        started_event_sha256=start["event_sha256"],
        terminal_trial_sha256=hashlib.sha256(canonical_json_bytes(trial)).hexdigest(),
        terminal_status=trial["status"],
        actual_wall_ns=actual,
        budget_actual_total_ns=start["budget_prior_ns"] + actual,
    )


def _block_interrupted_attempts(run_path: Path, plan: dict, state: dict) -> None:
    ids = state["unresolved"] + state["orphan_artifacts"]
    if not ids:
        return
    observations = []
    for trial_id in ids:
        start = state["starts"].get(trial_id)
        artifact = _artifact_path(run_path, trial_id)
        observations.append(
            {
                "trial_id": trial_id,
                "attempt_id": None if start is None else start["attempt_id"],
                "reserved_wall_ns": None if start is None else start["reserved_wall_ns"],
                "artifact": None
                if not artifact.exists()
                else {
                    "path": str(artifact.resolve()),
                    "sha256": _sha(artifact),
                    "physical_bytes": artifact.stat().st_size,
                },
                "reason": "STARTED_WITHOUT_DURABLE_TERMINAL"
                if start
                else "UNBOUND_EXISTING_ARTIFACT",
            }
        )
    _durable_json(
        run_path / "interruption_audit.json",
        {
            "schema_version": "tscb.pipeline-interruption-audit.v1",
            "status": "BLOCKED_INTERRUPTED_ATTEMPT",
            "run_set_id": plan["run_set_id"],
            **{
                k: state[k]
                for k in (
                    "frozen_plan_sha256",
                    "event_log_sha256",
                    "raw_trials_sha256",
                    "budget_used_ns",
                    "budget_accounting_status",
                )
            },
            "unresolved_attempts": observations,
            "automatic_retry_permitted": False,
            "performance_execution_required": False,
        },
    )
    raise PipelineComparisonError(
        "P2 interrupted/unbound attempt; no automatic retry permitted; "
        "retain original artifacts and inspect interruption_audit.json"
    )


@contextmanager
def _pipeline_lock(run_path: Path):
    descriptor = os.open(run_path / ".pipeline.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PipelineComparisonError("P2 execution/resume lock is already held") from error
        yield
    finally:
        os.close(descriptor)


def execute_pipeline_comparison(run_path: Path) -> dict[str, Any]:
    run_path = run_path.resolve()
    with _pipeline_lock(run_path):
        return _execute_pipeline_locked(run_path)


def _execute_pipeline_locked(run_path: Path) -> dict[str, Any]:
    plan = _json(run_path / "plan.json")
    validate_pipeline_plan(plan, run_path)
    _validate_auxiliary(plan, _json(run_path / "qualification.json"), "qualification")
    _validate_auxiliary(plan, _json(run_path / "pilot.json"), "pilot")
    existing = _trials(run_path / "trials.jsonl")
    state = _attempt_state(run_path, plan, existing)
    _block_interrupted_attempts(run_path, plan, state)
    _audit_trials(run_path, plan, existing)
    # The terminal JSONL append may be durable even when the following commit
    # event was interrupted. Finish its journal commit without a new worker.
    for trial_id in state["uncommitted_terminals"]:
        _commit_attempt(
            run_path, plan, state, next(t for t in existing if t["trial_id"] == trial_id)
        )
        state = _attempt_state(run_path, plan, existing)
    completed = {t["trial_id"] for t in existing}
    total_elapsed = state["budget_used_ns"]
    protocol = MeasurementProtocol.from_document(plan["protocol"])
    with _lease(plan) as lease:
        for slot in plan["schedule"]["trials"]:
            if slot["trial_id"] in completed:
                continue
            if total_elapsed >= protocol.max_total_wall_ns:
                break
            cell = next(
                c for c in plan["cells"] if c["execution_job_id"] == slot["execution_job_id"]
            )
            dataset = next(d for d in plan["datasets"] if d["dataset_key"] == cell["dataset_key"])
            before = lease.to_document()
            started = time.perf_counter_ns()
            reservation = min(
                protocol.max_trial_wall_ns, protocol.max_total_wall_ns - total_elapsed
            )
            start_event = _attempt_event(
                run_path,
                plan,
                state,
                slot,
                "STARTED",
                started_ns=started,
                reserved_wall_ns=reservation,
                budget_prior_ns=total_elapsed,
                budget_reserved_total_ns=total_elapsed + reservation,
            )
            deadline = started + reservation
            result = run_isolated(
                _measure,
                plan["project_root"],
                dataset["test"],
                cell["recipe"],
                plan["protocol"],
                timeout_seconds=reservation / 1e9,
                memory_limit_bytes=plan["resources"]["memory_limit_bytes"],
                cpu_affinity=tuple(plan["resources"]["logical_cpus"]),
                start_method="spawn",
                thread_monitor_interval_ns=protocol.thread_monitor_interval_ns,
                deadline_ns=deadline,
            )
            trial = {
                "schema_version": "tscb.pipeline-trial.v3.2",
                **slot,
                "run_set_id": plan["run_set_id"],
                "protocol_id": protocol.protocol_id,
                "schedule_id": plan["schedule_id"],
                "cell_id": cell["cell_id"],
                "status": result.status.value,
                "started_ns": started,
                "attempt_id": start_event["attempt_id"],
                "started_event_sha256": start_event["event_sha256"],
                "reserved_wall_ns": reservation,
                "measurement_lifecycle": result.lifecycle_document(),
                "thread_budget": thread_budget_evidence(result.thread_observation, thread_budget=1),
                "exception": result.message,
                "resource_lease": before,
                "memory_limit_method": result.limit_method,
            }
            if result.status is RunStatus.PASS:
                observed = result.value
                stream = observed.pop("stream")
                artifact_path = _artifact_path(run_path, slot["trial_id"])
                _save_artifact(artifact_path, stream)
                trial.update(
                    {
                        "observation": observed,
                        "artifact_path": str(artifact_path.resolve()),
                        "artifact_sha256": _sha(artifact_path),
                    }
                )
                try:
                    trial["independent_recovery"] = _recovery(
                        plan,
                        load_pipeline_input(dataset["test"]),
                        stream,
                        deadline,
                    )
                except PipelineComparisonError as error:
                    trial["status"] = "CORRECTNESS_FAILED"
                    trial["exception"] = str(error)
            trial["finished_ns"] = time.perf_counter_ns()
            trial["environment_gate"] = environment_gate(protocol, before, lease.to_document())
            # Bind the terminal event to the exact canonical evidence bytes
            # appended below, including decimal-string float observations.
            trial = evidence_document(trial)
            _append(run_path / "trials.jsonl", trial)
            existing.append(trial)
            state = _attempt_state(run_path, plan, existing)
            _commit_attempt(run_path, plan, state, trial)
            state = _attempt_state(run_path, plan, existing)
            total_elapsed = state["budget_used_ns"]
    return report_pipeline_comparison(run_path)


def _audit_trials(run_path: Path, plan: dict[str, Any], trials: list[dict[str, Any]]):
    slots = {t["trial_id"]: t for t in plan["schedule"]["trials"]}
    if len({t["trial_id"] for t in trials}) != len(trials):
        raise PipelineComparisonError("P2 duplicate trial attempts")
    ordered = [slots[t["trial_id"]]["sequence_index"] for t in trials if t["trial_id"] in slots]
    if ordered != sorted(ordered):
        raise PipelineComparisonError("P2 actual schedule order drift")
    issues = {}
    protocol = MeasurementProtocol.from_document(plan["protocol"])
    for trial in trials:
        slot = slots.get(trial["trial_id"])
        if slot is None or any(trial.get(k) != v for k, v in slot.items()):
            raise PipelineComparisonError("P2 unplanned/mismatched trial identity")
        cell = next(c for c in plan["cells"] if c["execution_job_id"] == slot["execution_job_id"])
        if (
            trial["cell_id"] != cell["cell_id"]
            or trial["run_set_id"] != plan["run_set_id"]
            or trial["protocol_id"] != protocol.protocol_id
            or trial["schedule_id"] != plan["schedule_id"]
        ):
            raise PipelineComparisonError("P2 trial belongs to another frozen plan")
        reasons = []
        if trial["finished_ns"] - trial["started_ns"] > trial.get(
            "reserved_wall_ns", protocol.max_trial_wall_ns
        ):
            reasons.append("RESERVED_TRIAL_BUDGET_EXCEEDED")
        if "artifact_path" in trial:
            artifact = Path(trial["artifact_path"])
            if (
                not artifact.is_relative_to(run_path.resolve())
                or _sha(artifact) != trial["artifact_sha256"]
            ):
                raise PipelineComparisonError("P2 retained attempt artifact drift")
        if trial["status"] != "PASS":
            reasons.append("EXECUTION_FAILED")
        else:
            artifact = Path(trial["artifact_path"])
            if (
                not artifact.is_relative_to(run_path.resolve())
                or _sha(artifact) != trial["artifact_sha256"]
            ):
                raise PipelineComparisonError("P2 measured artifact drift")
            observed = trial["observation"]
            stream = artifact.read_bytes()
            header, payload = _parse(stream)
            restored = decode_object(Path(plan["project_root"]), stream)
            dataset = next(d for d in plan["datasets"] if d["dataset_key"] == cell["dataset_key"])
            if (
                validate_restored_object(
                    load_pipeline_input(dataset["test"]),
                    restored,
                    loss_contract={"kind": "LOSSLESS"},
                )["passed"]
                is not True
            ):
                raise PipelineComparisonError("P2 artifact original-domain recovery drift")
            if (
                observed["ledger"]
                != PipelineLedger(
                    cell["canonical_raw_bits"],
                    len(payload) * 8,
                    (len(stream) - len(payload)) * 8,
                    len(stream) * 8,
                    len(stream) * 8,
                ).to_document()
                or header["recipe"] != cell["recipe"]
                or header["recipe_id"] != cell["recipe_id"]
                or header["logical_content_id"] != dataset["test"]["logical_content_id"]
            ):
                raise PipelineComparisonError("P2 raw denominator/physical accounting drift")
            lifecycle = trial["measurement_lifecycle"]
            if (
                not lifecycle["worker_exit_confirmed"]
                or lifecycle["exit_code"] != 0
                or lifecycle["start_method"] != "spawn"
                or observed["warmup_worker_pid"] != lifecycle["worker_pid"]
                or observed["warmup_count"] < protocol.warmup_min_count
                or observed["warmup_ns"] < protocol.warmup_min_ns
                or observed["encode_ns"] < protocol.encode_min_ns
                or observed["decode_ns"] < protocol.decode_min_ns
                or not observed["input_immutable"]
                or not observed["collector_enabled"]
                or observed["actual_affinity"] != plan["resources"]["logical_cpus"]
                or trial["memory_limit_method"] != "RLIMIT_AS_WITH_EXISTING_VM_HEADROOM"
                or any(
                    type(n) is not int or not 0 < n <= protocol.max_inner_iterations
                    for n in observed["direction_counts"].values()
                )
                or not trial["started_ns"]
                <= lifecycle["parent_started_ns"]
                <= lifecycle["worker_started_ns"]
                <= lifecycle["parent_finished_ns"]
                <= trial["finished_ns"]
            ):
                reasons.append("TIMING_WARMUP_OR_PROCESS_BOUNDARY_INVALID")
            recovery = trial["independent_recovery"]
            if (
                recovery["worker_pid"] == lifecycle["worker_pid"]
                or not recovery["owned"]
                or recovery["original_available"]
                or recovery["encoder_session_available"]
                or recovery["stream_sha256"] != trial["artifact_sha256"]
                or not recovery["correctness"]["passed"]
                or recovery["actual_affinity"] != plan["resources"]["logical_cpus"]
                or recovery["lifecycle"]["start_method"] != "spawn"
                or not recovery["lifecycle"]["worker_exit_confirmed"]
                or recovery["lifecycle"]["exit_code"] != 0
                or recovery["worker_pid"] == recovery["lifecycle"]["parent_pid"]
                or recovery["lifecycle"]["parent_started_ns"] < lifecycle["parent_finished_ns"]
            ):
                reasons.append("INDEPENDENT_PUBLIC_DECODER_INVALID")
            for direction in ("encode", "decode"):
                resource = observed["resources"][direction]
                if (
                    resource["scope_availability"] != "AVAILABLE"
                    or resource["swap_observed"] is True
                    or resource["peak_process_rss_bytes"] > plan["resources"]["memory_limit_bytes"]
                ):
                    reasons.append("RESOURCE_GATE_FAILED")
        expected_threads = thread_budget_evidence(
            trial["measurement_lifecycle"]["thread_observation"], thread_budget=1
        )
        gate = trial["environment_gate"]
        lease = trial["resource_lease"]
        expected_gate = environment_gate(
            protocol, {**lease, "boundary": gate["before"]}, {**lease, "boundary": gate["after"]}
        )
        if trial["thread_budget"] != expected_threads or gate != expected_gate:
            raise PipelineComparisonError(
                "P2 saved resource eligibility differs from raw observations"
            )
        if (
            expected_threads["observed_excess"]
            or not gate["eligible"]
            or lease["logical_cpus"] != plan["resources"]["logical_cpus"]
            or lease["threads"] != 1
            or lease["status"] != "HELD"
            or lease["run_set_id"] != plan["run_set_id"]
            or trial["finished_ns"] - trial["started_ns"] > protocol.max_trial_wall_ns
        ):
            reasons.append("THREAD_OR_ENVIRONMENT_GATE_FAILED")
        issues[trial["trial_id"]] = sorted(set(reasons))
    return issues


def report_pipeline_comparison(run_path: Path) -> dict[str, Any]:
    run_path = run_path.resolve()
    plan = _json(run_path / "plan.json")
    validate_pipeline_plan(plan, run_path)
    _validate_auxiliary(plan, _json(run_path / "qualification.json"), "qualification")
    _validate_auxiliary(plan, _json(run_path / "pilot.json"), "pilot")
    trials_path = run_path / "trials.jsonl"
    trials = _trials(trials_path)
    attempt_state = _attempt_state(run_path, plan, trials)
    issues = _audit_trials(run_path, plan, trials)
    for trial_id in attempt_state["uncommitted_terminals"]:
        issues[trial_id].append("ATTEMPT_TERMINAL_NOT_DURABLY_COMMITTED")
    policy = AnalysisPolicy.from_document(plan["analysis_policy"])
    rows, effects = [], []
    family = len(plan["datasets"]) * 2
    for dataset in plan["datasets"]:
        paired = {key: {direction: {} for direction in ("encode", "decode")} for key in METHODS}
        for cell in [c for c in plan["cells"] if c["dataset_key"] == dataset["dataset_key"]]:
            selected = [
                t for t in trials if t["cell_id"] == cell["cell_id"] and not issues[t["trial_id"]]
            ]
            direction_summaries = {}
            for direction in ("encode", "decode"):
                values = [
                    t["observation"][direction + "_ns"]
                    / t["observation"]["direction_counts"][direction]
                    for t in selected
                ]
                direction_summaries[direction] = None if not values else _description(values)
                paired[cell["method_id"]][direction] = {
                    str(t["block_index"]): value for t, value in zip(selected, values, strict=True)
                }
            rows.append(
                {
                    "dataset_key": dataset["dataset_key"],
                    "method_id": cell["method_id"],
                    "recipe_id": cell["recipe_id"],
                    "canonical_raw_bits": cell["canonical_raw_bits"],
                    "expected_outer_count": plan["protocol"]["outer_repetitions"],
                    "eligible_outer_count": len(selected),
                    "timing_ns_per_object": direction_summaries,
                    "complete_artifact_bits": [
                        t["observation"]["ledger"]["final_bits"] for t in selected
                    ],
                    "pipeline_accounting": [t["observation"]["ledger"] for t in selected],
                    "logical_schema": dataset["test"]["schema"],
                }
            )
        for direction in ("encode", "decode"):
            effects.append(
                {
                    "dataset_key": dataset["dataset_key"],
                    "direction": direction,
                    "members": list(METHODS),
                    "effect": _effect(
                        paired[METHODS[0]][direction],
                        paired[METHODS[1]][direction],
                        policy,
                        family,
                        dataset["dataset_key"] + direction,
                    ),
                }
            )
    complete = (
        len(trials) == len(plan["schedule"]["trials"])
        and not attempt_state["unresolved"]
        and not attempt_state["orphan_artifacts"]
        and not attempt_state["uncommitted_terminals"]
    )
    failed = sum(bool(v) for v in issues.values())
    document = {
        "schema_version": "tscb.pipeline-report.v3.2",
        "run_set_id": plan["run_set_id"],
        "decision_id": plan["decision_id"],
        "decision": plan["decision"],
        "auxiliary_artifacts": {
            "experiment_decision": "experiment_decision.json",
            "uncompressed_reference": ["uncompressed_reference.json", "uncompressed_reference.md"],
            "buffer_cost_audit": ["buffer_cost_audit.json", "buffer_cost_audit.md"],
        },
        "status": "COMPLETE" if complete and not failed else "INCONCLUSIVE",
        "expected_trials": len(plan["schedule"]["trials"]),
        "recorded_trials": len(trials),
        "eligible_trials": len(trials) - failed,
        "fixed_cell_denominator": len(plan["cells"]),
        "attempt_audit": {
            "event_log": ATTEMPT_POLICY["event_log"],
            "event_log_sha256": attempt_state["event_log_sha256"],
            "frozen_plan_sha256": attempt_state["frozen_plan_sha256"],
            "event_count": len(attempt_state["events"]),
            "committed_attempt_count": len(attempt_state["committed"]),
            "unresolved_attempts": attempt_state["unresolved"],
            "orphan_artifacts": attempt_state["orphan_artifacts"],
            "uncommitted_terminals": attempt_state["uncommitted_terminals"],
            "budget_used_ns": attempt_state["budget_used_ns"],
            "budget_accounting_status": attempt_state["budget_accounting_status"],
            "automatic_retry_permitted": False,
        },
        "missing_policy": policy.missing_policy,
        "rows": rows,
        "paired_effects": effects,
        "trial_issues": issues,
        "raw_trials_sha256": None if not trials_path.exists() else _sha(trials_path),
        "artifact_hashes": {
            t["trial_id"]: t["artifact_sha256"] for t in trials if "artifact_sha256" in t
        },
        "scope": plan["scope"],
        "timing_boundary": plan["boundary"],
        "inference_scope": "RUN_NOISE_ON_FROZEN_CORPUS_AND_HOST",
        "aggregation": "NO_CROSS_TASK_OR_UNRELATED_CODEC_RANKING",
    }
    _write(run_path / "report.json", document, immutable=False)
    markdown = [
        "# V3.2 P2 对象管线",
        "",
        f"状态：{document['status']}。"
        f"正式试验 {document['eligible_trials']}/{document['expected_trials']}；"
        f"冻结分母 {document['fixed_cell_denominator']} 个任务/配方单元。",
        "",
        "PIPELINE 时间包含输入准备、子压缩器容量 API、独立编码/解码上下文、"
        "公开对象树、散列和完整输出物化。读取冻结文件与独立进程资格恢复在稳态时间之外。",
        "",
        "| 任务 | 现有子压缩器 | 有效外层试验 | 原始 bits | 完整压缩 bits | "
        "编码 ns/对象 | 解码 ns/对象 |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        times = row["timing_ns_per_object"]
        encoded = "缺失" if times["encode"] is None else f"{times['encode']['mean']:.0f}"
        decoded = "缺失" if times["decode"] is None else f"{times['decode']['mean']:.0f}"
        bits = ", ".join(str(b) for b in sorted(set(row["complete_artifact_bits"]))) or "缺失"
        markdown.append(
            f"| {row['dataset_key']} | {row['method_id']} | "
            f"{row['eligible_outer_count']}/{row['expected_outer_count']} | "
            f"{row['canonical_raw_bits']} | {bits} | {encoded} | {decoded} |"
        )
    markdown.extend(
        [
            "",
            "时间区间按随机配对的独立调度块重采样，并进行族内多重比较调整。"
            "未达到精度目标的比较保持 INCONCLUSIVE。",
            "",
            "f32 类型转换、ND 形状、时间戳和有效性掩码均为显式派生任务；"
            "不代表源数据的原始时间戳或缺失模式，不推断跨来源泛化能力。",
            "",
            f"预先冻结的实验决策：`{plan['decision_id']}`；"
            "[实验决策合同](experiment_decision.json)。",
            "",
            "辅助证据由独立只读审计生成并单独验收："
            "[未压缩完整对象基线](uncompressed_reference.md) / "
            "[JSON](uncompressed_reference.json)，"
            "[准备与缓冲成本](buffer_cost_audit.md) / "
            "[JSON](buffer_cost_audit.json)。辅助观测不补写本次正式性能 trial。",
            "",
        ]
    )
    (run_path / "report.md").write_text("\n".join(markdown), encoding="utf-8")
    return evidence_document(document)


def build_real_pipeline_inputs(project_root: Path, output_path: Path) -> list[dict[str, Any]]:
    """Two public real-value sources; all added semantics are explicitly derived."""
    datasets = []
    for source in ("etth1", "weather"):
        key = f"v32_{source}_f64_mts"
        canonical = (
            project_root
            / "artifacts/comparisons/v32_20261010/prepared"
            / key
            / (key + ".canonical.tscb")
        )
        manifest = project_root / "registry/comparison_datasets/v32_20261010" / (key + ".json")
        source_artifact = read_canonical(canonical)
        columns = [
            np.frombuffer(source_artifact.buffers[b["name"]], dtype=b["dtype"]).reshape(b["shape"])
            for b in source_artifact.metadata["buffers"]
            if b["name"] not in {"timestamp", "validity"}
        ]
        matrix = np.column_stack(columns)[:, :4]
        if matrix.shape[0] < 2049 or matrix.shape[1] != 4:
            raise PipelineComparisonError("real source lacks disjoint windows/four typed columns")
        for profile in ("f32", "mixed_nd_tv_validity"):
            documents = {}
            for split, start, n in (("test", 0, 513), ("development", 1024, 513)):
                selected = matrix[start : start + n]
                if profile == "f32":
                    values = {"f32": selected.astype("<f4")}
                    descriptions = [("f32", [n, 4], ["time", "feature"], 0)]
                    timestamp = validity = None
                else:
                    values = {
                        "nd_f64": selected.reshape(n, 2, 2).transpose(1, 0, 2).copy(),
                        "f32": selected[:, 0].astype("<f4"),
                    }
                    descriptions = [
                        ("nd_f64", [2, n, 2], ["entity", "time", "feature"], 1),
                        ("f32", [n], ["time"], 0),
                    ]
                    timestamp = np.arange(start, start + n, dtype="<i8") * 60_000_000_000
                    validity = {
                        name: (np.arange(a.size).reshape(a.shape) % 11 != 0)
                        for name, a in values.items()
                    }
                schema = LogicalObjectSchema.from_document(
                    {
                        "schema_version": "tscb.logical-object-schema.v1",
                        "values": [
                            {
                                "name": name,
                                "dtype": values[name].dtype.str,
                                "shape": shape,
                                "axes": axes,
                                "time_axis": axis,
                                "unit": "SOURCE_UNIT_UNSPECIFIED",
                                "entity": source,
                                "feature": name,
                            }
                            for name, shape, axes, axis in descriptions
                        ],
                        "timestamp": {
                            "present": timestamp is not None,
                            "dtype": "<i8" if timestamp is not None else "NOT_APPLICABLE",
                            "unit": "ns" if timestamp is not None else "NOT_APPLICABLE",
                            "epoch": "DERIVED_ZERO_INDEX"
                            if timestamp is not None
                            else "NOT_APPLICABLE",
                            "pairing": "SHARED_TIME_AXIS"
                            if timestamp is not None
                            else "NOT_APPLICABLE",
                        },
                        "null_recovery_contract": "BITWISE",
                    }
                )
                original = LogicalObject(schema, values, timestamp, validity)
                documents[split] = save_pipeline_input(
                    output_path / (source + "_" + profile + "_" + split + ".npz"), original
                )
            datasets.append(
                {
                    "dataset_key": source + "_" + profile,
                    **documents,
                    "source_files": [
                        {"path": str(p.resolve()), "sha256": _sha(p)} for p in (canonical, manifest)
                    ],
                    "derivation": {
                        "source_key": source,
                        "source_canonical_sha256": source_artifact.sha256,
                        "test_window": [0, 513],
                        "development_window": [1024, 1537],
                        "f32_cast": "DERIVED_ORIGINAL_TASK_F32_AFTER_EXPLICIT_CAST",
                        "nd_mapping": "ROW_FOUR_FEATURES_TO_ENTITY_2_TIME_FEATURE_2",
                        "timestamp": "DERIVED_ROW_INDEX_NS_NOT_SOURCE_TIMESTAMPS",
                        "validity": "DERIVED_INDEX_MOD_11_NOT_SOURCE_MISSINGNESS",
                        "source_generalization_claim": False,
                    },
                }
            )
    return datasets
