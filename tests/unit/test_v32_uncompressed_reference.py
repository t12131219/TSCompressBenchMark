from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import audit_v32_uncompressed_reference as baseline

from tscompbench.datasets import DatasetRegistry, load_dataset, write_canonical
from tscompbench.execution.protocol import LogicalBuffer
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.pipelines import LogicalObject, LogicalObjectSchema

ROOT = Path(__file__).resolve().parents[2]


def _logical():
    values = {
        "nd": np.arange(12, dtype=np.int16).reshape(2, 6),
        "speed": np.arange(6, dtype=np.float64) / 3,
    }
    values["speed"].view(np.uint64)[0] = 0x7FF8000000000042
    descriptions = [
        {
            "name": name,
            "dtype": value.dtype.str,
            "shape": list(value.shape),
            "axes": ["feature", "time"] if name == "nd" else ["time"],
            "time_axis": 1 if name == "nd" else 0,
            "unit": "counts",
            "entity": "device",
            "feature": name,
        }
        for name, value in values.items()
    ]
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": descriptions,
            "timestamp": {
                "present": True,
                "dtype": "<i8",
                "unit": "ns",
                "epoch": "unix",
                "pairing": "SHARED_TIME_AXIS",
            },
            "null_recovery_contract": "BITWISE",
        }
    )
    masks = {name: np.ones(value.shape, np.bool_) for name, value in values.items()}
    masks["speed"][1] = False
    return LogicalObject(schema, values, np.array([0, 2, 2, -1, 5, 7], dtype="<i8"), masks)


def _configure(tmp_path, monkeypatch, lane, *, native=False, timestamp=False):
    original = _logical()
    if lane != "pipeline":
        datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
        original = write_canonical(
            load_dataset(datasets.load("national_illness")), tmp_path / "original.tscb"
        )
        from tscompbench.datasets import read_canonical

        original = read_canonical(original.path)
    row = {
        "key": "original",
        "original": original,
        "source": {"path": "original"},
        "track": "COMPLETE_LOGICAL_OBJECT"
        if lane == "pipeline"
        else "TIMESTAMP"
        if timestamp
        else "VALUE",
        "cost_boundary": "NATIVE_COMPONENT" if native else "SCHEMA_BOUND_OBJECT",
        "native_input_sizes": [{"scope": "NATIVE_INPUT_SIZE_ONLY", "input_payload_bytes": 64}]
        if native
        else [],
    }
    monkeypatch.setattr(baseline, "_inputs", lambda path, chosen: ({"test_input": "bound"}, [row]))
    monkeypatch.setattr(baseline, "control_plane_snapshot", lambda root: {"test": "stable"})
    run_path = tmp_path / "run"
    run_path.mkdir()
    return run_path, original


@pytest.mark.parametrize("lane", ["comparison", "workload", "pipeline"])
def test_complete_size_reference_pays_metadata_and_restores_public_raw_object(
    tmp_path,
    monkeypatch,
    lane,
):
    run, original = _configure(tmp_path, monkeypatch, lane)
    document = baseline.write_uncompressed_reference(run, lane)
    reference = document["objects"][0]["matched_boundary_reference"]
    ledger = reference["ledger"]
    assert document["status"] == "UNCOMPRESSED_REFERENCE_AUDIT"
    assert document["baseline_kind"] == "SIZE_BASELINE"
    assert document["formal_eligible"] is False
    assert document["performance_remeasured"] is False
    assert document["audit_id"] == document["reference_id"]
    assert document["codec_invoked"] is False
    assert document["statistical_method_count"] == 0
    assert document["performance"] is None and document["performance_unavailable_reason"]
    assert reference["can_compare_to_formal_final_bits"] is True
    assert ledger["final_bits"] == ledger["serialized_bits"] + ledger["required_external_bits"]
    assert ledger["metadata_and_frame_bits"] > 0
    assert ledger["required_external_bits"] > 0
    assert ledger["final_bits"] > ledger["canonical_raw_bits"]
    before = {path: path.read_bytes() for path in run.rglob("*") if path.is_file()}
    assert baseline.validate_uncompressed_reference(run, lane) == document
    assert before == {path: path.read_bytes() for path in before}
    assert baseline.write_uncompressed_reference(run, lane) == document
    if lane == "pipeline":
        assert reference["schema_id"] == original.schema.schema_id
        assert reference["content_id"] == original.content_id
        assert reference["underlying_bytes_sha256"] == original.underlying_bytes_sha256


