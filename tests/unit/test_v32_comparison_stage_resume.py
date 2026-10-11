"""Stage resume cannot remeasure saved proof or repair invalid proof in place."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "run_v32_comparison", ROOT / "tools/run_v32_comparison.py"
)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def fail_measurement(*args):
    raise AssertionError("resume performed a measurement")


@pytest.mark.parametrize(
    "stage, filename", [("qualify", "qualification.json"), ("pilot", "pilot.json")]
)
def test_resume_validates_saved_proof_and_preserves_bytes(tmp_path, monkeypatch, stage, filename):
    payload = {"status": "PASS", "proof": "frozen raw observations"}
    target = tmp_path / filename
    target.write_text(json.dumps(payload, indent=2) + "\n")
    if stage == "pilot":
        (tmp_path / "qualification.json").write_text(json.dumps(payload))
    observed = []
    monkeypatch.setattr(
        tool, "validate_qualification_evidence", lambda run, doc: observed.append("q")
    )
    monkeypatch.setattr(tool, "validate_comparison_pilots", lambda run, doc: observed.append("p"))
    monkeypatch.setattr(tool, "qualify_comparison", fail_measurement)
    monkeypatch.setattr(tool, "pilot_comparison", fail_measurement)
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    document, reused = tool.stage_evidence(SimpleNamespace(path=tmp_path), None, stage, resume=True)
    assert document == payload and reused is True
    assert observed == (["q"] if stage == "qualify" else ["q", "p"])
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "stage, filename", [("qualify", "qualification.json"), ("pilot", "pilot.json")]
)
def test_invalid_proof_is_preserved_and_never_remeasured(tmp_path, monkeypatch, stage, filename):
    target = tmp_path / filename
    target.write_text('{"status":"INCOMPLETE"}\n')
    (tmp_path / "qualification.json").write_text('{"status":"INCOMPLETE"}\n')

    def reject(run, document):
        raise ValueError("frozen proof is incomplete or changed")

    monkeypatch.setattr(tool, "validate_qualification_evidence", reject)
    monkeypatch.setattr(tool, "qualify_comparison", fail_measurement)
    monkeypatch.setattr(tool, "pilot_comparison", fail_measurement)
    before = target.read_bytes()
    with pytest.raises(ValueError, match="incomplete or changed"):
        tool.stage_evidence(SimpleNamespace(path=tmp_path), None, stage, resume=True)
    assert target.read_bytes() == before


def test_existing_stage_requires_explicit_resume(tmp_path, monkeypatch):
    (tmp_path / "qualification.json").write_text('{"status":"PASS"}')
    monkeypatch.setattr(tool, "qualify_comparison", fail_measurement)
    with pytest.raises(ValueError, match="use --resume"):
        tool.stage_evidence(SimpleNamespace(path=tmp_path), None, "qualify", resume=False)


def test_new_pilot_requires_valid_qualification_before_measurement(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "pilot_comparison", fail_measurement)
    with pytest.raises(FileNotFoundError):
        tool.stage_evidence(SimpleNamespace(path=tmp_path), None, "pilot", resume=True)
