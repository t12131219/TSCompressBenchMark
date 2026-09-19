"""Run retained upstream LZSS tests and project native safety qualification."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    adapter = ROOT / "adapters/lzss_raw"
    vendor = adapter / "vendor/lzss/lzss"
    records = []
    log = []
    for profile in ("release", "sanitizer"):
        directory = ROOT / f"build/adapters/lzss_raw/{profile}"
        dependency = directory / "rust-build"
        environment = dict(os.environ)
        environment["OUT_DIR"] = str(dependency)
        environment["ASAN_OPTIONS"] = "detect_leaks=0:halt_on_error=1"
        environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        flags = ["-C", "opt-level=3"]
        if profile == "sanitizer":
            environment["RUSTC_BOOTSTRAP"] = "1"
            flags = ["-C", "opt-level=1", "-g", "-Z", "sanitizer=address"]
        features = ["--cfg", 'feature="std"', "--cfg", 'feature="alloc"', "--cfg", 'feature="safe"']

        def run(command: list[str], env: dict[str, str] = environment) -> None:
            result = subprocess.run(
                command,
                cwd=vendor,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=240,
            )
            log.extend([shlex.join(command), result.stdout])
            log_path = ROOT / "build/source-audits/lzss-native-tests-20260918.log"
            log_path.write_text("\n".join(log), encoding="utf-8")
            if result.returncode:
                raise RuntimeError(f"qualification failed: {shlex.join(command)}\n{result.stdout}")
            print(result.stdout, flush=True)

        for name, path in [
            ("library", vendor / "src/lib.rs"),
            ("generic_in_place", vendor / "tests/generic_in_place.rs"),
            ("generic", vendor / "tests/generic.rs"),
            ("dynamic", vendor / "tests/dynamic.rs"),
        ]:
            if profile == "sanitizer" and name in {"generic", "dynamic"}:
                continue  # Upstream ignored release-only tests explicitly reject debug assertions.
            executable = directory / f"upstream-{name}"
            command = [
                "rustc",
                str(path),
                "--edition=2021",
                "--test",
                *features,
                *flags,
                "--extern",
                f"void={dependency / 'libvoid.rlib'}",
                "--extern",
                f"lzss={dependency / 'liblzss.rlib'}",
                "-L",
                str(dependency),
                "-o",
                str(executable),
            ]
            run(command)
            run(
                [
                    str(executable),
                    *(["--include-ignored"] if profile == "release" else []),
                    "--test-threads=1",
                ]
            )
            records.append({"profile": profile, "suite": f"upstream-{name}", "status": "PASS"})
        if profile == "release":
            run(
                [
                    "rustdoc",
                    "--edition=2021",
                    "--test",
                    str(vendor / "src/lib.rs"),
                    "--crate-name",
                    "lzss",
                    *features,
                    "--extern",
                    f"void={dependency / 'libvoid.rlib'}",
                    "--extern",
                    f"lzss={dependency / 'liblzss.rlib'}",
                    "-L",
                    str(dependency),
                ]
            )
            records.append({"profile": profile, "suite": "upstream-doctests", "status": "PASS"})
        executable = directory / "abi-qualification"
        run(
            [
                "c++",
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-O1",
                "-g",
                *(
                    ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
                    if profile == "sanitizer"
                    else []
                ),
                "-I",
                str(ROOT / "native/include"),
                str(adapter / "native/qualification.cc"),
                "-L",
                str(directory),
                f"-Wl,-rpath,{directory}",
                "-ltscb_lzss_raw",
                "-o",
                str(executable),
            ]
        )
        run([str(executable)])
        records.append(
            {"profile": profile, "suite": "abi-qualification-39-cases", "status": "PASS"}
        )
    log_path = ROOT / "build/source-audits/lzss-native-tests-20260918.log"
    document = {
        "suites": records,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "sanitizer_coverage": (
            "Rust codec/FFI ASan; C++ ABI ASan/UBSan; std uninstrumented; LSan disabled"
        ),
    }
    (ROOT / "build/source-audits/lzss-native-tests-20260918.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
