from __future__ import annotations

import copy
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.ids import canonical_json_bytes
from tscompbench.pipelines import (
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineError,
    PipelineRecipe,
    decode_in_fresh_process,
    decode_object,
    encode_object,
    validate_restored_object,
)

ROOT = Path(__file__).resolve().parents[2]


def _object(n=9, *, mixed=False, mask=False, semantic=False, timestamps=False):
    values = {"sensor/a": np.arange(6 * n, dtype=np.int16).reshape(2, n, 3)}
    descriptions = [
        {
            "name": "sensor/a",
            "dtype": "<i2",
            "shape": [2, n, 3],
            "axes": ["entity", "time", "feature"],
            "time_axis": 1,
            "unit": "counts",
            "entity": "device_a",
            "feature": "six_components",
        }
    ]
    if mixed:
        values["sensor/b"] = np.arange(n, dtype=np.float64) / 3
        descriptions.append(
            {
                "name": "sensor/b",
                "dtype": "<f8",
                "shape": [n],
                "axes": ["time"],
                "time_axis": 0,
                "unit": "m/s",
                "entity": "device_b",
                "feature": "speed",
            }
        )
    timestamp = {
        "present": timestamps,
        "dtype": "<i8" if timestamps else "NOT_APPLICABLE",
        "unit": "ns" if timestamps else "NOT_APPLICABLE",
        "epoch": "unix" if timestamps else "NOT_APPLICABLE",
        "pairing": "SHARED_TIME_AXIS" if timestamps else "NOT_APPLICABLE",
    }
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": descriptions,
            "timestamp": timestamp,
            "null_recovery_contract": "SEMANTIC" if semantic else "BITWISE",
        }
    )
    masks = (
        {name: np.ones(value.shape, dtype=np.bool_) for name, value in values.items()}
        if mask
        else None
    )
    if mask and n:
        masks["sensor/a"][0, 0, 0] = False
        if mixed:
            masks["sensor/b"][0] = False
            values["sensor/b"][0] = np.nan
    return LogicalObject(
        schema, values, np.arange(n, dtype=np.int64) * 3 - 1 if timestamps else None, masks
    )


def _recipe(original, *, value_codec="lz4-frame", block=8, tail="RAW_TAIL", mask_codec=None):
    return PipelineRecipe(
        {name: ChildSpec(value_codec, {}) for name in original.values},
        ChildSpec("zstd-frame", {}) if original.timestamp is not None else None,
        None if mask_codec is None else ChildSpec(mask_codec, {}),
        block,
        tail,
    )


@pytest.mark.parametrize("n", [0, 1, 2, 7, 8, 9, 15, 16, 17])
def test_nd_nonzero_time_axis_all_blocks_tail_and_exact_cost(n):
    original = _object(n)
    recipe = _recipe(original)
    artifact = encode_object(ROOT, original, recipe)
    restored = decode_object(ROOT, artifact)
    assert validate_restored_object(original, restored)["passed"]
    assert np.array_equal(restored.values["sensor/a"], original.values["sensor/a"])
    assert restored.values["sensor/a"].flags.owndata
    assert not restored.values["sensor/a"].flags.writeable
    assert artifact.ledger.final_bits == len(artifact.stream) * 8
    assert (
        artifact.ledger.payload_physical_bits + artifact.ledger.metadata_physical_bits
        == artifact.ledger.final_bits
    )
    assert artifact.ledger.canonical_raw_bits == 6 * n * 16


@pytest.mark.parametrize("semantic", [False, True])
@pytest.mark.parametrize("mask_codec", [None, "lz4-frame"])
def test_mixed_validity_and_timestamp_restore_complete_schema(semantic, mask_codec):
    original = _object(mixed=True, mask=True, semantic=semantic, timestamps=True)
    artifact = encode_object(ROOT, original, _recipe(original, mask_codec=mask_codec))
    restored, evidence = decode_in_fresh_process(ROOT, artifact)
    assert validate_restored_object(original, restored)["passed"]
    assert evidence["start_method"] == "spawn"
    assert evidence["original_input_available"] is False
    assert evidence["encoder_session_available"] is False
    assert evidence["output_owned_in_worker"] is True
    assert evidence["worker_exit_confirmed"] is True
    assert restored.schema.serialized == original.schema.serialized
    assert all(
        np.array_equal(mask, restored.validity[name]) for name, mask in original.validity.items()
    )
    if semantic:
        assert restored.values["sensor/b"][0] == 0
        assert restored.underlying_bytes_sha256 != original.underlying_bytes_sha256
    else:
        assert np.isnan(restored.values["sensor/b"][0])
        assert restored.underlying_bytes_sha256 == original.underlying_bytes_sha256


def test_existing_integer_and_float_children_without_domain_expansion():
    original = _object(16, mixed=True, timestamps=True)
    recipe = PipelineRecipe(
        {
            "sensor/a": ChildSpec("neats-lossless-i64", {}),
            "sensor/b": ChildSpec("alp", {}),
        },
        ChildSpec("lz4-frame", {}),
        None,
        8,
    )
    artifact = encode_object(ROOT, original, recipe)
    restored, _ = decode_in_fresh_process(ROOT, artifact)
    assert validate_restored_object(original, restored)["passed"]
    assert restored.values["sensor/a"].dtype == np.int16


