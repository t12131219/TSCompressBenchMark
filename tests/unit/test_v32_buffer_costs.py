"""Auxiliary observations cannot inflate work, hide costs, or grant qualification."""

from __future__ import annotations

import copy
import hashlib
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

from tscompbench.codecs import CodecRegistry, DataDescriptor, SourceRegistry, negotiate
from tscompbench.comparison.pipeline_runner import save_pipeline_input
from tscompbench.contracts import BenchmarkTrack, Topology, ValidityShape
from tscompbench.execution.preparation import prepare_execution_input
from tscompbench.execution.protocol import LogicalBuffer, RoutedInput
from tscompbench.execution.routing import hash_logical_buffers
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.pipelines import ChildSpec, LogicalObject, LogicalObjectSchema, PipelineRecipe
from tscompbench.pipelines.runtime import _prepare_child

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import audit_v32_buffer_costs as audit  # noqa: E402


def _prepared(values):
    descriptor = DataDescriptor(
        dataset_id="test:auxiliary-cost",
        track=BenchmarkTrack.VALUE,
        topology=Topology.UTS,
        n=values.size,
        m=1,
        shape=values.shape,
        dtype_vector=(values.dtype.str,),
        physical_layout="SOA_COLUMNS",
        endianness="little",
        alignment_bytes=1,
        canonical_raw_bits=values.nbytes * 8,
        validity_shape=ValidityShape.NONE,
        timestamp_present=False,
        preserve_order=True,
        has_duplicates=False,
        has_out_of_order=False,
        has_negative_delta=False,
    )
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    plan = negotiate(registry.get("simdcomp-u32"), descriptor)
    buffers = (LogicalBuffer("value/000000", values, values.nbytes * 8),)
    routed = RoutedInput(
        dataset_id=descriptor.dataset_id,
        track=BenchmarkTrack.VALUE,
        buffers=buffers,
        timestamp_reference=None,
        validity_reference=None,
        n=values.size,
        m=1,
        canonical_raw_bits=values.nbytes * 8,
        input_sha256=hash_logical_buffers(buffers),
    )
    return routed, prepare_execution_input(routed, plan)


def test_widening_preserves_original_denominator_and_separates_instrumentation():
    routed, prepared = _prepared(np.arange(128, dtype="|u1"))
    costs = audit.preparation_costs(routed, prepared)
    assert costs["canonical_raw_bits"]["value"] == 128 * 8
    assert costs["original_payload_bytes"]["value"] == 128
    assert costs["adapted_payload_bytes"]["value"] == 128 * 4
    assert costs["buffers"][0]["original"]["dtype"] == "|u1"
    assert costs["buffers"][0]["adapted"]["dtype"] == "<u4"
    assert costs["adapter_stages"][0]["read_bytes"]["evidence_method"] == "ESTIMATED"
    assert costs["adapter_stages"][0]["allocated_bytes"]["evidence_method"] == "INSTRUMENTED"
    assert "wall_ns" not in str(costs)
    assert costs == audit.preparation_costs(routed, prepared)


def test_native_unknowns_are_never_zero_or_inferred_from_codec_bytes():
    routed, prepared = _prepared(np.arange(128, dtype="|u1"))
    costs = audit.preparation_costs(routed, prepared)
    for value in costs["native"].values():
        assert value["value"] is None
        assert value["evidence_method"] == "UNAVAILABLE"
        assert value["unavailable_reason"]
    assert costs["buffers"][0]["codec_input_bytes"]["value"] == 512
    assert costs["buffers"][0]["native"]["native_input_bytes"]["value"] is None


def test_backing_storage_is_separate_from_noncontiguous_nd_payload():
    backing = np.arange(60, dtype="<i2").reshape(3, 4, 5)
    view = backing[:, ::2, :]
    row = audit.array_cost(view, logical_bits=view.size * 16)
    assert row["effective_bytes"]["value"] == 60
    assert row["backing_storage_bytes"]["value"] == 120
    assert row["effective_elements"]["value"] == 30
    assert row["backing_aggregation"] == "SHARED_BACKINGS_MUST_NOT_BE_SUMMED_PER_VIEW"


