from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import ZstdFrameAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import run_boundary_suite

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = PROJECT_ROOT / "build/adapters/zstd_frame/release/libtscb_zstd_frame.so"


def _ensure_library() -> None:
    if LIBRARY.is_file():
        return
    subprocess.run(
        [sys.executable, "tools/build_codec.py", "zstd-frame", "--profile", "release"],
        cwd=PROJECT_ROOT,
        check=True,
    )


def _adapter_and_manifest():
    _ensure_library()
    sources = SourceRegistry(PROJECT_ROOT / "registry/sources")
    manifest = CodecRegistry(PROJECT_ROOT / "registry/codecs", sources).get("zstd-frame")
    return ZstdFrameAdapter(LIBRARY, manifest.document["adapter"]), manifest


@pytest.mark.parametrize("content_checksum", [False, True])
def test_zstd_frame_round_trip_preserves_multiple_buffers_and_ieee_bits(
    content_checksum: bool,
) -> None:
    adapter, _ = _adapter_and_manifest()
    first = np.asarray([0.0, -0.0, np.inf, -np.inf], dtype="<f8")
    second_bits = np.asarray(
        [0x7FF8000000000001, 0x7FF8000000000123, 0x0000000000000001, 0x3FF0000000000001],
        dtype="<u8",
    )
    second = second_bits.view("<f8")
    first.flags.writeable = False
    second.flags.writeable = False
    buffers = (
        LogicalBuffer("value/000000", first, first.nbytes * 8),
        LogicalBuffer("value/000001", second, second.nbytes * 8),
    )
    routed = RoutedInput(
        dataset_id="v2:dataset:zstd-adapter-test",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=4,
        m=2,
        canonical_raw_bits=sum(item.logical_bits for item in buffers),
        input_sha256=hash_logical_buffers(buffers),
    )
    observation = perform_roundtrip(
        adapter,
        routed,
        {
            "block_size": 4,
            "compression_level": 3,
            "content_checksum": content_checksum,
            "isa": "SCALAR",
        },
    )
    decoded = observation.decoded.by_name()
    assert decoded["value/000000"].array.view("<u8").tolist() == first.view("<u8").tolist()
    assert decoded["value/000001"].array.view("<u8").tolist() == second_bits.tolist()
    assert observation.encoded.finalize_bytes > 0
    assert observation.encoded.ledger.final_bits == len(observation.encoded.stream) * 8
    assert observation.encoded.ledger.checksum_bits == (32 if content_checksum else 0)
    assert observation.encoded.ledger.accounting_method == (
        "EXACT_TSCB_CONTAINER_AND_ZSTD_FRAME_INSPECTION"
    )
    assert observation.determinism_match is True
    assert observation.input_immutable
    assert observation.canary_intact


def test_zstd_frame_passes_framework_boundary_suite() -> None:
    adapter, manifest = _adapter_and_manifest()
    report = run_boundary_suite(
        adapter,
        manifest,
        BenchmarkTrack.VALUE,
        {
            "block_size": 8,
            "compression_level": 3,
            "content_checksum": True,
            "isa": "SCALAR",
        },
    )
    assert report.passed, [item for item in report.observations if item.status != "PASS"]