def test_native_component_does_not_compare_complete_object_storage_cost(tmp_path, monkeypatch):
    run, _ = _configure(tmp_path, monkeypatch, "comparison", native=True)
    document = baseline.write_uncompressed_reference(run, "comparison")
    row = document["objects"][0]
    assert row["complete_object_reference"]["can_compare_to_formal_final_bits"] is False
    assert row["matched_boundary_reference"]["can_compare_to_formal_final_bits"] is False
    assert row["native_input_sizes"][0]["input_payload_bytes"] == 64
    assert document["native_component_vs_complete_object_cost_comparable"] is False


def test_timestamp_reference_preserves_task_scope_without_free_value_carrier(tmp_path, monkeypatch):
    run, original = _configure(tmp_path, monkeypatch, "comparison", timestamp=True)
    document = baseline.write_uncompressed_reference(run, "comparison")
    row = document["objects"][0]
    reference = row["matched_boundary_reference"]
    context = reference["paid_context"]
    assert context["track"] == "TIMESTAMP"
    assert [buffer["name"] for buffer in context["buffers"]] == ["timestamp"]
    assert (
        reference["ledger"]["canonical_raw_bits"]
        == original.metadata["accounting"]["timestamp_raw_bits"]
    )
    assert context["excluded_track_buffers"]
    assert row["complete_object_reference"]["can_compare_to_formal_final_bits"] is False


def test_public_track_reader_only_needs_two_paid_artifacts(tmp_path, monkeypatch):
    run, _ = _configure(tmp_path, monkeypatch, "comparison", timestamp=True)
    doc = baseline.write_uncompressed_reference(run, "comparison")
    reference = doc["objects"][0]["matched_boundary_reference"]
    recovered = baseline.read_uncompressed_track(
        Path(reference["artifact"]["path"]), Path(reference["required_context"]["path"])
    )
    assert [buffer.name for buffer in recovered] == ["timestamp"]
    assert all(
        buffer.array.flags.owndata and not buffer.array.flags.writeable for buffer in recovered
    )
    assert hash_logical_buffers(recovered) == reference["input_sha256"]


@pytest.mark.parametrize("field", ["name", "dtype", "shape", "logical_bits", "unit"])
def test_public_track_reader_rejects_tampered_paid_context(tmp_path, monkeypatch, field):
    run, _ = _configure(tmp_path, monkeypatch, "comparison", timestamp=True)
    doc = baseline.write_uncompressed_reference(run, "comparison")
    reference = doc["objects"][0]["matched_boundary_reference"]
    context = Path(reference["required_context"]["path"])
    data = json.loads(context.read_bytes())
    if field == "unit":
        data["timestamp_unit"] = "seconds"  # Context ID binds semantic metadata too.
    elif field == "name":
        data["buffers"][0]["name"] = "value/hidden"
    elif field == "dtype":
        data["buffers"][0]["dtype"] = "<f8"
    elif field == "shape":
        data["buffers"][0]["shape"] = [10**30]
    else:
        data["buffers"][0]["logical_bits"] += 1
    # For structural shape/name/dtype/bits attacks also try recomputing context
    # ID; the paid NPY header and Track constraints must still reject them.
    if field != "unit":
        identity = {key: value for key, value in data.items() if key != "context_id"}
        data["context_id"] = stable_id("uncompressed-track-context-v32", identity)
    context.write_bytes(canonical_json_bytes(data) + b"\n")
    with pytest.raises(ValueError):
        baseline.read_uncompressed_track(Path(reference["artifact"]["path"]), context)


def test_public_track_reader_restores_empty_original_timestamp_without_fake_values(tmp_path):
    empty = np.empty(0, dtype="<i8")
    frame = tmp_path / "empty.npz"
    frame.write_bytes(baseline._npz({"buffer_0": empty}))
    document = {
        "schema_version": "tscb.uncompressed-track-context.v1",
        "dataset_id": "empty-test-task",
        "track": "TIMESTAMP",
        "logical_descriptor": {
            "n_rows": 0,
            "timestamp": {
                "present": True,
                "unit": "ns",
                "epoch": "unix",
                "origin": "MANIFEST_CONSTRUCTED",
            },
        },
        "n": 0,
        "m": 1,
        "input_sha256": hash_logical_buffers((LogicalBuffer("timestamp", empty, 0),)),
        "canonical_raw_bits": 0,
        "timestamp_unit": "ns",
        "timestamp_epoch": "unix",
        "value_units": [],
        "pairing_reference_sha256_provenance_only": None,
        "buffers": [
            {
                "wire_name": "buffer_0",
                "name": "timestamp",
                "dtype": "<i8",
                "shape": [0],
                "logical_bits": 0,
            }
        ],
        "excluded_track_buffers": [],
        "excluded_payload_is_not_required_to_restore_selected_track": True,
        "artifact_sha256": baseline._sha(frame.read_bytes()),
    }
    document["context_id"] = stable_id("uncompressed-track-context-v32", document)
    context = tmp_path / "empty.context.json"
    context.write_bytes(canonical_json_bytes(document) + b"\n")
    recovered = baseline.read_uncompressed_track(frame, context)
    assert len(recovered) == 1 and recovered[0].name == "timestamp"
    assert recovered[0].array.shape == (0,) and recovered[0].logical_bits == 0


