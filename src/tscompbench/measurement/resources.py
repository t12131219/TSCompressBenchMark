from __future__ import annotations

import resource
import time
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from pathlib import Path
from typing import Any


def _proc_io() -> dict[str, int] | None:
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/self/io").read_text(encoding="ascii").splitlines():
            key, value = line.split(":", 1)
            values[key] = int(value.strip())
        return values
    except OSError, ValueError:
        return None


def _current_rss_bytes() -> int | None:
    try:
        fields = Path("/proc/self/status").read_text(encoding="ascii").splitlines()
        value = next(line for line in fields if line.startswith("VmRSS:"))
        return int(value.split()[1]) * 1024
    except OSError, ValueError, StopIteration, IndexError:
        return None


def _status_value(label: str) -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith(label + ":"):
                return int(line.split()[1])
    except OSError, ValueError, IndexError:
        return None
    return None


def _swap_counters() -> tuple[int, int] | None:
    try:
        values = {}
        for line in Path("/proc/vmstat").read_text(encoding="ascii").splitlines():
            key, value = line.split()
            if key in {"pswpin", "pswpout"}:
                values[key] = int(value)
        return values["pswpin"], values["pswpout"]
    except OSError, ValueError, KeyError:
        return None


def _smaps_rollup() -> tuple[int | None, int | None]:
    try:
        fields = Path("/proc/self/smaps_rollup").read_text(encoding="ascii").splitlines()
        values = {
            line.split(":", 1)[0]: int(line.split()[1]) * 1024
            for line in fields
            if ":" in line and line.split()[1].isdigit()
        }
        pss = values.get("Pss")
        private = sum(values.get(key, 0) for key in ("Private_Clean", "Private_Dirty"))
        return pss, private
    except OSError, ValueError, IndexError:
        return None, None


@dataclass(frozen=True)
class _Snapshot:
    wall_ns: int
    user_seconds: Decimal
    system_seconds: Decimal
    minor_faults: int
    major_faults: int
    voluntary_context_switches: int
    involuntary_context_switches: int
    block_input_operations: int
    block_output_operations: int
    max_rss_bytes: int
    current_rss_bytes: int | None
    logical_read_bytes: int | None
    logical_write_bytes: int | None
    physical_read_bytes: int | None
    physical_write_bytes: int | None
    read_syscalls: int | None
    write_syscalls: int | None
    thread_count: int | None
    swap_in_pages: int | None
    swap_out_pages: int | None


def _snapshot(wall_ns: int) -> _Snapshot:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    io = _proc_io()
    swap = _swap_counters()
    # Linux ru_maxrss is KiB. This project currently supports Linux execution only.
    return _Snapshot(
        wall_ns=wall_ns,
        user_seconds=Decimal(str(usage.ru_utime)),
        system_seconds=Decimal(str(usage.ru_stime)),
        minor_faults=int(usage.ru_minflt),
        major_faults=int(usage.ru_majflt),
        voluntary_context_switches=int(usage.ru_nvcsw),
        involuntary_context_switches=int(usage.ru_nivcsw),
        block_input_operations=int(usage.ru_inblock),
        block_output_operations=int(usage.ru_oublock),
        max_rss_bytes=int(usage.ru_maxrss) * 1024,
        current_rss_bytes=_current_rss_bytes(),
        logical_read_bytes=None if io is None else io.get("rchar"),
        logical_write_bytes=None if io is None else io.get("wchar"),
        physical_read_bytes=None if io is None else io.get("read_bytes"),
        physical_write_bytes=None if io is None else io.get("write_bytes"),
        read_syscalls=None if io is None else io.get("syscr"),
        write_syscalls=None if io is None else io.get("syscw"),
        thread_count=_status_value("Threads"),
        swap_in_pages=None if swap is None else swap[0],
        swap_out_pages=None if swap is None else swap[1],
    )


def _delta(after: int | None, before: int | None) -> int | None:
    if after is None or before is None:
        return None
    return max(0, after - before)


