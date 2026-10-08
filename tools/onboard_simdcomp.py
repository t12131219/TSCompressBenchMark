"""Register source-qualified uint32 plain P0 and modular D1/fixed-FOR P2 identities."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from audit_simdcomp_sdk import audit, require, sha

from tscompbench.codecs import validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.preprocess.simdcomp import EXECUTOR_IDS, STAGE_SPECS

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/simdcomp"
KEYS = {"simdcomp-u32": "PLAIN", "delta-simdcomp-u32": "DELTA", "for-simdcomp-u32": "FOR"}


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    current = audit()
    require(current["status"] == "PASS", "current source/native/direct SDK evidence required")
    lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    sdk = json.loads((ROOT / "build/source-audits/simdcomp_sdk_tests.json").read_text())
    builds = [
        json.loads((ROOT / f"build/adapters/simdcomp_u32/{p}/build-record.json").read_text())
        for p in ("release", "debug", "sanitizer")
    ]
    patches = builds[0]["patches"]
    identity = {
        "kind": "VENDORED_UPSTREAM_SOURCE_CLOSURE",
        "key": "simdcomp-d530177",
        "repository": lock["repository"],
        "commit": lock["commit"],
        "source_closure_sha256": hashlib.sha256(canonical_json_bytes(lock["files"])).hexdigest(),
        "patch_series": patches,
        "selection": "EXACT_WORKBOOK_SOURCE_BENCHMARK_FORMAT_DIFFERENCES_RETAINED",
        "benchmark_reference": "FastPFOR SIMDBinaryPacking has a different API/wire; "
        "original SIMDComp benchmarks retained as references only",
        "copy_policy": "UNMODIFIED_VENDOR_PLUS_EXPLICIT_BUILD_ONLY_SOURCE_FIXES",
    }
    source_id = stable_id("source-artifact", identity)
    units = [
        "adapters/simdcomp/native/tscb_simdcomp.c",
        "adapters/simdcomp/native/avx2_bridge.c",
        *[
            "adapters/simdcomp/vendor/simdcomp/src/" + name + ".c"
            for name in (
                "simdbitpacking",
                "simdintegratedbitpacking",
                "simdfor",
                "simdcomputil",
                "simdpackedselect",
                "simdpackedsearch",
                "avxbitpacking",
            )
        ],
    ]
    source = {
        "schema_version": "tscb.source-artifact.v2",
        "key": identity["key"],
        "kind": identity["kind"],
        "identity": identity,
        "license": {
            "spdx": "BSD-3-Clause",
            "status": "RUN_ALLOWED",
            "redistribution": "ALLOWED_WITH_LICENSE_NOTICE",
            "files": [lock["license"]["file"]],
        },
        "build": {
            "recipe": "python tools/build_codec.py simdcomp-u32 --profile all",
            "patches": patches,
            "submodules": [],
            "source_closure": lock["files"],
            "translation_units": units,
            "admission_card": "adapters/simdcomp/SOURCE_ADMISSION.md",
        },
    }
    base = json.loads((ROOT / "registry/codecs/maskedvbyte-u32.json").read_text())
    base_card = json.loads((ROOT / "registry/onboarding/maskedvbyte-u32.json").read_text())
    documents, cards = [], []
    for key, coding in KEYS.items():
        pipeline = coding != "PLAIN"
        document = copy.deepcopy(base)
        document["key"] = key
        document["identity"] = {
            "display_name": "SIMDComp (original uint32 primitive)"
            if not pipeline
            else ("Delta" if coding == "DELTA" else "Fixed FOR") + " + SIMDComp (modular uint32)",
            "family": "SIMDCOMP_" + coding + "_UINT32",
            "citations": [
                lock["repository"] + "@" + lock["commit"],
                "adapters/simdcomp/contract.md",
            ],
            "source_artifact_id": source_id,
        }
        document["classification"]["object_level"] = "P2_PIPELINE" if pipeline else "P0_PRIMITIVE"
        document["input"]["timestamp_semantics"]["overflow_policy"] = (
            "MODULAR_UINT32_VALUE_ONLY" if pipeline else "NOT_APPLICABLE_PLAIN_UINT32"
        )
        document["semantics"].update(
            rebuild_protocol="TSCB_SBP1_UINT32_" + coding + "_CHECKED_DESCRIPTOR_V1",
            decodability_profile="SELF_CONTAINED_CHECKED_DESCRIPTOR_SBP1_" + coding,
            preprocess_class="LOSSLESS_SEMANTIC" if pipeline else "NONE",
            preprocess_stages=copy.deepcopy(STAGE_SPECS[key]) if pipeline else [],
        )
        document["lifecycle"].update(
            block_semantics="SSE_128_AVX2_256_EXPLICIT_COUNT_SEED_LAYOUT",
            tail_policy="EXPLICIT_SSE_LENGTH_OR_D1_LAST_VALUE_FOR_BASE_PADDING_SBP1",
        )
        document["execution"]["isa"] = ["SSE4_1", "AVX2"] if not pipeline else ["SSE4_1"]
        apis = (
            ["MASKED", "WITHOUTMASK"]
            if coding == "DELTA"
            else (["LENGTH", "FULL"] if coding == "FOR" else ["LENGTH", "MASKED", "WITHOUTMASK"])
        )
        document["parameters"] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "native_timing": {"type": "boolean", "default": True},
                "api": {
                    "type": "string",
                    "enum": apis,
                    "default": "MASKED" if coding == "DELTA" else "LENGTH",
                },
                "isa": {
                    "type": "string",
                    "enum": document["execution"]["isa"],
                    "default": "SSE4_1",
                },
                "starting_point": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 2**32 - 1 if pipeline else 0,
                    "default": 0,
                },
            },
            "constraints": [
                {
                    "kind": "forbid_combination",
                    "when": {"api": "LENGTH", "isa": "AVX2"},
                    "reason": "AVX2_SOURCE_HAS_NO_LENGTH_API",
                }
            ]
            if not pipeline
            else [],
        }
        document["adapter"] = {
            "backend": "C_ABI_V1",
            "version": "simdcomp-ctypes-v1",
            "factory": "SIMDCOMP_CTYPES_V1",
            "artifact_path": "build/adapters/simdcomp_u32/release/libtscb_simdcomp_u32.so",
            "timing_boundary": "PYTHON_FFI_DESCRIPTOR_SBP1_SCALAR_VALIDATION_STAGING_INCLUDED",
            "native_timing_capability": {
                "optional": True,
                "boundary": "CODEC_API_ONLY_V1",
                "clock": "CLOCK_MONOTONIC",
                "excludes": [
                    "CONTEXT_LIFECYCLE",
                    "DESCRIPTOR_CONTAINER",
                    "PYTHON_FFI",
                    "STAGING_ALLOCATION_COPY",
                    "SCALAR_RANGE_CANONICAL_WIRE_VALIDATION",
                    "SBP1_HEADER_CHECKSUM",
                ],
            },
            "accounting_hooks": [
                "LOGICAL_WIDTH_BITS",
                "PHYSICAL_LANE_PADDING",
                "SBP1_COUNT_SEED_MODE_BLOCK_RECORDS",
                "DESCRIPTOR_SHA256",
                "FNV64",
            ],
            "input_materialization": "OBSERVABLE_GATHER_TYPED_STAGING_CORE_PIPELINE",
            "descriptor_limit_bytes": 4096,
            "python_source_closure": [
                i for i in sdk["source_snapshot"] if i["path"].startswith("src/")
            ],
            **({"pipeline_executor_id": EXECUTOR_IDS[key]} if pipeline else {}),
        }
        card = copy.deepcopy(base_card)
        card.pop("source_onboarding_id")
        card.update(
            source_artifact_id=source_id,
            repository=lock["repository"],
            commit=lock["commit"],
            implementation_files=[p for p in units if "/vendor/" in p],
            public_api_files=[i["path"] for i in lock["files"] if "/include/" in i["path"]],
            benchmark_files=[
                "adapters/simdcomp/vendor/simdcomp/" + p for p in lock["upstream_benchmarks"]
            ],
            test_files=[
                "adapters/simdcomp/vendor/simdcomp/tests/unit.c",
                "adapters/simdcomp/vendor/simdcomp/tests/unit_chars.c",
                "adapters/simdcomp/tests/source_guard.c",
                "adapters/simdcomp/tests/avx2_guard.c",
                "adapters/simdcomp/tests/abi_qualification.c",
                "tests/adapters/test_simdcomp.py",
            ],
            license_files=source["license"]["files"],
            object_level_candidates=[document["classification"]["object_level"]],
            output_contract={
                "kind": document["semantics"]["rebuild_protocol"],
                "self_contained": True,
                "capacity_is_not_size": True,
                "descriptor_sha256": True,
                "native_frame_checksum": "FNV1A64",
            },
            stream_components=[
                "descriptor",
                "sha256",
                "native_magic",
                "count",
                "seed",
                "wire_mode",
                "block_size",
                "block_count",
                "reserved",
                "body_length",
                "block_records",
                "original_lane_payload",
                "padding",
                "fnv64",
            ],
            builds=[
                {
                    "kind": b["profile"],
                    "artifact_sha256": b["artifact_sha256"],
                    "compile_commands_sha256": b["compile_commands_sha256"],
                }
                for b in builds
            ],
            license_decision={
                "spdx": "BSD-3-Clause",
                "status": "RUN_ALLOWED",
                "reason": "Original notices retained; four explicit build-only patches",
            },
            known_limitations=[
                "uint32 UTS only; checked int64 Timestamp and other domains/ISAs remain pending.",
                "SSE4.1 and separate AVX2 objects; AVX2 tails use explicit SSE length APIs.",
                "Original source failures retained; patches never modify original vendor bytes.",
                "A/B source API fused; stage times unavailable; no backend C; D mandatory.",
                "Disable A selects distinct plain P0; FOR LENGTH/FULL have distinct wire modes.",
                "Linux x86_64; no runtime fallback/query/streaming; leak detection disabled.",
            ],
            upstream_tests=[
                {"name": name, "status": "PASS", "evidence": path, "log_sha256": sha(ROOT / path)}
                for name, path in (
                    (
                        "source_original_failures_retained",
                        "build/source-audits/simdcomp-source-patched-guards.json",
                    ),
                    ("avx2_source", "build/source-audits/simdcomp_avx2_source_tests.json"),
                    ("bounded_native", "build/source-audits/simdcomp_native_tests.json"),
                    ("direct_sdk", "build/source-audits/simdcomp_sdk_tests.json"),
                )
            ],
        )
        card["lifecycle_contract"].pop("decoder_apis")
        card["lifecycle_contract"].update(
            output_bound="44 + descriptor bytes + checked SBP1 bound; capacity is not size",
            source_apis=apis,
            starting_point="SERIALIZED_UINT32_BASE" if pipeline else "ZERO_ONLY",
            stage_execution="FUSED_SOURCE_" + coding + "_BITPACK",
        )
        cards.append((key, validate_onboarding_card(card)))
        documents.append((key, document))
    write(ROOT / "registry/sources/simdcomp.artifact.json", source)
    for directory, items in (("codecs", documents), ("onboarding", cards)):
        for key, document in items:
            write(ROOT / "registry" / directory / (key + ".json"), document)
    print(source_id)


if __name__ == "__main__":
    main()
