"""Register the five audited original API pairs; five-layer and formal gates remain separate."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from audit_littleintpacker_sdk import audit, require, sdk_report_path, sha

from tscompbench.adapters.littleintpacker import KEYS
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "adapters/littleintpacker"


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    current = audit()
    require(current["status"] == "PASS", "complete native and direct SDK evidence required")
    lock = json.loads((ROOT / COMPONENT / "SOURCE_LOCK.json").read_text())
    patch = json.loads((ROOT / COMPONENT / "PATCH_LOCK.json").read_text())
    sdk_path = sdk_report_path()
    sdk = json.loads(sdk_path.read_text())
    identity = {
        "kind": "VENDORED_UPSTREAM_SOURCE_CLOSURE",
        "key": "littleintpacker-8777f57",
        "repository": lock["repository"],
        "commit": lock["commit"],
        "source_closure_sha256": hashlib.sha256(canonical_json_bytes(lock["files"])).hexdigest(),
        "patch_series": [patch["patch"]],
        "copy_policy": "TRACKED_PINNED_BYTES_WITH_BUILD_ONLY_LOCKED_PATCH",
        "selection": "WORKBOOK_134_138_ORIGINAL_REPOSITORY_BENCHMARK_AND_FIVE_PUBLIC_API_PAIRS",
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
            "files": [lock["license"]["file"]],
        },
        "build": {
            "recipe": "python tools/build_codec.py littleintpacker-pack32-u32 --profile all",
            "patches": [patch["patch"]],
            "submodules": [],
            "source_closure": lock["files"],
            "translation_units": [COMPONENT + "/native/tscb_littleintpacker.cpp"]
            + [item["path"] for item in lock["files"] if item["upstream_path"].startswith("src/")],
            "admission_card": COMPONENT + "/SOURCE_ADMISSION.md",
        },
    }
    builds = [
        json.loads((ROOT / f"build/adapters/littleintpacker/{p}/build-record.json").read_text())
        for p in ("release", "debug", "sanitizer")
    ]
    base = json.loads((ROOT / "registry/codecs/maskedvbyte-u32.json").read_text())
    base_card = json.loads((ROOT / "registry/onboarding/maskedvbyte-u32.json").read_text())
    implementation = {
        "PACK32": "bitpacking32.c",
        "TURBO": "turbobitpacking32.c",
        "SC": "scpacking32.c",
        "BMI2": "bmipacking32.c",
        "HORIZONTAL": "horizontalpacking32.c",
    }
    documents, cards = [], []
    for key, (codec, isa) in KEYS.items():
        document = copy.deepcopy(base)
        document["key"] = key
        document["identity"] = {
            "display_name": f"LittleIntPacker {codec} (original fixed-width uint32 primitive)",
            "family": "LITTLEINTPACKER_" + codec + "_UINT32",
            "source_artifact_id": source_id,
            "citations": [
                lock["repository"] + "@" + lock["commit"],
                COMPONENT + "/SOURCE_ADMISSION.md",
            ],
        }
        document["input"]["value_domain"] = {
            "kind": "FROZEN_SOURCE_WITH_BOUNDED_REJECTION",
            "unsupported_action": "REJECT_BEFORE_OUTPUT",
            "oracle_evidence": "build/source-audits/littleintpacker_native_tests.json",
            "rejection_reasons": ["LITTLEINTPACKER_SUPPLIED_WIDTH_OUT_OF_RANGE"],
        }
        document["semantics"].update(
            rebuild_protocol="TSCB_LIP1_UINT32_" + codec + "_CHECKED_DESCRIPTOR_V1",
            decodability_profile="SELF_CONTAINED_CHECKED_DESCRIPTOR_LIP1_" + codec,
        )
        document["lifecycle"]["tail_policy"] = (
            "INTERNAL_32_VALUE_PACK_AND_128_VALUE_DECODE_HEADROOM_NO_EXTERNAL_PADDING"
        )
        document["execution"]["isa"] = [isa]
        if codec == "HORIZONTAL":
            document["execution"]["required_cpu_flags"] = ["ssse3", "sse4_1"]
        document["parameters"] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "native_timing": {"type": "boolean", "default": True},
                "isa": {"type": "string", "enum": [isa], "default": isa},
                "width_mode": {"type": "string", "enum": ["AUTO", "FIXED"], "default": "AUTO"},
                "bit_width": {"type": "integer", "minimum": 0, "maximum": 32, "default": 32},
            },
            "constraints": [
                {
                    "kind": "requires",
                    "when": {"width_mode": "AUTO"},
                    "required": {"bit_width": [32]},
                    "reason": (
                        "AUTO width uses the whole object; "
                        "bit_width=32 is its canonical placeholder"
                    ),
                }
            ],
        }
        document["adapter"] = {
            "backend": "C_ABI_V1",
            "version": "littleintpacker-ctypes-v1",
            "factory": "LITTLEINTPACKER_CTYPES_V1",
            "artifact_path": "build/adapters/littleintpacker/release/libtscb_littleintpacker.so",
            "python_source_closure": sdk["source_snapshot"],
            "timing_boundary": (
                "PYTHON_FFI_DESCRIPTOR_LIP1_WIDTH_SCAN_STAGING_AND_CHECKSUM_INCLUDED"
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
                    "WIDTH_SCAN_AND_VALIDATION",
                    "LIP1_CHECKSUM",
                ],
            },
            "accounting_hooks": [
                "ORIGINAL_FIXED_WIDTH_VALUE_BITS",
                "TAIL_PADDING_BITS",
                "COUNT_WIDTH_VARIANT_MODE_METADATA",
                "DESCRIPTOR_LIP1_CONTAINER_CHECKSUM",
            ],
        }
        card = copy.deepcopy(base_card)
        card.pop("source_onboarding_id", None)
        card.update(
            source_artifact_id=source_id,
            repository=lock["repository"],
            commit=lock["commit"],
            implementation_files=[
                COMPONENT + "/vendor/littleintpacker/src/" + implementation[codec]
            ]
            + (
                [COMPONENT + "/vendor/littleintpacker/src/bitpacking32.c"]
                if codec == "HORIZONTAL"
                else []
            ),
            public_api_files=[COMPONENT + "/vendor/littleintpacker/include/bitpacking.h"],
            benchmark_files=[lock["benchmark"]["path"]],
            test_files=[
                COMPONENT + "/vendor/littleintpacker/tests/unit.c",
                COMPONENT + "/tests/source_api_probe.c",
                COMPONENT + "/tests/abi_qualification.cpp",
                COMPONENT + "/tests/native_faults.cpp",
                "tests/adapters/test_littleintpacker.py",
            ],
            license_files=source["license"]["files"],
            third_party_dependencies=[],
            input_contract={
                "dtype": "<u4",
                "value_minimum": 0,
                "value_maximum": 2**32 - 1,
                "shape": "CONTIGUOUS_VECTOR",
                "ownership": "BORROWED_IMMUTABLE",
                "max_count": 16777216,
                "alignment_bytes": 1,
                "external_padding_bytes": 0,
            },
            output_contract={
                "kind": document["semantics"]["rebuild_protocol"],
                "self_contained": True,
                "capacity_is_not_size": True,
                "descriptor_sha256": True,
                "native_frame_checksum": "FNV1A64",
            },
            lifecycle_contract={
                "update": "ONCE",
                "finalize": "MANDATORY_ZERO_BYTES",
                "reset": "MODE_ZERO_ONLY",
                "output_bound": (
                    "44 + descriptor bytes + 40 + ceil(N * actual_width / 8); exact bound"
                ),
                "return_length": "tscb_buffer_v1.used_bytes is exact; capacity is not size",
                "error_codes": base_card["lifecycle_contract"]["error_codes"],
                "width_policy": "FIXED_0_TO_32_OR_AUTO_WHOLE_OBJECT_MINIMUM_NO_DELTA_OR_TRANSFORM",
                "original_api_pair": lock["source_apis"][codec],
            },
            stream_components=[
                "descriptor",
                "sha256",
                "native_magic",
                "count",
                "codec_kind",
                "actual_width",
                "width_mode",
                "payload_length",
                "values",
                "tail_padding",
                "fnv64",
            ],
            upstream_tests=[
                {"name": name, "status": "PASS", "log_sha256": sha(ROOT / path), "evidence": path}
                for name, path in (
                    (
                        "original_source_failures_retained",
                        "build/source-audits/littleintpacker_source_tests.json",
                    ),
                    (
                        "patched_complete_upstream_and_source_api_matrix",
                        "build/source-audits/littleintpacker_patched_tests.json",
                    ),
                    (
                        "bounded_native_three_profiles",
                        "build/source-audits/littleintpacker_native_tests.json",
                    ),
                    ("direct_sdk", str(sdk_path.relative_to(ROOT))),
                )
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
                "spdx": "Apache-2.0",
                "status": "RUN_ALLOWED",
                "reason": (
                    "Apache-2.0 original files retained; "
                    "build-only correction notice and patch lock preserved."
                ),
            },
            known_limitations=[
                "VALUE/UTS uint32 primitive; "
                "other input domains and track pipelines require separate review.",
                "Five original API pairs retained; BMI2 decoder requires AVX2+BMI2, "
                "HORIZONTAL SSSE3+SSE4.1.",
                "No implicit Delta/ZigZag/quantization/truncation; "
                "AUTO is explicit whole-vector minimum width.",
                "No streaming/query/random access; full object includes all metadata and checksum.",
                "ASan+UBSan qualified; detect_leaks=0 does not qualify LeakSanitizer.",
                "Direct SDK and registry admission are not five-layer/formal qualification.",
            ],
            unsupported_reason_codes=[
                "LITTLEINTPACKER_SUPPLIED_WIDTH_OUT_OF_RANGE",
                "NON_DECLARED_DTYPE",
                "MULTIVARIATE_NOT_REGISTERED",
                "STREAMING_UNREGISTERED",
                "ISA_UNSUPPORTED",
            ],
        )
        documents.append((key, document))
        cards.append((key, validate_onboarding_card(card)))
    write(ROOT / "registry/sources/littleintpacker.artifact.json", source)
    for key, doc in documents:
        write(ROOT / "registry/codecs" / (key + ".json"), doc)
    for key, card in cards:
        write(ROOT / "registry/onboarding" / (key + ".json"), card)
    CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")).verify_all()
    print(
        json.dumps(
            {
                "registered": list(KEYS),
                "source_artifact_id": source_id,
                "benchmark_five_layers": "PENDING",
            }
        )
    )


if __name__ == "__main__":
    main()
