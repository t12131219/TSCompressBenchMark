"""Register audited original uint28 Simple primitives; five-layer qualification is separate."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from audit_fastpfor_simple_sdk import audit, require, sha
from freeze_fastpfor_simple_source import PIN, SOURCES, tracked

from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "adapters/fastpfor_simple"
KEYS = {"simple9-u28": "Simple9", "simple9hacked-u28": "Simple9hacked", "simple16-u28": "Simple16"}


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    current = audit()
    require(current["status"] == "PASS", "upstream/native/direct SDK qualification required")
    lock = json.loads((ROOT / COMPONENT / "SOURCE_LOCK.json").read_text())
    sdk = json.loads((ROOT / "build/source-audits/fastpfor_simple_sdk_tests.json").read_text())
    reference_name = "src/inmemorybenchmark.cpp"
    reference = ROOT / COMPONENT / "references/fastpfor" / reference_name
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_bytes(tracked(SOURCES / "fast-pack_FastPFOR", PIN, reference_name))
    files = lock["files"] + [
        {
            "path": str(reference.relative_to(ROOT)),
            "upstream_path": reference_name,
            "sha256": sha(reference),
            "role": "BENCHMARK_REFERENCE_ONLY",
        }
    ]
    identity = {
        "kind": "VENDORED_UPSTREAM_SOURCE_CLOSURE",
        "key": "fastpfor-simple-2457e1e",
        "repository": lock["repository"],
        "commit": PIN,
        "source_closure_sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
        "patch_series": [],
        "copy_policy": "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH",
        "selection": "WORKBOOK_SIMPLE9_SIMPLE16_ORIGINAL_PUBLIC_APIS_LZBENCH_NO_MATCHING_ENTRY",
    }
    source_id = stable_id("source-artifact", identity)
    source = {
        "schema_version": "tscb.source-artifact.v2",
        "key": identity["key"],
        "kind": identity["kind"],
        "identity": identity,
        "license": {
            "spdx": "Apache-2.0 AND BSD-3-Clause",
            "status": "RUN_ALLOWED",
            "redistribution": "ALLOWED_WITH_LICENSE_NOTICE",
            "files": [lock["license"]["file"], COMPONENT + "/third_party/googletest/LICENSE"],
        },
        "build": {
            "recipe": "python tools/build_codec.py simple9-u28 --profile all",
            "patches": [],
            "submodules": [],
            "source_closure": files,
            "translation_units": [COMPONENT + "/native/tscb_fastpfor_simple.cpp"],
            "admission_card": COMPONENT + "/SOURCE_ADMISSION.md",
        },
    }
    builds = [
        json.loads((ROOT / f"build/adapters/fastpfor_simple/{p}/build-record.json").read_text())
        for p in ("release", "debug", "sanitizer")
    ]
    base = json.loads((ROOT / "registry/codecs/maskedvbyte-u32.json").read_text())
    base_card = json.loads((ROOT / "registry/onboarding/maskedvbyte-u32.json").read_text())
    documents, cards = [], []
    for key, codec in KEYS.items():
        document = copy.deepcopy(base)
        document["key"] = key
        document["identity"] = {
            "display_name": codec + " (original uint28 primitive)",
            "family": "FASTPFOR_" + codec.upper() + "_UINT28",
            "citations": [lock["repository"] + "@" + PIN, COMPONENT + "/contract.md"],
            "source_artifact_id": source_id,
        }
        document["input"]["timestamp_semantics"]["overflow_policy"] = "NOT_APPLICABLE_PLAIN_UINT28"
        document["input"]["value_domain"] = {
            "kind": "FROZEN_SOURCE_WITH_BOUNDED_REJECTION",
            "unsupported_action": "REJECT_BEFORE_OUTPUT",
            "oracle_evidence": "build/source-audits/fastpfor_simple_source_tests.json",
            "rejection_reasons": ["SIMPLE_UINT28_VALUE_OUT_OF_RANGE"],
        }
        document["semantics"].update(
            rebuild_protocol="TSCB_SPF1_UINT28_" + codec.upper() + "_CHECKED_DESCRIPTOR_V1",
            decodability_profile="SELF_CONTAINED_CHECKED_DESCRIPTOR_SPF1_" + codec.upper(),
        )
        document["lifecycle"]["tail_policy"] = (
            "INTERNAL_28_WORD_PADDING_HEADROOM_EXACT_LOGICAL_COUNT_NO_EXTERNAL_PADDING"
        )
        document["execution"]["isa"] = ["SCALAR"]
        document["parameters"] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "native_timing": {"type": "boolean", "default": True},
                "isa": {"type": "string", "enum": ["SCALAR"], "default": "SCALAR"},
                "mark_length": {"type": "boolean", "default": True},
            },
            "constraints": [],
        }
        document["adapter"] = {
            "backend": "C_ABI_V1",
            "version": "fastpfor-simple-ctypes-v1",
            "factory": "FASTPFOR_SIMPLE_CTYPES_V1",
            "artifact_path": "build/adapters/fastpfor_simple/release/libtscb_fastpfor_simple.so",
            "python_source_closure": sdk["source_snapshot"],
            "timing_boundary": "PYTHON_FFI_DESCRIPTOR_SPF1_DOMAIN_GRAMMAR_STAGING_INCLUDED",
            "native_timing_capability": {
                "optional": True,
                "boundary": "CODEC_API_ONLY_V1",
                "clock": "CLOCK_MONOTONIC",
                "excludes": [
                    "CONTEXT_LIFECYCLE",
                    "DESCRIPTOR_CONTAINER",
                    "PYTHON_FFI",
                    "STAGING_ALLOCATION_COPY",
                    "DOMAIN_GRAMMAR_VALIDATION",
                    "SPF1_CHECKSUM",
                ],
            },
            "accounting_hooks": [
                "ORIGINAL_SELECTOR_VALUE_BITS",
                "TAIL_PADDING_BITS",
                "COUNT_SELECTOR_METADATA",
                "DESCRIPTOR_SPF1_CONTAINER_CHECKSUM",
            ],
        }
        card = copy.deepcopy(base_card)
        card.pop("source_onboarding_id", None)
        implementation = (
            COMPONENT
            + "/vendor/fastpfor/headers/"
            + ("simple16.h" if key == "simple16-u28" else "simple9.h")
        )
        card.update(
            source_artifact_id=source_id,
            repository=lock["repository"],
            commit=PIN,
            implementation_files=[implementation],
            public_api_files=[implementation, COMPONENT + "/vendor/fastpfor/headers/codecs.h"],
            benchmark_files=[str(reference.relative_to(ROOT))],
            test_files=[
                COMPONENT + "/third_party/fastpfor_upstream_unit/src/unit.cpp",
                COMPONENT + "/tests/source_guard.cpp",
                COMPONENT + "/tests/abi_qualification.cpp",
                COMPONENT + "/tests/native_faults.cpp",
                "tests/adapters/test_fastpfor_simple.py",
            ],
            license_files=source["license"]["files"],
            third_party_dependencies=[
                {
                    "kind": "UPSTREAM_TEST_ONLY",
                    "name": "Google Test",
                    "commit": lock["test_dependency"]["commit"],
                    "license": "BSD-3-Clause",
                    "runtime_dependency": False,
                }
            ],
            input_contract={
                "dtype": "<u4",
                "value_minimum": 0,
                "value_maximum": 2**28 - 1,
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
                "output_bound": "44 + descriptor bytes + 40 + 4*(N + marked); size may be shorter",
                "return_length": "tscb_buffer_v1.used_bytes is exact; capacity is not size",
                "error_codes": base_card["lifecycle_contract"]["error_codes"],
                "decoder_apis": ["ORIGINAL_DECODE_ARRAY_GRAMMAR_AND_COUNT_VALIDATED"],
                "marked": "TRUE_AND_FALSE_PRESERVED_ORIGINAL_HEADER_WORD",
            },
            stream_components=[
                "descriptor",
                "sha256",
                "native_magic",
                "count",
                "codec_kind",
                "marked",
                "word_count",
                "reserved",
                "original_marked_count",
                "selectors",
                "values",
                "tail_padding",
                "fnv64",
            ],
            upstream_tests=[
                {"name": name, "status": "PASS", "log_sha256": sha(ROOT / path), "evidence": path}
                for name, path in [
                    (
                        "entire_original_upstream_unit_release_assertions_enabled",
                        "build/source-audits/fastpfor_simple_upstream_tests.json",
                    ),
                    (
                        "source_matrix_original_unsafe_calls_retained",
                        "build/source-audits/fastpfor_simple_source_tests.json",
                    ),
                    (
                        "bounded_native_three_profiles",
                        "build/source-audits/fastpfor_simple_native_tests.json",
                    ),
                    ("direct_sdk", "build/source-audits/fastpfor_simple_sdk_tests.json"),
                ]
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
                "spdx": source["license"]["spdx"],
                "status": "RUN_ALLOWED",
                "reason": "Unmodified Apache-2.0 FastPFOR; BSD-3-Clause Google Test is test-only.",
            },
            known_limitations=[
                "uint28 stored in uint32 only; wider integers/float/MTS/validity are not admitted.",
                "No implicit Delta, ZigZag, quantization, truncation or limb pipeline.",
                "Standard/hacked Simple9 have distinct identities; mark_length changes ConfigID.",
                "Linux x86_64 scalar only; no streaming/query/random access registration.",
                "Entire upstream factory runs release with assertions; native Simple ABI has "
                "separate release/debug/ASan+UBSan evidence; leak detection is unavailable.",
                "Registry creation is not five-layer/formal qualification.",
            ],
            unsupported_reason_codes=[
                "SIMPLE_UINT28_VALUE_OUT_OF_RANGE",
                "NON_DECLARED_DTYPE",
                "MULTIVARIATE_NOT_REGISTERED",
                "STREAMING_UNREGISTERED",
                "ISA_UNSUPPORTED",
            ],
        )
        documents.append((key, document))
        cards.append((key, validate_onboarding_card(card)))
    write(ROOT / "registry/sources/fastpfor-simple.artifact.json", source)
    for key, document in documents:
        write(ROOT / "registry/codecs" / (key + ".json"), document)
    for key, card in cards:
        write(ROOT / "registry/onboarding" / (key + ".json"), card)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    registry.verify_all()
    print(
        json.dumps(
            {
                "source_artifact_id": source_id,
                "registered": list(KEYS),
                "benchmark_five_layers": "PENDING",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
