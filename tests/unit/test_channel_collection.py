from __future__ import annotations

import copy
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.ids import canonical_json_bytes
from tscompbench.pipelines.channel_collection import (
    ChannelCollection,
    ChannelCollectionRecipe,
    ChannelCollectionSchema,
    decode_collection,
    decode_collection_in_fresh_process,
    encode_collection,
    import_collection_raw,
    prepare_collection_raw,
    standalone_collection_rejection,
    validate_restored_collection,
)
from tscompbench.pipelines.models import (
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineError,
    PipelineRecipe,
)

ROOT = Path(__file__).resolve().parents[2]
FRAME = struct.Struct("<8sIQ")


def collection_fixture(*, kind="RAGGED_CHANNELS", semantic=False):
    channels, rows = {}, []
    for index, n in enumerate((9, 6, 0)):
        name = f"device/{index}"
        # Nonzero time_axis, mixed dtype, endian and strided physical views.
        value = (
            np.arange(4 * n, dtype=np.int16).reshape(2, 2 * n)[:, ::2]
            if index == 0
            else np.linspace(-1, 1, n, dtype=np.float64)
        )
        if index == 1 and n:
            value[0] = np.nan  # A valid NaN remains distinct from a null below.
        present = kind == "ASYNCHRONOUS_MTS" or index != 2
        logical = LogicalObjectSchema.from_document(
            {
                "schema_version": "tscb.logical-object-schema.v1",
                "values": [
                    {
                        "name": "reading",
                        "dtype": value.dtype.str,
                        "shape": list(value.shape),
                        "axes": ["feature", "time"] if index == 0 else ["time"],
                        "time_axis": 1 if index == 0 else 0,
                        "unit": "counts" if index == 0 else "m/s",
                        "entity": name,
                        "feature": "reading",
                    }
                ],
                "timestamp": {
                    "present": present,
                    "dtype": "<i8" if present else "NOT_APPLICABLE",
                    "unit": "ns" if present else "NOT_APPLICABLE",
                    "epoch": "unix" if present else "NOT_APPLICABLE",
                    "pairing": "SHARED_TIME_AXIS" if present else "NOT_APPLICABLE",
                },
                "null_recovery_contract": "SEMANTIC" if semantic else "BITWISE",
            }
        )
        t = np.arange(n, dtype=np.int64) * (3 + index) if present else None
        if present and n >= 4:
            t[1:4] = [3, 3, -4]  # Duplicates and out-of-order source T stay intact.
        mask = np.ones(value.shape, dtype=np.bool_)
        if value.size > 2:
            mask.reshape(-1)[-2] = False
        channels[name] = LogicalObject(logical, {"reading": value}, t, {"reading": mask})
        rows.append(
            {
                "channel_id": name,
                "timestamp_origin": "SOURCE_COLUMN" if present else "NONE",
                "logical_schema": logical.to_document(),
            }
        )
    schema = ChannelCollectionSchema.from_document(
        {
            "schema_version": "tscb.channel-collection-schema.v1",
            "topology": {"kind": kind, "alignment": "NONE", "time_pairing": "PER_CHANNEL"},
            "channels": rows,
        }
    )
    return ChannelCollection(schema, channels)


def collection_recipe(original, codec="lz4-frame"):
    return ChannelCollectionRecipe.from_recipes(
        {
            name: PipelineRecipe(
                {key: ChildSpec(codec, {}) for key in child.values},
                ChildSpec(codec, {}) if child.timestamp is not None else None,
                ChildSpec(codec, {}),
                4,
                "COMPRESS_TAIL",
            )
            for name, child in original.channels.items()
        }
    )


