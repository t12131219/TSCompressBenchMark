"""Verify the C++ port against bitstreams frozen from the original implementation."""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def input_bytes(case: dict) -> bytes:
    n, pattern = case["length"], case["pattern"]
    rng = random.Random(case["seed"])
    if pattern == "random256":
        return rng.randbytes(n)
    if pattern == "random4":
        return bytes(rng.randrange(4) for _ in range(n))
    unit = {
        "spaces": b" ", "zeros": b"\0", "cycle256": bytes(range(256)),
        "period3": b"abc", "ties": b"abcdabcXabcdabcYabcZab",
    }[pattern]
    return (unit * ((n + len(unit) - 1) // len(unit)))[:n]


def native_call(library: Path, payload: bytes, expected: int | None) -> bytes:
    from tscompbench.adapters.lzss_raw import LzssRawSession, _buffer

    encode = expected is None
    capacity = len(payload) + (len(payload) + 7) // 8 if encode else expected
    source = ctypes.create_string_buffer(payload, max(1, len(payload)))
    destination = ctypes.create_string_buffer(b"\xCA" * (capacity + 16), capacity + 16)
    incoming = _buffer(ctypes.addressof(source), capacity=len(payload), used=len(payload))
    outgoing = _buffer(ctypes.addressof(destination), capacity=capacity, used=0)
    session = LzssRawSession(library, {"native_timing": False})
    try:
        operation = session._native.library.tscb_compress if encode else session._native.library.tscb_decompress
        status = operation(session._handle, ctypes.byref(incoming), ctypes.byref(outgoing))
        if status:
            raise RuntimeError(f"native call failed: {status}: {session._last_error()}")
        assert destination.raw[capacity:] == b"\xCA" * 16, "output guard changed"
        assert source.raw[:len(payload)] == payload, "input changed"
        result = destination.raw[:outgoing.used_bytes]
        if encode:
            assert session._native.library.tscb_finalize(session._handle, ctypes.byref(outgoing)) == 0
            assert outgoing.used_bytes == 0
        return result
    finally:
        session.close()


def runner_call(runner: Path, payload: bytes, expected: int | None, temporary: Path) -> bytes:
    source, destination = temporary / "input.bin", temporary / "output.bin"
    source.write_bytes(payload)
    destination.unlink(missing_ok=True)
    arguments = [str(runner), "encode" if expected is None else "decode", str(source)]
    if expected is not None:
        arguments.append(str(expected))
    arguments.append(str(destination))
    result = subprocess.run(arguments, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace"))
    assert source.read_bytes() == payload, "input changed"
    return destination.read_bytes()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--runner", type=Path)
    parser.add_argument("--reference-library", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fixture = ROOT / "adapters/lzss_raw/tests/fixtures/reference_vectors.json"
    document = json.loads(fixture.read_text())
    if args.reference_library:
        assert sha(args.reference_library.read_bytes()) == document["reference"]["native_library_sha256"]
    rows = []
    with tempfile.TemporaryDirectory(prefix="lzss-cpp-wire-") as directory:
        temporary = Path(directory)
        for case in document["cases"]:
            data = input_bytes(case)
            expected = base64.b64decode(case["stream_base64"], validate=True)
            assert sha(data) == case["input_sha256"]
            assert sha(expected) == case["stream_sha256"] and len(expected) == case["stream_bytes"]
            def invoke(payload, count):
                if args.runner:
                    return runner_call(args.runner.resolve(), payload, count, temporary)
                return native_call(args.library.resolve(), payload, count)
            actual = invoke(data, None)
            assert actual == expected, f"encode differs from original: {case['name']}"
            assert invoke(expected, len(data)) == data, f"original stream decode: {case['name']}"
            if args.reference_library:
                assert native_call(args.reference_library.resolve(), actual, len(data)) == data
                assert native_call(args.reference_library.resolve(), data, None) == expected
            rows.append({"name": case["name"], "status": "PASS", "input_sha256": sha(data),
                         "stream_sha256": sha(actual), "decoded_bytes": len(data)})
    result = {
        "status": "PASS", "scope": "REGISTERED_EI10_EJ4_C32_BYTE_STREAM_PARITY",
        "case_count": len(rows), "reference": document["reference"],
        "fixture_sha256": sha(fixture.read_bytes()), "driver_sha256": sha(Path(__file__).read_bytes()),
        "library": {"path": str(args.library), "sha256": sha(args.library.read_bytes())},
        "runner": {"path": str(args.runner), "sha256": sha(args.runner.read_bytes())} if args.runner else None,
        "live_original_cross_decode": args.reference_library is not None,
        "compiler_or_reference_runtime_required": False, "cases": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "case_count": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()
