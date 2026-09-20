from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id

from .core import decimal_divide, descriptive_statistics, pareto_front, percentile, rank_values

_ANALYSES = ("SPACE_QUALITY", "PERFORMANCE", "RESOURCE")
_ACCOUNTING_COMPONENTS = (
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


class StatisticsError(ValueError):
    pass


@dataclass(frozen=True)
class AnalysisBundle:
    policy: dict[str, Any]
    source_hashes: dict[str, str]
    eligibility: tuple[dict[str, Any], ...]
    summaries: tuple[dict[str, Any], ...]
    corpus_summaries: tuple[dict[str, Any], ...]
    coverage: tuple[dict[str, Any], ...]
    comparability_groups: tuple[dict[str, Any], ...]
    pareto: tuple[dict[str, Any], ...]
    rankings: tuple[dict[str, Any], ...]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StatisticsError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise StatisticsError(f"{path.name} must contain a JSON object")
    return value


def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
    if not path.is_file():
        raise StatisticsError(f"required frozen evidence is missing: {path.name}")
    result: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.endswith(b"\n"):
                raise StatisticsError(f"{path.name} line {line_number} is incomplete")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise StatisticsError(f"{path.name} line {line_number} is invalid") from error
            if not isinstance(value, dict):
                raise StatisticsError(f"{path.name} line {line_number} is not an object")
            result.append(value)
    return tuple(result)


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError, OverflowError:
        return None
    return number if math.isfinite(number) else None


def _task_chain_valid(task: dict[str, Any]) -> bool:
    comparison = task.get("comparability") or {}
    semantic_key = comparison.get("semantic_key")
    execution_key = comparison.get("execution_key")
    return (
        bool(semantic_key)
        and bool(execution_key)
        and comparison.get("resource_key")
        and (comparison.get("execution_document") or {}).get("semantic_key") == semantic_key
        and (comparison.get("resource_document") or {}).get("execution_key") == execution_key
    )


def _accounting_valid(accounting: Any) -> bool:
    if not isinstance(accounting, dict):
        return False
    integers = _ACCOUNTING_COMPONENTS + (
        "external_side_information_bits",
        "serialized_bits",
        "final_bits",
        "final_physical_bytes",
        "canonical_raw_bits",
    )
    if any(
        not isinstance(accounting.get(name), int)
        or isinstance(accounting.get(name), bool)
        or accounting[name] < 0
        for name in integers
    ):
        return False
    serialized = accounting["serialized_bits"]
    return (
        sum(accounting[name] for name in _ACCOUNTING_COMPONENTS) == serialized
        and accounting["final_physical_bytes"] == (serialized + 7) // 8
        and accounting["final_bits"] == serialized + accounting["external_side_information_bits"]
    )


def _artifact_valid(run_path: Path, record: dict[str, Any]) -> tuple[bool, str]:
    bitstream_hash = record.get("bitstream_sha256")
    run_id = str(record.get("run_id", ""))
    if not bitstream_hash or not run_id:
        return False, "BITSTREAM_IDENTITY_MISSING"
    artifact = run_path / "artifacts" / f"{run_id.rsplit(':', 1)[-1]}.bin"
    if not artifact.is_file():
        return False, "BITSTREAM_ARTIFACT_MISSING"
    if _sha256_file(artifact) != bitstream_hash:
        return False, "BITSTREAM_ARTIFACT_HASH_MISMATCH"
    return True, "PASS"


def _base_reasons(
    run_path: Path,
    record: dict[str, Any],
    task: dict[str, Any] | None,
    dataset_provenance: dict[str, dict[str, Any]],
    source_artifact_ids: set[str],
) -> list[str]:
    reasons: list[str] = []
    if record.get("schema_version") != "tscb.run-record.v2":
        reasons.append("SCHEMA_VERSION_MISMATCH")
    if record.get("record_kind") != "FORMAL_REPETITION":
        reasons.append("NOT_FORMAL_REPETITION")
    if record.get("status") != "PASS":
        reasons.append(f"RUN_STATUS_{record.get('status', 'UNSPECIFIED')}")
    if record.get("eligibility") is not True:
        reasons.append("BENCHMARK_ELIGIBILITY_FALSE")
    if task is None:
        reasons.append("TASK_NOT_IN_FROZEN_UNIVERSE")
    elif not _task_chain_valid(task):
        reasons.append("COMPARABILITY_CHAIN_INVALID")
    else:
        execution = task.get("execution") or {}
        comparison = task.get("comparability") or {}
        semantic = comparison.get("semantic_document") or {}
        if execution.get("source_artifact_id") not in source_artifact_ids:
            reasons.append("SOURCE_PROVENANCE_MISSING")
        if any(
            execution.get(name) in {None, "", "UNSPECIFIED"}
            for name in (
                "source_artifact_id",
                "adapter_id",
                "artifact_sha256",
                "environment_id",
                "execution_path_hash",
            )
        ):
            reasons.append("EXECUTION_PROVENANCE_MISSING")
        if any(
            semantic.get(name) in {None, "", "UNSPECIFIED"}
            for name in ("track", "object_level", "loss_mode")
        ):
            reasons.append("COMPARABILITY_SEMANTICS_UNSPECIFIED")
        task_identity = tuple(
            task.get(name)
            for name in ("task_id", "dataset_id", "algorithm_id", "config_id", "track")
        )
        run_identity = tuple(
            record.get(name)
            for name in ("task_id", "dataset_id", "algorithm_id", "config_id", "track")
        )
        if task_identity != run_identity:
            reasons.append("RUN_TASK_IDENTITY_MISMATCH")
        if execution.get("execution_path_hash") != record.get("execution_path_hash"):
            reasons.append("RUN_TASK_EXECUTION_PATH_MISMATCH")
        expected_keys = (
            comparison.get("semantic_key"),
            comparison.get("execution_key"),
            comparison.get("resource_key"),
        )
        observed_keys = (
            record.get("semantic_comparability_key"),
            record.get("execution_comparability_key"),
            record.get("resource_profile_key"),
        )
        if expected_keys != observed_keys:
            reasons.append("RUN_TASK_COMPARABILITY_MISMATCH")
    dataset_facts = dataset_provenance.get(str(record.get("dataset_id")))
    if dataset_facts is None or any(
        not dataset_facts.get(name)
        for name in (
            "source_sha256",
            "canonical_artifact_sha256",
            "canonical_content_sha256",
        )
    ):
        reasons.append("DATASET_PROVENANCE_MISSING")
    required_identity = (
        "run_id",
        "run_set_id",
        "task_id",
        "dataset_id",
        "algorithm_id",
        "config_id",
        "execution_path_hash",
        "semantic_comparability_key",
        "execution_comparability_key",
        "resource_profile_key",
        "track",
        "input_sha256",
        "bitstream_sha256",
    )
    if any(record.get(name) in {None, "", "UNSPECIFIED"} for name in required_identity):
        reasons.append("REQUIRED_IDENTITY_UNSPECIFIED")
    correctness = record.get("correctness")
    if not isinstance(correctness, dict) or correctness.get("status") != "PASS":
        reasons.append("CORRECTNESS_NOT_PASS")
    elif correctness.get("first_failure_stage") is not None:
        reasons.append("CORRECTNESS_FAILURE_STAGE_PRESENT")
    loss = correctness.get("loss") if isinstance(correctness, dict) else None
    if isinstance(loss, dict) and loss.get("bound_passed") is not True:
        reasons.append("ERROR_BOUND_NOT_PASS")
    if not _accounting_valid(record.get("accounting")):
        reasons.append("ACCOUNTING_INCOMPLETE_OR_INCONSISTENT")
    timing = record.get("timing")
    if not isinstance(timing, dict):
        reasons.append("TIMING_MISSING")
    else:
        if timing.get("schema_version") != "tscb.timing-observation.v2":
            reasons.append("TIMING_SCHEMA_MISMATCH")
        if timing.get("min_duration_satisfied") is not True:
            reasons.append("MIN_DURATION_NOT_SATISFIED")
        if (
            not isinstance(timing.get("inner_iterations"), int)
            or timing.get("inner_iterations", 0) < 1
        ):
            reasons.append("INNER_ITERATIONS_INVALID")
        for name in (
            "selected_wall_ns",
            "selected_encode_wall_ns",
            "selected_decode_wall_ns",
            "e2e_wall_ns",
            "canonical_bytes_per_iteration",
        ):
            value = timing.get(name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                reasons.append(f"{name.upper()}_INVALID")
    policy = (record.get("diagnostics") or {}).get("measurement_policy")
    if not isinstance(policy, dict) or policy.get("measurement_mode") != "FORMAL":
        reasons.append("MEASUREMENT_MODE_NOT_FORMAL")
    valid_artifact, artifact_reason = _artifact_valid(run_path, record)
    if not valid_artifact:
        reasons.append(artifact_reason)
    return reasons


def _analysis_reasons(
    analysis: str,
    record: dict[str, Any],
    base_reasons: list[str],
) -> list[str]:
    reasons = list(base_reasons)
    if analysis == "RESOURCE":
        resources = record.get("resources")
        if not isinstance(resources, dict):
            reasons.append("RESOURCE_OBSERVATION_MISSING")
        elif resources.get("scope_availability") != "AVAILABLE":
            reasons.append("RESOURCE_SCOPE_UNAVAILABLE")
    return sorted(set(reasons))


def _eligibility(
    run_path: Path,
    records: tuple[dict[str, Any], ...],
    tasks: dict[str, dict[str, Any]],
    dataset_provenance: dict[str, dict[str, Any]],
    source_artifact_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], list[str]]]:
    rows: list[dict[str, Any]] = []
    reasons_by_run: dict[tuple[str, str], list[str]] = {}
    for record in records:
        run_id = str(record.get("run_id", "UNSPECIFIED"))
        task = tasks.get(str(record.get("task_id", "")))
        base = _base_reasons(
            run_path,
            record,
            task,
            dataset_provenance,
            source_artifact_ids,
        )
        for analysis in _ANALYSES:
            reasons = _analysis_reasons(analysis, record, base)
            reasons_by_run[(run_id, analysis)] = reasons
            key_name = {
                "SPACE_QUALITY": "semantic_comparability_key",
                "PERFORMANCE": "execution_comparability_key",
                "RESOURCE": "resource_profile_key",
            }[analysis]
            rows.append(
                {
                    "schema_version": "tscb.eligibility-record.v2",
                    "run_id": run_id,
                    "task_id": record.get("task_id"),
                    "dataset_id": record.get("dataset_id"),
                    "algorithm_id": record.get("algorithm_id"),
                    "config_id": record.get("config_id"),
                    "execution_path_hash": record.get("execution_path_hash"),
                    "analysis": analysis,
                    "comparison_key": record.get(key_name),
                    "eligible": not reasons,
                    "reason_codes": reasons or ["ELIGIBLE"],
                }
            )

    # Repetition sufficiency is a property of a complete frozen group, not one row.
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    by_run = {str(item.get("run_id")): item for item in records}
    for row in rows:
        if row["analysis"] != "PERFORMANCE" or not row["eligible"]:
            continue
        record = by_run[row["run_id"]]
        key = (
            str(record["dataset_id"]),
            str(record["algorithm_id"]),
            str(record["config_id"]),
            str(record["execution_path_hash"]),
            str(record["schema_version"]),
        )
        groups[key].append(row)
    for group_rows in groups.values():
        record = by_run[group_rows[0]["run_id"]]
        policy = record["diagnostics"]["measurement_policy"]
        required = max(10, int(policy.get("repetitions", 0)))
        repetition_indices = {by_run[row["run_id"]].get("repetition_index") for row in group_rows}
        if len(group_rows) < required or len(repetition_indices) != len(group_rows):
            for analysis in ("PERFORMANCE", "RESOURCE", "SPACE_QUALITY"):
                for row in rows:
                    if (
                        row["run_id"] in {item["run_id"] for item in group_rows}
                        and row["analysis"] == analysis
                    ):
                        reason_list = reasons_by_run[(row["run_id"], analysis)]
                        reason_list.append("INSUFFICIENT_OR_DUPLICATE_REPETITIONS")
                        row["eligible"] = False
                        row["reason_codes"] = sorted(set(reason_list))
    rows.sort(key=lambda item: (str(item["run_id"]), str(item["analysis"])))
    return rows, reasons_by_run


