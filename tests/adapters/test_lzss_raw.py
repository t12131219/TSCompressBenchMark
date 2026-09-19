from __future__ import annotations

import ctypes
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import LzssRawAdapter
from tscompbench.adapters.lzss_raw import LzssRawSession, _buffer
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.planning import expand_sweep
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "build/adapters/lzss_raw/release/libtscb_lzss_raw.so"


def _adapter():
    if not LIBRARY.is_file():
        subprocess.run([sys.executable, "tools/build_codec.py", "lzss-raw"], cwd=ROOT, check=True)
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("lzss-raw")
    return LzssRawAdapter(LIBRARY, manifest.document["adapter"]), manifest


def _route(n=8):
    bits = np.resize(
        np.asarray(
            [
                0,
                0x8000000000000000,
                0x7FF0000000000000,
                0xFFF0000000000000,
                0x7FF8000000000001,
                0x7FF8000000000123,
                1,
                0x3FF0000000000001,
            ],
            dtype="<u8",
        ),
        n,
    )
    buffers = tuple(
        LogicalBuffer(f"value/{index:06d}", array, array.nbytes * 8)
        for index, array in enumerate([bits.view("<f8"), bits[::-1].copy().view("<f8")])
    )
    for item in buffers:
        item.array.flags.writeable = False
    return RoutedInput(
        dataset_id="dataset:lzss",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=n,
        m=2,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )


def _reference_decode(stream, expected):
    # Independent test oracle for the published Okumura EI10/EJ4 bit format.
    bits = "".join(f"{value:08b}" for value in stream)
    dictionary = bytearray(b" " * 1024)
    cursor = 1007
    position = 0
    output = bytearray()
    while len(output) < expected:
        literal = bits[position] == "1"
        position += 1
        count = 8 if literal else 14
        assert len(bits) - position >= count
        token = int(bits[position : position + count], 2)
        position += count
        offset = token >> 4
        for k in range(1 if literal else (token & 15) + 2):
            value = token if literal else dictionary[(offset + k) & 1023]
            output.append(value)
            dictionary[cursor] = value
            cursor = (cursor + 1) & 1023
    assert len(output) == expected
    assert len(bits) - position <= 7 and "1" not in bits[position:]
    return bytes(output)


@pytest.mark.parametrize("profile", ["qualification", "formal"])
def test_config_and_source_card(profile):
    _, manifest = _adapter()
    config = tomllib.loads((ROOT / f"configs/experiments/lzss-raw-{profile}.toml").read_text())
    configs = expand_sweep(manifest, config["sweep"])
    assert len(configs) == 1 and configs[0].status is not RunStatus.SCHEMA_ERROR
    assert configs[0].parameters["ei"] == 10
    card = json.loads((ROOT / "registry/onboarding/lzss-raw.json").read_text())
    assert validate_onboarding_card(card)["source_artifact_id"] == manifest.source_artifact_id


@pytest.mark.parametrize("n", [0, 1, 2, 63, 64, 65, 1023, 1024, 1025, 4095, 4096, 4097])
def test_ieee_exactness_independent_decode_and_accounting(n):
    adapter, _ = _adapter()
    routed = _route(n)
    result = perform_roundtrip(adapter, routed, {})
    for item in routed.buffers:
        assert result.decoded.by_name()[item.name].array.tobytes() == item.array.tobytes()
    header, stream = LzssRawSession._parse_container(result.encoded.stream)
    payload = b"".join(item.array.tobytes() for item in routed.buffers)
    assert _reference_decode(stream, len(payload)) == payload
    parts = LzssRawSession._inspect_lzss_stream(stream, len(payload))
    ledger = result.encoded.ledger
    assert ledger.value_bits == parts["payload_bits"]
    assert ledger.padding_bits == parts["padding_bits"]
    assert ledger.container_bits == 96 and ledger.checksum_bits == 0
    assert ledger.final_bits == len(result.encoded.stream) * 8
    assert result.encoded.finalize_bytes == 0
    assert result.canary_intact and result.input_immutable and result.determinism_match
    session = adapter.create_session({})
    try:
        decoded = session.decompress(result.encoded.stream)
        assert decoded.by_name()[header["buffers"][0]["name"]].array.shape == (n,)
    finally:
        session.close()


