"""Freeze the workbook SIMDComp source and its benchmark references without registration."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = Path("/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos")
ORIGINAL = SOURCES / "lemire_simdcomp"
COMMIT = "d5301778fe5045ca8099252de5a6ed8016a287df"
FILES = (
    "README.md",
    "LICENSE",
    "CMakeLists.txt",
    "cmake/simdcompConfig.cmake.in",
    "cmake/simdcomp.pc.in",
    "include/simdcomp.h",
    "include/portability.h",
    "include/neon128.h",
    "include/simdbitpacking.h",
    "include/simdintegratedbitpacking.h",
    "include/simdcomputil.h",
    "include/simdfor.h",
    "include/avxbitpacking.h",
    "include/avx512bitpacking.h",
    "src/simdbitpacking.c",
    "src/simdintegratedbitpacking.c",
    "src/simdcomputil.c",
    "src/simdfor.c",
    "src/simdpackedselect.c",
    "src/simdpackedsearch.c",
    "src/avxbitpacking.c",
    "src/avx512bitpacking.c",
    "tests/unit.c",
    "tests/unit_chars.c",
    "example/example.c",
    "benchmarks/benchmark.c",
    "benchmarks/bitpackingbenchmark.cpp",
)


def git(path: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(path), *arguments],
        capture_output=True,
        check=True,
    )
    return result.stdout


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def main() -> None:
    if git(ORIGINAL, "rev-parse", "HEAD").decode().strip() != COMMIT:
        raise RuntimeError("SIMDComp source pin changed")
    if git(ORIGINAL, "status", "--porcelain") or git(ORIGINAL, "submodule", "status"):
        raise RuntimeError("SIMDComp source must be clean without submodules")
    content = {}
    for filename in FILES:
        data = (ORIGINAL / filename).read_bytes()
        if data != git(ORIGINAL, "show", f"{COMMIT}:{filename}"):
            raise RuntimeError("working source differs from the pinned Git tree: " + filename)
        content[filename] = data
    # FastPFOR is a benchmark reference with its own API/container. Do not substitute
    # its different SIMDBinaryPacking identity for the workbook's original library.
    reference = SOURCES / "fast-pack_FastPFOR"
    reference_commit = git(reference, "rev-parse", "HEAD").decode().strip()
    if reference_commit != "2457e1ed1af35bbf7f4c509c863fa9797e637cb3":
        raise RuntimeError("FastPFOR reference pin changed")
    reference_files = []
    for filename in (
        "headers/simdbinarypacking.h",
        "headers/simdbitpacking.h",
        "src/simdbitpacking.cpp",
        "src/inmemorybenchmark.cpp",
        "LICENSE",
    ):
        data = (reference / filename).read_bytes()
        if data != git(reference, "show", f"{reference_commit}:{filename}"):
            raise RuntimeError("FastPFOR reference differs from its pin: " + filename)
        reference_files.append({"path": filename, "sha256": sha(data)})
    destination = ROOT / "adapters/simdcomp/vendor/simdcomp"
    for filename, data in content.items():
        target = destination / filename
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError("refusing to overwrite an existing changed vendor file: " + filename)
    files = []
    for filename, data in content.items():
        target = destination / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        files.append(
            {
                "upstream_path": filename,
                "path": str(target.relative_to(ROOT)),
                "sha256": sha(data),
                "bytes": len(data),
            }
        )
    lock = {
        "schema_version": "tscb.simdcomp-source-lock.v1",
        "repository": "https://github.com/lemire/simdcomp",
        "commit": COMMIT,
        "dirty": False,
        "submodules": [],
        "copy_policy": "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH",
        "license": {"spdx": "BSD-3-Clause", "status": "RUN_ALLOWED", "file": files[1]["path"]},
        "worksheet": "全量审计",
        "logical_entry_index": 137,
        "logical_name": "SIMDComp",
        "files": files,
        "benchmark_reference": {
            "repository": "https://github.com/fast-pack/FastPFOR",
            "commit": reference_commit,
            "files": reference_files,
            "scope_parity": "DIFFERENT_PUBLIC_API_AND_CONTAINER_NO_ALIAS",
        },
        "upstream_benchmarks": ["benchmarks/benchmark.c", "benchmarks/bitpackingbenchmark.cpp"],
        "source_tests": "PENDING",
        "bounded_abi": "PENDING",
        "sdk": "PENDING",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
        "freezer_sha256": sha(Path(__file__).read_bytes()),
    }
    output = ROOT / "adapters/simdcomp/SOURCE_LOCK.json"
    if output.exists() and json.loads(output.read_text()) != lock:
        raise RuntimeError("refusing to replace an existing changed source lock")
    output.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "files": len(files),
                "bytes": sum(item["bytes"] for item in files),
                "source_lock_sha256": sha(output.read_bytes()),
                "status": "FROZEN_SOURCE_QUALIFICATION_PENDING",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
