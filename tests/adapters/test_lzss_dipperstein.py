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

from tscompbench.adapters import LzssDippersteinAdapter
from tscompbench.adapters.lzss_dipperstein import LzssDippersteinSession
from tscompbench.adapters.lzss_raw import _PREFIX, _buffer
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.planning import expand_sweep
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "build/adapters/lzss_dipperstein_c/release/libtscb_lzss_dipperstein_c.so"


def _adapter():
    if not LIBRARY.is_file():
        subprocess.run(
            [sys.executable, "tools/build_codec.py", "lzss-dipperstein-c"], cwd=ROOT, check=True
        )
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("lzss-dipperstein-c")
    return LzssDippersteinAdapter(LIBRARY, manifest.document["adapter"]), manifest


def _route(n=8):
    bits = np.resize(
        np.asarray(
            [
                0, 0x8000000000000000, 0x7FF0000000000000, 0xFFF0000000000000,
                0x7FF8000000000001, 0x7FF8000000000123, 1, 0x3FF0000000000001,
            ],
            dtype="<u8",
        ),
        n,
    )
    arrays = (bits.view("<f8"), bits[::-1].copy().view("<f8"))
    for array in arrays:
        array.flags.writeable = False
    buffers = tuple(
        LogicalBuffer(f"value/{index:06d}", array, array.nbytes * 8)
        for index, array in enumerate(arrays)
    )
    return RoutedInput(
        dataset_id="dataset:lzss-dipperstein", track=BenchmarkTrack.VALUE, buffers=buffers,
        timestamp_reference=None, validity_reference=None, n=n, m=2,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )


def _reference_decode(stream: bytes, expected: int) -> bytes:
    bits = "".join(f"{value:08b}" for value in stream)
    dictionary = bytearray(b" " * 4096)
    cursor = 0
    position = 0
    output = bytearray()
    while len(output) < expected:
        assert position < len(bits)
        literal = bits[position] == "1"
        position += 1
        count = 8 if literal else 16
        assert len(bits) - position >= count
        token = int(bits[position : position + count], 2)
        position += count
        if literal:
            emitted = bytes([token])
        else:
            low_offset = token >> 8
            high_offset = (token >> 4) & 15
            offset = low_offset | (high_offset << 8)
            length = (token & 15) + 3
            emitted = bytes(dictionary[(offset + index) & 4095] for index in range(length))
        output.extend(emitted)
        for value in emitted:
            dictionary[cursor] = value
            cursor = (cursor + 1) & 4095
    assert len(output) == expected
    assert len(bits) - position <= 7 and "1" not in bits[position:]
    return bytes(output)


@pytest.mark.parametrize("profile", ["qualification", "formal"])
def test_config_and_source_card(profile):
    _, manifest = _adapter()
    document = tomllib.loads(
        (ROOT / f"configs/experiments/lzss-dipperstein-c-{profile}.toml").read_text()
    )
    configs = expand_sweep(manifest, document["sweep"])
    assert len(configs) == 1 and configs[0].status is not RunStatus.SCHEMA_ERROR
    assert configs[0].parameters["offset_bits"] == 12
    assert configs[0].parameters["length_bits"] == 4
    assert configs[0].parameters["match_finder"] == "BINARY_TREE"
    card = json.loads((ROOT / "registry/onboarding/lzss-dipperstein-c.json").read_text())
    assert validate_onboarding_card(card)["source_artifact_id"] == manifest.source_artifact_id


@pytest.mark.parametrize("n", [0, 1, 2, 17, 18, 19, 4095, 4096, 4097])
def test_ieee_exactness_independent_decode_and_accounting(n):
    adapter, _ = _adapter()
    routed = _route(n)
    result = perform_roundtrip(adapter, routed, {})
    for item in routed.buffers:
        assert result.decoded.by_name()[item.name].array.tobytes() == item.array.tobytes()
    header, stream = LzssDippersteinSession._parse_container(result.encoded.stream)
    payload = b"".join(item.array.tobytes() for item in routed.buffers)
    assert _reference_decode(stream, len(payload)) == payload
    parts = LzssDippersteinSession._inspect_lzss_stream(stream, len(payload))
    ledger = result.encoded.ledger
    assert ledger.value_bits == parts["payload_bits"]
    assert ledger.padding_bits == parts["padding_bits"]
    assert ledger.container_bits == _PREFIX.size * 8
    assert ledger.checksum_bits == 0
    assert ledger.final_bits == len(result.encoded.stream) * 8
    assert result.encoded.finalize_bytes == 0
    assert result.canary_intact and result.input_immutable and result.determinism_match
    assert header["schema_version"] == "tscb.lzss-dipperstein-c-container.v1"


