"""Reports must match exact planned trial identities, not merely counts."""
from __future__ import annotations

import json

import pytest

from tsbench.records import append, file_hash, write_json
from tsbench.report import generate
from tsbench.trial_analysis import scheduled_rows


def fixture(root, rows):
    manifest = {"run_id": "synthetic-report", "cases": [
        {"case_id": "a", "status": "ready", "raw_bytes": 100}],
        "schedule": [{"case_id": "a", "session": 0, "round": index} for index in (0, 1)]}
    write_json(root / "manifest.json", manifest)
    for row in rows:
        append(root / "observations.jsonl", row)
    return manifest


def terminal(round_index=0, **overrides):
    return {"event": "terminal", "phase": "measurement", "case_id": "a", "session": 0,
            "round": round_index, "attempt": 0, "status": "ok", "encode_ns": 100,
            "decode_ns": 200, "stored_bytes": 50, **overrides}


@pytest.mark.parametrize("rows,reason", [
    ([terminal(), terminal(9)], "unscheduled measurement"),
    ([terminal(), terminal(), terminal(1)], "duplicate terminal attempt"),
    ([terminal(), terminal(1, case_id="unrequested")], "unscheduled measurement"),
    ([terminal(), terminal(1, session=True)], "nonnegative integer"),
    ([terminal(), terminal(1, attempt=-1)], "nonnegative integer"),
    ([terminal(), terminal(1, attempt=1, run_id="another")], "different run"),
])
def test_report_rejects_invalid_measurement_evidence_before_writing(tmp_path, rows, reason):
    fixture(tmp_path, rows)
    before = file_hash(tmp_path / "observations.jsonl")
    with pytest.raises(ValueError, match=reason):
        generate(tmp_path)
    assert file_hash(tmp_path / "observations.jsonl") == before
    assert not (tmp_path / "report").exists()


def test_missing_trial_is_explicit_even_when_observed_trial_succeeds(tmp_path):
    fixture(tmp_path, [terminal(1)])
    report = generate(tmp_path)
    case = report["cases"][0]
    assert not case["complete_case"]
    assert case["planned_trials"] == 2 and case["ok_primary_trials"] == 1
    assert case["missing_trial_keys"] == [{"session": 0, "round": 0}]
    assert case["primary_trace"][0]["observation_line"] == 1
    assert report["manifest_hash"] and report["observations_hash"] and report["trial_analysis_hash"]


def test_not_run_placeholder_is_not_failure_but_executed_failure_survives_retry(tmp_path):
    rows = [terminal(status="not_run"), terminal(attempt=1, status="error", encode_ns=999),
            terminal(attempt=2), terminal(1)]
    fixture(tmp_path, rows)
    result = generate(tmp_path)["cases"][0]
    assert not result["complete_case"] and result["ok_primary_trials"] == 1
    assert result["status_counts"] == {"not_run": 1, "error": 1, "ok": 2}
    assert result["primary_trial_status_counts"] == {"error": 1, "ok": 1}
    assert result["latest_attempt_status_counts"] == {"ok": 2}
    assert result["primary_trace"][0]["attempt"] == 1
    assert result["encode_ns"]["median"] == 100
    json.dumps(result, allow_nan=False)


def test_unexecuted_placeholder_followed_by_success_completes_exact_schedule(tmp_path):
    fixture(tmp_path, [terminal(status="not_run"), terminal(attempt=1), terminal(1)])
    result = generate(tmp_path)["cases"][0]
    assert result["complete_case"] and result["missing_trials"] == 0


def test_duplicate_schedule_and_case_are_rejected(tmp_path):
    manifest = fixture(tmp_path, [terminal(), terminal(1)])
    manifest["schedule"].append(manifest["schedule"][0])
    with pytest.raises(ValueError, match="duplicate scheduled trial"):
        scheduled_rows(manifest, [terminal(), terminal(1)])
    manifest["cases"].append(manifest["cases"][0])
    with pytest.raises(ValueError, match="duplicate case id"):
        scheduled_rows(manifest, [terminal(), terminal(1)])
