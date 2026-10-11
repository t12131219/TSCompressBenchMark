"""Linux cooperative host leases and honest CPU/NUMA/environment evidence."""

from __future__ import annotations

import fcntl
import json
import math
import os
import time
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id

from .v32_protocol import decimal_observations


class ResourceLeaseError(RuntimeError):
    pass


class ResourceLeaseConflict(ResourceLeaseError):
    pass


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii").strip()
    except OSError, UnicodeError:
        return None


def _value(value: Any, reason: str, *, scope: str) -> dict[str, Any]:
    return {"value": value, "reason": reason if value is None else None, "scope": scope}


def _memory_available() -> int | None:
    content = _read(Path("/proc/meminfo"))
    for line in (content or "").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return None


def cpu_topology(logical_cpus: Sequence[int]) -> tuple[dict[str, Any], ...]:
    result = []
    for cpu in logical_cpus:
        root = Path(f"/sys/devices/system/cpu/cpu{cpu}")
        package = _read(root / "topology/physical_package_id")
        core = _read(root / "topology/core_id")
        nodes = sorted(
            int(path.name[4:]) for path in root.glob("node[0-9]*") if path.name[4:].isdigit()
        )
        result.append(
            {
                "logical_cpu": cpu,
                "package_id": package,
                "core_id": core,
                "physical_core_id": None
                if package is None or core is None
                else f"{package}:{core}",
                "core_type": _read(root / "topology/core_type"),
                "thread_siblings": _read(root / "topology/thread_siblings_list"),
                "numa_nodes": nodes or None,
                "reason": "TOPOLOGY_UNAVAILABLE" if package is None or core is None else None,
            }
        )
    return tuple(result)


def _cgroup_cpu_stat() -> dict[str, int] | None:
    cgroups = _read(Path("/proc/self/cgroup"))
    for line in (cgroups or "").splitlines():
        if line.startswith("0::"):
            relative = line[3:].lstrip("/")
            root = Path("/sys/fs/cgroup")
            path = (root / relative / "cpu.stat").resolve()
            if not path.is_relative_to(root):
                return None
            content = _read(path)
            if content is None:
                return None
            try:
                values = {
                    key: int(value) for key, value in (row.split() for row in content.splitlines())
                }
            except ValueError:
                return None
            return values if "throttled_usec" in values else None
    return None


