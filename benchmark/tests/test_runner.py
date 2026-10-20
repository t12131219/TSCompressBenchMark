"""Fault isolation and admission identity; synthetic objects are correctness fixtures."""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from tsbench.records import canonical_json, read_jsonl
from tsbench.runner import WorkerProcess, run
from tsbench.worker import implementation_identity


@pytest.mark.parametrize("termination,expected", [("os._exit(17)", 17),
                                                 ("os.kill(os.getpid(),signal.SIGKILL)", -signal.SIGKILL)])
def test_parent_records_native_crash_with_signal_evidence(tmp_path, termination, expected):
    code = ("import os,sys,signal,json;sys.stdin.readline();"
            "print(json.dumps({'event':'stage','stage':'encode.finalize'}),flush=True);" + termination)
    worker = WorkerProcess(tmp_path / "crash.log", command=[sys.executable, "-u", "-c", code])
    try:
        result = worker.request({"op": "trial"}, 5)
        assert result["status"] == "crash" and result["stage"] == "encode.finalize"
        assert result["returncode"] == expected
        assert result["signal"] == (-expected if expected < 0 else None)
        assert result["oom_evidence"] is None  # SIGKILL alone cannot establish OOM.
    finally:
        worker.close()


def test_timeout_stops_the_worker_process_group(tmp_path):
    code = ("import sys,time,subprocess,json;sys.stdin.readline();"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            "print(json.dumps({'event':'stage','stage':'decode','child_pid':child.pid}),flush=True);"
            "time.sleep(60)")
    worker = WorkerProcess(tmp_path / "timeout.log", command=[sys.executable, "-u", "-c", code])
    events = []
    try:
        result = worker.request({"op": "trial"}, 0.3, events.append)
        assert result["status"] == "timeout" and result["stage"] == "decode"
        assert worker.process.poll() is not None
        child_pid = events[0]["child_pid"]
        proc_stat = Path(f"/proc/{child_pid}/stat")
        # A killed descendant may briefly remain an unreaped zombie.
        if proc_stat.exists():
            assert proc_stat.read_text().rsplit(")", 1)[1].split()[0] == "Z"
    finally:
        worker.close()


def test_timeout_includes_backpressure_when_child_does_not_read_stdin(tmp_path):
    worker = WorkerProcess(tmp_path / "blocked-input.log", command=[sys.executable, "-u", "-c", "import time;time.sleep(60)"])
    started = time.monotonic()
    try:
        result = worker.request({"op": "test", "body": "x" * 2 * 1024**2}, 0.3)
        assert result["status"] == "timeout"
        assert time.monotonic() - started < 3
        assert worker.process.poll() is not None
    finally:
        worker.close()


def test_dead_group_leader_cannot_leave_descendant_holding_protocol_pipe(tmp_path):
    code = ("import sys,subprocess,json,os;sys.stdin.readline();"
            "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']);"
            "print(json.dumps({'event':'stage','stage':'decode','child_pid':child.pid}),flush=True);os._exit(17)")
    worker = WorkerProcess(tmp_path / "dead-leader.log", command=[sys.executable, "-u", "-c", code])
    events = []
    try:
        result = worker.request({"op": "trial"}, 3, events.append)
        assert result["status"] == "crash" and result["returncode"] == 17
        assert result["stage"] == "decode"
    finally:
        worker.close()
    child_pid = events[0]["child_pid"]
    status = Path(f"/proc/{child_pid}/stat")
    deadline = time.monotonic() + 1
    while status.exists() and status.read_text().rsplit(")", 1)[1].split()[0] != "Z" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not status.exists() or status.read_text().rsplit(")", 1)[1].split()[0] == "Z"


def test_nonobject_protocol_json_has_recorded_error_instead_of_parent_exception(tmp_path):
    worker = WorkerProcess(tmp_path / "protocol.log", command=[sys.executable, "-u", "-c", "import sys;sys.stdin.readline();print('[]',flush=True)"])
    try:
        result = worker.request({"op": "trial"}, 3)
        assert result["status"] == "error" and result["stage"] == "worker.protocol"
    finally:
        worker.close()


