from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np
import pytest

from tscompbench.execution.protocol import SourceDomainError
from tscompbench.pipelines import (
    ByteSymbolRecipe,
    ChildSpec,
    LogicalObject,
    LogicalObjectSchema,
    PipelineError,
    decode_byte_symbol_bridge,
    decode_byte_symbol_in_fresh_process,
    encode_byte_symbol_bridge,
)

ROOT = Path(__file__).resolve().parents[2]
_FRAME = struct.Struct("<8sIQ")


def _object(n: int) -> LogicalObject:
    values = np.arange(n, dtype=np.uint8)
    schema = LogicalObjectSchema.from_document(
        {
            "schema_version": "tscb.logical-object-schema.v1",
            "values": [
                {
                    "name": "bytes",
                    "dtype": "|u1",
                    "shape": [n],
                    "axes": ["time"],
                    "time_axis": 0,
                    "unit": "bytes",
                    "entity": "stream",
                    "feature": "octet",
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
    return LogicalObject(schema, {"bytes": values})


def test_radix4_mapping_covers_all_byte_values_and_fresh_decode():
    original = _object(256)
    artifact = encode_byte_symbol_bridge(
        ROOT, original, ByteSymbolRecipe(ChildSpec("deepzip", {}), 64)
    )
    restored, evidence = decode_byte_symbol_in_fresh_process(ROOT, artifact)
    assert np.array_equal(restored.values["bytes"], original.values["bytes"])
    assert restored.values["bytes"].flags.owndata and not restored.values["bytes"].flags.writeable
    assert evidence["start_method"] == "spawn"
    assert evidence["original_input_available"] is False
    assert evidence["encoder_session_available"] is False
    assert artifact.ledger.final_bits == len(artifact.stream) * 8
    assert artifact.execution_evidence["native_input_bytes"] == 4 * original.schema.n
    assert artifact.execution_evidence["stages"][0]["output_payload_bytes"] == 4 * original.schema.n


@pytest.mark.parametrize("n", [0, 1, 2, 63, 64, 65, 255])
def test_radix4_true_count_and_tail_are_reversible(n):
    original = _object(n)
    artifact = encode_byte_symbol_bridge(
        ROOT, original, ByteSymbolRecipe(ChildSpec("deepzip", {}), 64)
    )
    restored = decode_byte_symbol_bridge(ROOT, artifact)[0]
    assert restored.content_id == original.content_id
    assert restored.values["bytes"].shape == (n,)


def test_direct_deepzip_native_bytes_remains_rejected_and_bridge_is_explicit():
    original = _object(8)
    from tscompbench.pipelines import PipelineRecipe, encode_object

    with pytest.raises(SourceDomainError, match="MODEL_ALPHABET_UNSUPPORTED"):
        encode_object(
            ROOT, original, PipelineRecipe({"bytes": ChildSpec("deepzip", {})}, None, None, 8)
        )
    assert ByteSymbolRecipe(ChildSpec("deepzip", {})).to_document()["mapping"] == "BYTE_TO_RADIX4"


def test_radix4_artifact_rejects_header_count_mapping_or_child_tampering():
    artifact = encode_byte_symbol_bridge(
        ROOT, _object(17), ByteSymbolRecipe(ChildSpec("deepzip", {}))
    )

    def changed(mutator):
        magic, size, payload = _FRAME.unpack_from(artifact.stream)
        header = json.loads(artifact.stream[_FRAME.size : _FRAME.size + size])
        mutator(header)
        encoded = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        return (
            _FRAME.pack(magic, len(encoded), payload)
            + encoded
            + artifact.stream[_FRAME.size + size :]
        )

    with pytest.raises(PipelineError):
        decode_byte_symbol_bridge(ROOT, changed(lambda h: h.update(original_byte_count=16)))
    with pytest.raises(PipelineError):
        decode_byte_symbol_bridge(
            ROOT, changed(lambda h: h["recipe"].update(digit_order="LSB_FIRST"))
        )
    with pytest.raises(PipelineError):
        decode_byte_symbol_bridge(ROOT, changed(lambda h: h.update(native_input_elements=17)))


def test_radix4_missing_public_child_dependency_fails_cleanly():
    artifact = encode_byte_symbol_bridge(
        ROOT, _object(8), ByteSymbolRecipe(ChildSpec("deepzip", {}))
    )
    with pytest.raises(PipelineError, match="failed|unavailable"):
        decode_byte_symbol_in_fresh_process(ROOT, artifact, available_child_keys=set())
