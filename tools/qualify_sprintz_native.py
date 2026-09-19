"""Rebuild and exercise the limited Sprintz 8-bit native admission candidate."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPRINTZ = ROOT / "adapters/sprintz"
VENDOR = SPRINTZ / "vendor/sprintz"
PATCH = SPRINTZ / "patches/0001-lowdim-byte-safety.patch"
SOURCES = ("sprintz_delta_lowdim.cpp", "sprintz_xff_lowdim.cpp", "bitpack.h")


def run(command: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    print(f"patch sha256: {hashlib.sha256(PATCH.read_bytes()).hexdigest()}", flush=True)
    with tempfile.TemporaryDirectory(prefix="tscb-sprintz-") as work:
        workspace = Path(work)
        target = workspace / "sprintz"
        target.mkdir()
        for name in SOURCES:
            shutil.copy2(VENDOR / name, target / name)
        baseline = workspace / "baseline-encoder"
        encoder_test = SPRINTZ / "tests/encoder_bytes.cc"

        def compile_encoder(destination: Path, sources: Path) -> None:
            run(["c++", "-std=c++17", "-O2", "-mavx2", "-mbmi2", "-mlzcnt",
                 "-Wno-ignored-attributes", "-w", "-I", str(VENDOR), str(encoder_test),
                 str(sources / SOURCES[0]), str(sources / SOURCES[1]),
                 "-o", str(destination)])

        compile_encoder(baseline, VENDOR)
        run(["git", "apply", "--check", str(PATCH)], cwd=workspace)
        run(["git", "apply", str(PATCH)], cwd=workspace)
        patched = workspace / "patched-encoder"
        compile_encoder(patched, target)
        original_bytes = subprocess.check_output([str(baseline)])
        patched_bytes = subprocess.check_output([str(patched)])
        if original_bytes != patched_bytes:
            raise RuntimeError("Sprintz patch changed encoded output")
        print(f"128 baseline/patched streams identical: "
              f"sha256={hashlib.sha256(patched_bytes).hexdigest()}", flush=True)

        for sanitizer in (False, True):
            common = [
                "c++", "-std=c++17", "-O1" if sanitizer else "-O2", "-g",
                "-mavx2", "-mbmi2", "-mlzcnt", "-Wno-ignored-attributes", "-w",
                "-I", str(VENDOR),
                str(SPRINTZ / "native/bounded_lowdim.cc"),
                *(str(target / name) for name in SOURCES[:2]),
            ]
            if sanitizer:
                common[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            env = os.environ.copy()
            env.update(ASAN_OPTIONS="detect_leaks=0", UBSAN_OPTIONS="halt_on_error=1")
            for name, extra in (
                ("bounded_lowdim_test", []),
                ("allocation_failure", ["-Wl,--wrap=malloc", "-Wl,--wrap=calloc"]),
            ):
                binary = workspace / (name + ("-sanitized" if sanitizer else "-release"))
                run([*common, str(SPRINTZ / "tests" / (name + ".cc")),
                     *extra, "-o", str(binary)])
                run([str(binary)], env=env)


if __name__ == "__main__":
    main()
