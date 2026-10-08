"""Cross-check actual Stream VByte P0 five-layer evidence; P2 is separate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from streamvbyte_audit_common import audit_run_provenance, audit_source, audit_summary, formal_direction_durations_satisfied

from tscompbench.adapters.factory import create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets.canonical import read_canonical

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("formal_run_set_id")
    parser.add_argument("qualification_run_set_id")
    parser.add_argument(
        "--key", choices=("streamvbyte-u32", "streamvbyte-modern-u32"), default="streamvbyte-u32"
    )
    args = parser.parse_args()
    for name in (args.formal_run_set_id, args.qualification_run_set_id):
        if Path(name).name != name:
            raise ValueError("run set ID must be a single path component")
    run = ROOT / "runs" / args.formal_run_set_id
    qualification = ROOT / "runs" / args.qualification_run_set_id
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(args.key)
    checked = audit_source(ROOT, registry, manifest)
    runtime_digest = checked["runtime_digest"]
    for path in (run, qualification):
        audit_run_provenance(path, manifest, checked["source"], runtime_digest)
    records = rows(run / "run_components.jsonl")
    assert len(records) == 40 and len({r["run_id"] for r in records}) == 40
    tasks = rows(run / "task_plan.jsonl")
    assert len(tasks) == 2
    resolved = json.loads((run / "resolved_configs.json").read_text())
    assert {r["parameters"]["native_timing"] for r in resolved["configs"]} == {True, False}
    components = [
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
    ]
    for task in tasks:
        assert task["algorithm_id"] == manifest.algorithm_id
        assert task["execution"]["artifact_sha256"] == runtime_digest
        assert task["execution"]["adapter_id"] == create_adapter(ROOT, manifest).adapter_id
        assert task["execution"]["cpu_affinity"] == [0]
        assert (
            task["execution"]["actual_isa"] == "SSE4_1" and not task["execution"]["fallback_used"]
        )
        observed = [r for r in records if r["task_id"] == task["task_id"]]
        assert len(observed) == 20 and {r["repetition_index"] for r in observed} == set(range(20))
        assert sum(r["status"] == "PASS" and r["eligibility"] for r in observed) >= 10
        assert {r["execution_path_hash"] for r in observed} == {
            task["execution"]["execution_path_hash"]
        }
        preflight = json.loads(
            (run / "preflight" / (task["task_id"].split(":")[-1] + ".json")).read_text()
        )
        assert preflight["status"] == "PASS" and preflight["eligible_for_formal_repetitions"]
        boundary = preflight["boundary"]
        assert boundary["passed"] and all(
            item["status"] == "PASS" for item in boundary["observations"]
        )
    assert len({r["bitstream_sha256"] for r in records}) == 1
    assert len({r["input_sha256"] for r in records}) == 1
    for record in records:
        assert record["correctness"]["status"] == "PASS"
        if record["status"] == "RESOURCE_PRESSURE":
            assert not record["eligibility"]
            assert record["reason_code"] == "SWAP_OBSERVED_DURING_FORMAL_REPETITION"
            assert record["resources"]["swap_observed"]
            assert record["resources"]["swap_observation_scope"] == "SYSTEM_VMSTAT"
        else:
            assert record["status"] == "PASS" and record["eligibility"]
        assert record["diagnostics"]["same_repetition_correctness_and_measurement"]
        timing = record["timing"]
        assert formal_direction_durations_satisfied(timing)
        for operation in ("encode", "decode"):
            assert (
                0 < timing[f"core_{operation}_wall_ns"] <= timing[f"pipeline_{operation}_wall_ns"]
            )
            if timing["native_timing_enabled"]:
                assert (
                    0 < timing[f"native_{operation}_wall_ns"] <= timing[f"core_{operation}_wall_ns"]
                )
                assert timing["native_timing_boundary"] == "CODEC_API_ONLY_V1"
                assert timing["native_timing_clock"] == "CLOCK_MONOTONIC"
            else:
                assert timing[f"native_{operation}_wall_ns"] is None
                assert timing[f"native_{operation}_mb_per_second"] is None
        ledger = record["accounting"]
        assert (
            sum(ledger[k] for k in components) == ledger["serialized_bits"] == ledger["final_bits"]
        )
        assert ledger["final_bits"] == 8 * ledger["final_physical_bytes"]
        assert ledger["canonical_raw_bits"] == 8193 * 32
        assert (
            ledger["timestamp_bits"]
            == ledger["padding_bits"]
            == ledger["external_side_information_bits"]
            == 0
        )
        assert record["finalize_bytes"] == 0
        telemetry = record["diagnostics"]["codec_telemetry"]
        assert telemetry["scope"] == "LAST_INNER_ITERATION"
        assert telemetry["observed_iteration_index"] == timing["inner_iterations"] - 1
        for direction in ("encode", "decode"):
            assert telemetry[direction]["internal_padding_bytes"] == 16
            assert telemetry[direction]["padding_stream_bits"] == 0
    (canonical_path,) = (run / "datasets").glob("*/*.canonical.tscb")
    canonical = read_canonical(canonical_path, include_buffers=True)
    assert canonical.metadata["dataset_id"] == records[0]["dataset_id"]
    files = [p for p in run.rglob("*.bin") if sha(p) == records[0]["bitstream_sha256"]]
    assert files and files[0].stat().st_size == records[0]["accounting"]["final_physical_bytes"]
    session = create_adapter(ROOT, manifest).create_session({})
    try:
        decoded = session.decompress(files[0].read_bytes()).buffers[0].array
        assert decoded.dtype.str == "<u4" and decoded.size == 8193
        (expected,) = canonical.buffers.values()
        assert decoded.tobytes() == expected
    finally:
        session.close()
    warmups = [json.loads(p.read_text()) for p in (run / "warmup").glob("*.json")]
    assert len(warmups) == 2
    assert all(
        w["threshold_satisfied"]
        and w["completed_iterations"] >= 3
        and w["elapsed_wall_ns"] >= 500_000_000
        for w in warmups
    )
    qual = rows(qualification / "run_components.jsonl")
    assert len(qual) == 2 and all(r["status"] == "PASS" and not r["eligibility"] for r in qual)
    report = json.loads((run / "report/report.json").read_text())
    eligible_count = sum(record["eligibility"] for record in records)
    assert (
        report["eligible_run_count"] == eligible_count
        and report["summary_count"] == report["task_count"] == 2
    )
    assert all(row["n"] >= 10 for row in report["summaries"])
    audit_summary(run)
    with (run / "summary.csv").open(newline="") as stream:
        summaries = list(csv.DictReader(stream))
    assert len(summaries) == 2
    for filename in (
        "eligibility.csv",
        "coverage.csv",
        "ranking.csv",
        "pareto.csv",
        "layer5-statistics.json",
    ):
        assert (run / filename).is_file()
    result = {
        "status": "PASS",
        "codec_key": manifest.key,
        "object_level": "P0_PRIMITIVE",
        "algorithm_id": manifest.algorithm_id,
        "source_artifact_id": manifest.source_artifact_id,
        "formal_run": run.name,
        "qualification_run": qualification.name,
        "eligible_repetitions": eligible_count,
        "formal_attempts": len(records),
        "resource_pressure_attempts": len(records) - eligible_count,
        "native_timing_values": [True, False],
        "supported_fixture": "SYNTHETIC_U32_UTS_NOT_OBSERVATIONAL_TIMESTAMPS",
        "raw_components_sha256": sha(run / "run_components.jsonl"),
        "report_id": report["report_id"],
        "p2_pipeline_qualification": "NOT_CLAIMED",
    }
    output = ROOT / f"build/source-audits/{args.key}-five-layer-audit.json"
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
