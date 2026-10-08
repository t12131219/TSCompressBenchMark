"""Freeze the selected native source closure and its two distinct registered uses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tscompbench.codecs.onboarding import validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.preprocess.streamvbyte import EXECUTOR_ID, STAGE_SPEC

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "580c4f085381f31b1ad669525ed04e63cbc385f3"
KEYS = ("streamvbyte-u32", "delta-zigzag-streamvbyte64")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    vendor = ROOT / "adapters/streamvbyte/vendor/fastpfor"
    files = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in sorted(vendor.iterdir())]
    patch = ROOT / "adapters/streamvbyte/patches/0001-unaligned-access.patch"
    frozen = json.loads((ROOT / "adapters/streamvbyte/SOURCE_LOCK.json").read_text())
    for item in frozen["files"]:
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError(f"frozen Stream VByte source changed: {item['path']}")
    identity = {
        "kind": "VENDORED_BENCHMARK_SOURCE_CLOSURE",
        "key": "streamvbyte-lzbench-580c4f0",
        "benchmark_repository": "https://github.com/dblalock/lzbench",
        "benchmark_commit": COMMIT,
        "benchmark_path": "fastpfor/streamvbyte.c",
        "upstream_reference_repository": "https://github.com/fast-pack/streamvbyte",
        "upstream_reference_commit": "7c472d7d4d63c8bc65a88f310ccfc695a0eaf1ce",
        "source_closure_sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
        "patch_sha256": sha(patch),
        "copy_policy": "UNMODIFIED_VENDOR_WITH_REPLAYED_SAFETY_PATCH",
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
            "files": [
                "adapters/streamvbyte/vendor/fastpfor/LICENSE",
                "adapters/streamvbyte/vendor/fastpfor/streamvariablebyte.h",
            ],
        },
        "build": {
            "recipe": "PYTHONPATH=src python tools/build_codec.py <key> --profile all",
            "patches": [str(patch.relative_to(ROOT))],
            "submodules": [],
            "translation_units": [
                "adapters/streamvbyte/native/tscb_streamvbyte.c",
                "adapters/streamvbyte/vendor/fastpfor/streamvbyte.c",
            ],
            "source_closure": files,
        },
    }
    write(ROOT / "registry/sources/streamvbyte-lzbench.artifact.json", source)
    for key in KEYS:
        delta = key == KEYS[1]
        document = json.loads((ROOT / "registry/codecs/delta-varint.json").read_text())
        document["key"] = key
        document["identity"] = {
            "display_name": (
                "Checked Delta + ZigZag + limb32 + Stream VByte (int64)"
                if delta
                else "Stream VByte (lzbench uint32 primitive)"
            ),
            "family": "CHECKED_DELTA_ZIGZAG_LIMB32_STREAMVBYTE" if delta else "STREAMVBYTE_U32",
            "citations": [
                "benchmark:dblalock/lzbench@" + COMMIT,
                "adapters/streamvbyte/contract.md",
            ],
            "source_artifact_id": source_id,
        }
        document["classification"]["object_level"] = "P2_PIPELINE" if delta else "P0_PRIMITIVE"
        document["classification"]["tracks"] = ["TIMESTAMP" if delta else "VALUE"]
        document["classification"]["subtracks"] = ["T1" if delta else "V0"]
        inp = document["input"]
        inp["topologies"] = ["UTS", "SYNCHRONOUS_MTS"] if delta else ["UTS"]
        inp["dtypes"] = ["<i8" if delta else "<u4"]
        inp["max_n"] = 16777216
        inp["max_total_raw_bytes"] = 134217728 if delta else 67108864
        inp["timestamp_semantics"]["overflow_policy"] = (
            "CHECKED_I64_DELTA_AND_RECOVERY" if delta else "NOT_APPLICABLE_VALUE_ONLY"
        )
        if delta:
            inp["value_domain"] = {
                "kind": "FROZEN_SOURCE_WITH_BOUNDED_REJECTION",
                "unsupported_action": "REJECT_BEFORE_OUTPUT",
                "oracle_evidence": "adapters/streamvbyte/tests/abi_smoke.c",
                "rejection_reasons": ["checked int64 delta overflow"],
            }
        sem = document["semantics"]
        sem["rebuild_protocol"] = (
            "TSCB_EXPLICIT_CHECKED_D1_ZIGZAG_LIMB32_SVB_STAGES_V1"
            if delta
            else "TSCB_U32_LZBENCH_SVB_V1"
        )
        sem["preprocess_class"] = "LOSSLESS_LAYOUT" if delta else "NONE"
        sem["preprocess_stages"] = STAGE_SPEC if delta else []
        sem["decodability_profile"] = "SELF_CONTAINED_CHECKED_DESCRIPTOR_AND_NATIVE_SVB_COUNT"
        document["lifecycle"]["block_semantics"] = "ONE_ROUTED_VECTOR_NO_IMPLICIT_CHUNKING"
        document["lifecycle"]["tail_policy"] = "EXACT_COUNT_SSE4_1_FULL_GROUPS_SCALAR_REMAINDER"
        document["execution"]["isa"] = ["SSE4_1"]
        document["parameters"]["properties"]["isa"] = {
            "type": "string",
            "enum": ["SSE4_1"],
            "default": "SSE4_1",
        }
        if delta:
            for switch in ("stage_a", "stage_b", "stage_c", "stage_d", "stage_timing"):
                document["parameters"]["properties"][switch] = {"type": "boolean", "default": True}
            document["parameters"]["properties"]["stage_d"]["enum"] = [True]
        directory = key.replace("-", "_")
        document["adapter"] = {
            "backend": "C_ABI_V1",
            "version": "streamvbyte-ctypes-v1",
            "factory": "STREAMVBYTE_CTYPES_V1",
            "artifact_path": f"build/adapters/{directory}/release/libtscb_{directory}.so",
            "timing_boundary": "PYTHON_FFI_DESCRIPTOR_AND_COMPLETE_NATIVE_PIPELINE_INCLUDED",
            "native_timing_capability": {
                "optional": True,
                "boundary": "CODEC_API_ONLY_V1",
                "clock": "CLOCK_MONOTONIC",
                "excludes": [
                    "CONTEXT_LIFECYCLE",
                    "DESCRIPTOR_CONTAINER",
                    "PYTHON_FFI",
                    "CHECKED_DELTA_ZIGZAG_LIMB_SPLIT_RECOVERY",
                    "PADDED_ALIGNED_STAGING",
                ],
            },
            "accounting_hooks": [
                "NATIVE_COUNT_AND_SEED",
                "DESCRIPTOR_AND_SHA256",
                "FINAL_SVB_CONTROL_DATA_BYTES",
                "OUTPUT_CAPACITY",
            ],
            "input_materialization": (
                "STRIDED_VECTOR_GATHER_PRESERVES_DTYPE_ORDER_AND_BITS_INCLUDED_IN_CORE_PIPELINE"
            ),
            "descriptor_limit_bytes": 4096,
        }
        if delta:
            document["adapter"].update(
                version="streamvbyte-pipeline-ctypes-v1",
                factory="STREAMVBYTE_PIPELINE_CTYPES_V1",
                pipeline_executor_id=EXECUTOR_ID,
            )
        write(ROOT / f"registry/codecs/{key}.json", document)
        builds = []
        for profile in ("release", "debug", "sanitizer"):
            record = json.loads(
                (ROOT / f"build/adapters/{directory}/{profile}/build-record.json").read_text()
            )
            builds.append(
                {
                    "kind": profile,
                    "artifact_sha256": record["artifact_sha256"],
                    "compile_commands_sha256": record["compile_commands_sha256"],
                }
            )
        card = {
            "schema_version": "tscb.source-onboarding.v2",
            "source_artifact_id": source_id,
            "repository": identity["benchmark_repository"],
            "commit": COMMIT,
            "dirty": False,
            "submodules": [],
            "implementation_files": ["fastpfor/streamvbyte.c"],
            "public_api_files": ["fastpfor/streamvariablebyte.h"],
            "benchmark_files": ["_lzbench/compressors.cpp", "fastpfor/codecfactory.h"],
            "test_files": [
                "adapters/streamvbyte/tests/abi_smoke.c",
                "adapters/streamvbyte/tests/stages_smoke.c",
                "tests/adapters/test_streamvbyte.py",
                "tests/adapters/test_streamvbyte_pipeline.py",
            ],
            "license_files": source["license"]["files"],
            "third_party_dependencies": [],
            "object_level_candidates": [document["classification"]["object_level"]],
            "input_contract": {
                "dtype": inp["dtypes"][0],
                "shape": "CONTIGUOUS_VECTOR",
                "ownership": "BORROWED_IMMUTABLE",
                "max_count": inp["max_n"],
            },
            "output_contract": {
                "kind": sem["rebuild_protocol"],
                "self_contained": True,
                "capacity_is_not_size": True,
                "descriptor_sha256": True,
            },
            "lifecycle_contract": {
                "update": "ONCE",
                "finalize": "MANDATORY_ZERO_BYTES",
                "reset": "MODE_ZERO_ONLY",
                "decoder_padding": "INTERNAL_COPY_PLUS_16",
                "output_bound": (
                    "PREFIX + COUNT_U32 + CEIL(WORD_COUNT/4) + 4*WORD_COUNT; "
                    "descriptor included by Python"
                ),
                "return_length": (
                    "tscb_buffer_v1.used_bytes is the exact physical output length; "
                    "capacity is never the length"
                ),
                "error_codes": {
                    "0": "OK",
                    "1": "INVALID_ARGUMENT",
                    "2": "UNSUPPORTED",
                    "3": "DST_TOO_SMALL",
                    "4": "CODEC_ERROR",
                    "5": "FINALIZE_REQUIRED",
                    "6": "ABI_MISMATCH",
                },
            },
            "stream_components": ["descriptor", "sha256", "count", "control_bytes", "data_bytes"]
            + (["base_i64"] if delta else []),
            "upstream_tests": [],
            "builds": builds,
            "license_decision": {
                "spdx": "Apache-2.0",
                "status": "RUN_ALLOWED",
                "reason": "FastPFOR license and public header retained",
            },
            "known_limitations": [
                "Frozen old lzbench variant: scalar encoding, SSE4_1 decode and scalar tail.",
                "No 0124 variant, query, random access or incremental streaming registration.",
                (
                    "P2 uses reviewed independent A/B/C/D execution and inverses; stage D is "
                    "mandatory for its self-contained format. Stage A/B/C disable paths are "
                    "explicit byte-preserving representations, not fallback."
                ),
                (
                    "Native API timing excludes P2 transforms and padded staging; "
                    "CORE/PIPELINE include them."
                ),
            ]
            + (
                [
                    (
                        "Checked int64 delta overflow rejects the object atomically; "
                        "no unit scaling or raw fallback."
                    )
                ]
                if delta
                else ["uint32 UTS only; no implicit cast from int64 timestamps or floating values."]
            ),
            "unsupported_reason_codes": [
                "NON_DECLARED_DTYPE",
                "STREAMING_UNREGISTERED",
                "ISA_UNSUPPORTED",
            ]
            + (["SOURCE_DOMAIN_UNSUPPORTED"] if delta else ["MULTIVARIATE_NOT_REGISTERED"]),
        }
        report = ROOT / "build/source-audits/streamvbyte-native-tests.json"
        if report.is_file():
            evidence = json.loads(report.read_text())
            if evidence.get("status") == "PASS":
                card["upstream_tests"] = [
                    {
                        "name": "original lzbench byte equivalence and bidirectional decode",
                        "status": "PASS",
                        "log_sha256": sha(report),
                        "evidence": str(report.relative_to(ROOT)),
                    }
                ]
        write(ROOT / f"registry/onboarding/{key}.json", validate_onboarding_card(card))
    print(source_id)


if __name__ == "__main__":
    main()
