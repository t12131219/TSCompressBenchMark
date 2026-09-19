"""Run project native safety qualification for Michael Dipperstein LZSS."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATE = "20260919"


def _encode(library_path: Path, payload: bytes) -> bytes:
    sys.path.insert(0, str(ROOT / "src"))
    from tscompbench.adapters.lzss_dipperstein import LzssDippersteinSession
    from tscompbench.adapters.lzss_raw import _buffer

    session = LzssDippersteinSession(library_path, {"native_timing": False})
    source_storage = ctypes.create_string_buffer(payload or b"\0")
    bound = len(payload) + (len(payload) + 7) // 8
    destination_storage = ctypes.create_string_buffer(max(1, bound))
    source = _buffer(
        ctypes.addressof(source_storage), capacity=len(payload), used=len(payload)
    )
    destination = _buffer(
        ctypes.addressof(destination_storage), capacity=bound, used=0
    )
    try:
        status = session._native.library.tscb_compress(
            session._handle, ctypes.byref(source), ctypes.byref(destination)
        )
        if status != 0:
            raise RuntimeError(f"reference encode failed with status {status}")
        return destination_storage.raw[: destination.used_bytes]
    finally:
        session.close()


def main() -> None:
    adapter = ROOT / "adapters/lzss_dipperstein"
    records: list[dict[str, str]] = []
    log: list[str] = []
    for profile in ("release", "sanitizer"):
        directory = ROOT / f"build/adapters/lzss_dipperstein_c/{profile}"
        executable = directory / "abi-qualification"
        command = [
            os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-O1", "-g",
            *(
                ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-no-pie"]
                if profile == "sanitizer" else []
            ),
            "-I", str(ROOT / "native/include"),
            str(adapter / "native/qualification.c"),
            "-L", str(directory), f"-Wl,-rpath,{directory}",
            "-ltscb_lzss_dipperstein_c", "-o", str(executable),
        ]
        environment = dict(os.environ)
        environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
        environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
        for invocation in (command, [str(executable)]):
            result = subprocess.run(
                invocation, cwd=ROOT, env=environment, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=240,
            )
            log.extend([shlex.join(invocation), result.stdout])
            if result.returncode:
                raise RuntimeError(
                    f"qualification failed: {shlex.join(invocation)}\n{result.stdout}"
                )
        records.append(
            {
                "profile": profile,
                "suite": "abi-qualification-48-roundtrips-hostile-streams",
                "status": "PASS",
            }
        )
    reference = ROOT / "build/source-audits/libtscb_lzss_dipperstein_unpatched.so"
    vendor = adapter / "vendor/lzss"
    reference_command = [
        os.environ.get("CC", "cc"), "-std=c11", "-fPIC", "-O3", "-DNDEBUG", "-shared",
        "-Wl,--no-undefined", "-I", str(ROOT / "native/include"),
        "-I", str(vendor), "-I", str(vendor / "bitfile"),
        str(adapter / "native/tscb_lzss_dipperstein.c"), str(vendor / "lzss.c"),
        str(vendor / "tree.c"), str(vendor / "bitfile/bitfile.c"), "-o", str(reference),
    ]
    result = subprocess.run(
        reference_command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, timeout=240,
    )
    log.extend([shlex.join(reference_command), result.stdout])
    if result.returncode:
        raise RuntimeError(f"reference build failed\n{result.stdout}")
    patched = ROOT / "build/adapters/lzss_dipperstein_c/release/libtscb_lzss_dipperstein_c.so"
    cases = 0
    for pattern in range(3):
        for length in (0, 1, 2, 17, 18, 19, 63, 64, 65, 4095, 4096, 4097,
                       8191, 8192, 8193, 65537):
            payload = bytes(
                0 if pattern == 0 else index % 7 if pattern == 1
                else ((index * 67) ^ (index >> 5)) & 0xFF
                for index in range(length)
            )
            if _encode(reference, payload) != _encode(patched, payload):
                raise RuntimeError(
                    f"patched/unpatched bitstream mismatch: pattern={pattern}, length={length}"
                )
            cases += 1
    records.append(
        {
            "profile": "release",
            "suite": f"patched-vs-unmodified-upstream-bitstream-{cases}-cases",
            "status": "PASS",
        }
    )
    log_path = ROOT / f"build/source-audits/lzss-dipperstein-native-tests-{DATE}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(log), encoding="utf-8")
    document = {
        "schema_version": "tscb.native-qualification.v1",
        "algorithm": "lzss-dipperstein-c",
        "suites": records,
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "sanitizer_coverage": "C codec, bitfile, binary-tree matcher and ABI ASan/UBSan",
    }
    output = ROOT / f"build/source-audits/lzss-dipperstein-native-tests-{DATE}.json"
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(document, indent=2))


if __name__ == "__main__":
    main()
