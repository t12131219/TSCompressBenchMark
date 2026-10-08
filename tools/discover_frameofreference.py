"""Freeze and execute unmodified FOR source; preserve failures before any repair."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPOS = ROOT.parent / "Compression_Source_Code/Source_Code/_repos"
ORIGINAL = REPOS / "fast-pack_FrameOfReference"
ADAPTER = ROOT / "adapters/frameofreference"
PIN = "e1fd9b06e7e1811346284cf4a76d52410134a342"
FILES = (
    "LICENSE", "README.md", "CMakeLists.txt", "Makefile", "sampledata.txt",
    "include/bpacking.h", "include/common.h", "include/compression.h",
    "include/turbocompression.h", "include/turbopacking32.h", "include/turbopacking64.h",
    "include/util.h", "src/bpacking.cpp", "src/test.cpp",
    "scripts/turbopacking32.py", "scripts/turbopacking64.py",
)
PROFILES = {
    "release": ["-O3", "-DNDEBUG"],
    "debug": ["-O0", "-g", "-D_GLIBCXX_ASSERTIONS"],
    "sanitizer": ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args], check=True, capture_output=True).stdout


def save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError("refusing to replace existing bytes: " + str(path))
    else:
        path.write_bytes(data)


def identity(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", default="20261007-1")
    args = parser.parse_args()
    if not args.suffix or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in args.suffix):
        raise ValueError("invalid suffix")
    if os.sched_getaffinity(0) != {2}:
        raise RuntimeError("source discovery must run on CPU2")
    if sys.byteorder != "little":
        raise RuntimeError("the independent forensic wire reference covers little-endian hosts")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if git(ORIGINAL, "rev-parse", "HEAD").decode().strip() != PIN or git(ORIGINAL, "status", "--porcelain"):
        raise RuntimeError("workbook source pin/cleanliness mismatch")
    if git(ORIGINAL, "submodule", "status"):
        raise RuntimeError("unexpected submodules")
    out = ROOT / "build/source-audits" / ("frameofreference-baseline-" + args.suffix)
    out.mkdir(parents=True, exist_ok=False)
    report = {
        "status": "RUNNING", "scope": "UNMODIFIED_UPSTREAM_FORENSICS_ONLY", "audit_index": 149,
        "pin": PIN, "cpu_affinity": [2], "commands": [], "source_snapshot": [],
        "source_admission": "PENDING", "bounded_abi": "PENDING", "python_sdk": "PENDING",
        "benchmark_five_layers": "PENDING", "full_logical_entry_qualified": False,
    }
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")

    def write_report() -> None:
        (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")

    def run(command: list[str], name: str, timeout: int = 600) -> dict:
        log = out / (name + ".log")
        started = time.time()
        with log.open("wb") as output:
            process = subprocess.run(command, cwd=out, env=environment, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
        item = {"name": name, "command": command, "cwd": str(out), "returncode": process.returncode,
                "elapsed_seconds": time.time() - started, "log": identity(log), "cpu_affinity": [2]}
        report["commands"].append(item)
        write_report()
        print(json.dumps({"name": name, "returncode": process.returncode}), flush=True)
        return item

    try:
        records = []
        for name in FILES:
            data = git(ORIGINAL, "show", f"{PIN}:{name}")
            if (ORIGINAL / name).read_bytes() != data:
                raise RuntimeError("checkout differs from Git pin: " + name)
            target = ADAPTER / "vendor/frameofreference" / name
            save(target, data)
            records.append(dict(identity(target), upstream_path=name))
        lock = {
            "schema_version": "tscb.frameofreference-source-lock.v1", "repository": "https://github.com/fast-pack/FrameOfReference",
            "commit": PIN, "dirty": False, "submodules": [], "copy_policy": "TRACKED_PINNED_BYTES_NO_PATCH",
            "license": {"spdx": "Apache-2.0", "status": "RUN_ALLOWED", "file": records[0]["path"]},
            "logical_entries": [{"audit_index": 149, "name": "Frame of Reference (FOR)"}], "files": records,
            "source_apis": {"BASIC32": ["compress", "uncompress"], "TURBO32": ["turbocompress", "turbouncompress"], "TURBO64": ["turbocompress64", "turbouncompress64"]},
            "format": "NATIVE_ENDIAN_COUNT_MIN_MAX_GLOBAL_FOR_THEN_PACKED_BLOCKS_RAW_TAIL",
            "preprocessing": "GLOBAL_FOR_IS_SOURCE_CODEC_BEHAVIOR_NO_EXTERNAL_DELTA_ZIGZAG",
            "benchmark_selection": "WORKBOOK_PIN_WITH_ORIGINAL_UPSTREAM_TEST_AND_BENCHMARK_PROVENANCE_REVIEW_PENDING",
            "source_admission": "PENDING", "bounded_abi": "PENDING", "python_sdk": "PENDING", "benchmark_five_layers": "PENDING",
            "full_logical_entries_qualified": False, "freezer_sha256": sha(Path(__file__)),
        }
        save(ADAPTER / "SOURCE_LOCK.json", (json.dumps(lock, indent=2) + "\n").encode())
        inputs = [ROOT / r["path"] for r in records] + [ADAPTER / "SOURCE_LOCK.json", Path(__file__).resolve(), ADAPTER / "tests/source_probe.cpp"]
        for path in inputs:
            snapshot = out / "source_snapshot" / path.relative_to(ROOT)
            save(snapshot, path.read_bytes())
            report["source_snapshot"].append(dict(identity(path), snapshot=identity(snapshot)))
        compiler = run(["g++", "--version"], "compiler-version")
        if compiler["returncode"] != 0:
            raise RuntimeError("compiler unavailable")
        source = out / "source_snapshot/adapters/frameofreference/vendor/frameofreference"
        probe = out / "source_snapshot/adapters/frameofreference/tests/source_probe.cpp"
        for profile, flags in PROFILES.items():
            directory = out / profile
            directory.mkdir()
            common = ["g++", "-std=c++11", "-Wall", "-Wextra", *flags, "-I" + str(source / "include")]
            for kind, translation in [("bpacking", source / "src/bpacking.cpp"), ("upstream", source / "src/test.cpp"), ("probe", probe)]:
                object_file = directory / (kind + ".o")
                dep = directory / (kind + ".d")
                item = run(common + ["-MD", "-MF", str(dep), "-c", str(translation), "-o", str(object_file)], profile + "-build-" + kind)
                if item["returncode"] != 0:
                    raise RuntimeError("upstream/probe build failed")
                item["object"] = identity(object_file)
                item["compiler_dependencies"] = identity(dep)
                # A separate dependency file for every translation unit avoids losing headers.
                dependency_paths = dep.read_text().replace("\\\n", " ").split(":", 1)[1].split()
                for value in sorted(set(dependency_paths)):
                    path = Path(value)
                    snapshot = out / "compiler_dependency_snapshot" / path.relative_to("/")
                    save(snapshot, path.read_bytes())
                item["actual_compiler_closure"] = [{"path": value, "sha256": sha(Path(value)),
                                                     "snapshot": str((out / "compiler_dependency_snapshot" / Path(value).relative_to("/")).relative_to(ROOT))}
                                                    for value in sorted(set(dependency_paths))]
                write_report()
            for kind in ["upstream", "probe"]:
                binary = directory / kind
                item = run(["g++", *flags, str(directory / (kind + ".o")), str(directory / "bpacking.o"), "-o", str(binary)], profile + "-link-" + kind)
                if item["returncode"] != 0:
                    raise RuntimeError("upstream/probe link failed")
                item["binary"] = identity(binary)
                write_report()
            run([str(directory / "upstream"), str(source / "sampledata.txt")], profile + "-upstream-test")
            for variant, width, count, mode in [
                ("basic32", 0, 8, "check"), ("basic32", 0, 16, "check"), ("basic32", 0, 32, "check"),
                ("basic32", 1, 32, "check"),
                ("turbo32", 1, 32, "check"), ("turbo64", 1, 32, "check"),
                ("turbo32", 2, 32, "heap-encode"), ("turbo64", 2, 32, "heap-encode"),
                ("turbo32", 1, 32, "guard-encode"), ("turbo32", 1, 32, "guard-decode"),
                ("turbo64", 1, 32, "guard-encode"), ("turbo64", 1, 32, "guard-decode"),
            ]:
                run([str(directory / "probe"), variant, str(width), str(count), mode], f"{profile}-{variant}-w{width}-n{count}-{mode}")
        original_dirty = git(ORIGINAL, "status", "--porcelain")
        if original_dirty or git(ORIGINAL, "rev-parse", "HEAD").decode().strip() != PIN:
            raise RuntimeError("read-only source changed during execution")
        for item in report["source_snapshot"]:
            if sha(ROOT / item["path"]) != item["sha256"]:
                raise RuntimeError("execution source changed during discovery")
        report["status"] = "BASELINE_EXECUTED_ADMISSION_PENDING"
        report["source_original_modified"] = False
        write_report()
        print(json.dumps({"status": report["status"], "report": str((out / "report.json").relative_to(ROOT))}), flush=True)
    except BaseException as error:
        report["status"] = "DISCOVERY_DRIVER_FAILED"
        report["error"] = repr(error)
        write_report()
        raise


if __name__ == "__main__":
    main()