def sample_environment(logical_cpus: Sequence[int] | None = None) -> dict[str, Any]:
    cpus = (
        tuple(logical_cpus) if logical_cpus is not None else tuple(sorted(os.sched_getaffinity(0)))
    )
    frequency = {}
    governors = {}
    for cpu in cpus:
        root = Path(f"/sys/devices/system/cpu/cpu{cpu}/cpufreq")
        raw = _read(root / "scaling_cur_freq")
        if raw is not None and raw.isdigit():
            frequency[str(cpu)] = int(raw)
        governor = _read(root / "scaling_governor")
        if governor is not None:
            governors[str(cpu)] = governor
    temperatures = {}
    paths = list(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
    paths += list(Path("/sys/class/hwmon").glob("hwmon*/temp*_input"))
    for path in paths:
        raw = _read(path)
        try:
            value = int(raw) / 1000 if raw is not None else None
        except ValueError:
            continue
        if value is not None and -100 < value < 200:
            temperatures[str(path)] = value
    try:
        load = os.getloadavg()[0]
    except OSError, AttributeError:
        load = None
    throttling = _cgroup_cpu_stat()
    try:
        threads = len(list(Path("/proc/self/task").iterdir()))
    except OSError:
        threads = None
    return decimal_observations(
        {
            "schema_version": "tscb.environment-boundary.v3.2",
            "monotonic_ns": time.perf_counter_ns(),
            "frequency_khz": _value(
                frequency or None,
                "CPUFREQ_UNAVAILABLE",
                scope="SELECTED_LOGICAL_CPU_READ_AT_BOUNDARY",
            ),
            "governor": _value(
                governors or None, "GOVERNOR_UNAVAILABLE", scope="SELECTED_LOGICAL_CPU"
            ),
            "load_1m": _value(load, "LOAD_AVERAGE_UNAVAILABLE", scope="HOST_SYSTEM"),
            "temperature_c": _value(
                max(temperatures.values()) if temperatures else None,
                "THERMAL_SENSORS_UNAVAILABLE",
                scope="MAX_VISIBLE_HOST_SENSOR",
            ),
            "temperature_sensors": temperatures or None,
            "throttled_usec": _value(
                None if throttling is None else throttling.get("throttled_usec"),
                "CGROUP_V2_THROTTLE_COUNTER_UNAVAILABLE",
                scope="CURRENT_CGROUP_AGGREGATE",
            ),
            "memory_available_bytes": _value(
                _memory_available(), "MEMAVAILABLE_UNAVAILABLE", scope="HOST_SYSTEM"
            ),
            "thread_count": _value(
                threads, "PROC_TASK_UNAVAILABLE", scope="CURRENT_PROCESS_BOUNDARY_NOT_HIGH_WATER"
            ),
            "actual_affinity": sorted(os.sched_getaffinity(0)),
        }
    )


def evaluate_environment(
    snapshot: dict[str, Any],
    protocol: Any,
    *,
    before: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply only frozen thresholds; missing sensors stay unknown unless explicitly required."""
    reasons = []
    missing = []
    observed = {}
    for metric, threshold in (
        ("load_1m", protocol.max_load_1m),
        ("temperature_c", protocol.max_temperature_c),
    ):
        value = snapshot[metric]["value"]
        observed[metric] = value
        if threshold is not None:
            if value is None:
                missing.append(metric)
            elif Decimal(str(value)) > Decimal(threshold):
                reasons.append(f"{metric.upper()}_EXCEEDS_FROZEN_THRESHOLD")
    throttle_ratio = None
    if before is not None:
        first = before["throttled_usec"]["value"]
        last = snapshot["throttled_usec"]["value"]
        elapsed = snapshot["monotonic_ns"] - before["monotonic_ns"]
        if first is not None and last is not None and last >= first and elapsed > 0:
            throttle_ratio = (last - first) * 1000 / elapsed
    observed["throttle_ratio"] = throttle_ratio
    if protocol.max_throttle_ratio is not None:
        if throttle_ratio is None:
            missing.append("throttle_ratio")
        elif Decimal(str(throttle_ratio)) > Decimal(protocol.max_throttle_ratio):
            reasons.append("CGROUP_THROTTLE_EXCEEDS_FROZEN_THRESHOLD")
    if missing and protocol.require_environment_observations:
        reasons.append("REQUIRED_ENVIRONMENT_EVIDENCE_UNAVAILABLE")
    return decimal_observations(
        {
            "accepted": not reasons,
            "eligible": not reasons,
            "reasons": reasons,
            "missing": missing,
            "observed": observed,
            "external_process_occupancy_controlled": False,
            "throttle_scope": "CURRENT_CGROUP_AGGREGATE_NOT_CODEC_ATTRIBUTION",
        }
    )


def environment_gate(
    protocol: Any,
    lease_before: dict[str, Any],
    lease_after: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate per-trial boundary copies from an acquired resource lease."""
    if (
        lease_before.get("lease_id") != lease_after.get("lease_id")
        or lease_before.get("status") != "HELD"
    ):
        raise ResourceLeaseError("environment boundaries require the same held lease")
    before = lease_before.get("boundary") or lease_before["before"]
    after = lease_after.get("boundary") or lease_after.get("after")
    if after is None:
        raise ResourceLeaseError("lease lacks a current/released environment boundary")
    result = evaluate_environment(after, protocol, before=before)
    return {**result, "before": before, "after": after}


class ResourceLease:
    """Serialize cooperating RunSets on this host/account using Linux flock.

    This does not evict external workloads, bind NUMA memory or impose RSS/cgroup
    limits. Caller processes must stop workers before releasing the owner lease.
    """

    def __init__(
        self,
        *,
        run_set_id: str,
        logical_cpus: Sequence[int],
        threads: int,
        memory_limit_bytes: int,
        processes: int = 1,
        numa_nodes: Sequence[int] = (),
        lock_root: Path | None = None,
        timeout_seconds: float = 0,
        allow_smt: bool = False,
        require_physical_core_evidence: bool = False,
        apply_affinity: bool = True,
    ) -> None:
        cpus = tuple(logical_cpus)
        if not isinstance(run_set_id, str) or not run_set_id or not cpus:
            raise ResourceLeaseError("lease requires identity and unique logical CPUs")
        if any(type(cpu) is not int or cpu < 0 for cpu in cpus):
            raise ResourceLeaseError("logical CPU IDs must be non-negative integers")
        if len(cpus) != len(set(cpus)):
            raise ResourceLeaseError("lease requires unique logical CPUs")
        for name, value in (
            ("threads", threads),
            ("processes", processes),
            ("memory_limit_bytes", memory_limit_bytes),
        ):
            if type(value) is not int or not 1 <= value <= 2**63 - 1:
                raise ResourceLeaseError(f"{name} must be a positive finite integer")
        if threads * processes > len(cpus):
            raise ResourceLeaseError("thread/process budget exceeds allocated logical CPUs")
        if (
            type(timeout_seconds) not in {int, float}
            or not math.isfinite(timeout_seconds)
            or not 0 <= timeout_seconds <= 60
        ):
            raise ResourceLeaseError("lease acquisition timeout must be finite and in [0, 60]")
        if any(type(node) is not int or node < 0 for node in numa_nodes):
            raise ResourceLeaseError("NUMA node IDs must be non-negative integers")
        for name, value in (
            ("allow_smt", allow_smt),
            ("require_physical_core_evidence", require_physical_core_evidence),
            ("apply_affinity", apply_affinity),
        ):
            if type(value) is not bool:
                raise ResourceLeaseError(f"{name} must be boolean")
        self.run_set_id = run_set_id
        self.logical_cpus = tuple(sorted(cpus))
        self.numa_nodes = tuple(sorted(set(numa_nodes)))
        self.threads = threads
        self.processes = processes
        self.memory_limit_bytes = memory_limit_bytes
        self.timeout_seconds = timeout_seconds
        self.allow_smt = allow_smt
        self.require_physical_core_evidence = require_physical_core_evidence
        self.apply_affinity = apply_affinity
        self.lock_root = lock_root or Path("/tmp") / f"tscompbench-resource-leases-{os.getuid()}"
        self._handle = None
        self._original_affinity: set[int] | None = None
        self._document: dict[str, Any] = {}

    def __enter__(self) -> ResourceLease:
        if self._handle is not None:
            raise ResourceLeaseError("lease is already held")
        self._document = {}
        self._original_affinity = None
        available = set(os.sched_getaffinity(0))
        if not set(self.logical_cpus) <= available:
            raise ResourceLeaseError("requested affinity is outside the available CPU set")
        topology = cpu_topology(self.logical_cpus)
        physical = [item["physical_core_id"] for item in topology]
        if self.require_physical_core_evidence and any(value is None for value in physical):
            raise ResourceLeaseError("physical-core topology is required but unavailable")
        known = [value for value in physical if value is not None]
        if not self.allow_smt and len(known) != len(set(known)):
            raise ResourceLeaseError("SMT siblings share a physical core; profile forbids this")
        if self.numa_nodes:
            for item in topology:
                if not item["numa_nodes"] or not set(item["numa_nodes"]) <= set(self.numa_nodes):
                    raise ResourceLeaseError("CPU NUMA topology does not match the frozen nodes")
        self.lock_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(
            self.lock_root / "host.lock",
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        handle = os.fdopen(descriptor, "r+", encoding="utf-8")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise ResourceLeaseConflict(
                        "another cooperating RunSet/process owns the host lease"
                    ) from None
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
        self._handle = handle
        self._original_affinity = available
        try:
            memory = _memory_available()
            if memory is not None and self.memory_limit_bytes > memory:
                raise ResourceLeaseError("memory budget exceeds current host MemAvailable")
            if self.apply_affinity:
                os.sched_setaffinity(0, set(self.logical_cpus))
            acquired = time.perf_counter_ns()
            identity = {
                "run_set_id": self.run_set_id,
                "owner_pid": os.getpid(),
                "acquired_ns": acquired,
                "logical_cpus": self.logical_cpus,
                "threads": self.threads,
                "processes": self.processes,
                "memory_limit_bytes": self.memory_limit_bytes,
                "numa_nodes": self.numa_nodes,
                "lock_path": str(self.lock_root / "host.lock"),
            }
            self._document = {
                "schema_version": "tscb.resource-lease.v3.2",
                **identity,
                "lease_id": stable_id("resource-lease-v32", identity),
                "status": "HELD",
                "lock_method": "LINUX_FLOCK_EXCLUSIVE_HOST_COORDINATOR",
                "exclusion_scope": "COOPERATING_PROCESSES_SAME_HOST_ACCOUNT_AND_LOCK_NAMESPACE",
                "external_process_occupancy_controlled": False,
                "hard_process_tree_limit": False,
                "hard_rss_limit": False,
                "memory_admission": "MEMAVAILABLE_BOUNDARY_CHECK_NOT_OS_RESERVATION",
                "numa_memory_binding": "NOT_ENFORCED_CPU_AFFINITY_ONLY",
                "affinity_scope": "CALLING_THREAD_AND_FUTURE_CHILDREN",
                "topology": list(topology),
                "allow_smt": self.allow_smt,
                "thread_budget": self.threads * self.processes,
                "thread_budget_verification": "CALLER_MUST_CHECK_EACH_WORKER_PROCESS",
                "lifetime_scope": "OWNER_MUST_STOP_WORKERS_BEFORE_RELEASE",
                "owner_exit_scope": "KERNEL_RELEASES_ON_LAST_INHERITED_DESCRIPTOR_CLOSE",
                "before": sample_environment(self.logical_cpus),
                "after": None,
                "released_ns": None,
            }
            handle.seek(0)
            handle.truncate()
            json.dump(self._document, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, exception_type: Any, exception: Any, trace: Any) -> None:
        if self._handle is None:
            return
        try:
            if self._document:
                self._document["after"] = sample_environment(self.logical_cpus)
                self._document["released_ns"] = time.perf_counter_ns()
                self._document["status"] = "RELEASED"
        finally:
            try:
                if self._original_affinity is not None and self.apply_affinity:
                    os.sched_setaffinity(0, self._original_affinity)
                if self._document:
                    self._handle.seek(0)
                    self._handle.truncate()
                    json.dump(self._document, self._handle, sort_keys=True)
                    self._handle.flush()
                    os.fsync(self._handle.fileno())
            finally:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                self._handle.close()
                self._handle = None

    def to_document(self) -> dict[str, Any]:
        if not self._document:
            raise ResourceLeaseError("lease has not been acquired")
        result = json.loads(json.dumps(self._document))
        result["boundary"] = (
            sample_environment(self.logical_cpus) if self._handle is not None else result["after"]
        )
        return result
