from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

import qualify_v32_channel_collection as qualification

from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.pipelines.channel_collection import ChannelCollectionArtifact
from tscompbench.pipelines.models import PipelineError, PipelineLedger


def _offline_report(tmp_path, monkeypatch):
    frozen = {"test_only": "mocked dependency closure"}
    monkeypatch.setattr(qualification, "frozen_inputs", lambda root: copy.deepcopy(frozen))

    class FakeLease:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def to_document(self):
            return {"scope": "PURE_TEST_NO_CODEC_OR_HOST_LEASE"}

    monkeypatch.setattr(qualification, "ResourceLease", FakeLease)
    objects = {}

    def encode(root, original, recipe):
        # Structural-validation tests explicitly use fake streams; they never
        # grant the default independent decoder audit or a native PASS.
        stream = original.content_id.encode() + recipe.recipe_id.encode()
        objects[stream] = original
        bits = len(stream) * 8
        return ChannelCollectionArtifact(
            stream,
            PipelineLedger(original.canonical_raw_bits, bits, 0, bits, bits),
            recipe.recipe_id,
            original.content_id,
        )

    def decode(root, artifact, available_child_keys=None):
        if available_child_keys == set():
            raise PipelineError("unavailable mock public child decoder")
        stream = artifact.stream if isinstance(artifact, ChannelCollectionArtifact) else artifact
        original = objects[stream]
        return original, {
            "start_method": "spawn",
            "original_input_available": False,
            "encoder_session_available": False,
            "output_owned_in_worker": True,
            "worker_exit_confirmed": True,
            "exit_code": 0,
            "stream_sha256": hashlib.sha256(stream).hexdigest(),
            "schema_id": original.schema.schema_id,
        }

    monkeypatch.setattr(qualification, "encode_collection", encode)
    monkeypatch.setattr(qualification, "decode_collection_in_fresh_process", decode)
    qualification.qualify(tmp_path, 0)
    return tmp_path / "qualification.json"


def _change(path, mutate):
    document = json.loads(path.read_bytes())
    mutate(document)
    identity = {key: value for key, value in document.items() if key != "qualification_id"}
    document["qualification_id"] = stable_id("channel-collection-qualification-v32", identity)
    path.write_bytes(canonical_json_bytes(document) + b"\n")


def test_structural_only_audit_never_grants_independent_decoder_qualification(
    tmp_path, monkeypatch
):
    path = _offline_report(tmp_path, monkeypatch)
    monkeypatch.setattr(
        qualification,
        "decode_collection_in_fresh_process",
        lambda *args, **kwargs: pytest.fail("structural audit called codec"),
    )
    before = {file: file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()}
    proof = qualification.validate_collection_qualification(path, decode_artifacts=False)
    assert proof["status"] == "STRUCTURAL_EVIDENCE_VALIDATED"
    assert proof["codec_execution_required"] is False
    assert proof["performance_execution_required"] is False
    assert proof["cells"] == 12
    assert before == {file: file.read_bytes() for file in before}


@pytest.mark.parametrize(
    "damage",
    [
        "drop_cell",
        "duplicate_cell",
        "fake_rawbits",
        "fake_recovery",
        "changed_raw",
        "path_escape",
        "dependency_drift",
    ],
)
def test_recomputed_report_id_cannot_hide_incomplete_or_changed_qualification(
    tmp_path,
    monkeypatch,
    damage,
):
    path = _offline_report(tmp_path, monkeypatch)

    def mutate(doc):
        if damage == "drop_cell":
            doc["cells"].pop()
        elif damage == "duplicate_cell":
            doc["cells"][-1] = copy.deepcopy(doc["cells"][0])
        elif damage == "fake_rawbits":
            doc["cells"][0]["original"]["canonical_raw_bits"] += 1
        elif damage == "fake_recovery":
            doc["cells"][0]["recovery"]["encoder_session_available"] = True
        elif damage == "changed_raw":
            raw = tmp_path / doc["cells"][0]["raw"]["path"]
            raw.write_bytes(raw.read_bytes() + b"hidden")
            doc["cells"][0]["raw"]["sha256"] = hashlib.sha256(raw.read_bytes()).hexdigest()
            doc["cells"][0]["raw"]["bytes"] = raw.stat().st_size
        elif damage == "path_escape":
            doc["cells"][0]["raw"]["path"] = "../outside.raw"
        else:
            doc["frozen_inputs"]["test_only"] = "changed runtime"

    _change(path, mutate)
    with pytest.raises(ValueError):
        qualification.validate_collection_qualification(path, decode_artifacts=False)


def test_existing_qualification_report_cannot_be_replaced(tmp_path, monkeypatch):
    path = _offline_report(tmp_path, monkeypatch)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="immutable"):
        qualification.qualify(tmp_path, 0)
    assert path.read_bytes() == before
