import hashlib
import json
from pathlib import Path

from tscompbench.reporting import generate_report
from tscompbench.statistics import analyze_run_set


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _task(task_id: str, algorithm: str, execution_path: str) -> dict:
    semantic = "semantic:lossless-value"
    execution = "execution:single-thread-pipeline"
    resource = "resource:process-rss"
    return {
        "schema_version": "tscb.benchmark-task.v2",
        "task_id": task_id,
        "dataset_id": "dataset:one",
        "algorithm_id": algorithm,
        "config_id": f"config:{algorithm}",
        "track": "VALUE",
        "profile_id": "profile:formal",
        "status": "PLANNED",
        "reason_code": "READY_FOR_PREFLIGHT",
        "execution": {
            "execution_path_hash": execution_path,
            "source_artifact_id": f"source:{algorithm}",
            "adapter_id": f"adapter:{algorithm}",
            "artifact_sha256": hashlib.sha256(algorithm.encode()).hexdigest(),
            "environment_id": "environment:one",
        },
        "comparability": {
            "semantic_key": semantic,
            "execution_key": execution,
            "resource_key": resource,
            "semantic_document": {
                "track": "VALUE",
                "object_level": "P1_STANDALONE_CODEC",
                "loss_mode": "LOSSLESS",
            },
            "execution_document": {"semantic_key": semantic, "repetitions": 10},
            "resource_document": {"execution_key": execution},
        },
    }


