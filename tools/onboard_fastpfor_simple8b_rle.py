"""Register the frozen patched FastPFOR RLE primitive after actual native and SDK audits."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from audit_fastpfor_simple8b_rle_sdk import audit
from audit_fastpfor_simple8b_rle_native import identity, require
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = "adapters/fastpfor_simple8b_rle"
KEY = "fastpfor-simple8b-rle-u32"


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    sdk = audit()
    lock = json.loads((ROOT / COMPONENT / "SOURCE_LOCK.json").read_text())
    patch = json.loads((ROOT / COMPONENT / "PATCH_LOCK.json").read_text())
    source_identity = {
        "kind": "VENDORED_UPSTREAM_SOURCE_CLOSURE", "key": "fastpfor-simple8b-rle-2457e1e-patched",
        "repository": lock["repository"], "commit": lock["commit"],
        "source_closure_sha256": hashlib.sha256(canonical_json_bytes(lock["files"])).hexdigest(),
        "patch_series": [patch["patch"]], "copy_policy": lock["copy_policy"],
        "selection": "WORKBOOK_RLE_PIN_BENCHMARK_COPY_DIFFERS_NOT_A_STANDALONE_LZBENCH_ENTRY",
    }
    source_id = stable_id("source-artifact", source_identity)
    source = {
        "schema_version": "tscb.source-artifact.v2", "key": source_identity["key"],
        "kind": source_identity["kind"], "identity": source_identity,
        "license": {"spdx": "Apache-2.0", "status": "RUN_ALLOWED",
                    "redistribution": "ALLOWED_WITH_LICENSE_NOTICE", "files": [lock["license"]["path"]]},
        "build": {"recipe": "PYTHONPATH=src taskset -c 2 python tools/build_codec.py fastpfor-simple8b-rle-u32 --profile all",
                  "patches": [patch["patch"]], "submodules": [], "source_closure": lock["files"],
                  "translation_units": [COMPONENT + "/native/tscb_fastpfor_simple8b_rle.cpp"],
                  "admission_card": COMPONENT + "/SOURCE_ADMISSION.md"},
    }
    document = copy.deepcopy(json.loads((ROOT / "registry/codecs/simple9-u28.json").read_text()))
    document["key"] = KEY
    document["identity"] = {
        "display_name": "FastPFOR Simple8b_RLE (patched original uint32 primitive)",
        "family": "FASTPFOR_SIMPLE8B_RLE_UINT32", "source_artifact_id": source_id,
        "citations": [lock["repository"] + "@" + lock["commit"], COMPONENT + "/contract.md"],
    }
    document["input"].pop("value_domain", None)
    document["input"]["timestamp_semantics"]["overflow_policy"] = "NOT_APPLICABLE_PLAIN_UINT32"
    document["semantics"].update(
        rebuild_protocol="TSCB_8BR1_UINT32_SIMPLE8B_RLE_CHECKED_DESCRIPTOR_V1",
        decodability_profile="SELF_CONTAINED_CHECKED_DESCRIPTOR_8BR1_SIMPLE8B_RLE",
    )
    document["lifecycle"]["tail_policy"] = "EXACT_LOGICAL_COUNT_INTERNAL_ALIGNED_STAGING_NO_EXTERNAL_PADDING"
    document["adapter"] = {
        "backend": "C_ABI_V1", "version": "fastpfor-simple8b-rle-ctypes-v1",
        "factory": "FASTPFOR_SIMPLE8B_RLE_CTYPES_V1",
        "artifact_path": "build/adapters/fastpfor_simple8b_rle/20261007-2/release/libtscb_fastpfor_simple8b_rle.so",
        "python_source_closure": sdk["source_snapshot"],
        "timing_boundary": "PYTHON_FFI_DESCRIPTOR_8BR1_GRAMMAR_STAGING_CHECKSUM_INCLUDED",
        "native_timing_capability": {
            "optional": True, "boundary": "CODEC_API_ONLY_V1", "clock": "CLOCK_MONOTONIC",
            "excludes": ["CONTEXT_LIFECYCLE", "DESCRIPTOR_CONTAINER", "PYTHON_FFI",
                         "STAGING_ALLOCATION_COPY", "GRAMMAR_VALIDATION", "8BR1_CHECKSUM"],
        },
        "accounting_hooks": ["RLE_COUNT_METADATA", "ORIGINAL_SELECTOR_VALUE_BITS",
                             "TAIL_PADDING_BITS", "COUNT_MARKER_METADATA", "DESCRIPTOR_8BR1_CHECKSUM"],
    }
    card = copy.deepcopy(json.loads((ROOT / "registry/onboarding/simple9-u28.json").read_text()))
    card.pop("source_onboarding_id", None)
    implementation = COMPONENT + "/vendor/fastpfor/headers/simple8b_rle.h"
    card.update(
        source_artifact_id=source_id, repository=lock["repository"], commit=lock["commit"],
        implementation_files=[implementation],
        public_api_files=[implementation, COMPONENT + "/vendor/fastpfor/headers/codecs.h"],
        benchmark_files=[COMPONENT + "/references/fastpfor/src/inmemorybenchmark.cpp"],
        test_files=[COMPONENT + "/references/fastpfor/src/unit.cpp", COMPONENT + "/tests/source_matrix.cpp",
                    COMPONENT + "/tests/native_safety.cpp", COMPONENT + "/tests/native_faults.cpp",
                    COMPONENT + "/tests/native_source_faults.cpp", "tests/adapters/test_fastpfor_simple8b_rle.py"],
        license_files=source["license"]["files"], third_party_dependencies=[],
        input_contract={"dtype": "<u4", "value_minimum": 0, "value_maximum": 2**32-1,
                        "shape": "CONTIGUOUS_VECTOR", "ownership": "BORROWED_IMMUTABLE",
                        "max_count": 16777216, "alignment_bytes": 1, "external_padding_bytes": 0},
        output_contract={"kind": document["semantics"]["rebuild_protocol"], "self_contained": True,
                         "capacity_is_not_size": True, "descriptor_sha256": True, "native_frame_checksum": "FNV1A64"},
        lifecycle_contract={**card["lifecycle_contract"],
                            "output_bound": "44 + descriptor bytes + 40 + 8*N + 4*marked; capacity is not size"},
        stream_components=["descriptor", "sha256", "native_magic", "count", "kind", "marked",
                           "word_count", "reserved", "original_marked_count", "selectors",
                           "RLE_count", "values", "tail_padding", "fnv64"],
        upstream_tests=[
            {"name": name, "status": "PASS", "log_sha256": identity(ROOT / path)["sha256"], "evidence": path}
            for name, path in (
                ("patched_source_matrix_and_complete_upstream_unit", "build/source-audits/fastpfor-simple8b-rle-source-20261007-1/report.json"),
                ("shared_native_safety_three_profiles", "build/source-audits/fastpfor-simple8b-rle-native-safety-20261007-1/report.json"),
                ("same_object_native_faults_three_profiles", "build/source-audits/fastpfor-simple8b-rle-native-faults-20261007-1/report.json"),
                ("direct_python_sdk_466_tests", sdk["sdk_report"]["path"]),
            )
        ],
        license_decision={"spdx": "Apache-2.0", "status": "RUN_ALLOWED",
                          "reason": "Pinned Apache-2.0 source retained; explicit build-only safety/length patch."},
        known_limitations=[
            "Full uint32 VALUE/UTS primitive only; Timestamp/int64/float/MTS/validity paths remain unadmitted.",
            "Distinct from Timescale Simple8b-RLE and sprintz-lzbench's differing bits() variant.",
            "No implicit Delta/ZigZag/DoD, dtype conversion, quantization or sorting.",
            "Patch fixes length, alignment and decoder tail; selector/RLE choices and wire remain original.",
            "Linux x86_64 scalar, no fallback, streaming or random access; detect_leaks=0.",
            "Registration alone does not qualify five-layer/formal execution or a full workbook entry.",
        ],
        unsupported_reason_codes=["NON_DECLARED_DTYPE", "TIMESTAMP_PIPELINE_NOT_REGISTERED",
                                  "MULTIVARIATE_NOT_REGISTERED", "STREAMING_UNREGISTERED", "ISA_UNSUPPORTED"],
    )
    card["builds"] = []
    for profile in ("release", "debug", "sanitizer"):
        build_path = ROOT / "build/adapters/fastpfor_simple8b_rle/20261007-2" / profile / "build-record.json"
        build = json.loads(build_path.read_text())
        card["builds"].append({"kind": profile, "artifact_sha256": build["artifact"]["sha256"],
                               "compile_commands_sha256": hashlib.sha256(canonical_json_bytes(
                                   [i["command"] for i in build["commands"]])).hexdigest()})
    card = validate_onboarding_card(card)
    require(not (ROOT / f"registry/codecs/{KEY}.json").exists(), "preserve existing codec registration")
    write(ROOT / "registry/sources/fastpfor-simple8b-rle.artifact.json", source)
    write(ROOT / f"registry/codecs/{KEY}.json", document)
    write(ROOT / f"registry/onboarding/{KEY}.json", card)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    registry.verify_all()
    print(json.dumps({"registered": KEY, "source_artifact_id": source_id, "benchmark_five_layers": "PENDING"}, indent=2))


if __name__ == "__main__":
    main()
