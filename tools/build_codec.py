from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {shlex.join(command)}\n{completed.stdout}"
        )
    return completed.stdout


def _lz4_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "lz4_frame"
    vendor = adapter / "vendor" / "lz4" / "lib"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_lz4_frame.c"),
        str(vendor / "lz4.c"),
        str(vendor / "lz4frame.c"),
        str(vendor / "lz4hc.c"),
        str(vendor / "xxhash.c"),
        "-o",
        str(output),
    ]


def _zstd_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "zstd_frame"
    vendor = adapter / "vendor" / "zstd" / "lib"
    flags = [
        "-std=c11",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-DXXH_NAMESPACE=ZSTD_",
        "-DDYNAMIC_BMI2=0",
        "-DZSTD_LEGACY_SUPPORT=0",
        "-DZSTD_DISABLE_ASM",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_files = [
        *(vendor / "common").glob("*.c"),
        *(vendor / "compress").glob("*.c"),
        *(vendor / "decompress").glob("*.c"),
    ]
    source_files = sorted(source_files)
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_zstd_frame.c"),
        *(str(path) for path in source_files),
        "-o",
        str(output),
    ]


def _snappy_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "snappy_raw"
    vendor = adapter / "vendor" / "snappy"
    flags = [
        "-std=c++17",
        "-fPIC",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-DHAVE_CONFIG_H=0",
        "-DSNAPPY_HAVE_SSSE3=0",
        "-DSNAPPY_HAVE_NEON=0",
        "-DSNAPPY_HAVE_BMI2=0",
        "-DSNAPPY_HAVE_X86_CRC32=0",
        "-DSNAPPY_HAVE_NEON_CRC32=0",
    ]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    return [
        os.environ.get("CXX", "c++"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_snappy_raw.cc"),
        str(vendor / "snappy-sinksource.cc"),
        str(vendor / "snappy-stubs-internal.cc"),
        str(vendor / "snappy.cc"),
        "-o",
        str(output),
    ]


def _brotli_command(output: Path, profile: str) -> list[str]:
    adapter = PROJECT_ROOT / "adapters" / "brotli_stream"
    vendor = adapter / "vendor" / "brotli"
    flags = ["-std=c11", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    if profile == "release":
        flags += ["-O3", "-DNDEBUG"]
    elif profile == "sanitizer":
        flags += [
            "-O1",
            "-g",
            "-fno-omit-frame-pointer",
            "-fsanitize=address,undefined",
        ]
    else:
        raise ValueError(f"unknown build profile: {profile}")
    source_files = sorted(
        [
            *(vendor / "common").glob("*.c"),
            *(vendor / "dec").glob("*.c"),
            *(vendor / "enc").glob("*.c"),
        ]
    )
    return [
        os.environ.get("CC", "cc"),
        *flags,
        "-shared",
        "-I",
        str(PROJECT_ROOT / "native" / "include"),
        "-I",
        str(vendor / "include"),
        "-I",
        str(vendor),
        str(adapter / "native" / "tscb_brotli_stream.c"),
        *(str(path) for path in source_files),
        "-lm",
        "-o",
        str(output),
    ]


def _build(algorithm: str, profile: str) -> dict[str, Any]:
    directory_name = algorithm.replace("-", "_")
    output_dir = PROJECT_ROOT / "build" / "adapters" / directory_name / profile
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"libtscb_{directory_name}.so"
    if algorithm == "lz4-frame":
        command = _lz4_command(output, profile)
    elif algorithm == "zstd-frame":
        command = _zstd_command(output, profile)
    elif algorithm == "snappy-raw":
        command = _snappy_command(output, profile)
    elif algorithm == "brotli-stream":
        command = _brotli_command(output, profile)
    else:
        raise ValueError(f"unknown algorithm: {algorithm}")
    log = _run(command)
    command_document = {
        "schema_version": "tscb.compile-command.v1",
        "profile": profile,
        "command": command,
    }
    command_bytes = json.dumps(
        command_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    record = {
        "schema_version": "tscb.build-artifact.v1",
        "algorithm": algorithm,
        "profile": profile,
        "artifact": str(output.relative_to(PROJECT_ROOT)),
        "artifact_sha256": _sha256(output),
        "compile_commands_sha256": hashlib.sha256(command_bytes).hexdigest(),
        "compiler": _run([command[0], "--version"]).splitlines()[0],
        "command_display": shlex.join(command),
        "build_log": log,
    }
    record_path = output_dir / "build-record.json"
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a frozen source codec adapter")
    parser.add_argument(
        "algorithm", choices=("lz4-frame", "zstd-frame", "snappy-raw", "brotli-stream")
    )
    parser.add_argument("--profile", choices=("release", "sanitizer", "all"), default="release")
    arguments = parser.parse_args()
    profiles = ("release", "sanitizer") if arguments.profile == "all" else (arguments.profile,)
    records = [_build(arguments.algorithm, item) for item in profiles]
    print(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