@dataclass(frozen=True)
class ResourceObservation:
    requested_scope: str
    actual_scope: str
    scope_availability: str
    scope_reason: str
    memory_accounting_scope: str
    baseline_memory_bytes: int | None
    peak_process_rss_bytes: int
    incremental_peak_memory_bytes: int | None
    process_pss_at_boundary_bytes: int | None
    process_uss_at_boundary_bytes: int | None
    process_user_seconds: str
    process_system_seconds: str
    process_total_seconds: str
    encode_user_seconds: str
    encode_system_seconds: str
    encode_total_seconds: str
    decode_user_seconds: str
    decode_system_seconds: str
    decode_total_seconds: str
    cpu_equivalent_cores: str | None
    cpu_utilization_of_allocation_pct: str | None
    cpu_core_seconds_per_gb: str | None
    minor_faults: int
    major_faults: int
    voluntary_context_switches: int
    involuntary_context_switches: int
    block_input_operations: int
    block_output_operations: int
    logical_read_bytes: int | None
    logical_write_bytes: int | None
    physical_read_bytes: int | None
    physical_write_bytes: int | None
    read_syscalls: int | None
    write_syscalls: int | None
    thread_count_before: int | None
    thread_count_after: int | None
    swap_observed: bool | None
    swap_observation_scope: str
    cpu_throttled_usec: int | None
    throttle_ratio: str | None
    counter_observation: dict[str, Any]
    energy_observation: dict[str, Any]
    sampler_overhead: dict[str, Any]

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": "tscb.resource-observation.v2", **asdict(self)}

    def with_phase_cpu(
        self,
        *,
        encode_user_seconds: Decimal,
        encode_system_seconds: Decimal,
        decode_user_seconds: Decimal,
        decode_system_seconds: Decimal,
    ) -> ResourceObservation:
        return replace(
            self,
            encode_user_seconds=format(encode_user_seconds, "f"),
            encode_system_seconds=format(encode_system_seconds, "f"),
            encode_total_seconds=format(encode_user_seconds + encode_system_seconds, "f"),
            decode_user_seconds=format(decode_user_seconds, "f"),
            decode_system_seconds=format(decode_system_seconds, "f"),
            decode_total_seconds=format(decode_user_seconds + decode_system_seconds, "f"),
        )