@pytest.mark.parametrize("track", [BenchmarkTrack.VALUE, BenchmarkTrack.TIMESTAMP])
def test_framework_boundary_suite(track):
    adapter, manifest = _adapter()
    report = run_boundary_suite(adapter, manifest, track, {"block_size": 8, "isa": "SCALAR"})
    assert report.passed, [item for item in report.observations if item.status != "PASS"]


@pytest.mark.parametrize("mutation", ["truncated", "trailing", "concat", "padding"])
def test_reject_partial_tokens_extra_bytes_and_nonzero_padding(mutation):
    adapter, _ = _adapter()
    result = perform_roundtrip(adapter, _route(1), {})
    _, stream = LzssRawSession._parse_container(result.encoded.stream)
    prefix = result.encoded.stream[: -len(stream)]
    if mutation == "padding":
        # A one-byte literal always has seven zero padding bits.
        with pytest.raises(ExecutionContractError):
            LzssRawSession._inspect_lzss_stream(bytes([0xA0, 0x81]), 1)
        return
    damaged = {"truncated": stream[:-1], "trailing": stream + b"\0", "concat": stream + stream}[
        mutation
    ]
    session = adapter.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.decompress(prefix + damaged)
    finally:
        session.close()


@pytest.mark.parametrize("key,value", [("ei", 11), ("ej", 5), ("initial_byte", 0)])
def test_fixed_variant_is_not_silently_changed(key, value):
    adapter, _ = _adapter()
    with pytest.raises(ExecutionContractError):
        adapter.create_session({key: value})


def test_native_golden_vector_bound_state_reset_and_timing():
    adapter, _ = _adapter()
    session = adapter.create_session({})
    library = session._native.library
    library.tscb_reset.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    library.tscb_reset.restype = ctypes.c_uint32
    source = b"Sample   Data   11221233123"
    expected = bytes(
        [
            169,
            216,
            109,
            183,
            11,
            101,
            149,
            246,
            13,
            18,
            195,
            116,
            176,
            191,
            81,
            152,
            204,
            102,
            83,
            32,
            0,
            19,
            57,
            152,
            3,
            16,
        ]
    )
    src = ctypes.create_string_buffer(source)
    bound = len(source) + (len(source) + 7) // 8
    dst = ctypes.create_string_buffer(bound + 8)
    ctypes.memset(ctypes.addressof(dst), 0xCA, bound + 8)
    inp = _buffer(ctypes.addressof(src), capacity=len(source), used=len(source))
    out = _buffer(ctypes.addressof(dst), capacity=bound - 1, used=0)
    handle = session._handle
    try:
        assert library.tscb_compress(handle, ctypes.byref(inp), ctypes.byref(out)) == 3
        assert session.native_timing() == (0, 0)
        out.capacity_bytes = bound
        assert library.tscb_compress(handle, ctypes.byref(inp), ctypes.byref(out)) == 0
        assert dst.raw[: out.used_bytes] == expected
        assert dst.raw[bound:] == b"\xca" * 8
        measured = session.native_timing()
        assert measured[0] > 0 and measured[1] == 0
        assert library.tscb_compress(handle, ctypes.byref(inp), ctypes.byref(out)) == 4
        assert library.tscb_finalize(handle, ctypes.byref(out)) == 0 and out.used_bytes == 0
        assert session.native_timing() == measured
        assert library.tscb_finalize(handle, ctypes.byref(out)) == 4
        assert library.tscb_reset(handle, 0) == 0 and session.native_timing() == (0, 0)
        assert library.tscb_finalize(handle, ctypes.byref(out)) == 5
    finally:
        session.close()
    with pytest.raises(ExecutionContractError):
        session.native_timing()


def test_source_closure_digest():
    root = ROOT / "adapters/lzss_raw/vendor"
    source = json.loads((ROOT / "registry/sources/lzss-alexkazik.artifact.json").read_text())
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    assert len(files) == source["identity"]["source_closure_file_count"] == 34
    assert digest.hexdigest() == source["identity"]["source_closure_sha256"]


def test_upstream_closure_identity_is_pinned():
    source = json.loads((ROOT / "registry/sources/lzss-alexkazik.artifact.json").read_text())
    assert (
        source["identity"]["source_closure_sha256"]
        == "82cb61ecc9d31fd48a31624fd2b45f310fcf641d5fcd8e2dcca11d361feced2c"
    )
