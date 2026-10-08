"""Require the registered RLE factory and Runner to consume the frozen real artifacts."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from tscompbench.adapters import fastpfor_simple8b_rle as rle
from tscompbench.adapters.factory import AdapterFactoryError, adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[2]


def registry() -> CodecRegistry:
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


def test_registered_rle_consumes_native_build_and_current_sdk() -> None:
    manifest = registry().get(rle.KEY)
    artifact, dependencies = adapter_artifacts(ROOT, manifest)
    assert artifact == ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2/release/libtscb_fastpfor_simple8b_rle.so"
    for path in ("src/tscompbench/adapters/factory.py", "src/tscompbench/adapters/fastpfor_simple8b_rle.py",
                 "src/tscompbench/adapters/fastpfor_simple.py", "src/tscompbench/execution/repetition.py"):
        assert ROOT / path in dependencies
    session = create_adapter(ROOT, manifest).create_session({})
    session.close()


@pytest.mark.parametrize("tamper", ["wrong_object", "missing_compiler_file", "wrong_source_pin",
                                  "missing_patch", "fallback", "wrong_build_id"])
def test_factory_rejects_changed_native_build(tamper: str, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = registry().get(rle.KEY)
    artifact, _ = adapter_artifacts(ROOT, manifest)
    raw = (artifact.parent / "build-record.json").read_text()
    document = copy.deepcopy(json.loads(raw))
    if tamper == "wrong_object":
        document["objects"][0]["sha256"] = "0" * 64
    elif tamper == "missing_compiler_file":
        document["compiled_source_closure"].pop()
    elif tamper == "wrong_source_pin":
        document["source_lock_sha256"] = "0" * 64
    elif tamper == "missing_patch":
        document["patches"] = []
    elif tamper == "fallback":
        document["runtime_fallback"] = True
    else:
        document["build_id"] = "20261007-1"
    loads = json.loads
    monkeypatch.setattr(rle.json, "loads", lambda value, *args, **kwargs:
                        document if value == raw else loads(value, *args, **kwargs))
    with pytest.raises(AdapterFactoryError):
        adapter_artifacts(ROOT, manifest)


def test_runner_retains_three_repetitions_per_configuration(tmp_path: Path) -> None:
    config = tmp_path / "repeated.toml"
    config.write_text((ROOT / f"configs/experiments/{rle.KEY}-qualification.toml").read_text()
                      .replace("repetitions = 1", "repetitions = 3"))
    run = initialize_run_set(config, tmp_path / "runs", run_set_id="rle-repetitions")
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    records = [json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()]
    assert len(results) == 4 and len(records) == sum(len(result.records) for result in results) == 12
    assert {record["repetition_index"] for record in records} == {0, 1, 2}
    assert all(record["status"] == "PASS" and not record["eligibility"] for record in records)
    assert report_run_set(run).task_count == 4
