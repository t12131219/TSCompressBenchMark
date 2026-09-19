from __future__ import annotations

import hashlib
import lzma
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import XzStreamAdapter
from tscompbench.adapters.xz_stream import XzStreamSession
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack, RunStatus
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.planning import expand_sweep
from tscompbench.validation import run_boundary_suite

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = PROJECT_ROOT / "build/adapters/xz_stream/release/libtscb_xz_stream.so"


@pytest.mark.parametrize("profile", ["qualification", "formal"])
def test_checked_in_experiment_parameters_are_registered(profile):
    sources = SourceRegistry(PROJECT_ROOT / "registry/sources")
    manifest = CodecRegistry(PROJECT_ROOT / "registry/codecs", sources).get("xz-stream")
    path = PROJECT_ROOT / f"configs/experiments/xz-stream-{profile}.toml"
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    configurations = expand_sweep(manifest, document["sweep"])
    assert len(configurations) == 1
    assert configurations[0].status is not RunStatus.SCHEMA_ERROR
    assert configurations[0].parameters["compression_level"] == 6


def _adapter_and_manifest():
    if not LIBRARY.is_file():
        subprocess.run([
            sys.executable, "tools/build_codec.py", "xz-stream", "--profile", "release"
        ], cwd=PROJECT_ROOT, check=True)
    sources = SourceRegistry(PROJECT_ROOT / "registry/sources")
    manifest = CodecRegistry(PROJECT_ROOT / "registry/codecs", sources).get("xz-stream")
    return XzStreamAdapter(LIBRARY, manifest.document["adapter"]), manifest


def _route(n=8):
    bits = np.resize(np.asarray([
        0, 0x8000000000000000, 0x7FF0000000000000, 0xFFF0000000000000,
        0x7FF8000000000001, 0x7FF8000000000123, 1, 0x3FF0000000000001,
    ], dtype="<u8"), n)
    arrays = (bits.view("<f8"), bits[::-1].copy().view("<f8"))
    for array in arrays:
        array.flags.writeable = False
    buffers = tuple(
        LogicalBuffer(f"value/{index:06d}", array, array.nbytes * 8)
        for index, array in enumerate(arrays)
    )
    return RoutedInput(
        dataset_id="dataset:xz-adapter", track=BenchmarkTrack.VALUE, buffers=buffers,
        timestamp_reference=None, validity_reference=None, n=n, m=2,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("n", [0, 1, 2, 65535, 65536, 65537])
@pytest.mark.parametrize("level", [0, 6, 9])
def test_ieee_buffers_bound_tail_independent_decoder_and_accounting(n, level):
    adapter, _ = _adapter_and_manifest()
    routed = _route(n)
    result = perform_roundtrip(adapter, routed, {"compression_level": level})
    for item in routed.buffers:
        assert result.decoded.by_name()[item.name].array.tobytes() == item.array.tobytes()
    _, frame = XzStreamSession._parse_container(result.encoded.stream)
    payload = b"".join(item.array.tobytes() for item in routed.buffers)
    assert lzma.decompress(frame, format=lzma.FORMAT_XZ) == payload
    parts = XzStreamSession._inspect_xz_stream(frame, len(payload))
    ledger = result.encoded.ledger
    assert ledger.final_bits == len(result.encoded.stream) * 8
    assert ledger.index_bits == parts["index_bytes"] * 8 > 0
    assert ledger.checksum_bits == (96 if not n else 128)
    assert ledger.container_bits == 224
    assert ledger.value_bits == parts["payload_bytes"] * 8
    assert result.encoded.finalize_bytes == 0
    assert result.determinism_match and result.input_immutable and result.canary_intact
    session = adapter.create_session({})
    try:
        decoded = session.decompress(result.encoded.stream).by_name()["value/000000"]
        assert decoded.array.shape == (n,)
    finally:
        session.close()


def test_framework_boundary_suite():
    adapter, manifest = _adapter_and_manifest()
    report = run_boundary_suite(adapter, manifest, BenchmarkTrack.VALUE, {
        "block_size": 8, "compression_level": 6, "isa": "SCALAR",
    })
    assert report.passed, [item for item in report.observations if item.status != "PASS"]


@pytest.mark.parametrize(
    "mutation", ["truncated", "trailing", "concat", "header", "index", "footer"]
)
def test_native_decode_and_accounting_reject_malformed_streams(mutation):
    adapter, _ = _adapter_and_manifest()
    result = perform_roundtrip(adapter, _route(), {})
    container = result.encoded.stream
    _, frame = XzStreamSession._parse_container(container)
    prefix = container[:-len(frame)]
    offsets = {"header": 8, "index": -16, "footer": -12}
    damaged = bytearray(frame)
    if mutation in offsets:
        damaged[offsets[mutation]] ^= 1
    else:
        damaged = {
            "truncated": frame[:-1], "trailing": frame + b"x", "concat": frame + frame
        }[mutation]
    session = adapter.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.decompress(prefix + damaged)
        with pytest.raises(ExecutionContractError):
            XzStreamSession._inspect_xz_stream(bytes(damaged), 128)
    finally:
        session.close()


@pytest.mark.parametrize("level", [-1, 10])
def test_invalid_preset_rejected(level):
    adapter, _ = _adapter_and_manifest()
    with pytest.raises(ExecutionContractError):
        adapter.create_session({"compression_level": level})


def test_other_data_check_not_silently_accepted():
    adapter, _ = _adapter_and_manifest()
    result = perform_roundtrip(adapter, _route(), {})
    _, frame = XzStreamSession._parse_container(result.encoded.stream)
    prefix = result.encoded.stream[:-len(frame)]
    payload = b"".join(item.array.tobytes() for item in _route().buffers)
    checked = lzma.compress(payload, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32)
    session = adapter.create_session({})
    try:
        with pytest.raises(ExecutionContractError, match="not registered"):
            session.decompress(prefix + checked)
    finally:
        session.close()


def test_vendored_closure_digest():
    root = PROJECT_ROOT / "adapters/xz_stream/vendor/xz"
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    assert len(files) == 341
    assert digest.hexdigest() == "ef43c1771d2d12fdb35b9d53a15394f81da23770f97891d78f1e97e3504d3574"
