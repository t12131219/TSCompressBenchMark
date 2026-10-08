"""Check registered source identities, factory binding and bounded domain rejection."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.factory import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack
from tscompbench.datasets import DatasetRegistry
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput, SourceDomainError
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set
from tscompbench.validation.boundary import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]
KEYS = ["simple9-u28", "simple9hacked-u28", "simple16-u28"]


def registry() -> CodecRegistry:
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("marked", [False, True])
def test_registered_factory_roundtrip_and_real_boundary_suite(key: str, marked: bool) -> None:
    manifest = registry().get(key)
    adapter = create_adapter(ROOT, manifest)
    artifact, dependencies = adapter_artifacts(ROOT, manifest)
    assert artifact.is_file()
    assert ROOT / "src/tscompbench/adapters/fastpfor_simple.py" in dependencies
    build = json.loads((artifact.parent / "build-record.json").read_text())
    assert not any("googletest" in p["path"] for p in build["compiled_source_closure"])
    card = json.loads((ROOT / "registry/onboarding" / (key + ".json")).read_text())
    assert validate_onboarding_card(card) == card
    assert card["input_contract"]["value_maximum"] == 2**28 - 1
    values = np.array([0, 1, 2**28 - 1, 2**27, 7], dtype="<u4")
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    routed = RoutedInput(
        "v2:dataset:simple-registry-test",
        BenchmarkTrack.VALUE,
        (item,),
        None,
        None,
        values.size,
        1,
        item.logical_bits,
        hash_logical_buffers((item,)),
    )
    result = perform_roundtrip(adapter, routed, {"mark_length": marked})
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    suite = run_boundary_suite(adapter, manifest, BenchmarkTrack.VALUE, {"mark_length": marked})
    assert suite.passed, suite.to_document()
    assert any(
        o.reason == "SOURCE_DOMAIN_REJECTED_ATOMICALLY:SIMPLE_UINT28_VALUE_OUT_OF_RANGE"
        for o in suite.observations
    )


@pytest.mark.parametrize("key", KEYS)
def test_full_uint32_rejected_as_source_domain_with_unchanged_output(key: str) -> None:
    adapter = create_adapter(ROOT, registry().get(key))
    values = np.array([0, 2**28, 2**32 - 1], dtype="<u4")
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    routed = RoutedInput(
        "v2:dataset:simple-rejection-test",
        BenchmarkTrack.VALUE,
        (item,),
        None,
        None,
        3,
        1,
        item.logical_bits,
        hash_logical_buffers((item,)),
    )
    session = adapter.create_session({})
    target = bytearray(b"\xa5" * 2048)
    try:
        with pytest.raises(SourceDomainError) as error:
            session.compress_update(routed, memoryview(target))
        assert str(error.value) == "SIMPLE_UINT28_VALUE_OUT_OF_RANGE"
        assert error.value.rejection_atomic
        assert target == b"\xa5" * len(target)
    finally:
        session.close()


def test_three_distinct_algorithms_share_frozen_source_without_alias_inflation() -> None:
    manifests = [registry().get(key) for key in KEYS]
    assert len({m.algorithm_id for m in manifests}) == 3
    assert len({m.source_artifact_id for m in manifests}) == 1
    source = registry().sources.get(manifests[0].source_artifact_id)
    assert source["identity"]["commit"] == "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
    assert source["license"]["status"] == "RUN_ALLOWED"


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize(
    "kind", ["qualification", "unsupported-qualification", "source-domain-rejection-qualification"]
)
def test_all_five_layers_preserve_supported_and_rejected_attempts(
    tmp_path: Path, key: str, kind: str
) -> None:
    run = initialize_run_set(
        ROOT / f"configs/experiments/{key}-{kind}.toml", tmp_path / "runs", run_set_id=key
    )
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    count = 8 if kind == "unsupported-qualification" else 4
    assert len(results) == len(records) == count
    assert all(not r["eligibility"] for r in records)
    passed = kind == "qualification"
    assert {r["status"] for r in records} == ({"PASS"} if passed else {"UNSUPPORTED"})
    for r in records:
        if passed:
            assert r["correctness"]["status"] == "PASS"
            assert r["accounting"]["canonical_raw_bits"] == 8193 * 32
            assert r["accounting"]["final_bits"] == r["accounting"]["final_physical_bytes"] * 8
            assert r["finalize_bytes"] == 0
            timing = r["timing"]
            if timing["native_timing_enabled"]:
                assert 0 < timing["native_encode_wall_ns"] <= timing["core_encode_wall_ns"]
                assert 0 < timing["native_decode_wall_ns"] <= timing["core_decode_wall_ns"]
            else:
                assert timing["native_encode_wall_ns"] is timing["native_decode_wall_ns"] is None
        elif kind == "source-domain-rejection-qualification":
            assert r["reason_code"] == "SOURCE_DOMAIN_UNSUPPORTED"
    assert report_run_set(run).task_count == count
    assert list((run.path / "datasets").glob("*/*.canonical.tscb"))


@pytest.mark.parametrize("kind", ["qualification", "unsupported-qualification"])
def test_task_results_preserve_multiple_repetitions_and_single_diagnostics(
    tmp_path: Path, kind: str
) -> None:
    # Exercise the real Runner contract that the benchmark driver consumes.
    config = tmp_path / "repeated.toml"
    config.write_text(
        (ROOT / f"configs/experiments/simple9-u28-{kind}.toml")
        .read_text()
        .replace("repetitions = 1", "repetitions = 3")
    )
    run = initialize_run_set(config, tmp_path / "runs", run_set_id="multiple-repetitions")
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), registry())
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert len(records) == sum(len(result.records) for result in results)
    if kind == "qualification":
        assert len(results) == 4 and len(records) == 12
        assert all(len(result.records) == 3 for result in results)
        assert all(r["status"] == "PASS" and not r["eligibility"] for r in records)
        assert {r["repetition_index"] for r in records} == {0, 1, 2}
    else:
        assert len(results) == len(records) == 8
        assert all(len(result.records) == 1 for result in results)
        assert all(r["status"] == "UNSUPPORTED" and r["repetition_index"] is None for r in records)
