"""Shared raw-record, statistics, provenance and duration audit helpers."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter
from decimal import Decimal
from pathlib import Path

import numpy as np

from tscompbench.ids import stable_id

ROOT = Path(__file__).resolve().parents[1]


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


COMPONENTS = (
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


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def report_source_path(run: Path, filename: str) -> Path:
    if filename.startswith("implementation/"):
        return ROOT / "src/tscompbench" / filename.removeprefix("implementation/")
    return run / filename


def audit_raw_projection_and_coverage(run: Path, tasks: list[dict], records: list[dict]) -> None:
    with (run / "runs.csv").open(newline="") as file:
        projection = list(csv.DictReader(file))
    require(len(projection) == len(records), "raw CSV dropped attempts")
    for flat, record in zip(projection, records, strict=True):
        for field in (
            "run_id",
            "task_id",
            "dataset_id",
            "algorithm_id",
            "config_id",
            "execution_path_hash",
            "status",
            "reason_code",
            "eligibility",
            "record_kind",
            "repetition_index",
            "bitstream_sha256",
            "finalize_bytes",
        ):
            value = record[field]
            require(flat[field] == ("" if value is None else str(value)), "raw CSV identity drift")
        for group, fields in (
            (
                "accounting",
                (
                    "canonical_raw_bits",
                    "serialized_bits",
                    "final_bits",
                    "final_physical_bytes",
                    "external_side_information_bits",
                ),
            ),
            (
                "timing",
                (
                    "inner_iterations",
                    "selected_encode_wall_ns",
                    "selected_decode_wall_ns",
                    "core_encode_wall_ns",
                    "core_decode_wall_ns",
                    "pipeline_encode_wall_ns",
                    "pipeline_decode_wall_ns",
                    "native_encode_wall_ns",
                    "native_decode_wall_ns",
                ),
            ),
        ):
            for field in fields:
                value = (record[group] or {}).get(field)
                require(flat[field] == ("" if value is None else str(value)), "raw CSV value drift")
    report = json.loads((run / "report/report.json").read_text())
    coverage = report["coverage"]
    require(
        len(coverage) == len(tasks)
        and {item["task_id"] for item in coverage} == {task["task_id"] for task in tasks},
        "coverage dropped or duplicated tasks",
    )
    for item in coverage:
        attempts = [record for record in records if record["task_id"] == item["task_id"]]
        require(
            item["record_count"] == len(attempts)
            and set(item["run_ids"]) == {r["run_id"] for r in attempts}
            and (item["status_counts"] == dict(Counter(r["status"] for r in attempts))),
            "coverage does not describe the actual attempt universe",
        )


def audit_independent_statistics(summary: dict, accepted: list[dict], policy: dict) -> None:
    accepted.sort(key=lambda record: record["repetition_index"])
    for prefix in (
        "core_encode",
        "core_decode",
        "pipeline_encode",
        "pipeline_decode",
        "native_encode",
        "native_decode",
    ):
        field = prefix + "_wall_ns"
        values = [record["timing"][field] for record in accepted]
        names = ("mean", "median", "p25", "p75", "sd", "cv", "ci_low", "ci_high")
        if any(value is None for value in values):
            require(
                all(summary[prefix + "_ns_" + name] is None for name in names)
                and summary[prefix + "_observation_count"] == 0
                and (summary[prefix + "_mb_per_second_micro"] is None),
                "null native summary fabricated",
            )
            continue
        per_object = [
            value / record["timing"]["inner_iterations"]
            for value, record in zip(values, accepted, strict=True)
        ]
        mean, sd = (statistics.mean(per_object), statistics.stdev(per_object))
        seed = hashlib.sha256((summary["summary_id"] + ":" + prefix + "_ns").encode()).digest()
        generator = random.Random(int.from_bytes(seed[:8], "big"))
        medians = [
            statistics.median(generator.choices(per_object, k=len(per_object)))
            for _ in range(policy["bootstrap_samples"])
        ]
        alpha = (Decimal(1) - Decimal(policy["confidence_level"])) / 2
        expected = {
            "mean": mean,
            "median": statistics.median(per_object),
            "sd": sd,
            "p25": float(np.quantile(per_object, 0.25)),
            "p75": float(np.quantile(per_object, 0.75)),
            "cv": sd / abs(mean),
            "ci_low": float(np.quantile(medians, float(alpha))),
            "ci_high": float(np.quantile(medians, float(1 - alpha))),
        }
        for name, value in expected.items():
            require(
                math.isclose(summary[prefix + "_ns_" + name], value, rel_tol=1e-12),
                "independently recomputed summary differs: " + prefix + "/" + name,
            )
        rate = (
            sum(
                r["timing"]["canonical_bytes_per_iteration"] * r["timing"]["inner_iterations"]
                for r in accepted
            )
            * 1000
            / sum(values)
        )
        require(
            summary[prefix + "_observation_count"] == len(accepted)
            and math.isclose(float(summary[prefix + "_mb_per_second_micro"]), rate, rel_tol=1e-12),
            "micro throughput is not total bytes / total time",
        )


def audit_stage_plan(task: dict, manifest) -> None:
    declared = [
        dict(stage, enabled=True) for stage in manifest.document["semantics"]["preprocess_stages"]
    ]
    require(
        task["preprocess"]
        == {
            "schema_version": "tscb.preprocess-plan.v2",
            "stages": declared,
            "preprocess_plan_id": stable_id("preprocess-plan", declared),
            "semantic_class": manifest.document["semantics"]["preprocess_class"],
        },
        "declared stage plan differs",
    )


def formal_direction_durations_satisfied(timing: dict, minimum_ns: int = 1000000000) -> bool:
    """Audit actual selected nanoseconds independently of the recorded PASS flag."""
    return timing.get("min_duration_satisfied") is True and all(
        type(timing.get(f"selected_{direction}_wall_ns")) is int
        and timing[f"selected_{direction}_wall_ns"] >= minimum_ns
        for direction in ("encode", "decode")
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_run_provenance(run: Path, manifest, source: dict, runtime_digest: str) -> None:
    codec_snapshot = json.loads((run / "codec_registry_snapshot.json").read_text())
    matches = [item for item in codec_snapshot["codecs"] if item["key"] == manifest.key]
    assert len(matches) == 1
    assert matches[0]["algorithm_id"] == manifest.algorithm_id
    assert matches[0]["manifest"] == manifest.document
    source_snapshot = json.loads((run / "source_registry_snapshot.json").read_text())
    matches = [
        item for item in source_snapshot["sources"] if item["identity"] == source["identity"]
    ]
    assert len(matches) == 1
    assert matches[0] == source
    tasks = [json.loads(line) for line in (run / "task_plan.jsonl").read_text().splitlines()]
    assert tasks
    for task in tasks:
        assert task["algorithm_id"] == manifest.algorithm_id
        assert task["execution"]["artifact_sha256"] == runtime_digest
        assert task["execution"]["actual_isa"] == "SSE4_1"
        assert task["execution"]["fallback_used"] is False
    for layer in range(2, 6):
        assert list(run.glob(f"layer{layer}-*.json"))


def audit_summary(run: Path) -> None:
    """Recompute basic per-repetition statistics independently from raw evidence."""
    records = [json.loads(line) for line in (run / "run_components.jsonl").read_text().splitlines()]
    report = json.loads((run / "report/report.json").read_text())
    assert report["source_hashes"]["run_components.jsonl"] == sha(run / "run_components.jsonl")
    for filename, digest in report["derived_artifact_hashes"].items():
        assert sha(run / filename) == digest
    accepted = [r for r in records if r["eligibility"]]
    assert report["eligible_run_count"] == len(accepted)
    covered_ids = []
    for summary in report["summaries"]:
        selected = [
            r
            for r in accepted
            if r["dataset_id"] == summary["dataset_id"] and r["config_id"] == summary["config_id"]
        ]
        assert len(selected) == summary["n"] >= 10
        assert set(summary["run_ids"]) == {r["run_id"] for r in selected}
        covered_ids += summary["run_ids"]
        assert set(summary["bitstream_sha256s"]) == {r["bitstream_sha256"] for r in selected}
        assert {r["accounting"]["final_bits"] for r in selected} == {summary["final_bits"]}
        for prefix, field in (
            ("encode", "selected_encode_wall_ns"),
            ("decode", "selected_decode_wall_ns"),
            ("core_encode", "core_encode_wall_ns"),
            ("core_decode", "core_decode_wall_ns"),
        ):
            values = [r["timing"][field] / r["timing"]["inner_iterations"] for r in selected]
            assert math.isclose(
                summary[prefix + "_ns_mean"], statistics.mean(values), rel_tol=1e-12
            )
            assert math.isclose(
                summary[prefix + "_ns_median"], statistics.median(values), rel_tol=1e-12
            )
            assert math.isclose(summary[prefix + "_ns_sd"], statistics.stdev(values), rel_tol=1e-12)
    assert Counter(covered_ids) == Counter(r["run_id"] for r in accepted)
