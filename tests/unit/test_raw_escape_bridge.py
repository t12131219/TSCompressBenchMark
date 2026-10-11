from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.pipelines import (
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineError,
    SourceRejectRawRecipe,
    decode_source_reject_raw,
    decode_source_reject_raw_in_fresh_process,
    encode_source_reject_raw,
)

ROOT = Path(__file__).resolve().parents[2]
_FRAME = struct.Struct("<8sIQ")


def _object(n=17):
    values = np.arange(n, dtype=np.float64) / 3
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": [
                {
                    "name": "sensor",
                    "dtype": "<f8",
                    "shape": [n],
                    "axes": ["time"],
                    "time_axis": 0,
                    "unit": "m/s",
                    "entity": "device",
                    "feature": "speed",
                }
            ],
            "timestamp": {
                "present": False,
                "dtype": "NOT_APPLICABLE",
                "unit": "NOT_APPLICABLE",
                "epoch": "NOT_APPLICABLE",
                "pairing": "NOT_APPLICABLE",
            },
            "null_recovery_contract": "BITWISE",
        }
    )
    return LogicalObject(schema, {"sensor": values})


def test_source_reject_raw_roundtrip_and_fresh_spawn():
    original = _object()
    artifact = encode_source_reject_raw(
        ROOT, original, SourceRejectRawRecipe(ChildSpec("alp", {}), 8)
    )
    restored = decode_source_reject_raw(ROOT, artifact)
    assert np.array_equal(restored.values["sensor"], original.values["sensor"])
    cold = decode_source_reject_raw_in_fresh_process(ROOT, artifact)
    assert np.array_equal(cold.values["sensor"], original.values["sensor"])
    assert artifact.ledger.final_bits == len(artifact.stream) * 8
    assert artifact.execution_evidence["encode_timing_boundary"].startswith("BLOCK_ATTEMPT")
    assert (
        artifact.execution_evidence["raw_block_count"]
        + artifact.execution_evidence["codec_block_count"]
        == 3
    )


def test_raw_escape_records_attempt_and_never_records_non_source_failures():
    artifact = encode_source_reject_raw(
        ROOT, _object(8), SourceRejectRawRecipe(ChildSpec("alp", {}), 4)
    )
    assert len(artifact.execution_evidence["blocks"]) == 2
    for block in artifact.execution_evidence["blocks"]:
        assert block["source_attempt_not_in_wire"] is True
        assert block["source_attempt_evidence"] == "MEASURED_CONTROL_CLOCK"
        assert block["outcome"] in {"RAW", "CODEC"}


def test_recipe_and_block_header_tampering_fails_closed():
    artifact = encode_source_reject_raw(
        ROOT, _object(), SourceRejectRawRecipe(ChildSpec("alp", {}), 8)
    )
    magic, size, payload = _FRAME.unpack_from(artifact.stream)
    header = json.loads(artifact.stream[_FRAME.size : _FRAME.size + size])
    header["blocks"][0]["encoding"] = "UNKNOWN"
    encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    tampered = (
        _FRAME.pack(magic, len(encoded), payload) + encoded + artifact.stream[_FRAME.size + size :]
    )
    with pytest.raises(PipelineError):
        decode_source_reject_raw(ROOT, tampered)


def test_real_etth1_alp_source_rejection_uses_explicit_raw_escape():
    csv_path = ROOT.parent / "Compression_Rewrite/datasets/ETTh1.csv"
    raw = np.genfromtxt(csv_path, delimiter=",", names=True, dtype=None, encoding=None)
    values = np.asarray(raw["HUFL"], dtype="<f8")
    item = {
        "name": "HUFL",
        "dtype": "<f8",
        "shape": [values.size],
        "unit": "UNSPECIFIED",
        "entity": "transformer",
        "feature": "HUFL",
    }
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": [
                {
                    "name": item["name"],
                    "dtype": item["dtype"],
                    "shape": item["shape"],
                    "axes": ["time"],
                    "time_axis": 0,
                    "unit": item["unit"],
                    "entity": item["entity"],
                    "feature": item["feature"],
                }
            ],
            "timestamp": {
                "present": False,
                "dtype": "NOT_APPLICABLE",
                "unit": "NOT_APPLICABLE",
                "epoch": "NOT_APPLICABLE",
                "pairing": "NOT_APPLICABLE",
            },
            "null_recovery_contract": "BITWISE",
        }
    )
    original = LogicalObject(schema, {item["name"]: values})
    artifact = encode_source_reject_raw(
        ROOT, original, SourceRejectRawRecipe(ChildSpec("alp", {}), values.size)
    )
    evidence = artifact.execution_evidence
    assert evidence["raw_block_count"] == 1 and evidence["codec_block_count"] == 0
    assert all(block["rejection"]["type"] == "SOURCE_DOMAIN_ONLY" for block in evidence["blocks"])
    restored = decode_source_reject_raw(ROOT, artifact)
    assert np.array_equal(restored.values[item["name"]], original.values[item["name"]])


def test_alp_source_reject_raw_supports_multiple_synchronous_value_columns():
    n = 4096
    rng = np.random.default_rng(20261010)
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": [
                {
                    "name": "sensor/a",
                    "dtype": "<f8",
                    "shape": [n],
                    "axes": ["time"],
                    "time_axis": 0,
                    "unit": "m/s",
                    "entity": "device-a",
                    "feature": "speed",
                },
                {
                    "name": "sensor/b",
                    "dtype": "<f8",
                    "shape": [n],
                    "axes": ["time"],
                    "time_axis": 0,
                    "unit": "m/s",
                    "entity": "device-b",
                    "feature": "speed",
                },
            ],
            "timestamp": {
                "present": False,
                "dtype": "NOT_APPLICABLE",
                "unit": "NOT_APPLICABLE",
                "epoch": "NOT_APPLICABLE",
                "pairing": "NOT_APPLICABLE",
            },
            "null_recovery_contract": "BITWISE",
        }
    )
    original = LogicalObject(
        schema,
        {
            "sensor/a": rng.integers(0, 2**64, n, dtype="<u8").view("<f8"),
            "sensor/b": rng.integers(0, 2**64, n, dtype="<u8").view("<f8"),
        },
    )
    artifact = encode_source_reject_raw(
        ROOT, original, SourceRejectRawRecipe(ChildSpec("alp", {}), n)
    )
    assert artifact.execution_evidence["method_identity"] == "alp"
    assert (
        artifact.execution_evidence["raw_block_count"]
        + artifact.execution_evidence["codec_block_count"]
        == 2
    )
    assert {block["owner"] for block in artifact.execution_evidence["blocks"]} == {
        "sensor/a",
        "sensor/b",
    }
    restored = decode_source_reject_raw(ROOT, artifact)
    for name in original.values:
        assert restored.values[name].tobytes() == original.values[name].tobytes()
        assert not restored.values[name].flags.writeable


def test_raw_escape_does_not_translate_non_source_pipeline_errors(monkeypatch):
    import tscompbench.pipelines.raw_escape_bridge as bridge

    original = _object(8)
    monkeypatch.setattr(
        bridge,
        "encode_object",
        lambda *args, **kwargs: (_ for _ in ()).throw(PipelineError("capacity failure")),
    )
    with pytest.raises(PipelineError, match="capacity failure"):
        encode_source_reject_raw(
            ROOT, original, SourceRejectRawRecipe(ChildSpec("alp", {}), 4)
        )
