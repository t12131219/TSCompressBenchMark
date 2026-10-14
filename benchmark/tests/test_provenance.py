"""Execution provenance covers scheduling code without coupling analyses."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tsbench.provenance import execution_provenance, snapshot_sources
from tsbench.runner import run


def test_scheduler_changes_revoke_identity_but_report_changes_do_not(tmp_path):
    for name in ("runner.py", "worker.py", "records.py", "report.py"):
        (tmp_path / name).write_text(name)
    before = execution_provenance(tmp_path)
    assert {row["module"] for row in before["sources"]} == {"runner.py", "worker.py", "records.py"}
    (tmp_path / "report.py").write_text("new analysis")
    assert execution_provenance(tmp_path)["source_id"] == before["source_id"]
    (tmp_path / "runner.py").write_text("new scheduling")
    assert execution_provenance(tmp_path)["source_id"] != before["source_id"]


def test_source_snapshot_preserves_bytes_and_refuses_overwriting_history(tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    (package / "runner.py").write_bytes(b"old execution\n")
    (package / "report.py").write_bytes(b"old analysis\n")
    target = tmp_path / "snapshot"
    snapshot = snapshot_sources(target, package)
    assert len(snapshot["files"]) == 2
    (package / "runner.py").write_bytes(b"changed execution\n")
    assert (target / "runner.py").read_bytes() == b"old execution\n"
    with pytest.raises(FileExistsError):
        snapshot_sources(target, package)
    assert (target / "runner.py").read_bytes() == b"old execution\n"


def test_at_run_snapshots_are_adjacent_evidence_and_not_resume_identity(tmp_path, monkeypatch):
    from tsbench import environment, runner
    values = np.arange(7, dtype="<i8")
    np.save(tmp_path / "values.npy", values)
    snapshots = []
    def capture(root):
        value = {"schema": "fixture", "frequency": len(snapshots), "captured_at": len(snapshots)}
        snapshots.append(value)
        return value
    monkeypatch.setattr(environment, "capture", capture)
    config = {"schema": "tsbench.experiment/1", "name": "provenance-fixture",
              "_base_dir": str(tmp_path), "_asset_root": str(Path(__file__).resolve().parents[2]),
              "_build_root": str(tmp_path / "build"), "datasets": [{"id": "values", "path": "values.npy"}],
              "methods": [{"id": "raw", "codec": "raw-store"}],
              "execution": {"sessions": 1, "rounds": 1, "warmup_objects": 0, "timeout_s": 10}}
    root = run(config, tmp_path / "run")
    manifest = json.loads((root / "manifest.json").read_bytes())
    assert manifest["execution_source_unchanged"]
    assert manifest["environment_snapshots"]["before_admission"]["frequency"] == 0
    assert manifest["environment_snapshots"]["after_measurement"]["frequency"] == 1
    before = (root / "observations.jsonl").read_bytes()
    run(config, root, resume=True)
    assert len(snapshots) == 3
    assert (root / "observations.jsonl").read_bytes() == before
    from tsbench.records import write_json
    latest = json.loads((root / "manifest.json").read_bytes())
    latest["execution_source_unchanged"] = False
    write_json(root / "manifest.json", latest)
    with pytest.raises(ValueError, match="changed during this run"):
        run(config, root, resume=True)
    assert not json.loads((root / "manifest.json").read_bytes())["execution_source_unchanged"]
    latest["execution_source_unchanged"] = True
    write_json(root / "manifest.json", latest)
    recorded = runner.execution_provenance
    monkeypatch.setattr(runner, "execution_provenance", lambda: {**recorded(), "source_id": "changed-runner"})
    with pytest.raises(ValueError, match="execution source differs"):
        run(config, root, resume=True)
    assert (root / "observations.jsonl").read_bytes() == before
