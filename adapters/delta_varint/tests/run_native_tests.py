from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/delta_varint"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tscb-delta-varint-native-") as temporary:
        for profile in ("release", "sanitizer"):
            library = ROOT / f"build/adapters/delta_varint/{profile}"
            if not (library / "libtscb_delta_varint.so").is_file():
                raise FileNotFoundError(f"build {profile} before native tests")
            executable = Path(temporary) / f"{profile}-abi-smoke"
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
            if profile == "sanitizer":
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            subprocess.run([
                os.environ.get("CC", "cc"), *flags,
                "-I", str(ROOT / "native/include"),
                str(ADAPTER / "tests/abi_smoke.c"),
                "-L", str(library), "-ltscb_delta_varint",
                f"-Wl,-rpath,{library}", "-o", str(executable),
            ], check=True)
            environment = dict(os.environ)
            if profile == "sanitizer":
                environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
                environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
            subprocess.run([str(executable)], env=environment, check=True)


if __name__ == "__main__":
    main()