def test_existing_bound_codec_is_verified_in_total_original_domain():
    original = _object(16, mixed=True)
    recipe = PipelineRecipe(
        {
            "sensor/a": ChildSpec("lz4-frame", {}),
            "sensor/b": ChildSpec("zfp-accuracy-1d", {"error_bound": "0.01"}),
        },
        None,
        None,
        8,
        loss_contract={"kind": "ABS", "threshold": "0.01"},
    )
    artifact = encode_object(ROOT, original, recipe)
    restored = decode_object(ROOT, artifact)
    report = validate_restored_object(original, restored, loss_contract=recipe.loss_contract)
    assert report["passed"] and report["loss"]["error_bound"] == "0.01"
    bad = copy.deepcopy(recipe.to_document())
    bad["loss_contract"]["threshold"] = "0.001"
    with pytest.raises(PipelineError, match="budget"):
        encode_object(ROOT, original, PipelineRecipe.from_document(bad))


def _change_header(stream, change):
    frame = struct.Struct("<8sIQ")
    magic, length, payload_length = frame.unpack_from(stream)
    header = json.loads(stream[frame.size : frame.size + length])
    change(header)
    encoded = canonical_json_bytes(header)
    return frame.pack(magic, len(encoded), payload_length) + encoded + stream[frame.size + length :]


@pytest.mark.parametrize("cut", [1, 19, 100])
def test_truncated_artifacts_fail_closed(cut):
    original = _object()
    artifact = encode_object(ROOT, original, _recipe(original))
    with pytest.raises(PipelineError, match="truncated"):
        decode_object(ROOT, artifact.stream[:-cut])


def test_missing_public_child_decoder_is_rejected_in_clean_process():
    original = _object()
    artifact = encode_object(ROOT, original, _recipe(original))
    with pytest.raises(PipelineError, match="unavailable"):
        decode_in_fresh_process(ROOT, artifact, available_child_keys=set())


@pytest.mark.parametrize(
    "change",
    ["missing_child", "duplicate_child", "wrong_axis", "wrong_child", "hidden_raw", "extra_bytes"],
)
def test_child_tree_and_frozen_recipe_tampering_cannot_pass(change):
    original = _object()
    artifact = encode_object(ROOT, original, _recipe(original))

    def corrupt(header):
        if change == "missing_child":
            header["nodes"].pop()
        elif change == "duplicate_child":
            header["nodes"].append(header["nodes"][0])
        elif change == "wrong_axis":
            header["logical_schema"]["values"][0]["time_axis"] = 0
        elif change == "wrong_child":
            header["nodes"][0]["child"]["codec_key"] = "zstd-frame"
        elif change == "hidden_raw":
            header["nodes"][0]["encoding"] = "RAW"
        else:
            header["nodes"][0]["length"] += 1

    with pytest.raises((PipelineError, ValueError)):
        decode_object(ROOT, _change_header(artifact.stream, corrupt))


def test_semantic_null_content_identity_differs_from_underlying_byte_hash():
    original = _object(mask=True, semantic=True)
    changed = {name: value.copy() for name, value in original.values.items()}
    changed["sensor/a"][0, 0, 0] = 999
    other = LogicalObject(original.schema, changed, original.timestamp, original.validity)
    assert original.content_id == other.content_id
    assert original.underlying_bytes_sha256 != other.underlying_bytes_sha256
    assert original.canonical_raw_bits == other.canonical_raw_bits


def test_restored_semantic_metadata_is_checked_independently():
    original = _object(timestamps=True)
    artifact = encode_object(ROOT, original, _recipe(original))
    restored = decode_object(ROOT, artifact)
    modified = restored.schema.to_document()
    modified["timestamp"]["unit"] = "ms"
    modified_object = type(restored)(
        LogicalObjectSchema.from_document(modified),
        restored.values,
        restored.timestamp,
        restored.validity,
    )
    assert (
        validate_restored_object(original, modified_object)["reason"]
        == "RESTORED_LOGICAL_SCHEMA_MISMATCH"
    )


def test_native_child_source_domain_is_not_widened_by_recipe_metadata():
    original = _object(8)
    with pytest.raises(PipelineError, match="unsupported"):
        encode_object(ROOT, original, _recipe(original, value_codec="sprintz-fire-u8"))


def test_child_and_recipe_are_snapshots_and_buffer_order_is_schema_driven():
    parameters = {"compression_level": 1}
    child = ChildSpec("zstd-frame", parameters)
    parameters["compression_level"] = 3
    child.parameters["compression_level"] = 5
    original = _object(8, mixed=True)
    loss = {"kind": "LOSSLESS"}
    children = {name: child for name in reversed(original.values)}
    recipe = PipelineRecipe(children, None, None, 8, loss_contract=loss)
    frozen = recipe.recipe_id
    children.clear()
    loss["kind"] = "ABS"
    recipe.value_children.clear()
    recipe.loss_contract["kind"] = "ABS"
    assert child.parameters == {"compression_level": 1}
    assert recipe.recipe_id == frozen
    assert validate_restored_object(
        original, decode_object(ROOT, encode_object(ROOT, original, recipe))
    )["passed"]


