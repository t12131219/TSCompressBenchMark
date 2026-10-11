"""Fresh original Rust / current C++ differential in a temporary oracle project."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from verify_lzss_cpp import input_bytes, native_call

ROOT = Path(__file__).resolve().parents[1]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--void-source", type=Path, required=True)
    parser.add_argument("--void-archive", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_root.resolve()
    if output.exists():
        raise SystemExit("Use a new output directory")
    output.mkdir(parents=True)
    source = args.source_root.resolve() / "lzss"
    fixture = ROOT / "adapters/lzss_raw/tests/fixtures/reference_vectors.json"
    vectors = json.loads(fixture.read_text())
    for file in vectors["reference"]["source_files"]:
        if sha(source / file["path"]) != file["sha256"]:
            raise SystemExit("Frozen Rust source drift: " + file["path"])
    expected_void = "6a02e4885ed3bc0f2de90ea6dd45ebcbb66dacffe03547fadbb0eeae2770887d"
    if sha(args.void_archive) != expected_void:
        raise SystemExit("Cargo.lock void archive SHA mismatch")
    original_files = {
        str(p.relative_to(source)): sha(p) for p in sorted(source.rglob("*")) if p.is_file()
    }
    shutil.copytree(source, output / "original/lzss")
    shutil.copytree(args.void_source, output / "original/void")
    manifest = output / "Cargo.toml"
    manifest.write_text(
        '[package]\nname="tscb_original_lzss_oracle"\nversion="0.1.0"\nedition="2021"\n'
        '[workspace]\n[dependencies]\nlzss={path="original/lzss"}\n'
        '[patch.crates-io]\nvoid={path="original/void"}\n'
    )
    (output / "src").mkdir()
    main_rs = output / "src/main.rs"
    main_rs.write_text("""use lzss::{LzssDyn, SliceReader, VecWriter, ResultLzssErrorVoidExt};
use std::{env, fs};
fn main() {
    let args: Vec<String> = env::args().collect();
    let bytes = fs::read(&args[2]).unwrap();
    let codec = LzssDyn::new(10, 4, 32).unwrap();
    let result = if args[1] == "encode" {
        codec.compress(SliceReader::new(&bytes),
            VecWriter::with_capacity(bytes.len() + bytes.len()/8 + 16)).void_unwrap()
    } else {
        codec.decompress(SliceReader::new(&bytes),
            VecWriter::with_capacity(args[3].parse().unwrap())).void_unwrap()
    };
    if args[1] == "decode" { assert_eq!(result.len(), args[3].parse::<usize>().unwrap()); }
    fs::write(args.last().unwrap(), result).unwrap();
}
""")
    report = {
        "schema_version": 1,
        "evidence_kind": "FRESH_ORIGINAL_RUST_SOURCE_EXECUTION",
        "scope": "REGISTERED_EI10_EJ4_C32_BYTE_STREAM_PARITY",
        "full_parity_granted": False,
        "benchmark_qualification_granted": False,
        "formal_granted": False,
        "driver_sha256": sha(Path(__file__)),
        "input_driver_sha256": sha(ROOT / "tools/verify_lzss_cpp.py"),
        "fixture_sha256": sha(fixture),
        "source_files": original_files,
        "void_archive_sha256": sha(args.void_archive),
        "void_source_files": {
            str(p.relative_to(args.void_source)): sha(p)
            for p in sorted(args.void_source.rglob("*"))
            if p.is_file()
        },
        "oracle_wrapper_sha256": sha(main_rs),
        "oracle_cargo_manifest_sha256": sha(manifest),
        "library": {"path": str(args.library.resolve()), "sha256": sha(args.library)},
        "commands": [],
        "cases": [],
    }
    env = dict(os.environ, CARGO_TARGET_DIR=str(output / "target"))

    def run(label: str, command: list[str], log: Path, timeout: int = 120) -> bytes:
        start = time.monotonic()
        result = subprocess.run(command, cwd=output, env=env, capture_output=True, timeout=timeout)
        log.write_bytes(result.stdout + result.stderr)
        report["commands"].append(
            {
                "label": label,
                "command": command,
                "exit_code": result.returncode,
                "seconds": time.monotonic() - start,
                "log": str(log),
                "log_sha256": sha(log),
            }
        )
        if result.returncode:
            raise RuntimeError(f"{label} failed; see {log}")
        return result.stdout

    try:
        run("rustc-version", ["rustc", "--version", "--verbose"], output / "rustc-version.log")
        run(
            "cargo-offline-build",
            ["cargo", "build", "--release", "--offline", "--manifest-path", str(manifest)],
            output / "cargo-build.log",
        )
        runner = output / "target/release/tscb_original_lzss_oracle"
        report["oracle_binary_sha256"] = sha(runner)
        report["oracle_cargo_lock_sha256"] = sha(output / "Cargo.lock")
        for case in vectors["cases"]:
            directory = output / "cases" / case["name"]
            directory.mkdir(parents=True)
            incoming = directory / "input.bin"
            encoded = directory / "source.bin"
            decoded = directory / "source-cross-decode.bin"
            incoming.write_bytes(input_bytes(case))
            run(
                case["name"] + "-source-encode",
                [str(runner), "encode", str(incoming), str(encoded)],
                directory / "encode.log",
            )
            actual_source = encoded.read_bytes()
            assert sha(incoming) == case["input_sha256"]
            assert sha(encoded) == case["stream_sha256"], (
                "fresh source differs from frozen original stream"
            )
            native = native_call(args.library.resolve(), incoming.read_bytes(), None)
            assert native == actual_source, "current native stream differs from fresh original"
            encoded.write_bytes(native)
            run(
                case["name"] + "-source-decode-native",
                [str(runner), "decode", str(encoded), str(incoming.stat().st_size), str(decoded)],
                directory / "decode.log",
            )
            assert decoded.read_bytes() == incoming.read_bytes()
            assert (
                native_call(args.library.resolve(), actual_source, incoming.stat().st_size)
                == incoming.read_bytes()
            )
            report["cases"].append(
                {
                    "name": case["name"],
                    "status": "PASS",
                    "input_sha256": sha(incoming),
                    "stream_sha256": sha(encoded),
                    "both_cross_decode": True,
                }
            )
        report.update(
            status="PASS_FRESH_ORIGINAL_RUST_DIFFERENTIAL", case_count=len(report["cases"])
        )
    except Exception as error:
        report.update(status="FAIL_OR_BLOCKED", error=str(error))
    changes = [p for p, expected in original_files.items() if sha(source / p) != expected]
    report["original_source_changes"] = changes
    if changes:
        report["status"] = "FAIL_ORIGINAL_SOURCE_CHANGED"
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": report["status"],
                "case_count": len(report["cases"]),
                "error": report.get("error"),
            }
        )
    )
    raise SystemExit(0 if report["status"] == "PASS_FRESH_ORIGINAL_RUST_DIFFERENTIAL" else 1)


if __name__ == "__main__":
    main()
