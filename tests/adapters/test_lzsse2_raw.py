import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters import Lzsse2RawAdapter
from tscompbench.adapters.lzsse2_raw import Lzsse2RawSession
from tscompbench.codecs import CodecRegistry, SourceRegistry, validate_onboarding_card
from tscompbench.contracts import BenchmarkTrack
from tscompbench.execution.protocol import ExecutionContractError, LogicalBuffer, RoutedInput
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.validation import run_boundary_suite

ROOT = Path(__file__).resolve().parents[2]


def adapter():
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("lzsse2-raw")
    return Lzsse2RawAdapter(
        ROOT / manifest.document["adapter"]["artifact_path"], manifest.document["adapter"]
    ), manifest


def route(n, pattern):
    rng = np.random.default_rng(20260918)
    bits = (
        rng.integers(0, 2**64, size=n, dtype="<u8")
        if pattern == "random"
        else np.resize(
            np.array(
                [
                    0,
                    0x8000000000000000,
                    1,
                    0x7FF0000000000000,
                    0xFFF0000000000000,
                    0x7FF8000000000001,
                    0x7FF8000000000123,
                    0x3FF0000000000001,
                ],
                dtype="<u8",
            ),
            n,
        )
    )
    values = bits.view("<f8")
    values.flags.writeable = False
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    return RoutedInput(
        dataset_id="dataset:lzsse2",
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=n,
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )


