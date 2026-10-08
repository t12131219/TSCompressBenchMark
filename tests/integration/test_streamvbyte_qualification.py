from __future__ import annotations

import json
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=(False, True))
def modern(request):
    return request.param


def pipeline_key(modern):
    return "delta-zigzag-streamvbyte-modern64" if modern else "delta-zigzag-streamvbyte64"


def config_path(modern, delta=False):
    key = (
        pipeline_key(modern)
        if delta
        else ("streamvbyte-modern-u32" if modern else "streamvbyte-u32")
    )
    return ROOT / f"configs/experiments/{key}-qualification.toml"


def test_streamvbyte_u32_five_layers_with_native_timing_switch(
    tmp_path: Path, modern: bool
) -> None:
    run = initialize_run_set(
        config_path(modern),
        tmp_path / "runs",
        run_set_id="streamvbyte-u32-five-layers",
    )
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), codecs)
    assert len(results) == 2
    assert all(item.preflight.eligible_for_formal_repetitions for item in results)
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    assert all(item["status"] == "PASS" and not item["eligibility"] for item in records)
    assert len({item["bitstream_sha256"] for item in records}) == 1
    for item in records:
        ledger = item["accounting"]
        assert ledger["final_bits"] == ledger["final_physical_bytes"] * 8
        assert ledger["canonical_raw_bits"] == 8193 * 32
        assert ledger["timestamp_bits"] == ledger["padding_bits"] == 0
        assert item["correctness"]["status"] == "PASS" and item["finalize_bytes"] == 0
        assert item["diagnostics"]["codec_telemetry"]["scope"] == "LAST_INNER_ITERATION"
        timing = item["timing"]
        if timing["native_timing_enabled"]:
            assert 0 < timing["native_encode_wall_ns"] <= timing["core_encode_wall_ns"]
            assert 0 < timing["native_decode_wall_ns"] <= timing["core_decode_wall_ns"]
        else:
            assert timing["native_encode_wall_ns"] is timing["native_decode_wall_ns"] is None
    report = report_run_set(run)
    assert report.task_count == 2
    for layer in range(2, 6):
        assert list(run.path.glob(f"layer{layer}-*.json"))


def test_delta64_registered_stage_executor_passes_five_layers(tmp_path: Path, modern: bool) -> None:
    run = initialize_run_set(
        config_path(modern, True),
        tmp_path / "runs",
        run_set_id="delta64-stage-executor-gate",
    )
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), codecs)
    assert len(results) == 1
    assert results[0].preflight.status.value == "PASS"
    assert results[0].preflight.eligible_for_formal_repetitions
    evidence = results[0].preflight.diagnostics["preprocess_stage_validation"]
    assert evidence["status"] == "PASS" and evidence["checked_stages"] == list("ABCD")
    assert all(item.record_kind == "FORMAL_REPETITION" for item in results[0].records)
    records = [
        json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()
    ]
    for record in records:
        stages = record["timing"]["pipeline_stage_timings"]
        assert stages["scope"] == "ALL_INNER_ITERATIONS"
        for direction in ("encode", "decode"):
            for stage in stages[direction]["stages"].values():
                assert stage["observation_count"] == record["timing"]["inner_iterations"]
                assert stage["wall_ns"] > 0
        assert (
            sum(stage["final_contribution_bits"] for stage in stages["encode"]["stages"].values())
            == record["accounting"]["final_bits"]
        )
    report_run_set(run)


def test_unregistered_stage_executor_is_still_gated(tmp_path: Path, modern: bool) -> None:
    import copy
    from dataclasses import replace

    from tscompbench.adapters.factory import create_adapter
    from tscompbench.datasets.canonical import read_canonical
    from tscompbench.execution.preflight import preflight_task
    from tscompbench.runner import plan_run_set, prepare_run_set

    run = initialize_run_set(
        config_path(modern, True),
        tmp_path / "runs",
        run_set_id="unregistered-stage-executor",
    )
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    prepare_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT))
    tasks = plan_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), codecs)
    # Admission is bound to the reviewed stage specification, not just a callable hook.
    manifest = codecs.get(pipeline_key(modern))
    document = copy.deepcopy(manifest.document)
    document["semantics"]["preprocess_stages"][0]["parameters"]["seed"] = "UNKNOWN_SEED"
    changed = replace(manifest, document=document)
    artifact = read_canonical(next((run.path / "datasets").glob("*/*.canonical.tscb")))
    result, _ = preflight_task(
        tasks[0],
        changed,
        codecs.sources.get(manifest.source_artifact_id),
        artifact,
        create_adapter(ROOT, manifest),
        {},
    )
    assert result.reason_code == "PREPROCESS_EXECUTOR_NOT_REGISTERED"


def test_disabled_wrapper_remains_a_structured_configuration_rejection(
    tmp_path: Path, modern: bool
) -> None:
    config = tmp_path / "disabled-stage-d.toml"
    config.write_text((config_path(modern, True)).read_text() + "\nstage_d = [false]\n")
    run = initialize_run_set(config, tmp_path / "runs", run_set_id="disabled-wrapper")
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    results = execute_run_set(run, DatasetRegistry(ROOT / "registry/datasets", ROOT), codecs)
    assert len(results) == 1
    assert results[0].preflight.status.value == "SCHEMA_ERROR"
    assert not results[0].preflight.eligible_for_formal_repetitions
    assert all(item.record_kind == "DIAGNOSTIC" for item in results[0].records)
