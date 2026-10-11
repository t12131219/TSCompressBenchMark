"""Fresh, bounded wrapper parity and native API tests; no source-parity claim."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import random
import resource
import shutil
import subprocess
from pathlib import Path

from tscompbench.adapters.lz4_frame import _Buffer, _buffer

ROOT = Path(__file__).resolve().parents[1]


def entry(path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def run(command: list[str], *, expected_failure: bool = False) -> dict:
    environment = dict(
        os.environ,
        ASAN_OPTIONS="detect_leaks=0:abort_on_error=1",
        UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1",
    )
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if (result.returncode == 0) == expected_failure:
        raise RuntimeError(f"unexpected native test outcome: {command}\n{result.stdout}")
    return {"command": command, "returncode": result.returncode, "output": result.stdout}


class Native:
    def __init__(self, path: Path):
        self.lib = ctypes.CDLL(str(path))
        pointer = ctypes.POINTER(_Buffer)
        signatures = {
            "tscb_create": [ctypes.c_char_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_void_p)],
            "tscb_destroy": [ctypes.c_void_p],
            "tscb_compress_bound": [ctypes.c_void_p, pointer, ctypes.POINTER(ctypes.c_uint64)],
            "tscb_compress": [ctypes.c_void_p, pointer, pointer],
            "tscb_finalize": [ctypes.c_void_p, pointer],
            "tscb_decompress": [ctypes.c_void_p, pointer, pointer],
            "tscb_stream_update": [ctypes.c_void_p, pointer, pointer],
            "tscb_stream_finalize": [ctypes.c_void_p, pointer],
        }
        for name, signature in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes = signature
            function.restype = ctypes.c_int

    def create(self, parameters: dict) -> ctypes.c_void_p:
        handle = ctypes.c_void_p()
        config = json.dumps(parameters, sort_keys=True, separators=(",", ":")).encode()
        assert self.lib.tscb_create(config, len(config), ctypes.byref(handle)) == 0
        return handle

    def encode(self, data: bytes, parameters: dict, *, streaming: bool) -> bytes:
        handle = self.create(parameters)
        allocation = ctypes.create_string_buffer(data, max(len(data), 1))
        source = _buffer(ctypes.addressof(allocation), capacity=len(data), used=len(data))
        bound = ctypes.c_uint64()
        try:
            assert (
                self.lib.tscb_compress_bound(handle, ctypes.byref(source), ctypes.byref(bound)) == 0
            )
            target_allocation = ctypes.create_string_buffer(bound.value + 4096)
            capacity = len(target_allocation)
            target = _buffer(ctypes.addressof(target_allocation), capacity=capacity, used=0)
            wire = bytearray()
            chunks = (
                [data] if not streaming else [data[i : i + 1023] for i in range(0, len(data), 1023)]
            )
            if not chunks:
                chunks = [b""]
            for chunk in chunks:
                chunk_allocation = ctypes.create_string_buffer(chunk, max(len(chunk), 1))
                source = _buffer(
                    ctypes.addressof(chunk_allocation), capacity=len(chunk), used=len(chunk)
                )
                target.used_bytes = 0
                function = self.lib.tscb_stream_update if streaming else self.lib.tscb_compress
                assert function(handle, ctypes.byref(source), ctypes.byref(target)) == 0
                wire.extend(target_allocation.raw[: target.used_bytes])
            target.used_bytes = 0
            function = self.lib.tscb_stream_finalize if streaming else self.lib.tscb_finalize
            assert function(handle, ctypes.byref(target)) == 0
            wire.extend(target_allocation.raw[: target.used_bytes])
            return bytes(wire)
        finally:
            assert self.lib.tscb_destroy(handle) == 0

    def decode(
        self, wire: bytes, expected_size: int, *, invalid_used: bool = False
    ) -> tuple[int, bytes, int]:
        handle = self.create({})
        source_allocation = ctypes.create_string_buffer(wire, len(wire))
        source = _buffer(ctypes.addressof(source_allocation), capacity=len(wire), used=len(wire))
        target_allocation = ctypes.create_string_buffer(max(expected_size, 1))
        target = _buffer(
            ctypes.addressof(target_allocation),
            capacity=expected_size,
            used=expected_size + 1 if invalid_used else 0,
        )
        try:
            status = self.lib.tscb_decompress(handle, ctypes.byref(source), ctypes.byref(target))
            return status, target_allocation.raw[: target.used_bytes], target.used_bytes
        finally:
            assert self.lib.tscb_destroy(handle) == 0


def qualify(build_root: Path, report_root: Path) -> dict:
    report_root.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    generator = random.Random(20261011)
    cases = []
    for length in (0, 1, 2, 3, 31, 32, 33, 255, 256, 257, 65535, 65536, 65537, 131073):
        for name, data in (
            ("zeros", bytes(length)),
            ("ascending", bytes(index % 256 for index in range(length))),
            ("alternating", (b"\x00\xff" * ((length + 1) // 2))[:length]),
            ("seeded_random", generator.randbytes(length)),
        ):
            cases.append((f"{name}/{length}", data))
    datasets = []
    for name in ("ETTh1.csv", "exchange_rate.csv", "weather.csv"):
        path = ROOT / "datasets" / name
        data = path.read_bytes()[:32768]
        cases.append((f"dataset_byte_sample/{name}", data))
        datasets.append(
            {
                **entry(path),
                "sample_size_bytes": len(data),
                "sample_sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    results = []
    for family in ("lz4_frame", "zstd_frame"):
        patch = ROOT / f"adapters/{family}/patches/0001-output-descriptor-eof-state.patch"
        relative = f"adapters/{family}/native/tscb_{family}.c"
        baseline = ROOT / "docs/audits/20261011_port_standard_v30/native_api_baselines" / relative
        replay_root = report_root / "patch_replay" / family
        replay = replay_root / relative
        replay.parent.mkdir(parents=True)
        shutil.copyfile(baseline, replay)
        directory = str(replay_root.relative_to(ROOT))
        replay_commands = [
            run(["git", "apply", "--check", f"--directory={directory}", str(patch)]),
            run(["git", "apply", f"--directory={directory}", str(patch)]),
        ]
        assert replay.read_bytes() == (ROOT / relative).read_bytes()
        native_tests = []
        old_path = ROOT / f"build/adapters/{family}/release/libtscb_{family}.so"
        for profile in ("release", "sanitizer"):
            folder = build_root / family / profile
            library = folder / f"libtscb_{family}.so"
            for test_name, source in (
                ("api_contract", ROOT / "tests/native/frame_byte_api_contract.c"),
                ("abi_smoke", ROOT / f"adapters/{family}/tests/abi_smoke.c"),
            ):
                output = report_root / f"{family}_{profile}_{test_name}"
                flags = (
                    ["-O2"]
                    if profile == "release"
                    else [
                        "-O1",
                        "-g",
                        "-fno-omit-frame-pointer",
                        "-fsanitize=address,undefined",
                        "-no-pie",
                    ]
                )
                command = [
                    "cc",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-UNDEBUG",
                    *flags,
                    "-I",
                    str(ROOT / "native/include"),
                    str(source),
                    "-L",
                    str(folder),
                    f"-ltscb_{family}",
                    f"-Wl,-rpath,{folder}",
                    "-o",
                    str(output),
                ]
                compilation = run(command)
                execution = run([str(output)])
                native_tests.append(
                    {
                        "profile": profile,
                        "test": test_name,
                        "library": entry(library),
                        "source": entry(source),
                        "executable": entry(output),
                        "compilation": compilation,
                        "execution": execution,
                    }
                )
        old = Native(old_path)
        fresh_path = build_root / family / "release" / f"libtscb_{family}.so"
        fresh = Native(fresh_path)
        parameters = (
            [
                {
                    "compression_level": 0,
                    "block_size_id": 4,
                    "block_mode": 0,
                    "content_checksum": True,
                    "block_checksum": False,
                },
                {
                    "compression_level": 12,
                    "block_size_id": 7,
                    "block_mode": 1,
                    "content_checksum": False,
                    "block_checksum": True,
                },
            ]
            if family == "lz4_frame"
            else [
                {"compression_level": 1, "content_checksum": False},
                {"compression_level": 3, "content_checksum": True},
                {"compression_level": 19, "content_checksum": True},
            ]
        )
        parity = []
        for parameters_item in parameters:
            for streaming in (False, True):
                for name, data in cases:
                    before = old.encode(data, parameters_item, streaming=streaming)
                    after = fresh.encode(data, parameters_item, streaming=streaming)
                    assert before == after
                    for decoder, encoded in ((old, after), (fresh, before)):
                        status, decoded, used = decoder.decode(encoded, len(data))
                        assert status == 0 and used == len(data) and decoded == data
                    parity.append(
                        {
                            "case": name,
                            "streaming": streaming,
                            "parameters": parameters_item,
                            "input_sha256": hashlib.sha256(data).hexdigest(),
                            "frame_sha256": hashlib.sha256(after).hexdigest(),
                            "frame_size_bytes": len(after),
                            "byte_parity": "PASS",
                            "both_cross_decode_directions": "PASS",
                        }
                    )
        data = bytes(range(128))
        wire = fresh.encode(data, {}, streaming=False)
        old_status, _, old_used = old.decode(wire, len(data), invalid_used=True)
        fresh_status, _, fresh_used = fresh.decode(wire, len(data), invalid_used=True)
        assert old_status == 0 and old_used == len(data)
        assert fresh_status == 1 and fresh_used == len(data) + 1
        results.append(
            {
                "family": family,
                "status": "PASS",
                "baseline_library": entry(old_path),
                "current_library": entry(fresh_path),
                "binding_baseline": entry(baseline),
                "binding_source": entry(ROOT / relative),
                "patch": entry(patch),
                "replay_output": entry(replay),
                "patch_replay": replay_commands,
                "native_tests": native_tests,
                "legal_wrapper_parity_cases": parity,
                "counterexample": {
                    "invalid_output_used_bytes": len(data) + 1,
                    "capacity_bytes": len(data),
                    "old_status": old_status,
                    "old_result_used_bytes": old_used,
                    "fresh_status": fresh_status,
                    "fresh_result_used_bytes": fresh_used,
                },
            }
        )
    return {
        "schema_version": "tscb.frame-binding-contract-audit.v1",
        "status": "PASS",
        "scope": "PROJECT_BINDING_API_SAFETY_AND_FINITE_OLD_NEW_FRAME_PARITY",
        "source_full_parity": "NOT_ASSERTED",
        "driver": entry(Path(__file__)),
        "datasets": datasets,
        "results": results,
        "sanitizer_scope": "C_BINDING_AND_VENDORED_CODEC_ASAN_UBSAN_SYSTEM_RUNTIME_UNINSTRUMENTED",
        "leak_sanitizer": "DISABLED_HOST_PTRACE_LIMITATION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-root", required=True, type=Path)
    parser.add_argument("--report-root", required=True, type=Path)
    arguments = parser.parse_args()
    report_root = arguments.report_root.resolve()
    result = qualify(arguments.build_root.resolve(), report_root)
    with (report_root / "qualification.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(
        json.dumps({"status": result["status"], "report": str(report_root / "qualification.json")})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
