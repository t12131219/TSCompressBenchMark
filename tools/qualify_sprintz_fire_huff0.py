"""Rebuild and qualify the paper-defined SprintzFIRE+Huf pipeline."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPRINTZ = ROOT / "adapters/sprintz"
ENTROPY = ROOT / "adapters/entropy_fse/vendor/lib"
PATCHES = (
    SPRINTZ / "patches/0001-lowdim-byte-safety.patch",
    SPRINTZ / "patches/0002-generic-allocation-safety.patch",
    SPRINTZ / "patches/0003-fire-prediction-overflow.patch",
)
SPRINTZ_SOURCES = (
    "sprintz.cpp",
    "sprintz_delta_lowdim.cpp",
    "sprintz_xff_lowdim.cpp",
    "sprintz_delta_rle.cpp",
    "sprintz_xff_rle.cpp",
    "format.cpp",
)
ENTROPY_SOURCES = (
    "fse_compress.c",
    "fse_decompress.c",
    "huf_compress.c",
    "huf_decompress.c",
    "entropy_common.c",
    "hist.c",
)


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def tree_hash(root: Path, relative_root: Path) -> str:
    lines = bytearray()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(relative_root).as_posix()
        lines.extend(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        lines.extend(b"  " + relative.encode("utf-8") + b"\n")
    return hashlib.sha256(lines).hexdigest()


def patch_hash() -> str:
    lines = bytearray()
    for path in PATCHES:
        relative = path.relative_to(ROOT).as_posix()
        lines.extend(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        lines.extend(b"  " + relative.encode("utf-8") + b"\n")
    return hashlib.sha256(lines).hexdigest()


def entropy_closure_hash() -> str:
    vendor = ENTROPY.parent
    files = sorted(path for path in ENTROPY.iterdir() if path.is_file()) + [
        vendor / "LICENSE"
    ]
    lines = bytearray()
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        lines.extend(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        lines.extend(b"  " + relative.encode("utf-8") + b"\n")
    return hashlib.sha256(lines).hexdigest()


def compile_test(profile: str) -> Path:
    source_root = ROOT / f"build/adapters/sprintz_fire_huff0/{profile}/sprintz"
    output = ROOT / f"build/qualification/sprintz-fire-huff0-{profile}"
    output.parent.mkdir(parents=True, exist_ok=True)
    flags = [
        "-std=c++17",
        "-O1" if profile == "sanitizer" else "-O2",
        "-g",
        "-fno-strict-aliasing",
        "-mavx2",
        "-mbmi2",
        "-mlzcnt",
        "-Wno-ignored-attributes",
        "-w",
    ]
    if profile == "sanitizer":
        flags += [
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
            "-fno-sanitize=alignment",
        ]
    command = [
        "c++",
        *flags,
        "-I",
        str(ROOT / "native/include"),
        "-I",
        str(source_root),
        "-I",
        str(SPRINTZ / "vendor/sprintz"),
        "-I",
        str(ENTROPY),
        str(SPRINTZ / "tests/sprintz_fire_huff0_test.cc"),
        str(SPRINTZ / "native/tscb_sprintz_fire_huff0.cc"),
        str(SPRINTZ / "native/bounded_sprintz.cc"),
        *(str(source_root / name) for name in SPRINTZ_SOURCES),
        *(str(ENTROPY / name) for name in ENTROPY_SOURCES),
        "-o",
        str(output),
    ]
    run(command)
    return output


def main() -> None:
    print(
        "Sprintz source closure sha256:",
        tree_hash(SPRINTZ / "vendor/sprintz", SPRINTZ / "vendor"),
        flush=True,
    )
    print(
        "Huff0 source closure sha256:",
        entropy_closure_hash(),
        flush=True,
    )
    print("Sprintz patch set sha256:", patch_hash(), flush=True)
    run([
        "conda",
        "run",
        "-n",
        "CompressBench14",
        "python",
        "tools/build_codec.py",
        "sprintz-fire-huff0",
        "--profile",
        "all",
    ])
    environment = os.environ.copy()
    environment.update(
        ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
        UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
    )
    for profile in ("release", "sanitizer"):
        run([str(compile_test(profile))], env=environment)
    print(
        "LeakSanitizer was not enabled because it is incompatible with the "
        "ptrace-managed execution environment.",
        flush=True,
    )


if __name__ == "__main__":
    main()