def _raw_config(tmp_path):
    bits = np.array([0, 0x8000000000000000, 0x7ff0000000000000, 0x7ff8000000000042], dtype="<u8")
    np.save(tmp_path / "values.npy", bits.view("<f8"))
    return {"schema": "tsbench.experiment/1", "name": "protocol-correctness",
            "_base_dir": str(tmp_path), "_asset_root": str(Path(__file__).resolve().parents[2]),
            "_build_root": str(tmp_path / "cache"),
            "datasets": [{"id": "special-values", "path": "values.npy", "format": "npy"}],
            "methods": [{"id": "raw", "codec": "raw-store"}],
            "profiles": [{"id": "single", "device": "cpu", "native_threads": 1, "object_workers": 1}],
            "execution": {"sessions": 1, "rounds": 1, "warmup_objects": 0, "timeout_s": 10,
                          "qualification_cache": True}}


def _qualification(root):
    rows, tail = read_jsonl(root / "observations.jsonl")
    assert tail is None
    return {row["qualification_kind"]: row for row in rows
            if row["phase"] == "qualification" and row["event"] == "terminal"}


def test_exact_input_cache_is_distinct_from_implementation_cache(tmp_path):
    config = _raw_config(tmp_path)
    first = run(config, tmp_path / "first")
    evidence = _qualification(first)
    assert not evidence["implementation"]["cache_hit"] and not evidence["exact"]["cache_hit"]
    assert evidence["exact"]["independent_recovery"]["decoder_process"]
    second = run(config, tmp_path / "second")
    evidence = _qualification(second)
    assert evidence["implementation"]["cache_hit"] and evidence["exact"]["cache_hit"]
    changed = np.load(tmp_path / "values.npy").copy().view("<u8")
    changed[-1] ^= np.uint64(1)  # A NaN payload bit is part of the raw identity.
    np.save(tmp_path / "values.npy", changed.view("<f8"))
    before = (first / "observations.jsonl").read_bytes()
    with pytest.raises(ValueError, match="dataset content changed"):
        run(config, first, resume=True)
    assert (first / "observations.jsonl").read_bytes() == before
    third = run(config, tmp_path / "third")
    evidence = _qualification(third)
    assert evidence["implementation"]["cache_hit"] and not evidence["exact"]["cache_hit"]


