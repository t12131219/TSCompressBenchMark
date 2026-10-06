from __future__ import annotations

import ctypes
import hashlib
import json
import struct
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.rewrite_lossless import RewriteLosslessAdapter, _buffer, _storage
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.codecs.models import DataDescriptor
from tscompbench.codecs.negotiation import negotiate
from tscompbench.contracts import BenchmarkTrack, CapabilityStatus, Topology, ValidityShape
from tscompbench.execution.protocol import (
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
)
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers, hash_reference_array

ROOT = Path(__file__).resolve().parents[2]
ALGORITHMS = [
    "chimp",
    "chimp128",
    "elf",
    "elf-plus",
    "elf-star",
    "self-star",
    "prometheus-xor-chunk",
]


def codec(name):
    doc = json.loads((ROOT / "registry/codecs" / (name + ".json")).read_text())
    path = ROOT / doc["adapter"]["artifact_path"]
    assert path.is_file(), f"build {name} before qualification"
    return RewriteLosslessAdapter(path, doc["adapter"], name)


def route(n, width=8, m=2, matrix=False, system=False):
    values = np.array([(i % 19 - 9) / 10 for i in range(n * m)], dtype=f"<f{width}").reshape(n, m)
    values.flags.writeable = False
    if matrix:
        buffers = [LogicalBuffer("value/matrix", values, values.nbytes * 8)]
    else:
        buffers = [
            LogicalBuffer(f"value/{i:06}", np.ascontiguousarray(values[:, i]), n * width * 8)
            for i in range(m)
        ]
    timestamp = None
    if system:
        pattern = [-(2**63), 2**63 - 1, 0, 0, -1, -15, 1000]
        timestamp = np.array([pattern[i % len(pattern)] for i in range(n)], dtype="<i8")
        timestamp.flags.writeable = False
        buffers.insert(0, LogicalBuffer("timestamp", timestamp, n * 64))
    for b in buffers:
        b.array.flags.writeable = False
    buffers = tuple(buffers)
    return RoutedInput(
        "dataset:rewrite-tests",
        BenchmarkTrack.SYSTEM if system else BenchmarkTrack.VALUE,
        buffers,
        timestamp,
        None,
        n,
        m,
        sum(b.logical_bits for b in buffers),
        hash_logical_buffers(buffers),
        segment_plan_id="segment:tests" if system else None,
        pairing_reference_sha256=hash_reference_array(timestamp),
    )


@pytest.mark.parametrize("name", ALGORITHMS)
@pytest.mark.parametrize("n", [0, 1, 2, 6, 7, 8, 1001])
@pytest.mark.parametrize("width", [4, 8])
@pytest.mark.parametrize("matrix", [False, True])
def test_roundtrip_fresh_decoder_boundaries_layout_and_accounting(name, n, width, matrix):
    system = name == "prometheus-xor-chunk"
    if system and (width != 8 or matrix):
        return
    routed = route(n, width, matrix=matrix, system=system)
    observation = perform_roundtrip(codec(name), routed, {"block_size": 7, "isa": "SCALAR"})
    assert observation.input_immutable and observation.canary_intact
    assert observation.determinism_match
    assert observation.encoded.finalize_bytes == 0
    ledger = observation.encoded.ledger
    assert ledger.final_bits == len(observation.encoded.stream) * 8
    if system:
        assert ledger.unallocated_shared_bits > 0 or n == 0
        assert ledger.timestamp_bits == ledger.value_bits == 0
    assert {b.name: b.array.tobytes() for b in observation.decoded.buffers} == {
        b.name: b.array.tobytes() for b in routed.buffers
    }


@pytest.mark.parametrize("name", ALGORITHMS)
def test_capacity_retry_finalize_reset_close_and_malformed(name):
    adapter = codec(name)
    r = route(8, system=name == "prometheus-xor-chunk")
    params = {"block_size": 7}
    result = perform_roundtrip(adapter, r, params)
    with_session = adapter.create_session(params)
    try:
        short = bytearray([0x5A] * (len(result.encoded.stream) - 1))
        with pytest.raises(OutputCapacityError):
            with_session.compress_update(r, memoryview(short))
        assert short == bytes([0x5A]) * len(short)
        output = bytearray(with_session.output_bound(r))
        used = with_session.compress_update(r, memoryview(output))
        assert bytes(output[:used]) == result.encoded.stream
        assert with_session.finalize(memoryview(bytearray())) == 0
        with pytest.raises(ExecutionContractError):
            with_session.finalize(memoryview(bytearray()))
        with pytest.raises(ExecutionContractError):
            with_session.compress_update(r, memoryview(output))
        native = with_session._native.lib
        assert native.tscb_reset(with_session._handle, 1) == 2
        assert native.tscb_reset(with_session._handle, 0) == 0
    finally:
        handle = with_session._handle
        with_session.close()
        assert with_session._native.lib.tscb_destroy(handle) == 1
        with_session.close()
    decoder = adapter.create_session(params)
    try:
        stream = result.encoded.stream
        for cut in [0, 1, 43, len(stream) - 1]:
            with pytest.raises(ExecutionContractError):
                decoder.decompress(stream[:cut])
        for pos in [0, 15, 45, len(stream) - 1]:
            broken = bytearray(stream)
            broken[pos] ^= 1
            with pytest.raises(ExecutionContractError):
                decoder.decompress(bytes(broken))
        # Repair the outer hash and native checksum after poisoning a record count.
        header_len = struct.unpack_from("<I", stream, 8)[0]
        start = 44 + header_len
        broken = bytearray(stream)
        struct.pack_into("<I", broken, start + 28, 2**32 - 1)
        checksum = 14695981039346656037
        for byte in broken[start:-8]:
            checksum = ((checksum ^ byte) * 1099511628211) & (2**64 - 1)
        struct.pack_into("<Q", broken, len(broken) - 8, checksum)
        with pytest.raises(ExecutionContractError):
            decoder.decompress(bytes(broken))
    finally:
        decoder.close()