@pytest.mark.parametrize(
    "value,method",
    [(0, "UNAVAILABLE"), (None, "MEASURED"), (-1, "ESTIMATED"), (False, "INSTRUMENTED")],
)
def test_invalid_unknown_zero_or_negative_cost_rejected(value, method):
    with pytest.raises(ValueError):
        audit.metric(value, method, "test")


def _object(n=1):
    values = {"sensor": np.arange(3 * n, dtype="<f4").reshape(3, n)}
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": [
                {
                    "name": "sensor",
                    "dtype": "<f4",
                    "shape": [3, n],
                    "axes": ["feature", "time"],
                    "time_axis": 1,
                    "unit": "counts",
                    "entity": "sensor",
                    "feature": "three_channels",
                }
            ],
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
    return LogicalObject(
        schema,
        values,
        np.arange(n, dtype="<i8"),
        {"sensor": np.arange(3 * n).reshape(3, n) % 2 == 0},
    )


def _frame(original, recipe, *, codec=False):
    payload, nodes = b"", []
    schema = original.schema.to_document()
    for slot, values, _logical_bits, child, raw in audit._pipeline_blocks(original, recipe):
        descriptor = None
        if codec and child is not None and not raw:
            track = BenchmarkTrack.TIMESTAMP if slot[0] == "TIMESTAMP" else BenchmarkTrack.VALUE
            manifest, routed, prepared, context, parameters, plan = _prepare_child(
                ROOT,
                child,
                values,
                track,
                {"kind": "LOSSLESS"},
                "ns",
                "unix",
                "BOOLEAN"
                if slot[0] == "VALIDITY"
                else "counts"
                if slot[0] == "VALUE"
                else "NOT_APPLICABLE",
            )
            part = b"opaque-fixture"  # Tests preparation contracts, never codec qualification.
            descriptor = {
                "codec_key": child.codec_key,
                "manifest": manifest.document,
                "parameters": parameters,
                "decode_context": context.to_document(),
                "compatibility_plan": audit.evidence_document(plan.to_document()),
                "accounting": {"serialized_bits": len(part) * 8},
            }
        else:
            part = values.tobytes()
        node = {
            "node_id": stable_id(
                "pipeline-child",
                {"role": slot[0], "owner": slot[1], "column": slot[2], "start": slot[3]},
                version="v3",
            ),
            "role": slot[0],
            "owner": slot[1],
            "column": slot[2],
            "start": slot[3],
            "count": values.size,
            "dtype": values.dtype.str,
            "encoding": "CODEC" if descriptor else "RAW",
            "offset": len(payload),
            "length": len(part),
            "sha256": hashlib.sha256(part).hexdigest(),
            "child": descriptor,
        }
        nodes.append(node)
        payload += part
    header = {
        "schema_version": "tscb.pipeline-artifact.v1",
        "logical_schema": schema,
        "logical_content_id": original.content_id,
        "underlying_bytes_sha256": original.underlying_bytes_sha256,
        "recipe": recipe.to_document(),
        "recipe_id": recipe.recipe_id,
        "canonical_raw_bits": original.canonical_raw_bits,
        "validity_present": True,
        "nodes": nodes,
    }
    return _assemble(header, payload)


def _assemble(header, payload):
    public = canonical_json_bytes(header)
    return struct.pack("<8sIQ", b"TSCBP2V1", len(public), len(payload)) + public + payload


