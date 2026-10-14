"""Real process isolation, complete collection recovery and bounded pipe failures."""
from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import sys
import time

import numpy as np
import pytest

from tsbench.build import artifact_path
from tsbench.config import resolve
from tsbench.pool import Channel, PoolFailure, pack_collection, run, unpack_collection
from tsbench.records import read_jsonl

ROOT = Path(__file__).resolve().parents[2]


def test_collection_directory_order_and_full_cost():
    wires = {"a": b"first wire", "b": b"second wire"}
    bundle = pack_collection(["b", "a"], wires)
    order, restored = unpack_collection(bundle)
    assert order == ["b", "a"] and restored == wires
    assert len(bundle) > sum(map(len, wires.values()))
    for bad in (bundle[:-1], bundle + b"x", bundle[:-1] + bytes([bundle[-1] ^ 1])):
        with pytest.raises(ValueError):
            unpack_collection(bad)
    bad_header = bytearray(bundle)
    bad_header[55] ^= 1
    with pytest.raises(ValueError, match="directory checksum"):
        unpack_collection(bytes(bad_header))
    with pytest.raises(ValueError):
        pack_collection(["a", "a"], wires)


def test_large_blocked_pipe_has_deadline_and_cleanup(tmp_path):
    channel = Channel(tmp_path / "blocked.log", {}, [sys.executable, "-c", "import time; time.sleep(20)"])
    started = time.monotonic()
    try:
        with pytest.raises(PoolFailure) as failure:
            channel.request({"data": "x" * (512 * 1024)}, time.monotonic() + 0.15)
        assert failure.value.status == "timeout"
    finally:
        channel.close(time.monotonic(), graceful=False)
    assert time.monotonic() - started < 2
    assert channel.process.poll() is not None


def test_crash_does_not_become_oom_or_hang(tmp_path):
    channel = Channel(tmp_path / "crash.log", {}, [sys.executable, "-c", "import os; os._exit(11)"])
    try:
        with pytest.raises(PoolFailure) as failure:
            channel.request({"op": "anything"}, time.monotonic() + 2)
        assert failure.value.status == "crash"
        assert "oom" not in failure.value.evidence
    finally:
        channel.close(time.monotonic(), graceful=False)


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process-group cleanup requires POSIX")
def test_cleanup_kills_descendants_even_after_leader_exit(tmp_path):
    pidfile = tmp_path / "child.pid"
    program = (
        "import subprocess,sys,os,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "open(sys.argv[1],'w').write(str(child.pid)); "
        "print('{\"event\":\"result\",\"status\":\"ok\"}',flush=True); os._exit(0)"
    )
    channel = Channel(tmp_path / "group.log", {}, [sys.executable, "-c", program, str(pidfile)])
    try:
        assert channel.request({}, time.monotonic() + 2)["status"] == "ok"
        channel.process.wait(timeout=2)
        child_pid = int(pidfile.read_text())
    finally:
        channel.close(time.monotonic(), graceful=False)
    status = Path(f"/proc/{child_pid}/status")
    # A killed orphan may remain a zombie until init reaps it; it cannot execute.
    deadline = time.monotonic() + 1
    while status.is_file() and "\nState:\tZ" not in status.read_text() and time.monotonic() < deadline:
        time.sleep(0.01)
    if status.is_file():
        assert "\nState:\tZ" in status.read_text()


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="process groups require POSIX")
def test_dead_leader_with_retained_pipe_is_crash(tmp_path):
    program = "import subprocess,sys,os; subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); os._exit(11)"
    channel = Channel(tmp_path / "retained.log", {}, [sys.executable, "-c", program])
    started = time.monotonic()
    try:
        with pytest.raises(PoolFailure) as failure:
            channel.request({}, time.monotonic() + 3)
        assert failure.value.status == "crash"
        assert failure.value.evidence["returncode"] == 11
    finally:
        channel.close(time.monotonic(), graceful=False)
    assert time.monotonic() - started < 1


def test_final_close_result_is_drained_after_select_exit_race(tmp_path, monkeypatch):
    program = "import sys,os; sys.stdin.readline(); print('{\"event\":\"result\",\"status\":\"ok\",\"closed\":true}',flush=True); os._exit(0)"
    channel = Channel(tmp_path / "close.log", {}, [sys.executable, "-c", program])
    real_selector = selectors.DefaultSelector
    class ExitRaceSelector(real_selector):
        calls = 0
        def select(self, timeout=None):
            self.calls += 1
            if self.calls == 2:
                # The write completed on call 1. Reproduce select timing out just
                # before the child writes its valid final response and exits.
                channel.process.wait(timeout=2)
                return []
            return super().select(timeout)
    monkeypatch.setattr(selectors, "DefaultSelector", ExitRaceSelector)
    try:
        response = channel.request({"op": "close"}, time.monotonic() + 3)
        assert response["status"] == "ok" and response["closed"]
    finally:
        channel.close(time.monotonic(), graceful=False)


