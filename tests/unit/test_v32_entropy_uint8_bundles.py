"""Frozen entropy/uint8 task contracts and bytes, without native codec execution."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry, descriptor_from_dataset, negotiate
from tscompbench.comparison import (
    ComparisonContract,
    CorpusSpec,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    compile_group_plan,
)
from tscompbench.comparison.runner import load_comparison_bundle
from tscompbench.contracts import BenchmarkTrack, CapabilityStatus
from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.datasets.canonical import read_canonical, semantic_content_sha256

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "registry/comparison_datasets/v32_20261010"
GROUPS = {
    "entropy": ("g-byte-entropy-ll", {"fse", "huff0", "lz4-frame", "zstd-frame"}),
    "u8": ("g-uint8-ll", {"sprintz-delta-u8", "sprintz-fire-u8", "lz4-frame", "zstd-frame"}),
}


def _bundle(group):
    name, _ = GROUPS[group]
    return load_comparison_bundle(ROOT / "configs/comparisons" / f"{name}-v32-20261010-v2.json")


def _notes(manifest):
    return json.loads(manifest.document["source"]["notes"])


@pytest.mark.parametrize("group", GROUPS)
def test_new_groups_keep_all_four_complete_methods_and_two_independent_sources(group):
    bundle = _bundle(group)
    _, members = GROUPS[group]
    assert {member["codec_key"] for member in bundle["group"]["members"]} == members
    assert {member["role"] for member in bundle["group"]["members"]} == {"CORE"}
    contract = ComparisonContract.from_document(bundle["contract"])
    assert contract.to_document()["fidelity"]["kind"] == "LOSSLESS"
    assert contract.to_document()["cost_boundary"] == "SCHEMA_BOUND_OBJECT"
    assert contract.to_document()["timing_boundary"] == "PIPELINE"
    assert contract.to_document()["resources"]["threads"] == 1
    assert len(bundle["cpu_affinity"]) == 1
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    plan = compile_group_plan(
        GroupSpec.from_document(bundle["group"]),
        contract,
        CorpusSpec.from_document(bundle["corpus"]),
        MethodConfigMap.from_document(bundle["config_map"]),
        ExpectedOutcomeMatrix.from_document(bundle["expected_matrix"]),
        codec_registry=registry,
        active_codec_keys=set(
            json.loads((ROOT / "registry/algorithm_scope.json").read_text())["registered_codecs"]
        ),
    )
    assert len(plan.cells) == plan.denominators["all_cells"] == 16
    assert plan.denominators["core_expected_pass_cells"] == 16
    assert plan.denominators["independent_real_sources"] == 2
    assert len(bundle["corpus"]["datasets"]) == 4
    assert "4096" in bundle["corpus"]["selection_rule"]
    assert "8192" in bundle["corpus"]["exclusion_rule"]
    assert "before measurement" in bundle["corpus"]["exclusion_rule"]


@pytest.mark.parametrize("group", GROUPS)
def test_every_original_object_is_in_each_registered_complete_codec_domain(group):
    bundle = _bundle(group)
    datasets = DatasetRegistry(REGISTRY, ROOT)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    configurations = {
        row["member_id"]: row["configs"][0] for row in bundle["config_map"]["members"]
    }
    for key in bundle["dataset_bindings"].values():
        dataset = load_dataset(datasets.load(key))
        descriptor = descriptor_from_dataset(dataset, BenchmarkTrack.VALUE)
        assert descriptor.canonical_raw_bits <= 131072 * 8
        for member, config in configurations.items():
            assert (
                negotiate(registry.get(member), descriptor, parameters=config["parameters"]).status
                is not CapabilityStatus.UNSUPPORTED
            )
        expected_rows = 4096 if group == "entropy" else 4096 * 8 * (1 if "_c1" in key else 4)
        assert dataset.n_rows == expected_rows


def test_uint8_original_is_exact_column_order_bytes_with_explicit_task_identity():
    bundle = _bundle("u8")
    datasets = DatasetRegistry(REGISTRY, ROOT)
    originals = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    source_cache = {}
    for key in bundle["dataset_bindings"].values():
        manifest = datasets.load(key)
        notes = _notes(manifest)
        spec, proof = notes["generation_spec"], notes["domain_proof"]
        assert spec["original_comparison_object"] == "UINT8_BYTE_STREAM"
        assert spec["floating_object_recovery_claim"] is False
        assert spec["model_symbol_task"] is False
        assert spec["row_start"] == 0 and spec["row_stop"] == 4096
        assert proof["allowed_range"] == [0, 255]
        assert proof["logical_rank"] == proof["logical_channels"] == 1
        assert 0 <= proof["actual_minimum"] <= proof["actual_maximum"] <= 255
        source_key = spec["source_key"]
        if source_key not in source_cache:
            source_cache[source_key] = load_dataset(originals.load(source_key))
        source = source_cache[source_key]
        assert spec["parent_dataset_id"] == source.dataset_id
        assert spec["parent_file_sha256"] == source.manifest.document["file"]["sha256"]
        assert spec["source_manifest"] == str(source.manifest.path.relative_to(ROOT))
        selected = {column.name: column for column in source.values}
        expected = b"".join(
            selected[name].array[:4096].tobytes() for name in spec["selected_columns"]
        )
        dataset = load_dataset(manifest)
        assert len(dataset.values) == 1 and dataset.values[0].array.dtype == np.dtype("u1")
        assert dataset.logical_descriptor["topology"] == "UTS"
        assert dataset.values[0].array.tobytes() == expected
        assert proof["byte_count"] == len(expected)


@pytest.mark.parametrize("group", GROUPS)
def test_development_and_qualification_are_disjoint_and_uint8_covers_full_range(group):
    bundle = _bundle(group)
    datasets = DatasetRegistry(REGISTRY, ROOT)
    real_ids = {row["logical_content_id"] for row in bundle["corpus"]["datasets"]}
    patterns, octets = set(), set()
    for key in [bundle["development_dataset"], *bundle["qualification_datasets"]]:
        manifest = datasets.load(key)
        assert manifest.document["expected"]["semantic_content_sha256"] not in real_ids
        assert manifest.document["split"]["policy"] == "VALIDATION"
        if key in bundle["qualification_datasets"]:
            patterns.add(_notes(manifest)["generation_spec"]["pattern"])
        if group == "u8":
            dataset = load_dataset(manifest)
            assert len(dataset.values) == 1 and dataset.values[0].array.ndim == 1
            assert dataset.values[0].array.dtype == np.dtype("u1")
            octets.update(int(value) for value in dataset.values[0].array)
    assert patterns == {"constant", "linear", "periodic", "random"}
    if group == "u8":
        assert len(bundle["qualification_datasets"]) == 4
        assert octets == set(range(256))


def test_new_window_objects_preserve_old_manifests_and_use_distinct_identity():
    datasets = DatasetRegistry(REGISTRY, ROOT)
    for source in ("etth1", "weather"):
        for topology in ("uts", "mts"):
            old = datasets.load(f"v32_{source}_f64_{topology}")
            new = datasets.load(f"v32_{source}_f64_{topology}_n4096")
            assert _notes(old)["generation_spec"]["row_stop"] == 8192
            assert _notes(new)["generation_spec"]["row_stop"] == 4096
            assert old.dataset_id != new.dataset_id
            assert (
                old.document["expected"]["semantic_content_sha256"]
                != new.document["expected"]["semantic_content_sha256"]
            )
        metadata = read_canonical(new.source_path, include_buffers=False).metadata
        assert (
            semantic_content_sha256(metadata) == new.document["expected"]["semantic_content_sha256"]
        )


def test_bundle_tool_refuses_to_replace_new_frozen_group(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "entropy_uint8_builder", ROOT / "tools/build_v32_comparison_bundles.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    target = tmp_path / "frozen.json"
    original = _bundle("u8")
    helper.write_or_verify(target, original)
    raw = target.read_bytes()
    altered = dict(original, seed=1)
    with pytest.raises(ValueError, match="refusing to overwrite"):
        helper.write_or_verify(target, altered)
    assert target.read_bytes() == raw
