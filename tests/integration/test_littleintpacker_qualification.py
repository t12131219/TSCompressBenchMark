"""Registered paths must use the frozen build and preserve Runner repetition evidence."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tscompbench.adapters import littleintpacker
from tscompbench.adapters.factory import AdapterFactoryError, adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[2]
KEYS = tuple(littleintpacker.KEYS)


def registry() -> CodecRegistry:
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


@pytest.mark.parametrize("key", KEYS)
def test_registered_factory_validates_native_and_python_closure(key: str) -> None:
    manifest = registry().get(key)
    artifact, dependencies = adapter_artifacts(ROOT, manifest)
    assert artifact.is_file()
    assert ROOT / "src/tscompbench/planning/resolution.py" in dependencies
    assert ROOT / "src/tscompbench/codecs/registry.py" in dependencies
    session = create_adapter(ROOT, manifest).create_session({})
    session.close()


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize(
    "mutation",
    [
        "missing_object",
        "missing_compiler_dependency",
        "wrong_isa",
        "wrong_source_hash",
        "missing_runtime",
        "fallback",
    ],
)
def test_factory_rejects_unqualified_build_evidence(key, mutation, monkeypatch):
    manifest = registry().get(key)
    artifact, _ = adapter_artifacts(ROOT, manifest)
    raw = (artifact.parent / "build-record.json").read_text()
    document = copy.deepcopy(json.loads(raw))
    if mutation == "missing_object":
        document["objects"].pop()
    elif mutation == "missing_compiler_dependency":
        document["translation_units"][0]["compiler_closure"].pop()
    elif mutation == "wrong_isa":
        document["translation_units"][3]["required_isa_flags"] = ["-mbmi2"]
    elif mutation == "wrong_source_hash":
        document["source_files"][0]["sha256"] = "0" * 64
    elif mutation == "missing_runtime":
        document["runtime_dependencies"] = []
    else:
        document["runtime_fallback"] = True
    original_loads = json.loads

    def altered_build(value, *args, **kwargs):
        return document if value == raw else original_loads(value, *args, **kwargs)

    monkeypatch.setattr(littleintpacker.json, "loads", altered_build)
    with pytest.raises(AdapterFactoryError):
        adapter_artifacts(ROOT, manifest)


def test_five_algorithms_share_one_frozen_source_without_alias_inflation() -> None:
    manifests = [registry().get(key) for key in KEYS]
    assert len({m.algorithm_id for m in manifests}) == 5
    assert len({m.source_artifact_id for m in manifests}) == 1
    source = registry().sources.get(manifests[0].source_artifact_id)
    assert source["identity"]["commit"] == "8777f574a5ab3c653881371819383c986292843c"
    assert source["license"]["status"] == "RUN_ALLOWED"


def test_runner_preserves_all_repetitions_before_reporting(tmp_path: Path) -> None:
    config = tmp_path / "repeated.toml"
    config.write_text(
        (ROOT / "configs/experiments/littleintpacker-pack32-u32-qualification.toml")
        .read_text()
        .replace("repetitions = 1", "repetitions = 3")
    )
    run = initialize_run_set(config, tmp_path / "runs", run_set_id="littleintpacker-repetitions")
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(results) == 4
    assert len(records) == sum(len(result.records) for result in results) == 12
    assert {record["repetition_index"] for record in records} == {0, 1, 2}
    assert all(record["status"] == "PASS" and not record["eligibility"] for record in records)
    report = report_run_set(run)
    assert report.task_count == 4
