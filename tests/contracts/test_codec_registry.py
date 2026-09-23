import json
from pathlib import Path

import pytest

from tscompbench.codecs import (
    CodecContractError,
    CodecRegistry,
    SourceRegistry,
    classify_logical_entries,
    validate_onboarding_card,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _registries() -> tuple[SourceRegistry, CodecRegistry]:
    sources = SourceRegistry(PROJECT_ROOT / "registry" / "sources")
    return sources, CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources)


def test_codec_manifests_reference_audited_sources_and_have_stable_ids() -> None:
    sources, codecs = _registries()
    assert len(codecs) == 30
    assert "alp" in codecs.keys()
    assert "alp-rd" in codecs.keys()
    assert "serf-qt" in codecs.keys()
    assert "serf-xor" in codecs.keys()
    assert "neats-lossless-i64" in codecs.keys()
    assert "leats-lossless-i64" in codecs.keys()
    assert "bzip2-stream" in codecs.keys()
    assert "sprintz-fire-huff0" in codecs.keys()
    assert "sprintz-delta" in codecs.keys()
    assert "sprintz-fire" in codecs.keys()
    assert "sprintz-delta-u8" in codecs.keys()
    assert "sprintz-fire-u8" in codecs.keys()
    assert "huff0" in codecs.keys()
    assert "fse" in codecs.keys()
    assert "lzsse2-raw" in codecs.keys()
    assert "lzsse8-raw" in codecs.keys()
    assert "lzss-raw" in codecs.keys()
    assert "lzss-dipperstein-c" in codecs.keys()
    assert "xz-stream" in codecs.keys()
    assert "deflate-zlib" in codecs.keys()
    assert "brotli-stream" in codecs.keys()
    assert "lz4-frame" in codecs.keys()
    assert "zstd-frame" in codecs.keys()
    assert "snappy-raw" in codecs.keys()
    assert "delta-varint" in codecs.keys()
    first = {item.key: item.algorithm_id for item in codecs.verify_all()}
    second = {
        item.key: item.algorithm_id
        for item in CodecRegistry(PROJECT_ROOT / "registry" / "codecs", sources).verify_all()
    }
    assert first == second
    assert all(codecs.get(key).source_artifact_id in sources for key in codecs.keys())


def test_all_221_logical_source_entries_are_classified_without_auto_qualification() -> None:
    sources, codecs = _registries()
    report = classify_logical_entries(
        sources.catalog, codecs.root / "logical_classification_rules.json"
    )
    assert report["entry_count"] == 221
    assert len({item["classification_id"] for item in report["entries"]}) == 221
    assert all(
        item["independent_algorithm_decision"]
        in {"PENDING_SOURCE_ONBOARDING_REVIEW", "REFERENCE_ONLY_NO_ALGORITHM_ID"}
        for item in report["entries"]
    )
    assert (
        json.loads((PROJECT_ROOT / "registry" / "sources" / "source_catalog.json").read_text())[
            "summary"
        ]["clean_repository_count"]
        == 71
    )


def test_source_onboarding_requires_build_lifecycle_and_license_evidence() -> None:
    card = {
        "schema_version": "tscb.source-onboarding.v2",
        "source_artifact_id": "v2:source-artifact:sha256:" + "0" * 64,
        "repository": "example/codec",
        "commit": "1" * 40,
        "dirty": False,
        "submodules": [],
        "implementation_files": ["src/codec.c"],
        "public_api_files": ["include/codec.h"],
        "benchmark_files": ["bench/bench.c"],
        "test_files": ["tests/test.c"],
        "license_files": ["LICENSE"],
        "third_party_dependencies": [],
        "object_level_candidates": ["P1_STANDALONE_CODEC"],
        "input_contract": {"dtype": "bytes"},
        "output_contract": {"used_length": True},
        "lifecycle_contract": {
            "output_bound": "codec_bound",
            "return_length": "return_value",
            "error_codes": ["DST_TOO_SMALL"],
            "finalize": "REQUIRED",
            "reset": "REQUIRED",
        },
        "stream_components": ["header", "payload", "footer"],
        "upstream_tests": [{"status": "PASS", "log_sha256": "2" * 64}],
        "builds": [
            {
                "kind": "release",
                "artifact_sha256": "3" * 64,
                "compile_commands_sha256": "4" * 64,
            }
        ],
        "license_decision": {"status": "RUN_ALLOWED"},
        "known_limitations": [],
        "unsupported_reason_codes": [],
    }
    first = validate_onboarding_card(card)
    assert first["source_onboarding_id"] == validate_onboarding_card(first)["source_onboarding_id"]
    with pytest.raises(CodecContractError, match="license-blocked"):
        validate_onboarding_card({**card, "license_decision": {"status": "BLOCKED"}})
