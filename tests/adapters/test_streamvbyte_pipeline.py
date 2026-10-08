from __future__ import annotations

import copy
import itertools
import json
from pathlib import Path

import numpy as np
import pytest
from test_streamvbyte import routed

from tscompbench.adapters.factory import create_adapter
from tscompbench.adapters.streamvbyte import StreamVByteAdapter
from tscompbench.adapters.streamvbyte_modern import ModernStreamVByteAdapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.execution.repetition import _accumulate_stage_timings, perform_roundtrip
from tscompbench.preprocess import PreprocessContractError, build_preprocess_plan
from tscompbench.preprocess.runtime import validate_pipeline_stages
from tscompbench.preprocess.streamvbyte import validate_stage_snapshot

ROOT = Path(__file__).resolve().parents[2]
KEYS = ("delta-zigzag-streamvbyte64", "delta-zigzag-streamvbyte-modern64")


@pytest.fixture(params=KEYS)
def key(request):
    return request.param


def adapter(key):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    return create_adapter(ROOT, registry.get(key))


@pytest.mark.parametrize("abc", tuple(itertools.product((False, True), repeat=3)))
@pytest.mark.parametrize("n", [0, 1, 2, 33, 129])
def test_switch_combinations_independent_stage_oracles_and_fresh_decode(abc, n, key):
    flags = dict(zip(("stage_a", "stage_b", "stage_c"), abc, strict=True))
    values = np.arange(n, dtype="<i8") * -129 + 1700000000123456789
    item = routed(values, key)
    codec = adapter(key)
    assert validate_pipeline_stages(codec, item, flags)["status"] == "PASS"
    observation = perform_roundtrip(codec, item, flags)
    decoder = codec.create_session({})  # Stream switches override decoder defaults.
    try:
        assert (
            decoder.decompress(observation.encoded.stream).buffers[0].array.tobytes()
            == values.tobytes()
        )
    finally:
        decoder.close()
    encode = observation.codec_telemetry["encode"]["pipeline_stages"]
    assert sum(stage["final_contribution_bits"] for stage in encode["stages"].values()) == (
        observation.encoded.ledger.final_bits
    )
    assert (
        observation.timing.native_encode_wall_ns is None
        if not abc[2]
        else (observation.timing.native_encode_wall_ns is not None)
    )


def test_default_staged_native_payload_matches_original_monolithic_path(key):
    codec = adapter(key)
    factory = ModernStreamVByteAdapter if "modern" in key else StreamVByteAdapter
    monolithic = factory(codec.library_path, codec.manifest_adapter, key)
    for n in (0, 1, 2, 33, 129, 8193):
        item = routed(np.arange(n, dtype="<i8") * 3600000000000 + 1700000000123456789, key)
        snapshot = codec.inspect_preprocess(item, {})
        baseline = perform_roundtrip(monolithic, item, {}).encoded.stream
        import struct

        offset = 44 + struct.unpack_from("<I", baseline, 8)[0]
        actual_offset = 44 + len(snapshot["descriptor"])
        assert baseline[offset:] == snapshot["stream"][actual_offset:]


@pytest.mark.parametrize("field", ["A", "B", "C", "inverse_A", "inverse_B", "inverse_C", "seed"])
def test_independent_validator_detects_corrupt_intermediate_stage(field, key):
    snapshot = adapter(key).inspect_preprocess(routed(np.array([1, 2, 99], dtype="<i8"), key), {})
    snapshot = copy.deepcopy(snapshot)
    if field == "seed":
        snapshot[field] += 1
    elif field == "C":
        snapshot[field] = snapshot[field][:-1] + bytes([snapshot[field][-1] ^ 1])
    else:
        snapshot[field].flags.writeable = True
        snapshot[field][0] += 1
    with pytest.raises(PreprocessContractError):
        validate_stage_snapshot(snapshot, executor_id=adapter(key).pipeline_executor_id)


def test_stage_timing_toggle_does_not_change_stream_and_totals_cover_every_iteration(key):
    codec = adapter(key)
    item = routed(np.array([0, 1, 1, -7, 99], dtype="<i8"), key)
    on = perform_roundtrip(codec, item, {"stage_timing": True})
    off = perform_roundtrip(codec, item, {"stage_timing": False})
    assert on.encoded.stream == off.encoded.stream
    telemetry = on.codec_telemetry["encode"]
    total = _accumulate_stage_timings(None, telemetry, 0)
    total = _accumulate_stage_timings(total, telemetry, 1)
    for slot in "ABCD":
        assert (
            total["stages"][slot]["wall_ns"]
            == 2 * telemetry["pipeline_stages"]["stages"][slot]["wall_ns"]
        )
        assert total["stages"][slot]["observation_count"] == 2
    assert _accumulate_stage_timings(total, None, 2) is None
    assert _accumulate_stage_timings(None, telemetry, 3) is None
    assert all(
        stage["wall_ns"] is None
        for stage in off.codec_telemetry["encode"]["pipeline_stages"]["stages"].values()
    )


def test_disabled_delta_accepts_full_i64_bits_and_resolved_plan_keeps_switches(key):
    codec = adapter(key)
    item = routed(np.array([-(2**63), 2**63 - 1, -(2**63)], dtype="<i8"), key)
    result = perform_roundtrip(codec, item, {"stage_a": False})
    assert result.decoded.buffers[0].array.tobytes() == item.buffers[0].array.tobytes()
    manifest = json.loads((ROOT / f"registry/codecs/{key}.json").read_text())
    plan = build_preprocess_plan(manifest, {"stage_a": False, "stage_b": False})
    assert not plan.stages[0].enabled and not plan.stages[1].enabled
    assert plan.semantic_class.value == "NONE"