class ResourceSampler:
    """Boundary sampler for one isolated repetition.

    It never silently upgrades PROCESS measurements to process-tree or device data.
    Unsupported requested scopes remain explicit in the result.
    """

    def __init__(
        self,
        *,
        requested_scope: str,
        memory_accounting_scope: str,
        counter_method: str,
        energy_method: str,
        allocated_logical_cpus: int,
        canonical_bytes: int,
    ) -> None:
        self.requested_scope = requested_scope
        self.memory_accounting_scope = memory_accounting_scope
        self.counter_method = counter_method
        self.energy_method = energy_method
        self.allocated_logical_cpus = allocated_logical_cpus
        self.canonical_bytes = canonical_bytes
        self._before: _Snapshot | None = None
        self._overhead_ns = 0

    def start(self, wall_ns: int) -> None:
        overhead_start = time.perf_counter_ns()
        self._before = _snapshot(wall_ns)
        self._overhead_ns += time.perf_counter_ns() - overhead_start

    def stop(self, wall_ns: int) -> ResourceObservation:
        if self._before is None:
            raise RuntimeError("resource sampler was not started")
        overhead_start = time.perf_counter_ns()
        after = _snapshot(wall_ns)
        pss, uss = _smaps_rollup()
        self._overhead_ns += time.perf_counter_ns() - overhead_start
        before = self._before
        user = max(Decimal(0), after.user_seconds - before.user_seconds)
        system = max(Decimal(0), after.system_seconds - before.system_seconds)
        total = user + system
        wall_seconds = Decimal(max(0, after.wall_ns - before.wall_ns)) / Decimal(1e9)
        cores = None if wall_seconds == 0 else total / wall_seconds
        utilization = (
            None
            if cores is None or self.allocated_logical_cpus <= 0
            else Decimal(100) * cores / Decimal(self.allocated_logical_cpus)
        )
        core_seconds_per_gb = (
            None
            if self.canonical_bytes <= 0
            else total / (Decimal(self.canonical_bytes) / Decimal(1_000_000_000))
        )
        baseline = before.current_rss_bytes
        incremental = None if baseline is None else max(0, after.max_rss_bytes - baseline)
        if self.requested_scope == "PROCESS":
            actual_scope = "PROCESS"
            availability = "AVAILABLE"
            reason = "GETRUSAGE_AND_PROC_SELF"
        else:
            actual_scope = "PROCESS"
            availability = "UNSUPPORTED"
            reason = "REQUESTED_SCOPE_REQUIRES_EXTERNAL_CGROUP_OR_DEVICE_COLLECTOR"
        counter = {
            "method": self.counter_method,
            "availability": (
                "NOT_COLLECTED" if self.counter_method == "NOT_COLLECTED" else "UNSUPPORTED"
            ),
            "reason": (
                "PROFILE_DISABLED"
                if self.counter_method == "NOT_COLLECTED"
                else "PERF_WRAPPER_NOT_ACTIVE"
            ),
            "values": None,
            "time_enabled_ns": None,
            "time_running_ns": None,
            "multiplex_ratio": None,
            "eligible": False,
        }
        energy = {
            "method": self.energy_method,
            "availability": (
                "NOT_COLLECTED" if self.energy_method == "NOT_COLLECTED" else "UNSUPPORTED"
            ),
            "reason": (
                "PROFILE_DISABLED"
                if self.energy_method == "NOT_COLLECTED"
                else "ENERGY_COLLECTOR_NOT_ACTIVE"
            ),
            "domains": None,
            "joules": None,
        }
        swap_observed = None
        if None not in {
            before.swap_in_pages,
            before.swap_out_pages,
            after.swap_in_pages,
            after.swap_out_pages,
        }:
            swap_observed = bool(
                after.swap_in_pages > before.swap_in_pages
                or after.swap_out_pages > before.swap_out_pages
            )
        return ResourceObservation(
            requested_scope=self.requested_scope,
            actual_scope=actual_scope,
            scope_availability=availability,
            scope_reason=reason,
            memory_accounting_scope=self.memory_accounting_scope,
            baseline_memory_bytes=baseline,
            peak_process_rss_bytes=after.max_rss_bytes,
            incremental_peak_memory_bytes=incremental,
            process_pss_at_boundary_bytes=pss,
            process_uss_at_boundary_bytes=uss,
            process_user_seconds=format(user, "f"),
            process_system_seconds=format(system, "f"),
            process_total_seconds=format(total, "f"),
            encode_user_seconds="0",
            encode_system_seconds="0",
            encode_total_seconds="0",
            decode_user_seconds="0",
            decode_system_seconds="0",
            decode_total_seconds="0",
            cpu_equivalent_cores=None if cores is None else format(cores, ".17g"),
            cpu_utilization_of_allocation_pct=(
                None if utilization is None else format(utilization, ".17g")
            ),
            cpu_core_seconds_per_gb=(
                None if core_seconds_per_gb is None else format(core_seconds_per_gb, ".17g")
            ),
            minor_faults=max(0, after.minor_faults - before.minor_faults),
            major_faults=max(0, after.major_faults - before.major_faults),
            voluntary_context_switches=max(
                0, after.voluntary_context_switches - before.voluntary_context_switches
            ),
            involuntary_context_switches=max(
                0,
                after.involuntary_context_switches - before.involuntary_context_switches,
            ),
            block_input_operations=max(
                0, after.block_input_operations - before.block_input_operations
            ),
            block_output_operations=max(
                0, after.block_output_operations - before.block_output_operations
            ),
            logical_read_bytes=_delta(after.logical_read_bytes, before.logical_read_bytes),
            logical_write_bytes=_delta(after.logical_write_bytes, before.logical_write_bytes),
            physical_read_bytes=_delta(after.physical_read_bytes, before.physical_read_bytes),
            physical_write_bytes=_delta(after.physical_write_bytes, before.physical_write_bytes),
            read_syscalls=_delta(after.read_syscalls, before.read_syscalls),
            write_syscalls=_delta(after.write_syscalls, before.write_syscalls),
            thread_count_before=before.thread_count,
            thread_count_after=after.thread_count,
            swap_observed=swap_observed,
            swap_observation_scope="SYSTEM_VMSTAT",
            cpu_throttled_usec=None,
            throttle_ratio=None,
            counter_observation=counter,
            energy_observation=energy,
            sampler_overhead={
                "method": "BOUNDARY_CALL_CALIBRATION",
                "estimated_ns": self._overhead_ns,
            },
        )
