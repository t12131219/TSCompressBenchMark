"""Direct SDK checks compare complete objects to an independent bit grammar."""

from __future__ import annotations

import ctypes
import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.factory import create_adapter
from tscompbench.adapters.littleintpacker import KEYS, PREFIX, LittleIntPackerAdapter
from tscompbench.adapters.native_timing import _NativeTiming
from tscompbench.codecs import (
    CodecManifest,
    CodecRegistry,
    DataDescriptor,
    SourceRegistry,
    negotiate,
)
from tscompbench.contracts import BenchmarkTrack, RunStatus, Topology, ValidityShape
from tscompbench.execution.protocol import (
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
    SourceDomainError,
)
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import canonical_json_bytes
from tscompbench.planning import expand_sweep, resolve_execution

ROOT = Path(__file__).resolve().parents[2]
LENGTHS = [
    0,
    1,
    2,
    7,
    15,
    16,
    17,
    31,
    32,
    33,
    63,
    64,
    65,
    127,
    128,
    129,
    255,
    256,
    257,
    511,
    512,
    513,
    8193,
]


def adapter(key: str) -> LittleIntPackerAdapter:
    return LittleIntPackerAdapter(
        ROOT / "build/adapters/littleintpacker/release/libtscb_littleintpacker.so",
        {"backend": "C_ABI_V1", "version": "littleintpacker-ctypes-v1"},
        key,
    )


def routed(values: np.ndarray) -> RoutedInput:
    values.flags.writeable = False
    item = LogicalBuffer("value/0", values, values.nbytes * 8)
    return RoutedInput(
        "v2:dataset:littleintpacker-sdk-test",
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


def fnv(data: bytes) -> int:
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) % 2**64
    return value


def split(stream: bytes) -> tuple[dict, bytes]:
    _, size, _ = PREFIX.unpack_from(stream)
    return json.loads(stream[PREFIX.size : PREFIX.size + size]), stream[PREFIX.size + size :]


