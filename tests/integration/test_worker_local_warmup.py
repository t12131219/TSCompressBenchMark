import hashlib
import json
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_every_repetition_has_worker_local_warmup_and_resume_preserves_raw(tmp_path):
    config = tmp_path / "worker-local.toml"
    config.write_text(
        """schema_version = "2.0"
datasets = ["national_illness"]
algorithms = ["oracle-direct"]
tracks = ["VALUE"]

[data_preparation]
characterization_mode = "exact"
write_canonical = true

[profile]
measurement_mode = "QUALIFICATION"
warmup_min_count = 2
warmup_min_seconds = "0"
repetitions = 3
min_repetition_seconds = "0"
timeout_seconds = 10
memory_limit_bytes = 1073741824
""",
        encoding="utf-8",
    )
    run_set = initialize_run_set(config, tmp_path / "runs", run_set_id="worker-local")
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    codecs = CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources)
    datasets = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    results = execute_run_set(run_set, datasets, codecs)
    assert len(results) == 1
    records = results[0].records
    assert [record.repetition_index for record in records] == [0, 1, 2]
    assert all(record.status.value == "PASS" for record in records)
    raw_path = run_set.path / "run_components.jsonl"
    raw_before = raw_path.read_bytes()
    documents = [json.loads(line) for line in raw_before.splitlines()]
    pids = []
    for record in documents:
        diagnostics = record["diagnostics"]
        lifecycle = diagnostics["worker_lifecycle"]
        evidence = diagnostics["worker_measurement"]
        pids.append(lifecycle["worker_pid"])
        assert evidence["warmup"]["completed_iterations"] == 2
        assert len(evidence["warmup_iterations"]) == 2
        assert evidence["warmup_worker_pid"] == evidence["measurement_worker_pid"] == pids[-1]
        assert evidence["warmup_finished_ns"] <= evidence["measurement_started_ns"]
        recovery = diagnostics["independent_recovery"]
        artifact_name = record["run_id"].rsplit(":", 1)[-1]
        context = (run_set.path / "artifacts" / f"{artifact_name}.decode.json").read_bytes()
        assert recovery["protocol"] == "PERSISTED_DECODE_CONTEXT_V1"
        assert recovery["context_sha256"] == hashlib.sha256(context).hexdigest()
        assert recovery["required_external_bits"] == len(context) * 8
        assert recovery["output_materialization"] == "OWNED_CANONICAL_BUFFERS"
        assert recovery["qualification_evidence_scope"] == "TASK_PREFLIGHT_FRESH_WORKER_ONLY"
        assert recovery["qualification"] is not None
    assert len(set(pids)) == 3
    events = [json.loads(line) for line in (run_set.path / "events.jsonl").read_text().splitlines()]
    completed = [event for event in events if event["event_type"] == "REPETITION_WORKER_COMPLETED"]
    assert len(completed) == 3
    assert execute_run_set(run_set, datasets, codecs) == ()
    assert raw_path.read_bytes() == raw_before
