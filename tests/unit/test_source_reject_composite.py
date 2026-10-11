"""Source/RAW recipe identity, full block accounting and adversarial restoration."""

import gc
import hashlib
import json
import struct
import weakref
from pathlib import Path

import numpy as np
import pytest

from tscompbench.accounting import AccountingLedger
from tscompbench.adapters.alp import AlpAdapter
from tscompbench.adapters.source_reject_fallback import (
    SourceRejectCompositeAdapter,
    _block_input,
    source_reject_composite_adapter_id,
    source_reject_composite_recipe_id,
)
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import (
    DecodedOutput,
    ExecutionContractError,
    LogicalBuffer,
    OutputCapacityError,
    RoutedInput,
    SourceDomainError,
)
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]
FRAME = struct.Struct("<8sIQ")


def route(length=13, channels=2):
    arrays = [np.arange(length, dtype="<f8") + i / 10 for i in range(channels)]
    for array in arrays:
        array.flags.writeable = False
    buffers = tuple(LogicalBuffer(f"value/{i:06d}", a, a.nbytes * 8) for i, a in enumerate(arrays))
    return RoutedInput(
        "dataset:test",
        BenchmarkTrack.VALUE,
        buffers,
        None,
        None,
        length,
        channels,
        sum(b.logical_bits for b in buffers),
        hash_logical_buffers(buffers),
    )


class Child:
    adapter_id = "child:test"
    deterministic = True

    def __init__(self, *, reject_from=None, dirty=False, failure=None, extra=0, external=0):
        self.reject_from = reject_from
        self.dirty = dirty
        self.failure = failure
        self.extra = extra
        self.external = external
        self.sessions = []
        self.decode_calls = 0

    def create_session(self, parameters):
        session = ChildSession(self)
        self.sessions.append(weakref.ref(session))
        return session


class ChildSession:
    def __init__(self, child):
        self.child = child

    def _stream(self, routed):
        document = [
            {"name": b.name, "dtype": b.array.dtype.str, "shape": list(b.array.shape)}
            for b in routed.buffers
        ]
        return (
            canonical_json_bytes(document)
            + b"\n"
            + b"".join(b.array.tobytes() for b in routed.buffers)
        )

    def output_bound(self, routed):
        return len(self._stream(routed)) + self.child.extra

    def compress_update(self, routed, destination):
        if self.child.failure is not None:
            raise self.child.failure("injected source failure")
        if (
            self.child.reject_from is not None
            and routed.n
            and routed.buffers[0].array[0] >= self.child.reject_from
        ):
            if self.child.dirty:
                destination[0] = 1
            # Reproduce ALP's exception->traceback->originating-frame cycle.
            error = SourceDomainError("source rowgroup is outside the decimal domain")
            error.rejection_atomic = True
            raise error
        data = self._stream(routed) + b"\0" * self.child.extra
        destination[: len(data)] = data
        return len(data)

    def finalize(self, destination):
        return 0

    def accounting(self, stream, routed):
        return AccountingLedger.create(
            track=routed.track,
            canonical_raw_bits=routed.canonical_raw_bits,
            final_physical_bytes=len(stream),
            value_bits=len(stream) * 8,
            external_side_information_bits=self.child.external,
        )

    def decompress(self, stream):
        self.child.decode_calls += 1
        header, data = stream.split(b"\n", 1)
        buffers, offset = [], 0
        for item in json.loads(header):
            size = int(np.prod(item["shape"])) * np.dtype(item["dtype"]).itemsize
            array = np.frombuffer(data[offset : offset + size], dtype=item["dtype"]).reshape(
                item["shape"]
            )
            buffers.append(LogicalBuffer(item["name"], array, size * 8))
            offset += size
        return DecodedOutput(tuple(buffers))

    def close(self):
        pass


def encode(adapter, routed):
    session = adapter.create_session({})
    try:
        bound = session.output_bound(routed)
        destination = bytearray(bound)
        length = session.compress_update(routed, memoryview(destination))
        assert session.finalize(memoryview(destination)[length:]) == 0
        stream = bytes(destination[:length])
        return stream, session.accounting(stream, routed), session._artifact.codec_telemetry, bound
    finally:
        session.close()


def frame(stream):
    magic, header_length, _ = FRAME.unpack_from(stream)
    return (
        magic,
        json.loads(stream[FRAME.size : FRAME.size + header_length]),
        stream[FRAME.size + header_length :],
    )


def rebuild(magic, header, payload):
    data = canonical_json_bytes(header)
    return FRAME.pack(magic, len(data), len(payload)) + data + payload


