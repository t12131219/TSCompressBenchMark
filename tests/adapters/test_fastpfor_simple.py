"""Exercise the Python SDK against source-backed SPF1 libraries and a wire oracle."""

from __future__ import annotations

import ctypes
import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.fastpfor_simple import KEYS, PREFIX, FastPFORSimpleAdapter
from tscompbench.adapters.native_timing import _NativeTiming
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
CONFIGS = [(key, marked) for key in KEYS for marked in (False, True)]
S9 = [[1] * 28, [2] * 14, [3] * 9, [4] * 7, [5] * 5, [7] * 4, [9] * 3, [14] * 2, [28]]
S16 = [
    S9[0],
    [2] * 7 + [1] * 14,
    [1] * 7 + [2] * 7 + [1] * 7,
    [1] * 14 + [2] * 7,
    S9[1],
    [4] + [3] * 8,
    [3, 4, 4, 4, 4, 3, 3, 3],
    S9[3],
    [5, 5, 5, 5, 4, 4],
    [4, 4, 5, 5, 5, 5],
    [6, 6, 6, 5, 5],
    [5, 5, 6, 6, 6],
    S9[5],
    [10, 9, 9],
    S9[7],
    S9[8],
]


def adapter(key: str) -> FastPFORSimpleAdapter:
    return FastPFORSimpleAdapter(
        ROOT / "build/adapters/fastpfor_simple/release/libtscb_fastpfor_simple.so",
        {"backend": "C_ABI_V1", "version": "simple-ctypes-v1"},
        key,
    )


def routed(values: np.ndarray) -> RoutedInput:
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    return RoutedInput(
        "v2:dataset:simple-sdk-test",
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
    _, size, _ = PREFIX.unpack_from(stream)
    return json.loads(stream[PREFIX.size : PREFIX.size + size]), stream[PREFIX.size + size :]


def fnv(data: bytes) -> int:
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) % 2**64
    return value


def oracle(values: np.ndarray, key: str, marked: bool) -> tuple[bytes, int, int]:
    inputs = [int(v) for v in values]
    table = S16 if key == "simple16-u28" else S9
    words, at, value_bits, padding = ([len(inputs)] if marked else []), 0, 0, 0
    while at < len(inputs):
        if key == "simple9hacked-u28" and all(v == 0 for v in inputs[at : at + 28]):
            words.append(9 << 28)
            padding += 28
            at += min(28, len(inputs) - at)
            continue
        for selector, widths in enumerate(table):
            part = inputs[at : at + len(widths)]
            if all(v < 2**w for v, w in zip(part, widths, strict=False)):
                word, remaining = selector << 28, 28
                for value, width in zip(part, widths, strict=False):
                    remaining -= width
                    word |= value << remaining
                words.append(word)
                value_bits += 28 - remaining
                padding += remaining
                at += len(part)
                break
        else:
            raise AssertionError("oracle source domain")
    frame = struct.pack(
        "<8s6I", b"TSCBSPF1", len(inputs), list(KEYS).index(key), marked, len(words), 0, 0
    )
    frame += b"".join(struct.pack("<I", word) for word in words)
    frame += struct.pack("<Q", fnv(frame))
    return frame, value_bits, padding


