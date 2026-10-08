"""Reproducible bounded Simple-9/16 shared-library builds; no source patches."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "adapters/fastpfor_simple"
FLAGS = {
    "release": ["-O3", "-DNDEBUG"],
    "debug": ["-O0", "-g", "-UNDEBUG"],
    "sanitizer": [
        "-O1",
        "-g",
        "-UNDEBUG",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
    ],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path),
    }


def build(profile: str) -> dict:
    lock_path = ADAPTER / "SOURCE_LOCK.json"
    lock = json.loads(lock_path.read_text())
    for item in lock["files"]:
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError("source drift: " + item["path"])
    directory = ROOT / "build/adapters/fastpfor_simple" / profile
    directory.mkdir(parents=True, exist_ok=True)
    record_path = directory / "build-record.json"
    observations = []
    record_path.write_text(json.dumps({"status": "BUILDING", "profile": profile}) + "\n")

    def run(command: list[str]) -> str:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        observations.append(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        if result.returncode:
            record_path.write_text(
                json.dumps({"status": "FAIL", "commands": observations}, indent=2) + "\n"
            )
            raise RuntimeError(shlex.join(command) + "\n" + result.stderr)
        return result.stdout

    baseline = [
        "-march=x86-64",
        "-mno-ssse3",
        "-mno-sse4.1",
        "-mno-avx",
        "-mno-avx2",
        "-mno-avx512f",
        "-fno-tree-vectorize",
        "-fno-tree-slp-vectorize",
    ]
    compiler = "/usr/bin/g++"
    obj, dependency = directory / "shim.o", directory / "shim.d"
    run(
        [
            compiler,
            "-std=c++17",
            "-fPIC",
            "-Wall",
            "-Wextra",
            "-Werror",
            *FLAGS[profile],
            *baseline,
            "-I",
            str(ROOT / "native/include"),
            "-I",
            str(ADAPTER / "vendor/fastpfor/headers"),
            "-MD",
            "-MF",
            str(dependency),
            "-c",
            str(ADAPTER / "native/tscb_fastpfor_simple.cpp"),
            "-o",
            str(obj),
        ]
    )
    library = directory / "libtscb_fastpfor_simple.so"
    run(
        [
            compiler,
            *FLAGS[profile],
            "-shared",
            "-Wl,-z,defs",
            "-Wl,-Bsymbolic-functions",
            str(obj),
            "-o",
            str(library),
        ]
    )
    compile_document = {
        "schema_version": "tscb.compile-command.v1",
        "algorithm": "fastpfor-simple-source",
        "profile": profile,
        "commands": [o["command"] for o in observations],
    }
    command_bytes = json.dumps(compile_document, sort_keys=True, separators=(",", ":")).encode()
    (directory / "compile-command.json").write_bytes(command_bytes + b"\n")
    closure = sorted(
        {
            Path(p).resolve()
            for p in shlex.split(dependency.read_text().replace("\\\n", " ").split(":", 1)[1])
        }
    )
    ldd = run(["ldd", str(library)])
    runtime = [
        identity(Path(p).resolve()) for p in ldd.split() if p.startswith("/") and Path(p).is_file()
    ]
    compiler_version = run([compiler, "--version"]).splitlines()[0]
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "status": "PASS",
        "algorithm": "fastpfor-simple-source",
        "profile": profile,
        "artifact": str(library.relative_to(ROOT)),
        "artifact_sha256": sha(library),
        "compile_commands_sha256": hashlib.sha256(command_bytes).hexdigest(),
        "compiler": compiler_version,
        "commands": observations,
        "command_display": [shlex.join(c) for c in compile_document["commands"]],
        "ldd": ldd,
        "runtime_dependencies": runtime,
        "source_lock_sha256": sha(lock_path),
        "source_files": lock["files"],
        "upstream_repository": lock["repository"],
        "upstream_commit": lock["commit"],
        "patches": [],
        "binding_sources": [
            identity(p)
            for p in (
                Path(__file__),
                lock_path,
                ADAPTER / "native/tscb_fastpfor_simple.cpp",
                ROOT / "native/include/tscb_adapter_v1.h",
                ROOT / "native/include/tscb_native_timing.h",
            )
        ],
        "compiled_source_closure": [identity(p) for p in closure],
        "objects": [identity(obj)],
        "dependency_files": [identity(dependency)],
        "source_isa": "BASELINE_X86_64_NO_AUTOVECTORIZATION",
        "runtime_fallback": False,
        "qualification": "NATIVE_SDK_FIVE_LAYERS_PENDING",
    }
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=(*FLAGS, "all"), default="all")
    args = parser.parse_args()
    for profile in FLAGS if args.profile == "all" else [args.profile]:
        result = build(profile)
        print(profile, result["artifact_sha256"], flush=True)