def test_multiblock_costs_and_frozen_recipe_are_independent_of_realized_branches():
    original = route()
    child = Child(reject_from=8)
    adapter = SourceRejectCompositeAdapter(child, "test", block_rows=4)
    stream, ledger, telemetry, bound = encode(adapter, original)
    magic, header, _ = frame(stream)
    assert magic == b"TSCBRSV3"
    assert len(stream) <= bound < 100_000
    assert ledger.final_bits == len(stream) * 8
    assert ledger.canonical_raw_bits == original.canonical_raw_bits
    assert telemetry["raw_block_count"] == telemetry["codec_block_count"] == 2
    assert telemetry["recipe_id"] == source_reject_composite_recipe_id(
        child.adapter_id, "test", {}, 4
    )
    assert telemetry["recipe_id"] == header["recipe_id"]
    assert telemetry["realized_artifact_recipe_id"] != telemetry["recipe_id"]
    assert "source_attempts" not in telemetry
    for block in header["blocks"]:
        bits = block["count"] * original.m * 64
        if block["encoding"] == "CODEC":
            assert block["child_ledger"]["canonical_raw_bits"] == bits
        else:
            assert sum(d["logical_bits"] for d in block["raw_descriptors"]) == bits
    decoded = adapter.create_session({}).decompress(stream)
    assert hash_logical_buffers(decoded.buffers) == original.input_sha256
    assert all(b.array.flags.owndata and not b.array.flags.writeable for b in decoded.buffers)
    assert _block_input(original, 4, 8).canonical_raw_bits == 4 * original.m * 64


def test_adapter_and_recipe_identity_bind_actual_block_size_and_parameters():
    child = Child()
    assert (
        SourceRejectCompositeAdapter(child, "test", 2).adapter_id
        != SourceRejectCompositeAdapter(child, "test", 4).adapter_id
    )
    assert SourceRejectCompositeAdapter(
        child, "test", 2
    ).adapter_id == source_reject_composite_adapter_id(child.adapter_id, "test", 2)
    assert source_reject_composite_recipe_id(
        child.adapter_id, "test", {}, 2
    ) != source_reject_composite_recipe_id(child.adapter_id, "test", {"mode": 1}, 2)
    with pytest.raises(ExecutionContractError):
        SourceRejectCompositeAdapter(child, "test", 0)


def test_bound_uses_child_expansion_and_column_metadata_instead_of_fixed_reserve():
    child = Child(extra=2 * 1024 * 1024)
    stream, _, _, bound = encode(SourceRejectCompositeAdapter(child, "test", 4), route(1, 1))
    assert bound >= len(stream) > 2 * 1024 * 1024
    many = route(1, 4096)
    stream, _, _, bound = encode(SourceRejectCompositeAdapter(Child(), "test"), many)
    assert bound >= len(stream)


def test_rejection_does_not_retain_sessions_with_gc_disabled():
    child = Child(reject_from=0)
    adapter = SourceRejectCompositeAdapter(child, "test", 4)
    original = route(4, 1)
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(16):
            encode(adapter, original)
        assert all(reference() is None for reference in child.sessions)
    finally:
        if was_enabled:
            gc.enable()


@pytest.mark.parametrize("failure", [MemoryError, OutputCapacityError, RuntimeError])
def test_non_domain_failures_never_become_raw(failure):
    with pytest.raises(failure):
        encode(SourceRejectCompositeAdapter(Child(failure=failure), "test", 4), route())


def test_dirty_source_rejection_and_untransported_child_dependency_fail_closed():
    with pytest.raises(ExecutionContractError, match="modified"):
        encode(SourceRejectCompositeAdapter(Child(reject_from=0, dirty=True), "test", 4), route())
    with pytest.raises(ExecutionContractError, match="self-contained"):
        encode(SourceRejectCompositeAdapter(Child(external=8), "test", 4), route())


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "payload_tail",
        "negative_offset",
        "gap",
        "wrong_count",
        "dtype",
        "unsafe_dtype",
        "raw_offset",
        "raw_shape",
        "raw_bits",
        "raw_reason",
        "input_hash",
        "encoding_type",
        "block_size_type",
        "huge_shape",
        "ledger",
        "empty_replay",
    ],
)
def test_malformed_frames_fail_closed(mutation):
    adapter = SourceRejectCompositeAdapter(Child(reject_from=0), "test", 4)
    stream, _, _, _ = encode(adapter, route(4, 1))
    magic, header, payload = frame(stream)
    block = header["blocks"][0]
    raw = block["raw_descriptors"][0]
    if mutation == "unknown":
        header["unregistered"] = True
    elif mutation == "payload_tail":
        payload += b"undeclared"
    elif mutation == "negative_offset":
        block["offset"] = -1
    elif mutation == "gap":
        block["offset"] = 1
    elif mutation == "wrong_count":
        block["count"] = 3
    elif mutation == "dtype":
        header["buffers"][0]["dtype"] = "<f4"
    elif mutation == "unsafe_dtype":
        header["buffers"][0]["dtype"] = {"object": True}
    elif mutation == "raw_offset":
        raw["offset"] = -1
    elif mutation == "raw_shape":
        raw["shape"] = [100_000_000_000]
    elif mutation == "raw_bits":
        raw["logical_bits"] = 0
    elif mutation == "raw_reason":
        block["rejection"] = None
    elif mutation == "input_hash":
        block["input_sha256"] = "0" * 64
    elif mutation == "encoding_type":
        block["encoding"] = []
    elif mutation == "block_size_type":
        header["block_rows"] = True
    elif mutation == "huge_shape":
        header["buffers"][0]["shape"] = [2**62]
    elif mutation == "ledger":
        block["encoding"] = "CODEC"
        block["rejection"] = block["raw_descriptors"] = None
        block["child_ledger"] = {}
    elif mutation == "empty_replay":
        header["n"] = block["count"] = 0
        header["canonical_raw_bits"] = header["buffers"][0]["logical_bits"] = 0
        header["buffers"][0]["shape"] = [0]
    session = adapter.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.decompress(rebuild(magic, header, payload))
    finally:
        session.close()


