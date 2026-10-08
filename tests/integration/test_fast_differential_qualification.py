from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tscompbench.adapters.factory import AdapterFactoryError, adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.datasets import DatasetRegistry
from tscompbench.planning.sweep import expand_sweep
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]
KEY = "fast-differential-u32"


def registry() -> CodecRegistry:
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


@pytest.mark.parametrize("mode", ["DISTINCT", "INPLACE"])
@pytest.mark.parametrize("seed", [0, 1, 2**31, 2**32 - 1])
@pytest.mark.parametrize("timer", [True, False])
def test_all_declared_modes_and_edge_seed_framework_boundaries(
    mode: str, seed: int, timer: bool
) -> None:
    manifest = registry().get(KEY)
    report = run_boundary_suite(
        create_adapter(ROOT, manifest),
        manifest,
        BenchmarkTrack.VALUE,
        {"api_mode": mode, "starting_point": seed, "native_timing": timer},
    )
    failures = [
        (item.case_id, item.reason) for item in report.observations if item.status != "PASS"
    ]
    assert report.passed and report.required_case_count >= 23, failures


def test_onboarding_defaults_and_parameter_identity() -> None:
    manifest = registry().get(KEY)
    card = validate_onboarding_card(
        json.loads((ROOT / f"registry/onboarding/{KEY}.json").read_text())
    )
    assert card["source_artifact_id"] == manifest.source_artifact_id
    (default,) = expand_sweep(manifest, {})
    (explicit,) = expand_sweep(
        manifest,
        {
            "api_mode": ["DISTINCT"],
            "starting_point": [0],
            "native_timing": [True],
            "isa": ["SSE4_1"],
        },
    )
    assert default.config_id == explicit.config_id
    configs = expand_sweep(
        manifest,
        {
            "api_mode": ["DISTINCT", "INPLACE"],
            "starting_point": [0, 1, 2**31, 2**32 - 1],
            "native_timing": [True, False],
        },
    )
    assert len(configs) == len({config.config_id for config in configs}) == 16
    assert all(config.status is RunStatus.PLANNED for config in configs)
    for seed in (-1, 2**32, True):
        (invalid,) = expand_sweep(manifest, {"starting_point": [seed]})
        assert invalid.status is RunStatus.SCHEMA_ERROR


def test_five_layers_preserve_modes_seed_ledger_and_native_timing(tmp_path: Path) -> None:
    run = initialize_run_set(
        ROOT / f"configs/experiments/{KEY}-qualification.toml",
        tmp_path / "runs",
        run_set_id="fast-differential-five-layers",
    )
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    assert len(results) == 16 and all(
        item.preflight.eligible_for_formal_repetitions for item in results
    )
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == 16
    assert all(item["status"] == "PASS" and not item["eligibility"] for item in records)
    assert len({item["bitstream_sha256"] for item in records}) == 8
    for record in records:
        assert record["correctness"]["status"] == "PASS" and record["finalize_bytes"] == 0
        ledger = record["accounting"]
        assert ledger["value_bits"] == ledger["canonical_raw_bits"] == 8193 * 32
        assert ledger["final_bits"] == 8 * ledger["final_physical_bytes"]
        assert (
            ledger["timestamp_bits"]
            == ledger["padding_bits"]
            == ledger["external_side_information_bits"]
            == 0
        )
        telemetry = record["diagnostics"]["codec_telemetry"]
        assert telemetry["scope"] == "LAST_INNER_ITERATION"
        for direction in ("encode", "decode"):
            assert telemetry[direction]["internal_padding_bytes"] == 0
            assert telemetry[direction]["native_staging_input_copy_bytes"] == 8193 * 4
        timing = record["timing"]
        if timing["native_timing_enabled"]:
            assert 0 < timing["native_encode_wall_ns"] <= timing["core_encode_wall_ns"]
            assert 0 < timing["native_decode_wall_ns"] <= timing["core_decode_wall_ns"]
        else:
            assert timing["native_encode_wall_ns"] is timing["native_decode_wall_ns"] is None
    report = report_run_set(run)
    assert report.task_count == 16 and report.eligible_run_count == 0
    assert len(list((run.path / "datasets").glob("*/*.canonical.tscb"))) == 1
    for layer in range(2, 6):
        assert list(run.path.glob(f"layer{layer}-*.json"))


def test_actual_non_uint32_tracks_are_recorded_as_unsupported(tmp_path: Path) -> None:
    run = initialize_run_set(
        ROOT / f"configs/experiments/{KEY}-unsupported-qualification.toml",
        tmp_path / "runs",
        run_set_id="fast-differential-unsupported",
    )
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    assert len(results) == 32 and all(
        not item.preflight.eligible_for_formal_repetitions for item in results
    )
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == 32
    assert {record["status"] for record in records} == {"UNSUPPORTED"}
    assert all(
        not record["eligibility"] and record["record_kind"] == "DIAGNOSTIC" for record in records
    )
    assert report_run_set(run).task_count == 32


@pytest.mark.parametrize("target", ["source", "binding", "binary", "command", "missing-record"])
def test_factory_refuses_qualification_dependency_drift(tmp_path: Path, target: str) -> None:
    manifest = registry().get(KEY)
    artifact, supports = adapter_artifacts(ROOT, manifest)
    for original in (artifact, *supports):
        if original.is_relative_to(ROOT):
            target_path = tmp_path / original.relative_to(ROOT)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target_path)
    adapter_artifacts(tmp_path, manifest)
    relative = {
        "source": "adapters/fast_differential/vendor/FastDifferentialCoding/src/fastdelta.c",
        "binding": "src/tscompbench/adapters/fast_differential.py",
        "binary": str(artifact.relative_to(ROOT)),
        "command": str((artifact.parent / "compile-command.json").relative_to(ROOT)),
        "missing-record": str((artifact.parent / "build-record.json").relative_to(ROOT)),
    }[target]
    path = tmp_path / relative
    if target == "missing-record":
        path.unlink()
    elif target == "command":
        document = json.loads(path.read_text())
        document["commands"][0].append("-march=native")
        path.write_text(json.dumps(document))
    else:
        path.write_bytes(path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(AdapterFactoryError, match="drift|missing"):
        adapter_artifacts(tmp_path, manifest)
