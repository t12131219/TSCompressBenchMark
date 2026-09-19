from __future__ import annotations

import hashlib
import subprocess
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import DeflateZlibAdapter
from tscompbench.adapters.deflate_zlib import _PREFIX, DeflateZlibSession
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import run_boundary_suite

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = PROJECT_ROOT / "build/adapters/deflate_zlib/release/libtscb_deflate_zlib.so"


def _adapter_and_manifest():
    if not LIBRARY.is_file():
        subprocess.run(
            [sys.executable, "tools/build_codec.py", "deflate-zlib", "--profile", "release"],
            cwd=PROJECT_ROOT, check=True,
        )
    sources = SourceRegistry(PROJECT_ROOT / "registry/sources")
    manifest = CodecRegistry(PROJECT_ROOT / "registry/codecs", sources).get("deflate-zlib")
    return DeflateZlibAdapter(LIBRARY, manifest.document["adapter"]), manifest


def _route(n=4):
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
        dataset_id="dataset:deflate-adapter", track=BenchmarkTrack.VALUE, buffers=buffers,
        timestamp_reference=None, validity_reference=None, n=n, m=2,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )


def test_multiple_buffers_ieee_bits_envelope_and_external_decoder():
    adapter, _ = _adapter_and_manifest()
    routed = _route(8)
    result = perform_roundtrip(adapter, routed, {})
    for item in routed.buffers:
        assert result.decoded.by_name()[item.name].array.tobytes() == item.array.tobytes()
    header, stream = DeflateZlibSession._parse_container(result.encoded.stream)
    payload = b"".join(item.array.tobytes() for item in routed.buffers)
    assert zlib.decompress(stream) == payload
    assert int.from_bytes(stream[-4:], "big") == zlib.adler32(payload)
    ledger = result.encoded.ledger
    assert ledger.final_bits == len(result.encoded.stream) * 8
    assert ledger.container_bits == (_PREFIX.size + 2) * 8
    assert ledger.checksum_bits == 32
    assert ledger.value_bits == (len(stream) - 6) * 8
    assert ledger.accounting_method == "EXACT_TSCB_CONTAINER_ZLIB_ENVELOPE_AND_DEFLATE_LENGTH"
    assert header["schema_version"] == "tscb.deflate-zlib-container.v1"
    assert result.encoded.finalize_bytes > 0
    assert result.determinism_match and result.input_immutable and result.canary_intact


@pytest.mark.parametrize("level", range(10))
@pytest.mark.parametrize("window", [9, 15])
@pytest.mark.parametrize("n", [0, 1, 2, 65537])
def test_bound_tails_and_parameter_extremes(level, window, n):
    adapter, _ = _adapter_and_manifest()
    result = perform_roundtrip(
        adapter, _route(n), {"compression_level": level, "window_bits": window}
    )
    _, stream = DeflateZlibSession._parse_container(result.encoded.stream)
    assert stream[0] >> 4 == window - 8
    assert result.determinism_match and result.canary_intact


def test_framework_boundary_suite():
    adapter, manifest = _adapter_and_manifest()
    report = run_boundary_suite(
        adapter, manifest, BenchmarkTrack.VALUE,
        {"block_size": 8, "compression_level": 6, "window_bits": 15, "isa": "SCALAR"},
    )
    assert report.passed, [item for item in report.observations if item.status != "PASS"]


@pytest.mark.parametrize(
    "mutation", ["truncated", "trailing", "concatenated", "checksum", "header"]
)
def test_independent_decoder_rejects_nonexact_or_corrupt_streams(mutation):
    adapter, _ = _adapter_and_manifest()
    result = perform_roundtrip(adapter, _route(), {})
    container = result.encoded.stream
    _, stream = DeflateZlibSession._parse_container(container)
    prefix = container[:-len(stream)]
    altered = {
        "truncated": stream[:-1], "trailing": stream + b"x",
        "concatenated": stream + stream,
        "checksum": stream[:-1] + bytes([stream[-1] ^ 1]),
        "header": bytes([stream[0] ^ 1]) + stream[1:],
    }[mutation]
    session = adapter.create_session({})
    try:
        assert session.decompress(container).by_name()["value/000000"].array.shape == (4,)
        with pytest.raises(ExecutionContractError):
            session.decompress(prefix + altered)
    finally:
        session.close()


@pytest.mark.parametrize("parameters", [
    {"compression_level": -1}, {"compression_level": 10},
    {"window_bits": 8}, {"window_bits": 16},
])
def test_invalid_parameters_rejected(parameters):
    adapter, _ = _adapter_and_manifest()
    with pytest.raises(ExecutionContractError):
        adapter.create_session(parameters)


def test_vendored_closure_digest():
    root = PROJECT_ROOT / "adapters/deflate_zlib/vendor/zlib"
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    assert len(files) == 48
    assert digest.hexdigest() == "90abdcdbb1d1670afd5b5ca06827f2bb7aedd2e10469b6ceaae90e08d455f7c0"
