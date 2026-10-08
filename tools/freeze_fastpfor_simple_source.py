"""Freeze the workbook Simple-9/16 APIs and local upstream test dependencies."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = Path("/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/_repos")
ADAPTER = ROOT / "adapters/fastpfor_simple"
PIN = "2457e1ed1af35bbf7f4c509c863fa9797e637cb3"
GTEST_PIN = "2d804ff492e45222e841dc1a50904476fa64f4a0"
REFERENCE_PIN = "580c4f085381f31b1ad669525ed04e63cbc385f3"
FILES = (
    "LICENSE",
    "AUTHORS",
    "README.md",
    "headers/common.h",
    "headers/codecs.h",
    "headers/util.h",
    "headers/bitpacking.h",
    "headers/bitpackinghelpers.h",
    "headers/simple9.h",
    "headers/simple16.h",
    "unittest/test_simple16.cpp",
    "unittest/util.h",
    "unittest/test_driver.cpp",
)
GTEST_PREFIX = "lib/sdsl-lite/external/googletest/"


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        capture_output=True,
        check=True,
    ).stdout


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pinned(repo: Path, commit: str) -> list[str]:
    if git(repo, "rev-parse", "HEAD").decode().strip() != commit:
        raise RuntimeError("source pin changed: " + str(repo))
    if git(repo, "status", "--porcelain"):
        raise RuntimeError("source repository is not clean: " + str(repo))
    return git(repo, "submodule", "status").decode().splitlines()


def tracked(repo: Path, commit: str, path: str) -> bytes:
    data = (repo / path).read_bytes()
    if data != git(repo, "show", f"{commit}:{path}"):
        raise RuntimeError("source differs from pinned Git bytes: " + path)
    return data


def main() -> None:
    original, dependency, reference = (
        SOURCES / "fast-pack_FastPFOR",
        SOURCES / "and-gue_NeaTS",
        SOURCES / "sprintz-lzbench",
    )
    submodules = pinned(original, PIN)
    if submodules:
        raise RuntimeError("unexpected FastPFOR submodules")
    dependency_submodules = pinned(dependency, GTEST_PIN)
    reference_submodules = pinned(reference, REFERENCE_PIN)
    content = [
        (
            filename,
            ADAPTER / "vendor/fastpfor" / filename,
            tracked(original, PIN, filename),
            "ALGORITHM_AND_UPSTREAM_TEST",
        )
        for filename in FILES
    ]
    dependency_names = [
        name
        for name in git(dependency, "ls-tree", "-r", "--name-only", GTEST_PIN, GTEST_PREFIX)
        .decode()
        .splitlines()
        if name == GTEST_PREFIX + "LICENSE"
        or (name.startswith(GTEST_PREFIX + "googletest/include/") and name.endswith(".h"))
        or (
            name.startswith(GTEST_PREFIX + "googletest/src/")
            and name.endswith((".cc", ".h"))
            and not name.endswith("gtest_main.cc")
        )
    ]
    if not dependency_names:
        raise RuntimeError("local tracked Google Test closure missing")
    content.extend(
        (
            filename,
            ADAPTER / "third_party/googletest" / filename.removeprefix(GTEST_PREFIX),
            tracked(dependency, GTEST_PIN, filename),
            "UPSTREAM_TEST_ONLY",
        )
        for filename in dependency_names
    )
    references = []
    for repo, commit, paths, label in (
        (
            original,
            PIN,
            ("src/codecfactory.cpp", "src/unit.cpp", "src/inmemorybenchmark.cpp", "CMakeLists.txt"),
            "FASTPFOR",
        ),
        (
            reference,
            REFERENCE_PIN,
            (
                "_lzbench/compressors.cpp",
                "_lzbench/lzbench.h",
                "fastpfor/codecfactory.h",
                "fastpfor/simple9.h",
                "fastpfor/simple16.h",
            ),
            "SPRINTZ_LZBENCH",
        ),
    ):
        references.append(
            {
                "label": label,
                "commit": commit,
                "files": [
                    {"path": name, "sha256": sha(tracked(repo, commit, name))} for name in paths
                ],
            }
        )
    files = [
        {
            "upstream_path": name,
            "path": str(target.relative_to(ROOT)),
            "sha256": sha(data),
            "bytes": len(data),
            "role": role,
        }
        for name, target, data, role in content
    ]
    lock = {
        "schema_version": "tscb.fastpfor-simple-source-lock.v1",
        "repository": "https://github.com/fast-pack/FastPFOR",
        "commit": PIN,
        "dirty": False,
        "submodules": submodules,
        "copy_policy": "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH",
        "license": {
            "spdx": "Apache-2.0",
            "status": "RUN_ALLOWED",
            "file": str((ADAPTER / "vendor/fastpfor/LICENSE").relative_to(ROOT)),
        },
        "logical_entries": [
            {"audit_index": 145, "name": "Simple-9"},
            {"audit_index": 146, "name": "Simple-16"},
        ],
        "files": files,
        "test_dependency": {
            "repository": "https://github.com/and-gue/NeaTS",
            "commit": GTEST_PIN,
            "upstream_component": "google/googletest",
            "prefix": GTEST_PREFIX,
            "license": "BSD-3-Clause",
            "submodules": dependency_submodules,
            "scope": "LOCAL_TRACKED_GOOGLE_TEST_ONLY_NO_ALGORITHM_DEPENDENCY",
        },
        "benchmark_references": references,
        "sprintz_lzbench_submodules": reference_submodules,
        "benchmark_extraction_decision": (
            "LZBENCH_HAS_NO_SIMPLE9_OR_SIMPLE16_ENTRY;_ITS_GENERIC_WRAPPER_ROUNDS_RAW_BYTES_"
            "AND_IGNORES_BOUNDED_OUTPUT;_USE_WORKBOOK_FASTPFOR_PUBLIC_APIS_WITH_SOURCE_PARITY_REVIEW"
        ),
        "upstream_tests": "PENDING",
        "source_safety": "PENDING",
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
        "freezer_sha256": sha(Path(__file__).read_bytes()),
    }
    output = ADAPTER / "SOURCE_LOCK.json"
    if output.exists() and json.loads(output.read_text()) != lock:
        raise RuntimeError("refusing to replace an existing changed source lock")
    for name, target, data, _ in content:
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError("refusing to overwrite changed vendor file: " + name)
    for _, target, data, _ in content:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
    output.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": "SOURCE_FROZEN_QUALIFICATION_PENDING",
                "files": len(files),
                "bytes": sum(f["bytes"] for f in files),
                "source_lock_sha256": sha(output.read_bytes()),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