def test_raw_payload_rehash_cannot_replace_original_input_hash():
    adapter = SourceRejectCompositeAdapter(Child(reject_from=0), "test", 4)
    stream, _, _, _ = encode(adapter, route(4, 1))
    magic, header, payload = frame(stream)
    payload = bytes([payload[0] ^ 1]) + payload[1:]
    header["blocks"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    header["blocks"][0]["raw_descriptors"][0]["sha256"] = hashlib.sha256(payload).hexdigest()
    with pytest.raises(ExecutionContractError, match="block hash"):
        adapter.create_session({}).decompress(rebuild(magic, header, payload))


def test_all_block_metadata_is_validated_before_output_allocation_or_native_decode(monkeypatch):
    child = Child()
    adapter = SourceRejectCompositeAdapter(child, "test", 4)
    stream, _, _, _ = encode(adapter, route(8, 1))
    magic, header, payload = frame(stream)
    header["blocks"][-1]["offset"] = -1

    def premature_allocation(*args, **kwargs):
        raise AssertionError("output allocated before complete metadata validation")

    monkeypatch.setattr(np, "empty", premature_allocation)
    with pytest.raises(ExecutionContractError):
        adapter.create_session({}).decompress(rebuild(magic, header, payload))
    assert child.decode_calls == 0


def test_capacity_failure_does_not_publish_partial_output():
    adapter = SourceRejectCompositeAdapter(Child(reject_from=0), "test", 4)
    session = adapter.create_session({})
    destination = bytearray([0xA5] * 10)
    with pytest.raises(OutputCapacityError):
        session.compress_update(route(4, 1), memoryview(destination))
    assert destination == bytearray([0xA5] * 10)
    session.close()


def test_empty_codec_lifecycle_is_strict_and_restores_owned_empty_buffers():
    adapter = SourceRejectCompositeAdapter(Child(), "test", 4)
    original = route(0, 2)
    stream, ledger, telemetry, _ = encode(adapter, original)
    assert ledger.canonical_raw_bits == 0 and telemetry["codec_block_count"] == 1
    decoded = adapter.create_session({}).decompress(stream)
    assert hash_logical_buffers(decoded.buffers) == original.input_sha256
    session = adapter.create_session({})
    destination = memoryview(bytearray(session.output_bound(original)))
    session.compress_update(original, destination)
    session.finalize(destination)
    with pytest.raises(ExecutionContractError):
        session.finalize(destination)
    with pytest.raises(ExecutionContractError):
        session.compress_update(original, destination)
    session.close()


@pytest.mark.parametrize("random_bits", [False, True])
def test_real_alp_multiblock_codec_and_source_raw_restore_all_rows(random_bits):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("alp")
    artifact = ROOT / manifest.document["adapter"]["artifact_path"]
    if not artifact.is_file():
        pytest.skip("ALP binary is unavailable")
    adapter = SourceRejectCompositeAdapter(
        AlpAdapter(artifact, manifest.document["adapter"], "alp"), "alp"
    )
    values = np.arange(102401, dtype="<f8") / 10
    if random_bits:
        values = (
            np.random.default_rng(20260920).integers(0, 2**64, len(values), dtype="<u8").view("<f8")
        )
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    original = RoutedInput(
        "dataset:real-alp",
        BenchmarkTrack.VALUE,
        buffers,
        None,
        None,
        len(values),
        1,
        values.nbytes * 8,
        hash_logical_buffers(buffers),
    )
    result = perform_roundtrip(adapter, original, {})
    assert result.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert result.encoded.ledger.canonical_raw_bits == values.nbytes * 8
    assert result.encoded.ledger.final_bits == len(result.encoded.stream) * 8
    assert result.input_immutable and result.canary_intact
    _, header, _ = frame(result.encoded.stream)
    assert [b["count"] for b in header["blocks"]] == [102400, 1]
    assert any(b["encoding"] == ("RAW" if random_bits else "CODEC") for b in header["blocks"])
