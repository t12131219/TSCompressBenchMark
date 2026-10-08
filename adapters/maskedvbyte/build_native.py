"""Build frozen MaskedVByte plus its recorded patch and bounded ABI out of tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "adapters/maskedvbyte"
VENDOR = ADAPTER / "vendor/MaskedVByte"
KEY = "maskedvbyte-source-u32"
FLAGS = {
    "release": ["-O3", "-DNDEBUG"],
    "debug": ["-O0", "-g"],
    "sanitizer": [
        "-O1",
        "-g",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
    ],
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
    for item in lock["files"]:
        if sha(ROOT / item["path"]) != item["sha256"]:
            raise RuntimeError("frozen source drift: " + item["path"])
    out = ROOT / "build/adapters/maskedvbyte_u32" / profile
    out.mkdir(parents=True, exist_ok=True)
    record_path = out / "build-record.json"
    record_path.write_text(json.dumps({"status": "BUILDING", "algorithm": KEY}) + "\n")
    source = out / "patched-source"
    # Replace only this recipe's generated source snapshot, never the frozen vendor.
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(VENDOR, source)
    patches = sorted((ADAPTER / "patches").glob("*.patch"))
    if not patches:
        raise RuntimeError("unsigned-shift patch missing")
    commands, logs, objects, closure = [], [], [], set()
    for patch in patches:
        command = ["patch", "--batch", "--forward", "-p1", "-d", str(source), "-i", str(patch)]
        commands.append(command)
        logs.append(run(command))
    compiler = os.environ.get("CC", "clang" if profile == "sanitizer" else "cc")
    for name, translation_unit, isa in (
        ("shim", ADAPTER / "native/tscb_maskedvbyte.c", ["-march=x86-64", "-fno-tree-vectorize"]),
        ("encoder", source / "src/varintencode.c", ["-march=x86-64", "-fno-tree-vectorize"]),
        ("decoder", source / "src/varintdecode.c", ["-march=x86-64", "-msse4.1"]),
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
            "-mno-avx",
            "-mno-avx2",
            "-I",
            str(ROOT / "native/include"),
            "-I",
            str(source / "include"),
            "-MD",
            "-MF",
            str(deps),
            "-c",
            str(translation_unit),
            "-o",
            str(obj),
        ]
        commands.append(command)
        logs.append(run(command))
        dependency_text = deps.read_text().replace("\\\n", " ").partition(":")[2]
        closure.update(Path(value).resolve() for value in shlex.split(dependency_text))
        objects.append(obj)
    library = out / "libtscb_maskedvbyte_u32.so"
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
    ldd = run(["ldd", str(library)])
    dependencies = []
    for token in ldd.split():
        if token.startswith("/") and Path(token).is_file():
            dependencies.append(identity(Path(token).resolve()))
    bindings = [
        ADAPTER / "native/tscb_maskedvbyte.c",
        lock_path,
        ADAPTER / "contract.md",
        Path(__file__),
        ROOT / "native/include/tscb_adapter_v1.h",
        ROOT / "native/include/tscb_native_timing.h",
    ]
    bindings.extend(
        ROOT / name
        for name in (
            "src/tscompbench/adapters/maskedvbyte.py",
            "src/tscompbench/adapters/deflate_zlib.py",
            "src/tscompbench/adapters/native_timing.py",
            "src/tscompbench/adapters/factory.py",
            "src/tscompbench/preprocess/maskedvbyte.py",
            "src/tscompbench/preprocess/runtime.py",
            "src/tscompbench/execution/protocol.py",
            "src/tscompbench/execution/repetition.py",
            "src/tscompbench/execution/preflight.py",
            "tools/build_codec.py",
        )
    )
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "status": "PASS",
        "algorithm": KEY,
        "codec_keys": ["maskedvbyte-u32", "delta-maskedvbyte-u32"],
        "profile": profile,
        "artifact": str(library.relative_to(ROOT)),
        "artifact_sha256": sha(library),
        "compile_commands_sha256": hashlib.sha256(command_bytes).hexdigest(),
        "compiler": run([compiler, "--version"]).splitlines()[0],
        "command_display": [shlex.join(command) for command in commands],
        "build_log": "".join(logs),
        "ldd": ldd,
        "runtime_dependencies": dependencies,
        "source_lock_sha256": sha(lock_path),
        "source_files": lock["files"],
        "upstream_repository": lock["repository"],
        "upstream_commit": lock["commit"],
        "patches": [identity(path) for path in patches],
        "generated_source_files": [
            identity(source / Path(item["path"]).relative_to(VENDOR.relative_to(ROOT)))
            for item in lock["files"]
        ],
        "binding_sources": [identity(path) for path in bindings],
        "compiled_source_closure": [identity(path) for path in sorted(closure)],
        "objects": [identity(path) for path in objects],
        "shim_isa": "BASELINE_X86_64_NO_AUTOVECTORIZATION",
        "encoder_isa": "BASELINE_X86_64_NO_AUTOVECTORIZATION",
        "source_isa": "SSE4_1_WITH_SCALAR_TAIL",
        "runtime_fallback": False,
        "benchmark_registration": "PENDING_PYTHON_AND_FIVE_LAYER_QUALIFICATION",
    }
    record_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=(*FLAGS, "all"), default="all")
    args = parser.parse_args()
    for profile in FLAGS if args.profile == "all" else [args.profile]:
        result = build(profile)
        print(profile, result["artifact_sha256"], flush=True)


if __name__ == "__main__":
    main()
