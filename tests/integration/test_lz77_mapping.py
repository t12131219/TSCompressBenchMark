from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from tscompbench.adapters import create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.datasets import DatasetRegistry
from tscompbench.planning import expand_sweep
from tscompbench.runner import RunnerError, initialize_run_set, plan_run_set
from tscompbench.validation import run_boundary_suite

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _registry():
    return CodecRegistry(
        PROJECT_ROOT / "registry/codecs", SourceRegistry(PROJECT_ROOT / "registry/sources")
    )


@pytest.mark.parametrize("profile", ["qualification", "formal"])
def test_lz77_experiment_sweeps_are_valid_for_the_actual_source_codec(profile):
    path = PROJECT_ROOT / f"configs/experiments/lz77-{profile}.toml"
    document = tomllib.loads(path.read_text())
    assert document["algorithms"] == ["lz77"]
    configurations = expand_sweep(_registry().get("lz77"), document["sweep"])
    assert len(configurations) == 1
    assert configurations[0].status is not RunStatus.SCHEMA_ERROR


@pytest.mark.parametrize("names", [
    ["lz77"], ["lz77", "deflate-zlib"], ["deflate-zlib", "lz77"],
])
def test_mapping_is_frozen_and_duplicate_logical_names_do_not_multiply_tasks(
    tmp_path, monkeypatch, names,
):
    original = (PROJECT_ROOT / "configs/experiments/lz77-qualification.toml").read_text()
    config_path = tmp_path / "config.toml"
    config_path.write_text(original.replace('algorithms = ["lz77"]',
                                            "algorithms = " + json.dumps(names)))
    run = initialize_run_set(config_path, tmp_path / "runs", run_set_id="lz77-mapping")
    registry = _registry()
    datasets = DatasetRegistry(PROJECT_ROOT / "registry/datasets", PROJECT_ROOT)
    tasks = plan_run_set(run, datasets, registry)
    assert len(tasks) == 1
    assert tasks[0].algorithm_id == registry.get("deflate-zlib").algorithm_id
    snapshot = json.loads((run.path / "codec_alias_snapshot.json").read_text())
    assert snapshot["aliases"][0]["key"] == "lz77"
    codec_snapshot = json.loads((run.path / "codec_registry_snapshot.json").read_text())
    assert len(codec_snapshot["codecs"]) == 1
    assert codec_snapshot["codecs"][0]["key"] == "deflate-zlib"
    assert plan_run_set(run, datasets, registry) == tasks
    altered = list(registry.alias_documents())
    altered[0]["limitations"].append("Different admission evidence cannot resume this run.")
    monkeypatch.setattr(registry, "alias_documents", lambda: tuple(altered))
    with pytest.raises(RunnerError, match="existing frozen artifact differs"):
        plan_run_set(run, datasets, registry)


@pytest.mark.parametrize("track", [BenchmarkTrack.VALUE, BenchmarkTrack.TIMESTAMP])
def test_mapping_passes_registered_boundary_gate_on_both_tracks(track):
    manifest = _registry().get("lz77")
    adapter = create_adapter(PROJECT_ROOT, manifest)
    report = run_boundary_suite(adapter, manifest, track, {
        "block_size": 8, "compression_level": 6, "window_bits": 15, "isa": "SCALAR",
    })
    assert report.passed, [item for item in report.observations if item.status != "PASS"]
