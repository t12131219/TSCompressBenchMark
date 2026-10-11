from __future__ import annotations

import multiprocessing as mp
import os
from dataclasses import replace
from pathlib import Path

import pytest

from tscompbench.ids import canonical_json_bytes
from tscompbench.measurement import resource_lease as leases
from tscompbench.measurement.resource_lease import (
    ResourceLease,
    ResourceLeaseConflict,
    ResourceLeaseError,
    environment_gate,
    evaluate_environment,
    sample_environment,
)
from tscompbench.measurement.v32_protocol import MeasurementProtocol


def protocol(**kwargs):
    return MeasurementProtocol("STEADY_PROCESS", 1, 1000, 1000, 1_000_000, 1_000_000, **kwargs)


def lease(root, **kwargs):
    args = {
        "run_set_id": "run",
        "logical_cpus": (min(os.sched_getaffinity(0)),),
        "threads": 1,
        "memory_limit_bytes": 1024 * 1024,
        "lock_root": root,
    }
    return ResourceLease(**(args | kwargs))


def child_try_lease(root, cpus, connection):
    try:
        with ResourceLease(
            run_set_id="other-run",
            logical_cpus=cpus,
            threads=1,
            memory_limit_bytes=1024 * 1024,
            lock_root=Path(root),
        ):
            connection.send("ACQUIRED")
    except ResourceLeaseConflict:
        connection.send("CONFLICT")
    finally:
        connection.close()


def child_abandon_lease(root, cpus, connection):
    owner = ResourceLease(
        run_set_id="abandoned-run",
        logical_cpus=cpus,
        threads=1,
        memory_limit_bytes=1024 * 1024,
        lock_root=Path(root),
    )
    owner.__enter__()
    connection.send("ACQUIRED")
    connection.close()
    os._exit(0)


def run_child(function, root, cpus):
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=function, args=(str(root), cpus, child))
    process.start()
    child.close()
    try:
        assert parent.poll(5)
        result = parent.recv()
        process.join(timeout=5)
        assert process.exitcode == 0
        return result
    finally:
        parent.close()
        if process.is_alive():
            process.kill()
            process.join(timeout=1)


def test_real_spawned_processes_cannot_hold_overlapping_host_leases(tmp_path):
    root = tmp_path / "leases"
    original = set(os.sched_getaffinity(0))
    owner = lease(root)
    with owner:
        assert os.sched_getaffinity(0) == set(owner.logical_cpus)
        assert run_child(child_try_lease, root, owner.logical_cpus) == "CONFLICT"
        evidence = owner.to_document()
        assert evidence["status"] == "HELD"
        assert evidence["boundary"]["actual_affinity"] == list(owner.logical_cpus)
        assert evidence["hard_rss_limit"] is False
        assert evidence["external_process_occupancy_controlled"] is False
        assert canonical_json_bytes(evidence)
    assert os.sched_getaffinity(0) == original
    assert owner.to_document()["status"] == "RELEASED"
    assert run_child(child_try_lease, root, owner.logical_cpus) == "ACQUIRED"


def test_kernel_releases_abandoned_spawn_owner_lock(tmp_path):
    root = tmp_path / "leases"
    cpus = (min(os.sched_getaffinity(0)),)
    assert run_child(child_abandon_lease, root, cpus) == "ACQUIRED"
    with lease(root):
        pass


def test_exception_restores_affinity_and_reused_lease_does_not_retain_old_evidence(tmp_path):
    original = set(os.sched_getaffinity(0))
    owner = lease(tmp_path / "leases")
    with pytest.raises(RuntimeError, match="intentional"):
        with owner:
            raise RuntimeError("intentional")
    assert os.sched_getaffinity(0) == original
    first_id = owner.to_document()["lease_id"]
    with owner:
        assert owner.to_document()["lease_id"] != first_id
    assert os.sched_getaffinity(0) == original


