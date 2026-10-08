from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.factory import create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.codecs.onboarding import validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import (
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
    SourceDomainError,
)
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers, hash_reference_array
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]
KEYS = (
    "streamvbyte-u32",
    "delta-zigzag-streamvbyte64",
    "streamvbyte-modern-u32",
    "delta-zigzag-streamvbyte-modern64",
)


def registry() -> CodecRegistry:
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))


def routed(values: np.ndarray, key: str) -> RoutedInput:
    delta = key.startswith("delta-")
    values.flags.writeable = False
    timestamp = values if delta else None
    item = LogicalBuffer("timestamp" if delta else "value/0", values, values.nbytes * 8)
    return RoutedInput(
        dataset_id="v2:dataset:streamvbyte-test",
        track=BenchmarkTrack.TIMESTAMP if delta else BenchmarkTrack.VALUE,
        buffers=(item,),
        timestamp_reference=timestamp,
        validity_reference=None,
        n=values.size,
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers((item,)),
        pairing_reference_sha256=hash_reference_array(timestamp),
        timestamp_unit="ns" if delta else "UNSPECIFIED",
        timestamp_epoch="UNIX" if delta else "UNSPECIFIED",
        value_units=() if delta else ("count",),
    )


@pytest.mark.parametrize("key", KEYS)
def test_onboarding_contract(key: str) -> None:
    card = json.loads((ROOT / f"registry/onboarding/{key}.json").read_text())
    assert validate_onboarding_card(card)["source_onboarding_id"]


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 31, 32, 33, 127, 128, 129, 1000, 8193])
def test_roundtrip_preserves_bits_and_exact_ledger(key: str, n: int) -> None:
    rng = np.random.default_rng(20261007 + n)
    values = (
        np.arange(n, dtype="<i8") * 3600000000000 + 1700000000123456789
        if key.startswith("delta-")
        else rng.integers(0, 2**32, n, dtype="<u4")
    )
    observation = perform_roundtrip(
        create_adapter(ROOT, registry().get(key)), routed(values, key), {}
    )
    actual = observation.decoded.buffers[0].array
    assert actual.dtype == values.dtype and actual.tobytes() == values.tobytes()
    assert observation.input_immutable and observation.canary_intact
    assert observation.determinism_match
    ledger = observation.encoded.ledger
    assert ledger.final_bits == 8 * len(observation.encoded.stream)
    assert ledger.canonical_raw_bits == values.nbytes * 8
    assert ledger.timestamp_bits == 0 if not key.startswith("delta-") else ledger.value_bits == 0
    assert observation.encoded.finalize_bytes == 0
    assert observation.timing.native_encode_wall_ns is not None
    assert observation.timing.native_decode_wall_ns is not None
    assert observation.codec_telemetry["encode"]["internal_padding_bytes"] == 16
    assert observation.codec_telemetry["decode"]["padding_stream_bits"] == 0


@pytest.mark.parametrize("key", KEYS)
def test_native_timing_switch_keeps_stream_and_fresh_decode(key: str) -> None:
    values = np.array(
        [0, 1, 1, 255, 256, 65535, 65536, 2**31], dtype="<i8" if key.startswith("delta-") else "<u4"
    )
    adapter = create_adapter(ROOT, registry().get(key))
    on = perform_roundtrip(adapter, routed(values, key), {"native_timing": True})
    off = perform_roundtrip(adapter, routed(values, key), {"native_timing": False})
    assert on.encoded.stream == off.encoded.stream
    assert off.timing.native_encode_wall_ns is None and off.timing.native_decode_wall_ns is None
    session = adapter.create_session({})
    try:
        assert session.native_timing() == (0, 0)
        session.decompress(on.encoded.stream)
        first = session.native_timing()
        assert first == session.native_timing()
        session.decompress(on.encoded.stream)
        assert session.native_timing()[1] >= first[1]
    finally:
        session.close()
        session.close()


@pytest.mark.parametrize("key", (KEYS[1], KEYS[3]))
def test_delta64_extremes_duplicates_negative_and_out_of_order(key: str) -> None:
    vectors = (
        [-(2**63), -(2**63) + 1, -(2**63) + 1, -(2**63) + 2],
        [2**63 - 1, 2**63 - 2, 2**63 - 2],
        [-(2**63), -1, -1, 0, 2**63 - 1],
        [2**63 - 1, 0, -(2**63), -1],
        [0, -100, -100, 123, -7],
    )
    adapter = create_adapter(ROOT, registry().get(key))
    for vector in vectors:
        values = np.array(vector, dtype="<i8")
        observation = perform_roundtrip(adapter, routed(values, key), {})
        assert observation.decoded.buffers[0].array.tobytes() == values.tobytes()


