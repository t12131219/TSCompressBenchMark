"""Freeze modern upstream identity without conflating the old Benchmark variant."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from tscompbench.codecs.onboarding import validate_onboarding_card
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.preprocess.streamvbyte_modern import EXECUTOR_ID, STAGE_SPEC

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/streamvbyte_modern"
KEYS = ("streamvbyte-modern-u32", "delta-zigzag-streamvbyte-modern64")
LEGACY = ("streamvbyte-u32", "delta-zigzag-streamvbyte64")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, document: dict) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    lock = json.loads((ADAPTER / "SOURCE_LOCK.json").read_text())
    for item in lock["files"]:
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError(f"frozen source changed: {item['path']}")
    tests_path = ROOT / "build/source-audits/streamvbyte-modern-native-tests.json"
    evidence = json.loads(tests_path.read_text())
    if evidence.get("status") != "PASS" or evidence["source_lock_sha256"] != sha(
        ADAPTER / "SOURCE_LOCK.json"
    ):
        raise RuntimeError("modern native qualification missing or stale")
    if evidence["driver_sha256"] != sha(ADAPTER / "tests/run_native_tests.py"):
        raise RuntimeError("modern native qualification driver changed")
    files = [item for item in lock["files"] if "/vendor/" in item["path"]]
    patches = [item for item in lock["files"] if "/patches/" in item["path"]]
    identity = {
        "kind": "VENDORED_UPSTREAM_SOURCE_CLOSURE",
        "key": "streamvbyte-modern-7c472d7",
        "repository": lock["repository"],
        "commit": lock["commit"],
        "source_closure_sha256": hashlib.sha256(canonical_json_bytes(files)).hexdigest(),
        "patch_series": patches,
        "selection": lock["selection"],
        "benchmark_reference": lock["benchmark_reference"],
        "copy_policy": "UNMODIFIED_VENDOR_WITH_REPLAYED_SAFETY_PATCHES",
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
            "redistribution": "ALLOWED_WITH_LICENSE_NOTICES",
            "files": [
                "adapters/streamvbyte_modern/vendor/streamvbyte/LICENSE",
                "adapters/streamvbyte_modern/vendor/streamvbyte/src/streamvbyte_isadetection.h",
            ],
        },
        "build": {
            "recipe": "PYTHONPATH=src python tools/build_codec.py <key> --profile all",
            "patches": [item["path"] for item in patches],
            "submodules": [],
            "translation_units": [
                "adapters/streamvbyte_modern/native/tscb_streamvbyte_modern.c",
                "src/streamvbyte_encode.c",
                "src/streamvbyte_decode.c",
            ],
            "source_closure": files,
            "admission_card": "adapters/streamvbyte_modern/SOURCE_ADMISSION.md",
        },
    }
    cards, manifests = [], []
    for index, key in enumerate(KEYS):
        delta = bool(index)
        document = copy.deepcopy(
            json.loads((ROOT / f"registry/codecs/{LEGACY[index]}.json").read_text())
        )
        document["key"] = key
        document["identity"] = {
            "display_name": "Checked Delta + ZigZag + limb32 + modern Stream VByte (int64)"
            if delta
            else "Modern Stream VByte 1234 (uint32 primitive)",
            "family": "CHECKED_DELTA_ZIGZAG_LIMB32_MODERN_STREAMVBYTE"
            if delta
            else "MODERN_STREAMVBYTE_1234_U32",
            "citations": [
                lock["repository"] + "@" + lock["commit"],
                "adapters/streamvbyte_modern/contract.md",
            ],
            "source_artifact_id": source_id,
        }
        document["semantics"]["rebuild_protocol"] = (
            "TSCB_MODERN_1234_EXPLICIT_STAGES_V1"
            if delta
            else ("TSCB_MODERN_1234_U32_DESCRIPTOR_COUNT_V1")
        )
        document["semantics"]["preprocess_stages"] = STAGE_SPEC if delta else []
        if delta:
            document["input"]["value_domain"]["oracle_evidence"] = (
                "build/source-audits/streamvbyte-modern-native-tests.json"
            )
        directory = key.replace("-", "_")
        adapter = document["adapter"]
        adapter.update(
            version="streamvbyte-modern-pipeline-ctypes-v1"
            if delta
            else "streamvbyte-modern-ctypes-v1",
            factory="STREAMVBYTE_MODERN_PIPELINE_CTYPES_V1"
            if delta
            else "STREAMVBYTE_MODERN_CTYPES_V1",
            artifact_path=f"build/adapters/{directory}/release/libtscb_{directory}.so",
        )
        if delta:
            adapter["pipeline_executor_id"] = EXECUTOR_ID
        adapter["native_timing_capability"]["excludes"].append("SHIM_COUNT_AND_USED_LENGTH")
        manifests.append(document)
        card = copy.deepcopy(
            json.loads((ROOT / f"registry/onboarding/{LEGACY[index]}.json").read_text())
        )
        card.pop("source_onboarding_id", None)
        card.update(
            source_artifact_id=source_id,
            repository=lock["repository"],
            commit=lock["commit"],
            implementation_files=["src/streamvbyte_encode.c", "src/streamvbyte_decode.c"],
            public_api_files=["include/streamvbyte.h"],
            benchmark_files=["tests/perf.c"],
            test_files=[
                "tests/unit.c",
                "adapters/streamvbyte_modern/tests/run_native_tests.py",
                "adapters/streamvbyte/tests/abi_smoke.c",
                "adapters/streamvbyte/tests/stages_smoke.c",
                "tests/adapters/test_streamvbyte.py",
                "tests/adapters/test_streamvbyte_pipeline.py",
            ],
            license_files=source["license"]["files"],
            license_decision={
                "spdx": "Apache-2.0 AND BSD-3-Clause",
                "status": "RUN_ALLOWED",
                "reason": "LICENSE and embedded ISA detection notices preserved",
            },
            known_limitations=[
                "Frozen modern 1234 SSE4.1 encode/decode with declared scalar tails; no fallback.",
                "Separate source identity from old Benchmark variants.",
                "Full upstream tests include unregistered 0124/delta32/zigzag variants; "
                "their testing does not register them.",
                "Original upstream sanitizer fails modular signed ZigZag delta; "
                "bounded adapter excludes it; patched tests preserve modular32 arithmetic.",
                "Native API timer excludes count, staging, FFI, descriptor and P2 transforms.",
                "D wrapper is mandatory; A/B/C disabled representations are explicit "
                "and independently validated.",
                "Leak detection disabled; Linux x86_64 qualification only.",
            ]
            + (
                [
                    "Checked int64 subtraction/recovery overflow atomically rejects; "
                    "no scaling/sorting/raw fallback."
                ]
                if delta
                else ["uint32 UTS only; no implicit int64/float conversion."]
            ),
            upstream_tests=[
                {
                    "name": "full upstream unit + bounded ABI/stages + 1234 equivalence",
                    "status": "PASS",
                    "log_sha256": sha(tests_path),
                    "evidence": str(tests_path.relative_to(ROOT)),
                }
            ],
            builds=[],
        )
        card["output_contract"]["kind"] = document["semantics"]["rebuild_protocol"]
        card["input_contract"].update(alignment_bytes=1, external_padding_bytes=0)
        card["lifecycle_contract"]["encoder_padding"] = "INTERNAL_BOUND_PLUS_16"
        for profile in ("release", "debug", "sanitizer"):
            record = json.loads(
                (ROOT / f"build/adapters/{directory}/{profile}/build-record.json").read_text()
            )
            accepted = next(
                item
                for item in evidence["builds"]
                if item["algorithm"] == key and item["profile"] == profile
            )
            if record != accepted:
                raise RuntimeError(f"qualified build changed: {key}/{profile}")
            for item in (
                record["binding_sources"]
                + record["source_files"]
                + record["compiled_source_closure"]
            ):
                if sha(ROOT / item["path"]) != item["sha256"]:
                    raise RuntimeError(f"qualified dependency changed: {item['path']}")
            if sha(ROOT / record["artifact"]) != record["artifact_sha256"]:
                raise RuntimeError(f"qualified artifact changed: {key}/{profile}")
            card["builds"].append(
                {
                    "kind": profile,
                    "artifact_sha256": record["artifact_sha256"],
                    "compile_commands_sha256": record["compile_commands_sha256"],
                }
            )
        cards.append(validate_onboarding_card(card))
    write(ROOT / "registry/sources/streamvbyte-modern.artifact.json", source)
    for key, document, card in zip(KEYS, manifests, cards, strict=True):
        write(ROOT / f"registry/codecs/{key}.json", document)
        write(ROOT / f"registry/onboarding/{key}.json", card)
    print(source_id)


if __name__ == "__main__":
    main()
