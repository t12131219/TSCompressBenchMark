from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

from tscompbench.adapters import DeltaVarintAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers, hash_reference_array

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "build/adapters/delta_varint/release/libtscb_delta_varint.so"


def _adapter() -> DeltaVarintAdapter:
    if not LIBRARY.is_file():
        subprocess.run(
            [sys.executable, "tools/build_codec.py", "delta-varint", "--profile", "release"],
            cwd=ROOT, check=True,
        )
    sources = SourceRegistry(ROOT / "registry/sources")
    manifest = CodecRegistry(ROOT / "registry/codecs", sources).get("delta-varint")
    return DeltaVarintAdapter(LIBRARY, manifest.document["adapter"])


def _routed(values: np.ndarray) -> RoutedInput:
    values = np.asarray(values, dtype="<i8")
    values.flags.writeable = False
    item = LogicalBuffer("timestamp", values, values.nbytes * 8)
    return RoutedInput(
        dataset_id="v2:dataset:delta-varint-test",
        track=BenchmarkTrack.TIMESTAMP,
        buffers=(item,),
        timestamp_reference=values,
        validity_reference=None,
        n=values.size,
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers((item,)),
        pairing_reference_sha256=hash_reference_array(values),
    )


def test_delta_varint_round_trip_and_exact_accounting() -> None:
    observation = perform_roundtrip(
        _adapter(),
        _routed(np.asarray([0, 1, 1, -100, 2**63 - 1, -2**63], dtype="<i8")),
        {"isa": "SCALAR", "native_timing": True},
    )
    decoded = observation.decoded.by_name()["timestamp"].array
    assert decoded.tolist() == [0, 1, 1, -100, 2**63 - 1, -2**63]
    assert observation.encoded.ledger.final_bits == len(observation.encoded.stream) * 8
    assert observation.encoded.ledger.timestamp_bits > 0
    assert observation.encoded.finalize_bytes == 0
    assert observation.encoded.native_encode_wall_ns is not None
    assert observation.encoded.native_encode_wall_ns > 0
    assert observation.input_immutable and observation.canary_intact


def test_delta_varint_supports_empty_and_expansion_without_false_capacity() -> None:
    observation = perform_roundtrip(_adapter(), _routed(np.asarray([], dtype="<i8")), {
        "isa": "SCALAR", "native_timing": False,
    })
    assert observation.decoded.by_name()["timestamp"].array.size == 0
    assert observation.encoded.ledger.timestamp_bits == 0
    assert observation.encoded.ledger.final_physical_bytes == len(observation.encoded.stream)
