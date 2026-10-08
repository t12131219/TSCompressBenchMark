"""Build the RLE shim against the actual locked patch; building grants no native qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from audit_fastpfor_simple8b_rle_source import audit as audit_source  # noqa: E402

ADAPTER = Path(__file__).resolve().parent
PROFILES = {
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
BASELINE = [
    "-march=x86-64",
    "-mno-ssse3",
    "-mno-sse4.1",
    "-mno-avx",
    "-mno-avx2",
    "-mno-avx512f",
    "-fno-tree-vectorize",
    "-fno-tree-slp-vectorize",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path),
    }


def build(profile: str, build_id: str = "20261007-2") -> dict:
    if profile not in PROFILES or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,63}", build_id):
        raise ValueError("invalid profile/build ID")
    source = audit_source()
    directory = ROOT / "build/adapters/fastpfor_simple8b_rle" / build_id / profile
    if directory.exists():
        raise RuntimeError("preserve prior build; choose a new build ID")
    directory.mkdir(parents=True)
    (directory / "builder.py").write_bytes(Path(__file__).read_bytes())
    record = {
        "status": "BUILDING",
        "profile": profile,
        "build_id": build_id,
        "algorithm": "fastpfor-simple8b-rle-source",
        "commands": [],
        "source_audit": source,
        "actual_cpu_affinity": sorted(os.sched_getaffinity(0)),
        "qualification": "NATIVE_SDK_REGISTRY_FIVE_LAYERS_PENDING",
    }
    record_path = directory / "build-record.json"

    def save() -> None:
        record_path.write_text(json.dumps(record, indent=2) + "\n")

    def run(command: list[str]) -> str:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
        record["commands"].append(
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
        save()
        if result.returncode:
            raise RuntimeError(shlex.join(command) + "\n" + result.stderr[-4000:])
        return result.stdout

    save()
    try:
        if record["actual_cpu_affinity"] != [2]:
            raise RuntimeError("auxiliary builds require CPU2")
        source_lock = ADAPTER / "SOURCE_LOCK.json"
        patch_lock = ADAPTER / "PATCH_LOCK.json"
        lock, patch = json.loads(source_lock.read_text()), json.loads(patch_lock.read_text())
        generated = directory / "generated"
        for item in lock["files"]:
            if item["role"] == "ORIGINAL_ALGORITHM":
                target = generated / item["upstream_path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / item["path"]).read_bytes())
        run(
            [
                "/usr/bin/patch",
                "--batch",
                "--forward",
                "-p1",
                "-d",
                str(generated),
                "-i",
                str(ROOT / patch["patch"]["path"]),
            ]
        )
        if sha(generated / "headers/simple8b_rle.h") != patch["patched_sha256"]:
            raise RuntimeError("applied source patch differs")
        flags = [*PROFILES[profile], *BASELINE]
        obj, dep = directory / "shim.o", directory / "shim.d"
        binding = ADAPTER / "native/tscb_fastpfor_simple8b_rle.cpp"
        run(
            [
                "/usr/bin/g++",
                "-std=c++17",
                "-fPIC",
                "-Wall",
                "-Wextra",
                "-Werror",
                *flags,
                "-I",
                str(ROOT / "native/include"),
                "-I",
                str(generated / "headers"),
                "-MD",
                "-MF",
                str(dep),
                "-c",
                str(binding),
                "-o",
                str(obj),
            ]
        )
        library = directory / "libtscb_fastpfor_simple8b_rle.so"
        run(
            [
                "/usr/bin/g++",
                *PROFILES[profile],
                "-shared",
                "-Wl,-z,defs",
                "-Wl,-Bsymbolic",
                str(obj),
                "-o",
                str(library),
            ]
        )
        closure = sorted(
            {
                Path(p).resolve()
                for p in shlex.split(dep.read_text().replace("\\\n", " ").split(":", 1)[1])
            }
        )
        ldd = run(["ldd", str(library)])
        runtime = [
            identity(Path(p).resolve())
            for p in ldd.split()
            if p.startswith("/") and Path(p).is_file()
        ]
        compiler_version = run(["/usr/bin/g++", "--version"]).splitlines()[0]
        exports = run(["/usr/bin/nm", "-D", "--defined-only", str(library)])
        record.update(
            status="PASS",
            artifact=identity(library),
            objects=[identity(obj)],
            dependency_files=[identity(dep)],
            compiled_source_closure=[identity(p) for p in closure],
            runtime_dependencies=runtime,
            ldd=ldd,
            exports=exports,
            compiler=compiler_version,
            source_lock_sha256=sha(source_lock),
            patch_lock_sha256=sha(patch_lock),
            source_files=lock["files"],
            patches=[patch["patch"]],
            generated_source_files=[
                identity(p) for p in sorted(generated.rglob("*")) if p.is_file()
            ],
            binding_sources=[
                identity(p)
                for p in (
                    Path(__file__),
                    binding,
                    source_lock,
                    patch_lock,
                    ROOT / "native/include/tscb_adapter_v1.h",
                    ROOT / "native/include/tscb_native_timing.h",
                )
            ],
            source_isa="BASELINE_X86_64_NO_AUTOVECTORIZATION",
            runtime_fallback=False,
        )
        return record
    except Exception as error:
        record.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=(*PROFILES, "all"), default="all")
    parser.add_argument("--build-id", default="20261007-2")
    args = parser.parse_args()
    for profile in PROFILES if args.profile == "all" else [args.profile]:
        result = build(profile, args.build_id)
        print(profile, result["artifact"]["sha256"], flush=True)
