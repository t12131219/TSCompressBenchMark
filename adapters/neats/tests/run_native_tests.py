from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ALGORITHMS = ("neats-lossless-i64", "leats-lossless-i64")


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
            f"command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout}"
        )
    return completed.stdout


def main() -> int:
    evidence: dict[str, object] = {"schema_version": "tscb.native-tests.v1", "runs": {}}
    for algorithm in ALGORITHMS:
        directory = algorithm.replace("-", "_")
        evidence["runs"][algorithm] = {}
        for profile in ("release", "sanitizer"):
            build = run([
                "conda", "run", "-n", "CompressBench14", "python",
                "tools/build_codec.py", algorithm, "--profile", profile,
            ])
            library_dir = ROOT / "build/adapters" / directory / profile
            executable = library_dir / "abi-smoke"
            flags = ["-std=gnu++20", "-Wall", "-Wextra", "-Werror"]
            if profile == "sanitizer":
                flags += ["-O1", "-g", "-fno-omit-frame-pointer", "-fsanitize=address,undefined"]
            else:
                flags += ["-O2", "-DNDEBUG"]
            compile_output = run([
                os.environ.get("CXX", "c++"), *flags,
                f"-DTSCB_TEST_NEATS={int(algorithm.startswith('neats'))}",
                "-I", str(ROOT / "native/include"),
                str(ROOT / "adapters/neats/tests/abi_smoke.cc"),
                "-L", str(library_dir), "-Wl,-rpath," + str(library_dir),
                "-l" + "tscb_" + directory, "-o", str(executable),
            ])
            test_output = run(
                [str(executable)],
                environment={
                    # LeakSanitizer cannot run under the managed ptrace environment.
                    "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                    "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
                },
            )
            evidence["runs"][algorithm][profile] = {
                "build": json.loads(build),
                "compile_output": compile_output,
                "test_output": test_output,
            }
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