def change_header(stream, change, *, change_payload=None):
    magic, size, _ = FRAME.unpack_from(stream)
    header = json.loads(stream[FRAME.size : FRAME.size + size])
    payload = stream[FRAME.size + size :]
    if change_payload is not None:
        payload = change_payload(payload)
    change(header)
    header["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    encoded = canonical_json_bytes(header)
    return FRAME.pack(magic, len(encoded), len(payload)) + encoded + payload


@pytest.mark.parametrize("kind", ["RAGGED_CHANNELS", "ASYNCHRONOUS_MTS"])
@pytest.mark.parametrize("semantic", [False, True])
def test_raw_collection_preserves_per_channel_topology_and_null_contract(kind, semantic):
    original = collection_fixture(kind=kind, semantic=semantic)
    restored = import_collection_raw(prepare_collection_raw(original))
    assert validate_restored_collection(original, restored)["passed"]
    assert restored.underlying_bytes_sha256 == original.underlying_bytes_sha256
    assert [child.schema.n for child in restored.channels.values()] == [9, 6, 0]
    assert restored.schema.schema_id == original.schema.schema_id
    assert all(
        buffer.array.flags.owndata and not buffer.array.flags.writeable
        for view in restored.buffer_views()
        for buffer in (
            *view.values,
            *view.validity,
            *(() if view.timestamp is None else (view.timestamp,)),
        )
    )
    assert np.isnan(restored.channels["device/1"].values["reading"][0])
    assert restored.channels["device/1"].validity["reading"][0]
    assert (restored.channels["device/2"].timestamp is None) == (kind == "RAGGED_CHANNELS")


def test_rawbits_and_native_views_use_independent_lengths_without_padding():
    original = collection_fixture()
    assert original.canonical_raw_bits == 18 * 16 + 6 * 64 + (9 + 6) * 64 + 18 + 6
    views = original.buffer_views()
    assert [view.n for view in views] == [9, 6, 0]
    assert not views[0].values[0].array.flags.c_contiguous
    assert views[0].values[0].array is original.channels["device/0"].values["reading"]
    assert (
        sum(
            buffer.logical_bits
            for view in views
            for buffer in (
                *view.values,
                *view.validity,
                *(() if view.timestamp is None else (view.timestamp,)),
            )
        )
        == original.canonical_raw_bits
    )
    semantic = collection_fixture(semantic=True)
    assert semantic.canonical_raw_bits == original.canonical_raw_bits - 16 - 64


@pytest.mark.parametrize("field", ["order", "unit", "epoch", "origin", "T", "mask"])
def test_semantic_identity_binds_channel_order_units_origin_T_and_validity(field):
    original = collection_fixture()
    doc = original.schema.to_document()
    channels = copy.deepcopy(original.channels)
    if field == "order":
        doc["channels"].reverse()
        channels = dict(reversed(tuple(channels.items())))
    elif field in {"unit", "epoch", "origin"}:
        if field == "unit":
            doc["channels"][0]["logical_schema"]["values"][0]["unit"] = "other"
        elif field == "epoch":
            doc["channels"][0]["logical_schema"]["timestamp"]["epoch"] = "other"
        else:
            doc["channels"][0]["timestamp_origin"] = "MANIFEST_CONSTRUCTED"
        child = channels["device/0"]
        channels["device/0"] = LogicalObject(
            LogicalObjectSchema.from_document(doc["channels"][0]["logical_schema"]),
            child.values,
            child.timestamp,
            child.validity,
        )
    elif field == "T":
        channels["device/0"].timestamp[0] = 888
    else:
        channels["device/0"].validity["reading"][0, 0] = False
    changed = ChannelCollection(ChannelCollectionSchema.from_document(doc), channels)
    assert changed.content_id != original.content_id


def test_identity_ignores_physical_layout_and_semantic_null_payload_only():
    original = collection_fixture(semantic=True)
    channels = copy.deepcopy(original.channels)
    channels["device/0"].values["reading"][~channels["device/0"].validity["reading"]] = 99
    changed = ChannelCollection(original.schema, channels)
    assert changed.content_id == original.content_id
    assert changed.underlying_bytes_sha256 != original.underlying_bytes_sha256
    channels = {
        name: LogicalObject(
            child.schema,
            {key: np.array(value, order="F", copy=True) for key, value in child.values.items()},
            child.timestamp,
            child.validity,
        )
        for name, child in original.channels.items()
    }
    assert ChannelCollection(original.schema, channels).content_id == original.content_id


@pytest.mark.parametrize(
    "damage",
    [
        "suffix",
        "truncate",
        "overlap",
        "reorder",
        "missing",
        "shape",
        "hash",
        "padding",
        "rawbits",
        "version",
    ],
)
def test_raw_parser_rejects_corrupted_or_ambiguous_collections(damage):
    raw = prepare_collection_raw(collection_fixture())
    if damage == "suffix":
        broken = raw + b"hidden"
    elif damage == "truncate":
        broken = raw[:-1]
    else:

        def mutate(header):
            if damage == "overlap":
                header["buffers"][1]["offset"] = 0
            elif damage == "reorder":
                header["buffers"][:2] = reversed(header["buffers"][:2])
            elif damage == "missing":
                header["buffers"].pop()
            elif damage == "shape":
                header["collection_schema"]["channels"][0]["logical_schema"]["values"][0]["shape"][
                    1
                ] = 10**30
            elif damage == "hash":
                header["buffers"][0]["sha256"] = "0" * 64
            elif damage == "rawbits":
                header["canonical_raw_bits"] += 1
            elif damage == "version":
                header["schema_version"] = "future"
            else:
                row = next(row for row in header["buffers"] if row["role"] == "VALIDITY")
                row["sha256"] = hashlib.sha256(
                    changed_payload[row["offset"] : row["offset"] + row["length"]]
                ).hexdigest()

        changed_payload = None
        if damage == "padding":
            _, size, _ = FRAME.unpack_from(raw)
            h = json.loads(raw[FRAME.size : FRAME.size + size])
            row = next(row for row in h["buffers"] if row["role"] == "VALIDITY")
            changed_payload = bytearray(raw[FRAME.size + size :])
            changed_payload[row["offset"] + row["length"] - 1] |= 128
            changed_payload = bytes(changed_payload)
        broken = change_header(
            raw,
            mutate,
            change_payload=None if changed_payload is None else lambda payload: changed_payload,
        )
    with pytest.raises(PipelineError):
        import_collection_raw(broken)


def test_standalone_rejection_is_explicit_before_any_codec_call():
    rejection = standalone_collection_rejection(collection_fixture())
    assert rejection["status"] == "UNSUPPORTED"
    assert rejection["codec_called"] is False
    assert rejection["actual_input_observed"] is False
    assert rejection["channel_lengths"] == {"device/0": 9, "device/1": 6, "device/2": 0}


def test_zero_length_axis_cannot_hide_unaddressable_other_dimensions():
    doc = collection_fixture().schema.to_document()
    doc["channels"][2]["logical_schema"]["values"][0].update(
        shape=[10**30, 0],
        axes=["entity", "time"],
        time_axis=1,
    )
    with pytest.raises(PipelineError, match="shape budget"):
        ChannelCollectionSchema.from_document(doc)


@pytest.mark.parametrize("codec", ["lz4-frame", "zstd-frame"])
@pytest.mark.parametrize("semantic", [False, True])
def test_codec_complete_collection_recovers_in_public_fresh_process_and_closes_cost(
    codec, semantic
):
    original = collection_fixture(semantic=semantic)
    artifact = encode_collection(ROOT, original, collection_recipe(original, codec))
    restored, recovery = decode_collection_in_fresh_process(ROOT, artifact)
    assert validate_restored_collection(original, restored)["passed"]
    assert recovery["worker_exit_confirmed"] and recovery["output_owned_in_worker"]
    assert recovery["original_input_available"] is False
    assert recovery["stream_sha256"] == hashlib.sha256(artifact.stream).hexdigest()
    assert artifact.ledger.canonical_raw_bits == original.canonical_raw_bits
    assert artifact.ledger.final_bits == len(artifact.stream) * 8
    assert (
        artifact.ledger.metadata_physical_bits + artifact.ledger.payload_physical_bits
        == len(artifact.stream) * 8
    )
    if semantic:
        assert restored.underlying_bytes_sha256 != original.underlying_bytes_sha256
    else:
        assert restored.underlying_bytes_sha256 == original.underlying_bytes_sha256


def test_codec_missing_child_decoder_and_channel_frame_tampering_are_rejected():
    original = collection_fixture()
    artifact = encode_collection(ROOT, original, collection_recipe(original))
    with pytest.raises(PipelineError, match="unavailable"):
        decode_collection_in_fresh_process(ROOT, artifact, available_child_keys=set())
    broken = change_header(artifact.stream, lambda header: header["channels"].reverse())
    with pytest.raises(PipelineError):
        decode_collection(ROOT, broken)


def test_collection_schema_and_recipe_do_not_accept_hidden_alignment_or_lossy_contract():
    doc = collection_fixture().schema.to_document()
    doc["topology"]["alignment"] = "RESAMPLE"
    with pytest.raises(PipelineError):
        ChannelCollectionSchema.from_document(doc)
    original = collection_fixture()
    recipes = collection_recipe(original).to_document()
    recipes["channels"][0]["recipe"]["loss_contract"] = {"kind": "ABS", "threshold": "1"}
    with pytest.raises(PipelineError, match="lossless"):
        ChannelCollectionRecipe.from_document(recipes)