@pytest.mark.parametrize("allowed", [True, False])
def test_only_expected_missing_timestamp_extension_can_omit_matched_baseline(
    tmp_path,
    monkeypatch,
    allowed,
):
    source = ROOT / "artifacts/comparisons/v32_20261010/sources/v32_dev_f64_random_m3.tscb"
    from tscompbench.datasets import read_canonical

    original = read_canonical(source)
    assert "timestamp" not in original.buffers
    row = {
        "key": "explicit-missing-T",
        "original": original,
        "source": baseline._binding(source),
        "track": "TIMESTAMP",
        "cost_boundary": "SCHEMA_BOUND_OBJECT",
        "native_input_sizes": [],
        "allow_missing_timestamp": allowed,
    }
    monkeypatch.setattr(baseline, "_inputs", lambda path, lane: ({"test": "frozen"}, [row]))
    run = tmp_path / "run"
    run.mkdir()
    if allowed:
        document = baseline.write_uncompressed_reference(run, "comparison")
        matched = document["objects"][0]["matched_boundary_reference"]
        assert matched["status"] == "NOT_APPLICABLE"
        assert matched["reason"] == "TIMESTAMP_UNAVAILABLE_EXPECTED_EXTENSION"
        assert matched["ledger"] is None
    else:
        with pytest.raises(ValueError, match="legal/core"):
            baseline.write_uncompressed_reference(run, "comparison")


@pytest.mark.parametrize(
    "damage",
    [
        "metadata_free",
        "context_changed",
        "artifact_changed",
        "artifact_missing",
        "performance_fabricated",
        "native_comparable",
    ],
)
def test_recomputed_reference_id_cannot_hide_free_metadata_or_changed_saved_bytes(
    tmp_path,
    monkeypatch,
    damage,
):
    run, _ = _configure(tmp_path, monkeypatch, "pipeline")
    baseline.write_uncompressed_reference(run, "pipeline")
    path = run / "uncompressed_reference.json"
    document = json.loads(path.read_bytes())
    reference = document["objects"][0]["matched_boundary_reference"]
    if damage == "metadata_free":
        reference["ledger"]["required_external_bits"] = 0
    elif damage == "context_changed":
        context = Path(reference["required_context"]["path"])
        data = json.loads(context.read_bytes())
        data["schema"]["timestamp"]["unit"] = "seconds"
        context.write_bytes(canonical_json_bytes(data) + b"\n")
    elif damage == "artifact_changed":
        artifact = Path(reference["artifact"]["path"])
        artifact.write_bytes(artifact.read_bytes() + b"hidden")
    elif damage == "artifact_missing":
        Path(reference["artifact"]["path"]).unlink()
    elif damage == "performance_fabricated":
        document["performance"] = {"encode_MB_s": 999}
    else:
        document["native_component_vs_complete_object_cost_comparable"] = True
    identity = {key: value for key, value in document.items() if key != "reference_id"}
    document["reference_id"] = stable_id("uncompressed-object-reference-v32", identity)
    path.write_bytes(canonical_json_bytes(document) + b"\n")
    with pytest.raises(ValueError):
        baseline.validate_uncompressed_reference(run, "pipeline")


def test_missing_reference_cannot_be_silently_created_by_read_only_validation(
    tmp_path, monkeypatch
):
    run, _ = _configure(tmp_path, monkeypatch, "pipeline")
    baseline.write_uncompressed_reference(run, "pipeline")
    directory = run / "reference_artifacts"
    for path in directory.iterdir():
        path.unlink()
    with pytest.raises(ValueError, match="missing"):
        baseline.validate_uncompressed_reference(run, "pipeline")
    assert not list(directory.iterdir())
