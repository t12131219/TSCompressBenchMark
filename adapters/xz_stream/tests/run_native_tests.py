from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ADAPTER = PROJECT_ROOT / "adapters/xz_stream"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="tscb-xz-native-") as temporary:
        for profile in ("release", "sanitizer"):
            build = PROJECT_ROOT / f"build/adapters/xz_stream/{profile}"
            if (not (build / "libtscb_xz_stream.so").is_file()
                    or not (build / "vendor-build/CTestTestfile.cmake").is_file()):
                raise FileNotFoundError(f"build {profile} before running native tests")
            environment = dict(os.environ)
            if profile == "sanitizer":
                environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
                environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
            transcript = []

            def run_logged(command, *, env, transcript=transcript, build=build):
                completed = subprocess.run(
                    command, env=env, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                print(completed.stdout, end="", flush=True)
                transcript.append(shlex.join(command) + "\n" + completed.stdout)
                (build / "native-tests.log").write_text("\n".join(transcript), encoding="utf-8")
                completed.check_returncode()

            run_logged([
                "ctest", "--test-dir", str(build / "vendor-build"),
                "--output-on-failure", "-R", "^test_[a-z_]+$",
            ], env=environment)
            for name, include in (
                ("abi_smoke", PROJECT_ROOT / "native/include"),
                ("vendor_roundtrip", ADAPTER / "vendor/xz/src/liblzma/api"),
            ):
                executable = Path(temporary) / f"{profile}-{name}"
                flags = ["-std=c11", "-Wall", "-Wextra", "-Werror"]
                if profile == "sanitizer":
                    flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
                linkage = ([str(build / "vendor-build/liblzma.a")]
                           if name == "vendor_roundtrip" else
                           ["-L", str(build), "-ltscb_xz_stream", f"-Wl,-rpath,{build}"])
                subprocess.run([
                    os.environ.get("CC", "cc"), *flags, "-I", str(include),
                    str(ADAPTER / f"tests/{name}.c"), *linkage, "-o", str(executable),
                ], check=True)
                print(f"{profile}: {name}", flush=True)
                run_logged([str(executable)], env=environment)
                if profile == "release" and name == "abi_smoke":
                    competitor = Path(temporary) / "competitor.so"
                    subprocess.run([
                        os.environ.get("CC", "cc"), "-shared", "-fPIC", "-I",
                        str(ADAPTER / "vendor/xz/src/liblzma/api"),
                        str(ADAPTER / "tests/symbol_interposition.c"), "-o", str(competitor),
                    ], check=True)
                    interference = {**environment, "LD_PRELOAD": str(competitor)}
                    print("release: competing global codec symbols", flush=True)
                    run_logged([str(executable)], env=interference)


if __name__ == "__main__":
    main()