def test_p2_nd_timestamp_validity_physical_children_and_unrounded_original_bits():
    original = _object()
    recipe = PipelineRecipe(
        {"sensor": ChildSpec("lz4-frame", {})}, ChildSpec("lz4-frame", {}), None, 2, "RAW_TAIL"
    )
    stream = _frame(original, recipe)
    profile = audit.pipeline_profile(ROOT, original, recipe, stream)
    assert profile["canonical_raw_bits"]["value"] == 3 * 32 + 64 + 3
    assert profile["payload_bytes"]["value"] == 3 * 4 + 8 + 1
    assert profile["final_bits"]["value"] == len(stream) * 8
    assert len(profile["children"]) == 5
    assert profile["children"][-1]["logical"]["logical_bits"]["value"] == 3
    assert profile["children"][-1]["serialized_bytes"]["value"] == 1
    assert profile["original_object_buffers"]["sensor"]["shape"] == [3, 1]
    assert profile["original_object_buffers"]["validity/sensor"]["dtype"] == "|b1"
    assert all(c["codec_input_bytes"]["value"] == 0 for c in profile["children"])


def test_p2_codec_costs_rebuild_saved_exact_child_preparation_without_native_calls():
    original = _object(2)
    recipe = PipelineRecipe(
        {"sensor": ChildSpec("lz4-frame", {"native_timing": False})},
        ChildSpec("lz4-frame", {"native_timing": False}),
        None,
        2,
        "RAW_TAIL",
    )
    stream = _frame(original, recipe, codec=True)
    profile = audit.pipeline_profile(ROOT, original, recipe, stream)
    assert [c["codec_input_bytes"]["value"] for c in profile["children"]] == [8, 8, 8, 16, 0]
    assert all(c["native"]["native_input_bytes"]["value"] is None for c in profile["children"])


@pytest.mark.parametrize(
    "mutation", ["missing", "overlap", "count", "hash", "denominator", "raw_corrupt"]
)
def test_p2_costs_reject_incomplete_or_unbound_child_tree(mutation):
    original = _object()
    recipe = PipelineRecipe(
        {"sensor": ChildSpec("lz4-frame", {})}, ChildSpec("lz4-frame", {}), None, 2, "RAW_TAIL"
    )
    header, payload = audit._parse(_frame(original, recipe))
    header = copy.deepcopy(header)
    if mutation == "missing":
        header["nodes"].pop()
    elif mutation == "overlap":
        header["nodes"][1]["offset"] = 0
    elif mutation == "count":
        header["nodes"][0]["count"] += 1
    elif mutation == "hash":
        header["nodes"][0]["sha256"] = "0" * 64
    elif mutation == "denominator":
        header["canonical_raw_bits"] += 1
    else:
        payload = bytes([payload[0] ^ 1]) + payload[1:]
        header["nodes"][0]["sha256"] = hashlib.sha256(payload[:4]).hexdigest()
    with pytest.raises(ValueError):
        audit.pipeline_profile(ROOT, original, recipe, _assemble(header, payload))


def test_retained_artifact_costs_bind_context_and_stream_and_never_capacity(tmp_path):
    name = "a" * 64
    directory = tmp_path / "artifacts"
    directory.mkdir()
    for suffix, value in [
        (".bin", b"abc"),
        (".decode.json", b"context"),
        (".decoder.json", b"public"),
    ]:
        (directory / (name + suffix)).write_bytes(value)
    record = {
        "run_id": "run:" + name,
        "bitstream_sha256": hashlib.sha256(b"abc").hexdigest(),
        "accounting": {
            "serialized_bits": 24,
            "external_side_information_bits": 56,
            "final_bits": 80,
        },
    }
    trials = [{"trial_id": "trial", "cell_id": "cell", "record": record}]
    result = audit._retained_artifacts(tmp_path, trials, "comparison")[0]
    assert result["final_bits"]["value"] == 80
    assert result["artifact_physical_bytes"]["evidence_method"] == "MEASURED"
    assert result["output_capacity_bytes"]["value"] is None
    (directory / (name + ".decode.json")).write_bytes(b"changed context")
    with pytest.raises(ValueError, match="storage cost mismatch"):
        audit._retained_artifacts(tmp_path, trials, "comparison")


def test_unavailable_capacity_cannot_be_replaced_by_serialized_length():
    unknown = audit.opaque_native_costs()["output_capacity_bytes"]
    assert unknown["value"] is None
    assert unknown["unavailable_reason"] == audit.CAPACITY_REASON


