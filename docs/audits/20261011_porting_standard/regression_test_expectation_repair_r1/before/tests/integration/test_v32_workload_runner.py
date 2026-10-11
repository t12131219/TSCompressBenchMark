"""Real native stream/query RunSets with independently frozen integration-only protocols."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.comparison.models import ExpectedOutcomeMatrix, GroupSpec, MethodConfigMap
from tscompbench.comparison.runner import prepare_comparison, qualify_comparison
from tscompbench.comparison.workload_runner import (
    WorkloadProtocol,
    execute_workload_comparison,
    pilot_workload_comparison,
    prepare_workload_comparison,
    report_workload_comparison,
    validate_workload_pilot,
)
from tscompbench.datasets import DatasetRegistry
from tscompbench.execution import preparation
from tscompbench.execution.protocol import LogicalBuffer
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import stable_id

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", params=["STREAM", "QUERY"])
def real_workload(request, tmp_path_factory):
    kind = request.param
    directory = tmp_path_factory.mktemp("v32-workload-" + kind.lower())
    stem = "g-stream-ll" if kind == "STREAM" else "g-query-ll-variants"
    bundle = ROOT / "configs/comparisons" / (stem + "-v32-20261010.json")
    registry = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    protocol = WorkloadProtocol(
        kind, outer_sessions=2, pilot_pairs=3, query_count=10, max_collector_fraction="0.90"
    )
    # These short protocols verify software contracts, and are not scientific performance evidence.
    prior = {
        k: os.environ.get(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")
    }
    os.environ.update({k: "1" for k in prior})
    try:
        run, plan = prepare_workload_comparison(
            bundle,
            directory,
            ROOT,
            registry,
            codecs,
            run_set_id="integration-only",
            protocol=protocol,
        )
        qualified = qualify_comparison(run, registry)
        assert qualified["status"] == "PASS", qualified
        pilot = pilot_workload_comparison(run, plan, registry)
        assert pilot["status"] == "PASS", pilot
        report = execute_workload_comparison(run, plan, pilot)
        yield run, plan, pilot, report, bundle, registry, codecs, protocol
    finally:
        for k, v in prior.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_workload_real_fixed_cells_sessions_and_truthful_uncertainty(real_workload):
    run, plan, _, report, *_ = real_workload
    assert report["status"] == "PROFILE_COMPLETE", report
    raw = (run.path / "workload_trials.jsonl").read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert len(rows) == len(run.cells) * 2
    assert [r["trial_id"] for r in rows] == [s["trial_id"] for s in plan["schedule"]["trials"]]
    assert all(r["observation"]["status"] == "PASS" for r in rows)
    analysis = json.loads((run.path / "workload_analysis.json").read_text())
    assert analysis["timing_thresholds"]
    assert analysis["timing_overhead_subtracted"] is False
    assert analysis["independent_real_source_count"] == 2
    assert all(p["status"] == "INCONCLUSIVE" for p in analysis["paired_comparisons"])
    if plan["protocol"]["kind"] == "QUERY":
        assert report["distinct_methods"] == 1
        assert report["inference_scope"] == "IMPLEMENTATION_VARIANT_STUDY"
        assert all(s["p99_ns"] is None for c in analysis["matrix"] for s in c["query_sessions"])
        for cell in analysis["matrix"]:
            for session in cell["query_sessions"]:
                assert session["read_amplification_availability"] == "AVAILABLE"
                assert session["decode_amplification"] == "1"
                cost = session["index_checkpoint_cost"]
                assert cost["index_bits"] is None and cost["checkpoint_bits"] is None
                assert cost["final_bits"] == sum(
                    d["bits"] for d in session["decoder_dependencies"] if d["charged_in_final_bits"]
                )
        assert all(
            [s["request"] for s in r["observation"]["query"]["query_samples"]]
            == plan["requests"][r["dataset_id"]]
            for r in rows
        )
    else:
        assert report["distinct_methods"] == 5
        assert all(r["observation"]["encode"]["first_consumable_sample_ns"] is None for r in rows)
    assert report_workload_comparison(run.path)["analysis_id"] == report["analysis_id"]
    assert (run.path / "workload_trials.jsonl").read_bytes() == raw


def test_workload_resume_retains_raw_and_frozen_environment(real_workload):
    run, _, pilot, report, bundle, datasets, codecs, protocol = real_workload
    raw = (run.path / "workload_trials.jsonl").read_bytes()
    environment = (run.path / "environment.json").read_bytes()
    resumed, plan = prepare_workload_comparison(
        bundle,
        run.path.parent,
        ROOT,
        datasets,
        codecs,
        run_set_id="integration-only",
        protocol=protocol,
        resume=True,
    )
    assert execute_workload_comparison(resumed, plan, pilot)["analysis_id"] == report["analysis_id"]
    assert (run.path / "workload_trials.jsonl").read_bytes() == raw
    assert (run.path / "environment.json").read_bytes() == environment


def test_workload_physical_context_tamper_is_excluded_read_only(real_workload):
    run, *_ = real_workload
    raw = (run.path / "workload_trials.jsonl").read_bytes()
    row = json.loads(raw.splitlines()[0])
    path = run.path / "workload_artifacts" / (row["trial_id"].rsplit(":", 1)[-1] + ".decode.json")
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    try:
        assert report_workload_comparison(run.path)["status"] == "PROFILE_INCOMPLETE"
        assert (run.path / "workload_trials.jsonl").read_bytes() == raw
    finally:
        path.write_bytes(original)
        report_workload_comparison(run.path)


def test_workload_pilot_coverage_and_frozen_request_tamper_rejected(real_workload):
    run, plan, pilot, *_ = real_workload
    damaged = copy.deepcopy(pilot)
    damaged["raw"].pop()
    assert (
        "PILOT_FIXED_MEMBER_PAIR_COVERAGE_MISMATCH"
        in validate_workload_pilot(run, plan, damaged)["reasons"]
    )
    path = run.path / "workload_plan.json"
    original = path.read_bytes()
    saved = json.loads(original)
    saved["cells"][0]["canonical_raw_bits"] += 8
    saved["workload_id"] = stable_id(
        "workload-comparison-v32", {k: v for k, v in saved.items() if k != "workload_id"}
    )
    path.write_text(json.dumps(saved))
    try:
        with pytest.raises(ValueError, match="plan/protocol/base/schedule"):
            report_workload_comparison(run.path)
    finally:
        path.write_bytes(original)
    if plan["protocol"]["kind"] == "QUERY":
        saved = json.loads(original)
        next(iter(saved["requests"].values()))[0]["start"] += 1
        saved["workload_id"] = stable_id(
            "workload-comparison-v32", {k: v for k, v in saved.items() if k != "workload_id"}
        )
        path.write_text(json.dumps(saved))
        try:
            with pytest.raises(ValueError, match="query requests"):
                report_workload_comparison(run.path)
        finally:
            path.write_bytes(original)


def test_workload_pilot_clock_raw_and_worker_provenance_are_required(real_workload):
    run, plan, pilot, *_ = real_workload
    assert pilot["validation"]["timing_calibration_metrics"]
    for fault in ("missing", "pid", "resolution"):
        damaged = copy.deepcopy(pilot)
        observation = damaged["raw"][0]["observation"]
        document = (
            observation["encode"] if plan["protocol"]["kind"] == "STREAM" else observation["query"]
        )
        if fault == "missing":
            document["timing_calibration"] = None
        elif fault == "pid":
            document["timing_calibration"]["worker_pid"] += 1
        else:
            document["timing_calibration"]["clock"]["declared_resolution_ns"] = 1_000_000_000
        validation = validate_workload_pilot(run, plan, damaged)
        assert not validation["eligible"], validation
        expected = {
            "missing": "PILOT_CLOCK_HARNESS_RAW_EVIDENCE_MISSING_OR_INVALID",
            "pid": "PILOT_CLOCK_HARNESS_PROVENANCE_INVALID",
            "resolution": "PILOT_DIRECTION_OR_QUERY_BELOW_CLOCK_SIGNAL",
        }[fault]
        assert expected in validation["reasons"]


def test_workload_formal_short_signal_is_excluded_using_frozen_pilot(real_workload):
    run, plan, *_ = real_workload
    path = run.path / "workload_trials.jsonl"
    original = path.read_bytes()
    rows = [json.loads(line) for line in original.splitlines()]
    observation = rows[0]["observation"]
    if plan["protocol"]["kind"] == "STREAM":
        observation["encode"]["encode_wall_ns"] = 1
    else:
        sample = observation["query"]["query_samples"][0]
        sample["wall_ns"] = 1
        sample["finished_ns"] = sample["started_ns"] + 1
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    try:
        assert report_workload_comparison(run.path)["status"] == "PROFILE_INCOMPLETE"
        analysis = json.loads((run.path / "workload_analysis.json").read_text())
        assert any(
            "WORKLOAD_DIRECTION_OR_QUERY_BELOW_CALIBRATED_SIGNAL" in r["reasons"]
            for r in analysis["exclusions"]
        )
    finally:
        path.write_bytes(original)
        report_workload_comparison(run.path)


@pytest.mark.parametrize("fault", ["schema", "bytes"])
def test_native_api_rejects_different_actual_inputs_on_same_original_corpus(
    tmp_path, monkeypatch, fault
):
    spec = importlib.util.spec_from_file_location(
        "v32_profile_builder", ROOT / "tools/build_v32_profile_bundles.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    document = module.derive(
        json.loads((ROOT / "configs/comparisons/g-int-ll-i16-v32-20261010-v2.json").read_text()),
        "api",
    )
    # The integer bundle also contains P2 pipelines; isolate two legal P1 components.
    keep = {"neats-lossless-i64", "lz4-frame"}
    document["config_map"]["members"] = [
        m for m in document["config_map"]["members"] if m["member_id"] in keep
    ]
    config_id = MethodConfigMap.from_document(document["config_map"]).id
    document["expected_matrix"]["entries"] = [
        e for e in document["expected_matrix"]["entries"] if e["member_id"] in keep
    ]
    document["expected_matrix"]["config_map_id"] = config_id
    expected_id = ExpectedOutcomeMatrix.from_document(document["expected_matrix"]).id
    document["group"]["members"] = [
        m for m in document["group"]["members"] if m["member_id"] in keep
    ]
    for member in document["group"]["members"]:
        member["role"] = "CORE"
    document["group"]["method_equivalence"] = [
        e for e in document["group"]["method_equivalence"] if set(e["members"]) <= keep
    ]
    document["group"].update(config_map_id=config_id, expected_matrix_id=expected_id)
    GroupSpec.from_document(document["group"])
    bundle = tmp_path / "mismatched-native-api.json"
    bundle.write_text(json.dumps(document))
    datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    # Inject a physical preparation defect, never a performance result or a FORMAL label.
    # Both unmodified public APIs accept the original i16; the boundary must catch a
    # changed array schema or bytes introduced by either implementation's preparation.
    actual_prepare = preparation.prepare_execution_input
    calls = 0

    def differing_preparation(*args, **kwargs):
        nonlocal calls
        prepared = actual_prepare(*args, **kwargs)
        calls += 1
        if calls != 2:
            return prepared
        buffers = []
        for b in prepared.codec_input.buffers:
            array = np.array(
                b.array, dtype="<i8" if fault == "schema" else b.array.dtype, copy=True
            )
            if fault == "bytes":
                array.flat[0] += 1
            array.flags.writeable = False
            buffers.append(LogicalBuffer(b.name, array, array.nbytes * 8))
        codec_input = replace(
            prepared.codec_input,
            buffers=tuple(buffers),
            input_sha256=hash_logical_buffers(tuple(buffers)),
        )
        return replace(prepared, codec_input=codec_input)

    monkeypatch.setattr(preparation, "prepare_execution_input", differing_preparation)
    with pytest.raises(ValueError, match="actual input schemas and bytes"):
        prepare_comparison(bundle, tmp_path, ROOT, datasets, codecs, run_set_id="mismatch")


def test_missing_timestamp_expected_rejection_never_routes_an_absent_timestamp(
    tmp_path, monkeypatch
):
    from tscompbench.comparison import runner
    from tscompbench.contracts import BenchmarkTrack, RunStatus

    actual_route = runner.route_canonical_artifact

    def no_missing_timestamp_route(artifact, track):
        if (
            track is BenchmarkTrack.TIMESTAMP
            and not artifact.metadata["logical_descriptor"]["timestamp"]["present"]
        ):
            pytest.fail("admission rejection must not route nonexistent timestamp buffers")
        return actual_route(artifact, track)

    monkeypatch.setattr(runner, "route_canonical_artifact", no_missing_timestamp_route)
    datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    run = prepare_comparison(
        ROOT / "configs/comparisons/g-timestamp-v32-20261010-v1.json",
        tmp_path,
        ROOT,
        datasets,
        codecs,
        run_set_id="missing-t-plan",
    )
    rejected = [c for c in run.cells.values() if c["expected_outcome"] == "REJECT"]
    assert len(rejected) == 8
    assert all(run.tasks[c["cell_id"]].status is RunStatus.UNSUPPORTED for c in rejected)
    assert all(c["input_sha256"] is None for c in rejected)
    assert all(":unavailable-codec-input:" in c["actual_input_id"] for c in rejected)
    assert all(":unavailable-codec-input-schema:" in c["actual_input_schema_id"] for c in rejected)
    runner.validate_frozen_comparison(run.path, run.bundle, run.plan)
