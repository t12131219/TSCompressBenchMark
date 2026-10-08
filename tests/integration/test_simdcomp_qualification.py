"""Source-backed SIMDComp admission across all five Benchmark layers."""

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
from tscompbench.preprocess.runtime import reviewed_pipeline_executor
from tscompbench.preprocess.simdcomp import validate_stage_snapshot
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]
KEYS = ("simdcomp-u32", "delta-simdcomp-u32", "for-simdcomp-u32")
CONFIGS = [
    (key, api, isa, seed, timer)
    for key, apis, isas in (
        (KEYS[0], ("LENGTH", "MASKED", "WITHOUTMASK"), ("SSE4_1", "AVX2")),
        (KEYS[1], ("MASKED", "WITHOUTMASK"), ("SSE4_1",)),
        (KEYS[2], ("LENGTH", "FULL"), ("SSE4_1",)),
    )
    for api in apis
    for isa in isas
    if (api, isa) != ("LENGTH", "AVX2")
    for seed in ((0,) if key == KEYS[0] else (0, 1, 2**31, 2**32 - 1))
    for timer in (True, False)
]


def registry() -> CodecRegistry:
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


@pytest.mark.parametrize("key,api,isa,seed,timer", CONFIGS)
def test_all_declared_source_paths_pass_framework_boundaries(key, api, isa, seed, timer) -> None:
    manifest = registry().get(key)
    report = run_boundary_suite(
        create_adapter(ROOT, manifest),
        manifest,
        BenchmarkTrack.VALUE,
        {"api": api, "isa": isa, "starting_point": seed, "native_timing": timer},
    )
    assert report.passed and report.required_case_count >= 23, [
        (o.case_id, o.reason) for o in report.observations if o.status != "PASS"
    ]


@pytest.mark.parametrize("key", KEYS)
def test_identity_defaults_explicit_stage_contract_and_illegal_config(key: str) -> None:
    manifest = registry().get(key)
    assert len({registry().get(k).source_artifact_id for k in KEYS}) == 1
    assert len({registry().get(k).algorithm_id for k in KEYS}) == 3
    card = validate_onboarding_card(
        json.loads((ROOT / f"registry/onboarding/{key}.json").read_text())
    )
    assert card["source_artifact_id"] == manifest.source_artifact_id
    (default,) = expand_sweep(manifest, {})
    (explicit,) = expand_sweep(manifest, {k: [v] for k, v in default.parameters.items()})
    assert default.config_id == explicit.config_id
    plan = build_preprocess_plan(manifest.document, default.parameters)
    assert reviewed_pipeline_executor(
        manifest.document, create_adapter(ROOT, manifest), plan, default.parameters
    )
    assert [s.stage_slot for s in plan.stages] == ([] if key == KEYS[0] else ["A", "B", "D"])
    assert manifest.object_level.value == ("P0_PRIMITIVE" if key == KEYS[0] else "P2_PIPELINE")
    if key == KEYS[0]:
        (invalid,) = expand_sweep(manifest, {"api": ["LENGTH"], "isa": ["AVX2"]})
        assert invalid.status is RunStatus.SCHEMA_ERROR
        assert invalid.reason_code == "AVX2_SOURCE_HAS_NO_LENGTH_API"


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("unsupported", [False, True])
def test_five_layers_keep_supported_and_unsupported_attempts(tmp_path, key, unsupported) -> None:
    suffix = "unsupported-qualification" if unsupported else "qualification"
    run = initialize_run_set(
        ROOT / f"configs/experiments/{key}-{suffix}.toml", tmp_path / "runs", run_set_id=key
    )
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    count = (12 if key == KEYS[0] else 16) * (2 if unsupported else 1)
    assert len(results) == count
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == count and all(not r["eligibility"] for r in records)
    passed = [r for r in records if r["status"] == "PASS"]
    assert len(passed) == (0 if unsupported else 10 if key == KEYS[0] else 16)
    assert {r["status"] for r in records} <= {"PASS", "UNSUPPORTED", "SCHEMA_ERROR"}
    for r in passed:
        assert r["correctness"]["status"] == "PASS" and r["finalize_bytes"] == 0
        ledger, timing = r["accounting"], r["timing"]
        assert ledger["canonical_raw_bits"] == 8193 * 32
        assert ledger["final_bits"] == ledger["final_physical_bytes"] * 8
        assert ledger["timestamp_bits"] == ledger["external_side_information_bits"] == 0
        if timing["native_timing_enabled"]:
            assert 0 < timing["native_encode_wall_ns"] <= timing["core_encode_wall_ns"]
            assert 0 < timing["native_decode_wall_ns"] <= timing["core_decode_wall_ns"]
        else:
            assert timing["native_encode_wall_ns"] is timing["native_decode_wall_ns"] is None
    assert report_run_set(run).task_count == count
    assert list((run.path / "datasets").glob("*/*.canonical.tscb"))


