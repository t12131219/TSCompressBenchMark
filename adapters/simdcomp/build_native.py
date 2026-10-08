"""Build SIMDComp's bounded ABI with separate baseline, SSE4.1 and AVX2 objects."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "adapters/simdcomp"
FLAGS = {
    "release": ["-O3", "-DNDEBUG"],
    "debug": ["-O0", "-g", "-DSIMDCOMP_DEBUG"],
    "sanitizer": [
        "-O1",
        "-g",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
    ],
}
SSE_UNITS = (
    "simdbitpacking",
    "simdintegratedbitpacking",
    "simdfor",
    "simdcomputil",
    "simdpackedselect",
    "simdpackedsearch",
)
OBJECT_NAMES = ("shim", *SSE_UNITS, "avxbitpacking", "avx2_bridge")


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
            raise RuntimeError("frozen source drift: " + item["path"])
    out = ROOT / "build/adapters/simdcomp_u32" / profile
    out.mkdir(parents=True, exist_ok=True)
    record_path = out / "build-record.json"
    record_path.write_text(json.dumps({"status": "BUILDING", "profile": profile}) + "\n")
    source = out / "patched-source"
    if source.exists():
        shutil.rmtree(source)
    shutil.copytree(ADAPTER / "vendor/simdcomp", source)
    patches = [
        *sorted((ADAPTER / "patches").glob("*.patch")),
        ADAPTER / "patches/avx2/0001-zero-width-unpack-byte-count.patch",
    ]
    commands, observations, objects, closure = [], [], [], set()

    def run(command: list[str]) -> str:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=600)
        commands.append(command)
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
        return result.stdout + result.stderr

    for patch in patches:
        run(["patch", "--batch", "--forward", "-p1", "-d", str(source), "-i", str(patch)])
    compiler = "/usr/bin/cc"
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
    sse = ["-march=x86-64", "-msse4.1", "-mno-avx", "-mno-avx2", "-mno-avx512f"]
    avx = ["-march=x86-64", "-mavx2", "-mno-avx512f"]
    units = [("shim", ADAPTER / "native/tscb_simdcomp.c", baseline)]
    units += [(name, source / "src" / (name + ".c"), sse) for name in SSE_UNITS]
    units += [
        ("avxbitpacking", source / "src/avxbitpacking.c", avx),
        ("avx2_bridge", ADAPTER / "native/avx2_bridge.c", avx),
    ]
    for name, unit, isa in units:
        obj, deps = out / (name + ".o"), out / (name + ".d")
        run(
            [
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
                str(source / "include"),
                "-MD",
                "-MF",
                str(deps),
                "-c",
                str(unit),
                "-o",
                str(obj),
            ]
        )
        closure.update(
            Path(p).resolve()
            for p in shlex.split(deps.read_text().replace("\\\n", " ").partition(":")[2])
        )
        objects.append(obj)
    library = out / "libtscb_simdcomp_u32.so"
    run(
        [
            compiler,
            *FLAGS[profile],
            "-shared",
            "-Wl,-z,defs",
            "-Wl,-Bsymbolic-functions",
            *(str(p) for p in objects),
            "-o",
            str(library),
        ]
    )
    command_doc = {
        "schema_version": "tscb.compile-command.v1",
        "algorithm": "simdcomp-source-u32",
        "profile": profile,
        "commands": commands.copy(),
    }
    command_bytes = json.dumps(command_doc, sort_keys=True, separators=(",", ":")).encode()
    (out / "compile-command.json").write_bytes(command_bytes + b"\n")
    ldd = run(["ldd", str(library)])
    dependencies = [
        identity(Path(p).resolve()) for p in ldd.split() if p.startswith("/") and Path(p).is_file()
    ]
    compiler_version = run([compiler, "--version"]).splitlines()[0]
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "status": "PASS",
        "algorithm": "simdcomp-source-u32",
        "profile": profile,
        "artifact": str(library.relative_to(ROOT)),
        "artifact_sha256": sha(library),
        "compile_commands_sha256": hashlib.sha256(command_bytes).hexdigest(),
        "compiler": compiler_version,
        "command_display": [shlex.join(c) for c in command_doc["commands"]],
        "commands": observations,
        "ldd": ldd,
        "runtime_dependencies": dependencies,
        "source_lock_sha256": sha(lock_path),
        "source_files": lock["files"],
        "upstream_repository": lock["repository"],
        "upstream_commit": lock["commit"],
        "patches": [identity(p) for p in patches],
        "generated_source_files": [identity(source / p["upstream_path"]) for p in lock["files"]],
        "binding_sources": [
            identity(p)
            for p in (
                Path(__file__),
                lock_path,
                ADAPTER / "contract.md",
                ADAPTER / "native/tscb_simdcomp.c",
                ADAPTER / "native/avx2_bridge.c",
                ROOT / "native/include/tscb_adapter_v1.h",
                ROOT / "native/include/tscb_native_timing.h",
            )
        ],
        "compiled_source_closure": [identity(p) for p in sorted(closure)],
        "objects": [identity(p) for p in objects],
        "shim_isa": "BASELINE_X86_64_NO_AUTOVECTORIZATION",
        "source_isa": "SSE4_1_AND_SEPARATE_AVX2_OBJECTS_NO_AVX512",
        "runtime_fallback": False,
        "benchmark_registration": "PENDING_PYTHON_AND_FIVE_LAYER_QUALIFICATION",
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
