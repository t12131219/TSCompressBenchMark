from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, plan_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[2]
ALIASES = {
    "lz77": "deflate-zlib",
    "gorilla": "prometheus-xor-chunk",
    "delta-of-delta": "prometheus-xor-chunk",
    "second-order-difference": "prometheus-xor-chunk",
}


@pytest.mark.parametrize("alias,target", ALIASES.items())
def test_alias_cli_builds_both_profiles_at_the_canonical_artifact_path(
    monkeypatch, capsys, alias, target
):
    spec = importlib.util.spec_from_file_location(
        "alias_build_driver", ROOT / "tools/build_codec.py"
    )
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    calls = []

    def build(name, profile):
        calls.append((name, profile))
        return {"algorithm": name, "profile": profile}

    monkeypatch.setattr(driver, "_build", build)
    monkeypatch.setattr(sys, "argv", ["build_codec.py", alias, "--profile", "all"])
    assert driver.main() == 0
    assert calls == [(target, "release"), (target, "sanitizer")]
    assert {record["algorithm"] for record in json.loads(capsys.readouterr().out)} == {target}


@pytest.mark.parametrize("alias,target", ALIASES.items())
def test_alias_and_canonical_name_run_one_real_task_and_preserve_requested_mapping(
    tmp_path, alias, target
):
    template = (
        ROOT
        / "configs/experiments"
        / (
            "lz77-qualification.toml"
            if alias == "lz77"
            else "completed-rewrites-prometheus-xor-chunk-qualification.toml"
        )
    )
    text = template.read_text()
    original = 'algorithms = ["lz77"]' if alias == "lz77" else f'algorithms = ["{target}"]'
    config = tmp_path / "aliases.toml"
    config.write_text(text.replace(original, "algorithms = " + json.dumps([alias, target])))
    run = initialize_run_set(config, tmp_path / "runs", run_set_id=alias)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    results = execute_run_set(run, datasets, codecs)
    assert len(results) == 1
    assert results[0].preflight.eligible_for_formal_repetitions
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == 1
    assert records[0]["status"] in {"PASS", "RESOURCE_PRESSURE"}
    assert records[0]["correctness"]["status"] == "PASS"
    assert records[0]["algorithm_id"] == codecs.get(target).algorithm_id
    assert (
        records[0]["accounting"]["final_bits"]
        == records[0]["accounting"]["final_physical_bytes"] * 8
    )
    snapshot = json.loads((run.path / "codec_alias_snapshot.json").read_text())
    assert [(item["key"], item["canonical_key"]) for item in snapshot["aliases"]] == [
        (alias, target)
    ]
    assert json.loads((run.path / "frozen_config.json").read_text())["algorithms"] == [
        alias,
        target,
    ]
    report = report_run_set(run)
    assert report.task_count == 1
    assert (run.path / "report/report.json").is_file()


def test_all_prometheus_aliases_select_one_shared_algorithm(tmp_path):
    target = "prometheus-xor-chunk"
    names = [name for name, key in ALIASES.items() if key == target]
    template = (
        ROOT / "configs/experiments/completed-rewrites-prometheus-xor-chunk-qualification.toml"
    )
    config = tmp_path / "all_aliases.toml"
    config.write_text(
        template.read_text().replace(
            f'algorithms = ["{target}"]', "algorithms = " + json.dumps(names + [target])
        )
    )
    run = initialize_run_set(config, tmp_path / "runs", run_set_id="all-aliases")
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    assert len(plan_run_set(run, datasets, codecs)) == 1
    snapshot = json.loads((run.path / "codec_alias_snapshot.json").read_text())
    assert {item["key"] for item in snapshot["aliases"]} == set(names)
