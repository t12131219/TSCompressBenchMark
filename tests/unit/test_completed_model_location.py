from __future__ import annotations

import pytest

from tscompbench.adapters.completed_rewrites import _registered_model_path
from tscompbench.execution.protocol import ExecutionContractError


@pytest.mark.parametrize(
    "artifact",
    [
        "build/adapters/completed_rewrites/deepzip/release/libdeepzip.so",
        "build/port-standard-v30-20261011/adapters/deepzip/release/libdeepzip.so",
        "build/custom/nested/output/deepzip/release/libdeepzip.so",
    ],
)
def test_model_uses_registered_project_root_for_any_build_depth(tmp_path, artifact):
    model_name = "adapters/completed_rewrites/vendor/deepzip/models/biGRU.dzm"
    model = tmp_path / model_name
    model.parent.mkdir(parents=True)
    model.write_bytes(b"frozen-model")
    resolved = _registered_model_path(
        tmp_path / artifact, {"artifact_path": artifact}, {"path": model_name}
    )
    assert resolved == model
    assert resolved.read_bytes() == b"frozen-model"


@pytest.mark.parametrize("name", [None, "", "/tmp/model", "../model", "bad\0model"])
@pytest.mark.parametrize("field", ["artifact_path", "path"])
def test_model_location_rejects_unsafe_registered_paths(tmp_path, name, field):
    manifest = {"artifact_path": "build/deepzip/release/library.so"}
    record = {"path": "models/biGRU.dzm"}
    (manifest if field == "artifact_path" else record)[field] = name
    with pytest.raises(ExecutionContractError, match="unsafe registered"):
        _registered_model_path(tmp_path / "build/deepzip/release/library.so", manifest, record)


def test_model_location_rejects_artifact_from_another_registered_layout(tmp_path):
    with pytest.raises(ExecutionContractError, match="artifact differs"):
        _registered_model_path(
            tmp_path / "unrelated/library.so",
            {"artifact_path": "build/deepzip/release/library.so"},
            {"path": "models/biGRU.dzm"},
        )


def test_model_location_rejects_symlink_escape(tmp_path):
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "models").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ExecutionContractError, match="escapes project"):
        _registered_model_path(
            root / "build/deepzip/release/library.so",
            {"artifact_path": "build/deepzip/release/library.so"},
            {"path": "models/biGRU.dzm"},
        )