@pytest.mark.parametrize("track", [BenchmarkTrack.VALUE, BenchmarkTrack.TIMESTAMP])
def test_framework_boundary_suite(track):
    adapter, manifest = _adapter()
    report = run_boundary_suite(adapter, manifest, track, {"block_size": 18, "isa": "SCALAR"})
    assert report.passed, [item for item in report.observations if item.status != "PASS"]


@pytest.mark.parametrize("mutation", ["truncated", "trailing", "concat", "padding"])
def test_reject_partial_tokens_extra_bytes_and_nonzero_padding(mutation):
    adapter, _ = _adapter()
    result = perform_roundtrip(adapter, _route(1), {})
    _, stream = LzssDippersteinSession._parse_container(result.encoded.stream)
    prefix = result.encoded.stream[: -len(stream)]
    damaged = {
        "truncated": stream[:-1],
        "trailing": stream + b"\0",
        "concat": stream + stream,
        "padding": stream[:-1] + bytes([stream[-1] | 1]),
    }[mutation]
    session = adapter.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.decompress(prefix + damaged)
    finally:
        session.close()


@pytest.mark.parametrize(
    "key,value",
    [("offset_bits", 11), ("length_bits", 5), ("initial_byte", 0),
     ("match_finder", "BRUTE_FORCE")],
)
def test_fixed_variant_is_not_silently_changed(key, value):
    adapter, _ = _adapter()
    with pytest.raises(ExecutionContractError):
        adapter.create_session({key: value})


def test_native_golden_vector_bound_canary_state_reset_and_timing():
    adapter, _ = _adapter()
    session = adapter.create_session({})
    library = session._native.library
    library.tscb_reset.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    library.tscb_reset.restype = ctypes.c_uint32
    source = b"Sample   Data   11221233123"
    expected = bytes.fromhex("a9d86db70b6595dde144b0dd2c2eff098cc6653298cca67330a000")
    src = ctypes.create_string_buffer(source)
    bound = len(source) + (len(source) + 7) // 8
    dst = ctypes.create_string_buffer(bound + 8)
    ctypes.memset(ctypes.addressof(dst), 0xCA, bound + 8)
    inp = _buffer(ctypes.addressof(src), capacity=len(source), used=len(source))
    out = _buffer(ctypes.addressof(dst), capacity=bound - 1, used=0)
    try:
        assert library.tscb_compress(session._handle, ctypes.byref(inp), ctypes.byref(out)) == 3
        assert session.native_timing() == (0, 0)
        out.capacity_bytes = bound
        assert library.tscb_compress(session._handle, ctypes.byref(inp), ctypes.byref(out)) == 0
        assert dst.raw[: out.used_bytes] == expected
        assert dst.raw[bound:] == b"\xca" * 8
        measured = session.native_timing()
        assert measured[0] > 0 and measured[1] == 0
        assert library.tscb_compress(session._handle, ctypes.byref(inp), ctypes.byref(out)) == 4
        assert library.tscb_finalize(session._handle, ctypes.byref(out)) == 0
        assert library.tscb_finalize(session._handle, ctypes.byref(out)) == 4
        assert library.tscb_reset(session._handle, 0) == 0
        assert session.native_timing() == (0, 0)
        assert library.tscb_finalize(session._handle, ctypes.byref(out)) == 5
    finally:
        session.close()


def test_source_closure_digest_and_pinned_identity():
    root = ROOT / "adapters/lzss_dipperstein/vendor/lzss"
    source = json.loads(
        (ROOT / "registry/sources/lzss-dipperstein-c.artifact.json").read_text()
    )
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes())
    assert len(files) == source["identity"]["source_closure_file_count"] == 12
    assert digest.hexdigest() == source["identity"]["source_closure_sha256"]
    assert source["identity"]["commit"] == "65b6882ff1cc225f9c6fcd947def7b1adb21d578"
