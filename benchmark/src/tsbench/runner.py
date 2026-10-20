"""Sequential parent scheduling, isolated workers, admission and resume."""
from __future__ import annotations

import copy
import json
import os
import platform
import random
import selectors
import signal
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .records import append, canonical_json, preserve_tail, read_jsonl, stable_hash, write_json
from .provenance import execution_provenance, snapshot_sources
from .config import DEFAULT_TASK, DEFAULT_EXECUTION, validate_boundary



class WorkerProcess:
    """A JSONL protocol that cannot wait forever on a crashed native function."""
    def __init__(self, log_path: str | Path, *, environment: dict[str, str] | None = None,
                 command: list[str] | None = None):
        target = Path(log_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.log = target.open("ab")
        self.process = subprocess.Popen(command or [sys.executable, "-m", "tsbench.worker", "serve"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                        env=environment, start_new_session=True, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        os.set_blocking(self.process.stdout.fileno(), False)
        os.set_blocking(self.process.stdin.fileno(), False)
        self.buffer = b""
        self.stage = "worker.startup"
        self.healthy = True

    def request(self, command: dict[str, Any], timeout: float,
                on_event: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        if not self.healthy:
            return self._crashed()
        started = time.monotonic()
        outgoing = canonical_json(command) + b"\n"
        position = 0
        self.selector.register(self.process.stdin, selectors.EVENT_WRITE)
        try:
            return self._exchange(outgoing, position, started, timeout, on_event)
        finally:
            try:
                self.selector.unregister(self.process.stdin)
            except KeyError:
                pass

    def _exchange(self, outgoing: bytes, position: int, started: float, timeout: float,
                  on_event: Callable[[dict[str, Any]], None] | None) -> dict[str, Any]:
        while True:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                try:
                    message = json.loads(line)
                except ValueError:
                    self.terminate()
                    return {"status": "error", "stage": "worker.protocol", "reason": "invalid worker protocol JSON"}
                if not isinstance(message, dict):
                    self.terminate()
                    return {"status": "error", "stage": "worker.protocol", "reason": "worker protocol JSON must be an object"}
                if message.get("event") == "result":
                    if position != len(outgoing):
                        self.terminate()
                        return {"status": "error", "stage": "worker.protocol", "reason": "result arrived before command was delivered"}
                    return message
                if message.get("event") == "stage":
                    self.stage = message.get("stage", self.stage)
                if on_event:
                    on_event(message)
            elapsed = time.monotonic() - started
            if elapsed >= timeout:
                self.terminate()
                return {"status": "timeout", "stage": self.stage, "reason": "worker command exceeded timeout",
                        "timeout_s": timeout, "diagnostic_wall_ns": int(elapsed * 1e9)}
            ready = self.selector.select(min(timeout - elapsed, 0.2))
            for key, _ in ready:
                if key.fileobj is self.process.stdin:
                    try:
                        position += os.write(self.process.stdin.fileno(), outgoing[position:position + 65536])
                    except BlockingIOError:
                        continue
                    except (OSError, ValueError):
                        return self._crashed()
                    if position == len(outgoing):
                        self.selector.unregister(self.process.stdin)
                else:
                    try:
                        block = os.read(self.process.stdout.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if block:
                        self.buffer += block
                        if len(self.buffer) > 32 * 1024**2:
                            self.terminate()
                            return {"status": "error", "stage": "worker.protocol", "reason": "worker response exceeds protocol limit"}
                    else:
                        return self._crashed()
            if not ready and self.process.poll() is not None:
                # Drain final protocol bytes even if the child exited just now.
                try:
                    block = os.read(self.process.stdout.fileno(), 65536)
                except BlockingIOError:
                    # A descendant retaining stdout cannot keep a dead leader healthy.
                    return self._crashed()
                if block:
                    self.buffer += block
                else:
                    return self._crashed()

    def _crashed(self) -> dict[str, Any]:
        self.healthy = False
        code = self.process.poll()
        if code is None:
            try:
                code = self.process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        return {"status": "crash", "stage": self.stage, "reason": "worker terminated before returning a terminal result",
                "returncode": code, "signal": -code if code is not None and code < 0 else None,
                "oom_evidence": None}

    def terminate(self) -> None:
        self.healthy = False
        # Descendants can outlive the group leader and keep pipe/CUDA owners.
        # Always clean the known group, including after leader exit.
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def close(self) -> None:
        if self.healthy and self.process.poll() is None:
            self.request({"op": "close"}, 3)
        self.terminate()
        self.selector.close()
        self.process.stdin.close()
        self.process.stdout.close()
        self.log.close()


def make_schedule(cases: list[dict[str, Any]], sessions: int, rounds: int, seed: int) -> list[dict[str, Any]]:
    """Randomize methods only within the same object/task/profile block."""
    rng = random.Random(seed)
    blocks: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        if case.get("status") == "ready":
            blocks[case["block_id"]].append(case["case_id"])
    result = []
    for session in range(sessions):
        for block_id, members in blocks.items():
            for round_id in range(rounds):
                order = list(members)
                rng.shuffle(order)
                result.extend({"session": session, "round": round_id, "sequence": index,
                               "block_id": block_id, "case_id": case_id}
                              for index, case_id in enumerate(order))
    return result


def _configuration_identity(config: dict[str, Any]) -> str:
    relevant = {key: value for key, value in config.items() if key not in {"output", "_pass_kind", "_config_path"}}
    return stable_hash(relevant)


def _environment() -> dict[str, Any]:
    import numpy as np
    flags = []
    cpu_model = None
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.startswith("model name") and cpu_model is None:
                cpu_model = line.partition(":")[2].strip()
            elif line.startswith("flags") and not flags:
                flags = line.partition(":")[2].split()
    return {"python": sys.version, "executable": sys.executable, "numpy": np.__version__,
            "platform": platform.platform(), "machine": platform.machine(), "cpu_model": cpu_model,
            "cpu_count": os.cpu_count(), "isa_flags": flags,
            "loader_environment": {key: os.environ.get(key) for key in ("LD_PRELOAD", "LD_LIBRARY_PATH")},
            "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "captured_at_utc": datetime.now(timezone.utc).isoformat()}


def run(config: dict[str, Any], output: str | Path | None = None, resume: bool = False,
        retry: bool = False) -> Path:
    run_started_wall = time.monotonic()
    from .data import load_dataset, object_id, project, raw_bytes
    from .report import generate
    from .schemes import capability
    from .registry import Registry
    from .worker import implementation_identity
    cfg = copy.deepcopy(config)
    cfg["execution"] = {**DEFAULT_EXECUTION, **cfg.get("execution", {})}
    requested_task=cfg.get('task',{})
    cfg["task"] = {**DEFAULT_TASK, **requested_task}
    if cfg['task']['boundary']=='object_memory' and 'lifecycle' not in requested_task:
        cfg['task']['lifecycle']='independent_object'
    execution, task = cfg["execution"], cfg["task"]
    retry = retry or execution.get("retry", False)
    cfg.setdefault("profiles", [{"id": "cpu-single", "device": "cpu", "native_threads": 1,
                                 "object_workers": 1, "memory_limit_mb": 4096}])
    for profile in cfg["profiles"]:
        profile.setdefault("memory_limit_mb", 4096)
    validate_boundary(task)
    if execution["sessions"] < 1 or execution["rounds"] < 1 or execution["warmup_objects"] < 0 or execution["timeout_s"] <= 0:
        raise ValueError("execution sessions/rounds/timeout must be positive; warmup_objects must be nonnegative")
    base_dir = Path(cfg.get("_base_dir", cfg.get("base_dir", "."))).resolve()
    asset_root = Path(cfg.get("_asset_root", cfg.get("asset_root", Path(__file__).resolve().parents[3]))).resolve()
    build_root = Path(cfg.get("_build_root", cfg.get("build_root", asset_root / "build" / "tsbench"))).resolve()
    registry = Registry(asset_root)
    if task['boundary'] in {'native_core','native_api'}:
        from .native import ensure_driver
        ensure_driver(asset_root,build_root)
    for method in cfg["methods"]:
        method["codec"] = registry.get(method["codec"]).key
        method["params"] = registry.resolve_params(method["codec"], method.get("params", {}))
        for route in method.get("components", {}).values():
            route["codec"] = registry.get(route["codec"]).key
            route["params"] = registry.resolve_params(route["codec"], route.get("params", {}))
    location = Path(output or cfg.get("output", "runs/" + cfg.get("name", "experiment")))
    root = (base_dir / location).resolve() if not location.is_absolute() else location.resolve()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path, observations_path = root / "manifest.json", root / "observations.jsonl"
    identity = _configuration_identity(cfg)
    prior_rows, tail = read_jsonl(observations_path)
    if manifest_path.exists():
        if not resume:
            raise FileExistsError(f"run already exists: {root}; use resume or another output")
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("configuration_id") != identity:
            raise ValueError("resume configuration differs from the recorded experiment")
        if manifest.get("execution_source_unchanged") is False:
            raise ValueError("execution source changed during this run; preserve it and start a new run")
        recorded_source = manifest.get("execution_provenance")
        if recorded_source and recorded_source["source_id"] != execution_provenance()["source_id"]:
            raise ValueError("resume execution source differs from the recorded experiment; start a new run")
        current_environment = _environment()
        comparable = lambda value: {key: item for key, item in value.items() if key != "captured_at_utc"}
        if comparable(current_environment) != comparable(manifest["environment"]):
            raise ValueError("resume environment differs from the recorded experiment; start a new run")
        originals = {}
        for case in manifest.get("cases", []):
            if case.get("raw_object_id") is None:
                continue
            dataset_key = case["dataset_id"]
            if dataset_key not in originals:
                originals[dataset_key] = project(load_dataset(case["dataset"], base_dir), task)
            current_object = originals[dataset_key]
            if object_id(current_object) != case["raw_object_id"]:
                raise ValueError(f"resume dataset content changed: {dataset_key}; start a new run")
            if case.get("status") == "ready":
                support = capability(case["method"], current_object, task, case["profile"], asset_root=asset_root, build_root=build_root)
                if not support.get("supported"):
                    raise ValueError(f"resume capability changed: {case['case_id']}; start a new run")
                current_implementation = implementation_identity(case["method"], support, asset_root, build_root, case["effective_profile"])
                if current_implementation != case.get("implementation_id"):
                    raise ValueError(f"resume implementation changed: {case['case_id']}; start a new run")
        if tail:
            preserved = preserve_tail(observations_path, tail)
            append(observations_path, {"schema": "tsbench.observation/1", "event": "recovered_tail", "run_id": manifest["run_id"], "phase": "recovery", "tail": tail, "preserved_path": str(preserved)})
    else:
        if prior_rows:
            raise ValueError("observations exist without manifest; use a new output directory")
        manifest = {"schema": "tsbench.run/1", "run_id": uuid.uuid4().hex, "name": cfg.get("name", "experiment"),
                    "configuration_id": identity, "resolved_config": cfg,
                    "pass_kind": cfg.get("_pass_kind", "measurement"), "created_at_utc": datetime.now(timezone.utc).isoformat(),
                    "environment": _environment(), "schedule_version": "method-round-shuffle/1",
                    "worker_policy": "sequential timing; worker per method/profile/session; close between object blocks",
                    "retry_policy": "primary original attempt retained; explicit retry adds attempts",
                    "cases": [], "schedule": [], "state": "preparing", "qualification": []}
        from .environment import capture
        manifest["execution_provenance"] = execution_provenance()
        manifest["source_snapshot"] = snapshot_sources(root / "source" / "tsbench")
        manifest["environment_snapshots"] = {"before_admission": capture(asset_root),
                                             "interpretation": "adjacent recorder snapshots outside all trial clocks; frequency/NUMA/power are observed, not enforced or monitored throughout trials"}
        write_json(manifest_path, manifest)
    run_id = manifest["run_id"]
    def record(phase: str, event: str, **fields: Any) -> None:
        append(observations_path, {"schema": "tsbench.observation/1", "run_id": run_id,
                                  "pass_kind": manifest["pass_kind"], "phase": phase, "event": event, **fields})
    timeout = float(execution["timeout_s"])
    max_pending_workers = int(execution.get("max_pending_workers", 32))
    if max_pending_workers < 1:
        raise ValueError("max_pending_workers must be positive")
    manifest["max_pending_workers"] = max_pending_workers
    cache_root = build_root / "qualification"
    for category in ("implementation", "exact"):
        (cache_root / category).mkdir(parents=True, exist_ok=True)
    base_worker_environment = os.environ.copy()
    package_path = str(Path(__file__).resolve().parent.parent)
    base_worker_environment["PYTHONPATH"] = package_path + (os.pathsep + base_worker_environment["PYTHONPATH"] if base_worker_environment.get("PYTHONPATH") else "")

    def start_worker(case: dict[str, Any], session: Any) -> tuple[WorkerProcess, dict[str, Any]]:
        label = stable_hash(case["case_id"]).split(":", 1)[1][:36]
        from .runtime import worker_environment
        environment = worker_environment(base_worker_environment, case["profile"])
        worker = WorkerProcess(root / "logs" / f"{label}-s{session}.log", environment=environment)
        result = worker.request({"op": "init", "method": case["method"], "profile": case["profile"],
                                 "task": task, "execution": execution, "asset_root": str(asset_root),
                                 "build_root": str(build_root), "base_dir": str(base_dir)}, timeout)
        if result.get("status") == "ok":
            result = worker.request({"op": "prepare", "dataset": case["dataset"]}, timeout)
        if result.get("status") == "ok" and result.get("raw_object_id") != case.get("raw_object_id"):
            result = {"status": "error", "stage": "input_identity", "reason": "dataset content changed after the case matrix was resolved"}
        return worker, result

    # A completed admission matrix and schedule are reused exactly on resume.
    if not manifest.get("schedule") and manifest.get("state") == "preparing":
        cases = []
        for dataset in cfg["datasets"]:
            try:
                original = project(load_dataset(dataset, base_dir), task)
                raw_id, size = object_id(original), raw_bytes(original)
                data_error = None
            except Exception as error:
                original, raw_id, size, data_error = None, None, None, str(error)
            for profile in cfg["profiles"]:
                for method in cfg["methods"]:
                    case_id = f"{dataset['id']}/{method['id']}/{profile['id']}"
                    block_id = stable_hash({"raw_object_id": raw_id, "task": task, "profile": profile})
                    case = {"case_id": case_id, "block_id": block_id, "dataset_id": dataset["id"], "method_id": method["id"],
                            "codec": method["codec"], "profile_id": profile["id"], "dataset": dataset, "method": method, "profile": profile,
                            "task": task["kind"], "raw_object_id": raw_id, "raw_bytes": size,
                            "boundary": task["boundary"], "lifecycle": task["lifecycle"], "cache_policy": task["cache_policy"]}
                    if original is not None:
                        case["lineage"] = dict(original.lineage)
                        case["object_schema"] = dict(original.schema)
                        case["components"] = {name: {"dtype": array.dtype.str, "shape": list(array.shape),
                                                     "order": "F" if array.flags.f_contiguous and not array.flags.c_contiguous else "C"}
                                              for name, array in original.components.items()}
                    if data_error:
                        case.update(status="unavailable", stage="data", reason=data_error)
                    else:
                        support = capability(method, original, task, profile, asset_root=asset_root, build_root=build_root)
                        case.update(status="ready" if support.get("supported") else support.get("status", "unsupported"), reason=support.get("reason"), capability=support)
                    if case["status"] == "ready":
                        worker, prepared = start_worker(case, "qualification")
                        try:
                            if prepared.get("status") != "ok":
                                case.update(status=prepared["status"], stage=prepared.get("stage", "prepare"), reason=prepared.get("reason"))
                            else:
                                case["implementation_id"] = prepared["implementation_id"]
                                case["effective_profile"] = prepared["effective_profile"]
                                case["build_evidence"] = prepared.get("build_evidence", [])
                                scope = {name: {"dtype": array.dtype.str, "rank": array.ndim, "trailing_shape": list(array.shape[1:])}
                                         for name, array in original.components.items()}
                                impl_key = stable_hash({"implementation_id": prepared["implementation_id"], "scope": scope, "task": task})
                                exact_key = stable_hash({"implementation_key": impl_key, "raw_object_id": raw_id, "task": task})
                                for category, key, operation in (("implementation", impl_key, "implementation"), ("exact", exact_key, "qualify")):
                                    cache_path = cache_root / category / (key.split(":", 1)[1] + ".json")
                                    cached = None
                                    if execution["qualification_cache"] and cache_path.is_file():
                                        try:
                                            cached = json.loads(cache_path.read_bytes())
                                        except (ValueError, OSError):
                                            pass
                                    hit = bool(cached and cached.get("status") == "ok" and cached.get("cache_key") == key)
                                    if hit:
                                        qualification = {"status": "ok", "cache_hit": True, "cache_key": key, "cache_path": str(cache_path)}
                                    else:
                                        qualification = worker.request({"op": operation, "artifact_dir": str(root / "artifacts"), "save_wire": category == "exact"}, timeout)
                                        qualification.update(cache_hit=False, cache_key=key)
                                        if qualification["status"] == "ok" and execution["qualification_cache"]:
                                            write_json(cache_path, qualification)
                                    record("qualification", "terminal", case_id=case_id, qualification_kind=category,
                                           **{name: value for name, value in qualification.items() if name != "event"})
                                    manifest["qualification"].append({"case_id": case_id, "kind": category, "cache_key": key, "status": qualification["status"], "cache_hit": hit})
                                    if qualification["status"] != "ok":
                                        case.update(status=qualification["status"], stage=qualification.get("stage", "qualification"), reason=qualification.get("reason"))
                                        break
                        finally:
                            worker.close()
                    if case["status"] != "ready":
                        record("admission", "terminal", case_id=case_id, status=case["status"], stage=case.get("stage", "capability"), reason=case.get("reason"))
                    cases.append(case)
                    manifest["cases"] = cases
                    write_json(manifest_path, manifest)
        manifest["schedule"] = make_schedule(cases, int(execution["sessions"]), int(execution["rounds"]), int(execution["seed"]))
        manifest["state"] = "running"
        write_json(manifest_path, manifest)
        for trial in manifest["schedule"]:
            record("measurement", "planned", **trial, attempt=0, status="planned")
    case_map = {case["case_id"]: case for case in manifest["cases"]}
    prior_terminal = [row for row in prior_rows if row.get("event") == "terminal" and row.get("phase") == "measurement"]
    latest_terminal = {}
    for row in prior_terminal:
        latest_terminal[(row["case_id"], row.get("session"), row.get("round"))] = row
    completed = {key for key, row in latest_terminal.items() if row.get("status") != "not_run" and
                 (not retry or row.get("status") == "ok")}
    attempts: dict[tuple[Any, ...], int] = defaultdict(int)
    for row in prior_rows:
        if row.get("event") == "terminal" and row.get("phase") == "measurement":
            key = (row["case_id"], row.get("session"), row.get("round"))
            attempts[key] = max(attempts[key], row.get("attempt", 0) + 1)
    terminal_attempts = {(row["case_id"], row.get("session"), row.get("round"), row.get("attempt", 0))
                         for row in prior_terminal}
    recovered_attempts = set()
    for row in prior_rows:
        if row.get("event") != "started" or row.get("phase") != "measurement":
            continue
        old_attempt = (row["case_id"], row.get("session"), row.get("round"), row.get("attempt", 0))
        if old_attempt in terminal_attempts or old_attempt in recovered_attempts:
            continue
        context = {key: value for key, value in row.items() if key not in {"schema", "event", "phase", "run_id", "pass_kind", "status", "stage", "reason"}}
        record("measurement", "terminal", **context, status="error", stage="recovery", reason="interrupted_attempt_without_terminal",
               outcome_evidence="parent had recorded started; completion and duration are unknown")
        attempts[old_attempt[:3]] = max(attempts[old_attempt[:3]], old_attempt[3] + 1)
        recovered_attempts.add(old_attempt)
    workers: dict[str, WorkerProcess] = {}
    worker_failure: dict[str, dict[str, Any]] = {}
    block_session = None
    worker_generations = defaultdict(int)
    started_wall = time.monotonic()
    completed_normally = False
    try:
        for trial in manifest["schedule"]:
            key = (trial["case_id"], trial["session"], trial["round"])
            if key in completed:
                continue
            current = (trial["session"], trial["block_id"])
            if current != block_session:
                for existing in workers.values():
                    existing.close()
                workers, worker_failure = {}, {}
                block_session = current
            case = case_map[trial["case_id"]]
            context = {**trial, "attempt": attempts[key], "raw_object_id": case["raw_object_id"], "profile_id": case["profile_id"],
                       "implementation_id": case.get("implementation_id"), "task": task["kind"], "boundary": task["boundary"],
                       "lifecycle": task["lifecycle"], "cache_policy": task["cache_policy"], "raw_bytes": case["raw_bytes"]}
            budget = execution.get("total_budget_s")
            if budget is not None and time.monotonic() - run_started_wall >= budget:
                record("measurement", "terminal", **context, status="not_run", stage="schedule", reason="budget_exhausted")
                continue
            worker = workers.get(case["case_id"])
            if worker is None or not worker.healthy:
                if worker is not None:
                    worker.close()
                    del workers[case["case_id"]]
                if len(workers) >= max_pending_workers:
                    evicted_id = next(iter(workers))
                    workers.pop(evicted_id).close()
                worker, preparation = start_worker(case, trial["session"])
                workers[case["case_id"]] = worker
                worker_generations[(case["case_id"], trial["session"])] += 1
                if preparation["status"] == "ok" and preparation.get("implementation_id") != case.get("implementation_id"):
                    preparation = {"status": "error", "stage": "identity", "reason": "implementation changed after admission; start a new run"}
                if preparation["status"] == "ok":
                    calibration = worker.request({"op": "calibrate"}, timeout)
                    record("calibration", "terminal", case_id=case["case_id"], session=trial["session"],
                           worker_pid=worker.process.pid, worker_generation=worker_generations[(case["case_id"], trial["session"])],
                           **{name: value for name, value in calibration.items() if name != "event"})
                    if calibration["status"] != "ok":
                        preparation = calibration
                    for warmup in range(int(execution["warmup_objects"]) if preparation["status"] == "ok" else 0):
                        result = worker.request({"op": "warmup"}, timeout)
                        record("warmup", "terminal", case_id=case["case_id"], session=trial["session"], warmup=warmup,
                               worker_pid=worker.process.pid, worker_generation=worker_generations[(case["case_id"], trial["session"])],
                               **{name: value for name, value in result.items() if name != "event"})
                        if result["status"] != "ok":
                            preparation = result
                            break
                if preparation["status"] != "ok":
                    worker_failure[case["case_id"]] = preparation
            if case["case_id"] in worker_failure:
                failed = worker_failure[case["case_id"]]
                record("measurement", "terminal", **context, status="not_run", stage=failed.get("stage", "worker.prepare"),
                       reason="worker_preparation_failed", preparation_status=failed["status"], preparation_reason=failed.get("reason"))
                continue
            context["worker_pid"] = worker.process.pid
            context["worker_generation"] = worker_generations[(case["case_id"], trial["session"])]
            record("measurement", "started", **context, status="started", stage="execute")
            def phase(event: dict[str, Any]) -> None:
                record("measurement", "stage", **context, stage=event.get("stage"))
            result = worker.request({"op": "trial", "artifact_dir": str(root / "artifacts"),
                                     "save_wire": execution.get("save_artifacts", True) and trial["round"] == 0}, timeout, phase)
            merged = {**context, **{name: value for name, value in result.items() if name != "event"}}
            if task['boundary']=='object_memory' and merged.get("status") == "ok" and min(merged.get("encode_ns", 0), merged.get("decode_ns", 0)) < 10000:
                merged["timing_warning"] = "short object duration; Python/FFI/timer overhead is included"
            record("measurement", "terminal", **merged)
        completed_normally = True
    finally:
        for worker in workers.values():
            worker.close()
        manifest["state"] = "complete" if completed_normally else "interrupted"
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["measurement_wall_ns"] = int((time.monotonic() - started_wall) * 1e9)
        manifest["run_wall_ns"] = int((time.monotonic() - run_started_wall) * 1e9)
        from .environment import capture
        # Volatile diagnostics never enter the strict resume environment identity.
        if "environment_snapshots" in manifest:
            manifest["environment_snapshots"]["after_measurement"] = capture(asset_root)
        if "execution_provenance" in manifest:
            final_source = execution_provenance()
            manifest["execution_source_unchanged"] = manifest.get("execution_source_unchanged") is not False and final_source["source_id"] == manifest["execution_provenance"]["source_id"]
            if not manifest["execution_source_unchanged"]:
                manifest["execution_provenance_after"] = final_source
                manifest["state"] = "interrupted"
        write_json(manifest_path, manifest)
    generate(root)
    return root
