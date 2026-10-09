from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tscompbench.adapters.completed_rewrites import _PREFIX, _RECORD, CompletedRewriteAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import BenchmarkTrack, LossMode, RunStatus
from tscompbench.datasets import DatasetRegistry, load_dataset, read_canonical, write_canonical
from tscompbench.execution.protocol import ExecutionContractError, SourceDomainError
from tscompbench.execution.repetition import perform_roundtrip
from tscompbench.execution.routing import route_canonical_artifact
from tscompbench.planning.sweep import expand_sweep
from tscompbench.validation.lossy import profile_unbounded_loss

ROOT = Path(__file__).resolve().parents[2]
PROFILES = {
    **{name: ("rewrite_float_mts", "VALUE") for name in ("abba", "fabba", "tristan", "corad")},
    "influxdb-tsm-adaptive-timestamp": ("rewrite_float_mts", "TIMESTAMP"),
    "prometheus-xor2-chunk": ("rewrite_float_mts", "SYSTEM"),
    "deepzip": ("rewrite_byte_uts", "VALUE"),
    "dzip": ("rewrite_byte_uts", "VALUE"),
    "walloc-1d": ("rewrite_audio_stereo", "VALUE"),
    "prometheus-histogram-st": ("rewrite_histogram_int", "SYSTEM"),
    "prometheus-float-histogram-st": ("rewrite_histogram_float", "SYSTEM"),
}


def manifest(name):
    return CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")).get(
        name
    )


def adapter(name):
    doc = manifest(name).document
    return CompletedRewriteAdapter(ROOT / doc["adapter"]["artifact_path"], doc["adapter"], name)


def routed(tmp_path, name):
    key, track = PROFILES[name]
    registry = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    data = load_dataset(registry.load(key))
    artifact = write_canonical(data, tmp_path / (name + ".bin"))
    return route_canonical_artifact(read_canonical(artifact.path), BenchmarkTrack(track))


@pytest.mark.parametrize("name", PROFILES)
def test_native_profile_independent_decode_and_complete_accounting(tmp_path, name):
    original = routed(tmp_path, name)
    codec = adapter(name)
    observation = perform_roundtrip(codec, original, {})
    assert observation.input_immutable and observation.canary_intact
    assert observation.determinism_match
    expected = {b.name: b.array for b in original.buffers}
    decoded = {b.name: b.array for b in observation.decoded.buffers}
    assert expected.keys() == decoded.keys()
    loss_mode = manifest(name).loss_modes[0]
    for key in expected:
        assert expected[key].shape == decoded[key].shape
        assert expected[key].dtype == decoded[key].dtype
        if loss_mode is LossMode.LOSSLESS:
            assert expected[key].tobytes() == decoded[key].tobytes()
        else:
            assert np.all(np.isfinite(decoded[key]))
    ledger = observation.encoded.ledger
    assert ledger.final_bits == len(observation.encoded.stream) * 8
    assert ledger.external_side_information_bits == 0
    assert ledger.accounting_method == "EXACT_CONTAINER_AND_OPAQUE_COMPLETE_NATIVE_FRAMES"
    if original.track is BenchmarkTrack.SYSTEM:
        assert ledger.timestamp_bits == ledger.value_bits == 0
        assert ledger.unallocated_shared_bits > 0


def test_timestamp_boundary_accounting_counts_only_timestamp_elements():
    from tscompbench.validation.boundary import run_boundary_suite

    key = "influxdb-tsm-adaptive-timestamp"
    result = run_boundary_suite(adapter(key), manifest(key), BenchmarkTrack.TIMESTAMP, {})
    assert result.passed, [(o.case_id, o.reason) for o in result.observations if o.status != "PASS"]


