"""Freeze the workbook LittleIntPacker closure and its original benchmark/tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT.parent / "Compression_Source_Code/Source_Code/_repos/fast-pack_LittleIntPacker"
ADAPTER = ROOT / "adapters/littleintpacker"
PIN = "8777f574a5ab3c653881371819383c986292843c"
FILES = (
    "LICENSE",
    "README.md",
    "makefile",
    "include/bitpacking.h",
    "include/portability.h",
    "include/util.h",
    "src/bitpacking32.c",
    "src/turbobitpacking32.c",
    "src/scpacking32.c",
    "src/bmipacking32.c",
    "src/horizontalpacking32.c",
    "src/util.c",
    "tests/unit.c",
    "benchmarks/bitpackingbenchmark.c",
)
APIS = {
    "PACK32": ["pack32", "unpack32"],
    "TURBO": ["turbopack32", "turbounpack32"],
    "SC": ["scpack32", "scunpack32"],
    "BMI2": ["bmipack32", "bmiunpack32"],
    "HORIZONTAL": ["pack32", "horizontalunpack32"],
}


def git(*args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(ORIGINAL), *args],
        capture_output=True,
        check=True,
    ).stdout


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    if git("rev-parse", "HEAD").decode().strip() != PIN:
        raise RuntimeError("LittleIntPacker source pin changed")
    if git("status", "--porcelain") or git("submodule", "status"):
        raise RuntimeError("LittleIntPacker source dirty or contains submodules")
    records = []
    for filename in FILES:
        data = git("show", f"{PIN}:{filename}")
        if (ORIGINAL / filename).read_bytes() != data:
            raise RuntimeError("checkout differs from pinned Git bytes: " + filename)
        target = ADAPTER / "vendor/littleintpacker" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError("existing vendored file differs: " + filename)
        target.write_bytes(data)
        records.append(
            {
                "upstream_path": filename,
                "path": str(target.relative_to(ROOT)),
                "sha256": sha(data),
                "bytes": len(data),
            }
        )
    lock = {
        "schema_version": "tscb.littleintpacker-source-lock.v1",
        "repository": "https://github.com/fast-pack/LittleIntPacker",
        "commit": PIN,
        "dirty": False,
        "submodules": [],
        "copy_policy": "TRACKED_PINNED_BYTES_NO_PATCH",
        "license": {
            "spdx": "Apache-2.0",
            "status": "RUN_ALLOWED",
            "file": "adapters/littleintpacker/vendor/littleintpacker/LICENSE",
        },
        "logical_entries": [
            {"audit_index": 134, "name": "Fixed-width Bit Packing"},
            {"audit_index": 138, "name": "LittleIntPacker"},
        ],
        "files": records,
        "source_apis": APIS,
        "benchmark": {
            "path": (
                "adapters/littleintpacker/vendor/littleintpacker/benchmarks/bitpackingbenchmark.c"
            ),
            "timing_policy": "RDTSC_FASTEST_OF_50000_NOT_USED_FOR_FORMAL_STATISTICS",
            "length": 128,
            "widths": list(range(1, 33)),
            "backend_selection": "ORIGINAL_REPOSITORY_BENCHMARK_AND_PUBLIC_APIS",
        },
        "upstream_unit": {
            "path": "tests/unit.c",
            "filtered": False,
            "api_pairs": list(APIS),
            "widths": list(range(33)),
            "lengths": list(range(513)),
            "trials_per_width": 100,
        },
        "input": {
            "dtype": "uint32",
            "width": "CALLER_SUPPLIED_0_TO_32",
            "count": "UINT32_LOGICAL_COUNT_NOT_BYTE_LENGTH",
            "original_length_formula": "ceil(count*width/8)_UINT32_OVERFLOW_POSSIBLE",
            "original_padding": "FULL_32_VALUE_KERNEL_AND_UP_TO_64BIT_WORD_ACCESS",
        },
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entries_qualified": False,
        "freezer_sha256": sha(Path(__file__).read_bytes()),
    }
    (ADAPTER / "SOURCE_LOCK.json").write_text(json.dumps(lock, indent=2) + "\n")
    print(json.dumps({"status": "SOURCE_FROZEN", "files": len(records), "commit": PIN}))


if __name__ == "__main__":
    main()
