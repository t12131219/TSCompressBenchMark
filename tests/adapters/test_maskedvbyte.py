from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.maskedvbyte import MaskedVByteAdapter
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
KEYS = ["maskedvbyte-u32", "delta-maskedvbyte-u32"]
CONFIGS = [
    (key, decoder, seed)
    for key in KEYS
    for decoder in ("COUNT", "COMPRESSED_SIZE")
    for seed in ([0] if key == "maskedvbyte-u32" else [0, 1, 2**31, 2**32 - 1])
]


def adapter(key: str) -> MaskedVByteAdapter:
    return MaskedVByteAdapter(
        ROOT / "build/adapters/maskedvbyte_u32/release/libtscb_maskedvbyte_u32.so",
        {"backend": "C_ABI_V1", "version": "maskedvbyte-ctypes-v1", "algorithm": key},
        key,
    )


def routed(values: np.ndarray) -> RoutedInput:
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    return RoutedInput(
        dataset_id="v2:dataset:maskedvbyte-test",
        track=BenchmarkTrack.VALUE,
        buffers=(item,),
        timestamp_reference=None,
        validity_reference=None,
        n=int(values.size),
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers((item,)),
        value_units=("count",),
    )


def split(stream: bytes) -> tuple[dict, bytes]:
    _, length, _ = PREFIX.unpack_from(stream)
    return json.loads(stream[PREFIX.size : PREFIX.size + length]), stream[PREFIX.size + length :]


def repack(info: dict, frame: bytes) -> bytes:
    header = canonical_json_bytes(info)
    return PREFIX.pack(b"TSCBMVP1", len(header), hashlib.sha256(header).digest()) + header + frame


def scalar(values: np.ndarray, delta: bool, seed: int) -> bytes:
    output = bytearray()
    previous = seed
    for number in values:
        value = (int(number) - previous) % 2**32 if delta else int(number)
        previous = int(number)
        while value >= 128:
            output.append((value & 127) | 128)
            value >>= 7
        output.append(value)
    return bytes(output)


@pytest.mark.parametrize("key,decoder,seed", CONFIGS)
@pytest.mark.parametrize("n", [0, 1, 2, 3, 4, 5, 15, 16, 17, 32, 33, 1000, 8193])
def test_original_scalar_wire_exact_ledger_and_telemetry(
    key: str, decoder: str, seed: int, n: int
) -> None:
    values = np.random.default_rng(20261007 + n).integers(0, 2**32, n, dtype="<u4")
    if n:
        edges = np.array(
            [
                0,
                1,
                127,
                128,
                16383,
                16384,
                2097151,
                2097152,
                268435455,
                268435456,
                2**31,
                2**32 - 1,
            ],
            dtype="<u4",
        )
        values[: min(n, edges.size)] = edges[: min(n, edges.size)]
    observation = perform_roundtrip(
        adapter(key), routed(values), {"decoder_api": decoder, "starting_point": seed}
    )
    assert observation.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert not observation.decoded.buffers[0].array.flags.writeable
    assert (
        observation.input_immutable and observation.canary_intact and observation.determinism_match
    )
    info, frame = split(observation.encoded.stream)
    payload = scalar(values, key.startswith("delta-"), seed)
    assert frame[32:-8] == payload
    assert info["parameters"] == {
        "coding": "DELTA" if key.startswith("delta-") else "PLAIN",
        "starting_point": seed,
    }
    assert info["codec_stages"] == (
        ["ORIGINAL_MASKEDVBYTE_D1_MODULAR32"] if key.startswith("delta-") else []
    ) + ["ORIGINAL_MASKEDVBYTE_LEB128_UINT32"]
    ledger = observation.encoded.ledger
    assert ledger.final_bits == len(observation.encoded.stream) * 8
    assert ledger.value_bits == len(payload) * 8
    assert ledger.metadata_bits == (len(canonical_json_bytes(info)) + 24) * 8
    assert ledger.container_bits == 20 * 8 and ledger.checksum_bits == 40 * 8
    assert ledger.external_side_information_bits == ledger.timestamp_bits == 0
    assert observation.encoded.finalize_bytes == 0
    assert (
        observation.timing.native_encode_wall_ns is not None
        and observation.timing.native_decode_wall_ns is not None
    )
    enc, dec = observation.codec_telemetry["encode"], observation.codec_telemetry["decode"]
    assert enc["actual_original_api"] == (
        "vbyte_encode_delta" if key.startswith("delta-") else "vbyte_encode"
    )
    assert dec["actual_original_api"] == "masked_vbyte_decode" + (
        "_fromcompressedsize" if decoder == "COMPRESSED_SIZE" else ""
    ) + ("_delta" if key.startswith("delta-") else "")
    assert enc["native_staging_allocation_bytes"] == 4 * max(n, 1) + max(len(payload), 1)
    assert dec["native_staging_allocation_bytes"] == 4 * max(n, 1)
    assert enc["native_staging_input_copy_bytes"] == values.nbytes
    assert dec["native_staging_input_copy_bytes"] == 0
    assert enc["native_staging_output_copy_bytes"] == len(payload)
    assert dec["native_staging_output_copy_bytes"] == values.nbytes
    assert enc["python_payload_copy_bytes"] == dec["python_payload_copy_bytes"] == 0
    assert enc["internal_padding_bytes"] == dec["internal_padding_bytes"] == 0


