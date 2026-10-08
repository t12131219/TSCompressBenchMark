"""Build the exact source and baseline-ISA bounded shim out of tree.

This recipe is also consumable by the central builder when registration is ready.
The baseline shim and SSE4.1 source use separate translation units so the runtime
ISA gate does not itself require the gated ISA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "adapters/fast_differential"
VENDOR = ADAPTER / "vendor/FastDifferentialCoding"
KEY = "fast-differential-u32"
FLAGS = {
    "release": ["-O3", "-DNDEBUG"],
    "debug": ["-O0", "-g"],
    "sanitizer": ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path),
    }


def run(command: list[str]) -> str:
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(f"{shlex.join(command)}\n{result.stdout}{result.stderr}")
    return result.stdout + result.stderr


def build(profile: str) -> dict:
    lock_path = ADAPTER / "SOURCE_LOCK.json"
    lock = json.loads(lock_path.read_text())
    for entry in lock["files"]:
        if sha(ROOT / entry["path"]) != entry["sha256"]:
            raise RuntimeError(f"frozen source drift: {entry['path']}")
    out = ROOT / "build/adapters/fast_differential_u32" / profile
    out.mkdir(parents=True, exist_ok=True)
    # Mark stale output unqualified before rebuilding any object.
    record_path = out / "build-record.json"
    record_path.write_text(json.dumps({"status": "BUILDING", "algorithm": KEY}) + "\n")
    compiler = os.environ.get("CC", "cc")
    commands, logs, objects, closure = [], [], [], set()
    for name, source, isa in (
        (
            "shim",
            ADAPTER / "native/tscb_fast_differential.c",
            ["-march=x86-64", "-fno-tree-vectorize"],
        ),
        ("source", VENDOR / "src/fastdelta.c", ["-msse4.1"]),
    ):
        obj, deps = out / f"{name}.o", out / f"{name}.d"
        command = [
            compiler,
            "-std=c11",
            "-fPIC",
            "-Wall",
            "-Wextra",
            "-Werror",
            *FLAGS[profile],
            *isa,
            "-I",
            str(ROOT / "native/include"),
            "-I",
            str(VENDOR / "include"),
            "-MD",
            "-MF",
            str(deps),
            "-c",
            str(source),
            "-o",
            str(obj),
        ]
        commands.append(command)
        logs.append(run(command))
        dependency_text = deps.read_text().replace("\\\n", " ").partition(":")[2]
        closure.update(Path(value).resolve() for value in shlex.split(dependency_text))
        objects.append(obj)
    library = out / "libtscb_fast_differential_u32.so"
    command = [
        compiler,
        *FLAGS[profile],
        "-shared",
        "-Wl,-Bsymbolic-functions",
        *(str(obj) for obj in objects),
        "-o",
        str(library),
    ]
    commands.append(command)
    logs.append(run(command))
    command_doc = {
        "schema_version": "tscb.compile-command.v1",
        "algorithm": KEY,
        "profile": profile,
        "commands": commands,
    }
    command_bytes = json.dumps(command_doc, sort_keys=True, separators=(",", ":")).encode()
    (out / "compile-command.json").write_bytes(command_bytes + b"\n")
    dependencies = []
    ldd = run(["ldd", str(library)])
    for line in ldd.splitlines():
        tokens = line.split()
        paths = [Path(token) for token in tokens if token.startswith("/")]
        for path in paths:
            if path.is_file():
                dependencies.append(identity(path.resolve()))
    bindings = [
        ADAPTER / "native/tscb_fast_differential.c",
        lock_path,
        ADAPTER / "contract.md",
        Path(__file__),
        ROOT / "native/include/tscb_adapter_v1.h",
        ROOT / "native/include/tscb_native_timing.h",
    ]
    bindings.extend(
        ROOT / path
        for path in (
            "src/tscompbench/adapters/fast_differential.py",
            "src/tscompbench/adapters/deflate_zlib.py",
            "src/tscompbench/adapters/native_timing.py",
            "src/tscompbench/adapters/factory.py",
            "src/tscompbench/execution/protocol.py",
            "src/tscompbench/execution/repetition.py",
            "src/tscompbench/execution/orchestrator.py",
            "tools/build_codec.py",
        )
    )
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "status": "PASS",
        "algorithm": KEY,
        "profile": profile,
        "artifact": str(library.relative_to(ROOT)),
        "artifact_sha256": sha(library),
        "compile_commands_sha256": hashlib.sha256(command_bytes).hexdigest(),
        "compiler": run([compiler, "--version"]).splitlines()[0],
        "command_display": [shlex.join(value) for value in commands],
        "build_log": "".join(logs),
        "ldd": ldd,
        "runtime_dependencies": dependencies,
        "source_lock_sha256": sha(lock_path),
        "source_files": lock["files"],
        "upstream_repository": lock["repository"],
        "upstream_commit": lock["commit"],
        "binding_sources": [identity(path) for path in bindings],
        "compiled_source_closure": [identity(path) for path in sorted(closure)],
        "objects": [identity(path) for path in objects],
        "shim_isa": "BASELINE_X86_64_NO_AUTOVECTORIZATION",
        "source_isa": "SSE4_1_WITH_SCALAR_TAIL",
        "runtime_fallback": False,
        "benchmark_registration": "FACTORY_AVAILABLE_FIVE_LAYER_QUALIFICATION_SEPARATE",
    }
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=(*FLAGS, "all"), default="all")
    args = parser.parse_args()
    for profile in FLAGS if args.profile == "all" else [args.profile]:
        result = build(profile)
        print(profile, result["artifact_sha256"], flush=True)


if __name__ == "__main__":
    main()
