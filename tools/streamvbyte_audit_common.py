"""Current-source checks shared by legacy and modern Stream VByte run audits."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from tscompbench.adapters.factory import adapter_artifacts
from tscompbench.codecs import CodecRegistry, validate_onboarding_card
from tscompbench.ids import canonical_json_bytes


def formal_direction_durations_satisfied(timing: dict, minimum_ns: int = 1_000_000_000) -> bool:
    """Audit actual selected nanoseconds independently of the recorded PASS flag."""
    return timing.get('min_duration_satisfied') is True and all(
        type(timing.get(f'selected_{direction}_wall_ns')) is int
        and timing[f'selected_{direction}_wall_ns'] >= minimum_ns
        for direction in ('encode', 'decode')
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_run_provenance(run: Path, manifest, source: dict, runtime_digest: str) -> None:
    codec_snapshot = json.loads((run / "codec_registry_snapshot.json").read_text())
    matches = [item for item in codec_snapshot["codecs"] if item["key"] == manifest.key]
    assert len(matches) == 1
    assert matches[0]["algorithm_id"] == manifest.algorithm_id
    assert matches[0]["manifest"] == manifest.document
    source_snapshot = json.loads((run / "source_registry_snapshot.json").read_text())
    matches = [
        item for item in source_snapshot["sources"] if item["identity"] == source["identity"]
    ]
    assert len(matches) == 1
    assert matches[0] == source
    tasks = [json.loads(line) for line in (run / "task_plan.jsonl").read_text().splitlines()]
    assert tasks
    for task in tasks:
        assert task["algorithm_id"] == manifest.algorithm_id
        assert task["execution"]["artifact_sha256"] == runtime_digest
        assert task["execution"]["actual_isa"] == "SSE4_1"
        assert task["execution"]["fallback_used"] is False
    for layer in range(2, 6):
        assert list(run.glob(f"layer{layer}-*.json"))


def audit_summary(run: Path) -> None:
    """Recompute basic per-repetition statistics independently from raw evidence."""
    records = [json.loads(line) for line in (run / "run_components.jsonl").read_text().splitlines()]
    report = json.loads((run / "report/report.json").read_text())
    assert report["source_hashes"]["run_components.jsonl"] == sha(run / "run_components.jsonl")
    for filename, digest in report["derived_artifact_hashes"].items():
        assert sha(run / filename) == digest
    accepted = [r for r in records if r["eligibility"]]
    assert report["eligible_run_count"] == len(accepted)
    covered_ids = []
    for summary in report["summaries"]:
        selected = [
            r
            for r in accepted
            if r["dataset_id"] == summary["dataset_id"] and r["config_id"] == summary["config_id"]
        ]
        assert len(selected) == summary["n"] >= 10
        assert set(summary["run_ids"]) == {r["run_id"] for r in selected}
        covered_ids += summary["run_ids"]
        assert set(summary["bitstream_sha256s"]) == {r["bitstream_sha256"] for r in selected}
        assert {r["accounting"]["final_bits"] for r in selected} == {summary["final_bits"]}
        for prefix, field in (
            ("encode", "selected_encode_wall_ns"),
            ("decode", "selected_decode_wall_ns"),
            ("core_encode", "core_encode_wall_ns"),
            ("core_decode", "core_decode_wall_ns"),
        ):
            values = [r["timing"][field] / r["timing"]["inner_iterations"] for r in selected]
            assert math.isclose(
                summary[prefix + "_ns_mean"], statistics.mean(values), rel_tol=1e-12
            )
            assert math.isclose(
                summary[prefix + "_ns_median"], statistics.median(values), rel_tol=1e-12
            )
            assert math.isclose(summary[prefix + "_ns_sd"], statistics.stdev(values), rel_tol=1e-12)
    assert Counter(covered_ids) == Counter(r["run_id"] for r in accepted)


def audit_source(root: Path, registry: CodecRegistry, manifest) -> dict:
    key = manifest.key
    modern = "modern" in key
    adapter = root / ("adapters/streamvbyte_modern" if modern else "adapters/streamvbyte")
    source = registry.sources.get(manifest.source_artifact_id)
    assert source["license"]["status"] == "RUN_ALLOWED"
    assert source["license"]["spdx"] == ("Apache-2.0 AND BSD-3-Clause" if modern else "Apache-2.0")
    closure = source["build"]["source_closure"]
    for entry in closure:
        assert sha(root / entry["path"]) == entry["sha256"]
    assert (
        hashlib.sha256(canonical_json_bytes(closure)).hexdigest()
        == (source["identity"]["source_closure_sha256"])
    )
    if modern:
        assert source["identity"]["commit"] == "7c472d7d4d63c8bc65a88f310ccfc695a0eaf1ce"
        assert source["identity"]["repository"] == "https://github.com/fast-pack/streamvbyte"
        assert [entry["path"] for entry in source["identity"]["patch_series"]] == (
            source["build"]["patches"]
        )
        for entry in source["identity"]["patch_series"]:
            assert sha(root / entry["path"]) == entry["sha256"]
    else:
        assert sha(root / source["build"]["patches"][0]) == source["identity"]["patch_sha256"]
    artifact, supports = adapter_artifacts(root, manifest)
    runtime_digest = hashlib.sha256(
        canonical_json_bytes(
            [
                {"role": "PRIMARY_ADAPTER", "sha256": sha(artifact)},
                *[
                    {"role": f"SUPPORTING_COMPONENT_{index}", "sha256": sha(path)}
                    for index, path in enumerate(supports)
                ],
            ]
        )
    ).hexdigest()
    card = validate_onboarding_card(
        json.loads((root / f"registry/onboarding/{key}.json").read_text())
    )
    assert card["source_artifact_id"] == manifest.source_artifact_id
    native_path = root / (
        "build/source-audits/streamvbyte-modern-native-tests.json"
        if modern
        else "build/source-audits/streamvbyte-native-tests.json"
    )
    native = json.loads(native_path.read_text())
    assert native["status"] == "PASS"
    assert native["original_api_equivalence_vectors"] == (834 if modern else 278)
    assert native["driver_sha256"] == sha(adapter / "tests/run_native_tests.py")
    assert native["native_test_sha256"] == sha(root / "adapters/streamvbyte/tests/abi_smoke.c")
    assert native["native_stage_test_sha256"] == sha(
        root / "adapters/streamvbyte/tests/stages_smoke.c"
    )
    assert len(native["native_executables"]) == 6 and len(native["stage_executables"]) == 3
    assert all(
        item["returncode"] == 0
        for item in native["native_executables"] + native["stage_executables"]
    )
    if modern:
        assert native["source_lock_sha256"] == sha(adapter / "SOURCE_LOCK.json")
        assert native["shim_count_stripped_equivalence"] == "PASS"
        upstream = native["upstream_tests"]
        assert len(upstream) == 6
        assert {(item["source_kind"], item["profile"]) for item in upstream} == {
            (kind, profile)
            for kind in ("original", "patched")
            for profile in ("release", "debug", "sanitizer")
        }
        for item in upstream:
            original_failure = item["source_kind"] == "original" and item["profile"] == "sanitizer"
            assert item["returncode"] == (1 if original_failure else 0)
            if original_failure:
                assert "streamvbyte_zigzag.c" in item["stderr"]
                assert "signed integer overflow" in item["stderr"]
    assert len(card["upstream_tests"]) == 1
    for test in card["upstream_tests"]:
        assert test["status"] == "PASS" and sha(root / test["evidence"]) == test["log_sha256"]
    assert {build["kind"] for build in card["builds"]} == {"release", "debug", "sanitizer"}
    for build in card["builds"]:
        directory = artifact.parent.parent / build["kind"]
        record = json.loads((directory / "build-record.json").read_text())
        assert (
            sha(directory / artifact.name) == build["artifact_sha256"] == record["artifact_sha256"]
        )
        assert record["compile_commands_sha256"] == build["compile_commands_sha256"]
        qualified = next(
            item
            for item in native["builds"]
            if item["algorithm"] == key and item["profile"] == build["kind"]
        )
        assert qualified == record
        assert (
            record["source_files"]
            and record["binding_sources"]
            and record["compiled_source_closure"]
        )
        for entry in (
            record["source_files"] + record["binding_sources"] + record["compiled_source_closure"]
        ):
            assert sha(root / entry["path"]) == entry["sha256"]
        command = json.loads((directory / "compile-command.json").read_text())
        assert (
            hashlib.sha256(canonical_json_bytes(command)).hexdigest()
            == build["compile_commands_sha256"]
        )
        assert command["runtime_fallback"] is False
        assert command["upstream_encoder"] == ("SSE4_1_WITH_SCALAR_TAIL" if modern else "SCALAR")
        assert command["upstream_decoder"] == "SSE4_1_WITH_SCALAR_TAIL"
    return {"runtime_digest": runtime_digest, "source": source, "card": card}