def test_declared_thread_smt_numa_and_memory_constraints_are_checked(tmp_path, monkeypatch):
    root = tmp_path / "leases"
    with pytest.raises(ResourceLeaseError):
        lease(root, threads=2)
    with pytest.raises(ResourceLeaseError):
        lease(root, logical_cpus=(True,))
    with pytest.raises(ResourceLeaseError):
        lease(root, allow_smt=1)
    available = sorted(os.sched_getaffinity(0))
    if len(available) >= 2:
        cpus = tuple(available[:2])
        monkeypatch.setattr(
            leases,
            "cpu_topology",
            lambda _: tuple(
                {"logical_cpu": cpu, "physical_core_id": "0:0", "numa_nodes": [0]} for cpu in cpus
            ),
        )
        with pytest.raises(ResourceLeaseError, match="SMT"):
            with lease(root, logical_cpus=cpus):
                pass
        with lease(root, logical_cpus=cpus, allow_smt=True):
            pass
    monkeypatch.setattr(
        leases,
        "cpu_topology",
        lambda cpus: tuple(
            {"logical_cpu": cpu, "physical_core_id": None, "numa_nodes": None} for cpu in cpus
        ),
    )
    with pytest.raises(ResourceLeaseError, match="topology"):
        with lease(root, require_physical_core_evidence=True):
            pass
    with pytest.raises(ResourceLeaseError, match="NUMA"):
        with lease(root, numa_nodes=(0,)):
            pass
    monkeypatch.setattr(leases, "_memory_available", lambda: 1)
    with pytest.raises(ResourceLeaseError, match="memory budget"):
        with lease(root):
            pass
    monkeypatch.setattr(leases, "_memory_available", lambda: 1024 * 1024 * 10)
    with lease(root):
        pass


def test_environment_unknowns_only_fail_declared_required_gates():
    snapshot = {
        "load_1m": {"value": None},
        "temperature_c": {"value": None},
        "throttled_usec": {"value": None},
        "monotonic_ns": 1000,
    }
    p = protocol(max_load_1m="2", max_temperature_c="80", max_throttle_ratio="0.1")
    optional = evaluate_environment(snapshot, p)
    assert optional["eligible"]
    assert optional["missing"] == ["load_1m", "temperature_c", "throttle_ratio"]
    required = evaluate_environment(snapshot, replace(p, require_environment_observations=True))
    assert not required["eligible"]
    assert required["reasons"] == ["REQUIRED_ENVIRONMENT_EVIDENCE_UNAVAILABLE"]
    assert evaluate_environment(snapshot, protocol())["eligible"]
    before = snapshot | {"monotonic_ns": 1000, "throttled_usec": {"value": 0}}
    actual = snapshot | {
        "load_1m": {"value": "4.0"},
        "temperature_c": {"value": "90.5"},
        "throttled_usec": {"value": 500},
        "monotonic_ns": 1_001_000,
    }
    gated = evaluate_environment(actual, p, before=before)
    assert not gated["eligible"]
    assert len(gated["reasons"]) == 3
    assert gated["observed"]["throttle_ratio"] == "0.5"
    assert gated["throttle_scope"] == "CURRENT_CGROUP_AGGREGATE_NOT_CODEC_ATTRIBUTION"
    assert canonical_json_bytes(gated)


def test_fresh_environment_boundaries_are_canonical_and_gate_same_lease(tmp_path):
    snapshot = sample_environment((min(os.sched_getaffinity(0)),))
    assert canonical_json_bytes(snapshot)
    with lease(tmp_path / "leases") as owner:
        before = owner.to_document()
        after = owner.to_document()
        assert after["boundary"]["monotonic_ns"] >= before["boundary"]["monotonic_ns"]
        gate = environment_gate(protocol(), before, after)
        assert gate["eligible"]
        assert gate["before"] == before["boundary"]
        assert gate["after"] == after["boundary"]
        assert canonical_json_bytes(gate)
        with pytest.raises(ResourceLeaseError):
            environment_gate(protocol(), before, after | {"lease_id": "forged"})
