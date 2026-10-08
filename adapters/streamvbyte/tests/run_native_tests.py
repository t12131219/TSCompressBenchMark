from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/streamvbyte"


def main() -> None:
    out = ROOT / "build/source-audits/streamvbyte-native"
    out.mkdir(parents=True, exist_ok=True)
    report = ROOT / "build/source-audits/streamvbyte-native-tests.json"
    report.write_text(json.dumps({"status": "RUNNING"}) + "\n")
    logs = []
    for key in ("streamvbyte-u32", "delta-zigzag-streamvbyte64"):
        name = key.replace("-", "_")
        for profile in ("release", "debug", "sanitizer"):
            library = ROOT / f"build/adapters/{name}/{profile}"
            executable = out / f"{name}-{profile}"
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1"]
            if profile == "sanitizer":
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            subprocess.run(
                [
                    "cc",
                    *flags,
                    f"-DDELTA64={int(key.startswith('delta'))}",
                    "-I",
                    str(ROOT / "native/include"),
                    str(ADAPTER / "tests/abi_smoke.c"),
                    "-L",
                    str(library),
                    "-ltscb_" + name,
                    f"-Wl,-rpath,{library}",
                    "-o",
                    str(executable),
                ],
                check=True,
            )
            env = dict(
                os.environ,
                ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
                UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
            )
            completed = subprocess.run([str(executable)], env=env, capture_output=True, text=True)
            logs.append(
                {
                    "algorithm": key,
                    "profile": profile,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                    "returncode": completed.returncode,
                }
            )
            if completed.returncode:
                raise RuntimeError(json.dumps(logs[-1], indent=2))
    timing_executable = out / "native-timing-faults"
    stage_logs = []
    for profile in ("release", "debug", "sanitizer"):
        library = ROOT / f"build/adapters/delta_zigzag_streamvbyte64/{profile}"
        executable = out / f"stages-{profile}"
        flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1"]
        if profile == "sanitizer":
            flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        subprocess.run(
            [
                "cc",
                *flags,
                "-I",
                str(ROOT / "native/include"),
                "-I",
                str(ADAPTER / "native"),
                str(ADAPTER / "tests/stages_smoke.c"),
                "-L",
                str(library),
                "-ltscb_delta_zigzag_streamvbyte64",
                f"-Wl,-rpath,{library}",
                "-o",
                str(executable),
            ],
            check=True,
        )
        completed = subprocess.run([str(executable)], env=env, capture_output=True, text=True)
        stage_logs.append(
            {
                "profile": profile,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "returncode": completed.returncode,
            }
        )
        if completed.returncode:
            raise RuntimeError(json.dumps(stage_logs[-1], indent=2))
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(ROOT / "native/include"),
            str(ROOT / "tests/native/native_timing_smoke.c"),
            "-o",
            str(timing_executable),
        ],
        check=True,
    )
    subprocess.run([str(timing_executable)], check=True)
    # Run the untouched benchmark C APIs as a separate release-only oracle.
    original = out / "original.so"
    subprocess.run(
        [
            "cc",
            "-O3",
            "-msse4.1",
            "-shared",
            "-fPIC",
            "-Wl,-Bsymbolic-functions",
            str(ADAPTER / "vendor/fastpfor/streamvbyte.c"),
            "-o",
            str(original),
        ],
        check=True,
    )
    baseline = ctypes.CDLL(str(original))
    patched = ctypes.CDLL(
        str(ROOT / "build/adapters/streamvbyte_u32/release/libtscb_streamvbyte_u32.so")
    )
    for lib in (baseline, patched):
        lib.svb_encode.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.svb_encode.restype = ctypes.c_uint64
        lib.svb_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        lib.svb_decode.restype = ctypes.c_uint64
    rng = np.random.default_rng(20261007)
    vectors = [
        rng.integers(0, 2**32, n, dtype=np.uint32)
        for n in (
            0,
            1,
            2,
            3,
            4,
            7,
            8,
            9,
            31,
            32,
            33,
            63,
            64,
            65,
            127,
            128,
            129,
            255,
            256,
            257,
            1000,
            8193,
        )
    ]
    for control in range(256):
        vectors.append(
            np.array([1 << (8 * ((control >> (2 * i)) & 3)) for i in range(4)], dtype=np.uint32)
        )
    for values in vectors:
        streams = []
        for lib in (baseline, patched):
            buf = ctypes.create_string_buffer(4 + 5 * len(values) + 16)
            size = lib.svb_encode(buf, values.ctypes.data, len(values), 0, 1)
            streams.append((buf, size))
        assert streams[0][0].raw[: streams[0][1]] == streams[1][0].raw[: streams[1][1]]
        for lib, (buf, size) in zip((patched, baseline), streams, strict=True):
            decoded = np.empty_like(values)
            consumed = lib.svb_decode(decoded.ctypes.data, buf, 0, 5)
            assert consumed == size or len(values) == 0
            assert np.array_equal(values, decoded)
    document = {
        "status": "PASS",
        "native_executables": logs,
        "stage_executables": stage_logs,
        "native_stage_test_sha256": hashlib.sha256(
            (ADAPTER / "tests/stages_smoke.c").read_bytes()
        ).hexdigest(),
        "native_timer_clock_failure_backwards_overflow": "PASS",
        "original_api_equivalence_vectors": len(vectors),
        "source_sha256": hashlib.sha256(
            (ADAPTER / "vendor/fastpfor/streamvbyte.c").read_bytes()
        ).hexdigest(),
        "native_test_sha256": hashlib.sha256(
            (ADAPTER / "tests/abi_smoke.c").read_bytes()
        ).hexdigest(),
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "builds": [
            json.loads(path.read_text())
            for key in ("streamvbyte-u32", "delta-zigzag-streamvbyte64")
            for path in sorted(
                (ROOT / f"build/adapters/{key.replace('-', '_')}").glob("*/build-record.json")
            )
        ],
        "leak_detection": "DISABLED",
        "platform": "LINUX_X86_64_SSE4_1",
    }
    report.write_text(json.dumps(document, indent=2) + "\n")
    print(json.dumps(document, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        report = ROOT / "build/source-audits/streamvbyte-native-tests.json"
        report.write_text(json.dumps({"status": "FAIL", "error": str(error)}, indent=2) + "\n")
        raise
