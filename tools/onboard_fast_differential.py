"""Register the exact four-API D1 source after current native/SDK qualification."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from audit_fast_differential_native import audit, require, sha

from tscompbench.codecs import validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/fast_differential"
KEY = "fast-differential-u32"


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    native_audit = audit()
    lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    sdk_path = ROOT / "build/source-audits/fast-differential-sdk-tests.json"
    sdk = json.loads(sdk_path.read_text())
    require(
        sdk["status"] == "PASS" and sdk["native_current_audit"] == native_audit,
        "current direct SDK qualification required",
    )
    for item in sdk["source_snapshot"]:
        require(sha(ROOT / item["path"]) == item["sha256"], "direct SDK input drift")
    identity = {
        "kind": "VENDORED_UPSTREAM_SOURCE_CLOSURE",
        "key": "fast-differential-714a9fe",
        "repository": lock["repository"],
        "commit": lock["commit"],
        "source_closure_sha256": hashlib.sha256(canonical_json_bytes(lock["files"])).hexdigest(),
        "patch_series": [],
        "selection": lock["selection"],
        "benchmark_reference": lock["benchmark_reference"],
        "copy_policy": "UNMODIFIED_VENDOR_FOUR_ORIGINAL_APIS_D1_NOT_D4",
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
            "files": ["adapters/fast_differential/vendor/FastDifferentialCoding/LICENSE"],
        },
        "build": {
            "recipe": "python tools/build_codec.py fast-differential-u32 --profile all",
            "patches": [],
            "submodules": [],
            "source_closure": lock["files"],
            "translation_units": [
                "adapters/fast_differential/native/tscb_fast_differential.c",
                "adapters/fast_differential/vendor/FastDifferentialCoding/src/fastdelta.c",
            ],
            "admission_card": "adapters/fast_differential/SOURCE_ADMISSION.md",
        },
    }
    document = copy.deepcopy(
        json.loads((ROOT / "registry/codecs/streamvbyte-modern-u32.json").read_text())
    )
    document["key"] = KEY
    document["identity"] = {
        "display_name": "FastDifferentialCoding D1 (uint32 transform primitive)",
        "family": "FAST_DIFFERENTIAL_D1_MODULAR32",
        "citations": [
            lock["repository"] + "@" + lock["commit"],
            "adapters/fast_differential/contract.md",
        ],
        "source_artifact_id": source_id,
    }
    document["input"]["timestamp_semantics"]["overflow_policy"] = "MODULAR_UINT32_D1_VALUE_ONLY"
    document["semantics"].update(
        rebuild_protocol="TSCB_FDC1_U32_SEED_MODE_AND_CANONICAL_DESCRIPTOR_V1",
        decodability_profile="SELF_CONTAINED_CHECKED_DESCRIPTOR_FDC1_SEED_MODE",
        # D1 is this P0 primitive's original API, not an extra preprocessing stage
        # silently attached to another codec. Any subsequent backend needs P2.
        preprocess_class="NONE",
        preprocess_stages=[],
    )
    document["lifecycle"]["reset"] = "MODE_ZERO_PRESERVES_PARAMETERS_CLEARS_OBJECT_AND_TIMING"
    document["parameters"]["properties"].update(
        api_mode={"type": "string", "enum": ["DISTINCT", "INPLACE"], "default": "DISTINCT"},
        starting_point={"type": "integer", "minimum": 0, "maximum": 4294967295, "default": 0},
    )
    document["adapter"] = {
        "backend": "C_ABI_V1",
        "version": "fast-differential-ctypes-v1",
        "factory": "FAST_DIFFERENTIAL_CTYPES_V1",
        "artifact_path": (
            "build/adapters/fast_differential_u32/release/libtscb_fast_differential_u32.so"
        ),
        "timing_boundary": "PYTHON_FFI_DESCRIPTOR_FDC1_CHECKSUM_AND_STAGING_INCLUDED",
        "native_timing_capability": {
            "optional": True,
            "boundary": "CODEC_API_ONLY_V1",
            "clock": "CLOCK_MONOTONIC",
            "excludes": [
                "CONTEXT_LIFECYCLE",
                "DESCRIPTOR_CONTAINER",
                "PYTHON_FFI",
                "TYPED_STAGING_COPY_ALLOCATION",
                "FDC1_HEADER_CHECKSUM",
            ],
        },
        "accounting_hooks": [
            "EXACT_D1_UINT32_WORDS",
            "FDC1_COUNT_SEED_MODE_RESERVED",
            "DESCRIPTOR_AND_SHA256",
            "FNV64",
            "OUTPUT_CAPACITY",
        ],
        "input_materialization": (
            "STRIDED_VECTOR_GATHER_AND_TYPED_STAGING_PRESERVE_BITS_INCLUDED_IN_CORE_PIPELINE"
        ),
        "descriptor_limit_bytes": 4096,
    }
    report_paths = [
        ROOT / "build/source-audits/fast-differential-source-tests.json",
        ROOT / "build/source-audits/fast-differential-native-tests.json",
        sdk_path,
    ]
    card = {
        "schema_version": "tscb.source-onboarding.v2",
        "source_artifact_id": source_id,
        "repository": lock["repository"],
        "commit": lock["commit"],
        "dirty": False,
        "submodules": [],
        "implementation_files": [
            "adapters/fast_differential/vendor/FastDifferentialCoding/src/fastdelta.c"
        ],
        "public_api_files": [
            "adapters/fast_differential/vendor/FastDifferentialCoding/include/fastdelta.h"
        ],
        "benchmark_files": [],
        "test_files": [
            "adapters/fast_differential/vendor/FastDifferentialCoding/tests/unit.c",
            "adapters/fast_differential/tests/source_guard.c",
            "adapters/fast_differential/tests/abi_qualification.c",
            "tests/adapters/test_fast_differential.py",
        ],
        "license_files": source["license"]["files"],
        "third_party_dependencies": [],
        "object_level_candidates": ["P0_PRIMITIVE"],
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
            "output_bound": "44 + canonical descriptor bytes + 32 + 4*N; exact serialized length",
            "return_length": "tscb_buffer_v1.used_bytes is exact; capacity is never size",
            "error_codes": {
                "0": "OK",
                "1": "INVALID_ARGUMENT",
                "2": "UNSUPPORTED",
                "3": "DST_TOO_SMALL",
                "4": "CODEC_ERROR",
                "5": "FINALIZE_REQUIRED",
                "6": "ABI_MISMATCH",
            },
            "api_modes": ["DISTINCT", "INPLACE"],
            "starting_point": "UINT32_FROM_FRAME_ON_DECODE",
            "input_staging": "ALIGNED_UINT32_COPY; INPLACE_ONLY_ON_INTERNAL_SCRATCH",
        },
        "stream_components": [
            "descriptor",
            "sha256",
            "native_magic",
            "count",
            "seed",
            "mode",
            "reserved",
            "original_d1_words",
            "fnv64",
        ],
        "upstream_tests": [
            {
                "name": path.stem,
                "status": "PASS",
                "log_sha256": sha(path),
                "evidence": str(path.relative_to(ROOT)),
            }
            for path in report_paths
        ],
        "builds": [],
        "license_decision": {
            "spdx": "Apache-2.0",
            "status": "RUN_ALLOWED",
            "reason": "Original LICENSE retained; source unchanged",
        },
        "known_limitations": [
            "P0 transform preserves 4*N payload bytes; complete wrapper expands the object.",
            "Four original D1 modular32 APIs selected by observable mode; not FastPFOR D4.",
            "uint32 UTS only; int64 timestamps/floats/validity/MTS require separate admission.",
            "Native timer excludes allocation, typed copy, framing/checksums, descriptor and FFI.",
            "Linux x86_64/SSE4.1 only; no runtime fallback; ASan leak detection disabled.",
            "All starting_point values are admitted uint32 parameters; "
            "sampled qualification is not enumeration.",
        ],
        "unsupported_reason_codes": [
            "NON_DECLARED_DTYPE",
            "MULTIVARIATE_NOT_REGISTERED",
            "STREAMING_UNREGISTERED",
            "ISA_UNSUPPORTED",
        ],
    }
    for profile in ("release", "debug", "sanitizer"):
        record = json.loads(
            (ROOT / f"build/adapters/fast_differential_u32/{profile}/build-record.json").read_text()
        )
        card["builds"].append(
            {
                "kind": profile,
                "artifact_sha256": record["artifact_sha256"],
                "compile_commands_sha256": record["compile_commands_sha256"],
            }
        )
    card = validate_onboarding_card(card)
    write(ROOT / "registry/sources/fast-differential.artifact.json", source)
    write(ROOT / "registry/codecs/fast-differential-u32.json", document)
    write(ROOT / "registry/onboarding/fast-differential-u32.json", card)
    print(source_id)


if __name__ == "__main__":
    main()
