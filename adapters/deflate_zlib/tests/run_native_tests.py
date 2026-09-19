from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ADAPTER = PROJECT_ROOT / "adapters/deflate_zlib"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tscb-deflate-native-") as temporary:
        for profile in ("release", "sanitizer"):
            library_directory = PROJECT_ROOT / f"build/adapters/deflate_zlib/{profile}"
            if not (library_directory / "libtscb_deflate_zlib.so").is_file():
                raise FileNotFoundError(f"build {profile} before running native tests")
            for name, include in (
                ("abi_smoke", PROJECT_ROOT / "native/include"),
                ("vendor_roundtrip", ADAPTER / "vendor/zlib"),
            ):
                executable = Path(temporary) / f"{profile}-{name}"
                flags = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
                if profile == "sanitizer":
                    flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
                subprocess.run([
                    os.environ.get("CC", "cc"), *flags, "-I", str(include),
                    str(ADAPTER / f"tests/{name}.c"), "-L", str(library_directory),
                    "-ltscb_deflate_zlib", f"-Wl,-rpath,{library_directory}",
                    "-o", str(executable),
                ], check=True)
                environment = dict(os.environ)
                if profile == "sanitizer":
                    environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
                    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
                print(f"{profile}: {name}", flush=True)
                subprocess.run([str(executable)], env=environment, check=True)
                if profile == "release" and name == "abi_smoke":
                    competitor = Path(temporary) / "competing-zlib.so"
                    subprocess.run([
                        os.environ.get("CC", "cc"), "-shared", "-fPIC",
                        "-Wall", "-Wextra", "-Werror", "-I", str(ADAPTER / "vendor/zlib"),
                        str(ADAPTER / "tests/symbol_interposition.c"),
                        "-o", str(competitor),
                    ], check=True)
                    interference_environment = dict(environment)
                    interference_environment["LD_PRELOAD"] = str(competitor)
                    print("release: competing global zlib symbol rejection", flush=True)
                    subprocess.run(
                        [str(executable)], env=interference_environment, check=True
                    )


if __name__ == "__main__":
    main()
