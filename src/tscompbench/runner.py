from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tscompbench.adapters import adapter_artifacts, create_adapter
from tscompbench.codecs import (
    CodecRegistry,
    classify_logical_entries,
    descriptor_from_layer1_artifacts,
    negotiate,
)
from tscompbench.configuration import ExperimentConfig, load_experiment_config
from tscompbench.contracts import BenchmarkTrack
from tscompbench.datasets.canonical import read_canonical
from tscompbench.datasets.characterize import CharacterizationProfile
from tscompbench.datasets.prepare import (
    PreparationResult,
    load_preparation_result,
    prepare_dataset,
)
from tscompbench.datasets.registry import DatasetRegistry, sha256_file
from tscompbench.environment import capture_environment
from tscompbench.execution.orchestrator import execute_task
from tscompbench.measurement import MeasurementPolicy
from tscompbench.planning import (
    BenchmarkTask,
    build_comparability_keys,
    create_task,
    expand_sweep,
    resolve_execution,
    write_task_plan,
)
from tscompbench.preprocess import build_preprocess_plan
from tscompbench.reporting import ReportResult, generate_report
from tscompbench.version import __version__

from .storage import (
    EventLogError,
    append_event,
    append_run_record,
    rebuild_runs_csv,
    validate_event_log,
)


class RunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class RunSet:
    run_set_id: str
    path: Path
    config: ExperimentConfig
    environment: dict[str, Any]


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_or_verify_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True).encode(
            "utf-8"
        )
        + b"\n"
    )
    if path.exists():
        if path.read_bytes() != encoded:
            raise RunnerError(f"existing frozen artifact differs: {path.name}")
        return
    with path.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _write_or_verify_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != value:
            raise RunnerError(f"existing frozen artifact differs: {path.name}")
        return
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary_name = handle.name
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def _probe_workspace(output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(output_root)
    with tempfile.NamedTemporaryFile(dir=output_root, delete=False) as handle:
        probe_path = Path(handle.name)
        handle.write(b"atomic-append-probe\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        with probe_path.open("ab") as handle:
            handle.write(b"second-record\n")
            handle.flush()
            os.fsync(handle.fileno())
        atomic_append = probe_path.read_bytes() == b"atomic-append-probe\nsecond-record\n"
    finally:
        probe_path.unlink(missing_ok=True)
    return {
        "disk_total_bytes": usage.total,
        "disk_free_bytes": usage.free,
        "atomic_append_probe": atomic_append,
        "process_isolation": hasattr(os, "fork"),
        "monotonic_clock": True,
    }


def _default_run_set_id(config: ExperimentConfig) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = config.experiment_config_id.rsplit(":", 1)[-1][:12]
    return f"runset-{timestamp}-{suffix}"


def _repository_state(project_root: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if commit.returncode != 0:
            return {
                "status": "UNAVAILABLE",
                "reason": (commit.stderr or commit.stdout).strip(),
            }
        dirty = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain=v1"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return {
            "status": "AVAILABLE",
            "commit": commit.stdout.strip(),
            "dirty": bool(dirty.stdout.strip()),
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"status": "PROBE_FAILED", "reason": str(error)}


def initialize_run_set(
    config_path: Path,
    output_root: Path,
    *,
    run_set_id: str | None = None,
    resume: bool = False,
) -> RunSet:
    config = load_experiment_config(config_path)
    run_set_id = run_set_id or _default_run_set_id(config)
    if Path(run_set_id).name != run_set_id or run_set_id in {"", ".", ".."}:
        raise RunnerError("run_set_id must be a single safe path component")
    output_root = output_root.resolve()
    probe = _probe_workspace(output_root)
    if not probe["atomic_append_probe"]:
        raise RunnerError("output filesystem failed atomic append probe")
    if probe["disk_free_bytes"] < 64 * 1024 * 1024:
        raise RunnerError("less than 64 MiB free space is available")
    lock_root = output_root / ".locks"
    lock_root.mkdir(exist_ok=True)
    lock_path = lock_root / f"{run_set_id}.lock"
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError(f"run set is locked by another process: {run_set_id}") from error
        run_path = output_root / run_set_id
        if run_path.exists():
            if not resume:
                raise RunnerError(f"run set already exists: {run_set_id}")
            frozen_path = run_path / "frozen_config.json"
            environment_path = run_path / "environment.json"
            if not frozen_path.is_file() or not environment_path.is_file():
                raise RunnerError("resume target lacks frozen config or environment")
            frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
            if frozen != config.canonical_document:
                raise RunnerError("resume config differs from frozen config")
            environment = json.loads(environment_path.read_text(encoding="utf-8"))
            try:
                validate_event_log(run_path / "events.jsonl")
            except EventLogError as error:
                raise RunnerError(f"resume event log validation failed: {error}") from error
            current_environment = capture_environment()
            if current_environment["environment_id"] != environment.get("environment_id"):
                raise RunnerError("resume environment differs from frozen environment")
            append_event(
                run_path / "events.jsonl",
                "RUN_SET_RESUMED",
                {"run_set_id": run_set_id, "experiment_config_id": config.experiment_config_id},
            )
            return RunSet(run_set_id, run_path, config, environment)

        run_path.mkdir(mode=0o755)
        try:
            environment = capture_environment()
            project_root = Path(__file__).resolve().parents[2]
            _write_json(run_path / "frozen_config.json", config.canonical_document)
            _write_json(run_path / "environment.json", environment)
            _write_json(
                run_path / "run-set.json",
                {
                    "schema_version": "tscb.run-set.v2",
                    "run_set_id": run_set_id,
                    "experiment_config_id": config.experiment_config_id,
                    "environment_id": environment["environment_id"],
                    "workspace_probe": probe,
                    "runner": {
                        "implementation": "python",
                        "version": "0.1.0",
                        "executable": sys.executable,
                        "command_line": sys.argv,
                        "repository": _repository_state(project_root),
                    },
                    "config_source_sha256": sha256_file(config_path.resolve()),
                    "source_directories_policy": "READ_ONLY_NO_WRITES",
                },
            )
            append_event(
                run_path / "events.jsonl",
                "RUN_SET_CREATED",
                {
                    "run_set_id": run_set_id,
                    "experiment_config_id": config.experiment_config_id,
                    "environment_id": environment["environment_id"],
                },
            )
        except Exception:
            shutil.rmtree(run_path)
            raise
        return RunSet(run_set_id, run_path, config, environment)
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def prepare_run_set(
    run_set: RunSet,
    registry: DatasetRegistry,
) -> tuple[PreparationResult, ...]:
    profile = CharacterizationProfile(
        mode=run_set.config.data_preparation.characterization_mode,
        sample_rows=run_set.config.data_preparation.characterization_sample_rows,
        seed=run_set.config.seed,
    )
    lock_path = run_set.path.parent / ".locks" / f"{run_set.run_set_id}.lock"
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError(
                f"run set is locked by another process: {run_set.run_set_id}"
            ) from error

        results: list[PreparationResult] = []
        dataset_root = run_set.path / "datasets"
        for key in run_set.config.datasets:
            preparation_record = dataset_root / key / "preparation-record.json"
            append_event(run_set.path / "events.jsonl", "DATASET_PREPARATION_STARTED", {"key": key})
            try:
                if preparation_record.is_file():
                    result = load_preparation_result(registry, key, dataset_root)
                    event_type = "DATASET_PREPARATION_REUSED"
                else:
                    result = prepare_dataset(
                        registry, key, dataset_root, characterization_profile=profile
                    )
                    event_type = "DATASET_PREPARATION_COMPLETED"
            except Exception as error:
                append_event(
                    run_set.path / "events.jsonl",
                    "DATASET_PREPARATION_FAILED",
                    {"key": key, "error_type": type(error).__name__, "message": str(error)},
                )
                raise
            results.append(result)
            append_event(
                run_set.path / "events.jsonl",
                event_type,
                {
                    "key": key,
                    "dataset_id": result.dataset_id,
                    "canonical_sha256": result.canonical.sha256,
                },
            )
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_1_COMPLETED",
            {"dataset_count": len(results), "dataset_ids": [item.dataset_id for item in results]},
        )
        return tuple(results)
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def plan_run_set(
    run_set: RunSet,
    dataset_registry: DatasetRegistry,
    codec_registry: CodecRegistry,
) -> tuple[BenchmarkTask, ...]:
    """Complete Layer 1 if needed, then freeze the deterministic Layer 2 task universe."""

    if not run_set.config.algorithms:
        raise RunnerError("Layer 2 planning requires at least one configured algorithm")
    preparations = prepare_run_set(run_set, dataset_registry)
    preparation_by_key = {item.dataset_key: item for item in preparations}
    lock_path = run_set.path.parent / ".locks" / f"{run_set.run_set_id}.lock"
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError(
                f"run set is locked by another process: {run_set.run_set_id}"
            ) from error
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_2_PLANNING_STARTED",
            {
                "algorithm_keys": run_set.config.algorithms,
                "tracks": run_set.config.tracks,
            },
        )
        project_root = Path(__file__).resolve().parents[2]
        profile = run_set.config.profile.as_document()
        profile["runner_version"] = __version__
        tasks: list[BenchmarkTask] = []
        resolved_config_documents: dict[str, dict[str, Any]] = {}
        codec_documents: list[dict[str, Any]] = []
        source_documents: dict[str, dict[str, Any]] = {}
        requested_aliases = [
            item for item in codec_registry.alias_documents()
            if item["key"] in run_set.config.algorithms
        ]
        if requested_aliases:
            _write_or_verify_json(run_set.path / "codec_alias_snapshot.json", {
                "schema_version": "tscb.codec-alias-snapshot.v2",
                "aliases": requested_aliases,
            })
        planned_codec_keys: set[str] = set()
        for algorithm_key in run_set.config.algorithms:
            manifest = codec_registry.get(algorithm_key)
            if manifest.key in planned_codec_keys:
                continue
            planned_codec_keys.add(manifest.key)
            source_documents[manifest.source_artifact_id] = codec_registry.sources.get(
                manifest.source_artifact_id
            )
            adapter_artifact, supporting_adapter_artifacts = adapter_artifacts(
                project_root, manifest
            )
            preprocess = build_preprocess_plan(manifest.document)
            codec_documents.append(
                {
                    "key": manifest.key,
                    "algorithm_id": manifest.algorithm_id,
                    "source_artifact_id": manifest.source_artifact_id,
                    "manifest": manifest.document,
                }
            )
            configs = expand_sweep(
                manifest,
                run_set.config.sweep,
                framework_parameters={"benchmark_seed": run_set.config.seed},
            )
            for config in configs:
                resolved_config_documents[config.config_id] = {
                    "schema_version": "tscb.resolved-config.v2",
                    "algorithm_id": config.algorithm_id,
                    "config_id": config.config_id,
                    "parameters": config.parameters,
                    "framework_parameters": config.framework_parameters,
                    "status": config.status,
                    "reason_code": config.reason_code,
                }
            for dataset_key in run_set.config.datasets:
                preparation = preparation_by_key[dataset_key]
                characterization = json.loads(
                    preparation.characterization_path.read_text(encoding="utf-8")
                )
                if (
                    characterization["canonical_content_sha256"]
                    != preparation.canonical.metadata["dataset_content_sha256"]
                ):
                    raise RunnerError("Layer 1 characterization/canonical content hash mismatch")
                for track_name in run_set.config.tracks:
                    descriptor = descriptor_from_layer1_artifacts(
                        preparation.canonical.metadata,
                        characterization,
                        BenchmarkTrack(track_name),
                    )
                    for config in configs:
                        compatibility = negotiate(manifest, descriptor)
                        execution = resolve_execution(
                            manifest,
                            config,
                            compatibility,
                            run_set.environment,
                            artifact_path=adapter_artifact,
                            profile=profile,
                            supporting_artifact_paths=supporting_adapter_artifacts,
                        )
                        comparability = build_comparability_keys(
                            manifest,
                            descriptor,
                            config,
                            compatibility,
                            execution,
                            profile=profile,
                        )
                        tasks.append(
                            create_task(
                                descriptor=descriptor,
                                manifest=manifest,
                                config=config,
                                profile_id=run_set.config.profile.profile_id,
                                compatibility=compatibility,
                                preprocess=preprocess,
                                execution=execution,
                                comparability=comparability,
                                resource_limits={
                                    "timeout_seconds": run_set.config.profile.timeout_seconds,
                                    "memory_limit_bytes": run_set.config.profile.memory_limit_bytes,
                                },
                            )
                        )

        source_classification = classify_logical_entries(
            codec_registry.sources.catalog,
            codec_registry.root / "logical_classification_rules.json",
        )
        _write_or_verify_json(run_set.path / "source_classification.json", source_classification)
        _write_or_verify_json(
            run_set.path / "codec_registry_snapshot.json",
            {
                "schema_version": "tscb.codec-registry-snapshot.v2",
                "codecs": sorted(codec_documents, key=lambda item: item["algorithm_id"]),
            },
        )
        _write_or_verify_json(
            run_set.path / "source_registry_snapshot.json",
            {
                "schema_version": "tscb.source-registry-snapshot.v2",
                "sources": [source_documents[key] for key in sorted(source_documents)],
            },
        )
        _write_or_verify_json(
            run_set.path / "resolved_configs.json",
            {
                "schema_version": "tscb.resolved-config-set.v2",
                "configs": [
                    resolved_config_documents[key] for key in sorted(resolved_config_documents)
                ],
            },
        )
        ordered_tasks = tuple(sorted(tasks, key=lambda item: item.task_id))
        write_task_plan(run_set.path / "task_plan.jsonl", ordered_tasks)
        status_counts: dict[str, int] = {}
        capability_counts: dict[str, int] = {}
        for task in ordered_tasks:
            status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1
            capability = task.compatibility.status.value
            capability_counts[capability] = capability_counts.get(capability, 0) + 1
        _write_or_verify_json(
            run_set.path / "layer2-plan.json",
            {
                "schema_version": "tscb.layer2-plan.v2",
                "run_set_id": run_set.run_set_id,
                "profile_id": run_set.config.profile.profile_id,
                "task_count": len(ordered_tasks),
                "task_status_counts": status_counts,
                "capability_status_counts": capability_counts,
                "source_classification_report_id": source_classification[
                    "classification_report_id"
                ],
                "source_logical_entry_count": source_classification["entry_count"],
                "layer1_dataset_ids": [item.dataset_id for item in preparations],
            },
        )
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_2_COMPLETED",
            {
                "task_count": len(ordered_tasks),
                "task_status_counts": status_counts,
                "capability_status_counts": capability_counts,
            },
        )
        return ordered_tasks
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def _layer3_progress(run_path: Path) -> dict[str, dict[str, Any]]:
    path = run_path / "run_components.jsonl"
    if not path.is_file():
        return {}
    progress: dict[str, dict[str, Any]] = {}
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith(b"\n"):
                raise RunnerError(f"run_components line {line_number} is incomplete")
            try:
                document = json.loads(line)
            except json.JSONDecodeError as error:
                raise RunnerError(f"run_components line {line_number} is invalid") from error
            task = progress.setdefault(
                str(document["task_id"]), {"diagnostic": False, "repetitions": set()}
            )
            if document.get("record_kind") == "DIAGNOSTIC":
                task["diagnostic"] = True
            elif document.get("record_kind") == "FORMAL_REPETITION":
                task["repetitions"].add(int(document["repetition_index"]))
    return progress