def _auxiliary_run(tmp_path, monkeypatch):
    original = _object()
    recipe = PipelineRecipe(
        {"sensor": ChildSpec("lz4-frame", {})}, ChildSpec("lz4-frame", {}), None, 2, "RAW_TAIL"
    )
    stream = _frame(original, recipe)
    inputs = save_pipeline_input(tmp_path / "input.npz", original)
    plan = {
        "project_root": str(ROOT),
        "run_set_id": "frozen-run",
        "closure": {"frozen": True},
        "cells": [
            {
                "cell_id": "cell",
                "dataset_key": "input",
                "method_id": "lz4-frame",
                "execution_job_id": "job",
                "recipe": recipe.to_document(),
                "recipe_id": recipe.recipe_id,
            }
        ],
        "datasets": [{"dataset_key": "input", "test": inputs, "development": inputs}],
    }
    (tmp_path / "plan.json").write_bytes(canonical_json_bytes(plan))
    artifact = tmp_path / "retained.bin"
    artifact.write_bytes(stream)
    trial = {
        "trial_id": "trial",
        "cell_id": "cell",
        "artifact_path": str(artifact),
        "artifact_sha256": audit.sha(artifact),
    }
    (tmp_path / "trials.jsonl").write_bytes(canonical_json_bytes(trial) + b"\n")
    monkeypatch.setattr(audit, "validate_pipeline_plan", lambda plan: None)
    return plan, artifact


def test_auxiliary_document_is_deterministic_and_does_not_grant_formal(tmp_path, monkeypatch):
    _auxiliary_run(tmp_path, monkeypatch)
    before = {p.name: audit.sha(p) for p in tmp_path.iterdir() if p.is_file()}
    result = audit.write_buffer_cost_audit(tmp_path, "pipeline")
    assert result == audit.validate_buffer_cost_audit(tmp_path, "pipeline")
    assert result["status"] == "AUXILIARY_COST_AUDIT"
    assert result["codec_invoked"] is False
    assert result["formal_eligible"] is False
    assert result["performance_remeasured"] is False
    assert "NOT_SAME_PERFORMANCE_EXECUTION" in result["observation_relationship"]
    assert all(audit.sha(tmp_path / name) == digest for name, digest in before.items())
    assert (tmp_path / "buffer_cost_audit.md").is_file()


def test_rehashed_fake_cost_observation_cannot_pass_reconstruction(tmp_path, monkeypatch):
    _auxiliary_run(tmp_path, monkeypatch)
    result = audit.write_buffer_cost_audit(tmp_path, "pipeline")
    result["cells_or_artifact_profiles"][0]["costs"]["final_bits"]["value"] += 8
    result.pop("audit_id")
    result["audit_id"] = stable_id("auxiliary-buffer-cost-audit-v32", result)
    (tmp_path / "buffer_cost_audit.json").write_bytes(canonical_json_bytes(result) + b"\n")
    with pytest.raises(ValueError, match="cost evidence differs"):
        audit.validate_buffer_cost_audit(tmp_path, "pipeline")


@pytest.mark.parametrize("subject", ["input", "artifact", "plan"])
def test_auxiliary_binding_rejects_changed_frozen_evidence(tmp_path, monkeypatch, subject):
    plan, artifact = _auxiliary_run(tmp_path, monkeypatch)
    audit.write_buffer_cost_audit(tmp_path, "pipeline")
    if subject == "input":
        (tmp_path / "input.npz").write_bytes(b"corrupt NPZ")
    elif subject == "artifact":
        artifact.write_bytes(artifact.read_bytes() + b"extra")
    else:
        plan["closure"] = {"changed": True}
        (tmp_path / "plan.json").write_bytes(canonical_json_bytes(plan))
    with pytest.raises(ValueError):
        audit.validate_buffer_cost_audit(tmp_path, "pipeline")