def _per_iteration(record: dict[str, Any], field: str) -> float:
    timing = record["timing"]
    return float(timing[field]) / int(timing["inner_iterations"])


def _quality(record: dict[str, Any]) -> dict[str, float | None]:
    loss = (record.get("correctness") or {}).get("loss")
    if not isinstance(loss, dict):
        return {"rmse": None, "mae": None, "max_ae": None, "psnr_range_db": None}
    channels = loss.get("channels") or []
    weighted_square = weighted_absolute = elements = 0.0
    maximum: float | None = None
    psnr_values: list[float] = []
    for channel in channels:
        count = _finite_number(channel.get("element_count"))
        rmse = _finite_number(channel.get("rmse"))
        mae = _finite_number(channel.get("mae"))
        max_ae = _finite_number(channel.get("max_ae"))
        psnr = _finite_number(channel.get("psnr_range_db"))
        if count is not None and rmse is not None and mae is not None:
            weighted_square += rmse * rmse * count
            weighted_absolute += mae * count
            elements += count
        if max_ae is not None:
            maximum = max_ae if maximum is None else max(maximum, max_ae)
        if psnr is not None:
            psnr_values.append(psnr)
    return {
        "rmse": None if elements == 0 else math.sqrt(weighted_square / elements),
        "mae": None if elements == 0 else weighted_absolute / elements,
        "max_ae": maximum,
        "psnr_range_db": None if not psnr_values else sum(psnr_values) / len(psnr_values),
    }


