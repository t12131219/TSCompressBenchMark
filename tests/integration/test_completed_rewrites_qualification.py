from __future__ import annotations

import json
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, plan_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[2]


def registries():
    return DatasetRegistry(ROOT / "registry/datasets", ROOT), CodecRegistry(
        ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")
    )


@pytest.mark.parametrize(
    "name", ["abba", "influxdb-tsm-adaptive-timestamp", "prometheus-histogram-st", "deepzip"]
)
@pytest.mark.parametrize("scope", ["CORE", "PIPELINE", "E2E"])
def test_complete_framework_path_and_qualification_cannot_enter_rankings(tmp_path, name, scope):
    template = ROOT / "configs/experiments" / f"completed-rewrites-{name}-qualification.toml"
    config = tmp_path / "scope.toml"
    config.write_text(
        template.read_text().replace('timing_scope = "PIPELINE"', f'timing_scope = "{scope}"')
    )
    run = initialize_run_set(config, tmp_path / "runs", run_set_id=name)
    results = execute_run_set(run, *registries())
    assert len(results) == 1
    assert results[0].preflight.eligible_for_formal_repetitions
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == 1
    record = records[0]
    assert record["status"] in {"PASS", "RESOURCE_PRESSURE"}
    assert record["correctness"]["status"] == "PASS"
    assert record["eligibility"] is False
    timing = record["timing"]
    assert timing["timing_scope"] == scope
    boundary = "core" if scope == "CORE" else "pipeline"
    assert timing["selected_encode_wall_ns"] == timing[f"{boundary}_encode_wall_ns"]
    assert timing["selected_decode_wall_ns"] == timing[f"{boundary}_decode_wall_ns"]
    assert timing["selected_wall_ns"] == (
        timing["e2e_wall_ns"]
        if scope == "E2E"
        else timing[f"{boundary}_encode_wall_ns"] + timing[f"{boundary}_decode_wall_ns"]
    )
    assert timing["native_encode_wall_ns"] is None
    assert timing["native_decode_wall_ns"] is None
    assert record["accounting"]["final_bits"] == record["accounting"]["final_physical_bytes"] * 8
    if name == "abba":
        task = json.loads((run.path / "task_plan.jsonl").read_text().splitlines()[0])
        assert task["comparability"]["semantic_document"]["loss_mode"] == "UNBOUNDED_LOSSY"
        assert record["correctness"]["loss"]["bound_passed"] is None
    report = report_run_set(run)
    assert report.task_count == 1
    assert (run.path / "coverage.csv").is_file()
    for layer in (2, 3, 4, 5):
        assert next(run.path.glob(f"layer{layer}-*.json"), None)


def test_incompatible_histogram_fields_are_retained_in_task_universe(tmp_path):
    template = (
        ROOT / "configs/experiments/completed-rewrites-prometheus-histogram-st-qualification.toml"
    )
    config = tmp_path / "unsupported.toml"
    config.write_text(template.read_text().replace("rewrite_histogram_int", "rewrite_float_mts"))
    run = initialize_run_set(config, tmp_path / "runs", run_set_id="fields")
    tasks = plan_run_set(run, *registries())
    assert len(tasks) == 1 and tasks[0].status.value == "UNSUPPORTED"
    results = execute_run_set(run, *registries())
    assert len(results) == 1
    report = report_run_set(run)
    assert report.task_count == 1