@pytest.mark.parametrize("key", KEYS)
def test_execution_choices_do_not_change_wire_fresh_seed_reset_close(key: str) -> None:
    item = routed(np.array([2**32 - 1, 0, 1, 0, 2**31], dtype="<u4"))
    seed = 2**32 - 1 if key.startswith("delta-") else 0
    count = perform_roundtrip(adapter(key), item, {"starting_point": seed})
    size = perform_roundtrip(
        adapter(key),
        item,
        {"starting_point": seed, "decoder_api": "COMPRESSED_SIZE", "native_timing": False},
    )
    assert count.encoded.stream == size.encoded.stream
    assert size.timing.native_encode_wall_ns is None and size.timing.native_decode_wall_ns is None
    session = adapter(key).create_session({"decoder_api": "COMPRESSED_SIZE"})
    assert session.native_timing() == (0, 0)
    try:
        assert (
            session.decompress(count.encoded.stream).buffers[0].array.tobytes()
            == item.buffers[0].array.tobytes()
        )
        first = session.native_timing()
        assert first == session.native_timing()
        session.decompress(count.encoded.stream)
        assert session.native_timing()[1] >= first[1]
        session.reset()
        assert session.native_timing() == (0, 0) and not session.codec_telemetry()
    finally:
        session.close()
        session.close()
    for action in (
        session.native_timing,
        session.codec_telemetry,
        session.reset,
        lambda: session.output_bound(item),
        lambda: session.decompress(count.encoded.stream),
        lambda: session.compress_update(item, memoryview(bytearray(1024))),
        lambda: session.finalize(memoryview(bytearray())),
        lambda: session.accounting(count.encoded.stream, item),
    ):
        with pytest.raises(ExecutionContractError, match="closed"):
            action()


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("layout", ["strided", "reversed", "misaligned"])
def test_explicit_gather_and_alignment_one(key: str, layout: str) -> None:
    source = np.arange(65, dtype="<u4") * 1234567
    if layout == "strided":
        values = source[::2]
    elif layout == "reversed":
        values = source[::-1]
    else:
        storage = bytearray(1 + source.nbytes)
        values = np.ndarray(source.shape, dtype="<u4", buffer=storage, offset=1)
        values[:] = source
    observation = perform_roundtrip(adapter(key), routed(values), {})
    assert observation.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert observation.input_immutable and observation.canary_intact
    assert observation.codec_telemetry["encode"]["gather_bytes"] == (
        0 if layout == "misaligned" else values.nbytes
    )


@pytest.mark.parametrize("key", KEYS)
def test_actual_capacity_atomic_failure_alias_finalize_account_reset(key: str) -> None:
    item = routed(np.zeros(33, dtype="<u4"))
    reference = perform_roundtrip(adapter(key), item, {}).encoded.stream
    session = adapter(key).create_session({})
    try:
        bound = session.output_bound(item)
        assert bound > len(reference)
        short = bytearray(b"\xa5" * (len(reference) - 1))
        with pytest.raises(OutputCapacityError):
            session.compress_update(item, memoryview(short))
        assert short == b"\xa5" * len(short) and session.native_timing() == (0, 0)
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
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
        assert session.accounting(reference, item).final_bits == used * 8
        changed = bytearray(reference)
        changed[-1] ^= 1
        with pytest.raises(ExecutionContractError, match="object changed"):
            session.accounting(bytes(changed), item)
        session.reset()
        storage = bytearray(b"\xa5" * 1024)
        aliased = routed(np.ndarray((33,), dtype="<u4", buffer=storage))
        before = bytes(storage)
        with pytest.raises(ExecutionContractError, match="alias"):
            session.compress_update(aliased, memoryview(storage))
        assert bytes(storage) == before
        assert (
            session.compress_update(item, memoryview(destination)) == used
            and bytes(destination) == reference
        )
    finally:
        session.close()


