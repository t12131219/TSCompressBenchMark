import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.contracts import RunStatus


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("all_grid", ROOT / "tools/qualify_all_dataset_grids.py")
grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grid)


def test_grid_keeps_every_point_scope_and_duplicate_template_provenance(tmp_path, monkeypatch):
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifest = registry.get("abba")

    class Registry:
        def keys(self):
            return ("abba",)

        def get(self, key):
            assert key == "abba"
            return manifest

    directory = tmp_path / "configs/experiments"
    directory.mkdir(parents=True)
    text = 'algorithms=["abba"]\ntracks=["VALUE"]\n[sweep]\nmax_k=[0,1]\n'
    (directory / "first.toml").write_text(text)
    (directory / "second.toml").write_text(text)
    monkeypatch.setattr(grid, "ROOT", tmp_path)
    points = grid.policies(Registry(), 2)
    assert len(points) == 6
    assert {(p["parameters"]["max_k"], p["profile"]["timing_scope"]) for p in points} == {
        (k, scope) for k in (0, 1) for scope in ("CORE", "PIPELINE", "E2E")
    }
    assert all(len(p["templates"]) == 2 for p in points)
    assert sum(p["config_status"] is RunStatus.SCHEMA_ERROR for p in points) == 3


def test_resource_event_does_not_hide_a_correctness_failure():
    row = {"status": "RESOURCE_PRESSURE", "records": [{"correctness": {"status": "PASS"}}]}
    assert grid.category(row) == "CORRECTNESS_PASS_RESOURCE_EVENT"
    row["records"][0]["correctness"]["status"] = "BOUND_VIOLATION"
    assert grid.category(row) == "EXECUTION_ERROR"


@pytest.mark.parametrize("number", [2, 8])
def test_native_allocation_failure_is_oom_and_other_codec_failures_stay_errors(number):
    from tscompbench.adapters.lzsse2_raw import Lzsse2RawSession
    from tscompbench.adapters.lzsse8_raw import Lzsse8RawSession
    from tscompbench.execution.protocol import ExecutionContractError

    session = object.__new__(Lzsse2RawSession if number == 2 else Lzsse8RawSession)
    session._last_error = lambda: f"LZSSE{number} optimal parse state allocation failed"
    with pytest.raises(MemoryError):
        session._check(4, "compress_update")
    session._last_error = lambda: "invalid native frame"
    with pytest.raises(ExecutionContractError):
        session._check(4, "decompress")


@pytest.mark.parametrize("modern", [False, True])
def test_timestamp_descriptor_does_not_import_wide_value_track_metadata(modern):
    import json

    import numpy as np

    from tscompbench.adapters.streamvbyte_modern import ModernStreamVBytePipelineAdapter
    from tscompbench.adapters.streamvbyte_pipeline import StreamVBytePipelineAdapter
    from tscompbench.contracts import BenchmarkTrack
    from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
    from tscompbench.execution.repetition import perform_roundtrip
    from tscompbench.execution.routing import hash_logical_buffers, hash_reference_array

    key = "delta-zigzag-streamvbyte-modern64" if modern else "delta-zigzag-streamvbyte64"
    path = ROOT / f"build/adapters/{key.replace('-', '_')}/release/libtscb_{key.replace('-', '_')}.so"
    if not path.is_file():
        pytest.skip("native Stream VByte artifact is unavailable")
    values = np.array([1000, 2000, 3000, 4000], dtype="<i8")
    values.flags.writeable = False
    buffers = (LogicalBuffer("timestamp", values, values.nbytes * 8),)
    routed = RoutedInput(
        dataset_id="test:wide-timestamp", track=BenchmarkTrack.TIMESTAMP, buffers=buffers,
        timestamp_reference=values, validity_reference=None, n=4, m=1,
        canonical_raw_bits=256, input_sha256=hash_logical_buffers(buffers),
        timestamp_unit="s", timestamp_epoch="UNIX", value_units=("UNSPECIFIED",) * 862,
        pairing_reference_sha256=hash_reference_array(values),
    )
    codec = (ModernStreamVBytePipelineAdapter if modern else StreamVBytePipelineAdapter)(path, {}, key)
    observation = perform_roundtrip(codec, routed, {})
    assert observation.decoded.buffers[0].array.tobytes() == values.tobytes()
    assert observation.input_immutable and observation.canary_intact and observation.determinism_match
    session = codec.create_session({})
    try:
        header, _ = session._payload(routed)
        assert json.loads(header)["value_units"] == []
        assert session._payload(replace(routed, value_units=()))[0] == header
    finally:
        session.close()