def _stats_fields(
    prefix: str,
    values: list[int | float],
    *,
    policy: dict[str, Any],
    seed: str,
) -> dict[str, Any]:
    if not values:
        return {
            f"{prefix}_{suffix}": None
            for suffix in ("median", "p25", "p75", "mean", "sd", "cv", "ci_low", "ci_high")
        }
    statistics_row = descriptive_statistics(
        values,
        bootstrap_samples=int(policy["bootstrap_samples"]),
        confidence_level=Decimal(str(policy["confidence_level"])),
        seed_material=f"{seed}:{prefix}",
    )
    return {
        f"{prefix}_{name}": statistics_row[name]
        for name in ("median", "p25", "p75", "mean", "sd", "cv", "ci_low", "ci_high")
    }


def _dataset_provenance(run_path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted((run_path / "datasets").glob("*/preparation-record.json")):
        document = _read_json(path)
        result[str(document["dataset_id"])] = {
            "canonical_artifact_sha256": document.get("canonical_artifact_sha256"),
            "canonical_content_sha256": document.get("canonical_content_sha256"),
            "source_sha256": document.get("source_sha256"),
        }
    return result


def _auxiliary_timing_fields(
    group: list[dict[str, Any]], policy: dict[str, Any], seed: str
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    native_boundaries = {
        timing.get("native_timing_boundary")
        for record in group
        if isinstance((timing := record["timing"]).get("native_timing_boundary"), str)
        and timing["native_timing_boundary"]
    }
    native_clocks = {
        timing.get("native_timing_clock")
        for record in group
        if isinstance((timing := record["timing"]).get("native_timing_clock"), str)
        and timing["native_timing_clock"]
    }
    native_boundary = next(iter(native_boundaries)) if len(native_boundaries) == 1 else None
    native_clock = next(iter(native_clocks)) if len(native_clocks) == 1 else None
    for scope in ("core", "pipeline", "native"):
        for direction in ("encode", "decode"):
            field = f"{scope}_{direction}_wall_ns"
            observations = []
            for record in group:
                timing = record["timing"]
                value = timing.get(field)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    continue
                if scope == "native" and (
                    timing.get("native_timing_enabled") is not True
                    or native_boundary is None
                    or timing.get("native_timing_boundary") != native_boundary
                    or native_clock is None
                    or timing.get("native_timing_clock") != native_clock
                    or not isinstance(timing.get("codec_input_bytes_per_iteration"), int)
                    or isinstance(timing["codec_input_bytes_per_iteration"], bool)
                    or timing["codec_input_bytes_per_iteration"] < 0
                ):
                    continue
                observations.append(record)
            complete = len(observations) == len(group)
            values = [_per_iteration(item, field) for item in observations] if complete else []
            result.update(
                _stats_fields(f"{scope}_{direction}_ns", values, policy=policy, seed=seed)
            )
            result[f"{scope}_{direction}_observation_count"] = len(observations)
            result[f"{scope}_{direction}_mb_per_second_micro"] = (
                decimal_divide(
                    sum(
                        int(item["timing"][
                            "codec_input_bytes_per_iteration" if scope == "native"
                            else "canonical_bytes_per_iteration"
                        ]) * int(item["timing"]["inner_iterations"])
                        for item in observations
                    ) * 1000,
                    sum(int(item["timing"][field]) for item in observations),
                ) if complete else None
            )
    native_complete = all(result[f"native_{direction}_observation_count"] == len(group)
                          for direction in ("encode", "decode"))
    result["native_timing_boundary"] = native_boundary if native_complete else None
    result["native_timing_clock"] = native_clock if native_complete else None
    result["codec_input_bytes_per_iteration"] = group[0]["timing"].get(
        "codec_input_bytes_per_iteration"
    )
    return result


def _summaries(
    run_path: Path,
    records: tuple[dict[str, Any], ...],
    tasks: dict[str, dict[str, Any]],
    eligibility: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    performance_ids = {
        row["run_id"] for row in eligibility if row["analysis"] == "PERFORMANCE" and row["eligible"]
    }
    resource_ids = {
        row["run_id"] for row in eligibility if row["analysis"] == "RESOURCE" and row["eligible"]
    }
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("run_id") not in performance_ids:
            continue
        task = tasks[str(record["task_id"])]
        key = (
            str(record["dataset_id"]),
            str(record["algorithm_id"]),
            str(record["config_id"]),
            str(record["execution_path_hash"]),
            str(task["profile_id"]),
            str(record["schema_version"]),
        )
        groups[key].append(record)
    dataset_provenance = _dataset_provenance(run_path)
    summaries: list[dict[str, Any]] = []
    for key, group in sorted(groups.items()):
        group.sort(key=lambda item: int(item["repetition_index"]))
        first = group[0]
        task = tasks[str(first["task_id"])]
        comparison = task["comparability"]
        semantic = comparison["semantic_document"]
        execution = task["execution"]
        accounting = first["accounting"]
        raw_bits_values = {int(item["accounting"]["canonical_raw_bits"]) for item in group}
        final_bits_values = {int(item["accounting"]["final_bits"]) for item in group}
        if len(raw_bits_values) != 1 or len(final_bits_values) != 1:
            raise StatisticsError(
                "eligible repetitions changed accounting size within one frozen execution group"
            )
        raw_bits = next(iter(raw_bits_values))
        final_bits = next(iter(final_bits_values))
        summary_group_identity = {
            "run_set_id": first["run_set_id"],
            "dataset_id": key[0],
            "algorithm_id": key[1],
            "config_id": key[2],
            "execution_path_hash": key[3],
            "profile_id": key[4],
            "run_record_schema": key[5],
        }
        summary_id = stable_id(
            "summary",
            {
                **summary_group_identity,
                "run_ids": [item["run_id"] for item in group],
            },
        )
        encode = [_per_iteration(item, "selected_encode_wall_ns") for item in group]
        decode = [_per_iteration(item, "selected_decode_wall_ns") for item in group]
        e2e = [_per_iteration(item, "e2e_wall_ns") for item in group]
        canonical_bytes = int(first["timing"]["canonical_bytes_per_iteration"])
        encode_total_ns = sum(int(item["timing"]["selected_encode_wall_ns"]) for item in group)
        decode_total_ns = sum(int(item["timing"]["selected_decode_wall_ns"]) for item in group)
        total_iterations = sum(int(item["timing"]["inner_iterations"]) for item in group)
        resource_group = [item for item in group if item["run_id"] in resource_ids]
        qualities = [_quality(item) for item in group]
        row: dict[str, Any] = {
            "schema_version": "tscb.summary-record.v2",
            "summary_id": summary_id,
            **summary_group_identity,
            "track": first["track"],
            "object_level": semantic.get("object_level"),
            "loss_mode": semantic.get("loss_mode"),
            "semantic_comparability_key": first["semantic_comparability_key"],
            "execution_comparability_key": first["execution_comparability_key"],
            "resource_profile_key": first["resource_profile_key"],
            "n": len(group),
            "repetition_indices": [item["repetition_index"] for item in group],
            "run_ids": [item["run_id"] for item in group],
            "input_sha256s": sorted({item["input_sha256"] for item in group}),
            "bitstream_sha256s": sorted({item["bitstream_sha256"] for item in group}),
            "source_artifact_id": execution.get("source_artifact_id"),
            "adapter_id": execution.get("adapter_id"),
            "binary_artifact_sha256": execution.get("artifact_sha256"),
            "environment_id": execution.get("environment_id"),
            **dataset_provenance.get(key[0], {}),
            "canonical_raw_bits": raw_bits,
            "serialized_bits": int(accounting["serialized_bits"]),
            "external_side_information_bits": int(accounting["external_side_information_bits"]),
            "final_bits": final_bits,
            "final_physical_bytes": int(accounting["final_physical_bytes"]),
            "size_ratio": decimal_divide(final_bits, raw_bits),
            "compression_factor": decimal_divide(raw_bits, final_bits),
            "semantic_encode_mb_per_second_micro": decimal_divide(
                canonical_bytes * total_iterations * 1000, encode_total_ns
            ),
            "semantic_decode_mb_per_second_micro": decimal_divide(
                canonical_bytes * total_iterations * 1000, decode_total_ns
            ),
            "resource_observation_count": len(resource_group),
        }
        row.update(_stats_fields("encode_ns", encode, policy=policy, seed=summary_id))
        row.update(_stats_fields("decode_ns", decode, policy=policy, seed=summary_id))
        row.update(_stats_fields("e2e_ns", e2e, policy=policy, seed=summary_id))
        row.update(_auxiliary_timing_fields(group, policy, summary_id))
        for metric in ("rmse", "mae", "max_ae", "psnr_range_db"):
            values = [value for item in qualities if (value := item[metric]) is not None]
            row.update(_stats_fields(metric, values, policy=policy, seed=summary_id))
        resource_metrics = {
            "process_cpu_seconds": "process_total_seconds",
            "peak_memory_bytes": "peak_process_rss_bytes",
            "incremental_peak_memory_bytes": "incremental_peak_memory_bytes",
            "cpu_core_seconds_per_gb": "cpu_core_seconds_per_gb",
        }
        for prefix, field in resource_metrics.items():
            values: list[float] = []
            for item in resource_group:
                value = _finite_number(item["resources"].get(field))
                if value is not None:
                    if prefix == "process_cpu_seconds":
                        value /= int(item["timing"]["inner_iterations"])
                    elif prefix == "cpu_core_seconds_per_gb":
                        process_seconds = _finite_number(
                            item["resources"].get("process_total_seconds")
                        )
                        canonical_bytes = int(item["timing"]["canonical_bytes_per_iteration"])
                        if process_seconds is None or canonical_bytes == 0:
                            continue
                        value = (
                            process_seconds
                            / int(item["timing"]["inner_iterations"])
                            / (canonical_bytes / 1_000_000_000)
                        )
                    values.append(value)
            row.update(_stats_fields(prefix, values, policy=policy, seed=summary_id))
        summaries.append(row)
    return summaries


def _corpus_summaries(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in summaries:
        key = (
            str(row["algorithm_id"]),
            str(row["config_id"]),
            str(row["execution_path_hash"]),
            str(row["profile_id"]),
            str(row["semantic_comparability_key"]),
            str(row["execution_comparability_key"]),
            str(row["resource_profile_key"]),
        )
        groups[key].append(row)
    result: list[dict[str, Any]] = []
    for key, rows in sorted(groups.items()):
        rows.sort(key=lambda item: str(item["dataset_id"]))
        raw_bits = sum(int(item["canonical_raw_bits"]) for item in rows)
        final_bits = sum(int(item["final_bits"]) for item in rows)
        canonical_bytes = sum((int(item["canonical_raw_bits"]) + 7) // 8 for item in rows)
        encode_ns = sum(float(item["encode_ns_median"]) for item in rows)
        decode_ns = sum(float(item["decode_ns_median"]) for item in rows)
        factors = [
            float(item["compression_factor"])
            for item in rows
            if item.get("compression_factor") is not None and float(item["compression_factor"]) > 0
        ]
        peak_values = [
            float(item["peak_memory_bytes_median"])
            for item in rows
            if item.get("peak_memory_bytes_median") is not None
        ]
        cpu_values = [
            float(item["process_cpu_seconds_median"])
            for item in rows
            if item.get("process_cpu_seconds_median") is not None
        ]
        identity = {
            "algorithm_id": key[0],
            "config_id": key[1],
            "execution_path_hash": key[2],
            "profile_id": key[3],
            "semantic_comparability_key": key[4],
            "execution_comparability_key": key[5],
            "resource_profile_key": key[6],
            "summary_ids": [item["summary_id"] for item in rows],
        }
        result.append(
            {
                "schema_version": "tscb.corpus-summary-record.v2",
                "corpus_summary_id": stable_id("corpus-summary", identity),
                **identity,
                "dataset_count": len(rows),
                "dataset_ids": [item["dataset_id"] for item in rows],
                "summary_ids": [item["summary_id"] for item in rows],
                "micro_size_ratio": decimal_divide(final_bits, raw_bits),
                "micro_compression_factor": decimal_divide(raw_bits, final_bits),
                "geometric_mean_compression_factor": (
                    None
                    if len(factors) != len(rows)
                    else format(
                        math.exp(sum(math.log(item) for item in factors) / len(factors)),
                        ".17g",
                    )
                ),
                "micro_encode_mb_per_second": decimal_divide(canonical_bytes * 1000, encode_ns),
                "micro_decode_mb_per_second": decimal_divide(canonical_bytes * 1000, decode_ns),
                "corpus_peak_memory_bytes_max": None if not peak_values else max(peak_values),
                "corpus_peak_memory_bytes_p95": (
                    None if not peak_values else percentile(peak_values, 0.95)
                ),
                "corpus_cpu_core_seconds_per_gb": (
                    None
                    if len(cpu_values) != len(rows) or canonical_bytes == 0
                    else decimal_divide(sum(cpu_values), canonical_bytes / 1_000_000_000)
                ),
            }
        )
        for scope in ("core", "pipeline", "native"):
            for direction in ("encode", "decode"):
                times = [item.get(f"{scope}_{direction}_ns_median") for item in rows]
                sizes = [
                    item.get("codec_input_bytes_per_iteration") if scope == "native"
                    else (int(item["canonical_raw_bits"]) + 7) // 8
                    for item in rows
                ]
                complete = all(value is not None for value in times + sizes)
                result[-1][f"micro_{scope}_{direction}_mb_per_second"] = (
                    decimal_divide(sum(sizes) * 1000, sum(times)) if complete else None
                )
    return result


def _coverage(
    tasks: dict[str, dict[str, Any]], records: tuple[dict[str, Any], ...]
) -> list[dict[str, Any]]:
    records_by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_task[str(record.get("task_id"))].append(record)
    result: list[dict[str, Any]] = []
    for task_id, task in sorted(tasks.items()):
        observed = records_by_task.get(task_id, [])
        status_counts = Counter(str(item.get("status", "UNSPECIFIED")) for item in observed)
        pass_repetitions = status_counts.get("PASS", 0)
        expected_repetitions = int(
            ((task.get("comparability") or {}).get("execution_document") or {}).get(
                "repetitions", 1
            )
        )
        failed_repetitions = len(observed) - pass_repetitions
        if pass_repetitions == expected_repetitions and failed_repetitions == 0:
            final_status = "PASS"
        elif pass_repetitions:
            final_status = "PARTIAL_PASS"
        elif observed:
            final_status = str(observed[-1].get("status", "UNSPECIFIED"))
        else:
            final_status = "NOT_EXECUTED"
        if final_status == "PASS":
            category = "PASS"
        elif final_status in {"UNSUPPORTED", "ISA_UNSUPPORTED", "BUILD_UNAVAILABLE"}:
            category = "UNSUPPORTED"
        elif final_status == "OOM":
            category = "OOM"
        elif final_status == "TIMEOUT":
            category = "TIMEOUT"
        else:
            category = "FAIL"
        result.append(
            {
                "schema_version": "tscb.coverage-record.v2",
                "task_id": task_id,
                "dataset_id": task.get("dataset_id"),
                "algorithm_id": task.get("algorithm_id"),
                "config_id": task.get("config_id"),
                "track": task.get("track"),
                "profile_id": task.get("profile_id"),
                "planned_status": task.get("status"),
                "planned_reason_code": task.get("reason_code"),
                "final_status": final_status,
                "coverage_category": category,
                "record_count": len(observed),
                "expected_repetitions": expected_repetitions,
                "pass_repetitions": pass_repetitions,
                "failed_repetitions": failed_repetitions,
                "status_counts": dict(sorted(status_counts.items())),
                "run_ids": [item.get("run_id") for item in observed],
            }
        )
    return result


def _comparability_groups(tasks: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for task_id, task in sorted(tasks.items()):
        comparison = task.get("comparability") or {}
        key = (
            str(comparison.get("semantic_key")),
            str(comparison.get("execution_key")),
            str(comparison.get("resource_key")),
        )
        documents = {
            "semantic_document": comparison.get("semantic_document") or {},
            "execution_document": comparison.get("execution_document") or {},
            "resource_document": comparison.get("resource_document") or {},
        }
        if key in groups:
            existing = groups[key]
            if any(existing[name] != document for name, document in documents.items()):
                raise StatisticsError("one comparability key maps to conflicting documents")
            existing["task_ids"].append(task_id)
            continue
        semantic = documents["semantic_document"]
        execution = documents["execution_document"]
        resource = documents["resource_document"]
        groups[key] = {
            "schema_version": "tscb.comparability-group.v2",
            "semantic_comparability_key": key[0],
            "execution_comparability_key": key[1],
            "resource_profile_key": key[2],
            **documents,
            "semantic_context": "; ".join(
                f"{name}={semantic.get(name, 'UNSPECIFIED')}"
                for name in (
                    "track",
                    "object_level",
                    "loss_mode",
                    "topology",
                    "value_coupling_mode",
                    "adapter_semantic_class",
                )
            ),
            "execution_context": "; ".join(
                f"{name}={execution.get(name, 'UNSPECIFIED')}"
                for name in (
                    "timing_scope",
                    "actual_isa",
                    "device",
                    "threads",
                    "processes",
                    "fallback_used",
                    "adapter_boundary",
                )
            ),
            "resource_context": "; ".join(
                f"{name}={resource.get(name, 'UNSPECIFIED')}"
                for name in (
                    "resource_scope",
                    "memory_accounting_scope",
                    "counter_method",
                    "energy_method",
                    "sampling_policy",
                )
            ),
            "task_ids": [task_id],
        }
    result = list(groups.values())
    for row in result:
        row["task_ids"].sort()
        row["task_count"] = len(row["task_ids"])
    return sorted(
        result,
        key=lambda item: (
            item["semantic_comparability_key"],
            item["execution_comparability_key"],
            item["resource_profile_key"],
        ),
    )


def _pareto_rows(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    views = (
        (
            "SPACE_ENCODE",
            "execution_comparability_key",
            {"final_bits": "MIN", "encode_ns_median": "MIN"},
        ),
        (
            "SPACE_DECODE",
            "execution_comparability_key",
            {"final_bits": "MIN", "decode_ns_median": "MIN"},
        ),
        (
            "SPACE_MEMORY",
            "resource_profile_key",
            {"final_bits": "MIN", "peak_memory_bytes_median": "MIN"},
        ),
        (
            "RATE_DISTORTION",
            "semantic_comparability_key",
            {"final_bits": "MIN", "rmse_median": "MIN"},
        ),
    )
    result: list[dict[str, Any]] = []
    for view, key_name, directions in views:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in summaries:
            groups[(str(row["dataset_id"]), str(row[key_name]), str(row["profile_id"]))].append(row)
        for group_key, rows in sorted(groups.items()):
            candidates: dict[str, dict[str, float]] = {}
            for row in rows:
                metrics = {name: _finite_number(row.get(name)) for name in directions}
                if all(value is not None for value in metrics.values()):
                    candidates[str(row["summary_id"])] = {
                        name: float(value) for name, value in metrics.items() if value is not None
                    }
            if not candidates:
                continue
            front, dominated_by = pareto_front(candidates, directions)
            for summary_id, metrics in sorted(candidates.items()):
                result.append(
                    {
                        "schema_version": "tscb.pareto-record.v2",
                        "view": view,
                        "dataset_id": group_key[0],
                        "comparison_key_type": key_name,
                        "comparison_key": group_key[1],
                        "profile_id": group_key[2],
                        "summary_id": summary_id,
                        "objectives": metrics,
                        "directions": directions,
                        "pareto_optimal": summary_id in front,
                        "dominated_by_summary_ids": list(dominated_by[summary_id]),
                    }
                )
    return result


def _ranking_rows(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    definitions = (
        ("compression_factor", "MAX", "semantic_comparability_key"),
        ("semantic_encode_mb_per_second_micro", "MAX", "execution_comparability_key"),
        ("semantic_decode_mb_per_second_micro", "MAX", "execution_comparability_key"),
        ("peak_memory_bytes_median", "MIN", "resource_profile_key"),
    )
    result: list[dict[str, Any]] = []
    for metric, direction, key_name in definitions:
        groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in summaries:
            groups[(str(row["dataset_id"]), str(row[key_name]), str(row["profile_id"]))].append(row)
        for key, rows in sorted(groups.items()):
            values = {
                str(row["summary_id"]): value
                for row in rows
                if (value := _finite_number(row.get(metric))) is not None
            }
            if not values:
                continue
            ranks = rank_values(values, direction=direction)
            for summary_id, value in sorted(values.items()):
                result.append(
                    {
                        "schema_version": "tscb.ranking-record.v2",
                        "dataset_id": key[0],
                        "comparison_key_type": key_name,
                        "comparison_key": key[1],
                        "profile_id": key[2],
                        "metric": metric,
                        "direction": direction,
                        "summary_id": summary_id,
                        "value": value,
                        "rank": ranks[summary_id],
                        "tie_method": "DENSE_EXACT",
                        "coverage_used_as_score": False,
                    }
                )
    return result


def analyze_run_set(run_path: Path, policy: dict[str, Any]) -> AnalysisBundle:
    """Analyze one frozen run set without calling codecs or mutating raw evidence."""

    run_path = run_path.resolve()
    if int(policy.get("bootstrap_samples", 0)) < 100:
        raise StatisticsError("bootstrap_samples must be at least 100")
    try:
        confidence = Decimal(str(policy.get("confidence_level")))
    except InvalidOperation as error:
        raise StatisticsError("confidence_level must be decimal") from error
    if not Decimal("0.5") <= confidence < Decimal(1):
        raise StatisticsError("confidence_level must be in [0.5, 1)")
    task_path = run_path / "task_plan.jsonl"
    raw_path = run_path / "run_components.jsonl"
    provenance_paths = {
        "run-set.json": run_path / "run-set.json",
        "frozen_config.json": run_path / "frozen_config.json",
        "environment.json": run_path / "environment.json",
        "codec_registry_snapshot.json": run_path / "codec_registry_snapshot.json",
        "source_registry_snapshot.json": run_path / "source_registry_snapshot.json",
    }
    missing_provenance = [name for name, path in provenance_paths.items() if not path.is_file()]
    if missing_provenance:
        raise StatisticsError(
            "required frozen provenance is missing: " + ", ".join(missing_provenance)
        )
    tasks_raw = _read_jsonl(task_path)
    records = _read_jsonl(raw_path)
    tasks = {str(item.get("task_id")): item for item in tasks_raw}
    if len(tasks) != len(tasks_raw):
        raise StatisticsError("frozen task universe contains duplicate TaskIDs")
    run_ids = [str(item.get("run_id")) for item in records]
    if len(set(run_ids)) != len(run_ids):
        raise StatisticsError("raw evidence contains duplicate RunIDs")
    dataset_provenance = _dataset_provenance(run_path)
    source_snapshot = _read_json(run_path / "source_registry_snapshot.json")
    source_artifact_ids = {
        str(item.get("source_artifact_id")) for item in source_snapshot.get("sources", [])
    }
    eligibility, _ = _eligibility(
        run_path,
        records,
        tasks,
        dataset_provenance,
        source_artifact_ids,
    )
    summaries = _summaries(run_path, records, tasks, eligibility, policy)
    coverage = _coverage(tasks, records)
    source_hashes = {
        "task_plan.jsonl": _sha256_file(task_path),
        "run_components.jsonl": _sha256_file(raw_path),
        **{name: _sha256_file(path) for name, path in provenance_paths.items()},
    }
    for path in sorted((run_path / "datasets").glob("*/preparation-record.json")):
        source_hashes[str(path.relative_to(run_path))] = _sha256_file(path)
    return AnalysisBundle(
        policy=dict(policy),
        source_hashes=source_hashes,
        eligibility=tuple(eligibility),
        summaries=tuple(summaries),
        corpus_summaries=tuple(_corpus_summaries(summaries)),
        coverage=tuple(coverage),
        comparability_groups=tuple(_comparability_groups(tasks)),
        pareto=tuple(_pareto_rows(summaries)),
        rankings=tuple(_ranking_rows(summaries)),
    )