def forged(stream, mutate_descriptor=None, mutate_payload=None):
    magic, size, _, _ = _PREFIX.unpack_from(stream)
    descriptor = json.loads(stream[_PREFIX.size : _PREFIX.size + size])
    payload = bytearray(stream[_PREFIX.size + size :])
    if mutate_descriptor:
        mutate_descriptor(descriptor)
    if mutate_payload:
        mutate_payload(payload)
    header = json.dumps(descriptor, separators=(",", ":"), sort_keys=True).encode()
    return (
        _PREFIX.pack(
            magic, len(header), hashlib.sha256(header).digest(), hashlib.sha256(payload).digest()
        )
        + header
        + payload
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d["buffers"][0].update(dtype="<f4"),
        lambda d: d["buffers"][0].update(shape=[160, 3]),
        lambda d: d.update(rows=1 << 60),
        lambda d: d.update(track="SYSTEM"),
        lambda d: d["parameters"].update(unknown=1),
    ],
)
def test_forged_descriptor_rejected_before_native_decode(tmp_path, mutation):
    a = adapter("abba")
    stream = perform_roundtrip(a, routed(tmp_path, "abba"), {}).encoded.stream
    session = a.create_session({})
    session._native = lambda *args, **kwargs: pytest.fail(
        "malformed descriptor reached native decoder"
    )
    with pytest.raises(ExecutionContractError):
        session.decompress(forged(stream, mutation))


def test_forged_capacity_and_truncated_or_corrupt_container_are_rejected(tmp_path):
    a = adapter("abba")
    stream = perform_roundtrip(a, routed(tmp_path, "abba"), {}).encoded.stream
    session = a.create_session({})

    def capacity(payload):
        length, raw = _RECORD.unpack_from(payload)
        _RECORD.pack_into(payload, 0, length, raw + 8)

    with pytest.raises(ExecutionContractError, match="capacity"):
        session.decompress(forged(stream, mutate_payload=capacity))
    for changed in (stream[:-1], stream[:1], stream + b"x", bytes([stream[0] ^ 1]) + stream[1:]):
        with pytest.raises(ExecutionContractError):
            session.decompress(changed)
    session.close()
    with pytest.raises(ExecutionContractError, match="closed"):
        session.decompress(stream)


@pytest.mark.parametrize(
    "name,sweep",
    [
        ("abba", {"min_k": [9], "max_k": [2]}),
        ("fabba", {"scl": ["0"]}),
        ("tristan", {"atoms": [2], "nonzeros": [3]}),
        ("corad", {"correlation_threshold": ["2"]}),
        ("abba", {"compression_tolerance": ["NaN"]}),
    ],
)
def test_invalid_parameter_combinations_are_retained_as_schema_errors(name, sweep):
    result = expand_sweep(manifest(name), sweep)[0]
    assert result.status is RunStatus.SCHEMA_ERROR
    with pytest.raises(ExecutionContractError):
        adapter(name).create_session(result.parameters)


def test_deepzip_all_frozen_model_alphabets_match_native_metadata():
    a = adapter("deepzip")
    for key in a.manifest_adapter["models"]:
        session = a.create_session({"model_key": key})
        session._ensure_model()
        assert session._alphabet_size == 4
        session.close()


def test_source_domain_rejection_is_atomic_and_does_not_remap_bytes(tmp_path):
    a = adapter("deepzip")
    r = routed(tmp_path, "deepzip")
    array = r.buffers[0].array.copy()
    array[0] = 255
    array.flags.writeable = False
    b = replace(r.buffers[0], array=array)
    r = replace(r, buffers=(b,))
    with pytest.raises(SourceDomainError, match="MODEL_ALPHABET_UNSUPPORTED") as error:
        a.create_session({}).output_bound(r)
    assert error.value.rejection_atomic


def test_unbounded_quality_has_no_error_bound_claim():
    x = np.asarray([0.0, 1.0, 2.0])
    y = np.asarray([0.0, 1.1, 1.9])
    report = profile_unbounded_loss({"value/000000": x}, {"value/000000": y}).to_document()
    assert report["bound_passed"] is None
    assert report["raw_violation_count"] is None
    assert report["channels"][0]["rmse"] is not None


def test_embedded_model_decode_does_not_read_external_checkpoint(tmp_path):
    a = adapter("deepzip")
    r = routed(tmp_path, "deepzip")
    stream = perform_roundtrip(a, r, {}).encoded.stream
    session = a.create_session({})
    session._model = b"/this/checkpoint/is/absent"
    decoded = session.decompress(stream)
    assert decoded.buffers[0].array.tobytes() == r.buffers[0].array.tobytes()
    session.close()