@pytest.mark.parametrize("key", (KEYS[1], KEYS[3]))
@pytest.mark.parametrize("vector", [[-(2**63), 2**63 - 1], [2**63 - 1, -(2**63)]])
def test_delta_overflow_rejects_before_output_and_remains_usable(
    vector: list[int], key: str
) -> None:
    adapter = create_adapter(ROOT, registry().get(key))
    session = adapter.create_session({})
    try:
        item = routed(np.array(vector, dtype="<i8"), key)
        output = bytearray(b"\xa5" * session.output_bound(item))
        with pytest.raises(SourceDomainError, match="checked int64 delta overflow") as error:
            session.compress_update(item, memoryview(output))
        assert error.value.rejection_atomic and output == b"\xa5" * len(output)
        valid = routed(np.array([0, 1], dtype="<i8"), key)
        output = bytearray(session.output_bound(valid))
        assert session.compress_update(valid, memoryview(output)) > 0
        assert session.finalize(memoryview(bytearray())) == 0
    finally:
        session.close()


@pytest.mark.parametrize("key", KEYS)
def test_short_capacity_lifecycle_and_corrupt_streams(key: str) -> None:
    adapter = create_adapter(ROOT, registry().get(key))
    item = routed(
        np.array([0, 1, 255, 2**31], dtype="<i8" if key.startswith("delta-") else "<u4"), key
    )
    session = adapter.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.finalize(memoryview(bytearray()))
        bound = session.output_bound(item)
        short = bytearray(b"\xa5" * (bound - 1))
        with pytest.raises(OutputCapacityError):
            session.compress_update(item, memoryview(short))
        assert short == b"\xa5" * len(short)
        destination = bytearray(bound)
        size = session.compress_update(item, memoryview(destination))
        with pytest.raises(ExecutionContractError):
            session.compress_update(item, memoryview(destination))
        assert session.finalize(memoryview(bytearray())) == 0
        with pytest.raises(ExecutionContractError):
            session.finalize(memoryview(bytearray()))
        stream = bytes(destination[:size])
        bad_header = bytearray(stream)
        bad_header[44] ^= 1
        header_len = struct.unpack_from("<I", stream, 8)[0]
        bad_count = bytearray(stream)
        bad_count[44 + header_len + (20 if key.startswith("delta-") else 0)] ^= 1
        for bad in (stream[:1], stream[:-1], stream + b"\0", bytes(bad_header), bytes(bad_count)):
            decoder = adapter.create_session({})
            try:
                with pytest.raises(ExecutionContractError):
                    decoder.decompress(bad)
            finally:
                decoder.close()
    finally:
        session.close()


@pytest.mark.parametrize("key", KEYS)
def test_full_framework_boundary_suite(key: str) -> None:
    manifest = registry().get(key)
    report = run_boundary_suite(
        create_adapter(ROOT, manifest),
        manifest,
        BenchmarkTrack.TIMESTAMP if key.startswith("delta-") else BenchmarkTrack.VALUE,
        {},
    )
    failures = [
        (item.case_id, item.reason) for item in report.observations if item.status != "PASS"
    ]
    assert report.passed, failures


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("target", ["source", "binding", "artifact", "command", "compiled"])
def test_execution_rejects_source_binding_binary_and_command_drift(
    tmp_path: Path, target: str, key: str
) -> None:
    import shutil

    from tscompbench.adapters.factory import AdapterFactoryError, adapter_artifacts

    manifest = registry().get(key)
    artifact, supports = adapter_artifacts(ROOT, manifest)
    for original in (artifact, *supports):
        destination = tmp_path / original.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, destination)
    adapter_artifacts(tmp_path, manifest)
    changed = {
        "source": (
            "adapters/streamvbyte_modern/vendor/streamvbyte/src/streamvbyte_encode.c"
            if "modern" in key
            else "adapters/streamvbyte/vendor/fastpfor/streamvbyte.c"
        ),
        "compiled": (
            str((artifact.parent / "streamvbyte/src/streamvbyte_x64_encode.c").relative_to(ROOT))
            if "modern" in key
            else str((artifact.parent / "fastpfor/streamvbyte.c").relative_to(ROOT))
        ),
        "binding": "adapters/streamvbyte/native/tscb_streamvbyte.c",
        "artifact": str(artifact.relative_to(ROOT)),
        "command": str((artifact.parent / "compile-command.json").relative_to(ROOT)),
    }[target]
    path = tmp_path / changed
    if target == "command":
        command = json.loads(path.read_text())
        command["command"].append("-O0")
        path.write_text(json.dumps(command))
    else:
        path.write_bytes(path.read_bytes() + b"\nDRIFT\n")
    with pytest.raises(AdapterFactoryError, match="drift"):
        adapter_artifacts(tmp_path, manifest)


@pytest.mark.parametrize("key", (KEYS[0], KEYS[2]))
def test_oversized_descriptor_rejects_before_output(key: str) -> None:
    from dataclasses import replace

    item = replace(routed(np.array([1], dtype="<u4"), key), value_units=("x" * 4096,))
    session = create_adapter(ROOT, registry().get(key)).create_session({})
    try:
        output = bytearray(b"\xa5" * 8192)
        with pytest.raises(ExecutionContractError, match="descriptor exceeds"):
            session.compress_update(item, memoryview(output))
        assert output == b"\xa5" * 8192
    finally:
        session.close()