@pytest.mark.parametrize("threshold", ["NaN", "Infinity", "-1", "abc", "", 1, None])
def test_invalid_pipeline_bounds_are_rejected_before_children_run(threshold):
    with pytest.raises(PipelineError, match="finite nonnegative"):
        PipelineRecipe(
            {"sensor/a": ChildSpec("lz4-frame", {})},
            None,
            None,
            8,
            loss_contract={"kind": "ABS", "threshold": threshold},
        )


def test_timestamp_units_epoch_and_actual_order_evidence_are_paid_and_checked():
    original = _object(8, timestamps=True)
    original.timestamp[:] = [5, 5, 4, -3, 0, 2, 1, 9]
    recipe = PipelineRecipe(
        {"sensor/a": ChildSpec("lz4-frame", {})}, ChildSpec("lz4-frame", {}), None, 8
    )
    artifact = encode_object(ROOT, original, recipe)
    assert validate_restored_object(original, decode_object(ROOT, artifact))["passed"]
    frame = struct.Struct("<8sIQ")
    _, length, _ = frame.unpack_from(artifact.stream)
    header = json.loads(artifact.stream[frame.size : frame.size + length])
    child = next(node["child"] for node in header["nodes"] if node["role"] == "TIMESTAMP")
    assert child["decode_context"]["timestamp_unit"] == "ns"
    assert child["decode_context"]["timestamp_epoch"] == "unix"
    descriptor = child["compatibility_plan"]["input_descriptor"]
    assert descriptor["has_duplicates"] and descriptor["has_out_of_order"]
    assert descriptor["has_negative_delta"]


@pytest.mark.parametrize("field", ["track", "schema_version", "compression_factor", "extra"])
def test_saved_child_accounting_cannot_be_relabelled_or_partially_loaded(field):
    original = _object(8)
    artifact = encode_object(ROOT, original, _recipe(original))

    def corrupt(header):
        ledger = header["nodes"][0]["child"]["accounting"]
        ledger[field] = "TIMESTAMP" if field == "track" else "TAMPERED"

    with pytest.raises(ValueError):
        decode_object(ROOT, _change_header(artifact.stream, corrupt))


def test_saved_inverse_cannot_replace_actual_negotiated_path():
    original = _object(8)
    artifact = encode_object(ROOT, original, _recipe(original))

    def corrupt(header):
        header["nodes"][0]["child"]["decode_context"]["buffers"][0]["inverse"] = [
            {"kind": "ENDIANNESS_CONVERSION", "dtype": "<i2"}
        ]

    with pytest.raises(PipelineError, match="inverse"):
        decode_object(ROOT, _change_header(artifact.stream, corrupt))


def test_abs_quality_checks_bitwise_null_payload_independently():
    original = _object(8, mask=True)
    restored = decode_object(ROOT, encode_object(ROOT, original, _recipe(original)))
    changed = {name: value.copy() for name, value in restored.values.items()}
    changed["sensor/a"][0, 0, 0] = 123
    modified = type(restored)(restored.schema, changed, restored.timestamp, restored.validity)
    assert (
        validate_restored_object(
            original, modified, loss_contract={"kind": "ABS", "threshold": "1"}
        )["reason"]
        == "NULL_PAYLOAD_BITWISE_MISMATCH"
    )


def test_nd_abs_quality_profiles_actual_time_axis_for_every_logical_column():
    original = _object(8, mixed=True, timestamps=True)
    restored = decode_object(ROOT, encode_object(ROOT, original, _recipe(original)))
    result = validate_restored_object(
        original, restored, loss_contract={"kind": "ABS", "threshold": "0"}
    )
    assert result["passed"]
    assert len(result["logical_channel_map"]) == 7
    assert result["timestamp_unit"] == "ns"
    channels = result["loss"]["channels"]
    assert len(channels) == 7
    assert all(item["time_weighted_rmse"] == "0" for item in channels)
    assert all(item["derivative_rmse"] == "0" for item in channels)


def test_pipeline_schema_roots_and_version_names_are_closed():
    names = {
        "byte-symbol-recipe.schema.json",
        "logical-object-schema.schema.json",
        "pipeline-recipe.schema.json",
        "pipeline-ledger.schema.json",
        "pipeline-artifact-header.schema.json",
        "source-reject-raw-recipe.schema.json",
        "channel-collection-recipe.schema.json",
        "channel-collection-schema.schema.json",
        "channel-collection-artifact.schema.json",
        "channel-collection-raw.schema.json",
    }
    paths = list((ROOT / "schemas/pipelines/v1").glob("*.schema.json"))
    assert {path.name for path in paths} == names
    for path in paths:
        schema = json.loads(path.read_text())
        assert schema["$schema"].endswith("2020-12/schema")
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
