from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.factory import AdapterFactoryError, adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.datasets import DatasetRegistry
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.planning.sweep import expand_sweep
from tscompbench.preprocess.contracts import PreprocessContractError, build_preprocess_plan
from tscompbench.preprocess.maskedvbyte import validate_stage_snapshot
from tscompbench.preprocess.runtime import reviewed_pipeline_executor
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]
KEYS = ["maskedvbyte-u32", "delta-maskedvbyte-u32"]
CONFIGS = [
    (key, decoder, seed, timer)
    for key in KEYS
    for decoder in ("COUNT", "COMPRESSED_SIZE")
    for seed in ([0] if key == KEYS[0] else [0, 1, 2**31, 2**32 - 1])
    for timer in (True, False)
]


def registry() -> CodecRegistry:
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


@pytest.mark.parametrize("key,decoder,seed,timer", CONFIGS)
def test_every_declared_config_passes_framework_boundaries(
    key: str, decoder: str, seed: int, timer: bool
) -> None:
    manifest = registry().get(key)
    report = run_boundary_suite(
        create_adapter(ROOT, manifest),
        manifest,
        BenchmarkTrack.VALUE,
        {"decoder_api": decoder, "starting_point": seed, "native_timing": timer},
    )
    failures = [
        (item.case_id, item.reason) for item in report.observations if item.status != "PASS"
    ]
    assert report.passed and report.required_case_count >= 23, failures


@pytest.mark.parametrize("key", KEYS)
def test_defaults_identity_explicit_stages_and_shared_source(key: str) -> None:
    manifest = registry().get(key)
    other = registry().get(KEYS[1] if key == KEYS[0] else KEYS[0])
    assert manifest.source_artifact_id == other.source_artifact_id
    assert manifest.algorithm_id != other.algorithm_id
    card = validate_onboarding_card(
        json.loads((ROOT / f"registry/onboarding/{key}.json").read_text())
    )
    assert card["source_artifact_id"] == manifest.source_artifact_id
    (default,) = expand_sweep(manifest, {})
    (explicit,) = expand_sweep(
        manifest,
        {
            "decoder_api": ["COUNT"],
            "starting_point": [0],
            "native_timing": [True],
            "isa": ["SSE4_1"],
        },
    )
    assert default.config_id == explicit.config_id
    configs = expand_sweep(
        manifest,
        {
            "decoder_api": ["COUNT", "COMPRESSED_SIZE"],
            "starting_point": [0] if key == KEYS[0] else [0, 1, 2**31, 2**32 - 1],
            "native_timing": [True, False],
        },
    )
    assert len(configs) == len({c.config_id for c in configs}) == (4 if key == KEYS[0] else 16)
    assert all(c.status is RunStatus.PLANNED for c in configs)
    plan = build_preprocess_plan(manifest.document, default.parameters)
    assert reviewed_pipeline_executor(
        manifest.document, create_adapter(ROOT, manifest), plan, default.parameters
    )
    assert [s.stage_slot for s in plan.stages] == ([] if key == KEYS[0] else ["A", "B", "D"])
    assert manifest.object_level.value == ("P0_PRIMITIVE" if key == KEYS[0] else "P2_PIPELINE")


@pytest.mark.parametrize("key", KEYS)
def test_supported_five_layers_and_complete_wire_ledger(tmp_path: Path, key: str) -> None:
    run = initialize_run_set(
        ROOT / f"configs/experiments/{key}-qualification.toml", tmp_path / "runs", run_set_id=key
    )
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    count = 4 if key == KEYS[0] else 16
    assert len(results) == count and all(
        r.preflight.eligible_for_formal_repetitions for r in results
    )
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == count and all(
        r["status"] == "PASS" and not r["eligibility"] for r in records
    )
    assert len({r["bitstream_sha256"] for r in records}) == (1 if key == KEYS[0] else 4)
    for record in records:
        assert record["correctness"]["status"] == "PASS" and record["finalize_bytes"] == 0
        ledger = record["accounting"]
        assert ledger["canonical_raw_bits"] == 8193 * 32
        assert ledger["final_bits"] == 8 * ledger["final_physical_bytes"]
        assert (
            ledger["timestamp_bits"]
            == ledger["padding_bits"]
            == ledger["external_side_information_bits"]
            == 0
        )
        telemetry = record["diagnostics"]["codec_telemetry"]
        assert telemetry["scope"] == "LAST_INNER_ITERATION"
        assert telemetry["encode"]["native_staging_input_copy_bytes"] == 8193 * 4
        assert telemetry["decode"]["native_staging_input_copy_bytes"] == 0
        assert (
            telemetry["encode"]["python_payload_copy_bytes"]
            == telemetry["decode"]["python_payload_copy_bytes"]
            == 0
        )
        timing = record["timing"]
        if timing["native_timing_enabled"]:
            assert 0 < timing["native_encode_wall_ns"] <= timing["core_encode_wall_ns"]
            assert 0 < timing["native_decode_wall_ns"] <= timing["core_decode_wall_ns"]
        else:
            assert timing["native_encode_wall_ns"] is timing["native_decode_wall_ns"] is None
    assert report_run_set(run).task_count == count
    assert len(list((run.path / "datasets").glob("*/*.canonical.tscb"))) == 1
    for layer in range(2, 6):
        assert list(run.path.glob(f"layer{layer}-*.json"))


