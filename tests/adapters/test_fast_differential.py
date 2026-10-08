from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.fast_differential import FastDifferentialAdapter
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import (
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
)
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
PREFIX = struct.Struct("<8sI32s")


def adapter() -> FastDifferentialAdapter:
    # Direct SDK qualification precedes factory/registry/five-layer admission.
    return FastDifferentialAdapter(
        ROOT / "build/adapters/fast_differential_u32/release/libtscb_fast_differential_u32.so",
        {"backend": "C_ABI_V1", "version": "fast-differential-ctypes-v1"},
    )


def routed(values: np.ndarray) -> RoutedInput:
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    return RoutedInput(
        dataset_id="v2:dataset:fast-differential-test",
        track=BenchmarkTrack.VALUE,
        buffers=(item,),
        timestamp_reference=None,
        validity_reference=None,
        n=values.size,
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers((item,)),
        value_units=("count",),
    )


def split(stream: bytes) -> tuple[dict, bytes]:
    _, length, _ = PREFIX.unpack_from(stream)
    return json.loads(stream[PREFIX.size : PREFIX.size + length]), stream[PREFIX.size + length :]


@pytest.mark.parametrize("mode", ["DISTINCT", "INPLACE"])
@pytest.mark.parametrize("seed", [0, 1, 2**31, 2**32 - 1])
@pytest.mark.parametrize("n", [0, 1, 3, 4, 5, 31, 32, 33, 1000, 8193])
def test_sdk_roundtrip_original_words_and_exact_ledger(mode: str, seed: int, n: int) -> None:
    rng = np.random.default_rng(20261007 + n)
    values = rng.integers(0, 2**32, n, dtype="<u4")
    params = {"api_mode": mode, "starting_point": seed}
    observation = perform_roundtrip(adapter(), routed(values), params)
    assert observation.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert (
        observation.input_immutable and observation.canary_intact and observation.determinism_match
    )
    info, frame = split(observation.encoded.stream)
    # Mathematical unsigned D1 oracle, independent of the source and adapter implementation.
    previous = seed
    expected = []
    for value in values:
        expected.append((int(value) - previous) % 2**32)
        previous = int(value)
    assert frame[24:-8] == np.array(expected, dtype="<u4").tobytes()
    assert info["parameters"] == {"api_mode": mode, "isa": "SSE4_1", "starting_point": seed}
    assert observation.encoded.finalize_bytes == 0
    ledger = observation.encoded.ledger
    assert ledger.final_bits == 8 * len(observation.encoded.stream)
    assert ledger.value_bits == values.nbytes * 8
    assert ledger.timestamp_bits == 0 and ledger.external_side_information_bits == 0
    assert ledger.final_physical_bytes > values.nbytes  # A P0 transform preserves payload size.
    assert observation.timing.native_encode_wall_ns is not None
    assert observation.timing.native_decode_wall_ns is not None
    for phase in ("encode", "decode"):
        telemetry = observation.codec_telemetry[phase]
        assert telemetry["api_mode"] == mode
        assert telemetry["native_staging_allocation_bytes"] == 4 * max(n, 1) * (
            1 if mode == "INPLACE" else 2
        )
        assert telemetry["native_staging_input_copy_bytes"] == values.nbytes
        assert telemetry["native_staging_output_copy_bytes"] == values.nbytes
        assert telemetry["internal_padding_bytes"] == 0


@pytest.mark.parametrize("mode", ["DISTINCT", "INPLACE"])
def test_fresh_decode_uses_serialized_mode_and_seed_and_timer_is_optional(mode: str) -> None:
    item = routed(np.array([2**32 - 1, 0, 1, 0, 2**31], dtype="<u4"))
    params = {"api_mode": mode, "starting_point": 2**32 - 1}
    on = perform_roundtrip(adapter(), item, params)
    off = perform_roundtrip(adapter(), item, {**params, "native_timing": False})
    assert on.encoded.stream == off.encoded.stream
    assert off.timing.native_encode_wall_ns is None and off.timing.native_decode_wall_ns is None
    session = adapter().create_session(
        {"api_mode": "INPLACE" if mode == "DISTINCT" else "DISTINCT"}
    )
    try:
        assert session.native_timing() == (0, 0)
        assert (
            session.decompress(on.encoded.stream).buffers[0].array.tobytes()
            == item.buffers[0].array.tobytes()
        )
        assert session.codec_telemetry()["api_mode"] == mode
        first = session.native_timing()
        assert first == session.native_timing()
        session.decompress(on.encoded.stream)
        assert session.native_timing()[1] >= first[1]
        session.reset()
        assert session.native_timing() == (0, 0)
    finally:
        session.close()
        session.close()
    with pytest.raises(ExecutionContractError, match="closed"):
        session.native_timing()
    with pytest.raises(ExecutionContractError, match="closed"):
        session.output_bound(item)