@pytest.mark.parametrize("mask_dtype", ["|u1", "bool"])
def test_records_npz_binary_masks_pass_suite_and_exact_admission(tmp_path, mask_dtype):
    # Integer mask fixtures must stay 0/1 even when suite rows exceed two.
    # Masked values still contain payload bits that an exact records task preserves.
    bits = np.resize(np.array([0, 0x8000000000000000, 0x7ff0000000000000,
                               0x7ff8000000000042, 0xfff8000000000001], dtype="<u8"), 18)
    values = bits.view("<f8").reshape(9, 2)
    epoch = 1_720_000_000_000_000_000
    times = np.array([epoch, epoch, epoch + 60_000_000_000, epoch - 60_000_000_000,
                      epoch + 120_000_000_000, epoch, epoch + 180_000_000_000,
                      epoch + 240_000_000_000, epoch + 300_000_000_000], dtype="<i8")
    mask = np.resize(np.array([1, 0, 0, 1], dtype=mask_dtype), 18).reshape(9, 2)
    source = tmp_path / "records.npz"
    np.savez(source, V=values, T=times, mask=mask)
    source_bytes = source.read_bytes()
    config = _raw_config(tmp_path)
    config["datasets"] = [{"id": "records", "path": source.name, "format": "npz",
                           "components": {"V": "V", "T": "T", "mask": "mask"},
                           "time_unit": "ns"}]
    config["task"] = {"kind": "records", "fidelity": "bitwise", "boundary":"object_memory", "lifecycle":"independent_object"}
    config["execution"]["qualification_cache"] = False

    root = run(config, tmp_path / "records-run")
    evidence = _qualification(root)
    implementation = evidence["implementation"]
    assert implementation["status"] == "ok"
    assert [(fixture["rows"], fixture["status"]) for fixture in implementation["suite"]] == [
        (0, "ok"), (1, "ok"), (7, "ok"), (17, "ok")]
    for fixture in implementation["suite"]:
        recovery = fixture["independent_recovery"]
        assert recovery["decoder_process"] and recovery["decoder_returncode"] == 0
        assert recovery["verification"]["passed"]

    exact = evidence["exact"]
    assert exact["status"] == "ok" and exact["verification"]["input_unchanged"]
    assert exact["verification"]["fidelity"] == "bitwise"
    recovery = exact["independent_recovery"]
    assert recovery["decoder_process"] and recovery["decoder_returncode"] == 0
    assert recovery["verification"]["passed"]
    manifest = json.loads((root / "manifest.json").read_bytes())
    assert recovery["restored_object_id"] == manifest["cases"][0]["raw_object_id"]
    assert manifest["cases"][0]["status"] == "ready"
    assert exact["value_count"] == values.size and exact["timestamp_count"] == times.size
    assert exact["raw_bytes"] == values.nbytes + times.nbytes + mask.nbytes
    rows, tail = read_jsonl(root / "observations.jsonl")
    measurements = [row for row in rows if row["phase"] == "measurement" and row["event"] == "terminal"]
    assert tail is None and len(measurements) == 1 and measurements[0]["status"] == "ok"
    assert source.read_bytes() == source_bytes


def test_binary_and_runtime_dependency_bytes_change_admission_identity(tmp_path):
    library, dependency = tmp_path / "codec.so", tmp_path / "dependency.so"
    library.write_bytes(b"binary-one")
    dependency.write_bytes(b"runtime-one")
    method = {"id": "reference", "codec": "raw-store", "params": {}}
    capability = {"implementation_id": "declared-id", "library_paths": [str(library)],
                  "runtime_dependencies": [{"path": str(dependency)}]}
    asset = Path(__file__).resolve().parents[2]
    initial = implementation_identity(method, capability, asset, tmp_path, {"native_threads": 1})
    library.write_bytes(b"binary-two")
    binary_changed = implementation_identity(method, capability, asset, tmp_path, {"native_threads": 1})
    assert binary_changed != initial
    dependency.write_bytes(b"runtime-two")
    assert implementation_identity(method, capability, asset, tmp_path, {"native_threads": 1}) != binary_changed


def test_resume_retains_unknown_started_attempt_before_rerunning(tmp_path):
    config = _raw_config(tmp_path)
    root = run(config, tmp_path / "run")
    path = root / "observations.jsonl"
    rows, _ = read_jsonl(path)
    # Simulate parent interruption after started but before terminal persistence.
    rows = [row for row in rows if not (row["phase"] == "measurement" and row["event"] == "terminal")]
    path.write_bytes(b"".join(canonical_json(row) + b"\n" for row in rows))
    run(config, root, resume=True)
    rows, _ = read_jsonl(path)
    terminals = [row for row in rows if row["phase"] == "measurement" and row["event"] == "terminal"]
    assert [(row["attempt"], row["status"]) for row in terminals] == [(0, "error"), (1, "ok")]
    assert terminals[0]["reason"] == "interrupted_attempt_without_terminal"
    summary = json.loads((root / "report/summary.json").read_bytes())["cases"][0]
    assert summary["ok_primary_trials"] == 0 and summary["latest_attempt_status_counts"] == {"ok": 1}
    assert summary["status_counts"] == {"error": 1, "ok": 1}
    complete = path.read_bytes()
    run(config, root, resume=True)
    assert path.read_bytes() == complete
