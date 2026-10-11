"""Frozen new groups keep typed tasks, guarantees and full denominators distinct."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.comparison import (
    ComparisonContract,
    CorpusSpec,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    compile_group_plan,
)
from tscompbench.comparison.runner import load_comparison_bundle
from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.datasets.canonical import read_canonical, semantic_content_sha256
from tscompbench.measurement.v32_protocol import MeasurementProtocol

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "registry/comparison_datasets/v32_20261010"
SPEC = importlib.util.spec_from_file_location(
    "build_v32_comparison_bundles", ROOT / "tools/build_v32_comparison_bundles.py"
)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
REBIND_SPEC = importlib.util.spec_from_file_location(
    "rebind_v32_comparison_sources", ROOT / "tools/rebind_v32_comparison_sources.py"
)
source_rebind = importlib.util.module_from_spec(REBIND_SPEC)
REBIND_SPEC.loader.exec_module(source_rebind)


def load(group):
    return load_comparison_bundle(ROOT / f"configs/comparisons/{group}-v32-20261010-v5.json")


def compile_bundle(raw):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    return compile_group_plan(
        GroupSpec.from_document(raw["group"]),
        ComparisonContract.from_document(raw["contract"]),
        CorpusSpec.from_document(raw["corpus"]),
        MethodConfigMap.from_document(raw["config_map"]),
        ExpectedOutcomeMatrix.from_document(raw["expected_matrix"]),
        codec_registry=registry,
        active_codec_keys=set(
            json.loads((ROOT / "registry/algorithm_scope.json").read_text())["registered_codecs"]
        ),
    )


def test_quality_three_point_grid_is_empirical_and_keeps_every_cell():
    raw = load("g-quality")
    raw, proof = source_rebind.rebind_document(ROOT, raw, "integration-source-quality-r1")
    assert proof["formal_results_transferred"] is False
    assert raw["contract"]["fidelity"] == {
        "kind": "QUALITY_CURVE",
        "error_metric": None,
        "threshold": None,
        "unit": "ORIGINAL_VALUE_UNITS",
        "quality_metrics": ["RMSE_V1", "MAXAE_V1"],
    }
    assert raw["contract"]["selection_policy"]["kind"] == "FULL_GRID"
    configs = {member["member_id"]: member["configs"] for member in raw["config_map"]["members"]}
    assert set(configs) == {"abba", "fabba"}
    assert all(len(points) == 3 for points in configs.values())
    assert all(
        point["loss_mode"] == "UNBOUNDED_LOSSY" for points in configs.values() for point in points
    )
    assert all(
        point["guarantee"]["kind"] == "UNBOUNDED" for points in configs.values() for point in points
    )
    assert all(
        point["guarantee"]["original_domain_total"] is False
        for points in configs.values()
        for point in points
    )
    plan = compile_bundle(raw)
    assert len(plan.cells) == plan.denominators["core_expected_pass_cells"] == 24
    assert plan.denominators["independent_real_sources"] == 2
    assert {point["parameters"]["compression_tolerance"] for point in configs["abba"]} == {
        "0.01",
        "0.1",
        "1",
    }
    assert {point["parameters"]["tolerance"] for point in configs["fabba"]} == {"0.01", "0.1", "1"}


def test_model_common_symbol_domain_and_equal_three_thread_budget():
    raw = load("g-byte-model")
    assert raw["contract"]["fidelity"]["kind"] == "LOSSLESS"
    assert raw["contract"]["resources"]["threads"] == 3
    assert raw["cpu_affinity"] == [0, 2, 4]
    assert raw["contract"]["resources"]["memory_limit_bytes"] == 8_589_934_592
    protocol = MeasurementProtocol.from_document(raw["protocol"])
    assert protocol.max_trial_wall_ns == 900_000_000_000
    assert protocol.max_total_wall_ns == 7_200_000_000_000
    assert protocol.max_inner_iterations == 8
    assert protocol.outer_repetitions == 4
    members = {member["codec_key"]: member["role"] for member in raw["group"]["members"]}
    assert members == {
        "deepzip": "CORE",
        "dzip": "CORE",
        "lz4-frame": "REFERENCE",
        "zstd-frame": "REFERENCE",
    }
    plan = compile_bundle(raw)
    assert len(plan.cells) == 16
    assert plan.denominators["core_expected_pass_cells"] == 8
    assert plan.denominators["independent_real_sources"] == 2
    assert all(cell.to_document()["expected"]["outcome"] == "PASS" for cell in plan.cells)


@pytest.mark.parametrize("group", ["g-quality", "g-byte-model"])
def test_test_and_development_objects_remain_logically_disjoint(group):
    raw = load(group)
    datasets = DatasetRegistry(REGISTRY, ROOT)
    tests = {row["logical_content_id"] for row in raw["corpus"]["datasets"]}
    for key in [raw["development_dataset"], *raw["qualification_datasets"]]:
        manifest = datasets.load(key)
        artifact = read_canonical(manifest.source_path, include_buffers=False)
        logical_id = "v2:dataset:sha256:" + semantic_content_sha256(
            artifact.metadata, policy="tscb.dataset-content.v2"
        )
        assert logical_id not in tests
        assert manifest.document["split"]["policy"] == "VALIDATION"
    assert all(row["split"] == "TEST" for row in raw["corpus"]["datasets"])
    if group == "g-quality":
        core = load_comparison_bundle(ROOT / "configs/comparisons/g-float-ll-f64-v32-20261010.json")
        assert raw["dataset_bindings"] == core["dataset_bindings"]


def test_model_datasets_are_base4_symbols_with_explicit_parent_lineage():
    raw = load("g-byte-model")
    datasets = DatasetRegistry(REGISTRY, ROOT)
    original = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    for key in raw["dataset_bindings"].values():
        manifest = datasets.load(key)
        notes = json.loads(manifest.document["source"]["notes"])
        spec = notes["generation_spec"]
        assert spec["floating_object_recovery_claim"] is False
        assert spec["original_comparison_object"] == "UINT8_BASE4_SYMBOL_STREAM"
        assert notes["domain_proof"]["model_training_provenance"].startswith("UNKNOWN")
        data = load_dataset(manifest).values[0].array
        assert data.dtype.str == "|u1"
        assert set(data.tolist()) <= {0, 1, 2, 3}
        source = load_dataset(original.load(spec["source_key"]))
        names = set(spec["selected_columns"])
        payload = b"".join(
            np.asarray(column.array[:32], dtype="<f8").tobytes()
            for column in source.values
            if column.name in names
        )
        assert builder.base4_symbols(payload).tobytes() == data.tobytes()


def test_base4_mapping_is_injective_for_all_256_octets():
    payload = bytes(range(256))
    symbols = builder.base4_symbols(payload).reshape(-1, 4)
    decoded = ((symbols.astype(np.uint16) << [6, 4, 2, 0]).sum(axis=1)).astype("u1")
    assert decoded.tobytes() == payload
    assert symbols.min() == 0 and symbols.max() == 3
    assert builder.base4_symbols(b"").size == 0


def test_model_provenance_preserves_training_unknown_and_complete_frame_cost():
    provenance = json.loads(
        (ROOT / "artifacts/comparisons/v32_20261010/provenance/G-BYTE-MODEL-v5.json").read_text()
    )["scientific_scope"]
    assert provenance["model_original_object"] == "UINT8_BASE4_SYMBOL_STREAM"
    assert provenance["training_overlap"] == (
        "UNKNOWN_FOR_FROZEN_DEEPZIP_MODEL_NO_GENERALIZATION_CLAIM"
    )
    assert provenance["failure_policy"] == "KEEP_ALL_FROZEN_CONFIG_AND_CORPUS_CELLS"
    for key in ("deepzip", "dzip"):
        entry = provenance["model_provenance"][key]
        assert entry["parameters"]
        assert entry["source_artifact_id"]
        assert entry["accounting"] == "COMPLETE_EMBEDDED_NATIVE_MODEL_FRAMES_COUNTED_IN_VALUE_BITS"
        assert entry["separate_model_bucket"] == ("NOT_ALLOCATED_BY_CURRENT_OPAQUE_FRAME_INSPECTOR")
