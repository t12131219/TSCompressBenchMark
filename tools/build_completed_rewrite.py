"""Build the framework binding against a verified immutable standalone package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"abba": (1, "abba"), "fabba": (2, "fabba"), "deepzip": (7, "deepzip"), "dzip": (8, "dzip")}


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dependencies(output, package, torch_root, test_artifacts):
    listing = subprocess.check_output(["ldd", str(output)], text=True)
    if "not found" in listing:
        raise RuntimeError("unresolved runtime dependency: " + listing)
    paths = {Path(p).resolve() for p in re.findall("(?:=>\\s+)?(/\\S+)\\s+\\(", listing)}
    for entry in test_artifacts:
        test_listing = subprocess.check_output(["ldd", entry["path"]], text=True)
        if "not found" in test_listing:
            raise RuntimeError("unresolved test runtime dependency: " + test_listing)
        paths.update(
            Path(p).resolve() for p in re.findall("(?:=>\\s+)?(/\\S+)\\s+\\(", test_listing)
        )
    paths.discard(output.resolve())
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
    return (listing, [{"path": str(p), "sha256": sha(p)} for p in sorted(paths)], verified)


def compiled_dependencies(folder):
    """Read compiler-generated dependency files, including system headers."""
    paths = set()
    depfiles = sorted((folder / "cmake").rglob("*.o.d"))
    if not depfiles:
        raise RuntimeError("compiler dependency closure is missing")
    commands = json.loads((folder / "cmake/compile_commands.json").read_text())
    if not commands:
        raise RuntimeError("compile command universe is empty")
    for command in commands:
        arguments = command.get("arguments") or shlex.split(command["command"])
        try:
            object_name = arguments[arguments.index("-o") + 1]
        except (ValueError, IndexError) as error:
            raise RuntimeError("compile command has no object output") from error
        dependency_file = Path(command["directory"]) / (object_name + ".d")
        if not dependency_file.is_file():
            raise RuntimeError("compiled TU dependency file missing: " + str(dependency_file))
        source = Path(command["directory"]) / command["file"]
        content = dependency_file.read_text().replace("\\\n", " ")
        declared = {
            (Path(command["directory"]) / name).resolve()
            for name in shlex.split(content.partition(":")[2])
        }
        if source.resolve() not in declared:
            raise RuntimeError("compiled TU absent from its dependency file: " + str(source))
    for depfile in depfiles:
        content = depfile.read_text().replace("\\\n", " ")
        _, separator, dependencies_text = content.partition(":")
        if not separator:
            raise RuntimeError("invalid compiler dependency file: " + str(depfile))
        for name in shlex.split(dependencies_text):
            path = Path(name)
            if not path.is_absolute():
                path = folder / "cmake" / path
            paths.add(path.resolve())
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError("compiled dependency missing: " + ", ".join(missing))
    return [{"path": str(path), "sha256": sha(path)} for path in sorted(paths)]


def test_inventory(folder):
    document = json.loads(
        subprocess.check_output(
            ["ctest", "--test-dir", str(folder / "cmake"), "--show-only=json-v1"], text=True
        )
    )
    tests = document.get("tests", [])
    if not tests or any(not test.get("command") for test in tests):
        raise RuntimeError("completed rewrite has no executable CTest inventory")
    paths = {Path(test["command"][0]).resolve() for test in tests}
    if any(not path.is_file() for path in paths):
        raise RuntimeError("CTest executable is missing")
    return tests, [{"path": str(path), "sha256": sha(path)} for path in sorted(paths)]


def build(algorithm, profile, *, output_root=None):
    adapter = ROOT / "adapters/completed_rewrites"
    lock = json.loads((adapter / "FROZEN_SOURCES.json").read_text())
    package = algorithm
    for entry in lock["packages"][package]["files"]:
        path = ROOT / entry["path"]
        if sha(path) != entry["sha256"]:
            raise RuntimeError("frozen source drift: " + entry["path"])
    kind, target = KINDS[algorithm]
    folder = (output_root or ROOT / "build/adapters") / algorithm.replace("-", "_") / profile
    if output_root is not None and folder.exists():
        raise RuntimeError("new build output already exists: " + str(folder))
    folder.mkdir(parents=True, exist_ok=True)
    recipe = folder / "recipe"
    recipe.mkdir(exist_ok=True)
    model = (
        adapter / "vendor" / package / "tests/fixtures/biGRU.dzm" if algorithm == "deepzip" else ""
    )
    reconstruction_source = adapter / "tests/reconstruction_limits.cpp"
    reconstruction_test = ""
    if algorithm in {"abba", "fabba"}:
        reconstruction_test = f'''add_executable(reconstruction_limits "{reconstruction_source}")
target_link_libraries(reconstruction_limits PRIVATE {target})
target_compile_definitions(reconstruction_limits PRIVATE TSCB_RECONSTRUCTION_{algorithm.upper()})
target_link_options(reconstruction_limits PRIVATE -no-pie)
add_test(NAME reconstruction_capacity_and_cast_limits COMMAND reconstruction_limits {algorithm})
'''
    (recipe / "CMakeLists.txt").write_text(
        f'''cmake_minimum_required(VERSION 3.18)
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
'''
    )
    with (recipe / "CMakeLists.txt").open("a") as stream:
        stream.write(reconstruction_test)
    flags = "-fno-fast-math -ffp-contract=off"
    if profile == "sanitizer":
        flags += (
            " -O1 -g -fsanitize=address,undefined -fsanitize=float-cast-overflow"
            " -fno-omit-frame-pointer"
        )
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
    ]
    torch_root = os.environ.get(
        "TSCB_TORCH_ROOT",
        "/home/fzg/anaconda3/envs/CompressBench/lib/python3.11/site-packages/torch",
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
    tests, test_artifacts = test_inventory(folder)
    listing, runtime, pinned = dependencies(output, package, torch_root, test_artifacts)
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
        "compiled_source_closure": compiled_dependencies(folder),
        "ctest_tests": tests,
        "test_artifacts": test_artifacts,
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
            "FRAMEWORK_BINDING_AND_FROZEN_CPP_SOURCES;"
            " EXTERNAL_BINARY_RUNTIMES_NOT_INSTRUMENTED; LEAK_CHECK_DISABLED"
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
    parser.add_argument(
        "--output-root", type=Path, help="new build root; refuses existing profiles"
    )
    args = parser.parse_args()
    for profile in ("release", "sanitizer") if args.profile == "all" else (args.profile,):
        build(
            args.algorithm,
            profile,
            output_root=args.output_root.resolve() if args.output_root else None,
        )


if __name__ == "__main__":
    main()