@pytest.mark.parametrize(
    "target",
    [
        "source",
        "binding",
        "stage",
        "binary",
        "command",
        "patch",
        "generated",
        "missing-record",
        "missing-objects",
        "wrong-isa",
    ],
)
def test_factory_rejects_consumed_dependency_drift(tmp_path: Path, target: str) -> None:
    manifest = registry().get(KEYS[0])
    artifact, supports = adapter_artifacts(ROOT, manifest)
    for original in (artifact, *supports):
        if original.is_relative_to(ROOT):
            destination = tmp_path / original.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
    adapter_artifacts(tmp_path, manifest)
    record = str((artifact.parent / "build-record.json").relative_to(ROOT))
    names = {
        "source": "adapters/simdcomp/vendor/simdcomp/src/simdbitpacking.c",
        "binding": "src/tscompbench/adapters/simdcomp.py",
        "stage": "src/tscompbench/preprocess/simdcomp.py",
        "binary": str(artifact.relative_to(ROOT)),
        "command": str((artifact.parent / "compile-command.json").relative_to(ROOT)),
        "patch": "adapters/simdcomp/patches/avx2/0001-zero-width-unpack-byte-count.patch",
        "generated": "build/adapters/simdcomp_u32/release/patched-source/src/avxbitpacking.c",
    }
    changed = tmp_path / names.get(target, record)
    if target == "missing-record":
        changed.unlink()
    elif target in {"command", "missing-objects", "wrong-isa"}:
        document = json.loads(changed.read_text())
        if target == "command":
            document["commands"][1].append("-march=native")
        elif target == "missing-objects":
            document["objects"] = []
        else:
            document["source_isa"] = "AVX512"
        changed.write_text(json.dumps(document))
    else:
        changed.write_bytes(changed.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(AdapterFactoryError, match="drift|missing"):
        adapter_artifacts(tmp_path, manifest)


@pytest.mark.parametrize("key,api", [(KEYS[1], "MASKED"), (KEYS[2], "LENGTH"), (KEYS[2], "FULL")])
@pytest.mark.parametrize("width", [*range(33), None])
def test_independent_stages_cover_all_widths_tails_and_empty(key, api, width) -> None:
    residual, seed = 2**width - 1 if width is not None else 0, 2**32 - 1
    values = np.array(
        [
            (seed + ((i + 1) if key == KEYS[1] else 1) * residual) % 2**32
            for i in range(257 if width is not None else 0)
        ],
        dtype="<u4",
    )
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    routed = RoutedInput(
        "v2:dataset:simdcomp-stage-test",
        BenchmarkTrack.VALUE,
        (item,),
        None,
        None,
        int(values.size),
        1,
        values.nbytes * 8,
        hash_logical_buffers((item,)),
        value_units=("count",),
    )
    snapshot = create_adapter(ROOT, registry().get(key)).inspect_preprocess(
        routed, {"api": api, "starting_point": seed}
    )
    result = validate_stage_snapshot(snapshot)
    assert result["checked_stages"] == ["A", "B", "D"]
    assert result["stage_A_wall_ns"] is result["stage_B_wall_ns"] is None
    for target in ("original", "decoded", "wire_parameters", "stream"):
        bad = copy.deepcopy(snapshot)
        if target in {"original", "decoded"}:
            if not values.size:
                continue
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
