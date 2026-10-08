"""The worklist must retain the original logical scope and avoid alias inflation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from build_native_integration_plan import (  # noqa: E402
    littleintpacker_admission_review,
    refresh_littleintpacker_entries,
)


def test_selective_source_refresh_preserves_other_worklist_entries_and_scope() -> None:
    document = json.loads((ROOT / "registry/native_integration_plan.json").read_text())
    original = json.loads(json.dumps(document))
    refresh_littleintpacker_entries(document)
    assert len(document["entries"]) == 221
    assert document["scope_counts"] == original["scope_counts"]
    assert document["scope_counts"]["NATIVE_CORE_CANDIDATE"] == 115
    for old, current in zip(original["entries"], document["entries"], strict=True):
        if current["audit_index"] not in {134, 138}:
            assert current == old
        else:
            assert not current["full_logical_entry_qualified"]
            assert current["source_admission_review"]["kernel_audit"]["status"] == "PASS"


def test_source_admission_commit_mismatch_requires_requalification() -> None:
    state, review = littleintpacker_admission_review("0" * 40)
    assert state == "FROZEN_SOURCE_CURRENT_KERNEL_REQUALIFICATION_REQUIRED"
    assert review["status"] == "CURRENT_SOURCE_OR_KERNEL_REQUALIFICATION_REQUIRED"
    assert review["current_qualification_failure"]["reason"]
    assert (
        review["bounded_abi"]
        == review["python_sdk"]
        == review["benchmark_five_layers"]
        == "PENDING"
    )
    assert not review["full_logical_entries_qualified"]


def test_littleintpacker_worklist_records_sdk_and_registry_without_full_qualification() -> None:
    worklist = json.loads((ROOT / "registry/native_integration_plan.json").read_text())
    selected = [entry for entry in worklist["entries"] if entry["audit_index"] in {134, 138}]
    assert len(selected) == 2
    for entry in selected:
        assert entry["state"] in {
            "SYNTHETIC_UINT32_FIVE_LAYERS_PASSED_FORMAL_PENDING",
            "P0_LITTLEINTPACKER_UINT32_SYNTHETIC_UTS_SCOPE_QUALIFIED_OTHER_DATASETS_DOMAINS_PENDING",
        }
        review = entry["source_admission_review"]
        assert review["kernel_audit"]["status"] == "PASS"
        assert review["original_unsafe_probe_count"] == 78
        assert review["patched_api_matrix_cases"] == 56925
        assert review["bounded_abi"] == "QUALIFIED"
        assert review["bounded_abi_audit"]["native_cases"] == 284625
        assert review["bounded_abi_audit"]["native_fault_checks"] == 510
        assert review["python_sdk"] == "QUALIFIED_SCOPED_UINT32_FIXED_AUTO_FIVE_APIS"
        assert review["python_sdk_audit"]["status"] == "PASS"
        assert review["direct_python_sdk_test_count"] == 499
        assert review["direct_python_sdk_imported_file_count"] == 82
        assert review["benchmark_registration"] == "REGISTERED"
        qualification = review["five_layer_qualification_review"]
        assert qualification["status"] == "PASS"
        assert qualification["records"] == 90
        assert qualification["eligible"] == 0
        assert not qualification["full_logical_entries_qualified"]
        if "formal_repetition_review" in review:
            formal = review["formal_repetition_review"]
            assert formal["status"] == "PASS"
            assert formal["records"] == 400
            assert formal["eligible"] >= 200
            assert review["benchmark_five_layers"] == "SYNTHETIC_UINT32_VALUE_UTS_SCOPE_QUALIFIED"
            assert not formal["full_logical_entries_qualified"]
            assert len(entry["current_scope_reviews"]) == 5
            assert all(
                r["qualified_against_current_source"]
                and r["formal_attempts"] == 80
                and r["eligible_repetitions"] >= 40
                and not r["full_logical_entry_qualified"]
                for r in entry["current_scope_reviews"]
            )
        else:
            assert review["benchmark_five_layers"] == (
                "SYNTHETIC_UINT32_QUALIFICATION_PASSED_FORMAL_PENDING"
            )
        assert len(entry["registered_candidates"]) == 5
        assert all(
            c["relationship"] == "WORKBOOK_REPOSITORY_AND_COMMIT_MATCH_SCOPE_NOT_FULL_ENTRY"
            for c in entry["registered_candidates"]
        )
        assert not entry["full_logical_entry_qualified"]


def test_worklist_preserves_every_source_catalog_logical_entry() -> None:
    worklist = json.loads((ROOT / "registry/native_integration_plan.json").read_text())
    catalog = json.loads((ROOT / "registry/sources/source_catalog.json").read_text())
    expected = {
        (e["group"], e["sheet"], int(e["row"]), e["name"], e.get("github_repo"))
        for e in catalog["logical_entries"]
    }
    actual = {
        (e["asset_group"], e["source_sheet"], int(e["source_row"]), e["name"], e["repository"])
        for e in worklist["entries"]
    }
    assert actual == expected
    assert len(actual) == len(worklist["entries"]) == catalog["summary"]["logical_entry_count"]
    for entry in worklist["entries"]:
        if entry["asset_group"] != "TSBench" and entry["source_closure_hint"] in {
            "C",
            "C++",
            "C/C++ header",
            "C++ header",
        }:
            assert entry["scope"] == "NATIVE_CORE_CANDIDATE"
        if entry["asset_group"] == "TSBench":
            assert entry["state"] == "REFERENCE_REVIEW_PENDING"


def test_worklist_candidates_match_current_registry_without_broad_gorilla_aliasing() -> None:
    worklist = json.loads((ROOT / "registry/native_integration_plan.json").read_text())
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    for entry in worklist["entries"]:
        for candidate in entry["registered_candidates"]:
            manifest = codecs.get(candidate["key"])
            assert candidate["algorithm_id"] == manifest.algorithm_id
            assert candidate["source_artifact_id"] == manifest.source_artifact_id
        if entry["name"] in {
            "Generic Delta-of-Delta (D2)",
            "RedisTimeSeries Gorilla implementation",
        }:
            assert "prometheus-xor-chunk" not in {c["key"] for c in entry["registered_candidates"]}
        if entry["repository"] == "fast-pack/FastPFOR" and entry["name"] in {
            "Simple-9",
            "Simple-16",
        }:
            assert entry["audit_index"] == {"Simple-9": 145, "Simple-16": 146}[entry["name"]]
            admission = entry["source_admission_review"]
            assert not entry["full_logical_entry_qualified"]
            if admission["status"] == "CURRENT_SOURCE_OR_NATIVE_REQUALIFICATION_REQUIRED":
                assert entry["state"] == "FROZEN_SOURCE_CURRENT_NATIVE_REQUALIFICATION_REQUIRED"
                assert admission["current_qualification_failure"]["reason"]
            elif admission["python_sdk"] == "CURRENT_REQUALIFICATION_REQUIRED":
                assert entry["state"] == (
                    "SOURCE_BOUNDED_UINT28_ABI_QUALIFIED_"
                    "CURRENT_SDK_AND_FIVE_LAYER_REQUALIFICATION_REQUIRED"
                )
                assert admission["python_sdk_failure"]
                assert admission["bounded_abi_audit"]["status"] == "PASS"
                assert admission["benchmark_five_layers"] == "PENDING"
                assert not entry["current_scope_reviews"]
                assert len(entry["registered_candidates"]) == (
                    1 if entry["name"] == "Simple-16" else 2
                )
            elif admission["status"] == "ORIGINAL_SOURCE_UPSTREAM_BOUNDED_UINT28_AND_SDK_QUALIFIED":
                benchmark_status = admission["benchmark_five_layers"]
                expected_states = {
                    "PENDING": (
                        "SOURCE_UPSTREAM_BOUNDED_UINT28_SDK_QUALIFIED_"
                        "REGISTERED_FIVE_LAYERS_PENDING"
                    ),
                    "SYNTHETIC_UINT28_QUALIFICATION_PASSED_FORMAL_PENDING": (
                        "SYNTHETIC_UINT28_FIVE_LAYERS_PASSED_FORMAL_PENDING"
                    ),
                    "SYNTHETIC_UINT28_VALUE_UTS_SCOPE_QUALIFIED": (
                        "P0_SIMPLE_UINT28_SYNTHETIC_UTS_SCOPE_QUALIFIED_"
                        "OTHER_DATASETS_DOMAINS_PENDING"
                    ),
                }
                assert entry["state"] == expected_states[benchmark_status]
                if benchmark_status != "PENDING":
                    qualification = admission["five_layer_qualification_review"]
                    assert qualification["status"] == "PASS"
                    assert qualification["records"] == 48
                    assert qualification["eligible"] == 0
                    assert not qualification["full_logical_entries_qualified"]
                if benchmark_status == "SYNTHETIC_UINT28_VALUE_UTS_SCOPE_QUALIFIED":
                    formal = admission["formal_repetition_review"]
                    assert formal["status"] == "PASS"
                    assert formal["records"] == 240
                    assert formal["eligible"] >= 120
                    assert not formal["full_logical_entries_qualified"]
                    assert all(
                        r["qualified_against_current_source"]
                        and r["formal_attempts"] == 80
                        and r["eligible_repetitions"] >= 40
                        and not r["full_logical_entry_qualified"]
                        for r in entry["current_scope_reviews"]
                    )
                assert admission["python_sdk"] == "QUALIFIED_SCOPED_UINT28_ONLY"
                assert admission["python_sdk_audit"]["status"] == "PASS"
                assert admission["direct_python_sdk_test_count"] == 322
                assert admission["direct_python_sdk_imported_file_count"] >= 83
                assert admission["full_original_upstream_audit"]["status"] == "PASS"
                assert admission["simple9_original_full_upstream_unit"] == (
                    "RELEASE_ASSERTIONS_ENABLED_QUALIFIED"
                )
                assert {c["key"] for c in entry["registered_candidates"]} == (
                    {"simple16-u28"}
                    if entry["name"] == "Simple-16"
                    else {"simple9-u28", "simple9hacked-u28"}
                )
                assert all(
                    c["relationship"] == "WORKBOOK_REPOSITORY_AND_COMMIT_MATCH_SCOPE_NOT_FULL_ENTRY"
                    for c in entry["registered_candidates"]
                )
            else:
                assert entry["state"] == (
                    "SOURCE_BOUNDED_UINT28_ABI_QUALIFIED_"
                    "SIMPLE9_UPSTREAM_SDK_REGISTRATION_AND_FIVE_LAYERS_PENDING"
                )
                assert admission["bounded_abi_audit"]["status"] == "PASS"
                assert admission["source_api_audit"]["status"] == "PASS"
                assert admission["bounded_native_cases"] == 91350
                assert admission["bounded_native_fault_checks"] == 198
                assert admission["original_unsafe_probe_count"] == 72
                assert admission["input_domain"] == "UINT32_STORAGE_VALUES_0_TO_268435455_ONLY"
                assert admission["original_vendor_file_count"] == 51
                assert not entry["registered_candidates"]
        if entry["name"] == "Delta + Stream VByte":
            qualified = all(
                review["qualified_against_current_source"]
                for review in entry["current_scope_reviews"]
            )
            assert len(entry["current_scope_reviews"]) == 2
            assert entry["state"] == (
                "P2_MODERN_1234_CHECKED_INT64_SCOPE_QUALIFIED_OTHER_API_VARIANTS_PENDING"
                if qualified
                else "REGISTERED_CURRENT_SOURCE_OR_FIVE_LAYER_REQUALIFICATION_REQUIRED"
            )
            assert not entry["full_logical_entry_qualified"]
            candidates = {c["key"]: c for c in entry["registered_candidates"]}
            modern = candidates["delta-zigzag-streamvbyte-modern64"]
            legacy = candidates["delta-zigzag-streamvbyte64"]
            assert modern["source_artifact_id"] != legacy["source_artifact_id"]
            assert modern["relationship"] == (
                "WORKBOOK_REPOSITORY_AND_COMMIT_MATCH_SCOPE_NOT_FULL_ENTRY"
            )
        if entry["name"] == "SIMD Differential Coding":
            assert len(entry["current_scope_reviews"]) == 1
            qualified = entry["current_scope_reviews"][0]["qualified_against_current_source"]
            assert entry["state"] == (
                "P0_D1_UINT32_FOUR_APIS_SCOPE_QUALIFIED_OTHER_DOMAINS_PIPELINES_PENDING"
                if qualified
                else "REGISTERED_CURRENT_SOURCE_OR_FIVE_LAYER_REQUALIFICATION_REQUIRED"
            )
            assert not entry["full_logical_entry_qualified"]
            admission = entry["source_admission_review"]
            if admission["status"] == "CURRENT_NATIVE_OR_SDK_REQUALIFICATION_REQUIRED":
                assert not qualified
                assert admission["current_qualification_failure"]["type"]
                assert admission["current_qualification_failure"]["reason"]
            else:
                assert admission["bounded_cases_per_executable"] == 4160
                assert admission["bounded_executables"] == 6
                assert admission["direct_python_sdk_test_count"] >= 103
            assert admission["benchmark_registration"] == "REGISTERED"
            assert admission["benchmark_five_layers"] == (
                "UINT32_D1_SCOPE_QUALIFIED" if qualified else "REQUALIFICATION_REQUIRED"
            )
        if entry["repository"] == "fast-pack/MaskedVByte":
            (review,) = entry["current_scope_reviews"]
            qualified = review["qualified_against_current_source"]
            plain = entry["name"] == "Masked VByte"
            admission = entry["source_admission_review"]
            if admission["status"] == "CURRENT_NATIVE_OR_SDK_REQUALIFICATION_REQUIRED":
                assert not qualified
                assert (
                    entry["state"]
                    == "REGISTERED_CURRENT_SOURCE_OR_FIVE_LAYER_REQUALIFICATION_REQUIRED"
                )
                assert admission["current_qualification_failure"]["reason"]
                assert admission["benchmark_five_layers"] == "REQUALIFICATION_REQUIRED"
            else:
                assert entry["state"] == (
                    "P0_PLAIN_MASKEDVBYTE_UINT32_SCOPE_QUALIFIED_OTHER_DOMAINS_PENDING"
                    if qualified and plain
                    else "P2_ORIGINAL_MODULAR32_MASKEDVBYTE_SCOPE_QUALIFIED_INT64_TIMESTAMP_PENDING"
                    if qualified
                    else "SOURCE_BOUNDED_ABI_DIRECT_SDK_QUALIFIED_REGISTERED_FIVE_LAYERS_PENDING"
                )
                assert not entry["full_logical_entry_qualified"]
                admission = entry["source_admission_review"]
                assert admission["original_failure_retained"] == "SIGNED_SHIFT_OF_15_BY_28_UBSAN"
                assert admission["bounded_abi"] == "SCOPED_UINT32_PLAIN_AND_MODULAR_DELTA_QUALIFIED"
                assert admission["bounded_cases_per_executable"] == 9360
                assert admission["bounded_executables"] == 6
                assert admission["direct_python_sdk_test_count"] == 159
                assert admission["python_sdk"] == "SCOPED_UINT32_PLAIN_AND_MODULAR_DELTA_QUALIFIED"
                assert admission["benchmark_registration"] == "REGISTERED"
                assert admission["benchmark_five_layers"] == (
                    "P0_PLAIN_UINT32_SCOPE_QUALIFIED"
                    if qualified and plain
                    else "P2_ORIGINAL_MODULAR_UINT32_SCOPE_QUALIFIED"
                    if qualified
                    else "PENDING"
                )
            assert {c["key"] for c in entry["registered_candidates"]} == {
                "maskedvbyte-u32" if entry["name"] == "Masked VByte" else "delta-maskedvbyte-u32"
            }
        if entry["repository"] == "lemire/simdcomp":
            admission = entry["source_admission_review"]
            if admission["status"] == "PATCHED_SOURCE_BOUNDED_ABI_AND_DIRECT_SDK_SCOPE_QUALIFIED":
                qualified = all(
                    r["qualified_against_current_source"] for r in entry["current_scope_reviews"]
                )
                assert entry["state"] == (
                    "UINT32_UTS_P0_P2_SIMDCOMP_SCOPE_QUALIFIED_INT64_OTHER_ISA_PENDING"
                    if qualified
                    else "REGISTERED_SOURCE_ABI_SDK_QUALIFIED_FIVE_LAYERS_PENDING"
                )
                assert admission["python_sdk"] == "QUALIFIED_SCOPED_UINT32_ONLY"
                assert admission["python_sdk_audit"]["status"] == "PASS"
                assert admission["direct_python_sdk_test_count"] == 888
                assert admission["direct_python_sdk_imported_file_count"] >= 80
                assert admission["bounded_abi_audit"]["status"] == "PASS"
                assert admission["checked_int64_timestamp"] == "PENDING"
                assert admission["benchmark_five_layers"] == (
                    "UINT32_UTS_P0_P2_SOURCE_API_SCOPE_QUALIFIED" if qualified else "PENDING"
                )
            elif (
                admission["status"] == "PATCHED_SSE4_1_AVX2_SOURCE_AND_BOUNDED_ABI_SCOPE_QUALIFIED"
            ):
                assert entry["state"] == (
                    "PATCHED_SSE4_1_AVX2_SOURCE_AND_BOUNDED_ABI_SCOPE_"
                    "QUALIFIED_SDK_AND_FIVE_LAYERS_PENDING"
                )
                assert (
                    admission["bounded_abi"] == "SCOPED_UINT32_PLAIN_MODULAR_D1_AND_FOR_QUALIFIED"
                )
                assert admission["bounded_cases_per_executable"] == 31878
                assert admission["bounded_executables"] == 6
                assert admission["bounded_abi_audit"]["status"] == "PASS"
                assert admission["avx2_source_api_audit"]["original_failures_retained"] == 16
                assert admission["python_sdk"] in {"PENDING", "CURRENT_REQUALIFICATION_REQUIRED"}
                assert admission["checked_int64_timestamp"] == "PENDING"
            elif admission["status"] == "PATCHED_SSE4_1_AND_AVX2_SOURCE_API_SCOPE_QUALIFIED":
                assert entry["state"] == (
                    "PATCHED_SSE4_1_AVX2_SOURCE_API_SCOPE_QUALIFIED_"
                    "BOUNDED_ABI_SDK_AND_FIVE_LAYERS_PENDING"
                )
                assert admission["avx2_source_api_audit"]["status"] == "PASS"
                assert admission["bounded_abi"] in {"PENDING", "CURRENT_REQUALIFICATION_REQUIRED"}
            elif admission["status"] == "PATCHED_SSE4_1_SOURCE_API_SCOPE_QUALIFIED":
                assert entry["state"] == (
                    "PATCHED_SSE4_1_SOURCE_API_SCOPE_QUALIFIED_"
                    "OTHER_ISA_BOUNDED_ABI_AND_FIVE_LAYERS_PENDING"
                )
                current = admission["source_api_audit"]
                assert current["status"] == "PASS"
                assert current["original_failures_retained"] == 13
                assert current["query_calls_per_profile"] == 484638
                assert current["guard_cases_per_profile"]["plain"] == 11088
                assert not current["full_logical_entry_qualified"]
                assert admission["bounded_abi"] == admission["python_sdk"] == "PENDING"
            elif admission["status"] == "CURRENT_SOURCE_API_REQUALIFICATION_REQUIRED":
                assert entry["state"] == "FROZEN_SOURCE_CURRENT_API_REQUALIFICATION_REQUIRED"
                assert admission["current_qualification_failure"]["reason"]
            else:
                assert entry["state"] == "FROZEN_SOURCE_UPSTREAM_API_AND_FIVE_LAYERS_PENDING"
            assert entry["source_admission_review"]["original_vendor_file_count"] == 27
            assert entry["source_admission_review"]["benchmark_registration"] == "REGISTERED"
            assert {c["key"] for c in entry["registered_candidates"]} == {
                "simdcomp-u32",
                "delta-simdcomp-u32",
                "for-simdcomp-u32",
            }
            assert all(
                c["relationship"] == "WORKBOOK_REPOSITORY_AND_COMMIT_MATCH_SCOPE_NOT_FULL_ENTRY"
                for c in entry["registered_candidates"]
            )
            assert len(entry["current_scope_reviews"]) == (
                3
                if admission["status"]
                == "PATCHED_SOURCE_BOUNDED_ABI_AND_DIRECT_SDK_SCOPE_QUALIFIED"
                else 0
            )
            assert not entry["full_logical_entry_qualified"]
