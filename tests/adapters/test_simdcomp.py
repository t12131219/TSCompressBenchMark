"""Direct SDK qualification before registry and five-layer admission."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.simdcomp import SIMDCompAdapter
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
CONFIGS = [
    ("simdcomp-u32", {"api": "LENGTH"}, 0),
    ("simdcomp-u32", {"api": "MASKED"}, 0),
    ("simdcomp-u32", {"api": "WITHOUTMASK"}, 0),
    ("delta-simdcomp-u32", {"api": "MASKED", "starting_point": 2**32 - 1}, 1),
    ("delta-simdcomp-u32", {"api": "WITHOUTMASK", "starting_point": 2**31}, 1),
    ("for-simdcomp-u32", {"api": "LENGTH", "starting_point": 2**32 - 1}, 2),
    ("for-simdcomp-u32", {"api": "FULL", "starting_point": 2**31}, 3),
    ("simdcomp-u32", {"api": "MASKED", "isa": "AVX2"}, 4),
    ("simdcomp-u32", {"api": "WITHOUTMASK", "isa": "AVX2"}, 4),
]


def adapter(key: str) -> SIMDCompAdapter:
    return SIMDCompAdapter(
        ROOT / "build/adapters/simdcomp_u32/release/libtscb_simdcomp_u32.so",
        {"backend": "C_ABI_V1", "version": "simdcomp-ctypes-v1"},
        key,
    )


def routed(values: np.ndarray) -> RoutedInput:
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    return RoutedInput(
        "v2:dataset:simdcomp-sdk-test",
        BenchmarkTrack.VALUE,
        (item,),
        None,
        None,
        values.size,
        1,
        values.nbytes * 8,
        hash_logical_buffers((item,)),
        value_units=("count",),
    )


def split(stream: bytes) -> tuple[dict, bytes]:
    _, n, _ = PREFIX.unpack_from(stream)
    return json.loads(stream[PREFIX.size : PREFIX.size + n]), stream[PREFIX.size + n :]


def fnv(data: bytes) -> int:
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) % (2**64)
    return value


def oracle(values: np.ndarray, mode: int, seed: int) -> tuple[bytes, int, int, int]:
    block = 256 if mode == 4 else 128
    body = bytearray()
    previous = seed
    value_bits = payload = 0
    for start in range(0, values.size, block):
        logical = [int(x) for x in values[start : start + block]]
        layout = 1 if mode in (1, 3) else 2 if mode == 4 and len(logical) == 256 else 0
        physical = logical + (
            [logical[-1] if mode == 1 else seed] * (128 - len(logical)) if layout == 1 else []
        )
        codes = []
        for x in physical:
            codes.append(
                (x - previous) % 2**32 if mode == 1 else (x - seed) % 2**32 if mode in (2, 3) else x
            )
            previous = x
        width = max(codes, default=0).bit_length()
        lanes = 8 if layout == 2 else 4
        lane_words = ((len(physical) + lanes - 1) // lanes * width + 31) // 32
        wire = bytearray(lane_words * lanes * 4 if width != 32 else len(physical) * 4)
        if width == 32:
            wire[:] = np.array(physical, dtype="<u4").tobytes()
        else:
            for i, x in enumerate(codes):
                for bit in range(width):
                    if x & (1 << bit):
                        pos = i // lanes * width + bit
                        at = (pos // 32 * lanes + i % lanes) * 4 + pos % 32 // 8
                        wire[at] |= 1 << (pos % 8)
        body += struct.pack("<HBBI", len(logical), width, layout, len(wire)) + wire
        value_bits += len(logical) * width
        payload += len(wire)
        previous = logical[-1]
    blocks = (values.size + block - 1) // block
    frame = (
        struct.pack("<8s6IQ", b"TSCBSBP1", values.size, seed, mode, block, blocks, 0, len(body))
        + body
    )
    frame += struct.pack("<Q", fnv(frame))
    return bytes(frame), value_bits, payload * 8 - value_bits, blocks


@pytest.mark.parametrize("key,params,mode", CONFIGS)
@pytest.mark.parametrize("n", [0, 1, 2, 127, 128, 129, 255, 256, 257, 511, 512, 513, 1023, 8193])
@pytest.mark.parametrize("pattern", ["zero", "narrow", "random", "edges"])
def test_all_source_routes_exact_wire_and_ledger(
    key: str, params: dict, mode: int, n: int, pattern: str
) -> None:
    rng = np.random.default_rng(20261007 + n)
    values = (
        np.zeros(n, dtype="<u4")
        if pattern == "zero"
        else rng.integers(0, 32, n, dtype="<u4")
        if pattern == "narrow"
        else rng.integers(0, 2**32, n, dtype="<u4")
        if pattern == "random"
        else np.resize(np.array([0, 1, 2**31, 2**32 - 1], dtype="<u4"), n)
    )
    item = routed(values)
    observation = perform_roundtrip(adapter(key), item, params)
    info, frame = split(observation.encoded.stream)
    expected, value_bits, padding, blocks = oracle(values, mode, params.get("starting_point", 0))
    assert frame == expected
    assert observation.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert (
        observation.input_immutable and observation.canary_intact and observation.determinism_match
    )
    assert info["algorithm"] == key and info["count"] == n
    assert observation.encoded.finalize_bytes == 0
    ledger = observation.encoded.ledger
    header_bytes = PREFIX.unpack_from(observation.encoded.stream)[1]
    assert ledger.final_bits == len(observation.encoded.stream) * 8
    assert ledger.value_bits == value_bits and ledger.padding_bits == padding
    assert ledger.metadata_bits == (header_bytes + 32 + blocks * 8) * 8
    assert ledger.container_bits == 20 * 8 and ledger.checksum_bits == 40 * 8
    assert ledger.external_side_information_bits == ledger.timestamp_bits == 0
    for phase in ("encode", "decode"):
        telemetry = observation.codec_telemetry[phase]
        assert telemetry["native_payload_bytes"] == len(frame) - 48 - blocks * 8
        assert telemetry["padding_stream_bits"] == padding
        assert telemetry["external_padding_bytes"] == telemetry["python_payload_copy_bytes"] == 0
    assert observation.timing.native_encode_wall_ns is not None
    assert observation.timing.native_decode_wall_ns is not None


@pytest.mark.parametrize("key,params,mode", CONFIGS)
@pytest.mark.parametrize("width", range(33))
def test_each_minimal_width_including_absolute_32(
    key: str, params: dict, mode: int, width: int
) -> None:
    residual = 2**width - 1
    seed = params.get("starting_point", 0)
    values = np.array(
        [
            (
                seed + (i + 1) * residual
                if mode == 1
                else seed + residual
                if mode in (2, 3)
                else residual
            )
            % 2**32
            for i in range(257)
        ],
        dtype="<u4",
    )
    observation = perform_roundtrip(adapter(key), routed(values), params)
    _, frame = split(observation.encoded.stream)
    assert frame == oracle(values, mode, seed)[0]
    assert frame[42] == width


@pytest.mark.parametrize("key,params,mode", CONFIGS)
@pytest.mark.parametrize("layout", ["strided", "reversed", "misaligned"])
def test_explicit_layout_copies(key: str, params: dict, mode: int, layout: str) -> None:
    source = np.arange(257, dtype="<u4") * 123457
    if layout == "strided":
        values = source[::2]
    elif layout == "reversed":
        values = source[::-1]
    else:
        storage = bytearray(1 + source.nbytes)
        values = np.ndarray(source.shape, dtype="<u4", buffer=storage, offset=1)
        values[:] = source
    result = perform_roundtrip(adapter(key), routed(values), params)
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert result.codec_telemetry["encode"]["gather_bytes"] == (
        values.nbytes if layout != "misaligned" else 0
    )
    assert (
        split(result.encoded.stream)[1] == oracle(values, mode, params.get("starting_point", 0))[0]
    )


@pytest.mark.parametrize("key,params,mode", CONFIGS)
def test_fresh_seed_api_compatible_decode_and_optional_timer(
    key: str, params: dict, mode: int
) -> None:
    item = routed(np.array([0, 2**32 - 1, 1, 0, 2**31], dtype="<u4"))
    on = perform_roundtrip(adapter(key), item, params)
    off = perform_roundtrip(adapter(key), item, {**params, "native_timing": False})
    assert on.encoded.stream == off.encoded.stream
    assert off.timing.native_encode_wall_ns is None and off.timing.native_decode_wall_ns is None
    alternate = {**params, "starting_point": 0}
    if params["api"] in ("MASKED", "WITHOUTMASK"):
        alternate["api"] = "WITHOUTMASK" if params["api"] == "MASKED" else "MASKED"
    session = adapter(key).create_session(alternate)
    try:
        assert session.native_timing() == (0, 0)
        for _ in range(2):
            assert (
                session.decompress(on.encoded.stream).buffers[0].array.tobytes()
                == item.buffers[0].array.tobytes()
            )
        before = session.native_timing()
        assert session.native_timing() == before
        session.reset()
        assert session.native_timing() == (0, 0)
    finally:
        session.close()
        session.close()
    with pytest.raises(ExecutionContractError, match="closed"):
        session.native_timing()


@pytest.mark.parametrize("key,params,mode", CONFIGS)
def test_exact_capacity_atomic_failure_alias_and_lifecycle(
    key: str, params: dict, mode: int
) -> None:
    item = routed(np.arange(257, dtype="<u4"))
    session = adapter(key).create_session(params)
    reference = perform_roundtrip(adapter(key), item, params).encoded.stream
    try:
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        short = bytearray(b"\xa5" * (len(reference) - 1))
        with pytest.raises(OutputCapacityError):
            session.compress_update(item, memoryview(short))
        assert short == b"\xa5" * len(short)
        storage = bytearray(b"\xa5" * 8192)
        alias = routed(np.ndarray((257,), dtype="<u4", buffer=storage))
        before = bytes(storage)
        with pytest.raises(ExecutionContractError, match="alias"):
            session.compress_update(alias, memoryview(storage))
        assert bytes(storage) == before
        destination = bytearray(len(reference))
        used = session.compress_update(item, memoryview(destination))
        assert bytes(destination[:used]) == reference
        with pytest.raises(ExecutionContractError, match="accounting before finalize"):
            session.accounting(reference, item)
        with pytest.raises(ExecutionContractError, match="update lifecycle"):
            session.compress_update(item, memoryview(destination))
        assert session.finalize(memoryview(bytearray())) == 0
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        assert session.accounting(reference, item).final_bits == len(reference) * 8
        bad = bytearray(reference)
        bad[-1] ^= 1
        with pytest.raises(ExecutionContractError, match="object changed"):
            session.accounting(bytes(bad), item)
        session.reset()
        assert session.native_timing() == (0, 0)
        assert session.compress_update(item, memoryview(destination)) == used
    finally:
        session.close()


@pytest.mark.parametrize("key,params,mode", CONFIGS)
def test_malformed_descriptor_frame_and_wire_mode(key: str, params: dict, mode: int) -> None:
    item = routed(np.arange(129, dtype="<u4"))
    encoded = perform_roundtrip(adapter(key), item, params).encoded.stream
    info, frame = split(encoded)
    session = adapter(key).create_session(params)

    def pack(document, wire):
        header = canonical_json_bytes(document)
        return (
            PREFIX.pack(b"TSCBSCP1", len(header), hashlib.sha256(header).digest()) + header + wire
        )

    try:
        for mutate in [
            lambda d: d.update(count=True),
            lambda d: d.update(algorithm="unknown"),
            lambda d: d["buffer"].update(shape=[True]),
            lambda d: d["parameters"].update(starting_point=True),
            lambda d: d["parameters"].update(api=[]),
            lambda d: d.update(codec_stages=[]),
            lambda d: d.update(extra=0),
        ]:
            bad = json.loads(json.dumps(info))
            mutate(bad)
            with pytest.raises(ExecutionContractError):
                session.decompress(pack(bad, frame))
        for offset in [0, 8, 12, 16, 20, 24, 28, 32, 40, 42, 43, 44, len(frame) - 1]:
            bad = bytearray(frame)
            bad[offset] ^= 0x80
            with pytest.raises(ExecutionContractError):
                session.decompress(pack(info, bad))
        for n in [0, 1, 43, 44, len(encoded) - 1]:
            with pytest.raises(ExecutionContractError):
                session.decompress(encoded[:n])
    finally:
        session.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"api": []},
        {"api": True},
        {"isa": None},
        {"starting_point": True},
        {"starting_point": -1},
        {"starting_point": 2**32},
        {"starting_point": 1},
        {"native_timing": 1},
        {"isa": "AVX512"},
        {"api": "FULL"},
        {"coding": "DELTA"},
        {"api": "LENGTH", "isa": "AVX2"},
    ],
)
def test_invalid_parameters(changes: dict) -> None:
    with pytest.raises(ExecutionContractError):
        adapter("simdcomp-u32").create_session(changes)


@pytest.mark.parametrize("dtype", ["<f4", "<f8", "<i4", "<i8", ">u4", "<u8"])
def test_dtype_is_never_converted(dtype: str) -> None:
    session = adapter("simdcomp-u32").create_session({})
    try:
        with pytest.raises(ExecutionContractError, match="dtype/shape"):
            session.output_bound(routed(np.array([0, 1], dtype=dtype)))
    finally:
        session.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"n": True},
        {"m": 2},
        {"canonical_raw_bits": 0},
        {"value_units": ("a", "b")},
        {"validity_reference": np.ones(3, dtype=np.uint8)},
    ],
)
def test_logical_contract_errors_are_rejected(changes: dict) -> None:
    item = replace(routed(np.arange(3, dtype="<u4")), **changes)
    session = adapter("simdcomp-u32").create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.output_bound(item)
    finally:
        session.close()


def test_foreign_native_library_is_rejected() -> None:
    wrong = SIMDCompAdapter(
        ROOT / "build/adapters/maskedvbyte_u32/release/libtscb_maskedvbyte_u32.so", {}
    )
    with pytest.raises(ExecutionContractError, match="identity/path"):
        wrong.create_session({})


@pytest.mark.parametrize("key,params,mode", CONFIGS)
def test_decoder_cannot_change_wire_mode_or_identity(key: str, params: dict, mode: int) -> None:
    stream = perform_roundtrip(
        adapter(key), routed(np.arange(257, dtype="<u4")), params
    ).encoded.stream
    if mode in (0, 4):
        other_key = key
        other = {"api": "MASKED", "isa": "AVX2" if mode == 0 else "SSE4_1"}
    elif mode in (2, 3):
        other_key = key
        other = {"api": "FULL" if mode == 2 else "LENGTH"}
    else:
        other_key, other = "simdcomp-u32", {}
    session = adapter(other_key).create_session(other)
    try:
        with pytest.raises(ExecutionContractError, match="wire mode|identity"):
            session.decompress(stream)
    finally:
        session.close()