def execute_run_set(
    run_set: RunSet,
    dataset_registry: DatasetRegistry,
    codec_registry: CodecRegistry,
    *,
    formal_repetitions: int | None = None,
) -> tuple[Any, ...]:
    """Run the shared Layer-3 validation and Layer-4 measurement lifecycle."""

    if formal_repetitions is None:
        formal_repetitions = run_set.config.profile.repetitions
    elif formal_repetitions != run_set.config.profile.repetitions:
        raise RunnerError(
            "formal_repetitions override differs from the frozen qualification profile"
        )
    if formal_repetitions < 1:
        raise RunnerError("formal_repetitions must be positive")
    tasks = plan_run_set(run_set, dataset_registry, codec_registry)
    measurement_policy = MeasurementPolicy.from_profile(
        run_set.config.profile, seed=run_set.config.seed
    )
    resolved = json.loads((run_set.path / "resolved_configs.json").read_text(encoding="utf-8"))
    parameters = {item["config_id"]: item["parameters"] for item in resolved["configs"]}
    artifacts: dict[str, Any] = {}
    project_root = Path(__file__).resolve().parents[2]
    for path in sorted((run_set.path / "datasets").glob("*/*.canonical.tscb")):
        artifact = read_canonical(path, include_buffers=True)
        artifacts[str(artifact.metadata["dataset_id"])] = artifact

    progress = _layer3_progress(run_set.path)
    lock_path = run_set.path.parent / ".locks" / f"{run_set.run_set_id}.lock"
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    results: list[Any] = []
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError(
                f"run set is locked by another process: {run_set.run_set_id}"
            ) from error
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_3_EXECUTION_STARTED",
            {
                "task_count": len(tasks),
                "formal_repetitions": formal_repetitions,
                "measurement_mode": measurement_policy.measurement_mode,
            },
        )
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_4_MEASUREMENT_STARTED",
            measurement_policy.to_document(),
        )
        rebuild_runs_csv(run_set.path)
        for task in tasks:
            task_progress = progress.get(task.task_id, {"diagnostic": False, "repetitions": set()})
            missing_repetitions = tuple(
                value
                for value in range(formal_repetitions)
                if value not in task_progress["repetitions"]
            )
            if task_progress["diagnostic"] or not missing_repetitions:
                append_event(
                    run_set.path / "events.jsonl",
                    "LAYER_3_TASK_REUSED",
                    {"task_id": task.task_id},
                )
                continue
            manifest = next(
                item
                for item in codec_registry.verify_all()
                if item.algorithm_id == task.algorithm_id
            )
            source = codec_registry.sources.get(manifest.source_artifact_id)
            artifact = artifacts.get(task.dataset_id)
            if artifact is None:
                raise RunnerError(f"Layer 1 canonical artifact missing for {task.dataset_id}")
            adapter = create_adapter(project_root, manifest)
            append_event(
                run_set.path / "events.jsonl",
                "TASK_PREFLIGHTING",
                {"task_id": task.task_id, "adapter_id": adapter.adapter_id},
            )

            def persist_repetition(record: Any, stream: bytes | None) -> None:
                append_run_record(run_set.path, record)
                if stream is not None:
                    _write_or_verify_bytes(
                        run_set.path / "artifacts" / f"{record.run_id.rsplit(':', 1)[-1]}.bin",
                        stream,
                    )

            result = execute_task(
                run_set_id=run_set.run_set_id,
                task=task,
                manifest=manifest,
                source=source,
                artifact=artifact,
                adapter=adapter,
                parameters=parameters[task.config_id],
                measurement_policy=measurement_policy,
                repetitions=formal_repetitions,
                repetition_indices=missing_repetitions,
                event_callback=lambda event_type, payload: append_event(
                    run_set.path / "events.jsonl", event_type, payload
                ),
                record_callback=persist_repetition,
            )
            preflight_name = task.task_id.rsplit(":", 1)[-1] + ".json"
            _write_or_verify_json(
                run_set.path / "preflight" / preflight_name,
                result.preflight.to_document(),
            )
            if result.warmup is not None:
                warmup_name = (
                    preflight_name.removesuffix(".json") + f".from-{missing_repetitions[0]}.json"
                )
                _write_or_verify_json(
                    run_set.path / "warmup" / warmup_name,
                    result.warmup.to_document(),
                )
            stream_by_run = dict(result.bitstreams)
            for record in result.records:
                append_run_record(run_set.path, record)
                if record.run_id in stream_by_run:
                    _write_or_verify_bytes(
                        run_set.path / "artifacts" / f"{record.run_id.rsplit(':', 1)[-1]}.bin",
                        stream_by_run[record.run_id],
                    )
            results.append(result)

        status_counts: dict[str, int] = {}
        record_count = 0
        components_path = run_set.path / "run_components.jsonl"
        if components_path.is_file():
            with components_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    record = json.loads(line)
                    status = str(record["status"])
                    status_counts[status] = status_counts.get(status, 0) + 1
                    record_count += 1
        _replace_json(
            run_set.path / "layer3-execution.json",
            {
                "schema_version": "tscb.layer3-execution.v2",
                "run_set_id": run_set.run_set_id,
                "task_count": len(tasks),
                "record_count": record_count,
                "status_counts": status_counts,
                "formal_repetitions_per_eligible_task": formal_repetitions,
                "performance_aggregation": "DEFERRED_TO_LAYER_5",
            },
        )
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_3_COMPLETED",
            {"record_count": record_count, "status_counts": status_counts},
        )
        _replace_json(
            run_set.path / "layer4-performance.json",
            {
                "schema_version": "tscb.layer4-performance.v2",
                "run_set_id": run_set.run_set_id,
                "measurement_policy": measurement_policy.to_document(),
                "record_count": record_count,
                "status_counts": status_counts,
                "raw_repetitions_path": "run_components.jsonl",
                "flat_projection_path": "runs.csv",
                "statistics_aggregation": "DEFERRED_TO_LAYER_5",
            },
        )
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_4_COMPLETED",
            {"record_count": record_count, "status_counts": status_counts},
        )
        return tuple(results)
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)


def report_run_set(run_set: RunSet) -> ReportResult:
    """Run Layer 5 over frozen Layer 1-4 evidence without invoking a codec."""

    lock_path = run_set.path.parent / ".locks" / f"{run_set.run_set_id}.lock"
    lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunnerError(
                f"run set is locked by another process: {run_set.run_set_id}"
            ) from error
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_5_REPORTING_STARTED",
            {"reporting_policy": run_set.config.reporting.as_document()},
        )
        result = generate_report(run_set.path, run_set.config.reporting.as_document())
        append_event(
            run_set.path / "events.jsonl",
            "LAYER_5_COMPLETED",
            {
                "report_id": result.report_id,
                "task_count": result.task_count,
                "summary_count": result.summary_count,
                "eligible_run_count": result.eligible_run_count,
            },
        )
        return result
    finally:
        fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
        os.close(lock_descriptor)
