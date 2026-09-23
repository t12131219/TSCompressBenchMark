from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run(command: list[str], *, environment: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, **(environment or {})},
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): "
            f"{' '.join(command)}\n{completed.stdout}"
        )
    return completed.stdout


def main() -> int:
    evidence: dict[str, object] = {"schema_version": "tscb.native-tests.v1", "profiles": {}}
    for profile in ("release", "sanitizer"):
        build_output = run(
            [
                "conda",
                "run",
                "-n",
                "CompressBench14",
                "python",
                "tools/build_codec.py",
                "zfp-accuracy-1d",
                "--profile",
                profile,
            ]
        )
        library_dir = ROOT / "build/adapters/zfp_accuracy_1d" / profile
        executable = library_dir / "abi-smoke"
        flags = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
        if profile == "sanitizer":
            flags += [
                "-O1",
                "-g",
                "-fno-omit-frame-pointer",
                "-fsanitize=address,undefined",
            ]
        else:
            flags += ["-O2", "-DNDEBUG"]
        compile_output = run(
            [
                os.environ.get("CC", "cc"),
                *flags,
                "-I",
                str(ROOT / "native/include"),
                str(ROOT / "adapters/zfp/tests/abi_smoke.c"),
                "-L",
                str(library_dir),
                "-Wl,-rpath," + str(library_dir),
                "-ltscb_zfp_accuracy_1d",
                "-lm",
                "-o",
                str(executable),
            ]
        )
        test_output = run(
            [str(executable)],
            environment={
                "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1",
                "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
            },
        )
        evidence["profiles"][profile] = {
            "build": json.loads(build_output),
            "compile_output": compile_output,
            "test_output": test_output,
        }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
