import hashlib
from pathlib import Path

import pytest


@pytest.fixture
def assert_current_artifact_evidence():
    """Verify new raw against persisted files and the actual worker evidence."""

    def verify(run_path: Path, record: dict) -> None:
        name = record["run_id"].rsplit(":", 1)[-1]
        stream = (run_path / "artifacts" / f"{name}.bin").read_bytes()
        context = (run_path / "artifacts" / f"{name}.decode.json").read_bytes()
        ledger = record["accounting"]
        external_bits = len(context) * 8
        assert external_bits > 0
        assert ledger["final_physical_bytes"] == len(stream)
        assert ledger["serialized_bits"] == len(stream) * 8
        assert ledger["external_side_information_bits"] == external_bits
        assert ledger["final_bits"] == ledger["serialized_bits"] + external_bits
        assert hashlib.sha256(stream).hexdigest() == record["bitstream_sha256"]

        diagnostics = record["diagnostics"]
        recovery = diagnostics["independent_recovery"]
        context_sha256 = hashlib.sha256(context).hexdigest()
        assert recovery["protocol"] == "PERSISTED_DECODE_CONTEXT_V1"
        assert recovery["context_sha256"] == context_sha256
        assert recovery["required_external_bits"] == external_bits
        assert recovery["output_materialization"] == "OWNED_CANONICAL_BUFFERS"
        assert recovery["qualification_evidence_scope"] == "TASK_PREFLIGHT_FRESH_WORKER_ONLY"
        qualification = recovery["qualification"]
        assert qualification["decode_context_sha256"] == context_sha256
        assert qualification["required_external_bits"] == external_bits
        assert qualification["start_method"] == "spawn"
        assert not qualification["original_input_available"]
        assert not qualification["encoder_session_available"]
        assert qualification["output_owned_in_worker"]

        lifecycle = diagnostics["worker_lifecycle"]
        measurement = diagnostics["worker_measurement"]
        assert lifecycle["worker_exit_confirmed"]
        assert measurement["worker_pid"] == lifecycle["worker_pid"]
        assert measurement["warmup_worker_pid"] == measurement["measurement_worker_pid"]
        assert measurement["measurement_worker_pid"] == lifecycle["worker_pid"]
        warmup = measurement["warmup"]
        assert warmup["threshold_satisfied"]
        assert warmup["completed_iterations"] >= warmup["required_min_count"] >= 1
        assert len(measurement["warmup_iterations"]) == warmup["completed_iterations"]
        assert {item["worker_pid"] for item in measurement["warmup_iterations"]} == {
            lifecycle["worker_pid"]
        }
        assert measurement["warmup_finished_ns"] <= measurement["measurement_started_ns"]

    return verify