def reference_decode(stream, n):
    if len(stream) == n:
        return stream
    output = bytearray(stream[:3])
    cursor = 3
    offset = 3
    carry = False
    while len(output) < n - 16:
        controls = stream[cursor : cursor + 16]
        assert len(controls) == 16
        cursor += 16
        for k in range(32):
            control = (controls[k // 2] >> (4 * (k % 2))) & 15
            literal = not carry and control < 2
            count = control if carry else control + 1
            if not carry and not literal:
                offset ^= struct.unpack_from("<H", stream, cursor)[0]
                cursor += 2
            assert 3 <= offset <= len(output)
            for _ in range(count):
                value = output[-offset]
                if literal:
                    value ^= stream[cursor]
                    cursor += 1
                output.append(value)
            carry = control == 15
            if len(output) == n - 16:
                break
    assert cursor == len(stream) - 16
    output.extend(stream[cursor:])
    assert len(output) == n
    return bytes(output)


@pytest.mark.parametrize(
    "n", [0, 1, 2, 3, 4, 7, 8, 9, 31, 32, 33, 63, 64, 65, 511, 512, 513, 4095, 4096, 4097]
)
@pytest.mark.parametrize("pattern", ["random", "ieee"])
def test_roundtrip_independent_scalar_decode_and_accounting(n, pattern):
    driver, _ = adapter()
    routed = route(n, pattern)
    result = perform_roundtrip(driver, routed, {})
    header, stream = Lzsse2RawSession._parse_container(result.encoded.stream)
    assert header["schema_version"] == "tscb.lzsse2-raw-container.v1"
    assert header["raw_storage"] == int(len(stream) == n * 8)
    assert reference_decode(stream, n * 8) == routed.buffers[0].array.tobytes()
    assert (
        result.decoded.by_name()["value/000000"].array.tobytes()
        == routed.buffers[0].array.tobytes()
    )
    assert result.encoded.ledger.final_bits == len(result.encoded.stream) * 8
    assert result.encoded.ledger.external_side_information_bits == 0
    assert result.encoded.finalize_bytes == 0
    assert result.canary_intact and result.input_immutable and result.determinism_match


@pytest.mark.parametrize("track", [BenchmarkTrack.TIMESTAMP, BenchmarkTrack.VALUE])
def test_both_track_boundary_gates(track):
    driver, manifest = adapter()
    report = run_boundary_suite(driver, manifest, track, {"block_size": 8, "isa": "SSE4_1"})
    assert report.passed, [x for x in report.observations if x.status != "PASS"]


def test_source_closure_patch_and_admission_card():
    _, manifest = adapter()
    source = json.loads((ROOT / "registry/sources/lzsse2-raw-lzbench.artifact.json").read_text())
    closure = hashlib.sha256()
    base = ROOT / "adapters/lzsse2_raw/vendor/lzsse"
    files = sorted(p for p in base.rglob("*") if p.is_file())
    assert len(files) == 5
    for file in files:
        closure.update(file.relative_to(base).as_posix().encode() + b"\0" + file.read_bytes())
    assert closure.hexdigest() == source["identity"]["source_closure_sha256"]
    patch = ROOT / source["build"]["patches"][0]["path"]
    assert hashlib.sha256(patch.read_bytes()).hexdigest() == source["identity"]["patch_sha256"]
    card = json.loads((ROOT / "registry/onboarding/lzsse2-raw.json").read_text())
    assert validate_onboarding_card(card)["source_artifact_id"] == manifest.source_artifact_id
    assert len(card["builds"]) == 2


@pytest.mark.parametrize("mutation", ["truncate", "trailing", "concat", "bad_offset", "header"])
def test_malformed_streams_rejected_without_native_decode(mutation):
    driver, _ = adapter()
    result = perform_roundtrip(driver, route(512, "ieee"), {})
    _, payload = Lzsse2RawSession._parse_container(result.encoded.stream)
    assert len(payload) < 4096
    prefix = result.encoded.stream[: -len(payload)]
    damaged = {
        "truncate": payload[:-1],
        "trailing": payload + b"\0",
        "concat": payload + payload,
        "bad_offset": payload[:3] + b"\xff" * 16 + b"\xff\xff" + payload[21:],
    }
    stream = prefix + damaged.get(mutation, payload)
    if mutation == "header":
        stream = b"\0" + stream[1:]
    session = driver.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.decompress(stream)
        assert session.native_timing() == (0, 0)
    finally:
        session.close()


@pytest.mark.parametrize(
    "parameters",
    [
        {"compression_level": 1},
        {"compression_level": 17},
        {"content_checksum": True},
        {"isa": "SCALAR"},
        {"compression_level": "12"},
        {"native_timing": "true"},
    ],
)
def test_unregistered_variants_rejected(parameters):
    driver, _ = adapter()
    with pytest.raises(ExecutionContractError):
        driver.create_session(parameters)


@pytest.mark.parametrize("mutation", [
    "negative_shape", "bool_shape", "bad_rank", "dtype", "length", "logical_bits",
    "duplicate", "limit", "raw_bool", "raw_mismatch", "not_object", "wrong_variant",
])
def test_invalid_descriptors_and_variant_rejected_before_decode(mutation):
    driver, _ = adapter()
    encoded = perform_roundtrip(driver, route(512, "ieee"), {}).encoded.stream
    header, payload = Lzsse2RawSession._parse_container(encoded)
    item = header["buffers"][0]
    if mutation == "negative_shape":
        item["shape"] = [-1]
    elif mutation == "bool_shape":
        item["shape"] = [True]
    elif mutation == "bad_rank":
        item["shape"] = []
    elif mutation == "dtype":
        item["dtype"] = "O"
    elif mutation == "length":
        item["payload_bytes"] += 1
    elif mutation == "logical_bits":
        item["logical_bits"] -= 1
    elif mutation == "duplicate":
        header["buffers"].append(dict(item))
    elif mutation == "limit":
        item.update(shape=[268435456], payload_bytes=2147483648, logical_bits=17179869184)
    elif mutation == "raw_bool":
        header["raw_storage"] = False
    elif mutation == "raw_mismatch":
        header["raw_storage"] = 1
    elif mutation == "not_object":
        header = []
    elif mutation == "wrong_variant":
        header["schema_version"] = "tscb.lzsse8-raw-container.v1"
    metadata = json.dumps(header).encode()
    damaged = struct.pack("<8sI", b"TSCBLS2\x00", len(metadata)) + metadata + payload
    session = driver.create_session({})
    try:
        with pytest.raises(ExecutionContractError):
            session.decompress(damaged)
        assert session.native_timing() == (0, 0)
    finally:
        session.close()


def test_handcrafted_two_literal_and_carried_match_format():
    # Independent wire fixture: 3 roots, seven 2-byte XOR literals, then a 95-byte match.
    controls = [1] * 7 + [15] * 6 + [4] + [0] * 18
    block = bytes(controls[k] | (controls[k + 1] << 4) for k in range(0, 32, 2))
    payload = b"A" * 3 + block + b"\x00" * 14 + struct.pack("<H", 3 ^ 16) + b"A" * 16
    assert len(payload) == 51
    assert reference_decode(payload, 128) == b"A" * 128
    header = {
        "schema_version": "tscb.lzsse2-raw-container.v1", "raw_storage": 0,
        "track": "VALUE", "segment_plan_id": None,
        "buffers": [{"dtype": "|u1", "shape": [128], "payload_bytes": 128,
                     "logical_bits": 1024, "name": "value/000000"}],
    }
    metadata = json.dumps(header).encode()
    stream = struct.pack("<8sI", b"TSCBLS2\x00", len(metadata)) + metadata + payload
    driver, _ = adapter()
    session = driver.create_session({})
    try:
        assert session.decompress(stream).buffers[0].array.tobytes() == b"A" * 128
    finally:
        session.close()
