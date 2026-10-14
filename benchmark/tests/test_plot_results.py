"""Saved figure evidence uses exact schedules without codec execution or plotting."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

from tsbench.trial_analysis import analysis_dependency_hash


def plot_tool():
    path = Path(__file__).resolve().parents[1] / "tools" / "plot_results.py"
    spec = importlib.util.spec_from_file_location("plot_results_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence():
    manifest = {"run_id": "saved", "state": "complete", "cases": [
        {"case_id": "a", "status": "ready", "codec": "raw-store", "raw_bytes": 100}],
        "schedule": [{"case_id": "a", "session": 0, "round": n} for n in (0, 1)],
        "resolved_config": {"task": {"fidelity": "bitwise"}}}
    rows = [{"event": "terminal", "phase": "measurement", "run_id": "saved",
             "case_id": "a", "session": 0, "round": n, "attempt": 0, "status": "ok",
             "encode_ns": 100, "decode_ns": 200, "stored_bytes": 50} for n in (0, 1)]
    return manifest, rows


def save_run(path, manifest, rows):
    path.mkdir()
    (path / "manifest.json").write_text(json.dumps(manifest))
    # A blank physical line and a non-terminal row must not change raw trace positions.
    lines = [b"\n", b'{"event":"started"}\n']
    lines.extend(json.dumps(row).encode() + b"\n" for row in rows)
    (path / "observations.jsonl").write_bytes(b"".join(lines))
    return lines


@pytest.mark.parametrize("change,reason", [
    ("duplicate_terminal", "duplicate terminal attempt"),
    ("duplicate_schedule", "duplicate scheduled trial"),
    ("unscheduled", "unscheduled measurement"),
    ("foreign_run", "different run"),
])
def test_plot_aggregation_rejects_invalid_evidence(tmp_path, change, reason):
    tool = plot_tool()
    manifest, rows = evidence()
    if change == "duplicate_terminal":
        rows.append(copy.deepcopy(rows[0]))
    elif change == "duplicate_schedule":
        manifest["schedule"].append(copy.deepcopy(manifest["schedule"][0]))
    elif change == "unscheduled":
        rows[1]["round"] = 9
    else:
        rows[1]["run_id"] = "another"
    path = tmp_path / "run"
    save_run(path, manifest, rows)
    before = (path / "observations.jsonl").read_bytes()
    with pytest.raises(ValueError, match=reason):
        tool.aggregate_cases(tool.load_run(path, tmp_path))
    assert (path / "observations.jsonl").read_bytes() == before


def test_plot_aggregation_preserves_physical_line_and_line_hash(tmp_path):
    tool = plot_tool()
    manifest, rows = evidence()
    path = tmp_path / "run"
    lines = save_run(path, manifest, rows)
    case = tool.aggregate_cases(tool.load_run(path, tmp_path))[0]
    assert case["category"] == "complete" and case["complete"]
    assert case["requested_trials"] == 2 and case["missing_trials"] == 0
    assert [row["observation_line"] for row in case["primary_trials"]] == [3, 4]
    assert [row["observation_line_sha256"] for row in case["primary_trials"]] == [
        hashlib.sha256(line).hexdigest() for line in lines[2:]]


def test_plot_aggregation_keeps_missing_keys_and_original_executed_failure(tmp_path):
    tool = plot_tool()
    manifest, rows = evidence()
    missing = tmp_path / "missing"
    save_run(missing, manifest, rows[:1])
    case = tool.aggregate_cases(tool.load_run(missing, tmp_path))[0]
    assert case["category"] == "partial/not_run"
    assert case["missing_trial_keys"] == [{"session": 0, "round": 1}]
    original = rows[0]
    attempts = [{**original, "status": "not_run"}, {**original, "status": "error", "attempt": 1},
                {**original, "attempt": 2}, rows[1]]
    retry = tmp_path / "retry"
    save_run(retry, manifest, attempts)
    case = tool.aggregate_cases(tool.load_run(retry, tmp_path))[0]
    assert case["category"] == "error" and not case["complete"]
    assert case["primary_trials"][0]["attempt"] == 1
    assert case["trial_status_counts"] == {"error": 1, "ok": 1}
    assert len(case["all_terminal_attempts"]) == 4


def test_source_drift_cannot_complete_or_enter_pilot_figure(tmp_path):
    tool = plot_tool()
    manifest, rows = evidence()
    manifest["execution_source_unchanged"] = False
    path = tmp_path / "drifted"
    save_run(path, manifest, rows)
    cases = tool.aggregate_cases(tool.load_run(path, tmp_path))
    assert cases[0]["category"] == "error" and not cases[0]["complete"]
    assert not cases[0]["execution_source_valid"]
    assert cases[0]["invalidity_reason"] == "execution_source_changed_during_run"
    with pytest.raises(ValueError, match="requires all planned primary trials"):
        tool.pilot_plot(cases, tmp_path / "figures", None)


def test_figure_trace_records_public_analysis_helper_hash(tmp_path, monkeypatch):
    tool = plot_tool()
    manifest, rows = evidence()
    path = tmp_path / "run"
    save_run(path, manifest, rows)
    before = (path / "observations.jsonl").read_bytes()
    matplotlib = types.ModuleType("matplotlib")
    matplotlib.__version__ = "synthetic"
    matplotlib.use = lambda backend: None
    pyplot = types.ModuleType("matplotlib.pyplot")
    pyplot.rcParams = {}
    matplotlib.pyplot = pyplot
    monkeypatch.setitem(sys.modules, "matplotlib", matplotlib)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", pyplot)
    monkeypatch.setattr(tool, "coverage_plot", lambda cases, cards, output, plt: {"cases": cases})
    monkeypatch.setattr(tool, "pilot_plot", lambda cases, output, plt: {"cases": []})
    monkeypatch.setattr(sys, "argv", [str(tool.__file__), "--root", str(tmp_path),
                                     "--coverage-run", "run", "--pilot-run", "run", "--output", "figures"])
    tool.main()
    trace = json.loads((tmp_path / "figures" / "trace.json").read_text())
    assert trace["trial_analysis_hash"] == analysis_dependency_hash()
    assert trace["coverage"]["cases"][0]["primary_trials"][0]["observation_line"] == 3
    assert (path / "observations.jsonl").read_bytes() == before
