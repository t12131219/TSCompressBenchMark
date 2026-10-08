"""Audit current P2 stage, native safety and complete five-layer run evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from itertools import product
from pathlib import Path

from streamvbyte_audit_common import audit_run_provenance, audit_source, audit_summary, formal_direction_durations_satisfied

from tscompbench.adapters.factory import create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.datasets.canonical import read_canonical
from tscompbench.execution.routing import route_canonical_artifact
from tscompbench.measurement.contracts import decimal_rate
from tscompbench.preprocess.runtime import validate_pipeline_stages
from tscompbench.preprocess.streamvbyte import EXECUTOR_ID, STAGE_SPEC
from tscompbench.preprocess.streamvbyte_modern import EXECUTOR_ID as MODERN_EXECUTOR_ID
from tscompbench.preprocess.streamvbyte_modern import STAGE_SPEC as MODERN_STAGE_SPEC

ROOT = Path(__file__).resolve().parents[1]
KEY = "delta-zigzag-streamvbyte64"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def audit(formal_name: str, qualification_name: str, key: str = KEY) -> dict:
    if key not in (KEY, "delta-zigzag-streamvbyte-modern64"):
        raise ValueError("unknown reviewed P2 key")
    modern = "modern" in key
    executor_id = MODERN_EXECUTOR_ID if modern else EXECUTOR_ID
    stage_spec = MODERN_STAGE_SPEC if modern else STAGE_SPEC
    for name in (formal_name, qualification_name):
        if Path(name).name != name:
            raise ValueError("run ID must be a single path component")
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(key)
    checked = audit_source(ROOT, registry, manifest)
    runtime_digest = checked["runtime_digest"]
    adapter = create_adapter(ROOT, manifest)
    document = manifest.document
    assert document["classification"]["object_level"] == "P2_PIPELINE"
    assert document["semantics"]["preprocess_class"] == "LOSSLESS_LAYOUT"
    assert document["semantics"]["preprocess_stages"] == stage_spec
    assert document["adapter"]["pipeline_executor_id"] == executor_id
    run = ROOT / "runs" / formal_name
    qualification = ROOT / "runs" / qualification_name
    for path in (run, qualification):
        audit_run_provenance(path, manifest, checked["source"], runtime_digest)
    formal = rows(run / "run_components.jsonl")
    qualified = rows(qualification / "run_components.jsonl")
    tasks = rows(run / "task_plan.jsonl")
    configs = {
        c["config_id"]: c["parameters"]
        for c in json.loads((run / "resolved_configs.json").read_text())["configs"]
    }
    qual_configs = {
        c["config_id"]: c["parameters"]
        for c in json.loads((qualification / "resolved_configs.json").read_text())["configs"]
    }
    assert len(formal) == 240 and len(tasks) == 12 and len(qualified) == 96
    assert len({record["run_id"] for record in formal}) == len(formal)
    assert all(record["status"] == "PASS" and not record["eligibility"] for record in qualified)
    assert {tuple(c[f"stage_{s}"] for s in "abc") for c in qual_configs.values()} == set(
        product((False, True), repeat=3)
    )
    assert {c["native_timing"] for c in qual_configs.values()} == {True, False}
    assert {c["stage_timing"] for c in qual_configs.values()} == {True, False}
    assert {
        tuple(c[f"stage_{s}"] for s in "abc") + (c["native_timing"], c["stage_timing"])
        for c in qual_configs.values()
    } == set(product((False, True), repeat=5))
    qual_tasks = rows(qualification / "task_plan.jsonl")
    assert len(qual_tasks) == 96
    for task in qual_tasks:
        preflight = json.loads(
            (qualification / "preflight" / (task["task_id"].split(":")[-1] + ".json")).read_text()
        )
        assert preflight["status"] == "PASS" and preflight["eligible_for_formal_repetitions"]
        assert preflight["diagnostics"]["preprocess_stage_validation"]["status"] == "PASS"
        config = qual_configs[task["config_id"]]
        assert all(
            stage["enabled"] == config[f"stage_{stage['stage_slot'].lower()}"]
            for stage in task["preprocess"]["stages"]
        )
    for task in tasks:
        assert task["algorithm_id"] == manifest.algorithm_id
        assert task["execution"]["artifact_sha256"] == runtime_digest
        assert task["execution"]["adapter_id"] == adapter.adapter_id
        assert task["execution"]["cpu_affinity"] == [0]
        assert (
            task["execution"]["actual_isa"] == "SSE4_1" and not task["execution"]["fallback_used"]
        )
        assert all(stage["enabled"] for stage in task["preprocess"]["stages"])
        reps = [record for record in formal if record["task_id"] == task["task_id"]]
        assert len(reps) == 20 and {r["repetition_index"] for r in reps} == set(range(20))
        assert sum(r["status"] == "PASS" and r["eligibility"] for r in reps) >= 10
        preflight = json.loads(
            (run / "preflight" / (task["task_id"].split(":")[-1] + ".json")).read_text()
        )
        assert preflight["status"] == "PASS" and preflight["eligible_for_formal_repetitions"]
        stage_validation = preflight["diagnostics"]["preprocess_stage_validation"]
        assert (
            stage_validation["status"] == "PASS" and stage_validation["executor_id"] == executor_id
        )
        assert stage_validation["checked_stages"] == list("ABCD")
        assert preflight["boundary"]["passed"]
        assert all(case["status"] == "PASS" for case in preflight["boundary"]["observations"])
    canonical = {
        item.metadata["dataset_id"]: item
        for item in (
            read_canonical(path, include_buffers=True)
            for path in (run / "datasets").glob("*/*.canonical.tscb")
        )
    }
    streams = {sha(path): path for path in run.rglob("*.bin")}
    for dataset_id, artifact_data in canonical.items():
        original = route_canonical_artifact(artifact_data, BenchmarkTrack.TIMESTAMP)
        assert validate_pipeline_stages(adapter, original, {})["status"] == "PASS"
        dataset_records = [record for record in formal if record["dataset_id"] == dataset_id]
        assert len(dataset_records) == 80
        assert len({record["bitstream_sha256"] for record in dataset_records}) == 1
        for record in dataset_records:
            assert record["input_sha256"] == original.input_sha256
        stream_hash = dataset_records[0]["bitstream_sha256"]
        assert stream_hash in streams
        decoder = adapter.create_session({})
        try:
            decoded = decoder.decompress(streams[stream_hash].read_bytes()).buffers[0].array
            assert decoded.dtype.str == "<i8"
            assert decoded.tobytes() == original.buffers[0].array.tobytes()
        finally:
            decoder.close()
    components = (
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
    for record in formal:
        assert record["correctness"]["status"] == "PASS"
        if record["status"] == "RESOURCE_PRESSURE":
            assert not record["eligibility"]
            assert record["reason_code"] == "SWAP_OBSERVED_DURING_FORMAL_REPETITION"
            assert record["resources"]["swap_observed"]
            assert record["resources"]["swap_observation_scope"] == "SYSTEM_VMSTAT"
        else:
            assert record["status"] == "PASS" and record["eligibility"]
        assert record["diagnostics"]["same_repetition_correctness_and_measurement"]
        assert record["finalize_bytes"] == 0
        ledger, timing = record["accounting"], record["timing"]
        flags = configs[record["config_id"]]
        assert ledger["canonical_raw_bits"] == timing["rows_per_iteration"] * 64
        assert (
            sum(ledger[k] for k in components)
            == ledger["final_bits"]
            == 8 * ledger["final_physical_bytes"]
        )
        assert (
            ledger["value_bits"]
            == ledger["external_side_information_bits"]
            == ledger["padding_bits"]
            == 0
        )
        assert formal_direction_durations_satisfied(timing)
        assert timing["canonical_bytes_per_iteration"] == timing["rows_per_iteration"] * 8
        assert (
            timing["native_input_bytes_per_iteration"]
            == max(0, timing["rows_per_iteration"] - 1) * 8
        )
        stages = timing["pipeline_stage_timings"]
        assert stages["scope"] == "ALL_INNER_ITERATIONS"
        for direction in ("encode", "decode"):
            observed = stages[direction]
            assert observed["inner_iterations"] == timing["inner_iterations"]
            assert observed["timing_enabled"] == flags["stage_timing"]
            if flags["stage_timing"]:
                assert all(
                    stage["wall_ns"] > 0
                    and stage["observation_count"] == timing["inner_iterations"]
                    for stage in observed["stages"].values()
                )
                assert (
                    sum(stage["wall_ns"] for stage in observed["stages"].values())
                    <= timing[f"core_{direction}_wall_ns"]
                )
            else:
                assert all(
                    stage["wall_ns"] is None and stage["observation_count"] == 0
                    for stage in observed["stages"].values()
                )
            if flags["native_timing"]:
                assert (
                    0 < timing[f"native_{direction}_wall_ns"] <= timing[f"core_{direction}_wall_ns"]
                )
                assert timing[f"native_{direction}_mb_per_second"] == decimal_rate(
                    timing["native_input_bytes_per_iteration"] * timing["inner_iterations"],
                    timing[f"native_{direction}_wall_ns"],
                    scale=1_000_000,
                )
            else:
                assert (
                    timing[f"native_{direction}_wall_ns"]
                    is timing[f"native_{direction}_mb_per_second"]
                    is None
                )
        assert (
            sum(stage["final_contribution_bits"] for stage in stages["encode"]["stages"].values())
            == ledger["final_bits"]
        )
    warmups = [json.loads(path.read_text()) for path in (run / "warmup").glob("*.json")]
    assert len(warmups) == 12
    assert all(
        w["threshold_satisfied"]
        and w["completed_iterations"] >= 3
        and w["elapsed_wall_ns"] >= 500_000_000
        for w in warmups
    )
    report = json.loads((run / "report/report.json").read_text())
    eligible_count = sum(record["eligibility"] for record in formal)
    assert report["eligible_run_count"] == eligible_count
    assert report["task_count"] == report["summary_count"] == 12
    assert all(row["n"] >= 10 for row in report["summaries"])
    audit_summary(run)
    for layer in range(2, 6):
        assert list(run.glob(f"layer{layer}-*.json"))
    for table in (
        "summary.csv",
        "pipeline_stages.csv",
        "coverage.csv",
        "eligibility.csv",
        "ranking.csv",
        "pareto.csv",
    ):
        assert (run / table).is_file()
    with (run / "pipeline_stages.csv").open(newline="") as handle:
        stage_summary = list(csv.DictReader(handle))
    assert len(stage_summary) == 12 * 8
    summary_counts = {
        (row["dataset_id"], row["config_id"]): row["n"] for row in report["summaries"]
    }
    assert all(
        int(row["observation_count"]) in {0, summary_counts[(row["dataset_id"], row["config_id"])]}
        for row in stage_summary
    )
    prior_evidence = {}
    if not modern:
        prior = ROOT / "runs/delta-zigzag-streamvbyte64-formal-20261007-1"
        prior_records = rows(prior / "run_components.jsonl")
        assert len(prior_records) == 120
        assert any(record["status"] == "RESOURCE_PRESSURE" for record in prior_records)
        assert (prior / "report/report.json").is_file()
        prior_evidence = {
            "prior_pressure_run": prior.name,
            "prior_raw_sha256": sha(prior / "run_components.jsonl"),
        }
    return {
        "status": "PASS",
        "codec_key": key,
        "object_level": "P2_PIPELINE",
        "algorithm_id": manifest.algorithm_id,
        "source_artifact_id": manifest.source_artifact_id,
        "executor_id": executor_id,
        "formal_run": formal_name,
        "qualification_run": qualification_name,
        "eligible_repetitions": eligible_count,
        "formal_attempts": len(formal),
        "resource_pressure_attempts": len(formal) - eligible_count,
        **prior_evidence,
        "qualification_configs": 96,
        "native_timing_values": [True, False],
        "stage_timing_values": [True, False],
        "datasets": ["etth1", "exchange_rate", "weather"],
        "raw_components_sha256": sha(run / "run_components.jsonl"),
        "report_id": report["report_id"],
        "full_workbook_source_variant_parity": (
            "MODERN_1234_ONLY_OTHER_API_VARIANTS_PENDING"
            if modern
            else "NOT_CLAIMED_LZBENCH_FROZEN_VARIANT"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formal_run_set_id")
    parser.add_argument("qualification_run_set_id")
    parser.add_argument("--key", choices=(KEY, "delta-zigzag-streamvbyte-modern64"), default=KEY)
    args = parser.parse_args()
    result = audit(args.formal_run_set_id, args.qualification_run_set_id, args.key)
    name = "streamvbyte-modern" if "modern" in args.key else "streamvbyte"
    path = ROOT / f"build/source-audits/{name}-pipeline-five-layer-audit.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
