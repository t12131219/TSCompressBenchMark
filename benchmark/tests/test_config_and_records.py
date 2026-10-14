from __future__ import annotations

import copy
import json

import pytest

from tsbench.config import resolve
from tsbench.records import append, preserve_tail, read_jsonl, write_json
from tsbench.registry import Registry, UnsupportedError
from tsbench.report import generate


def minimal_config():
    return {"schema": "tsbench.experiment/1", "name": "strict-config",
            "datasets": [{"id": "data", "path": "data.npy", "format": "npy"}],
            "methods": [{"id": "raw", "codec": "raw-store"}]}


@pytest.mark.parametrize("key,value", [("rounds", True), ("sessions", 0), ("warmup_objects", -1),
                                      ("timeout_s", 0), ("timeout_s", float("inf"))])
def test_config_rejects_invalid_execution_budget(key, value):
    config = minimal_config()
    config["execution"] = {key: value}
    with pytest.raises(ValueError):
        resolve(config)


def test_config_rejects_unknowns_duplicate_ids_and_unimplemented_boundary():
    bad = minimal_config()
    bad["silent_cast"] = "float64"
    with pytest.raises(ValueError, match="unknown"):
        resolve(bad)
    bad = minimal_config()
    bad["methods"] *= 2
    with pytest.raises(ValueError, match="duplicate"):
        resolve(bad)
    bad = minimal_config()
    bad["task"] = {"boundary": "device_resident"}
    with pytest.raises(ValueError):
        resolve(bad)


def test_registry_rejects_unknown_and_bool_integer_parameters():
    from pathlib import Path
    registry = Registry(Path(__file__).resolve().parents[2])
    for params in ({"block_size": True}, {"imaginary_option": 1}, {"compression_level": 100}):
        with pytest.raises(UnsupportedError):
            registry.resolve_params("zstd-frame", params)
    assert registry.get("lz77").key == "deflate-zlib"
    assert len(registry.list(include_reference=False)) == 36


def test_interrupted_jsonl_tail_is_preserved_before_recovery(tmp_path):
    path = tmp_path / "observations.jsonl"
    append(path, {"event": "terminal", "status": "ok"})
    interrupted = b'{"event":"terminal","status":'
    with path.open("ab") as stream:
        stream.write(interrupted)
    rows, tail = read_jsonl(path)
    assert rows == [{"event": "terminal", "status": "ok"}]
    preserved = preserve_tail(path, tail)
    assert preserved.read_bytes() == interrupted
    append(path, {"event": "terminal", "status": "crash"})
    rows, tail = read_jsonl(path)
    assert tail is None and [r["status"] for r in rows] == ["ok", "crash"]


def test_malformed_complete_jsonl_is_never_silently_discarded(tmp_path):
    path = tmp_path / "observations.jsonl"
    path.write_bytes(b'{"status":"ok"}\nnot-json\n')
    with pytest.raises(ValueError, match="invalid complete"):
        read_jsonl(path)


def test_report_retains_failures_retries_and_zero_denominator(tmp_path):
    cases = [{"case_id": "partial", "raw_bytes": 100, "status": "ready"},
             {"case_id": "empty", "raw_bytes": 0, "status": "ready"},
             {"case_id": "rejected", "raw_bytes": 100, "status": "unsupported", "reason": "dtype"}]
    schedule = [{"case_id": "partial", "session": 0, "round": r} for r in range(3)] + [{"case_id": "empty", "session": 0, "round": 0}]
    write_json(tmp_path / "manifest.json", {"run_id": "report-only", "cases": cases, "schedule": schedule})
    path = tmp_path / "observations.jsonl"
    append(path, {"event": "terminal", "phase": "measurement", "case_id": "partial", "session": 0,
                  "round": 0, "attempt": 0, "status": "ok", "encode_ns": 20, "decode_ns": 30, "stored_bytes": 80})
    append(path, {"event": "terminal", "phase": "measurement", "case_id": "partial", "session": 0,
                  "round": 1, "attempt": 0, "status": "error", "encode_ns": 1, "decode_ns": 1, "stored_bytes": 1})
    append(path, {"event": "terminal", "phase": "measurement", "case_id": "partial", "session": 0,
                  "round": 2, "attempt": 0, "status": "timeout"})
    append(path, {"event": "terminal", "phase": "measurement", "case_id": "partial", "session": 0,
                  "round": 1, "attempt": 1, "status": "ok", "encode_ns": 10, "decode_ns": 10, "stored_bytes": 10})
    append(path, {"event": "terminal", "phase": "warmup", "case_id": "partial", "status": "ok",
                  "encode_ns": 0, "decode_ns": 0, "stored_bytes": 0})
    append(path, {"event": "terminal", "phase": "measurement", "case_id": "empty", "session": 0,
                  "round": 0, "attempt": 0, "status": "ok", "encode_ns": 10, "decode_ns": 10, "stored_bytes": 200})
    before = path.read_bytes()
    report = generate(tmp_path)
    assert path.read_bytes() == before  # Report can only consume the original measurements.
    result = {c["case_id"]: c for c in report["cases"]}
    assert report["requested_cases"] == 3 and report["planned_trials"] == 4
    assert result["partial"]["planned_trials"] == 3 and result["partial"]["ok_primary_trials"] == 1
    assert result["partial"]["encode_ns"]["median"] == 20
    assert result["partial"]["status_counts"]["timeout"] == 1
    assert not result["partial"]["complete_case"]
    assert result["rejected"]["planned_trials"] == 0 and result["rejected"]["case_status"] == "unsupported"
    assert result["empty"]["stored_fraction"] is None
    assert result["empty"]["compression_ratio"] is None
    assert result["empty"]["encode_MiB_s"] is None
    json.dumps(report, allow_nan=False)