@pytest.mark.parametrize("key", KEYS)
def test_bad_descriptor_native_checksum_and_canonical_varints(key: str) -> None:
    stream = perform_roundtrip(
        adapter(key), routed(np.array([0, 0], dtype="<u4")), {}
    ).encoded.stream
    info, frame = split(stream)
    session = adapter(key).create_session({})
    try:
        corrupt = bytearray(frame)
        corrupt[32] ^= 1
        bad = [stream[:1], stream[:-1], stream + b"\0", repack(info, bytes(corrupt))]
        changes = [
            {"count": True},
            {"count": 16777217},
            {"algorithm": "chimp"},
            {"codec_stages": []},
            {"parameters": {"coding": info["parameters"]["coding"], "starting_point": True}},
            {"parameters": {**info["parameters"], "decoder_api": "COUNT"}},
            {"buffer": {**info["buffer"], "shape": [True]}},
            {"buffer": {**info["buffer"], "dtype": "<i8"}},
            {"timestamp_unit": None},
            {"value_units": ["a", "b"]},
        ]
        bad += [repack({**info, **change}, frame) for change in changes]
        # Keep physical length/count and checksum correct, but grammar nonminimal.
        malformed = bytearray(frame)
        malformed[32:34] = b"\x80\0"
        fnv = 14695981039346656037
        for byte in malformed[:-8]:
            fnv = ((fnv ^ byte) * 1099511628211) % 2**64
        malformed[-8:] = struct.pack("<Q", fnv)
        bad.append(repack(info, bytes(malformed)))
        for candidate in bad:
            with pytest.raises(ExecutionContractError):
                session.decompress(candidate)
        # Cross-identity decode must fail even when native syntax is compatible.
        other = adapter(KEYS[1] if key == KEYS[0] else KEYS[0]).create_session({})
        try:
            with pytest.raises(ExecutionContractError, match="identity"):
                other.decompress(stream)
        finally:
            other.close()
    finally:
        session.close()


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize(
    "params",
    [
        {"starting_point": True},
        {"starting_point": -1},
        {"starting_point": 2**32},
        {"decoder_api": "ALIEN"},
        {"isa": "AVX2"},
        {"native_timing": 1},
        {"unknown": 1},
    ],
)
def test_invalid_parameters(key: str, params: dict) -> None:
    with pytest.raises(ExecutionContractError):
        adapter(key).create_session(params)


def test_plain_seed_is_not_a_hidden_delta() -> None:
    with pytest.raises(ExecutionContractError):
        adapter(KEYS[0]).create_session({"starting_point": 1})
    for key in KEYS:
        for params in ({"decoder_api": ["COUNT"]}, {"isa": ["SSE4_1"]}):
            with pytest.raises(ExecutionContractError):
                adapter(key).create_session(params)


@pytest.mark.parametrize("key", KEYS)
def test_reject_unsupported_dtype_topology_and_validity(key: str) -> None:
    session = adapter(key).create_session({})
    try:
        for dtype in ("<i8", "<u8", "<f8", "<i4", "<u2"):
            with pytest.raises(ExecutionContractError):
                session.output_bound(routed(np.arange(3, dtype=dtype)))
        base = routed(np.arange(3, dtype="<u4"))
        timestamp = replace(
            base,
            track=BenchmarkTrack.TIMESTAMP,
            buffers=(LogicalBuffer("timestamp", base.buffers[0].array, base.canonical_raw_bits),),
        )
        for bad in (
            timestamp,
            replace(base, n=2),
            replace(base, m=2),
            replace(base, m=True),
            replace(base, n=True),
            replace(base, canonical_raw_bits=1),
            replace(base, validity_reference=np.ones(3, dtype=bool)),
            replace(base, timestamp_unit=None),
            replace(base, value_units=(1,)),
        ):
            with pytest.raises(ExecutionContractError):
                session.output_bound(bad)
    finally:
        session.close()