@pytest.mark.parametrize("key,marked", CONFIGS)
@pytest.mark.parametrize("count", [0, 1, 2, 7, 14, 21, 27, 28, 29, 55, 56, 57, 127, 128, 129, 257])
def test_tail_wire_ledger_and_native_observations(key: str, marked: bool, count: int) -> None:
    values = np.array([(i * 2654435761) % 2**28 for i in range(count)], dtype="<u4")
    result = perform_roundtrip(adapter(key), routed(values), {"mark_length": marked})
    info, frame = split(result.encoded.stream)
    expected, bits, padding = oracle(values, key, marked)
    assert frame == expected
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert not result.decoded.buffers[0].array.flags.writeable
    assert result.input_immutable and result.canary_intact and result.determinism_match
    ledger = result.encoded.ledger
    assert ledger.value_bits == bits and ledger.padding_bits == padding
    assert ledger.final_bits == len(result.encoded.stream) * 8
    assert (
        ledger.metadata_bits
        == len(canonical_json_bytes(info)) * 8
        + 192
        + 32 * marked
        + ((len(frame) - 40) // 4 - marked) * 4
    )
    assert ledger.container_bits == 160 and ledger.checksum_bits == 320
    assert ledger.external_side_information_bits == ledger.timestamp_bits == 0
    assert (
        result.timing.native_encode_wall_ns is not None
        and result.timing.native_decode_wall_ns is not None
    )
    for phase in ("encode", "decode"):
        telemetry = result.codec_telemetry[phase]
        assert telemetry["native_payload_bytes"] == len(frame) - 40
        assert telemetry["internal_padding_bytes"] == 112
        assert telemetry["python_payload_copy_bytes"] == 0


@pytest.mark.parametrize("key,marked", CONFIGS)
@pytest.mark.parametrize("width", range(29))
def test_each_source_integer_width(key: str, marked: bool, width: int) -> None:
    values = np.full(57, 2**width - 1, dtype="<u4")
    result = perform_roundtrip(adapter(key), routed(values), {"mark_length": marked})
    assert split(result.encoded.stream)[1] == oracle(values, key, marked)[0]


@pytest.mark.parametrize("key,marked", CONFIGS)
def test_every_selector_and_mixed_width_layout(key: str, marked: bool) -> None:
    table = S16 if key == "simple16-u28" else S9
    observed = set()
    for widths in table:
        values = np.array([2**w - 1 for w in widths], dtype="<u4")
        result = perform_roundtrip(adapter(key), routed(values), {"mark_length": marked})
        frame = split(result.encoded.stream)[1]
        assert frame == oracle(values, key, marked)[0]
        observed.add(struct.unpack_from("<I", frame, 32 + 4 * marked)[0] >> 28)
    if key == "simple9hacked-u28":
        result = perform_roundtrip(
            adapter(key), routed(np.zeros(1, dtype="<u4")), {"mark_length": marked}
        )
        observed.add(
            struct.unpack_from("<I", split(result.encoded.stream)[1], 32 + 4 * marked)[0] >> 28
        )
    assert observed == set(
        range(16 if key == "simple16-u28" else 10 if key == "simple9hacked-u28" else 9)
    )


@pytest.mark.parametrize("key,marked", CONFIGS)
@pytest.mark.parametrize("layout", ["strided", "reversed", "misaligned"])
def test_layout_gather_preserves_logical_order(key: str, marked: bool, layout: str) -> None:
    data = np.arange(129, dtype="<u4")
    if layout == "strided":
        values = data[::2]
    elif layout == "reversed":
        values = data[::-1]
    else:
        values = np.ndarray(data.shape, dtype="<u4", buffer=bytearray(data.nbytes + 1), offset=1)
        values[:] = data
    result = perform_roundtrip(adapter(key), routed(values), {"mark_length": marked})
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert split(result.encoded.stream)[1] == oracle(values, key, marked)[0]
    assert result.codec_telemetry["encode"]["gather_bytes"] == (
        values.nbytes if layout != "misaligned" else 0
    )


@pytest.mark.parametrize("key,marked", CONFIGS)
def test_atomic_capacity_domain_alias_and_lifecycle(key: str, marked: bool) -> None:
    item = routed(np.arange(29, dtype="<u4"))
    params = {"mark_length": marked}
    stream = perform_roundtrip(adapter(key), item, params).encoded.stream
    session = adapter(key).create_session(params)
    try:
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        short = bytearray(b"\xa5" * (len(stream) - 1))
        with pytest.raises(OutputCapacityError):
            session.compress_update(item, memoryview(short))
        assert short == b"\xa5" * len(short)
        target = bytearray(b"\xa5" * 4096)
        illegal = routed(np.array([2**28], dtype="<u4"))
        with pytest.raises(ExecutionContractError, match="SIMPLE_UINT28_VALUE_OUT_OF_RANGE"):
            session.compress_update(illegal, memoryview(target))
        assert target == b"\xa5" * len(target)
        alias_values = np.ndarray((29,), dtype="<u4", buffer=target)
        alias_values[:] = np.arange(29)
        before = bytes(target)
        with pytest.raises(ExecutionContractError, match="alias"):
            session.compress_update(routed(alias_values), memoryview(target))
        assert bytes(target) == before
        destination = bytearray(len(stream))
        assert session.compress_update(item, memoryview(destination)) == len(stream)
        assert bytes(destination) == stream
        with pytest.raises(ExecutionContractError, match="before finalize"):
            session.accounting(stream, item)
        assert session.finalize(memoryview(bytearray())) == 0
        assert session.accounting(stream, item).final_bits == len(stream) * 8
        with pytest.raises(ExecutionContractError, match="update lifecycle"):
            session.compress_update(item, memoryview(destination))
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        altered = bytearray(stream)
        altered[-1] ^= 1
        with pytest.raises(ExecutionContractError, match="object changed"):
            session.accounting(bytes(altered), item)
        session.reset()
        assert session.native_timing() == (0, 0)
        assert session.compress_update(item, memoryview(destination)) == len(stream)
    finally:
        session.close()


@pytest.mark.parametrize("key,marked", CONFIGS)
def test_fresh_marked_decode_timer_disable_and_repeated_queries(key: str, marked: bool) -> None:
    item = routed(np.arange(57, dtype="<u4"))
    enabled = perform_roundtrip(adapter(key), item, {"mark_length": marked})
    disabled = perform_roundtrip(
        adapter(key), item, {"mark_length": marked, "native_timing": False}
    )
    assert enabled.encoded.stream == disabled.encoded.stream
    assert (
        disabled.timing.native_encode_wall_ns is None
        and disabled.timing.native_decode_wall_ns is None
    )
    session = adapter(key).create_session({"mark_length": not marked})
    try:
        assert session.native_timing() == (0, 0)
        for _ in range(2):
            assert (
                session.decompress(enabled.encoded.stream).buffers[0].array.tobytes()
                == item.buffers[0].array.tobytes()
            )
        first = session.native_timing()
        assert session.native_timing() == first
        session.reset()
        assert session.native_timing() == (0, 0)
    finally:
        session.close()
        session.close()
    with pytest.raises(ExecutionContractError, match="closed"):
        session.native_timing()
    off = adapter(key).create_session({"native_timing": False})
    try:
        off.decompress(enabled.encoded.stream)
        query = off._native.library.tscb_get_native_timing
        query.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NativeTiming)]
        query.restype = ctypes.c_uint32
        observation = _NativeTiming(ctypes.sizeof(_NativeTiming), 1, 41, 43)
        assert query(off._handle, ctypes.byref(observation)) == 2
        assert observation.native_encode_wall_ns == 41 and observation.native_decode_wall_ns == 43
    finally:
        off.close()


