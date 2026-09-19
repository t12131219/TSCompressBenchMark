from __future__ import annotations

import bz2
import hashlib
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import Bzip2StreamAdapter
from tscompbench.adapters.bzip2_stream import Bzip2StreamSession
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import run_boundary_suite

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = PROJECT_ROOT / "build/adapters/bzip2_stream/release/libtscb_bzip2_stream.so"


def _adapter_and_manifest():
    if not LIBRARY.is_file():
        subprocess.run(
            [sys.executable, "tools/build_codec.py", "bzip2-stream", "--profile", "release"],
            cwd=PROJECT_ROOT,
            check=True,
        )
    sources = SourceRegistry(PROJECT_ROOT / "registry/sources")
    manifest = CodecRegistry(PROJECT_ROOT / "registry/codecs", sources).get("bzip2-stream")
    return Bzip2StreamAdapter(LIBRARY, manifest.document["adapter"]), manifest


def _route(n: int = 4) -> RoutedInput:
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
    arrays = (bits.view("<f8"), bits[::-1].copy().view("<f8"))
    for array in arrays:
        array.flags.writeable = False
    buffers = tuple(
        LogicalBuffer(f"value/{index:06d}", array, array.nbytes * 8)
        for index, array in enumerate(arrays)
    )
    return RoutedInput(
        dataset_id="dataset:bzip2-adapter",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=n,
        m=2,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("level", [1, 5, 9])
def test_ieee_bits_accounting_and_external_decoder(level):
    adapter, _ = _adapter_and_manifest()
    routed = _route(100_001 if level == 1 else 257)
    result = perform_roundtrip(adapter, routed, {"compression_level": level})
    header, frame = Bzip2StreamSession._parse_container(result.encoded.stream)
    expected = b"".join(item.array.tobytes(order="C") for item in routed.buffers)
    assert frame.startswith(b"BZh" + str(level).encode("ascii"))
    assert bz2.decompress(frame) == expected
    assert header["schema_version"] == "tscb.bzip2-stream-container.v1"
    assert result.encoded.ledger.final_physical_bytes == len(result.encoded.stream)
    assert result.encoded.ledger.value_bits == len(frame) * 8
    assert result.encoded.ledger.serialized_bits == len(result.encoded.stream) * 8
    assert result.determinism_match and result.canary_intact


def test_framework_boundary_suite():
    adapter, manifest = _adapter_and_manifest()
    report = run_boundary_suite(
        adapter,
        manifest,
        BenchmarkTrack.VALUE,
        {"block_size": 8, "compression_level": 1, "isa": "SCALAR"},
    )
    assert report.passed, [item for item in report.observations if item.status != "PASS"]


@pytest.mark.parametrize(
    "mutation", ["truncated", "trailing", "concatenated", "crc", "header"]
)
def test_decoder_rejects_nonexact_or_corrupt_streams(mutation):
    adapter, _ = _adapter_and_manifest()
    result = perform_roundtrip(adapter, _route(32), {"compression_level": 9})
    container = result.encoded.stream
    _, frame = Bzip2StreamSession._parse_container(container)
    prefix = container[: -len(frame)]
    altered = {
        "truncated": frame[:-1],
        "trailing": frame + b"x",
        "concatenated": frame + frame,
        "crc": frame[:-5] + bytes([frame[-5] ^ 1]) + frame[-4:],
        "header": frame[:3] + b"1" + frame[4:],
    }[mutation]
    session = adapter.create_session({"compression_level": 9})
    try:
        assert session.decompress(container).by_name()["value/000000"].array.shape == (32,)
        with pytest.raises(ExecutionContractError):
            session.decompress(prefix + altered)
    finally:
        session.close()


@pytest.mark.parametrize("level", [0, 10])
def test_invalid_compression_level_rejected(level):
    adapter, _ = _adapter_and_manifest()
    with pytest.raises(ExecutionContractError):
        adapter.create_session({"compression_level": level})


def test_vendored_closure_digest():
    root = PROJECT_ROOT / "adapters/bzip2_stream/vendor/bzip2"
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes())
    assert len(files) == 12
    assert digest.hexdigest() == "eda9be9e525b9ea675c7574c46d7fa92c4a07fe493d7f6d34714614c8a650cc4"
