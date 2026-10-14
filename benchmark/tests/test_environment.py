"""Topology missingness and historical isolation are part of the evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tsbench.environment import cgroup_snapshot, cpu_list, hardware_snapshot, manifest_supplement, read_field
from tsbench.records import file_hash, write_json


def put(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


def test_topology_smt_and_missing_frequency_numa(tmp_path):
    sys_root, proc_root = tmp_path / "sys", tmp_path / "proc"
    cpu = sys_root / "devices/system/cpu"
    put(cpu / "online", "0-3")
    for index in range(4):
        put(cpu / f"cpu{index}/topology/physical_package_id", "0")
        put(cpu / f"cpu{index}/topology/core_id", str(index // 2))
        put(cpu / f"cpu{index}/topology/thread_siblings_list", "0-1" if index < 2 else "2-3")
    put(proc_root / "self/status", "Cpus_allowed_list:\t1-3\nMems_allowed_list:\t0\n")
    put(proc_root / "cpuinfo", "model name : fixture CPU\nflags : alpha beta\ncpu MHz : 2400.125\n\nmodel name : fixture CPU\nflags : beta gamma\n")
    snapshot = hardware_snapshot(sys_root, proc_root)
    assert snapshot["cpu"]["physical_cores_online"]["value"] == 2
    assert snapshot["cpu"]["online_smt_threads_per_core"]["value"] == [2, 2]
    assert snapshot["cpu"]["isa_common_flags"]["value"] == ["beta"]
    assert snapshot["cpu"]["recorder_allowed_cpus"]["value"] == [1, 2, 3]
    assert snapshot["frequency"]["policy_unavailable_reason"] == "cpufreq_policies_not_exposed"
    assert snapshot["numa"]["nodes_available"]["value"] is None
    assert snapshot["gpu"]["usable_executor"]["value"] is None
    (cpu / "cpu2/topology/core_id").unlink()
    incomplete = hardware_snapshot(sys_root, proc_root)
    assert incomplete["cpu"]["physical_cores_online"]["value"] is None
    assert incomplete["cpu"]["physical_cores_online"]["reason"] == "incomplete_exposed_topology"


def test_unified_cgroup_exposed_leaf_is_not_total_budget(tmp_path):
    proc_root, cg_root = tmp_path / "proc", tmp_path / "cg"
    put(proc_root / "self/cgroup", "0::/hidden-container-parent/child\n")
    put(cg_root / "cgroup.controllers", "cpu memory cpuset")
    put(cg_root / "cpu.max", "200000 100000")
    put(cg_root / "memory.max", "max")
    put(cg_root / "cpuset.cpus.effective", "0-3")
    snapshot = cgroup_snapshot(proc_root, cg_root)
    assert snapshot["exposed_root"] == str(cg_root)
    assert snapshot["bounds"]["cpu.max"]["value"] == "200000 100000"
    assert snapshot["bounds"]["memory.max"]["value"] == "max"
    assert snapshot["bounds"]["pids.max"]["value"] is None
    assert snapshot["bounds"]["pids.max"]["reason"] == "not_exposed"
    assert snapshot["hierarchical_effective_limits"]["value"] is None


def test_permission_failure_records_null_and_reason(tmp_path, monkeypatch):
    real = Path.read_text
    path = tmp_path / "unreadable"
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("fixture")
        return real(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", denied)
    assert read_field(path) == {"value": None, "reason": "permission_denied", "source": str(path)}


def test_historical_supplement_does_not_backfill_or_change_manifest(tmp_path):
    build = tmp_path / "build.json"
    write_json(build, {"compilers": {"cc": {"version": "fixture"}}, "commands": [["cc", "-O3"]], "runtime_dependencies": []})
    path = tmp_path / "manifest.json"
    write_json(path, {"run_id": "old", "environment": {"cpu_model": "fixture"}, "cases": [{"case_id": "one", "build_evidence": [{"path": str(build), "hash": file_hash(build)}]}]})
    original = path.read_bytes()
    supplement = manifest_supplement(path)
    assert supplement["build_records"][0]["matches_recorded"] is True
    assert all(item["value"] is None and "not_recorded_at_run" in item["reason"] for item in supplement["historical_missing"].values())
    assert path.read_bytes() == original
    build.write_text("{}")
    assert manifest_supplement(path)["build_records"][0]["matches_recorded"] is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="actual Linux resource enforcement")
def test_actual_worker_resource_limit_and_affinity_are_read_back():
    allowed = sorted(os.sched_getaffinity(0))
    program = """import json,mmap,os,resource
from tsbench.executors.cpu import apply_profile
profile=apply_profile({'native_threads':1,'affinity':[int(os.environ['TSBENCH_TEST_CPU'])],'memory_limit_mb':128},{})
soft,hard=resource.getrlimit(resource.RLIMIT_AS)
try:
    mmap.mmap(-1,256*1024**2)
    rejected=False
except (OSError,MemoryError):
    rejected=True
print(json.dumps({'effective':profile,'soft':soft,'hard':hard,'affinity':sorted(os.sched_getaffinity(0)),'rejected':rejected,'numpy_preloaded':'numpy' in __import__('sys').modules}))
"""
    environment = {**os.environ, "TSBENCH_TEST_CPU": str(allowed[0])}
    completed = subprocess.run([sys.executable, "-c", program], env=environment, check=True, capture_output=True, text=True, timeout=10)
    result = json.loads(completed.stdout)
    assert result["soft"] == result["hard"] == 128 * 1024**2
    limit = result["effective"]["memory_limit"]
    assert limit["implemented"] and limit["effective_soft_bytes"] == result["soft"]
    assert limit["effective_hard_bytes"] == result["hard"]
    assert result["affinity"] == [allowed[0]]
    assert result["rejected"] and not result["numpy_preloaded"]


def test_cpu_list_rejects_inverted_or_huge_ranges():
    assert cpu_list("0-2,2,5") == [0, 1, 2, 5]
    for value in ("3-1", "0-1000001", "-1"):
        with pytest.raises(ValueError):
            cpu_list(value)