@pytest.mark.parametrize("mode", ["DISTINCT", "INPLACE"])
@pytest.mark.parametrize("layout", ["strided", "reversed", "misaligned"])
def test_layout_materialization_preserves_bits(mode: str, layout: str) -> None:
    source = np.arange(65, dtype="<u4") * 1234567
    if layout == "strided":
        values = source[::2]
    elif layout == "reversed":
        values = source[::-1]
    else:
        storage = bytearray(1 + source.nbytes)
        values = np.ndarray(source.shape, dtype="<u4", buffer=storage, offset=1)
        values[:] = source
    observation = perform_roundtrip(adapter(), routed(values), {"api_mode": mode})
    assert observation.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert observation.input_immutable and observation.canary_intact
    assert observation.codec_telemetry["encode"]["gather_bytes"] == (
        values.nbytes if layout != "misaligned" else 0
    )


@pytest.mark.parametrize("mode", ["DISTINCT", "INPLACE"])
def test_capacity_alias_reset_and_atomic_lifecycle(mode: str) -> None:
    session = adapter().create_session({"api_mode": mode, "starting_point": 2**32 - 1})
    item = routed(np.array([0, 2**32 - 1, 1, 0], dtype="<u4"))
    try:
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        capacity = session.output_bound(item)
        short = bytearray(b"\xa5" * (capacity - 1))
        with pytest.raises(OutputCapacityError):
            session.compress_update(item, memoryview(short))
        assert short == b"\xa5" * len(short)
        storage = bytearray(b"\xa5" * 1024)
        aliased_input = routed(np.ndarray((4,), dtype="<u4", buffer=storage))
        before = bytes(storage)
        with pytest.raises(ExecutionContractError, match="alias"):
            session.compress_update(aliased_input, memoryview(storage))
        assert bytes(storage) == before
        destination = bytearray(capacity)
        used = session.compress_update(item, memoryview(destination))
        stream = bytes(destination[:used])
        with pytest.raises(ExecutionContractError, match="accounting before finalize"):
            session.accounting(stream, item)
        with pytest.raises(ExecutionContractError, match="update lifecycle"):
            session.compress_update(item, memoryview(destination))
        assert session.finalize(memoryview(bytearray())) == 0
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        assert session.accounting(stream, item).final_bits == len(stream) * 8
        changed = bytearray(stream)
        changed[-1] ^= 1
        with pytest.raises(ExecutionContractError, match="object changed"):
            session.accounting(bytes(changed), item)
        session.reset()
        used = session.compress_update(item, memoryview(destination))
        assert bytes(destination[:used]) == stream
    finally:
        session.close()


@pytest.mark.parametrize("mode", ["DISTINCT", "INPLACE"])
def test_corruption_and_forged_descriptor_rejected(mode: str) -> None:
    stream = perform_roundtrip(
        adapter(), routed(np.array([1, 0, 1], dtype="<u4")), {"api_mode": mode}
    ).encoded.stream
    info, frame = split(stream)
    corrupted = bytearray(frame)
    corrupted[24] ^= 1
    _, size, _ = PREFIX.unpack_from(stream)
    bad = [stream[:1], stream[:-1], stream + b"\0", stream[: PREFIX.size + size] + corrupted]
    for field, value in (
        ("count", True),
        ("count", -1),
        ("count", 16777217),
        ("track", "TIMESTAMP"),
        ("algorithm", "streamvbyte-u32"),
        ("value_units", [0]),
    ):
        modified = {**info, field: value}
        header = canonical_json_bytes(modified)
        bad.append(
            PREFIX.pack(b"TSCBFDP1", len(header), hashlib.sha256(header).digest()) + header + frame
        )
    for modified in (
        {**info, "parameters": {**info["parameters"], "starting_point": 7}},
        {**info, "parameters": {**info["parameters"], "starting_point": True}},
        {**info, "buffer": {**info["buffer"], "shape": [True]}},
        {**info, "buffer": {**info["buffer"], "dtype": "<i8"}},
        {**info, "buffer": {**info["buffer"], "logical_bits": 0}},
    ):
        header = canonical_json_bytes(modified)
        bad.append(
            PREFIX.pack(b"TSCBFDP1", len(header), hashlib.sha256(header).digest()) + header + frame
        )
    # A recomputed SHA does not make a noncanonical/duplicated JSON descriptor valid.
    header = stream[PREFIX.size : PREFIX.size + size].replace(
        b'{"algorithm"', b'{"extra":0,"algorithm"'
    )
    bad.append(
        PREFIX.pack(b"TSCBFDP1", len(header), hashlib.sha256(header).digest()) + header + frame
    )
    for malformed in bad:
        session = adapter().create_session({})
        try:
            with pytest.raises(ExecutionContractError):
                session.decompress(bytes(malformed))
        finally:
            session.close()


@pytest.mark.parametrize(
    "parameters",
    [
        {"starting_point": True},
        {"starting_point": -1},
        {"starting_point": 2**32},
        {"api_mode": "OTHER"},
        {"isa": "SCALAR"},
        {"native_timing": 1},
        {"unexpected": 0},
    ],
)
def test_invalid_parameters_reject(parameters: dict) -> None:
    with pytest.raises(ExecutionContractError):
        adapter().create_session(parameters)


@pytest.mark.parametrize("dtype", ["<i8", "<f4", "<f8", ">u4"])
def test_no_implicit_timestamp_float_or_endian_conversion(dtype: str) -> None:
    session = adapter().create_session({})
    try:
        item = routed(np.array([0, 1], dtype=dtype))
        with pytest.raises(ExecutionContractError, match="dtype"):
            session.output_bound(item)
    finally:
        session.close()