@pytest.mark.parametrize("name", ALGORITHMS)
def test_native_capacity_and_no_write_after_bad_frame(name):
    session = codec(name).create_session({"block_size": 7})
    try:
        data = session._input(route(8, system=name == "prometheus-xor-chunk"))
        backing, array = _storage(data)
        source = _buffer(ctypes.addressof(array), len(data), len(data))
        library = session._native.lib
        size = ctypes.c_uint64()
        assert (
            library.tscb_compress_bound(session._handle, ctypes.byref(source), ctypes.byref(size))
            == 0
        )
        output = bytearray([0xA5] * (size.value + 2))
        arr = (ctypes.c_ubyte * len(output)).from_buffer(output)
        target = _buffer(ctypes.addressof(arr) + 1, 0)
        assert (
            library.tscb_compress(session._handle, ctypes.byref(source), ctypes.byref(target)) == 3
        )
        assert output == bytes([0xA5]) * len(output)
        target.capacity_bytes = size.value
        assert (
            library.tscb_compress(session._handle, ctypes.byref(source), ctypes.byref(target)) == 0
        )
        assert output[0] == output[-1] == 0xA5
        frame = bytes(output[1 : 1 + target.used_bytes])
        frame_backing, frame_arr = _storage(frame)
        coded = _buffer(ctypes.addressof(frame_arr), len(frame), len(frame))
        target.capacity_bytes = len(data) - 21
        target.used_bytes = 0
        snapshot = bytes(output)
        assert (
            library.tscb_decompress(session._handle, ctypes.byref(coded), ctypes.byref(target)) == 3
        )
        assert bytes(output) == snapshot
    finally:
        session.close()


@pytest.mark.parametrize("name", ["elf", "elf-plus", "elf-star", "self-star"])
def test_source_non_lossless_values_reject_without_raw_fallback(name):
    r = route(1, m=1)
    for value in [float("nan"), 1e20]:
        a = np.array([value], dtype="<f8")
        unsupported = replace(r, buffers=(LogicalBuffer("value/000000", a, 64),))
        with pytest.raises(ExecutionContractError):
            perform_roundtrip(codec(name), unsupported, {"block_size": 7})


def test_chimp_noncanonical_nan_payloads_and_joint_ieee_values():
    bits = np.array(
        [
            0,
            2**63,
            0x7FF0000000000000,
            0xFFF0000000000000,
            0x7FF8000000000001,
            1,
            0x7FEFFFFFFFFFFFFF,
        ],
        dtype="<u8",
    )
    for name in ["chimp", "chimp128", "prometheus-xor-chunk"]:
        system = name == "prometheus-xor-chunk"
        r = route(len(bits), m=1, system=system)
        buffers = (
            r.buffers[:1] + (LogicalBuffer("value/000000", bits.view("<f8"), bits.nbytes * 8),)
            if system
            else (LogicalBuffer("value/000000", bits.view("<f8"), bits.nbytes * 8),)
        )
        result = perform_roundtrip(codec(name), replace(r, buffers=buffers), {"block_size": 7})
        assert result.decoded.buffers[-1].array.tobytes() == bits.tobytes()


def test_joint_dtype_roles_never_convert_int64_timestamp_to_float():
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    d = DataDescriptor(
        "dataset:roles",
        BenchmarkTrack.SYSTEM,
        Topology.SYNCHRONOUS_MTS,
        8,
        2,
        (8, 2),
        ("<i8", "<f8", "<f8"),
        "COMPOSITE_T_V",
        "little",
        1,
        8 * 3 * 64,
        ValidityShape.NONE,
        True,
        True,
        True,
        True,
        True,
    )
    plan = negotiate(registry.get("prometheus-xor-chunk"), d)
    assert plan.status is CapabilityStatus.DIRECT_SUPPORTED
    assert not plan.operations
    assert (
        negotiate(
            registry.get("prometheus-xor-chunk"), replace(d, dtype_vector=("<i8", "<i8", "<f8"))
        ).status
        is CapabilityStatus.UNSUPPORTED
    )
    assert (
        negotiate(
            registry.get("prometheus-xor-chunk"), replace(d, dtype_vector=("<f8", "<f8", "<f8"))
        ).status
        is CapabilityStatus.UNSUPPORTED
    )


def test_frozen_snapshots_are_exact_and_source_ids_are_bound_to_them():
    lock = json.loads((ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json").read_text())
    for name in ALGORITHMS:
        for record in lock["algorithms"][name]["files"]:
            path = ROOT / record["path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == record["sha256"]
        doc = json.loads(
            (ROOT / "registry/sources" / (name + "-rewrite.artifact.json")).read_text()
        )
        assert doc["identity"]["api_files"] == lock["algorithms"][name]["files"]


def test_aliases_share_one_joint_algorithm_and_onboarding_cards_are_valid():
    from tscompbench.codecs import validate_onboarding_card
    from tscompbench.planning.sweep import expand_sweep

    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    target = registry.get("prometheus-xor-chunk")
    for alias in ["gorilla", "delta-of-delta", "second-order-difference"]:
        assert registry.get(alias) is target
    for name in ALGORITHMS:
        assert expand_sweep(registry.get(name), {"block_size": [1000], "isa": ["SCALAR"]})
        card = json.loads((ROOT / "registry/onboarding" / (name + ".json")).read_text())
        assert (
            validate_onboarding_card(card)["source_artifact_id"]
            == registry.get(name).source_artifact_id
        )
