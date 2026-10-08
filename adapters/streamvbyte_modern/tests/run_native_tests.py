"""Out-of-tree upstream tests and bounded ABI qualification for modern 1234."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import subprocess
from pathlib import Path

import numpy as np

from tscompbench.adapters.streamvbyte import _buffer

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "adapters/streamvbyte_modern"
SHARED = ROOT / "adapters/streamvbyte"
KEYS = ("streamvbyte-modern-u32", "delta-zigzag-streamvbyte-modern64")
PROFILES = ("release", "debug", "sanitizer")
UNITS = (
    "streamvbyte_encode.c",
    "streamvbyte_decode.c",
    "streamvbytedelta_encode.c",
    "streamvbytedelta_decode.c",
    "streamvbyte_0124_encode.c",
    "streamvbyte_0124_decode.c",
    "streamvbyte_zigzag.c",
)
REPORT = ROOT / "build/source-audits/streamvbyte-modern-native-tests.json"
OUT = ROOT / "build/source-audits/streamvbyte-modern-native"
ENV = dict(
    os.environ,
    ASAN_OPTIONS="detect_leaks=0:halt_on_error=1",
    UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
)
evidence: dict = {
    "status": "RUNNING",
    "commands": [],
    "upstream_tests": [],
    "native_executables": [],
    "stage_executables": [],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save() -> None:
    REPORT.write_text(json.dumps(evidence, indent=2) + "\n")


def run(command: list[str], *, required: bool = True) -> dict:
    result = subprocess.run(command, capture_output=True, text=True, env=ENV, timeout=180)
    item = {
        "command": command,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
    evidence["commands"].append(item)
    save()
    if required and result.returncode:
        raise RuntimeError(json.dumps(item, indent=2))
    return item


def flags(profile: str) -> list[str]:
    return ["-std=c11", "-msse4.1", "-fno-strict-aliasing", "-Wall", "-Wextra"] + {
        "release": ["-O3"],
        "debug": ["-O0", "-g"],
        "sanitizer": ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"],
    }[profile]


def upstream_tests() -> None:
    for source_kind in ("original", "patched"):
        source = (
            ADAPTER / "vendor/streamvbyte"
            if source_kind == "original"
            else (ROOT / "build/adapters/streamvbyte_modern_u32/release/streamvbyte")
        )
        for profile in PROFILES:
            executable = OUT / f"upstream-{source_kind}-{profile}"
            run(
                [
                    "cc",
                    *flags(profile),
                    "-I",
                    str(source / "include"),
                    "-I",
                    str(source / "src"),
                    str(source / "tests/unit.c"),
                    *(str(source / "src" / name) for name in UNITS),
                    "-o",
                    str(executable),
                ]
            )
            item = run(
                [str(executable)], required=source_kind == "patched" or profile != "sanitizer"
            )
            evidence["upstream_tests"].append(
                {
                    "source_kind": source_kind,
                    "profile": profile,
                    "executable_sha256": sha(executable),
                    **item,
                }
            )
            save()
            print(f"upstream {source_kind}/{profile}: exit {item['returncode']}", flush=True)


def abi_tests() -> None:
    for key in KEYS:
        name = key.replace("-", "_")
        for profile in PROFILES:
            directory = ROOT / f"build/adapters/{name}/{profile}"
            executable = OUT / f"{name}-{profile}"
            run(
                [
                    "cc",
                    *flags(profile),
                    f"-DDELTA64={int(key == KEYS[1])}",
                    "-I",
                    str(ROOT / "native/include"),
                    str(SHARED / "tests/abi_smoke.c"),
                    "-L",
                    str(directory),
                    f"-ltscb_{name}",
                    f"-Wl,-rpath,{directory}",
                    "-o",
                    str(executable),
                ]
            )
            item = run([str(executable)])
            evidence["native_executables"].append({"algorithm": key, "profile": profile, **item})
            print(item["stdout"].strip(), flush=True)
    name = KEYS[1].replace("-", "_")
    for profile in PROFILES:
        directory = ROOT / f"build/adapters/{name}/{profile}"
        executable = OUT / f"stages-{profile}"
        run(
            [
                "cc",
                *flags(profile),
                "-I",
                str(ROOT / "native/include"),
                "-I",
                str(SHARED / "native"),
                str(SHARED / "tests/stages_smoke.c"),
                "-L",
                str(directory),
                f"-ltscb_{name}",
                f"-Wl,-rpath,{directory}",
                "-o",
                str(executable),
            ]
        )
        item = run([str(executable)])
        evidence["stage_executables"].append({"profile": profile, **item})
        print(item["stdout"].strip(), flush=True)


def equivalence() -> None:
    source = ADAPTER / "vendor/streamvbyte"
    original = OUT / "original.so"
    run(
        [
            "cc",
            *flags("release"),
            "-fPIC",
            "-shared",
            "-Wl,-Bsymbolic-functions",
            "-I",
            str(source / "include"),
            str(source / "src/streamvbyte_encode.c"),
            str(source / "src/streamvbyte_decode.c"),
            "-o",
            str(original),
        ]
    )
    baseline = ctypes.CDLL(str(original))
    library_path = (
        ROOT / "build/adapters/streamvbyte_modern_u32/release" / "libtscb_streamvbyte_modern_u32.so"
    )
    patched = ctypes.CDLL(str(library_path))
    for lib in (baseline, patched):
        lib.streamvbyte_encode.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        lib.streamvbyte_decode.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32]
        lib.streamvbyte_encode.restype = lib.streamvbyte_decode.restype = ctypes.c_size_t
    # Use the actual bounded ABI too, not just the exported patched upstream API.
    from tscompbench.adapters.streamvbyte_modern import ModernStreamVByteSession

    session = ModernStreamVByteSession(library_path, KEYS[0], {})
    rng = np.random.default_rng(20261007)
    lengths = (
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
    vectors = [rng.integers(0, 2**32, n, dtype="<u4") for n in lengths]
    vectors += [np.full(n, value, dtype="<u4") for n in lengths for value in (0, 2**32 - 1)]
    for control in range(256):
        quad = np.array([1 << (8 * ((control >> (2 * i)) & 3)) for i in range(4)], dtype="<u4")
        vectors.extend(np.tile(quad, repeat) for repeat in (1, 2, 8))
    try:
        for values in vectors:
            streams = []
            for lib in (baseline, patched):
                output = ctypes.create_string_buffer(4 * len(values) + (len(values) + 3) // 4 + 16)
                used = lib.streamvbyte_encode(values.ctypes.data, len(values), output)
                streams.append((output, used))
            assert streams[0][0].raw[: streams[0][1]] == streams[1][0].raw[: streams[1][1]]
            for lib, (output, used) in zip((patched, baseline), streams, strict=True):
                decoded = np.empty_like(values)
                assert lib.streamvbyte_decode(output, decoded.ctypes.data, len(values)) == used
                assert decoded.tobytes() == values.tobytes()
            src = _buffer(values.ctypes.data, values.nbytes, values.nbytes, 6)
            bound = ctypes.c_uint64()
            lib = session._native.library
            assert lib.tscb_reset(session._handle, 0) == 0
            assert (
                lib.tscb_compress_bound(session._handle, ctypes.byref(src), ctypes.byref(bound))
                == 0
            )
            output = ctypes.create_string_buffer(bound.value)
            dst = _buffer(ctypes.addressof(output), bound.value, 0, 11)
            assert lib.tscb_compress(session._handle, ctypes.byref(src), ctypes.byref(dst)) == 0
            assert int.from_bytes(output.raw[:4], "little") == len(values)
            assert output.raw[4 : dst.used_bytes] == streams[0][0].raw[: streams[0][1]]
    finally:
        session.close()
    evidence["original_api_equivalence_vectors"] = len(vectors)
    evidence["shim_count_stripped_equivalence"] = "PASS"
    evidence["original_api_sha256"] = sha(original)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    save()
    upstream_tests()
    abi_tests()
    equivalence()
    evidence.update(
        status="PASS",
        source_lock_sha256=sha(ADAPTER / "SOURCE_LOCK.json"),
        driver_sha256=sha(Path(__file__)),
        native_test_sha256=sha(SHARED / "tests/abi_smoke.c"),
        native_stage_test_sha256=sha(SHARED / "tests/stages_smoke.c"),
        builds=[
            json.loads(
                (
                    ROOT / f"build/adapters/{key.replace('-', '_')}/{profile}/build-record.json"
                ).read_text()
            )
            for key in KEYS
            for profile in PROFILES
        ],
        leak_detection="DISABLED",
        platform="LINUX_X86_64_SSE4_1",
    )
    save()
    print(
        f"Modern native qualification PASS; {evidence['original_api_equivalence_vectors']} vectors"
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        evidence.update(status="FAIL", error=str(error))
        save()
        raise
