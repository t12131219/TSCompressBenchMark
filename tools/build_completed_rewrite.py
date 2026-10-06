"""Build the framework binding against a verified immutable standalone package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = {
    "abba": (1, "abba"),
    "fabba": (2, "fabba"),
    "influxdb-tsm-adaptive-timestamp": (3, "tsm_timestamp"),
    "prometheus-xor2-chunk": (4, "prometheus_xor2_chunk"),
    "tristan": (5, "tristan"),
    "corad": (6, "corad"),
    "deepzip": (7, "deepzip"),
    "dzip": (8, "dzip"),
    "walloc-1d": (9, "walloc"),
    "prometheus-histogram-st": (10, "histogram_st"),
    "prometheus-float-histogram-st": (11, "histogram_st"),
}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dependencies(output, package, torch_root):
    listing = subprocess.check_output(["ldd", str(output)], text=True)
    if "not found" in listing:
        raise RuntimeError("unresolved runtime dependency: " + listing)
    paths = {Path(p).resolve() for p in re.findall(r"(?:=>\s+)?(/\S+)\s+\(", listing)}
    pinned = []
    lock_path = ROOT / "adapters/completed_rewrites/vendor" / package / "DEPENDENCY_LOCK.json"
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text())
        pinned = lock.get("numerical_runtime", {}).get("files", []) or lock.get(
            "tensor_runtime", []
        )
    verified = []
    for entry in pinned:
        original = entry["path"]
        path = (
            Path(torch_root).parent / original.split("site-packages/")[1]
            if "site-packages/" in original
            else Path(original)
        )
        if not path.is_file() or sha(path) != entry["sha256"]:
            raise RuntimeError("pinned native dependency drift: " + str(path))
        verified.append(
            {"path": str(path.resolve()), "original_path": original, "sha256": entry["sha256"]}
        )
        paths.add(path.resolve())
    return listing, [{"path": str(p), "sha256": sha(p)} for p in sorted(paths)], verified


def build(algorithm, profile):
    adapter = ROOT / "adapters/completed_rewrites"
    lock = json.loads((adapter / "FROZEN_SOURCES.json").read_text())
    package = (
        "prometheus-histogram-st" if algorithm == "prometheus-float-histogram-st" else algorithm
    )
    for entry in lock["packages"][package]["files"]:
        path = ROOT / entry["path"]
        if sha(path) != entry["sha256"]:
            raise RuntimeError("frozen source drift: " + entry["path"])
    kind, target = KINDS[algorithm]
    folder = ROOT / "build/adapters" / algorithm.replace("-", "_") / profile
    folder.mkdir(parents=True, exist_ok=True)
    recipe = folder / "recipe"
    recipe.mkdir(exist_ok=True)
    model = (
        adapter
        / "vendor"
        / package
        / ("tests/fixtures/biGRU.dzm" if algorithm == "deepzip" else "models/stereo_5x.wlm")
    )
    if algorithm not in {"deepzip", "walloc-1d"}:
        model = ""
    (recipe / "CMakeLists.txt").write_text(f'''cmake_minimum_required(VERSION 3.18)
project(completed_rewrite_binding LANGUAGES C CXX)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_STANDARD 17)
enable_testing()
add_subdirectory("{adapter / "vendor" / package}" standalone)
add_library(tscb_binding SHARED "{adapter / "native/binding.cpp"}")
target_link_libraries(tscb_binding PRIVATE {target})
target_compile_definitions(tscb_binding PRIVATE RW_KIND={kind} RW_KEY="{algorithm}")
set_target_properties(tscb_binding PROPERTIES
  OUTPUT_NAME tscb_{algorithm.replace("-", "_")}
  LIBRARY_OUTPUT_DIRECTORY "{folder}")
add_executable(binding_qualification "{adapter / "tests/qualification.cpp"}")
target_include_directories(binding_qualification PRIVATE "{adapter / "native"}")
target_compile_definitions(binding_qualification PRIVATE RW_KIND={kind})
target_link_libraries(binding_qualification PRIVATE tscb_binding)
target_link_options(binding_qualification PRIVATE -no-pie)
add_test(NAME framework_binding_qualification COMMAND binding_qualification "{model}")
''')
    flags = "-fno-fast-math -ffp-contract=off"
    if profile == "sanitizer":
        flags += " -O1 -g -fsanitize=address,undefined -fno-omit-frame-pointer"
    command = [
        "cmake",
        "-S",
        str(recipe),
        "-B",
        str(folder / "cmake"),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DCMAKE_CXX_FLAGS=" + flags,
        "-DCMAKE_C_FLAGS=" + flags,
        "-DCMAKE_EXE_LINKER_FLAGS=" + ("-no-pie" if profile == "sanitizer" else ""),
        "-DDEEPZIP_WITH_HDF5=OFF",
        "-DDEEPZIP_WITH_CUDA=OFF",
        "-DDZIP_WITH_HDF5=OFF",
        "-DDZIP_WITH_CUDA=OFF",
        "-DTRISTAN_MKL_ROOT=/home/fzg/anaconda3",
    ]
    torch_root = os.environ.get(
        "WALLOC_TORCH_ROOT",
        "/home/fzg/anaconda3/envs/CompressBench/lib/python3.11/site-packages/torch",
    )
    if algorithm == "walloc-1d":
        command.extend(
            [
                "-DWALLOC_TORCH_ROOT=" + torch_root,
                "-DCMAKE_CUDA_COMPILER=/usr/local/cuda-11.8/bin/nvcc",
                "-DCUDAToolkit_ROOT=/usr/local/cuda-11.8",
            ]
        )
    logs = []
    jobs = int(os.environ.get("TSCB_REWRITE_BUILD_JOBS", "2"))
    if not 1 <= jobs <= 16:
        raise ValueError("build jobs must be in 1..16")
    for cmd in [command, ["cmake", "--build", str(folder / "cmake"), f"-j{jobs}"]]:
        run = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        logs.append(run.stdout)
        (folder / "build.log").write_text("\n".join(logs))
        if run.returncode:
            raise RuntimeError(f"build failed; see {folder / 'build.log'}\n" + run.stdout[-3000:])
    output = folder / f"libtscb_{algorithm.replace('-', '_')}.so"
    listing, runtime, pinned = dependencies(output, package, torch_root)
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "algorithm": algorithm,
        "profile": profile,
        "artifact": str(output.relative_to(ROOT)),
        "artifact_sha256": sha(output),
        "compile_commands_sha256": sha(folder / "cmake/compile_commands.json"),
        "frozen_sources_sha256": sha(adapter / "FROZEN_SOURCES.json"),
        "configure_command": command,
        "dependencies": listing,
        "runtime_dependencies": runtime,
        "pinned_native_dependencies": pinned,
        "compiler": subprocess.check_output(["c++", "--version"], text=True),
        "binding_sources": [
            {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
            for p in [adapter / "native/binding.cpp", adapter / "native/binding.hpp"]
        ],
        "qualification_source_sha256": sha(adapter / "tests/qualification.cpp"),
        "build_recipe_sha256": sha(recipe / "CMakeLists.txt"),
        "build_driver_sha256": sha(Path(__file__)),
        "runtime_profile": "CPU_ONLY; HDF5_IMPORT_DISABLED; NO_PYTHON_CODEC_OR_EXPORTED_GRAPH",
        "sanitizer_scope": (
            "FRAMEWORK_BINDING_AND_FROZEN_CPP_SOURCES; "
            "EXTERNAL_BINARY_RUNTIMES_NOT_INSTRUMENTED; LEAK_CHECK_DISABLED"
        )
        if profile == "sanitizer"
        else "NOT_APPLICABLE",
    }
    (folder / "build-record.json").write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                "algorithm": algorithm,
                "profile": profile,
                "artifact_sha256": record["artifact_sha256"],
            }
        )
    )
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("algorithm", choices=KINDS)
    parser.add_argument("--profile", choices=["release", "sanitizer", "all"], default="release")
    args = parser.parse_args()
    for profile in ("release", "sanitizer") if args.profile == "all" else (args.profile,):
        build(args.algorithm, profile)


if __name__ == "__main__":
    main()
