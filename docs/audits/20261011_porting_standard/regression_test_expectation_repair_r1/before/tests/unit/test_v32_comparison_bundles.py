"""Contract checks for committed scientific bundles, without codec execution."""

import importlib.util
import json
from pathlib import Path

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
from tscompbench.datasets import DatasetRegistry
from tscompbench.datasets.canonical import read_canonical, semantic_content_sha256
from tscompbench.measurement.v32_protocol import MeasurementProtocol

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "registry/comparison_datasets/v32_20261010"
EXPECTED_GROUPS = {
    "g-byte-ll": ({"lz4-frame", "zstd-frame", "snappy-raw"}, set(), 12),
    "g-float-ll-f64": (
        {"alp", "alp-rd", "chimp", "chimp128", "elf", "elf-plus", "elf-star", "self-star"},
        {"lz4-frame", "zstd-frame"},
        40,
    ),
    "g-int-ll-i16": (
        {
            "sprintz-delta",
            "sprintz-fire",
            "sprintz-fire-huff0",
            "neats-lossless-i64",
            "leats-lossless-i64",
        },
        {"lz4-frame", "zstd-frame"},
        28,
    ),
    "g-float-abs": ({"serf-qt", "serf-xor", "zfp-accuracy-1d"}, set(), 12),
}


@pytest.mark.parametrize("revision", [1, 2])
@pytest.mark.parametrize("name", EXPECTED_GROUPS)
def test_committed_bundle_freezes_every_promised_member_and_full_matrix(name, revision):
    suffix = "" if revision == 1 else "-v2"
    raw = load_comparison_bundle(ROOT / "configs/comparisons" / f"{name}-v32-20261010{suffix}.json")
    members, references, count = EXPECTED_GROUPS[name]
    group = GroupSpec.from_document(raw["group"])
    assert {r["codec_key"] for r in raw["group"]["members"] if r["role"] == "CORE"} == members
    assert {
        r["codec_key"] for r in raw["group"]["members"] if r["role"] == "REFERENCE"
    } == references
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    plan = compile_group_plan(
        group,
        ComparisonContract.from_document(raw["contract"]),
        CorpusSpec.from_document(raw["corpus"]),
        MethodConfigMap.from_document(raw["config_map"]),
        ExpectedOutcomeMatrix.from_document(raw["expected_matrix"]),
        codec_registry=codecs,
        active_codec_keys=set(
            json.loads((ROOT / "registry/algorithm_scope.json").read_text())["registered_codecs"]
        ),
    )
    assert len(plan.cells) == plan.denominators["all_cells"] == count
    assert plan.denominators["core_cells"] == len(members) * 4
    assert plan.denominators["independent_real_sources"] == 2
    assert all(cell.to_document()["expected"]["outcome"] == "PASS" for cell in plan.cells)
    assert raw["protocol"]["outer_repetitions"] == 8
    assert raw["protocol"]["encode_min_ns"] == raw["protocol"]["decode_min_ns"] == 50_000_000
    protocol = MeasurementProtocol.from_document(raw["protocol"])
    assert protocol.protocol_id == raw["contract"]["measurement_protocol_id"]
    if revision == 2:
        assert protocol.thread_monitor_interval_ns == 1_000_000


@pytest.mark.parametrize("name", EXPECTED_GROUPS)
def test_real_content_and_auxiliary_content_are_frozen_and_disjoint(name):
    raw = load_comparison_bundle(ROOT / "configs/comparisons" / f"{name}-v32-20261010.json")
    datasets = DatasetRegistry(REGISTRY, ROOT)
    rows = {r["dataset_id"]: r for r in raw["corpus"]["datasets"]}
    assert set(raw["dataset_bindings"]) == set(rows)
    auxiliary = [raw["development_dataset"], *raw["qualification_datasets"]]
    observed = set()
    for dataset_id, key in raw["dataset_bindings"].items():
        manifest = datasets.load(key, verify_source=False)
        assert manifest.dataset_id == dataset_id
        assert (
            manifest.document["expected"]["semantic_content_sha256"]
            == rows[dataset_id]["logical_content_id"]
        )
        if manifest.source_path.is_file():
            artifact = read_canonical(manifest.source_path, include_buffers=False)
            assert (
                semantic_content_sha256(artifact.metadata) == rows[dataset_id]["logical_content_id"]
            )
        notes = json.loads(manifest.document["source"]["notes"])
        assert notes["generation_spec"]["row_start"] == 0
        assert notes["generation_spec"]["row_stop"] in {966, 8192}
        assert notes["source_lineage_authentication"] == (
            "LOCAL_MANIFEST_ONLY_NOT_EXTERNALLY_AUTHENTICATED"
        )
        observed.add(rows[dataset_id]["logical_content_id"])
    patterns = set()
    for key in auxiliary:
        manifest = datasets.load(key, verify_source=False)
        assert manifest.document["expected"]["semantic_content_sha256"] not in observed
        assert manifest.document["split"]["policy"] == "VALIDATION"
        notes = json.loads(manifest.document["source"]["notes"])
        if key in raw["qualification_datasets"]:
            patterns.add(notes["generation_spec"]["pattern"])
    assert patterns == {"constant", "linear", "periodic", "random"}
    assert len(raw["qualification_datasets"]) == 8


def test_integer_views_have_full_source_domain_evidence_without_quantization():
    for key, count, maximum in (
        ("v32_pems04_i16_mts", 5_216_544, "919.0"),
        ("v32_national_illness_i16_mts", 1932, "24097"),
    ):
        doc = json.loads((REGISTRY / f"{key}.json").read_text())
        proof = json.loads(doc["source"]["notes"])["domain_proof"]
        assert proof["full_source_selected_feature_values"] == count
        assert proof["integral"] and proof["exact_round_trip"]
        assert proof["lossy_transform"] is False
        assert proof["maximum"] == maximum
        assert set(c["dtype"] for c in doc["logical"]["value_columns"]) == {"<i2"}


def test_thread_monitor_revision_keeps_original_objects_and_changes_protocol_identity():
    first = load_comparison_bundle(ROOT / "configs/comparisons/g-byte-ll-v32-20261010.json")
    second = load_comparison_bundle(ROOT / "configs/comparisons/g-byte-ll-v32-20261010-v2.json")
    assert first["dataset_bindings"] == second["dataset_bindings"]
    assert first["corpus"]["datasets"] == second["corpus"]["datasets"]
    assert first["group"]["members"] == second["group"]["members"]
    assert first["protocol"]["protocol_id"] != second["protocol"]["protocol_id"]
    assert (
        first["contract"]["measurement_protocol_id"]
        != second["contract"]["measurement_protocol_id"]
    )


def test_bundle_generator_refuses_to_replace_a_frozen_document(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "v32_bundle_builder", ROOT / "tools/build_v32_comparison_bundles.py"
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    target = tmp_path / "frozen.json"
    helper.write_or_verify(target, {"threshold": "0.001"})
    original = target.read_bytes()
    helper.write_or_verify(target, {"threshold": "0.001"})
    with pytest.raises(ValueError, match="refusing to overwrite"):
        helper.write_or_verify(target, {"threshold": "0.01"})
    assert target.read_bytes() == original
