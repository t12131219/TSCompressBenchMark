from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pytest

from tscompbench.comparison import pipeline_runner as runner
from tscompbench.comparison.analysis import AnalysisPolicy
from tscompbench.measurement.v32_protocol import MeasurementProtocol
from tscompbench.pipelines import LogicalObject, LogicalObjectSchema

ROOT = Path(__file__).resolve().parents[2]


def _object(offset):
    n = 19
    values = {"nd": np.arange(offset, offset + 2 * n, dtype="<f4").reshape(2, n)}
    mask = {"nd": np.arange(2 * n).reshape(2, n) % 5 != 0}
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": [
                {
                    "name": "nd",
                    "dtype": "<f4",
                    "shape": [2, n],
                    "axes": ["feature", "time"],
                    "time_axis": 1,
                    "unit": "units",
                    "entity": "sensor",
                    "feature": "grid",
                }
            ],
            "timestamp": {
                "present": True,
                "dtype": "<i8",
                "unit": "ns",
                "epoch": "zero",
                "pairing": "SHARED_TIME_AXIS",
            },
            "null_recovery_contract": "BITWISE",
        }
    )
    return LogicalObject(schema, values, np.arange(n, dtype="<i8") + offset, mask)


def _prepare(tmp_path, monkeypatch):
    # Other independent implementation agents may edit unrelated source files.
    # Production freezes the entire control plane; this focused test freezes its
    # actual lane file while retaining the real child source/binary closures.
    monkeypatch.setattr(
        runner,
        "control_plane_snapshot",
        lambda root: {
            "path": "src/tscompbench/comparison/pipeline_runner.py",
            "sha256": hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
        },
    )
    for key in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        monkeypatch.setenv(key, "1")
    dataset = {
        "dataset_key": "fixture_nd_tv",
        "test": runner.save_pipeline_input(tmp_path / "test.npz", _object(0)),
        "development": runner.save_pipeline_input(tmp_path / "dev.npz", _object(100)),
    }
    protocol = MeasurementProtocol(
        profile="STEADY_PROCESS",
        outer_repetitions=2,
        encode_min_ns=5_000_000,
        decode_min_ns=5_000_000,
        max_trial_wall_ns=30_000_000_000,
        max_total_wall_ns=240_000_000_000,
        pilot_repetitions=3,
        warmup_min_count=1,
        thread_monitor_interval_ns=5_000_000,
        max_collector_fraction="0.95",
        max_harness_fraction="0.50",
    )
    return runner.prepare_pipeline_comparison(
        ROOT,
        tmp_path,
        [dataset],
        protocol=protocol,
        policy=AnalysisPolicy(minimum_paired_blocks=2, bootstrap_samples=100),
        block_size=8,
        resources={
            "logical_cpus": [min(os.sched_getaffinity(0))],
            "threads": 1,
            "memory_limit_bytes": 1_073_741_824,
        },
    )


def test_pipeline_frozen_inputs_and_recipe_drift(tmp_path, monkeypatch):
    plan = _prepare(tmp_path, monkeypatch)
    runner.validate_pipeline_plan(plan)
    altered = copy.deepcopy(plan)
    altered["cells"][0]["recipe"]["block_size"] = 7
    with pytest.raises(runner.PipelineComparisonError, match="identity drift"):
        runner.validate_pipeline_plan(altered)
    altered = copy.deepcopy(plan)
    altered["closure"]["children"]["lz4-frame"]["adapter_id"] = "wrong"
    with pytest.raises(runner.PipelineComparisonError, match="closure drift"):
        runner.validate_pipeline_plan(altered)
    path = Path(plan["datasets"][0]["test"]["path"])
    path.write_bytes(path.read_bytes() + b"drift")
    with pytest.raises(runner.PipelineComparisonError, match="input file drift"):
        runner.validate_pipeline_plan(plan)


def test_pipeline_full_qualification_pilot_formal_report_resume(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    qualification = runner.qualify_pipeline_comparison(tmp_path)
    assert len(qualification["cases"]) == 2
    for case in qualification["cases"]:
        assert case["recovery"]["only_arguments"] == [
            "public_decoder_program_root",
            "artifact_bytes",
        ]
        assert case["recovery"]["owned"] and not case["recovery"]["original_available"]
    pilot = runner.pilot_pipeline_comparison(tmp_path)
    assert all(c["evidence"]["status"] == "PASS" for c in pilot["cases"])
    report = runner.execute_pipeline_comparison(tmp_path)
    assert report["status"] == "COMPLETE"
    assert report["eligible_trials"] == report["expected_trials"] == 4
    assert report["fixed_cell_denominator"] == 2
    before = (tmp_path / "trials.jsonl").read_bytes()
    artifacts = {p.name: p.read_bytes() for p in (tmp_path / "artifacts").glob("*.p2")}
    assert runner.report_pipeline_comparison(tmp_path) == report
    assert runner.execute_pipeline_comparison(tmp_path) == report
    assert (tmp_path / "trials.jsonl").read_bytes() == before
    assert {p.name: p.read_bytes() for p in (tmp_path / "artifacts").glob("*.p2")} == artifacts
    trials = [json.loads(line) for line in before.splitlines()]
    wrong = copy.deepcopy(trials)
    wrong[0]["observation"]["ledger"]["canonical_raw_bits"] += 1
    with pytest.raises(runner.PipelineComparisonError, match="accounting drift"):
        runner._audit_trials(tmp_path, json.loads((tmp_path / "plan.json").read_bytes()), wrong)
    wrong = copy.deepcopy(trials)
    wrong[0]["observation"]["warmup_worker_pid"] = -1
    assert runner._audit_trials(tmp_path, json.loads((tmp_path / "plan.json").read_bytes()), wrong)[
        wrong[0]["trial_id"]
    ]
    path = Path(trials[0]["artifact_path"])
    path.write_bytes(path.read_bytes() + b"trailing")
    with pytest.raises(runner.PipelineComparisonError, match="artifact drift"):
        runner.report_pipeline_comparison(tmp_path)


def test_pipeline_real_sources_have_disjoint_explicit_extensions(tmp_path):
    datasets = runner.build_real_pipeline_inputs(ROOT, tmp_path)
    assert {d["dataset_key"] for d in datasets} == {
        "etth1_f32",
        "weather_f32",
        "etth1_mixed_nd_tv_validity",
        "weather_mixed_nd_tv_validity",
    }
    for dataset in datasets:
        test = runner.load_pipeline_input(dataset["test"])
        development = runner.load_pipeline_input(dataset["development"])
        assert test.schema.n == development.schema.n == 513
        assert test.content_id != development.content_id
        assert (
            dataset["derivation"]["test_window"][1] < dataset["derivation"]["development_window"][0]
        )
        if "mixed" in dataset["dataset_key"]:
            assert test.values["nd_f64"].shape == (2, 513, 2)
            assert test.timestamp is not None and test.validity is not None
            assert test.canonical_raw_bits == 513 * (4 * 64 + 32 + 64 + 5)
        else:
            assert test.canonical_raw_bits == 513 * 4 * 32
    # Frozen inputs are deterministic; saving again cannot overwrite content.
    assert runner.build_real_pipeline_inputs(ROOT, tmp_path) == datasets
