"""Build five original API pairs with the recorded correction, in separate ISA units."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "adapters/littleintpacker"
sys.path.insert(0, str(ROOT / "tools"))
from audit_littleintpacker_source import audit  # noqa: E402

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
SOURCES = {
    "bitpacking32.c": [],
    "turbobitpacking32.c": [],
    "scpacking32.c": [],
    "bmipacking32.c": ["-mavx2", "-mbmi2"],
    "horizontalpacking32.c": ["-mssse3", "-msse4.1"],
    "util.c": [],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def identity(path: Path) -> dict:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path),
    }


def dependencies(path: Path) -> list[dict]:
    names = shlex.split(path.read_text().replace("\\\n", " ").split(":", 1)[1])
    return [identity(p) for p in sorted({Path(name).resolve() for name in names})]


def build(profile: str) -> dict:
    source_audit = audit()
    lock_path, patch_path = ADAPTER / "SOURCE_LOCK.json", ADAPTER / "PATCH_LOCK.json"
    lock, patch_lock = json.loads(lock_path.read_text()), json.loads(patch_path.read_text())
    directory = ROOT / "build/adapters/littleintpacker" / profile
    directory.mkdir(parents=True, exist_ok=True)
    record_path = directory / "build-record.json"
    record = {"status": "BUILDING", "profile": profile, "commands": []}

    def save() -> None:
        record_path.write_text(json.dumps(record, indent=2) + "\n")

    def run(command: list[str]) -> str:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=240)
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
            raise RuntimeError(shlex.join(command) + "\n" + result.stderr)
        return result.stdout

    save()
    try:
        generated = directory / "generated"
        for item in lock["files"]:
            original = ROOT / item["path"]
            if sha(original) != item["sha256"]:
                raise RuntimeError("vendor source drift")
            target = generated / item["upstream_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
        run(
            [
                "/usr/bin/patch",
                "--batch",
                "--forward",
                "-p1",
                "-d",
                str(generated),
                "-i",
                str(ROOT / patch_lock["patch"]["path"]),
            ]
        )
        expected = {item["upstream_path"]: item["sha256"] for item in lock["files"]}
        expected.update(
            {item["upstream_path"]: item["patched_sha256"] for item in patch_lock["changes"]}
        )
        for name, digest in expected.items():
            if sha(generated / name) != digest:
                raise RuntimeError("applied patch differs from locked bytes: " + name)
        units, objects = [], []
        for name, isa in (*SOURCES.items(), ("shim", [])):
            cpp = name == "shim"
            source = (
                ADAPTER / "native/tscb_littleintpacker.cpp" if cpp else generated / "src" / name
            )
            obj, dep = directory / (name + ".o"), directory / (name + ".d")
            command = [
                "/usr/bin/g++" if cpp else "/usr/bin/gcc",
                "-std=c++17" if cpp else "-std=c99",
                "-fPIC",
                "-Wall",
                "-Wextra",
                *(["-Werror"] if cpp else []),
                *FLAGS[profile],
                *BASELINE,
                *isa,
                "-I",
                str(ROOT / "native/include"),
                "-I",
                str(generated / "include"),
                "-MD",
                "-MF",
                str(dep),
                "-c",
                str(source),
                "-o",
                str(obj),
            ]
            run(command)
            units.append(
                {
                    "source": identity(source),
                    "object": identity(obj),
                    "dependency": identity(dep),
                    "command": command,
                    "compiler_closure": dependencies(dep),
                    "required_isa_flags": isa,
                }
            )
            objects.append(obj)
        library = directory / "libtscb_littleintpacker.so"
        run(
            [
                "/usr/bin/g++",
                *FLAGS[profile],
                "-shared",
                "-Wl,-z,defs",
                "-Wl,-Bsymbolic-functions",
                *map(str, objects),
                "-o",
                str(library),
            ]
        )
        compile_document = {
            "schema_version": "tscb.compile-command.v1",
            "algorithm": "littleintpacker-source",
            "profile": profile,
            "commands": [r["command"] for r in record["commands"]],
        }
        command_bytes = json.dumps(compile_document, sort_keys=True, separators=(",", ":")).encode()
        (directory / "compile-command.json").write_bytes(command_bytes + b"\n")
        ldd = run(["ldd", str(library)])
        runtime = [
            identity(Path(p).resolve())
            for p in ldd.split()
            if p.startswith("/") and Path(p).is_file()
        ]
        compiler = run(["/usr/bin/g++", "--version"]).splitlines()[0]
        c_compiler = run(["/usr/bin/gcc", "--version"]).splitlines()[0]
        record.update(
            schema_version="tscb.build-artifact.v1",
            status="PASS",
            algorithm="littleintpacker-source",
            artifact=str(library.relative_to(ROOT)),
            artifact_sha256=sha(library),
            compile_commands_sha256=hashlib.sha256(command_bytes).hexdigest(),
            compiler=compiler,
            c_compiler=c_compiler,
            ldd=ldd,
            runtime_dependencies=runtime,
            source_lock_sha256=sha(lock_path),
            patch_lock_sha256=sha(patch_path),
            source_files=lock["files"],
            upstream_repository=lock["repository"],
            upstream_commit=lock["commit"],
            patches=[patch_lock["patch"]],
            source_audit=source_audit,
            translation_units=units,
            binding_sources=[
                identity(p)
                for p in (
                    Path(__file__),
                    lock_path,
                    patch_path,
                    ROOT / "tools/audit_littleintpacker_source.py",
                    ADAPTER / "native/tscb_littleintpacker.cpp",
                    ROOT / "native/include/tscb_adapter_v1.h",
                    ROOT / "native/include/tscb_native_timing.h",
                )
            ],
            generated_sources=[identity(generated / name) for name in expected],
            objects=[identity(p) for p in objects],
            runtime_fallback=False,
            native_abi="EXECUTION_TESTS_PENDING",
            python_sdk="PENDING",
            benchmark_five_layers="PENDING",
            full_logical_entries_qualified=False,
        )
        save()
        return record
    except Exception as error:
        record.update(status="FAIL", error=str(error))
        save()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=(*FLAGS, "all"), default="all")
    args = parser.parse_args()
    for profile in FLAGS if args.profile == "all" else [args.profile]:
        result = build(profile)
        print(profile, result["artifact_sha256"], flush=True)