@pytest.mark.parametrize("key,marked", CONFIGS)
def test_untrusted_descriptors_frames_and_all_truncations(key: str, marked: bool) -> None:
    stream = perform_roundtrip(
        adapter(key), routed(np.arange(29, dtype="<u4")), {"mark_length": marked}
    ).encoded.stream
    info, frame = split(stream)
    session = adapter(key).create_session({})

    def pack(document: dict, wire: bytes) -> bytes:
        header = canonical_json_bytes(document)
        return (
            PREFIX.pack(b"TSCBSPC1", len(header), hashlib.sha256(header).digest()) + header + wire
        )

    try:
        for end in range(len(stream)):
            with pytest.raises(ExecutionContractError):
                session.decompress(stream[:end])
        for change in (
            lambda d: d.update(count=True),
            lambda d: d.update(count=2**25),
            lambda d: d.update(extra=0),
            lambda d: d.update(track="TIMESTAMP"),
            lambda d: d["buffer"].update(shape=[True]),
            lambda d: d["buffer"].update(dtype="<i8"),
            lambda d: d["parameters"].update(mark_length=1),
            lambda d: d["parameters"].update(codec="NONE"),
        ):
            document = json.loads(json.dumps(info))
            change(document)
            with pytest.raises(ExecutionContractError):
                session.decompress(pack(document, frame))
        for offset in (8, 12, 16, 24, 28, 32):
            wire = bytearray(frame)
            wire[offset] ^= 1
            if offset == 32:
                struct.pack_into("<I", wire, 32 + 4 * marked, 15 << 28)
                if key == "simple16-u28":
                    struct.pack_into("<I", wire, 8, 0)
            struct.pack_into("<Q", wire, len(wire) - 8, fnv(wire[:-8]))
            with pytest.raises(ExecutionContractError):
                session.decompress(pack(info, bytes(wire)))
        with pytest.raises(ExecutionContractError):
            session.decompress(stream + b"\0")
    finally:
        session.close()


@pytest.mark.parametrize(
    "parameters",
    [
        {"mark_length": 1},
        {"isa": "AVX2"},
        {"native_timing": 0},
        {"codec": "SIMPLE16"},
        {"extra": 0},
    ],
)
def test_invalid_parameters(parameters: dict) -> None:
    with pytest.raises(ExecutionContractError):
        adapter("simple9-u28").create_session(parameters)


@pytest.mark.parametrize("dtype", ["<i8", "<f8", ">u4", "<u8"])
def test_wrong_dtype_is_rejected(dtype: str) -> None:
    session = adapter("simple9-u28").create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.output_bound(routed(np.arange(3, dtype=dtype)))
    finally:
        session.close()


def test_wrong_routed_geometry_and_missing_native_artifact() -> None:
    item = routed(np.arange(3, dtype="<u4"))
    session = adapter("simple9-u28").create_session({})
    try:
        for changed in (
            replace(item, m=2),
            replace(item, n=4),
            replace(item, canonical_raw_bits=1),
            replace(item, validity_reference=np.ones(3, dtype=bool)),
        ):
            with pytest.raises(ExecutionContractError):
                session.output_bound(changed)
    finally:
        session.close()
    with pytest.raises(ExecutionContractError, match="unavailable"):
        FastPFORSimpleAdapter(ROOT / "build/no-such-simple.so", {}).create_session({})
    with pytest.raises(ExecutionContractError, match="identity"):
        FastPFORSimpleAdapter(
            ROOT / "build/adapters/simdcomp_u32/release/libtscb_simdcomp_u32.so", {}
        ).create_session({})
