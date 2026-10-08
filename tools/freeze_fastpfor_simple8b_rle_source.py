"""Freeze the workbook RLE source and reuse the verified complete FastPFOR unit closure."""

from __future__ import annotations

import json
from pathlib import Path

from audit_fastpfor_simple_upstream import audit as audit_upstream
from freeze_fastpfor_simple_source import PIN, ROOT, SOURCES, pinned, sha, tracked

ADAPTER = ROOT / "adapters/fastpfor_simple8b_rle"
FILES = (
    "LICENSE", "AUTHORS", "README.md", "headers/common.h", "headers/codecs.h",
    "headers/util.h", "headers/bitpacking.h", "headers/bitpackinghelpers.h",
    "headers/simple8b_rle.h",
)
REFERENCE_FILES = (
    "src/codecfactory.cpp", "src/unit.cpp", "src/inmemorybenchmark.cpp",
    "headers/cpubenchmark.h", "headers/deltautil.h", "unittest/test_simple8b.cpp",
    "CMakeLists.txt",
)


def freeze() -> dict:
    original = SOURCES / "fast-pack_FastPFOR"
    if pinned(original, PIN):
        raise RuntimeError("unexpected FastPFOR submodules")
    upstream = audit_upstream()
    upstream_path = ROOT / "build/source-audits/fastpfor_simple_upstream_tests.json"
    upstream_report = json.loads(upstream_path.read_text())
    if upstream_report["result"]["stdout"].count(
        "Simple8b_RLE encoding ... decoding ... ok!"
    ) != 5:
        raise RuntimeError("complete upstream unit did not exercise RLE")
    files = []
    for names, destination, role in (
        (FILES, ADAPTER / "vendor/fastpfor", "ORIGINAL_ALGORITHM"),
        (REFERENCE_FILES, ADAPTER / "references/fastpfor", "BENCHMARK_AND_TEST_REFERENCE"),
    ):
        for name in names:
            data = tracked(original, PIN, name)
            target = destination / name
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError("refusing to overwrite changed source: " + str(target))
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_bytes(data)
            files.append({"path": str(target.relative_to(ROOT)), "upstream_path": name,
                          "role": role, "bytes": len(data), "sha256": sha(data)})
    provenance = ROOT / "build/source-audits/fastpfor-simple8b-rle-provenance-2/report.json"
    observations = json.loads(provenance.read_text())
    if observations["status"] != "SOURCE_VARIANT_DIFFERENCES_RETAINED_NOT_QUALIFIED":
        raise RuntimeError("benchmark source comparison incomplete")
    lock = {
        "schema_version": "tscb.fastpfor-simple8b-rle-source-lock.v1",
        "repository": "https://github.com/fast-pack/FastPFOR", "commit": PIN,
        "dirty": False, "submodules": [],
        "logical_entries": [{"audit_index": 148, "name": "FastPFOR Simple8b_RLE"}],
        "copy_policy": "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH", "files": files,
        "license": {"spdx": "Apache-2.0", "status": "RUN_ALLOWED",
                    "path": str((ADAPTER / "vendor/fastpfor/LICENSE").relative_to(ROOT))},
        "public_apis": ["Simple8b_RLE<false>", "Simple8b_RLE<true>"],
        "primitive": "UINT32_NO_IMPLICIT_DELTA_OR_ZIGZAG",
        "benchmark_extraction_decision":
            "SPRINTZ_FACTORY_HAS_RLE_BUT_NO_LZBENCH_ENTRY_AND_DIFFERENT_RLE_SELECTION;"
            "USE_WORKBOOK_FASTPFOR_PIN_WITH_EXPLICIT_REFERENCE_VARIANT",
        "benchmark_comparison": {"path": str(provenance.relative_to(ROOT)),
                                 "sha256": sha(provenance.read_bytes())},
        "original_full_upstream_unit": {
            "report_path": str(upstream_path.relative_to(ROOT)),
            "report_sha256": sha(upstream_path.read_bytes()),
            "lock_path": "adapters/fastpfor_simple/UPSTREAM_UNIT_LOCK.json",
            "lock_sha256": upstream["source_lock_sha256"],
            "role": "REUSED_COMPLETE_UNFILTERED_SOURCE_UNIT_ONLY_NOT_SDK",
            "rle_zipf_cases": 5,
        },
        "freezer_sha256": sha(Path(__file__).read_bytes()),
        "source_safety": "ORIGINAL_FAILURES_RETAINED_PENDING_PATCH_VERIFICATION",
        "bounded_abi": "PENDING", "python_sdk": "PENDING",
        "benchmark_registration": "PENDING", "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
    }
    target = ADAPTER / "SOURCE_LOCK.json"
    if target.exists() and json.loads(target.read_text()) != lock:
        raise RuntimeError("refusing to replace changed source lock")
    target.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
    return lock


if __name__ == "__main__":
    lock = freeze()
    print(json.dumps({"status": "SOURCE_FROZEN_PATCH_AND_ABI_PENDING",
                      "file_count": len(lock["files"]), "original_rle_zipf_cases": 5}))
