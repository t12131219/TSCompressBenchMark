"""Frozen V3.2 measurement budgets and executable development-only pilot probes."""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import random
import re
import statistics
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields
from decimal import Decimal
from typing import Any

from tscompbench.ids import stable_id

from .thread_monitor import ParentThreadMonitor, unobserved_threads

VERSION = "tscb.measurement-protocol.v3.2"


class MeasurementProtocolError(ValueError):
    pass


def _integer(value: Any, name: str, minimum: int = 1) -> None:
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise MeasurementProtocolError(f"{name} must be a finite integer >= {minimum}")


def _fraction(value: Any, name: str, *, allow_zero: bool = False) -> None:
    decimal = _decimal(value, name)
    if not (0 <= decimal < 1 if allow_zero else 0 < decimal < 1):
        raise MeasurementProtocolError(f"{name} must be a decimal string in (0, 1)")


def _decimal(value: Any, name: str) -> Decimal:
    if not isinstance(value, str) or re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value) is None:
        raise MeasurementProtocolError(f"{name} must be a finite non-negative decimal string")
    return Decimal(value)


def decimal_observations(value: Any) -> Any:
    """Make finite observed ratios canonical without silently accepting NaN/Inf."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MeasurementProtocolError("non-finite observation cannot be persisted")
        return format(Decimal(str(value)), "f")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise MeasurementProtocolError("non-finite observation cannot be persisted")
        return format(value, "f")
    if isinstance(value, Mapping):
        return {key: decimal_observations(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [decimal_observations(item) for item in value]
    return value


@dataclass(frozen=True)
class MeasurementProtocol:
    profile: str
    outer_repetitions: int
    encode_min_ns: int
    decode_min_ns: int
    max_trial_wall_ns: int
    max_total_wall_ns: int
    warmup_min_count: int = 1
    warmup_min_ns: int = 0
    max_inner_iterations: int = 1_000_000
    max_retries: int = 0
    start_method: str = "spawn"
    worker_initial_state: str = "FRESH_INTERPRETER"
    timing_scope: str = "PIPELINE"
    estimand: str = "DIRECTION_NS_PER_INDEPENDENT_OBJECT"
    clock: str = "PERF_COUNTER_NS"
    context_policy: str = "FRESH_ENCODE_AND_DECODE_CONTEXT_PER_OBJECT"
    cache_policy: str = "WARM_INPUT_OS_CACHE_UNCONTROLLED"
    cold_start_boundary: str | None = None
    collector_mode: str = "ENABLED"
    thread_monitor_interval_ns: int | None = None
    stop_mode: str = "FIXED_REPETITIONS"
    min_outer_repetitions: int = 1
    precision_relative_halfwidth: str | None = None
    precision_checkpoints: tuple[int, ...] = ()
    confidence_level: str = "0.95"
    sequential_method: str | None = None
    max_noise_cv: str | None = None
    pilot_repetitions: int = 7
    pilot_seed: int = 0
    min_clock_signal_ratio: int = 100
    max_harness_fraction: str = "0.05"
    max_collector_fraction: str = "0.15"
    max_load_1m: str | None = None
    max_temperature_c: str | None = None
    max_throttle_ratio: str | None = None
    require_environment_observations: bool = False
    retry_policy: str = "FAILED_ATTEMPTS_ONLY_RETAIN_ALL"
    exclusion_policy: str = "PREDECLARED_CORRECTNESS_RESOURCE_AND_ENVIRONMENT_GATES"

    def __post_init__(self) -> None:
        for name in (
            "profile",
            "start_method",
            "worker_initial_state",
            "timing_scope",
            "estimand",
            "clock",
            "context_policy",
            "cache_policy",
            "collector_mode",
            "stop_mode",
            "retry_policy",
            "exclusion_policy",
        ):
            if not isinstance(getattr(self, name), str):
                raise MeasurementProtocolError(f"{name} must be a string")
        for name in (
            "outer_repetitions",
            "encode_min_ns",
            "decode_min_ns",
            "max_trial_wall_ns",
            "max_total_wall_ns",
            "max_inner_iterations",
            "min_outer_repetitions",
            "pilot_repetitions",
            "min_clock_signal_ratio",
        ):
            _integer(getattr(self, name), name)
        for name in ("warmup_min_count", "warmup_min_ns", "max_retries", "pilot_seed"):
            _integer(getattr(self, name), name, 0)
        if self.outer_repetitions > 1_000_000 or self.pilot_repetitions > 1000:
            raise MeasurementProtocolError("repetition budget exceeds the supported finite bound")
        if self.max_retries > 10:
            raise MeasurementProtocolError("max_retries must be <= 10")
        if self.min_outer_repetitions > self.outer_repetitions:
            raise MeasurementProtocolError("minimum outer count exceeds the frozen budget")
        if self.profile not in {"STEADY_PROCESS", "COLD_PROCESS"}:
            raise MeasurementProtocolError("unsupported process profile")
        if self.start_method not in {"spawn", "fork"}:
            raise MeasurementProtocolError("start_method must be spawn or fork")
        expected_state = "FRESH_INTERPRETER" if self.start_method == "spawn" else "FORK_SNAPSHOT"
        if self.worker_initial_state != expected_state:
            raise MeasurementProtocolError("worker_initial_state does not match start_method")
        if self.profile == "COLD_PROCESS":
            if self.start_method != "spawn" or self.warmup_min_count or self.warmup_min_ns:
                raise MeasurementProtocolError("cold process requires spawn and no prior warmup")
            if self.cold_start_boundary != "SPAWN_THROUGH_OUTPUT_MATERIALIZATION":
                raise MeasurementProtocolError("cold process must include startup/loading boundary")
            if self.cache_policy != "OS_CACHE_UNCONTROLLED":
                raise MeasurementProtocolError(
                    "cold process cannot claim warmed or cleared OS cache"
                )
        elif not self.warmup_min_count and not self.warmup_min_ns:
            raise MeasurementProtocolError("steady process must declare worker-local warmup")
        elif self.cold_start_boundary is not None:
            raise MeasurementProtocolError("steady process cannot declare a cold-start boundary")
        if self.context_policy != "FRESH_ENCODE_AND_DECODE_CONTEXT_PER_OBJECT":
            raise MeasurementProtocolError("context reuse requires a separate implemented protocol")
        if self.clock != "PERF_COUNTER_NS" or self.timing_scope not in {"CORE", "PIPELINE", "E2E"}:
            raise MeasurementProtocolError("unsupported clock/timing boundary")
        if self.estimand != "DIRECTION_NS_PER_INDEPENDENT_OBJECT":
            raise MeasurementProtocolError("unsupported estimand")
        if self.cache_policy not in {"WARM_INPUT_OS_CACHE_UNCONTROLLED", "OS_CACHE_UNCONTROLLED"}:
            raise MeasurementProtocolError("unsupported cache policy")
        if self.collector_mode not in {"DISABLED", "ENABLED"}:
            raise MeasurementProtocolError("collector_mode must be ENABLED or DISABLED")
        if self.thread_monitor_interval_ns is not None:
            _integer(self.thread_monitor_interval_ns, "thread_monitor_interval_ns", 1_000_000)
            if self.collector_mode != "ENABLED":
                raise MeasurementProtocolError(
                    "parent thread monitoring requires enabled collector"
                )
        if self.stop_mode not in {"FIXED_REPETITIONS", "FIXED_BUDGET", "PRECISION_PREDECLARED"}:
            raise MeasurementProtocolError("unsupported stopping policy")
        minimum_trial = self.warmup_min_ns + self.encode_min_ns + self.decode_min_ns
        if self.max_trial_wall_ns <= minimum_trial:
            raise MeasurementProtocolError(
                "trial wall budget must exceed warmup plus both directions"
            )
        required_count = (
            self.outer_repetitions
            if self.stop_mode == "FIXED_REPETITIONS"
            else self.min_outer_repetitions
        )
        if self.max_total_wall_ns < minimum_trial * required_count:
            raise MeasurementProtocolError(
                "total wall budget cannot fund the declared minimum trials"
            )
        if self.warmup_min_count > self.max_inner_iterations:
            raise MeasurementProtocolError("warmup count exceeds max_inner_iterations")
        _fraction(self.confidence_level, "confidence_level")
        for name in ("max_harness_fraction", "max_collector_fraction"):
            _fraction(getattr(self, name), name, allow_zero=True)
        if self.stop_mode == "PRECISION_PREDECLARED":
            _fraction(self.precision_relative_halfwidth, "precision_relative_halfwidth")
            if self.min_outer_repetitions < 2 or self.sequential_method != "BONFERRONI_LOOKS":
                raise MeasurementProtocolError(
                    "precision requires independent N>=2 and BONFERRONI_LOOKS"
                )
            if (
                type(self.precision_checkpoints) is not tuple
                or not self.precision_checkpoints
                or any(
                    type(n) is not int
                    or not self.min_outer_repetitions <= n <= self.outer_repetitions
                    for n in self.precision_checkpoints
                )
                or tuple(sorted(set(self.precision_checkpoints))) != self.precision_checkpoints
            ):
                raise MeasurementProtocolError(
                    "precision checkpoints must be frozen, unique and bounded"
                )
        elif (
            self.precision_relative_halfwidth is not None
            or self.precision_checkpoints
            or self.sequential_method is not None
        ):
            raise MeasurementProtocolError(
                "fixed stopping cannot contain undeclared precision looks"
            )
        for name in ("max_noise_cv", "max_load_1m", "max_temperature_c", "max_throttle_ratio"):
            value = getattr(self, name)
            if value is not None:
                _decimal(value, name)
        if (
            self.max_throttle_ratio is not None
            and _decimal(self.max_throttle_ratio, "max_throttle_ratio") > 1
        ):
            raise MeasurementProtocolError("max_throttle_ratio must be <= 1")
        if type(self.require_environment_observations) is not bool:
            raise MeasurementProtocolError("environment observation requirement must be boolean")
        if self.retry_policy != "FAILED_ATTEMPTS_ONLY_RETAIN_ALL":
            raise MeasurementProtocolError("retries must preserve all failed attempts")
        if self.exclusion_policy != "PREDECLARED_CORRECTNESS_RESOURCE_AND_ENVIRONMENT_GATES":
            raise MeasurementProtocolError("unsupported exclusion policy")

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> MeasurementProtocol:
        allowed = {item.name for item in fields(cls)} | {"schema_version", "protocol_id"}
        if (
            not isinstance(document, Mapping)
            or document.get("schema_version") != VERSION
            or set(document) - allowed
        ):
            raise MeasurementProtocolError("invalid measurement protocol version or unknown fields")
        values = {
            key: value
            for key, value in document.items()
            if key not in {"schema_version", "protocol_id"}
        }
        if "precision_checkpoints" in values:
            if not isinstance(values["precision_checkpoints"], list | tuple):
                raise MeasurementProtocolError("precision_checkpoints must be an array")
            values["precision_checkpoints"] = tuple(values["precision_checkpoints"])
        try:
            result = cls(**values)
        except TypeError as error:
            raise MeasurementProtocolError(str(error)) from error
        if document.get("protocol_id", result.protocol_id) != result.protocol_id:
            raise MeasurementProtocolError("measurement protocol identity mismatch")
        return result

    @property
    def protocol_id(self) -> str:
        return stable_id("measurement-protocol-v32", {"schema_version": VERSION, **asdict(self)})

    def to_document(self) -> dict[str, Any]:
        document = {"schema_version": VERSION, **asdict(self), "protocol_id": self.protocol_id}
        document["precision_checkpoints"] = list(self.precision_checkpoints)
        return document

    @property
    def look_confidence_level(self) -> str:
        if not self.precision_checkpoints:
            return self.confidence_level
        return format(
            1 - (1 - Decimal(self.confidence_level)) / len(self.precision_checkpoints), "f"
        )

    def stop_decision(
        self,
        *,
        completed_outer: int,
        elapsed_ns: int,
        precision_evidence: Mapping[str, Any] | None = None,
        noise_cv: str | None = None,
    ) -> dict[str, Any]:
        _integer(completed_outer, "completed_outer", 0)
        _integer(elapsed_ns, "elapsed_ns", 0)
        exhausted = (
            completed_outer >= self.outer_repetitions or elapsed_ns >= self.max_total_wall_ns
        )
        reason = "CONTINUE"
        sufficient = completed_outer >= self.min_outer_repetitions
        observed_noise = None if noise_cv is None else _decimal(noise_cv, "noise_cv")
        noise_ok = self.max_noise_cv is None or (
            observed_noise is not None and observed_noise <= Decimal(self.max_noise_cv)
        )
        if self.stop_mode == "PRECISION_PREDECLARED" and precision_evidence is not None:
            if completed_outer not in self.precision_checkpoints:
                raise MeasurementProtocolError(
                    "precision evidence supplied outside a frozen checkpoint"
                )
            expected = {
                "method": self.sequential_method,
                "confidence_level": self.look_confidence_level,
                "sample_unit": "OUTER_PROCESS_OR_SCHEDULE_BLOCK",
                "sample_count": completed_outer,
            }
            if any(precision_evidence.get(key) != value for key, value in expected.items()):
                raise MeasurementProtocolError(
                    "precision evidence does not match registered looks/unit"
                )
            halfwidth = _decimal(precision_evidence.get("relative_halfwidth"), "relative_halfwidth")
            if (
                elapsed_ns < self.max_total_wall_ns
                and sufficient
                and noise_ok
                and halfwidth <= Decimal(self.precision_relative_halfwidth)
            ):
                reason = "PRECISION_REACHED"
        if reason == "CONTINUE" and exhausted:
            reason = (
                "FIXED_REPETITIONS_COMPLETE"
                if self.stop_mode == "FIXED_REPETITIONS"
                and completed_outer >= self.outer_repetitions
                and noise_ok
                else "FIXED_BUDGET_COMPLETE"
                if self.stop_mode == "FIXED_BUDGET" and sufficient and noise_ok
                else "INCONCLUSIVE"
            )
        return {
            "stop": reason != "CONTINUE",
            "reason": reason,
            "evidence_sufficient": reason not in {"CONTINUE", "INCONCLUSIVE"},
            "completed_outer": completed_outer,
            "elapsed_ns": elapsed_ns,
        }


def _pilot_worker(
    connection: Any,
    protocol: MeasurementProtocol,
    workload: Callable[[], Mapping[str, int]],
    harness_probe: Callable[[], Any],
    collector_enabled_probe: Callable[[], Mapping[str, int]] | None,
) -> None:
    """Stream completed probes so a killed callback cannot erase prior evidence."""
    pid = os.getpid()

    def probe(function: Callable[[], Any], kind: str, **labels: Any) -> tuple[Any, int]:
        # Announce the probe before opening its timing boundary.  Sending this
        # lifecycle event is control-plane IPC and must not be charged to the
        # callback, especially for the empty harness probe.  Workload probes
        # expose the same callback boundary; their returned direction timings
        # remain measured by the declared workload itself.
        connection.send(
            {
                "kind": "PROBE_STARTED",
                "started_ns": time.perf_counter_ns(),
                "phase": kind,
                "collector": labels.get("collector", "DISABLED"),
            }
        )
        started = time.perf_counter_ns()
        value = function()
        finished = time.perf_counter_ns()
        if kind != "HARNESS":
            if not isinstance(value, Mapping) or set(value) not in (
                {"encode_ns", "decode_ns"},
                {"encode_ns", "decode_ns", "inner_iterations"},
            ):
                raise MeasurementProtocolError("pilot workload must return encode_ns/decode_ns")
            for key in value:
                _integer(value[key], key)
            if value.get("inner_iterations", 1) > protocol.max_inner_iterations:
                raise MeasurementProtocolError("probe exceeds frozen inner iteration budget")
        event = {
            "kind": kind,
            "worker_pid": pid,
            "started_ns": started,
            "finished_ns": finished,
            "call_wall_ns": finished - started,
            **labels,
        }
        if kind != "HARNESS":
            event.update(value)
            event.setdefault("inner_iterations", 1)
        connection.send(event)
        return value, finished - started

    try:
        connection.send(
            {"kind": "WORKER_STARTED", "worker_pid": pid, "started_ns": time.perf_counter_ns()}
        )
        info = time.get_clock_info("perf_counter")
        ticks = []
        previous = time.perf_counter_ns()
        for _ in range(1000):
            current = time.perf_counter_ns()
            if current > previous:
                ticks.append(current - previous)
            previous = current
        quantum = max(1, math.ceil(info.resolution * 1e9), min(ticks) if ticks else 0)
        connection.send(
            {
                "kind": "CLOCK",
                "name": protocol.clock,
                "monotonic": info.monotonic,
                "declared_resolution_ns": math.ceil(info.resolution * 1e9),
                "observed_positive_quantum_ns": quantum,
            }
        )
        warmup_started = time.perf_counter_ns()
        warmup_count = 0
        conditioning = collector_enabled_probe if protocol.collector_mode == "ENABLED" else workload
        while (
            warmup_count < protocol.warmup_min_count
            or time.perf_counter_ns() - warmup_started < protocol.warmup_min_ns
        ):
            if warmup_count >= protocol.max_inner_iterations:
                raise MeasurementProtocolError("WARMUP_EXCEEDS_INNER_ITERATION_BUDGET")
            probe(conditioning, "WARMUP", index=warmup_count, collector=protocol.collector_mode)
            warmup_count += 1
        connection.send(
            {
                "kind": "WARMUP_COMPLETE",
                "worker_pid": pid,
                "count": warmup_count,
                "started_ns": warmup_started,
                "finished_ns": time.perf_counter_ns(),
                "profile": protocol.profile,
            }
        )
        rng = random.Random(protocol.pilot_seed)
        for index in range(protocol.pilot_repetitions):
            probe(harness_probe, "HARNESS", index=index)
            modes = ["DISABLED"] + (["ENABLED"] if collector_enabled_probe else [])
            rng.shuffle(modes)
            for mode in modes:
                function = workload if mode == "DISABLED" else collector_enabled_probe
                probe(function, "WORKLOAD", index=index, collector=mode)
        connection.send({"kind": "COMPLETE", "finished_ns": time.perf_counter_ns()})
    except BaseException as error:
        connection.send(
            {
                "kind": "FAILED",
                "exception_type": type(error).__name__,
                "message": str(error),
                "finished_ns": time.perf_counter_ns(),
            }
        )
    finally:
        connection.close()


def _pilot_metrics(
    protocol: MeasurementProtocol,
    raw: list[dict[str, Any]],
    harness: list[int],
    clock: dict[str, Any] | None,
    *,
    complete: bool,
    failure: str | None,
) -> dict[str, Any]:
    baseline = [item for item in raw if item["collector"] == "DISABLED"]
    enabled = [item for item in raw if item["collector"] == "ENABLED"]
    directions = ("encode_ns", "decode_ns")
    per_object = {
        key: [Decimal(item[key]) / Decimal(item["inner_iterations"]) for item in baseline]
        for key in directions
    }
    medians = {
        key: statistics.median(values) if values else None for key, values in per_object.items()
    }
    noise = {
        key: statistics.pstdev(values) / statistics.mean(values) if values else None
        for key, values in per_object.items()
    }
    harness_fraction = (
        None
        if not baseline or not harness
        else statistics.median([Decimal(value) for value in harness]) / min(medians.values())
    )
    off_by_index = {item["index"]: item for item in baseline}
    on_by_index = {item["index"]: item for item in enabled}
    collector_fraction = {}
    for key in directions:
        changes = [
            abs(
                (Decimal(on_by_index[index][key]) / on_by_index[index]["inner_iterations"])
                / (Decimal(off_by_index[index][key]) / off_by_index[index]["inner_iterations"])
                - 1
            )
            for index in sorted(set(off_by_index) & set(on_by_index))
        ]
        collector_fraction[key] = statistics.median(changes) if changes else None
    required_signal = (
        None
        if clock is None
        else clock["observed_positive_quantum_ns"] * protocol.min_clock_signal_ratio
    )
    reasons = [failure] if failure else []
    if not complete or len(baseline) != protocol.pilot_repetitions:
        reasons.append("PILOT_INCOMPLETE")
    if protocol.collector_mode == "ENABLED" and (
        len(enabled) != protocol.pilot_repetitions or set(off_by_index) != set(on_by_index)
    ):
        reasons.append("COLLECTOR_PAIRING_INCOMPLETE")
    if (
        required_signal is None
        or min(protocol.encode_min_ns, protocol.decode_min_ns) < required_signal
    ):
        reasons.append("DIRECTION_BUDGET_BELOW_CLOCK_SIGNAL")
    if clock is not None and any(
        item[key] < clock["observed_positive_quantum_ns"] for item in raw for key in directions
    ):
        reasons.append("PROBE_DIRECTION_BELOW_CLOCK_QUANTUM")
    if harness_fraction is None or harness_fraction > Decimal(protocol.max_harness_fraction):
        reasons.append("HARNESS_DISTURBANCE_EXCEEDS_REGISTERED_THRESHOLD")
    if protocol.collector_mode == "ENABLED" and any(
        value is None or value > Decimal(protocol.max_collector_fraction)
        for value in collector_fraction.values()
    ):
        reasons.append("COLLECTOR_DISTURBANCE_EXCEEDS_REGISTERED_THRESHOLD")
    if protocol.max_noise_cv is not None and any(
        value is None or value > Decimal(protocol.max_noise_cv) for value in noise.values()
    ):
        reasons.append("PILOT_NOISE_EXCEEDS_REGISTERED_THRESHOLD")
    recommended = (
        None
        if not baseline
        else max(
            1,
            math.ceil(Decimal(protocol.encode_min_ns) / medians["encode_ns"]),
            math.ceil(Decimal(protocol.decode_min_ns) / medians["decode_ns"]),
        )
    )
    if recommended is not None and recommended > protocol.max_inner_iterations:
        reasons.append("CALIBRATION_EXCEEDS_INNER_ITERATION_BUDGET")
    return decimal_observations(
        {
            "status": "PASS" if not reasons else "INCONCLUSIVE",
            "reasons": reasons,
            "direction_median_ns_per_object": medians,
            "noise_cv": noise,
            "harness_fraction": harness_fraction,
            "collector_direction_fraction": collector_fraction,
            "required_signal_ns": required_signal,
            "recommended_inner_iterations": recommended,
        }
    )


def run_pilot(
    protocol: MeasurementProtocol,
    workload: Callable[[], Mapping[str, int]],
    *,
    development_corpus_id: str,
    test_corpus_id: str,
    harness_probe: Callable[[], Any],
    collector_enabled_probe: Callable[[], Mapping[str, int]] | None = None,
) -> dict[str, Any]:
    """Run bounded worker-local calibration on a separate development corpus.

    Spawn probes must be pickleable top-level callables (or partials). Callbacks
    return encode/decode durations using the declared timing boundary. An enabled
    collector needs the same workload with its real collector on. Calibration
    does not subtract overhead or provide formal cold-start observations.
    """
    if (
        not isinstance(development_corpus_id, str)
        or not development_corpus_id
        or not isinstance(test_corpus_id, str)
        or not test_corpus_id
        or development_corpus_id == test_corpus_id
    ):
        raise MeasurementProtocolError("pilot requires a separate development corpus")
    if protocol.collector_mode == "ENABLED" and collector_enabled_probe is None:
        raise MeasurementProtocolError("enabled collector requires an actual on/off probe")
    if not all(callable(probe) for probe in (workload, harness_probe)) or (
        collector_enabled_probe is not None and not callable(collector_enabled_probe)
    ):
        raise MeasurementProtocolError("pilot probes must be callable")
    context = mp.get_context(protocol.start_method)
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_pilot_worker,
        args=(child, protocol, workload, harness_probe, collector_enabled_probe),
        daemon=False,
    )
    started = time.perf_counter_ns()
    total_deadline = started + protocol.max_total_wall_ns
    active_probe_deadline = None
    events: list[dict[str, Any]] = []
    failure = None
    complete = False
    process_started = False
    monitor = None
    monitored_phase = None
    try:
        process.start()
        process_started = True
        child.close()
        if protocol.thread_monitor_interval_ns is not None:
            monitor = ParentThreadMonitor(process.pid, protocol.thread_monitor_interval_ns)
        while True:
            now = time.perf_counter_ns()
            deadline = min(total_deadline, active_probe_deadline or total_deadline)
            if now >= deadline:
                failure = (
                    "PILOT_CALLBACK_WALL_BUDGET_EXHAUSTED"
                    if active_probe_deadline is not None and active_probe_deadline < total_deadline
                    else "PILOT_WALL_BUDGET_EXHAUSTED"
                )
                break
            wait_seconds = (deadline - now) / 1e9
            if monitor is not None and monitored_phase is not None:
                monitor.sample(monitored_phase)
                wait_seconds = min(wait_seconds, monitor.interval_ns / 1e9)
            if not parent.poll(wait_seconds):
                continue
            try:
                event = parent.recv()
            except EOFError:
                failure = "PILOT_WORKER_EXIT_WITHOUT_COMPLETE"
                break
            events.append(event)
            kind = event["kind"]
            if kind == "PROBE_STARTED":
                active_probe_deadline = event["started_ns"] + protocol.max_trial_wall_ns
                monitored_phase = (
                    event["phase"] + "_COLLECTOR_ENABLED"
                    if event["collector"] == "ENABLED"
                    else None
                )
                if monitor is not None and monitored_phase is not None:
                    monitor.sample(monitored_phase + "_ENTRY", force=True)
            elif kind in {"HARNESS", "WARMUP", "WORKLOAD"}:
                if monitor is not None and monitored_phase is not None:
                    monitor.sample(monitored_phase + "_EXIT", force=True)
                monitored_phase = None
                active_probe_deadline = None
                if event["call_wall_ns"] >= protocol.max_trial_wall_ns:
                    failure = "PILOT_CALLBACK_WALL_BUDGET_EXHAUSTED"
                    break
            elif kind == "FAILED":
                failure = f"{event['exception_type']}: {event['message']}"
                break
            elif kind == "COMPLETE":
                complete = True
                break
    except Exception as error:
        failure = f"PILOT_WORKER_START_FAILURE: {type(error).__name__}: {error}"
    finally:
        child.close()
        parent.close()
        if process_started:
            if not complete and process.is_alive():
                process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                process.kill()
                process.join(timeout=1)
                failure = failure or "PILOT_WORKER_EXIT_TIMEOUT"
    finished = time.perf_counter_ns()
    if complete and finished >= total_deadline:
        failure = failure or "PILOT_WALL_BUDGET_EXHAUSTED"
    if process_started and process.exitcode != 0 and failure is None:
        failure = "PILOT_WORKER_NONZERO_EXIT"
    raw = [
        {key: value for key, value in event.items() if key != "kind"}
        for event in events
        if event["kind"] == "WORKLOAD"
    ]
    harness = [event["call_wall_ns"] for event in events if event["kind"] == "HARNESS"]
    clock = next(
        (
            {key: value for key, value in event.items() if key != "kind"}
            for event in events
            if event["kind"] == "CLOCK"
        ),
        None,
    )
    metrics = _pilot_metrics(protocol, raw, harness, clock, complete=complete, failure=failure)
    document = {
        "schema_version": "tscb.measurement-pilot.v3.2",
        "protocol_id": protocol.protocol_id,
        "development_corpus_id": development_corpus_id,
        "test_corpus_id": test_corpus_id,
        **metrics,
        "failure": failure,
        "clock": clock,
        "raw": raw,
        "harness_probe_wall_ns": harness,
        "overhead_subtracted": False,
        "outer_independence_increased_by_calibration": False,
        "elapsed_wall_ns": finished - started,
        "probe_boundary": "DECLARED_IDENTICAL_WORKLOAD_SELECTED_DIRECTION",
        "lifecycle": {
            "worker_pid": process.pid,
            "parent_pid": os.getpid(),
            "start_method": protocol.start_method,
            "initial_state": protocol.worker_initial_state,
            "parent_started_ns": started,
            "parent_finished_ns": finished,
            "worker_exit_confirmed": process_started and not process.is_alive(),
            "exit_code": process.exitcode,
            "budget_scope": "STARTUP_PLUS_PILOT_CALLBACKS_WITH_BOUNDED_TERMINATION_CLEANUP",
        },
        "warmup": next((event for event in events if event["kind"] == "WARMUP_COMPLETE"), None),
        "progress_events": events,
        "calibration_scope": "DEVELOPMENT_ONLY_NOT_FORMAL_COLD_START_OR_OUTER_REPETITIONS",
        "parent_thread_monitor": (
            unobserved_threads(process.pid) if monitor is None else monitor.to_document()
        ),
        "thread_monitor_pairing": "ENABLED_PROBES_ON_DISABLED_PROBES_OFF",
    }
    document = decimal_observations(document)
    return {**document, "pilot_id": stable_id("measurement-pilot-v32", document)}


def _validate_pilot_evidence(
    protocol: MeasurementProtocol,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute admission from paid raw probes rather than trusting a PASS label.

    This verifies internal frozen evidence consistency; it is not a signature or
    proof against a party fabricating an entire execution transcript.
    """
    if not isinstance(document, Mapping):
        raise MeasurementProtocolError("pilot must be an object")
    values = dict(document)
    identifier = values.pop("pilot_id", None)
    try:
        actual_id = stable_id("measurement-pilot-v32", values)
    except ValueError as error:
        raise MeasurementProtocolError("pilot contains non-canonical observations") from error
    if identifier != actual_id or values.get("protocol_id") != protocol.protocol_id:
        raise MeasurementProtocolError("pilot identity or bound protocol mismatch")
    expected_fields = {
        "schema_version",
        "protocol_id",
        "development_corpus_id",
        "test_corpus_id",
        "status",
        "reasons",
        "direction_median_ns_per_object",
        "noise_cv",
        "harness_fraction",
        "collector_direction_fraction",
        "required_signal_ns",
        "recommended_inner_iterations",
        "failure",
        "clock",
        "raw",
        "harness_probe_wall_ns",
        "overhead_subtracted",
        "outer_independence_increased_by_calibration",
        "elapsed_wall_ns",
        "probe_boundary",
        "lifecycle",
        "warmup",
        "progress_events",
        "calibration_scope",
        "parent_thread_monitor",
        "thread_monitor_pairing",
    }
    if set(values) != expected_fields or values["schema_version"] != "tscb.measurement-pilot.v3.2":
        raise MeasurementProtocolError("pilot has unknown fields or unsupported version")
    if (
        not isinstance(values["development_corpus_id"], str)
        or not values["development_corpus_id"]
        or not isinstance(values["test_corpus_id"], str)
        or not values["test_corpus_id"]
        or values["development_corpus_id"] == values["test_corpus_id"]
    ):
        raise MeasurementProtocolError("pilot does not separate development and test corpora")
    lifecycle = values["lifecycle"]
    if not isinstance(lifecycle, Mapping):
        raise MeasurementProtocolError("pilot lifecycle is absent")
    for key in ("parent_started_ns", "parent_finished_ns", "parent_pid"):
        _integer(lifecycle.get(key), key, 0)
    if (
        lifecycle["parent_finished_ns"] - lifecycle["parent_started_ns"]
        != values["elapsed_wall_ns"]
    ):
        raise MeasurementProtocolError("pilot elapsed wall time differs from lifecycle")
    events = values["progress_events"]
    raw = values["raw"]
    if not isinstance(events, list) or not isinstance(raw, list):
        raise MeasurementProtocolError("pilot must retain ordered raw and progress arrays")
    allowed_kinds = {
        "WORKER_STARTED",
        "CLOCK",
        "PROBE_STARTED",
        "WARMUP",
        "WARMUP_COMPLETE",
        "HARNESS",
        "WORKLOAD",
        "COMPLETE",
        "FAILED",
    }
    for event in events:
        if not isinstance(event, Mapping) or event.get("kind") not in allowed_kinds:
            raise MeasurementProtocolError("pilot progress event is malformed")
    derived_raw = [
        {key: value for key, value in event.items() if key != "kind"}
        for event in events
        if event["kind"] == "WORKLOAD"
    ]
    harness_events = [event for event in events if event["kind"] == "HARNESS"]
    warmup_events = [event for event in events if event["kind"] == "WARMUP"]
    derived_harness = [event["call_wall_ns"] for event in harness_events]
    derived_clock = [
        {key: value for key, value in event.items() if key != "kind"}
        for event in events
        if event["kind"] == "CLOCK"
    ]
    warmup_complete = [event for event in events if event["kind"] == "WARMUP_COMPLETE"]
    if (
        raw != derived_raw
        or values["harness_probe_wall_ns"] != derived_harness
        or len(derived_clock) > 1
        or values["clock"] != (derived_clock[0] if derived_clock else None)
        or len(warmup_complete) > 1
        or values["warmup"] != (warmup_complete[0] if warmup_complete else None)
    ):
        raise MeasurementProtocolError("pilot raw projections differ from retained progress events")
    for event in [*raw, *warmup_events, *harness_events]:
        for key in ("index", "started_ns", "finished_ns", "call_wall_ns", "worker_pid"):
            _integer(event.get(key), key, 0)
        if (
            event["finished_ns"] - event["started_ns"] != event["call_wall_ns"]
            or not lifecycle["parent_started_ns"]
            <= event["started_ns"]
            <= event["finished_ns"]
            <= lifecycle["parent_finished_ns"]
            or event["worker_pid"] != lifecycle.get("worker_pid")
        ):
            raise MeasurementProtocolError("pilot probe timing/worker identity is inconsistent")
    for event in [*raw, *warmup_events]:
        for key in ("encode_ns", "decode_ns", "inner_iterations"):
            _integer(event.get(key), key)
        if (
            event["inner_iterations"] > protocol.max_inner_iterations
            or event["collector"] not in {"ENABLED", "DISABLED"}
            or event["encode_ns"] + event["decode_ns"] > event["call_wall_ns"]
        ):
            raise MeasurementProtocolError("pilot direction totals exceed actual completed work")
    clock = values["clock"]
    if clock is not None:
        for key in ("declared_resolution_ns", "observed_positive_quantum_ns"):
            _integer(clock.get(key), key)
        if (
            clock.get("name") != protocol.clock
            or clock.get("monotonic") is not True
            or clock["observed_positive_quantum_ns"] < clock["declared_resolution_ns"]
        ):
            raise MeasurementProtocolError("pilot lacks matching monotonic clock evidence")
    complete_events = [event for event in events if event["kind"] == "COMPLETE"]
    complete = len(complete_events) == 1 and bool(events) and events[-1]["kind"] == "COMPLETE"
    metrics = _pilot_metrics(
        protocol,
        raw,
        derived_harness,
        clock,
        complete=complete,
        failure=values["failure"],
    )
    if any(values[key] != value for key, value in metrics.items()):
        raise MeasurementProtocolError(
            "pilot derived duration/noise/collector admission was changed"
        )
    issues = list(metrics["reasons"])
    if (
        lifecycle.get("start_method") != protocol.start_method
        or lifecycle.get("initial_state") != protocol.worker_initial_state
        or lifecycle.get("worker_exit_confirmed") is not True
        or lifecycle.get("exit_code") != 0
        or type(lifecycle.get("worker_pid")) is not int
        or lifecycle["worker_pid"] == lifecycle["parent_pid"]
    ):
        issues.append("PILOT_WORKER_LIFECYCLE_NOT_PROVEN")
    if values["elapsed_wall_ns"] >= protocol.max_total_wall_ns or any(
        event["call_wall_ns"] >= protocol.max_trial_wall_ns
        for event in [*raw, *warmup_events, *harness_events]
    ):
        issues.append("PILOT_ACTUAL_WALL_BUDGET_EXCEEDED")
    if warmup_complete:
        warmup = warmup_complete[0]
        if (
            warmup["count"] != len(warmup_events)
            or warmup["count"] < protocol.warmup_min_count
            or warmup["finished_ns"] - warmup["started_ns"] < protocol.warmup_min_ns
            or warmup["profile"] != protocol.profile
            or warmup["worker_pid"] != lifecycle["worker_pid"]
            or [event["index"] for event in warmup_events] != list(range(len(warmup_events)))
            or any(event["collector"] != protocol.collector_mode for event in warmup_events)
            or any(event["started_ns"] < warmup["finished_ns"] for event in raw)
        ):
            issues.append("PILOT_WORKER_WARMUP_NOT_PROVEN")
    else:
        issues.append("PILOT_WORKER_WARMUP_NOT_PROVEN")
    modes = ["DISABLED"] + (["ENABLED"] if any(r["collector"] == "ENABLED" for r in raw) else [])
    rng = random.Random(protocol.pilot_seed)
    expected_order = []
    for index in range(protocol.pilot_repetitions):
        order = list(modes)
        rng.shuffle(order)
        expected_order.extend((index, mode) for mode in order)
    if complete and (
        [(item["index"], item["collector"]) for item in raw] != expected_order
        or [event["index"] for event in harness_events] != list(range(protocol.pilot_repetitions))
    ):
        issues.append("PILOT_PAIRED_RANDOMIZED_ORDER_DIFFERS")
    monitor = values["parent_thread_monitor"]
    if protocol.thread_monitor_interval_ns is None:
        if monitor != unobserved_threads(lifecycle.get("worker_pid")):
            issues.append("UNDECLARED_PILOT_THREAD_INSTRUMENTATION")
    else:
        if not isinstance(monitor, dict) or not isinstance(monitor.get("samples"), list):
            raise MeasurementProtocolError("pilot parent thread samples are absent")
        reconstructed = ParentThreadMonitor(
            lifecycle["worker_pid"], protocol.thread_monitor_interval_ns
        )
        reconstructed.samples = monitor["samples"]
        if (
            monitor != reconstructed.to_document()
            or monitor["status"] != "OBSERVED"
            or not any(
                sample["phase"].startswith("WORKLOAD_COLLECTOR_ENABLED")
                for sample in monitor["samples"]
            )
            or any("COLLECTOR_ENABLED" not in sample["phase"] for sample in monitor["samples"])
        ):
            issues.append("PILOT_THREAD_MONITOR_NOT_MATCHED")
    if (
        values["overhead_subtracted"] is not False
        or values["outer_independence_increased_by_calibration"] is not False
        or values["thread_monitor_pairing"] != "ENABLED_PROBES_ON_DISABLED_PROBES_OFF"
    ):
        issues.append("PILOT_BOUNDARY_OR_INDEPENDENCE_CLAIM_INVALID")
    return {
        "eligible": not issues,
        "status": "PASS" if not issues else "INCONCLUSIVE",
        "reasons": list(dict.fromkeys(issues)),
        "pilot_id": identifier,
        "recomputed_metrics": metrics,
    }


def validate_pilot_evidence(
    protocol: MeasurementProtocol,
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Return recomputed eligibility; reject malformed or altered frozen evidence."""
    try:
        return _validate_pilot_evidence(protocol, document)
    except MeasurementProtocolError:
        raise
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:
        raise MeasurementProtocolError(f"malformed pilot evidence: {error}") from error
