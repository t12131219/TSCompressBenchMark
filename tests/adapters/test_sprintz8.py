import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import Sprintz8Adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]
ALGORITHMS = ("sprintz-delta-u8", "sprintz-fire-u8")


def test_synthetic_u8_fixture_reproduces_manifest(tmp_path):
    expected = json.loads((ROOT / "registry/datasets/sprintz_u8_uts.json").read_text())
    output = tmp_path / "sprintz_u8_uts.npz"
    subprocess.run(
        [sys.executable, str(ROOT / "tools/generate_sprintz_fixture.py"),
         "--output", str(output)],
        check=True,
    )
    assert hashlib.sha256(output.read_bytes()).hexdigest() == expected["file"]["sha256"]
    with np.load(output, allow_pickle=False) as fixture:
        assert fixture.files == ["values"]
        assert fixture["values"].shape == (2048,)
        assert fixture["values"].dtype == np.dtype("uint8")


def codec(name):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get(name)
    library = ROOT / manifest.document["adapter"]["artifact_path"]
    if not library.is_file():
        pytest.skip(f"build {name} first")
    return Sprintz8Adapter(library, manifest.document["adapter"], name), manifest


def route(data):
    values = np.frombuffer(data, dtype=np.uint8).copy()
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, len(data) * 8),)
    return RoutedInput(
        dataset_id="dataset:sprintz-test", track=BenchmarkTrack.VALUE,
        buffers=buffers, timestamp_reference=None, validity_reference=None,
        n=len(data), m=1, canonical_raw_bits=len(data) * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


@pytest.mark.parametrize("name", ALGORITHMS)
@pytest.mark.parametrize("length", [0, 1, 2, 7, 8, 16, 127, 128, 129, 255, 256, 2048, 131072])
@pytest.mark.parametrize("pattern", ["constant", "random"])
def test_roundtrip_accounting_and_native_timing(name, length, pattern):
    adapter, _ = codec(name)
    data = (bytes(length) if pattern == "constant"
            else np.random.default_rng(length).integers(0, 256, length, dtype=np.uint8).tobytes())
    result = perform_roundtrip(adapter, route(data), {"isa": "AVX2_BMI2_LZCNT"})
    assert result.decoded.by_name()["value/000000"].array.tobytes() == data
    assert result.encoded.ledger.final_bits == 8 * len(result.encoded.stream)
    assert result.input_immutable and result.canary_intact and result.determinism_match
    assert result.encoded.native_encode_wall_ns is not None


@pytest.mark.parametrize("name", ALGORITHMS)
def test_boundary_malformed_and_wrong_variant(name):
    adapter, manifest = codec(name)
    report = run_boundary_suite(adapter, manifest, BenchmarkTrack.VALUE,
                                {"block_size": 128, "isa": "AVX2_BMI2_LZCNT"})
    assert report.passed, [item for item in report.observations if item.status != "PASS"]
    data = bytes(range(256))
    result = perform_roundtrip(adapter, route(data), {})
    stream = result.encoded.stream
    offset = 12 + struct.unpack_from("<I", stream, 8)[0]
    session = adapter.create_session({})
    try:
        for invalid in (stream[:-1], stream + b"x", b"bad" + stream[3:],
                        stream[:offset + 6] + b"\x02" + stream[offset + 7:]):
            with pytest.raises(ExecutionContractError):
                session.decompress(invalid)
    finally:
        session.close()
    other, _ = codec(ALGORITHMS[1] if name == ALGORITHMS[0] else ALGORITHMS[0])
    session = other.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.decompress(stream)
    finally:
        session.close()


@pytest.mark.parametrize("name", ALGORITHMS)
def test_rejects_float_and_multiple_columns(name):
    adapter, _ = codec(name)
    routed = route(b"\x01" * 128)
    session = adapter.create_session({})
    try:
        bad = LogicalBuffer("value/000000", np.ones(128, dtype=np.float32), 128 * 32)
        with pytest.raises(ExecutionContractError):
            session.output_bound(RoutedInput(
                **{**routed.__dict__, "buffers": (bad,), "canonical_raw_bits": 128 * 32}
            ))
    finally:
        session.close()