def test_encoder_input_mutation_has_error_and_remaining_not_run(tmp_path, monkeypatch):
    import tsbench.pool as pool_module
    np.save(tmp_path / "original.npy", np.arange(7, dtype="<i2"))
    experiment = resolve({"schema": "tsbench.experiment/1", "name": "pool-mutation",
                          "asset_root": str(ROOT), "build_root": str(ROOT / "build/tsbench"),
                          "datasets": [{"id": "source", "path": "original.npy"}],
                          "methods": [{"id": "raw", "codec": "raw-store"}], "execution": {"timeout_s": 10}}, tmp_path)
    program = """from tsbench.schemes import ObjectScheme
from tsbench.pool import _serve
original = ObjectScheme.encode_once
def mutate(self, obj):
    wire = original(self, obj)
    next(iter(obj.components.values())).view('u1').flat[0] ^= 1
    return wire
ObjectScheme.encode_once = mutate
raise SystemExit(_serve())
"""
    real_channel = pool_module.Channel
    class MutatingChannel(real_channel):
        def __init__(self, log, profile, command=None):
            super().__init__(log, profile, [sys.executable, "-c", program])
    monkeypatch.setattr(pool_module, "Channel", MutatingChannel)
    location = run({"schema": "tsbench.pool/1", "experiment": experiment, "output": str(tmp_path / "run"),
                    "workers": [1], "lifecycles": ["persistent_pool"], "sessions": 1,
                    "rounds": 2, "warmup_collections": 0, "seed": 7, "timeout_s": 10})
    rows, _ = read_jsonl(location / "observations.jsonl")
    terminal = [row for row in rows if row["event"] == "terminal"]
    assert len(terminal) == 4
    encode = [row for row in terminal if row["operation"] == "encode"]
    assert encode[0]["status"] == "error" and "input changed" in encode[0]["reason"]
    assert Path(encode[0]["artifact_path"]).is_file()
    assert encode[1]["status"] == "not_run"
    assert all(row["status"] == "not_run" for row in terminal if row["operation"] == "decode")


def test_actual_raw_zstd_collection_processes_and_lifecycles(tmp_path):
    if not artifact_path(ROOT, "zstd-frame").is_file():
        pytest.skip("build zstd-frame first")
    first = np.array([0, 0x8000000000000000, 0x7ff8000000000017, 0x3ff0000000000000], dtype="<u8").view("<f8")
    second = np.asfortranarray(np.arange(15, dtype="<f8").reshape(5, 3))
    np.save(tmp_path / "first.npy", first)
    np.save(tmp_path / "second.npy", second)
    experiment = resolve({"schema": "tsbench.experiment/1", "name": "pool-correctness",
                          "asset_root": str(ROOT), "build_root": str(ROOT / "build/tsbench"),
                          "datasets": [{"id": "first", "path": "first.npy"}, {"id": "second", "path": "second.npy"}],
                          "methods": [{"id": "raw", "codec": "raw-store"}, {"id": "zstd", "codec": "zstd-frame"}],
                          "execution": {"timeout_s": 20}}, tmp_path)
    config = {"schema": "tsbench.pool/1", "experiment": experiment, "output": str(tmp_path / "run"),
              "workers": [2], "lifecycles": ["cold_pool", "persistent_pool"], "sessions": 1,
              "rounds": 2, "warmup_collections": 1, "seed": 7, "timeout_s": 20}
    location = run(config)
    manifest = json.loads((location / "manifest.json").read_bytes())
    rows, tail = read_jsonl(location / "observations.jsonl")
    assert tail is None and manifest["state"] == "complete"
    terminal = [row for row in rows if row["event"] == "terminal"]
    assert len(terminal) == 16
    assert all(row["status"] == "ok" for row in terminal), terminal
    assert len(manifest["schedule"]) == len(terminal)
    assert all(row["stored_bytes"] == row["object_wire_bytes"] + row["collection_index_bytes"] for row in terminal)
    assert all(row["collection_index_bytes"] > 0 and row["collection_wall_ns"] > 0 for row in terminal)
    for row in terminal:
        assert set(row["verification"]) == {"first", "second"}
        assert all(check["passed"] for check in row["verification"].values())
        assert all(worker["pid"] != os.getpid() for worker in row["workers_evidence"])
        assert row["parent_before"]["pid"] == os.getpid() and row["parent_completed"]["cpu_user_s"] >= row["parent_before"]["cpu_user_s"]
        assert len({item["pid"] for item in row["actual_schedule"]}) == 2
        order, wires = unpack_collection(Path(row["artifact_path"]).read_bytes())
        assert order == ["first", "second"] and len(wires) == 2
    for method in ("raw", "zstd"):
        for operation in ("encode", "decode"):
            persistent = [row for row in terminal if row["method_id"] == method and row["operation"] == operation and row["lifecycle"] == "persistent_pool"]
            cold = [row for row in terminal if row["method_id"] == method and row["operation"] == operation and row["lifecycle"] == "cold_pool"]
            pids = lambda row: {item["pid"] for item in row["actual_schedule"]}
            assert pids(persistent[0]) == pids(persistent[1])
            assert pids(cold[0]).isdisjoint(pids(cold[1]))
    assert np.load(tmp_path / "first.npy").view("<u8").tobytes() == first.view("<u8").tobytes()
    groups = json.loads((location / "report.json").read_bytes())["groups"]
    # This fixture requests only W2, so no W1 baseline may be fabricated.
    assert all(item["paired_baseline"]["complete_session_pairs"] == 0 and item["paired_baseline"]["median_session_speedup"] is None for item in groups)
