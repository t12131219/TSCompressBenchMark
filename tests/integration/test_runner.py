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


def test_multi_dataset_execution_loads_payload_only_when_its_task_starts(tmp_path, monkeypatch):
    import json
    import tomllib

    import tscompbench.runner as runner
    from tools.verify_all_timing_scopes import config_text
    from tscompbench.codecs import CodecRegistry, SourceRegistry

    document = tomllib.loads(
        (PROJECT_ROOT / "configs/experiments/deflate-zlib-qualification.toml").read_text()
    )
    document.update(
        datasets=["streamvbyte_u32_uts", "simple_uint28_uts"], algorithms=["oracle-direct"]
    )
    document["sweep"] = {"block_size": [1024], "isa": ["SCALAR"]}
    file = tmp_path / "multi.toml"
    file.write_text(config_text(document))
    run = initialize_run_set(file, tmp_path / "runs", run_set_id="lazy")
    original_read = runner.read_canonical
    original_execute = runner.execute_task
    payload_loads = []
    executions = []

    def read(path, *, include_buffers=True):
        artifact = original_read(path, include_buffers=include_buffers)
        if include_buffers:
            payload_loads.append(artifact.metadata["dataset_id"])
        return artifact

    def execute(**kwargs):
        dataset_id = kwargs["task"].dataset_id
        assert payload_loads == executions + [dataset_id]
        executions.append(dataset_id)
        return original_execute(**kwargs)

    monkeypatch.setattr(runner, "read_canonical", read)
    monkeypatch.setattr(runner, "execute_task", execute)
    registry = DatasetRegistry(PROJECT_ROOT / "registry/datasets", PROJECT_ROOT)
    codecs = CodecRegistry(
        PROJECT_ROOT / "registry/codecs", SourceRegistry(PROJECT_ROOT / "registry/sources")
    )
    runner.execute_run_set(run, registry, codecs)
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(executions) == 2 and len(records) == 2
    assert all(record["correctness"]["status"] == "PASS" for record in records)
