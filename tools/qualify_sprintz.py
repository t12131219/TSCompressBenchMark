"""Rebuild and qualify the full Sprintz 8/16-bit UTS/MTS admission."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "adapters/sprintz"
VENDOR = ADAPTER / "vendor/sprintz"
PATCHES = (
    ADAPTER / "patches/0001-lowdim-byte-safety.patch",
    ADAPTER / "patches/0002-generic-allocation-safety.patch",
)
SOURCES = (
    "sprintz.cpp",
    "sprintz_delta_lowdim.cpp",
    "sprintz_xff_lowdim.cpp",
    "sprintz_delta_rle.cpp",
    "sprintz_xff_rle.cpp",
    "format.cpp",
)


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def source_closure_hash() -> str:
    lines = bytearray()
    for path in sorted(item for item in VENDOR.rglob("*") if item.is_file()):
        relative = path.relative_to(ADAPTER / "vendor").as_posix()
        lines.extend(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        lines.extend(b"  " + relative.encode("utf-8") + b"\n")
    return hashlib.sha256(lines).hexdigest()


def patch_set_hash() -> str:
    lines = bytearray()
    for path in PATCHES:
        relative = path.relative_to(ROOT).as_posix()
        lines.extend(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        lines.extend(b"  " + relative.encode("utf-8") + b"\n")
    return hashlib.sha256(lines).hexdigest()


def compile_test(name: str, *, sanitizer: bool, allocation_failure: bool = False) -> Path:
    profile = "sanitizer" if sanitizer else "release"
    source_root = ROOT / f"build/adapters/sprintz_delta/{profile}/sprintz"
    output = ROOT / f"build/qualification/{name}-{profile}"
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = [
        "-std=c++17",
        "-O1" if sanitizer else "-O2",
        "-g",
        "-fno-strict-aliasing",
        "-mavx2",
        "-mbmi2",
        "-mlzcnt",
        "-Wno-ignored-attributes",
        "-w",
    ]
    if sanitizer:
        flags += [
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
            "-fno-sanitize=alignment",
        ]
    command = [
        "c++",
        *flags,
        "-I",
        str(source_root),
        "-I",
        str(VENDOR),
        str(ADAPTER / f"tests/{name}.cc"),
        str(ADAPTER / "native/bounded_sprintz.cc"),
        *(str(source_root / item) for item in SOURCES),
    ]
    if allocation_failure:
        command += ["-Wl,--wrap=malloc", "-Wl,--wrap=calloc"]
    command += ["-o", str(output)]
    run(command)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(
            "/home/fzg/PycharmProjects/Compression_Source_Code/Source_Code/"
            "_repos/sprintz-lzbench/sprintz"
        ),
    )
    args = parser.parse_args()
    for vendor_file in sorted(item for item in VENDOR.iterdir() if item.is_file()):
        original = args.source_root / vendor_file.name
        if not original.is_file() or original.read_bytes() != vendor_file.read_bytes():
            raise RuntimeError(
                f"vendor source differs from audited lzbench file: {vendor_file.name}"
            )
    print(f"source closure sha256: {source_closure_hash()}", flush=True)
    print(f"patch set sha256: {patch_set_hash()}", flush=True)
    for algorithm in ("sprintz-delta", "sprintz-fire"):
        run([
            "conda", "run", "-n", "CompressBench14", "python",
            "tools/build_codec.py", algorithm, "--profile", "all",
        ])
    environment = os.environ.copy()
    environment.update(
        ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
        UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
    )
    for sanitizer in (False, True):
        binary = compile_test("bounded_sprintz_test", sanitizer=sanitizer)
        run([str(binary)], env=environment)
    allocation = compile_test(
        "allocation_failure_full", sanitizer=True, allocation_failure=True
    )
    run([str(allocation)], env=environment)
    print(
        "LeakSanitizer was not enabled because it is incompatible with the "
        "ptrace-managed execution environment.",
        flush=True,
    )


if __name__ == "__main__":
    main()
