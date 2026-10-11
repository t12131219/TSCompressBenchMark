"""Qualify the registered C++ LZSS core, ABI, and retained bitstream fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "build/source-audits/lzss-cpp-native-tests-20261011.json"


def _identity(path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def qualify(profiles: tuple[str, ...], output: Path, *, build: bool = True) -> dict[str, Any]:
    adapter = ROOT / "adapters/lzss_raw"
    compiler = os.environ.get("CXX", "c++")
    output.parent.mkdir(parents=True, exist_ok=True)
    log_path = output.with_suffix(".log")
    records: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    replay_records: list[dict[str, Any]] = []
    log: list[str] = []
    environment = {
        **os.environ,
        "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
        "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1",
        "PYTHONOPTIMIZE": "0",  # Retained fixture verification uses assertions.
    }

    def run(command: list[str]) -> str:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=240,
        )
        log.extend([shlex.join(command), result.stdout])
        log_path.write_text("\n".join(log), encoding="utf-8")
        if result.returncode:
            raise RuntimeError(
                f"qualification failed ({result.returncode}): "
                f"{shlex.join(command)}\n{result.stdout}"
            )
        if result.stdout.strip():
            print(result.stdout, flush=True)
        return result.stdout

    for profile in profiles:
        directory = ROOT / f"build/adapters/lzss_raw/{profile}"
        directory.mkdir(parents=True, exist_ok=True)
        if build:
            run([
                sys.executable, str(ROOT / "tools/build_codec.py"),
                "lzss-raw", "--profile", profile,
            ])
        library = directory / "libtscb_lzss_raw.so"
        build_record = json.loads((directory / "build-record.json").read_text(encoding="utf-8"))
        if build_record.get("core_execution_language") != "C++17":
            raise RuntimeError(f"artifact is not a qualified C++ build: {library}")
        if build_record["artifact_sha256"] != _identity(library)["sha256"]:
            raise RuntimeError(f"build record does not match artifact: {library}")
        for source in build_record["compiled_source_closure"]:
            if _identity(ROOT / source["path"])["sha256"] != source["sha256"]:
                raise RuntimeError(f"compiled source changed; rebuild before qualification: {source['path']}")
        flags = ["-std=c++17", "-Wall", "-Wextra", "-Werror", "-UNDEBUG"]
        if profile == "release":
            flags += ["-O3"]
        elif profile == "sanitizer":
            flags += [
                "-O1", "-g", "-fsanitize=address,undefined",
                "-fno-omit-frame-pointer", "-no-pie",
            ]
        else:
            raise ValueError(f"unknown qualification profile: {profile}")

        def compile_native(source: Path, name: str) -> tuple[Path, list[str]]:
            executable = directory / name
            command = [
                compiler, *flags,
                "-I", str(ROOT / "native/include"),
                "-I", str(adapter / "native"),
                str(source), "-L", str(directory),
                f"-Wl,-rpath,{directory}", "-ltscb_lzss_raw",
                "-o", str(executable),
            ]
            run(command)
            return executable, command

        for source, name, suite in (
            (adapter / "native/qualification.cc", "abi-qualification", "abi-qualification-39-cases"),
            (
                adapter / "tests/test_decoder_contract.cc",
                "decoder-contract-qualification",
                "independent-decoder-contract",
            ),
        ):
            executable, command = compile_native(source, name)
            observation = run([str(executable)])
            records.append({
                "profile": profile,
                "suite": suite,
                "status": "PASS",
                "source": _identity(source),
                "executable": _identity(executable),
                "compile_command": command,
                "observation": observation.strip(),
            })

        runner, runner_command = compile_native(adapter / "tests/codec_cli.cc", "codec-cli")
        replay_path = output.with_name(f"{output.stem}-{profile}-bitstream-replay.json")
        run([
            sys.executable, str(ROOT / "tools/verify_lzss_cpp.py"),
            "--library", str(library), "--runner", str(runner),
            "--output", str(replay_path),
        ])
        replay_document = json.loads(replay_path.read_text(encoding="utf-8"))
        if replay_document.get("status") != "PASS" or replay_document.get("case_count", 0) <= 0:
            raise RuntimeError(f"bitstream replay report did not confirm passing cases: {replay_path}")
        if replay_document["library"]["sha256"] != _identity(library)["sha256"]:
            raise RuntimeError(f"bitstream replay report does not match library: {library}")
        records.append({
            "profile": profile,
            "suite": "retained-reference-bitstream-replay",
            "status": "PASS",
            "runner": _identity(runner),
            "runner_compile_command": runner_command,
            "report": _identity(replay_path),
        })
        replay_records.append({
            "profile": profile,
            "report": _identity(replay_path),
            "verification": replay_document,
        })
        artifacts.append({
            "profile": profile,
            "library": _identity(library),
            "build_record": _identity(directory / "build-record.json"),
            "compile_command": _identity(directory / "compile-command.json"),
        })

    document = {
        "schema_version": "tscb.native-qualification.v1",
        "algorithm": "lzss-raw",
        "status": "PASS",
        "implementation": "C++17 registered EI=10/EJ=4/C=32 raw profile",
        "profiles": list(profiles),
        "suites": records,
        "artifacts": artifacts,
        "bitstream_replay": replay_records,
        "log": _identity(log_path),
        "log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),
        "sanitizer_coverage": (
            "C++ encoder, decoder, strict bitstream validator, ABI and native test runners "
            "use ASan/UBSan in sanitizer profile; system runtime is uninstrumented; "
            "LSan disabled for ptrace-based sandbox compatibility"
            if "sanitizer" in profiles else "NOT_APPLICABLE"
        ),
        "upstream_test_execution": "Retained fixtures replayed; original-language test suites are not executed",
    }
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("release", "sanitizer", "all"), default="all")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-build", action="store_true", help="Qualify already built C++ artifacts")
    arguments = parser.parse_args()
    profiles = ("release", "sanitizer") if arguments.profile == "all" else (arguments.profile,)
    output = arguments.output.resolve()
    document = qualify(profiles, output, build=not arguments.skip_build)
    print(json.dumps({
        "status": document["status"],
        "output": str(output),
        "profiles": document["profiles"],
        "suites": [
            {key: suite[key] for key in ("profile", "suite", "status")}
            for suite in document["suites"]
        ],
    }, indent=2))


if __name__ == "__main__":
    main()
