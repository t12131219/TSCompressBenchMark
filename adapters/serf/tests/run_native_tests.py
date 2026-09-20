from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ADAPTER = PROJECT_ROOT / "adapters/serf"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tscb-serf-native-") as temporary:
        for algorithm, macro in (("serf_qt", "0"), ("serf_xor", "1")):
            for profile in ("release", "sanitizer"):
                build = PROJECT_ROOT / f"build/adapters/{algorithm}/{profile}"
                library = build / f"libtscb_{algorithm}.so"
                if not library.is_file():
                    raise FileNotFoundError(
                        f"build {algorithm.replace('_', '-')} {profile} before native tests"
                    )
                executable = Path(temporary) / f"{algorithm}-{profile}-abi-smoke"
                flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror"]
                if profile == "sanitizer":
                    flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
                subprocess.run(
                    [
                        os.environ.get("CXX", "c++"),
                        *flags,
                        f"-DSMOKE_XOR={macro}",
                        "-I",
                        str(PROJECT_ROOT / "native/include"),
                        str(ADAPTER / "tests/abi_smoke.cc"),
                        "-L",
                        str(build),
                        f"-ltscb_{algorithm}",
                        f"-Wl,-rpath,{build}",
                        "-o",
                        str(executable),
                    ],
                    check=True,
                )
                environment = dict(os.environ)
                if profile == "sanitizer":
                    environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
                    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
                print(f"{algorithm}: {profile}: abi_smoke", flush=True)
                subprocess.run([str(executable)], env=environment, check=True)


if __name__ == "__main__":
    main()