def _record(
    run_path: Path,
    task: dict,
    repetition: int,
    *,
    final_bits: int,
    encode_ns: int,
    status: str = "PASS",
) -> dict:
    run_id = f"run:{task['task_id']}:{repetition}"
    stream = bytes([65 + repetition % 10]) * (final_bits // 8)
    bitstream_hash = hashlib.sha256(stream).hexdigest()
    if status == "PASS":
        (run_path / "artifacts" / f"{run_id.rsplit(':', 1)[-1]}-{task['task_id']}.bin").write_bytes(
            stream
        )
        # The production artifact convention uses the final RunID component. Keep IDs unique
        # across tasks by replacing the test artifact with the exact expected name below.
        expected = run_path / "artifacts" / f"{run_id.rsplit(':', 1)[-1]}.bin"
        expected.write_bytes(stream)
    accounting = {
        "schema_version": "tscb.accounting-ledger.v2",
        "track": "VALUE",
        "timestamp_bits": 0,
        "value_bits": final_bits,
        "shared_bits": 0,
        "unallocated_shared_bits": 0,
        "metadata_bits": 0,
        "validity_bits": 0,
        "dictionary_bits": 0,
        "model_bits": 0,
        "index_bits": 0,
        "checkpoint_bits": 0,
        "checksum_bits": 0,
        "padding_bits": 0,
        "container_bits": 0,
        "external_side_information_bits": 0,
        "serialized_bits": final_bits,
        "final_bits": final_bits,
        "final_physical_bytes": final_bits // 8,
        "canonical_raw_bits": 800,
    }
    passed = status == "PASS"
    return {
        "schema_version": "tscb.run-record.v2",
        "run_id": run_id,
        "run_set_id": "runset:one",
        "task_id": task["task_id"],
        "dataset_id": task["dataset_id"],
        "algorithm_id": task["algorithm_id"],
        "config_id": task["config_id"],
        "execution_path_hash": task["execution"]["execution_path_hash"],
        "semantic_comparability_key": task["comparability"]["semantic_key"],
        "execution_comparability_key": task["comparability"]["execution_key"],
        "resource_profile_key": task["comparability"]["resource_key"],
        "track": "VALUE",
        "record_kind": "FORMAL_REPETITION",
        "repetition_index": repetition,
        "status": status,
        "reason_code": "FORMAL_REPETITION_PASS" if passed else "WORKER_TIMEOUT",
        "eligibility": passed,
        "input_sha256": "1" * 64,
        "bitstream_sha256": bitstream_hash if passed else None,
        "finalize_bytes": 1 if passed else None,
        "timing": (
            {
                "schema_version": "tscb.timing-observation.v2",
                "timing_scope": "PIPELINE",
                "inner_iterations": 2,
                "selected_wall_ns": encode_ns + 100,
                "selected_encode_wall_ns": encode_ns,
                "selected_decode_wall_ns": 100,
                "e2e_wall_ns": encode_ns + 100,
                "canonical_bytes_per_iteration": 100,
                "min_duration_satisfied": True,
            }
            if passed
            else None
        ),
        "resources": (
            {
                "schema_version": "tscb.resource-observation.v2",
                "scope_availability": "AVAILABLE",
                "process_total_seconds": "0.002",
                "peak_process_rss_bytes": 1000 + repetition,
                "incremental_peak_memory_bytes": 100 + repetition,
                "cpu_core_seconds_per_gb": "10000",
            }
            if passed
            else None
        ),
        "workloads": {} if passed else None,
        "accounting": accounting if passed else None,
        "correctness": (
            {
                "schema_version": "tscb.correctness-report.v2",
                "status": "PASS",
                "first_failure_stage": None,
                "checks": ["FLOAT_IEEE_BITS"],
                "diagnostics": {},
                "loss": None,
            }
            if passed
            else None
        ),
        "diagnostics": {
            "measurement_policy": {
                "schema_version": "tscb.measurement-policy.v2",
                "measurement_mode": "FORMAL",
                "repetitions": 10,
            }
        },
    }


def test_layer5_filters_groups_uses_frozen_coverage_and_preserves_raw_evidence(tmp_path) -> None:
    run_path = tmp_path / "runset"
    (run_path / "artifacts").mkdir(parents=True)
    tasks = [_task("task-a", "algorithm:a", "path:a"), _task("task-b", "algorithm:b", "path:b")]
    records: list[dict] = []
    # Artifact names are keyed by the final RunID component in production, so make the
    # suffix unique across tasks in this fixture.
    for task, final_bits, encode_ns in ((tasks[0], 400, 200), (tasks[1], 480, 240)):
        for repetition in range(10):
            record = _record(
                run_path,
                task,
                repetition,
                final_bits=final_bits,
                encode_ns=encode_ns + repetition * 2,
            )
            record["run_id"] = f"run:{task['task_id']}-{repetition}"
            stream = bytes([65 + repetition % 10]) * (final_bits // 8)
            record["bitstream_sha256"] = hashlib.sha256(stream).hexdigest()
            (run_path / "artifacts" / f"{task['task_id']}-{repetition}.bin").write_bytes(stream)
            records.append(record)
    timeout_task = _task("task-timeout", "algorithm:timeout", "path:timeout")
    tasks.append(timeout_task)
    records.append(
        _record(
            run_path,
            timeout_task,
            0,
            final_bits=400,
            encode_ns=200,
            status="TIMEOUT",
        )
    )
    partial_task = _task("task-partial", "algorithm:partial", "path:partial")
    tasks.append(partial_task)
    for repetition in range(9):
        record = _record(
            run_path,
            partial_task,
            repetition,
            final_bits=560,
            encode_ns=300,
        )
        record["run_id"] = f"run:{partial_task['task_id']}-{repetition}"
        stream = bytes([75 + repetition]) * (560 // 8)
        record["bitstream_sha256"] = hashlib.sha256(stream).hexdigest()
        (run_path / "artifacts" / f"{partial_task['task_id']}-{repetition}.bin").write_bytes(stream)
        records.append(record)
    _write_jsonl(run_path / "task_plan.jsonl", tasks)
    _write_jsonl(run_path / "run_components.jsonl", records)
    (run_path / "datasets" / "one").mkdir(parents=True)
    (run_path / "datasets" / "one" / "preparation-record.json").write_text(
        json.dumps(
            {
                "dataset_id": "dataset:one",
                "canonical_artifact_sha256": "2" * 64,
                "canonical_content_sha256": "3" * 64,
                "source_sha256": "4" * 64,
            }
        ),
        encoding="utf-8",
    )
    (run_path / "run-set.json").write_text(
        json.dumps({"run_set_id": "runset:one"}), encoding="utf-8"
    )
    for name, document in (
        ("frozen_config.json", {"schema_version": "2.0"}),
        ("environment.json", {"environment_id": "environment:one"}),
        ("codec_registry_snapshot.json", {"codecs": []}),
    ):
        (run_path / name).write_text(json.dumps(document), encoding="utf-8")
    (run_path / "source_registry_snapshot.json").write_text(
        json.dumps(
            {
                "schema_version": "tscb.source-registry-snapshot.v2",
                "sources": [
                    {"source_artifact_id": f"source:algorithm:{name}"}
                    for name in ("a", "b", "timeout", "partial")
                ],
            }
        ),
        encoding="utf-8",
    )
    policy = {
        "bootstrap_samples": 200,
        "confidence_level": "0.95",
        "ranking_policy": "PER_METRIC_WITHIN_COMPARABILITY_GROUP",
        "tie_method": "DENSE_EXACT",
        "coverage_policy": "PUBLISH_SEPARATELY_NO_SCORE",
    }

    raw_before = hashlib.sha256((run_path / "run_components.jsonl").read_bytes()).hexdigest()
    bundle = analyze_run_set(run_path, policy)
    assert len(bundle.summaries) == 2
    assert all(item["n"] == 10 for item in bundle.summaries)
    assert bundle.summaries[0]["encode_ns_median"] > 0
    assert len(bundle.corpus_summaries) == 2
    assert {item["coverage_category"] for item in bundle.coverage} == {
        "PASS",
        "FAIL",
        "TIMEOUT",
    }
    timeout_eligibility = [item for item in bundle.eligibility if item["task_id"] == "task-timeout"]
    assert timeout_eligibility
    assert all(not item["eligible"] for item in timeout_eligibility)
    assert all("RUN_STATUS_TIMEOUT" in item["reason_codes"] for item in timeout_eligibility)
    partial_eligibility = [
        item
        for item in bundle.eligibility
        if item["task_id"] == "task-partial" and item["analysis"] == "PERFORMANCE"
    ]
    assert partial_eligibility
    assert all(not item["eligible"] for item in partial_eligibility)
    assert all(
        "INSUFFICIENT_OR_DUPLICATE_REPETITIONS" in item["reason_codes"]
        for item in partial_eligibility
    )
    assert bundle.rankings
    assert bundle.pareto

    result = generate_report(run_path, policy)
    assert result.summary_count == 2
    assert result.task_count == 4
    assert (run_path / "summary.csv").is_file()
    assert (run_path / "eligibility.csv").is_file()
    assert (run_path / "coverage.csv").is_file()
    assert (run_path / "comparability.csv").is_file()
    assert (run_path / "pareto.csv").is_file()
    assert (run_path / "report" / "report.json").is_file()
    assert (run_path / "report" / "report.md").is_file()
    assert (run_path / "report" / "report.html").is_file()
    assert (run_path / "report" / "coverage.svg").is_file()
    assert (run_path / "report" / "space-encode.svg").is_file()
    assert (run_path / "report" / "space-decode.svg").is_file()
    report_document = json.loads((run_path / "report" / "report.json").read_text())
    assert "report/coverage.svg" in report_document["derived_artifact_hashes"]
    assert report_document["dataset_evidence"][0]["dataset_id"] == "dataset:one"
    markdown_report = (run_path / "report" / "report.md").read_text()
    assert "## Reproducibility context" in markdown_report
    assert "### Exclusions and abnormal outcomes" in markdown_report
    raw_after = hashlib.sha256((run_path / "run_components.jsonl").read_bytes()).hexdigest()
    assert raw_after == raw_before
