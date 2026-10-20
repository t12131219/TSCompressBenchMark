"""Real native evidence; run after `python -m tsbench build --all`."""
from pathlib import Path

import numpy as np
import pytest

from tsbench.build import artifact_path
from tsbench.registry import Registry, UnsupportedError

ROOT = Path(__file__).resolve().parents[2]


def native(key):
    if not artifact_path(ROOT, key).is_file():
        pytest.skip(f"native artifact not built: {key}; run tsbench build {key}")
    from tsbench.bridges import create_bridge
    return create_bridge(ROOT, key), Registry(ROOT).resolve_params(key)


@pytest.mark.parametrize("key", ["zstd-frame", "snappy-raw"])
@pytest.mark.parametrize("length", [0, 1, 257, 1024])
def test_native_finished_frame_and_exact_tail(key, length):
    bridge, params = native(key)
    original = (np.arange(length) % 251).astype(np.uint8)
    before = original.tobytes()
    payload = bridge.encode(original, params)
    assert isinstance(payload, bytes)
    restored = bridge.decode(payload, original.dtype, original.shape, params)
    assert restored.dtype == original.dtype and restored.shape == original.shape
    assert restored.tobytes() == before
    assert original.tobytes() == before
    # Two independent operations on one Python bridge must not inherit encoder
    # session state. Zstd must finish each frame before it can be decoded.
    payload2 = bridge.encode(original, params)
    assert bridge.decode(payload2, original.dtype, original.shape, params).tobytes() == before


def test_rw_abba_frame_restores_original_grid_without_encoder_model(tmp_path):
    bridge, params = native("abba")
    original = np.arange(17, dtype=np.float64) / 8
    before = original.tobytes()
    payload = bridge.encode(original, params)
    restored = bridge.decode(payload, original.dtype, original.shape, {})
    assert restored.dtype == original.dtype and restored.shape == original.shape
    assert np.isfinite(restored).all()
    assert original.tobytes() == before
    assert payload  # Complete RW frame, not a symbolic-only intermediated value.


def test_rw_abba_rejects_nonfinite_source_domain():
    bridge, params = native("abba")
    with pytest.raises(UnsupportedError):
        bridge.encode(np.array([0., np.inf]), params)


def test_compiled_c_reference_matches_bridge_payload_and_abi(tmp_path):
    import importlib.util
    import shutil
    if not shutil.which("cc"):
        pytest.skip("C compiler unavailable")
    for key in ("zstd-frame", "snappy-raw"):
        native(key)
    spec = importlib.util.spec_from_file_location("native_crosscheck", ROOT / "benchmark/tools/native_crosscheck.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    evidence = module.crosscheck(ROOT, tmp_path / "evidence.json")
    assert evidence["passed"] and len(evidence["cases"]) == 6
    assert all(row["buffer_struct_size_equal"] for row in evidence["cases"])
    assert all(row["buffer_field_offsets_equal"] and row["native_timing_layout_equal"] for row in evidence["cases"])
    zstd = next(row for row in evidence["cases"] if row["codec"] == "zstd-frame" and row["input_length"] == 257)
    assert zstd["finalize_bytes"] > 0  # The reference verifies the real Finish tail.
