"""Real registered native methods, never an oracle or fabricated FORMAL evidence."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.comparison.analysis import AnalysisPolicy
from tscompbench.comparison.models import (
    ComparisonContract,
    ExpectedOutcomeMatrix,
    MethodConfigMap,
)
from tscompbench.comparison.runner import (
    execute_comparison,
    pilot_comparison,
    prepare_comparison,
    qualify_comparison,
    report_comparison,
    validate_comparison_pilots,
    validate_qualification_evidence,
)
from tscompbench.datasets import DatasetRegistry
from tscompbench.ids import stable_id
from tscompbench.measurement.v32_protocol import MeasurementProtocol

ROOT = Path(__file__).resolve().parents[2]


def _integration_bundle(path: Path, *, cold: bool = False, native_api: bool = False) -> Path:
    document = json.loads((ROOT / "configs/comparisons/g-byte-ll-v32-20261010-v2.json").read_text())
    protocol_values = {
        key: value
        for key, value in document["protocol"].items()
        if key not in {"schema_version", "protocol_id"}
    }
    protocol_values.update(
        outer_repetitions=2,
        encode_min_ns=5_000_000,
        decode_min_ns=5_000_000,
        max_harness_fraction="0.90",
        max_collector_fraction="0.90",
        pilot_repetitions=3,
    )
    if cold:
        protocol_values.update(
            profile="COLD_PROCESS",
            warmup_min_count=0,
            warmup_min_ns=0,
            max_inner_iterations=1,
            cache_policy="OS_CACHE_UNCONTROLLED",
            cold_start_boundary="SPAWN_THROUGH_OUTPUT_MATERIALIZATION",
            thread_monitor_interval_ns=1_000_000,
        )
    elif native_api:
        protocol_values["timing_scope"] = "CORE"
    protocol_values["precision_checkpoints"] = tuple(protocol_values["precision_checkpoints"])
    protocol = MeasurementProtocol(**protocol_values)
    policy = AnalysisPolicy(bootstrap_samples=200)
    document["protocol"] = protocol.to_document()
    document["analysis_policy"] = policy.to_document()
    contract = document["contract"]
    contract.update(
        name="BYTE_INTEGRATION_VERIFICATION_ONLY",
        revision="integration-no-scientific-publication",
        measurement_protocol_id=protocol.protocol_id,
        analysis_policy_id=policy.id,
    )
    if native_api:
        contract.update(
            mode="COMMON_NATIVE_API",
            cost_boundary="NATIVE_COMPONENT",
            timing_boundary="CORE_API",
            workload="API_COMPONENT",
        )
        contract["estimand"]["outcome"] = "SERIALIZED_COMPONENT_BITS_AND_EXTERNAL_CORE_API_WALL_NS"
    contract_id = ComparisonContract.from_document(contract).id
    document["config_map"]["contract_id"] = contract_id
    config_map_id = MethodConfigMap.from_document(document["config_map"]).id
    document["expected_matrix"].update(contract_id=contract_id, config_map_id=config_map_id)
    expected_id = ExpectedOutcomeMatrix.from_document(document["expected_matrix"]).id
    document["group"].update(
        name="BYTE_INTEGRATION_VERIFICATION_ONLY",
        revision="integration-no-scientific-publication",
        contract_id=contract_id,
        config_map_id=config_map_id,
        expected_matrix_id=expected_id,
    )
    path.write_text(json.dumps(document, indent=2))
    return path


def _run_real_comparison(tmp_path_factory, *, cold: bool, native_api: bool = False):
    import os

    directory = tmp_path_factory.mktemp("v32-cold-comparison" if cold else "v32-native-comparison")
    # Spawn must inherit these before importing NumPy/native dependencies.
    prior = {
        key: os.environ.get(key)
        for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
    }
    os.environ.update({key: "1" for key in prior})
    try:
        bundle = _integration_bundle(directory / "bundle.json", cold=cold, native_api=native_api)
        datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
        codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
        run = prepare_comparison(bundle, directory, ROOT, datasets, codecs, run_set_id="native")
        qualification = qualify_comparison(run, datasets)
        assert qualification["status"] == "PASS", qualification["failure_count"]
        pilot = pilot_comparison(run, datasets)
        assert pilot["status"] == "PASS", pilot
        report = execute_comparison(run, pilot)
        yield run, bundle, datasets, codecs, qualification, pilot, report
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture(scope="module")
def real_comparison(tmp_path_factory):
    yield from _run_real_comparison(tmp_path_factory, cold=False)


@pytest.fixture(scope="module")
def cold_comparison(tmp_path_factory):
    yield from _run_real_comparison(tmp_path_factory, cold=True)


@pytest.fixture(scope="module")
def native_api_comparison(tmp_path_factory):
    yield from _run_real_comparison(tmp_path_factory, cold=False, native_api=True)


def test_real_matrix_randomized_spawn_and_read_only_report(real_comparison):
    run, _, _, _, _, _, report = real_comparison
    assert report["status"] == "CORE_COMPLETE"
    raw_path = run.path / "comparison_trials.jsonl"
    before = raw_path.read_bytes()
    trials = [json.loads(line) for line in before.splitlines()]
    assert len(trials) == 24
    assert all(t["formal_eligible"] for t in trials)
    assert [t["trial_id"] for t in trials] == [t.trial_id for t in run.schedule.trials]
    pids = [t["record"]["diagnostics"]["worker_lifecycle"]["worker_pid"] for t in trials]
    assert len(set(pids)) == len(pids)
    assert all(
        t["record"]["diagnostics"]["worker_lifecycle"]["start_method"] == "spawn" for t in trials
    )
    assert report_comparison(run.path)["analysis_id"] == report["analysis_id"]
    assert raw_path.read_bytes() == before
    analysis = json.loads((run.path / "analysis.json").read_text())
    assert analysis["raw_sha256"] == hashlib.sha256(before).hexdigest()
    assert analysis["independent_real_source_count"] == 2


def test_resume_preserves_every_trial_and_original_environment(real_comparison):
    run, bundle, datasets, codecs, _, pilot, _ = real_comparison
    raw = (run.path / "comparison_trials.jsonl").read_bytes()
    frozen_environment = (run.path / "environment.json").read_bytes()
    resumed = prepare_comparison(
        bundle, run.path.parent, ROOT, datasets, codecs, run_set_id="native", resume=True
    )
    execute_comparison(resumed, pilot)
    assert (run.path / "comparison_trials.jsonl").read_bytes() == raw
    assert (run.path / "environment.json").read_bytes() == frozen_environment


def test_fake_pass_qualification_and_pilot_are_rejected(real_comparison):
    run, _, _, _, qualification, pilot, _ = real_comparison
    damaged = copy.deepcopy(qualification)
    damaged["evidence"].pop()
    damaged["qualification_id"] = stable_id(
        "comparison-qualification", {k: v for k, v in damaged.items() if k != "qualification_id"}
    )
    with pytest.raises(ValueError, match="coverage"):
        validate_qualification_evidence(run, damaged)
    damaged_pilot = copy.deepcopy(pilot)
    damaged_pilot["members"][0]["pilot"]["raw"] = []
    with pytest.raises(ValueError):
        validate_comparison_pilots(run, damaged_pilot)


def test_report_rechecks_paid_decoder_dependency_without_modifying_raw(real_comparison):
    run, _, _, _, _, _, _ = real_comparison
    raw_path = run.path / "comparison_trials.jsonl"
    before = raw_path.read_bytes()
    trial = json.loads(before.splitlines()[0])
    name = trial["record"]["run_id"].rsplit(":", 1)[-1]
    dependency = run.path / "artifacts" / (name + ".decoder.json")
    saved = dependency.read_bytes()
    damaged = json.loads(saved)
    damaged["artifact_sha256"] = "0" * 64
    dependency.write_text(json.dumps(damaged))
    try:
        assert report_comparison(run.path)["status"] == "CORE_INCOMPLETE"
        assert raw_path.read_bytes() == before
    finally:
        dependency.write_bytes(saved)
        report_comparison(run.path)


def test_real_cold_comparison_pays_startup_owned_recovery_and_preserves_resume(cold_comparison):
    run, bundle, datasets, codecs, _, pilot, report = cold_comparison
    assert report["status"] == "CORE_COMPLETE"
    raw_path = run.path / "comparison_trials.jsonl"
    before = raw_path.read_bytes()
    trials = [json.loads(line) for line in before.splitlines()]
    assert len(trials) == 24 and all(t["formal_eligible"] for t in trials)
    assert all(
        item["pilot"]["schema_version"] == "tscb.cold-measurement-pilot.v3.2"
        for item in pilot["members"]
    )
    pids = []
    for trial in trials:
        record = trial["record"]
        timing, diagnostics = record["timing"], record["diagnostics"]
        assert timing["profile"] == "COLD_PROCESS" and timing["inner_iterations"] == 1
        assert timing["startup_import_adapter_loading_included"] is True
        assert timing["native_encode_wall_ns"] is None
        assert diagnostics["warmup_count"] == 0 and "worker_measurement" not in diagnostics
        assert diagnostics["independent_recovery"]["parent_output_owned"] is True
        for direction in ("encode", "decode"):
            lifecycle = diagnostics[f"{direction}_worker_lifecycle"]
            assert lifecycle["worker_exit_confirmed"] and lifecycle["exit_code"] == 0
            assert lifecycle["selected_parent_wall_ns"] == timing[f"selected_{direction}_wall_ns"]
            assert lifecycle["thread_observation"]["samples"]
            pids.append(lifecycle["worker_pid"])
    assert len(set(pids)) == len(pids)
    assert report_comparison(run.path)["analysis_id"] == report["analysis_id"]
    resumed = prepare_comparison(
        bundle, run.path.parent, ROOT, datasets, codecs, run_set_id="native", resume=True
    )
    assert execute_comparison(resumed, pilot)["analysis_id"] == report["analysis_id"]
    assert raw_path.read_bytes() == before


@pytest.mark.parametrize("change", ["warmup", "worker_reuse", "materialization", "time_boundary"])
def test_cold_comparison_rejects_relabelled_or_incomplete_evidence(cold_comparison, change):
    from tscompbench.comparison.analysis import trial_issues

    run, _, _, _, _, pilot, _ = cold_comparison
    trial = json.loads((run.path / "comparison_trials.jsonl").read_text().splitlines()[0])
    diagnostics = trial["record"]["diagnostics"]
    if change == "warmup":
        diagnostics["warmup_count"] = 1
    elif change == "worker_reuse":
        diagnostics["decode_worker_lifecycle"]["worker_pid"] = diagnostics[
            "encode_worker_lifecycle"
        ]["worker_pid"]
    elif change == "materialization":
        diagnostics["independent_recovery"]["parent_output_owned"] = False
    else:
        trial["record"]["timing"]["selected_encode_wall_ns"] -= 1
    issues = trial_issues(
        trial,
        run.cells[trial["cell_id"]],
        {**run.plan, "pilot_eligible": True, "pilot_id": pilot["pilot_id"]},
    )
    assert any(issue.startswith("COLD_") for issue in issues), issues


def test_common_native_api_lane_has_common_inputs_and_actual_core_boundary(native_api_comparison):
    run, _, _, _, _, _, report = native_api_comparison
    assert report["status"] == "CORE_COMPLETE"
    raw_path = run.path / "comparison_trials.jsonl"
    before = raw_path.read_bytes()
    trials = [json.loads(line) for line in before.splitlines()]
    for trial in trials:
        timing = trial["record"]["timing"]
        assert trial["formal_eligible"]
        assert timing["timing_scope"] == "CORE"
        for direction in ("encode", "decode"):
            assert timing[f"selected_{direction}_wall_ns"] == timing[f"core_{direction}_wall_ns"]
        # Native C API observations remain auxiliary; this lane measures the
        # declared external component API, including its FFI/container work.
        assert timing["native_timing_boundary"] == "CODEC_API_ONLY_V1"
        assert trial["record"]["diagnostics"]["independent_recovery"]["qualification"][
            "original_input_available"
        ] is False
    for dataset_id in run.artifacts:
        cells = [cell for cell in run.cells.values() if cell["dataset_id"] == dataset_id]
        assert len({cell["public_projection_key"] for cell in cells}) == 1
        jobs = [
            json.loads(
                (run.path / "jobs" / (cell["cell_id"].rsplit(":", 1)[-1] + ".json")).read_text()
            )["execution_job"]
            for cell in cells
        ]
        assert len({job["actual_input_id"] for job in jobs}) == 1
        assert len({job["actual_input_schema_id"] for job in jobs}) == 1
    analysis = json.loads((run.path / "analysis.json").read_text())
    for cell in analysis["matrix"]:
        assert cell["comparison_cost_metric"] == "serialized_bits"
        ledger_bits = [
            trial["record"]["accounting"]["serialized_bits"]
            for trial in trials
            if trial["cell_id"] == cell["cell_id"]
        ]
        assert cell["comparison_cost_bits"]["mean"] == sum(ledger_bits) / len(ledger_bits)
        assert cell["final_bits"]["mean"] > cell["comparison_cost_bits"]["mean"]
    assert report_comparison(run.path)["analysis_id"] == report["analysis_id"]
    assert raw_path.read_bytes() == before


def test_native_api_lane_rejects_pipeline_relabelling(native_api_comparison):
    from tscompbench.comparison.analysis import trial_issues

    run, _, _, _, _, pilot, _ = native_api_comparison
    trial = json.loads((run.path / "comparison_trials.jsonl").read_text().splitlines()[0])
    timing = trial["record"]["timing"]
    timing["selected_encode_wall_ns"] = timing["pipeline_encode_wall_ns"]
    issues = trial_issues(
        trial,
        run.cells[trial["cell_id"]],
        {**run.plan, "pilot_eligible": True, "pilot_id": pilot["pilot_id"]},
    )
    assert "COMMON_NATIVE_API_COMPONENT_BOUNDARY_NOT_VERIFIED" in issues
