"""Register qualified plain P0 and original fused modular-D1 P2 source identities."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from audit_maskedvbyte_sdk import audit, require, sha

from tscompbench.codecs import validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.preprocess.maskedvbyte import EXECUTOR_ID, STAGE_SPEC

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/maskedvbyte"
KEYS = ["maskedvbyte-u32", "delta-maskedvbyte-u32"]


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    current = audit()
    require(current["status"] == "PASS", "current source/native/direct SDK evidence required")
    lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    patch = ADAPTER / "patches/0001-unsigned-shifts.patch"
    patches = [{"path": str(patch.relative_to(ROOT)), "sha256": sha(patch)}]
    identity = {
        "kind": "VENDORED_UPSTREAM_SOURCE_CLOSURE",
        "key": "maskedvbyte-e2298b7",
        "repository": lock["repository"],
        "commit": lock["commit"],
        "source_closure_sha256": hashlib.sha256(canonical_json_bytes(lock["files"])).hexdigest(),
        "patch_series": patches,
        "selection": "EXACT_WORKBOOK_SOURCE_BENCHMARK_WRAPPER_DIFFERENCES_RETAINED",
        "benchmark_reference": "FastPFOR headers/simdvariablebyte.h: "
        "plain-only padded other API; not substituted",
        "copy_policy": "UNMODIFIED_VENDOR_PLUS_EXPLICIT_BUILD_ONLY_UNSIGNED_SHIFT_PATCH",
    }
    source_id = stable_id("source-artifact", identity)
    source = {
        "schema_version": "tscb.source-artifact.v2",
        "key": identity["key"],
        "kind": identity["kind"],
        "identity": identity,
        "license": {
            "spdx": "Apache-2.0",
            "status": "RUN_ALLOWED",
            "redistribution": "ALLOWED_WITH_LICENSE_NOTICE",
            "files": ["adapters/maskedvbyte/vendor/MaskedVByte/LICENSE"],
        },
        "build": {
            "recipe": "python tools/build_codec.py maskedvbyte-u32 --profile all",
            "patches": patches,
            "submodules": [],
            "source_closure": lock["files"],
            "translation_units": [
                "adapters/maskedvbyte/native/tscb_maskedvbyte.c",
                "adapters/maskedvbyte/vendor/MaskedVByte/src/varintencode.c",
                "adapters/maskedvbyte/vendor/MaskedVByte/src/varintdecode.c",
            ],
            "admission_card": "adapters/maskedvbyte/SOURCE_ADMISSION.md",
        },
    }
    base = json.loads((ROOT / "registry/codecs/fast-differential-u32.json").read_text())
    builds = [
        json.loads(
            (ROOT / f"build/adapters/maskedvbyte_u32/{profile}/build-record.json").read_text()
        )
        for profile in ("release", "debug", "sanitizer")
    ]
    documents, cards = [], []
    for key in KEYS:
        delta = key.startswith("delta-")
        document = copy.deepcopy(base)
        document["key"] = key
        document["identity"] = {
            "display_name": "Delta + MaskedVByte (original modular uint32 pipeline)"
            if delta
            else "MaskedVByte (original uint32 primitive)",
            "family": "MASKEDVBYTE_D1_MODULAR32" if delta else "MASKEDVBYTE_UINT32",
            "citations": [
                lock["repository"] + "@" + lock["commit"],
                "adapters/maskedvbyte/contract.md",
            ],
            "source_artifact_id": source_id,
        }
        document["classification"]["object_level"] = "P2_PIPELINE" if delta else "P0_PRIMITIVE"
        document["input"]["timestamp_semantics"]["overflow_policy"] = (
            "MODULAR_UINT32_D1_VALUE_ONLY" if delta else "NOT_APPLICABLE_PLAIN_UINT32"
        )
        document["semantics"].update(
            rebuild_protocol="TSCB_MVB1_UINT32_"
            + ("MODULAR_DELTA" if delta else "PLAIN")
            + "_CHECKED_DESCRIPTOR_V1",
            decodability_profile="SELF_CONTAINED_CHECKED_DESCRIPTOR_MVB1_"
            + ("MODULAR_DELTA" if delta else "PLAIN"),
            preprocess_class="LOSSLESS_SEMANTIC" if delta else "NONE",
            preprocess_stages=copy.deepcopy(STAGE_SPEC) if delta else [],
        )
        props = document["parameters"]["properties"]
        props.pop("api_mode")
        props["decoder_api"] = {
            "type": "string",
            "enum": ["COUNT", "COMPRESSED_SIZE"],
            "default": "COUNT",
        }
        props["starting_point"]["maximum"] = 4294967295 if delta else 0
        document["lifecycle"]["tail_policy"] = (
            "CANONICAL_EXACT_UINT32_LEB128_SSE4_1_GROUPS_SCALAR_TAIL"
        )
        document["adapter"] = {
            "backend": "C_ABI_V1",
            "version": "maskedvbyte-ctypes-v1",
            "factory": "MASKEDVBYTE_CTYPES_V1",
            "artifact_path": "build/adapters/maskedvbyte_u32/release/libtscb_maskedvbyte_u32.so",
            "timing_boundary": (
                "PYTHON_FFI_DESCRIPTOR_MVB1_CHECKSUM_CANONICAL_SCAN_STAGING_INCLUDED"
            ),
            "native_timing_capability": {
                "optional": True,
                "boundary": "CODEC_API_ONLY_V1",
                "clock": "CLOCK_MONOTONIC",
                "excludes": [
                    "CONTEXT_LIFECYCLE",
                    "DESCRIPTOR_CONTAINER",
                    "PYTHON_FFI",
                    "STAGING_ALLOCATION_COPY",
                    "CANONICAL_VARINT_VALIDATION",
                    "MVB1_HEADER_CHECKSUM",
                ],
            },
            "accounting_hooks": [
                "ORIGINAL_LEB128_PAYLOAD",
                "MVB1_COUNT_SEED_CODING_LENGTH_RESERVED",
                "DESCRIPTOR_SHA256",
                "FNV64",
                "OUTPUT_CAPACITY",
            ],
            "input_materialization": "OBSERVABLE_GATHER_TYPED_STAGING_CORE_PIPELINE",
            "descriptor_limit_bytes": 4096,
            **({"pipeline_executor_id": EXECUTOR_ID} if delta else {}),
        }
        card = {
            "schema_version": "tscb.source-onboarding.v2",
            "source_artifact_id": source_id,
            "repository": lock["repository"],
            "commit": lock["commit"],
            "dirty": False,
            "submodules": [],
            "implementation_files": [
                p for p in source["build"]["translation_units"] if "/vendor/" in p
            ],
            "public_api_files": [
                "adapters/maskedvbyte/vendor/MaskedVByte/include/varintencode.h",
                "adapters/maskedvbyte/vendor/MaskedVByte/include/varintdecode.h",
            ],
            "benchmark_files": ["adapters/maskedvbyte/vendor/MaskedVByte/examples/example.c"],
            "test_files": [
                "adapters/maskedvbyte/vendor/MaskedVByte/tests/unit.c",
                "adapters/maskedvbyte/tests/source_guard.c",
                "adapters/maskedvbyte/tests/abi_qualification.c",
                "tests/adapters/test_maskedvbyte.py",
            ],
            "license_files": source["license"]["files"],
            "third_party_dependencies": [],
            "object_level_candidates": [document["classification"]["object_level"]],
            "input_contract": {
                "dtype": "<u4",
                "shape": "CONTIGUOUS_VECTOR",
                "ownership": "BORROWED_IMMUTABLE",
                "max_count": 16777216,
                "alignment_bytes": 1,
                "external_padding_bytes": 0,
            },
            "output_contract": {
                "kind": document["semantics"]["rebuild_protocol"],
                "self_contained": True,
                "capacity_is_not_size": True,
                "descriptor_sha256": True,
                "native_frame_checksum": "FNV1A64",
            },
            "lifecycle_contract": {
                "update": "ONCE",
                "finalize": "MANDATORY_ZERO_BYTES",
                "reset": "MODE_ZERO_ONLY",
                "output_bound": "44 + descriptor bytes + 40 + 5*N; actual length may be shorter",
                "return_length": "tscb_buffer_v1.used_bytes is exact; capacity is not size",
                "error_codes": {
                    str(i): v
                    for i, v in enumerate(
                        [
                            "OK",
                            "INVALID_ARGUMENT",
                            "UNSUPPORTED",
                            "DST_TOO_SMALL",
                            "CODEC_ERROR",
                            "FINALIZE_REQUIRED",
                            "ABI_MISMATCH",
                        ]
                    )
                },
                "decoder_apis": ["COUNT", "COMPRESSED_SIZE"],
                "starting_point": "FRAME_SEED_MODULAR_UINT32" if delta else "ZERO_ONLY",
                "stage_execution": "FUSED_ORIGINAL_D1_AND_LEB128"
                if delta
                else "ORIGINAL_PLAIN_LEB128",
            },
            "stream_components": [
                "descriptor",
                "sha256",
                "native_magic",
                "count",
                "seed",
                "coding",
                "reserved",
                "payload_length",
                "original_leb128",
                "fnv64",
            ],
            "upstream_tests": [
                {"name": name, "status": "PASS", "log_sha256": sha(ROOT / path), "evidence": path}
                for name, path in [
                    (
                        "source_matrix_original_failure_retained",
                        "build/source-audits/maskedvbyte-source-both-tests.json",
                    ),
                    ("bounded_native", "build/source-audits/maskedvbyte-native-tests.json"),
                    ("direct_sdk", "build/source-audits/maskedvbyte-sdk-tests.json"),
                ]
            ],
            "builds": [
                {
                    "kind": b["profile"],
                    "artifact_sha256": b["artifact_sha256"],
                    "compile_commands_sha256": b["compile_commands_sha256"],
                }
                for b in builds
            ],
            "license_decision": {
                "spdx": "Apache-2.0",
                "status": "RUN_ALLOWED",
                "reason": "License retained, original source unmodified, "
                "patch applied only in build",
            },
            "known_limitations": [
                "uint32 UTS only; int64 timestamps/floats/validity/MTS require separate admission.",
                "Six source APIs preserved; COUNT vs COMPRESSED_SIZE is execution-only "
                "and does not change bytes.",
                "Original unsigned-shift UB failure retained; "
                "only explicit patched decode is admitted.",
                "Query/select/search are source-qualified, not Benchmark workloads.",
                "Linux x86_64/SSE4.1 only; no fallback; leak detection disabled.",
                "Delta A/B fused by source; individual stage times unavailable; no backend C.",
            ]
            if delta
            else [
                "Plain uint32 primitive only; no int64/float conversion or hidden delta.",
                "Original unsigned-shift UB failure retained; explicit decode patch required.",
                "COUNT vs COMPRESSED_SIZE and timer do not change wire bytes.",
                "Linux x86_64/SSE4.1 only; query/streaming not registered; "
                "leak detection disabled.",
            ],
            "unsupported_reason_codes": [
                "NON_DECLARED_DTYPE",
                "MULTIVARIATE_NOT_REGISTERED",
                "STREAMING_UNREGISTERED",
                "ISA_UNSUPPORTED",
            ],
        }
        cards.append((key, validate_onboarding_card(card)))
        documents.append((key, document))
    write(ROOT / "registry/sources/maskedvbyte.artifact.json", source)
    for key, document in documents:
        write(ROOT / "registry/codecs" / (key + ".json"), document)
    for key, card in cards:
        write(ROOT / "registry/onboarding" / (key + ".json"), card)
    print(source_id)


if __name__ == "__main__":
    main()
