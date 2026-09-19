from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tscb-entropy-qual-") as temporary:
        for algorithm in ("huff0", "fse"):
            for profile in ("release", "sanitizer"):
                directory = ROOT / f"build/adapters/{algorithm}/{profile}"
                if not (directory / f"libtscb_{algorithm}.so").is_file():
                    raise FileNotFoundError(f"build {algorithm} {profile} first")
                executable = Path(temporary) / f"{algorithm}-{profile}"
                flags = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
                if profile == "sanitizer":
                    flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
                subprocess.run([
                    os.environ.get("CC", "cc"), *flags, "-I", str(ROOT / "native/include"),
                    str(ROOT / "adapters/entropy_fse/native/qualification.c"),
                    "-L", str(directory), f"-ltscb_{algorithm}",
                    f"-Wl,-rpath,{directory}", "-o", str(executable),
                ], check=True)
                environment = dict(os.environ)
                if profile == "sanitizer":
                    environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
                    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
                print(f"{algorithm} {profile}", flush=True)
                subprocess.run([str(executable)], env=environment, check=True)


if __name__ == "__main__":
    main()
