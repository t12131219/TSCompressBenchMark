"""Decode and reproduce frozen Rust-era Benchmark artifacts with the current C++ codec.

This compatibility replay does not modify the old run set or reinterpret its
recorded implementation identity, measurements, or formal eligibility.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.adapters.lzss_raw import LzssRawSession, _buffer
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import canonical_json_bytes, stable_id


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def identity(path: Path) -> dict[str, str]:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "sha256": sha(path.read_bytes()),
    }


def tree_snapshot(directory: Path) -> list[dict[str, str]]:
    return [
        {"path": str(path.relative_to(directory)), "sha256": sha(path.read_bytes())}
        for path in sorted(directory.rglob("*")) if path.is_file()
    ]


def runtime_manifest(session: LzssRawSession) -> dict[str, Any]:
    pointer = ctypes.c_char_p()
    length = ctypes.c_uint64()
    status = session._native.library.tscb_get_manifest_json(
        ctypes.byref(pointer), ctypes.byref(length)
    )
    session._check(status, "get_manifest")
    manifest = json.loads(ctypes.string_at(pointer, length.value))
    require(manifest.get("library") == "tscb-alexkazik-lzss-0.9.1-cpp",
            "loaded artifact does not declare the current C++ implementation")
    return manifest


def encode_raw(library: Path, payload: bytes) -> bytes:
    session = LzssRawSession(library, {"native_timing": False})
    try:
        runtime_manifest(session)
        bound = session._native_bound(len(payload))
        source = ctypes.create_string_buffer(payload, max(1, len(payload)))
        original_source = source.raw
        destination = ctypes.create_string_buffer(b"\xCA" * (bound + 16), bound + 16)
        incoming = _buffer(ctypes.addressof(source), capacity=len(payload), used=len(payload))
        outgoing = _buffer(ctypes.addressof(destination), capacity=bound, used=0)
        status = session._native.library.tscb_compress(
            session._handle, ctypes.byref(incoming), ctypes.byref(outgoing)
        )
        session._check(status, "compress")
        require(outgoing.used_bytes <= bound, "encoder exceeded output bound")
        require(destination.raw[bound:] == b"\xCA" * 16, "encoder changed output canary")
        require(source.raw == original_source, "encoder mutated input")
        result = destination.raw[:outgoing.used_bytes]
        session._check(session._native.library.tscb_finalize(
            session._handle, ctypes.byref(outgoing)
        ), "finalize")
        require(outgoing.used_bytes == 0, "finalize produced unexpected bytes")
        return result
    finally:
        session.close()


def verify(library: Path, run_set: Path, output: Path) -> dict[str, Any]:
    require(not output.is_relative_to(run_set), "compatibility output must be outside the frozen run set")
    before = tree_snapshot(run_set)
    require(bool(before), "frozen run set is empty")
    build_path = library.parent / "build-record.json"
    build = json.loads(build_path.read_text())
    require(build.get("algorithm") == "lzss-raw" and build.get("core_execution_language") == "C++17",
            "current build record is not a C++ lzss-raw build")
    require(build["artifact_sha256"] == sha(library.read_bytes()), "current library/build SHA mismatch")
    for entry in build["compiled_source_closure"]:
        require(sha((ROOT / entry["path"]).read_bytes()) == entry["sha256"],
                f"current compiled source changed: {entry['path']}")
    source_path = ROOT / "registry/sources/lzss-alexkazik.artifact.json"
    codec_path = ROOT / "registry/codecs/lzss-raw.json"
    source = json.loads(source_path.read_text())
    codec = json.loads(codec_path.read_text())
    source_id = stable_id("source-artifact", source["identity"])
    algorithm_id = stable_id("algorithm", codec)
    require(source_id == codec["identity"]["source_artifact_id"], "current registry source identity mismatch")
    require(source["identity"]["source_closure"] == build["compiled_source_closure"],
            "current source card/build closure mismatch")

    codec_snapshot_path = run_set / "codec_registry_snapshot.json"
    source_snapshot_path = run_set / "source_registry_snapshot.json"
    codec_snapshot = json.loads(codec_snapshot_path.read_text())
    legacy_codecs = [entry for entry in codec_snapshot["codecs"] if entry["key"] == "lzss-raw"]
    require(len(legacy_codecs) == 1, "frozen run set must identify exactly one lzss-raw implementation")
    legacy = legacy_codecs[0]
    legacy_source_id = legacy["manifest"]["identity"]["source_artifact_id"]
    source_snapshot = json.loads(source_snapshot_path.read_text())
    legacy_sources = [entry for entry in source_snapshot["sources"]
                      if entry.get("source_artifact_id") == legacy_source_id]
    require(len(legacy_sources) == 1, "frozen source identity is missing or ambiguous")
    require(legacy_sources[0]["build"]["build_system"] == "OFFLINE_RUSTC_STATICLIB_CPP_C_ABI",
            "requested frozen run set is not the pre-migration Rust implementation")
    require(legacy["algorithm_id"] != algorithm_id and legacy_source_id != source_id,
            "legacy and current implementation identities were conflated")

    records_path = run_set / "run_components.jsonl"
    raw_records = records_path.read_bytes()
    rows: list[dict[str, Any]] = []
    manifest: dict[str, Any] | None = None
    for index, line in enumerate(raw_records.splitlines(keepends=True), 1):
        if not line.strip():
            continue
        record = json.loads(line)
        if record["algorithm_id"] != legacy["algorithm_id"] or record["record_kind"] != "FORMAL_REPETITION":
            continue
        require(record["status"] == "PASS", f"legacy record {index} did not pass")
        digest = record["run_id"].rsplit(":", 1)[-1]
        require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None, "invalid frozen run ID")
        stream_path = run_set / "artifacts" / f"{digest}.bin"
        stream = stream_path.read_bytes()
        require(sha(stream) == record["bitstream_sha256"], f"legacy bitstream SHA mismatch: {stream_path}")
        header, raw_frame = LzssRawSession._parse_container(stream)
        session = LzssRawSession(library, {"native_timing": False})
        try:
            manifest = runtime_manifest(session)
            decoded = session.decompress(stream)
        finally:
            session.close()
        decoded_sha = hash_logical_buffers(decoded.buffers)
        require(decoded_sha == record["input_sha256"], f"legacy decoded input SHA mismatch: {record['run_id']}")
        payload = b"".join(item.array.tobytes(order="C") for item in decoded.buffers)
        encoded = encode_raw(library, payload)
        require(encoded == raw_frame, f"current C++ encoding differs from frozen raw frame: {record['run_id']}")
        require(hash_logical_buffers(decoded.buffers) == decoded_sha, "decoded buffers mutated during re-encode")
        rows.append({
            "status": "PASS",
            "run_id": record["run_id"],
            "run_set_id": record["run_set_id"],
            "record_kind": record["record_kind"],
            "record_line": index,
            "record_serialized_sha256": sha(line),
            "legacy_algorithm_id": record["algorithm_id"],
            "repetition_index": record["repetition_index"],
            "stream": identity(stream_path),
            "container_schema_version": header["schema_version"],
            "container_track": header["track"],
            "decoded_buffers": [
                {"name": item.name, "dtype": item.array.dtype.str, "shape": list(item.array.shape),
                 "logical_bits": item.logical_bits, "payload_bytes": item.array.nbytes}
                for item in decoded.buffers
            ],
            "recorded_input_sha256": record["input_sha256"],
            "decoded_input_sha256": decoded_sha,
            "decoded_payload_bytes": len(payload),
            "raw_frame_sha256": sha(raw_frame),
            "cpp_reencoded_frame_sha256": sha(encoded),
            "raw_frame_bytes": len(raw_frame),
            "checks": ["FROZEN_STREAM_SHA", "CPP_FULL_CONTAINER_DECODE", "LOGICAL_INPUT_SHA",
                       "CPP_RAW_FRAME_BYTE_PARITY", "INPUT_IMMUTABILITY", "ENCODE_CANARY"],
        })
    require(bool(rows), "no legacy lzss-raw formal repetition artifacts found")
    require(tree_snapshot(run_set) == before, "frozen run set changed during verification")
    require(build["artifact_sha256"] == sha(library.read_bytes()), "current library changed during verification")
    result = {
        "schema_version": "tscb.lzss-cpp-legacy-artifact-replay.v1",
        "status": "PASS",
        "scope": "LEGACY_BENCHMARK_CONTAINER_DECODE_AND_RAW_FRAME_REENCODE_COMPATIBILITY",
        "case_count": len(rows),
        "unique_container_sha256_count": len({row["stream"]["sha256"] for row in rows}),
        "unique_logical_input_sha256_count": len({row["recorded_input_sha256"] for row in rows}),
        "frozen_run_set": str(run_set.relative_to(ROOT)) if run_set.is_relative_to(ROOT) else str(run_set),
        "frozen_records": identity(records_path),
        "frozen_codec_snapshot": identity(codec_snapshot_path),
        "frozen_source_snapshot": identity(source_snapshot_path),
        "frozen_tree_sha256": sha(canonical_json_bytes(before)),
        "frozen_tree_file_count": len(before),
        "frozen_run_set_unchanged": True,
        "legacy_algorithm_id": legacy["algorithm_id"],
        "legacy_source_artifact_id": legacy_source_id,
        "current_algorithm_id": algorithm_id,
        "current_source_artifact_id": source_id,
        "current_registry": {"source": identity(source_path), "codec": identity(codec_path)},
        "current_library": identity(library),
        "current_build_record": identity(build_path),
        "current_native_manifest": manifest,
        "driver": identity(Path(__file__).resolve()),
        "original_runtime_required": False,
        "formal_identity_policy": "Compatibility evidence only; frozen identities, performance and eligibility are unchanged",
        "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--run-set", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.library.resolve(), args.run_set.resolve(), args.output.resolve())
    print(json.dumps({"status": result["status"], "case_count": result["case_count"],
                      "frozen_run_set_unchanged": result["frozen_run_set_unchanged"],
                      "output": str(args.output.resolve())}))


if __name__ == "__main__":
    main()