@pytest.mark.parametrize("key", KEYS)
def test_actual_float_and_timestamp_domains_are_retained_unsupported(
    tmp_path: Path, key: str
) -> None:
    run = initialize_run_set(
        ROOT / f"configs/experiments/{key}-unsupported-qualification.toml",
        tmp_path / "runs",
        run_set_id=key,
    )
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    count = 8 if key == KEYS[0] else 32
    assert len(results) == count and all(
        not r.preflight.eligible_for_formal_repetitions for r in results
    )
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == count and {r["status"] for r in records} == {"UNSUPPORTED"}
    assert all(r["record_kind"] == "DIAGNOSTIC" and not r["eligibility"] for r in records)
    assert report_run_set(run).task_count == count


@pytest.mark.parametrize(
    "target", ["source", "binding", "binary", "command", "patch", "generated", "missing-record"]
)
def test_factory_refuses_consumed_dependency_drift(tmp_path: Path, target: str) -> None:
    manifest = registry().get(KEYS[0])
    artifact, supports = adapter_artifacts(ROOT, manifest)
    for original in (artifact, *supports):
        if original.is_relative_to(ROOT):
            destination = tmp_path / original.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
    adapter_artifacts(tmp_path, manifest)
    names = {
        "source": "adapters/maskedvbyte/vendor/MaskedVByte/src/varintdecode.c",
        "binding": "src/tscompbench/adapters/maskedvbyte.py",
        "binary": str(artifact.relative_to(ROOT)),
        "command": str((artifact.parent / "compile-command.json").relative_to(ROOT)),
        "patch": "adapters/maskedvbyte/patches/0001-unsigned-shifts.patch",
        "generated": "build/adapters/maskedvbyte_u32/release/patched-source/src/varintdecode.c",
        "missing-record": str((artifact.parent / "build-record.json").relative_to(ROOT)),
    }
    changed = tmp_path / names[target]
    if target == "missing-record":
        changed.unlink()
    elif target == "command":
        document = json.loads(changed.read_text())
        document["commands"][1].append("-march=native")
        changed.write_text(json.dumps(document))
    else:
        changed.write_bytes(changed.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(AdapterFactoryError, match="drift|missing"):
        adapter_artifacts(tmp_path, manifest)


def test_independent_delta_stage_validator_refuses_wrong_residuals_and_identity() -> None:
    adapter = create_adapter(ROOT, registry().get(KEYS[1]))
    values = np.array([2**32 - 1, 0, 1, 0, 2**31], dtype="<u4")
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    routed = RoutedInput(
        dataset_id="v2:dataset:maskedvbyte-stage-test",
        track=BenchmarkTrack.VALUE,
        buffers=(item,),
        timestamp_reference=None,
        validity_reference=None,
        n=int(values.size),
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers((item,)),
        value_units=("count",),
    )
    snapshot = adapter.inspect_preprocess(routed, {"starting_point": 2**32 - 1})
    result = validate_stage_snapshot(snapshot)
    assert result["checked_stages"] == ["A", "B", "D"]
    assert result["stage_A_wall_ns"] is result["stage_B_wall_ns"] is None
    for target in ("original", "decoded", "wire_parameters", "stream"):
        bad = copy.deepcopy(snapshot)
        if target in {"original", "decoded"}:
            bad[target] = bad[target].copy()
            bad[target][0] ^= 1
        elif target == "wire_parameters":
            bad[target]["starting_point"] ^= 1
        else:
            wire = bytearray(bad["stream"])
            wire[-1] ^= 1
            bad["stream"] = bytes(wire)
        with pytest.raises(PreprocessContractError):
            validate_stage_snapshot(bad)
