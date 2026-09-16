import pytest

from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.storage import RunRecord, RunStoreError, append_run_record


def _record(**overrides):
    values = {
        "run_set_id": "run-set",
        "task_id": "task",
        "dataset_id": "dataset",
        "algorithm_id": "algorithm",
        "config_id": "config",
        "execution_path_hash": "execution",
        "semantic_comparability_key": "semantic",
        "execution_comparability_key": "comparison-execution",
        "resource_profile_key": "resource",
        "track": BenchmarkTrack.VALUE,
        "record_kind": "DIAGNOSTIC",
        "repetition_index": None,
        "status": RunStatus.UNSUPPORTED,
        "reason_code": "TEST_DIAGNOSTIC",
        "benchmark_eligible": False,
        "diagnostics": {"ordered_probe": ("one", "two")},
    }
    values.update(overrides)
    return RunRecord.create(**values)


def test_append_is_idempotent_after_json_tuple_normalization(tmp_path) -> None:
    record = _record()
    append_run_record(tmp_path, record)
    append_run_record(tmp_path, record)
    assert len((tmp_path / "run_components.jsonl").read_text().splitlines()) == 1


def test_passing_formal_record_requires_complete_same_repetition_evidence() -> None:
    with pytest.raises(RunStoreError, match="missing evidence"):
        _record(
            record_kind="FORMAL_REPETITION",
            repetition_index=0,
            status=RunStatus.PASS,
            reason_code="FORMAL_REPETITION_PASS",
        )
