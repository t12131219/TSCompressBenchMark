from pathlib import Path

import pytest

from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import RunnerError, initialize_run_set, prepare_run_set

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _config(path: Path, dataset: str = "national_illness") -> Path:
    path.write_text(
        f'''schema_version = "2.0"\ndatasets = ["{dataset}"]\nseed = 7\n\n'''
        "[data_preparation]\n"
        'characterization_mode = "exact"\n'
        "write_canonical = true\n",
        encoding="utf-8",
    )
    return path


def test_run_set_refuses_overwrite_and_supports_verified_resume(tmp_path) -> None:
    config_path = _config(tmp_path / "experiment.toml")
    output = tmp_path / "runs"
    run_set = initialize_run_set(config_path, output, run_set_id="test-run")
    assert (run_set.path / "frozen_config.json").is_file()
    assert (run_set.path / "environment.json").is_file()
    assert (run_set.path / "events.jsonl").is_file()
    with pytest.raises(RunnerError, match="already exists"):
        initialize_run_set(config_path, output, run_set_id="test-run")
    resumed = initialize_run_set(config_path, output, run_set_id="test-run", resume=True)
    assert resumed.config.canonical_document == run_set.config.canonical_document


def test_resume_rejects_corrupt_event_log(tmp_path) -> None:
    config_path = _config(tmp_path / "experiment.toml")
    output = tmp_path / "runs"
    run_set = initialize_run_set(config_path, output, run_set_id="corrupt")
    with (run_set.path / "events.jsonl").open("ab") as handle:
        handle.write(b"not-json\n")
    with pytest.raises(RunnerError, match="event log validation failed"):
        initialize_run_set(config_path, output, run_set_id="corrupt", resume=True)


def test_run_prepare_completes_layer_1(tmp_path) -> None:
    config_path = _config(tmp_path / "experiment.toml")
    run_set = initialize_run_set(config_path, tmp_path / "runs", run_set_id="prepared")
    registry = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    results = prepare_run_set(run_set, registry)
    assert len(results) == 1
    assert "LAYER_1_COMPLETED" in (run_set.path / "events.jsonl").read_text(encoding="utf-8")


def test_resumed_run_reuses_only_verified_layer_1_artifacts(tmp_path) -> None:
    config_path = _config(tmp_path / "experiment.toml")
    output = tmp_path / "runs"
    run_set = initialize_run_set(config_path, output, run_set_id="resumed-prepare")
    registry = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    original = prepare_run_set(run_set, registry)

    resumed = initialize_run_set(config_path, output, run_set_id="resumed-prepare", resume=True)
    reused = prepare_run_set(resumed, registry)

    assert reused[0].canonical.sha256 == original[0].canonical.sha256
    events = (run_set.path / "events.jsonl").read_text(encoding="utf-8")
    assert "DATASET_PREPARATION_REUSED" in events


def test_resumed_run_rejects_tampered_layer_1_artifact(tmp_path) -> None:
    config_path = _config(tmp_path / "experiment.toml")
    output = tmp_path / "runs"
    run_set = initialize_run_set(config_path, output, run_set_id="tampered-prepare")
    registry = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    result = prepare_run_set(run_set, registry)[0]
    with result.canonical.path.open("ab") as handle:
        handle.write(b"tampered")

    resumed = initialize_run_set(config_path, output, run_set_id="tampered-prepare", resume=True)
    with pytest.raises(Exception, match="trailing bytes"):
        prepare_run_set(resumed, registry)