def oracle(values: np.ndarray, key: str, width: int | str) -> bytes:
    inputs = [int(value) for value in values]
    automatic = width == "AUTO"
    if automatic:
        combined = 0
        for value in inputs:
            combined |= value
        width = combined.bit_length()
    payload = bytearray((len(inputs) * width + 7) // 8)
    for i, value in enumerate(inputs):
        for k in range(width):
            bit = i * width + k
            payload[bit // 8] |= ((value >> k) & 1) << (bit % 8)
    wire = (
        struct.pack(
            "<8s4IQ",
            b"TSCBLIP1",
            len(inputs),
            list(KEYS).index(key),
            width,
            automatic,
            len(payload),
        )
        + payload
    )
    return wire + struct.pack("<Q", fnv(wire))


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("count", LENGTHS)
def test_full_uint32_tail_wire_ledger_and_native_observations(key: str, count: int) -> None:
    values = np.array([(i * 2654435761) % 2**32 for i in range(count)], dtype="<u4")
    result = perform_roundtrip(adapter(key), routed(values), {})
    info, frame = split(result.encoded.stream)
    assert frame == oracle(values, key, "AUTO")
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert not result.decoded.buffers[0].array.flags.writeable
    assert result.input_immutable and result.canary_intact and result.determinism_match
    width = struct.unpack_from("<I", frame, 16)[0]
    ledger = result.encoded.ledger
    assert ledger.value_bits == count * width
    assert ledger.padding_bits == (len(frame) - 40) * 8 - count * width
    assert ledger.metadata_bits == len(canonical_json_bytes(info)) * 8 + 192
    assert ledger.container_bits == 160 and ledger.checksum_bits == 320
    assert ledger.final_bits == len(result.encoded.stream) * 8
    assert ledger.external_side_information_bits == ledger.timestamp_bits == 0
    assert (
        result.timing.native_encode_wall_ns is not None
        and result.timing.native_decode_wall_ns is not None
    )
    for phase in ("encode", "decode"):
        telemetry = result.codec_telemetry[phase]
        assert telemetry["native_payload_bytes"] == len(frame) - 40
        assert telemetry["native_raw_bytes"] == values.nbytes
        assert telemetry["native_api_calls"] == 1
        assert telemetry["external_padding_bytes"] == 0
        assert telemetry["python_payload_copy_bytes"] == 0


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("width", range(33))
@pytest.mark.parametrize("automatic", [False, True])
def test_every_width_zero_maximum_and_original_api(key: str, width: int, automatic: bool) -> None:
    values = np.full(129, 2**width - 1, dtype="<u4")
    params = {} if automatic else {"width_mode": "FIXED", "bit_width": width}
    result = perform_roundtrip(adapter(key), routed(values), params)
    assert split(result.encoded.stream)[1] == oracle(values, key, "AUTO" if automatic else width)
    assert (
        result.codec_telemetry["decode"]["actual_original_api"]
        == {
            "PACK32": "unpack32",
            "TURBO": "turbounpack32",
            "SC": "scunpack32",
            "BMI2": "bmiunpack32",
            "HORIZONTAL": "horizontalunpack32",
        }[KEYS[key][0]]
    )


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("layout", ["strided", "reversed", "misaligned"])
def test_layout_gather_preserves_logical_order(key: str, layout: str) -> None:
    data = np.arange(129, dtype="<u4")
    if layout == "strided":
        values = data[::2]
    elif layout == "reversed":
        values = data[::-1]
    else:
        values = np.ndarray(data.shape, dtype="<u4", buffer=bytearray(data.nbytes + 1), offset=1)
        values[:] = data
    result = perform_roundtrip(adapter(key), routed(values), {})
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert split(result.encoded.stream)[1] == oracle(values, key, "AUTO")
    assert result.codec_telemetry["encode"]["gather_bytes"] == (
        values.nbytes if layout != "misaligned" else 0
    )


@pytest.mark.parametrize("key", KEYS)
def test_atomic_capacity_domain_alias_lifecycle_and_fresh_decoder(key: str) -> None:
    params = {"width_mode": "FIXED", "bit_width": 8}
    item = routed(np.arange(129, dtype="<u4"))
    stream = perform_roundtrip(adapter(key), item, params).encoded.stream
    session = adapter(key).create_session(params)
    try:
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        short = bytearray(b"\xa5" * (len(stream) - 1))
        with pytest.raises(OutputCapacityError):
            session.compress_update(item, memoryview(short))
        assert short == b"\xa5" * len(short)
        destination = bytearray(b"\xa5" * 4096)
        with pytest.raises(SourceDomainError) as failure:
            session.compress_update(routed(np.array([256], dtype="<u4")), memoryview(destination))
        assert failure.value.rejection_atomic
        assert destination == b"\xa5" * len(destination)
        alias_values = np.ndarray((129,), dtype="<u4", buffer=destination)
        alias_values[:] = np.arange(129)
        before = bytes(destination)
        with pytest.raises(ExecutionContractError, match="alias"):
            session.compress_update(routed(alias_values), memoryview(destination))
        assert bytes(destination) == before
        output = bytearray(session.output_bound(item))
        assert session.compress_update(item, memoryview(output)) == len(stream)
        with pytest.raises(ExecutionContractError, match="before finalize"):
            session.accounting(stream, item)
        assert session.finalize(memoryview(bytearray())) == 0
        assert session.accounting(stream, item).final_bits == len(stream) * 8
        with pytest.raises(ExecutionContractError, match="update lifecycle"):
            session.compress_update(item, memoryview(output))
        with pytest.raises(ExecutionContractError, match="finalize lifecycle"):
            session.finalize(memoryview(bytearray()))
        changed = bytearray(stream)
        changed[-1] ^= 1
        with pytest.raises(ExecutionContractError, match="object changed"):
            session.accounting(bytes(changed), item)
        session.reset()
        assert session.native_timing() == (0, 0)
    finally:
        session.close()
    fresh = adapter(key).create_session({"width_mode": "FIXED", "bit_width": 0})
    try:
        assert (
            fresh.decompress(stream).buffers[0].array.tobytes() == item.buffers[0].array.tobytes()
        )
        first = fresh.native_timing()
        assert fresh.native_timing() == first
    finally:
        fresh.close()
    with pytest.raises(ExecutionContractError, match="closed"):
        fresh.native_timing()


@pytest.mark.parametrize("key", KEYS)
def test_native_timing_disable_reaches_actual_library_and_preserves_wire(key: str) -> None:
    item = routed(np.arange(33, dtype="<u4"))
    on = perform_roundtrip(adapter(key), item, {})
    off = perform_roundtrip(adapter(key), item, {"native_timing": False})
    assert on.encoded.stream == off.encoded.stream
    assert off.timing.native_encode_wall_ns is off.timing.native_decode_wall_ns is None
    session = adapter(key).create_session({"native_timing": False})
    try:
        query = session._native.library.tscb_get_native_timing
        query.argtypes = [ctypes.c_void_p, ctypes.POINTER(_NativeTiming)]
        query.restype = ctypes.c_uint32
        value = _NativeTiming(ctypes.sizeof(_NativeTiming), 1, 77, 88)
        assert query(session._handle, ctypes.byref(value)) == 2
        assert value.native_encode_wall_ns == 77
    finally:
        session.close()


@pytest.mark.parametrize("key", KEYS)
def test_untrusted_descriptor_native_frame_and_every_truncation(key: str) -> None:
    item = routed(np.array([0, 1, 0], dtype="<u4"))
    stream = perform_roundtrip(adapter(key), item, {}).encoded.stream
    info, frame = split(stream)
    decoder = adapter(key).create_session({})
    try:
        for length in range(len(stream)):
            with pytest.raises(ExecutionContractError):
                decoder.decompress(stream[:length])
        for change in (
            "shape_bool",
            "count_bool",
            "extra",
            "wrong_variant",
            "width_bool",
            "width_mode",
        ):
            bad = json.loads(json.dumps(info))
            if change == "shape_bool":
                bad["buffer"]["shape"] = [True]
            elif change == "count_bool":
                bad["count"] = True
            elif change == "extra":
                bad["unexpected"] = 1
            elif change == "wrong_variant":
                bad["parameters"]["codec"] = "INVALID"
            elif change == "width_bool":
                bad["parameters"]["bit_width"] = True
            else:
                bad["parameters"]["width_mode"] = "FIXED"
            header = canonical_json_bytes(bad)
            forged = (
                PREFIX.pack(b"TSCBLPC1", len(header), hashlib.sha256(header).digest())
                + header
                + frame
            )
            with pytest.raises(ExecutionContractError):
                decoder.decompress(forged)
        for field in (0, 12, 16, 20, 24, 32):
            bad = bytearray(frame)
            bad[field] ^= 0x80
            bad[-8:] = struct.pack("<Q", fnv(bad[:-8]))
            header = canonical_json_bytes(info)
            with pytest.raises(ExecutionContractError):
                decoder.decompress(
                    PREFIX.pack(b"TSCBLPC1", len(header), hashlib.sha256(header).digest())
                    + header
                    + bad
                )
    finally:
        decoder.close()


@pytest.mark.parametrize(
    "changes",
    [
        {"bit_width": -1},
        {"bit_width": 33},
        {"bit_width": True},
        {"bit_width": "AUTO"},
        {"bit_width": 1},
        {"width_mode": "auto"},
        {"isa": "AVX512"},
        {"native_timing": 1},
        {"unknown": 0},
    ],
)
def test_invalid_parameters(changes: dict) -> None:
    with pytest.raises(ExecutionContractError):
        adapter(next(iter(KEYS))).create_session(changes)


@pytest.mark.parametrize("dtype", ["<i4", "<i8", "<u8", "<f4", "<f8"])
def test_wrong_dtype_and_routed_geometry(dtype: str) -> None:
    with pytest.raises(ExecutionContractError):
        perform_roundtrip(adapter(next(iter(KEYS))), routed(np.arange(8, dtype=dtype)), {})


def test_missing_native_artifact_and_invalid_routed_contract() -> None:
    with pytest.raises(ExecutionContractError, match="unavailable"):
        LittleIntPackerAdapter(ROOT / "missing.so", {}, next(iter(KEYS))).create_session({})
    session = adapter(next(iter(KEYS))).create_session({})
    try:
        item = routed(np.arange(8, dtype="<u4"))
        for bad in (replace(item, n=7), replace(item, m=2), replace(item, canonical_raw_bits=1)):
            with pytest.raises(ExecutionContractError):
                session.output_bound(bad)
    finally:
        session.close()


@pytest.mark.parametrize(
    "flags,allowed",
    [
        (["avx2", "bmi2"], True),
        (["avx2"], False),
        (["bmi2"], False),
        (["avx2", "lzcnt"], False),
        ([], False),
    ],
)
def test_bmi2_resolver_requires_avx2_and_bmi2_without_lzcnt(
    flags: list[str], allowed: bool, tmp_path: Path
) -> None:
    check_resolver(flags, allowed, tmp_path, "AVX2_BMI2")


@pytest.mark.parametrize(
    "flags,allowed",
    [(["ssse3", "sse4_1"], True), (["sse4_1"], False), (["ssse3"], False), ([], False)],
)
def test_horizontal_resolver_requires_ssse3_and_sse4_1(
    flags: list[str], allowed: bool, tmp_path: Path
) -> None:
    check_resolver(flags, allowed, tmp_path, "SSE4_1", ["ssse3", "sse4_1"])


def check_resolver(
    flags: list[str],
    allowed: bool,
    tmp_path: Path,
    isa: str,
    required_flags: list[str] | None = None,
) -> None:
    # Use a registered contract and replace only the ISA declaration for this resolver test.
    base = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")).get(
        "simple9-u28"
    )
    document = json.loads(json.dumps(base.document))
    document["execution"]["isa"] = [isa]
    if required_flags:
        document["execution"]["required_cpu_flags"] = required_flags
    document["parameters"]["properties"]["isa"] = {
        "type": "string",
        "enum": [isa],
        "default": isa,
    }
    manifest = CodecManifest(base.key, document, base.algorithm_id)
    descriptor = DataDescriptor(
        dataset_id="test",
        track=BenchmarkTrack.VALUE,
        topology=Topology.UTS,
        n=4,
        m=1,
        shape=(4,),
        dtype_vector=("<u4",),
        physical_layout="ROW_MAJOR_CONTIG",
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=128,
        validity_shape=ValidityShape.NONE,
        timestamp_present=True,
        preserve_order=True,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )
    artifact = tmp_path / "adapter.bin"
    artifact.write_bytes(b"frozen")
    resolution = resolve_execution(
        manifest,
        expand_sweep(manifest, {})[0],
        negotiate(manifest, descriptor),
        {"environment_id": "test", "cpu": {"flags": flags, "affinity": [0]}},
        artifact_path=artifact,
        profile={
            "threads": 1,
            "processes": 1,
            "runner_version": "test",
            "allocation_policy": "PER_REPETITION",
            "cache_policy": "WARM_INPUT",
            "state_policy": "RESET_PER_REPETITION",
            "gc_policy": "DISABLED_DURING_TIMING",
            "jit_policy": "NOT_APPLICABLE",
        },
    )
    assert resolution.status is (RunStatus.PLANNED if allowed else RunStatus.ISA_UNSUPPORTED)
    assert resolution.actual_isa == (isa if allowed else "NOT_EXECUTED")
    assert not resolution.fallback_used
    assert callable(create_adapter)
