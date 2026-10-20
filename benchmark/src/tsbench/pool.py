"""Separate process-pool workload boundary; the object runner stays unchanged.

No NumPy/native import occurs before the child resource profile is applied.
This module deliberately has its own config, records and CLI.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import selectors
import signal
import struct
import subprocess
import sys
import time
import tomllib
import uuid
from typing import Any

from .records import append, canonical_json, file_hash, read_jsonl, stable_hash, write_json

MAX_MESSAGE = 64 * 1024**2
MAX_COLLECTION = 512 * 1024**2
COLLECTION_PREFIX = struct.Struct("<8sQ32s")
COLLECTION_MAGIC = b"TSBPC01\0"


class PoolFailure(RuntimeError):
    def __init__(self, status: str, reason: str, **evidence: Any):
        super().__init__(reason)
        self.status, self.evidence = status, evidence


def process_resources(dependencies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Cumulative participant snapshots, never a per-trial native peak."""
    import resource
    from .runtime import loaded_runtime
    usage = resource.getrusage(resource.RUSAGE_SELF)
    status = Path("/proc/self/status")
    threads = None
    if status.is_file():
        threads = next((int(line.split()[1]) for line in status.read_text().splitlines() if line.startswith("Threads:")), None)
    return {"pid": os.getpid(), "ppid": os.getppid(), "threads": threads,
            "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
            "cpu_user_s": usage.ru_utime, "cpu_system_s": usage.ru_stime,
            "maxrss": usage.ru_maxrss, "maxrss_unit": "KiB on Linux; process lifetime high-water",
            "runtime": loaded_runtime(dependencies)}


def pack_collection(ids: list[str], wires: dict[str, bytes]) -> bytes:
    """A real charged directory, followed by each standalone wire exactly once."""
    if len(set(ids)) != len(ids) or set(ids) != set(wires):
        raise ValueError("collection IDs must be unique and match returned artifacts")
    entries, offset = [], 0
    for key in ids:
        wire = wires[key]
        entries.append({"id": key, "offset": offset, "length": len(wire),
                        "sha256": hashlib.sha256(wire).hexdigest()})
        offset += len(wire)
    header = canonical_json({"schema": "tsbench.collection/1", "objects": entries})
    if offset + len(header) + COLLECTION_PREFIX.size > MAX_COLLECTION:
        raise PoolFailure("unsupported", "collection exceeds the 512 MiB add-on safety ceiling")
    return COLLECTION_PREFIX.pack(COLLECTION_MAGIC, len(header), hashlib.sha256(header).digest()) + header + b"".join(wires[key] for key in ids)


def unpack_collection(bundle: bytes) -> tuple[list[str], dict[str, bytes]]:
    if len(bundle) < COLLECTION_PREFIX.size or len(bundle) > MAX_COLLECTION:
        raise ValueError("invalid collection length")
    magic, size, checksum = COLLECTION_PREFIX.unpack_from(bundle)
    end = COLLECTION_PREFIX.size + size
    if magic != COLLECTION_MAGIC or size > MAX_MESSAGE or end > len(bundle):
        raise ValueError("invalid collection prefix")
    header = bundle[COLLECTION_PREFIX.size:end]
    if hashlib.sha256(header).digest() != checksum:
        raise ValueError("collection directory checksum mismatch")
    descriptor = json.loads(header)
    if descriptor.get("schema") != "tsbench.collection/1" or not isinstance(descriptor.get("objects"), list):
        raise ValueError("invalid collection directory")
    ids, wires, offset = [], {}, 0
    for entry in descriptor["objects"]:
        key, length = entry["id"], entry["length"]
        if not isinstance(key, str) or key in wires or type(length) is not int or length < 0 or entry["offset"] != offset:
            raise ValueError("invalid collection member/interval")
        wire = bundle[end + offset:end + offset + length]
        if len(wire) != length or hashlib.sha256(wire).hexdigest() != entry["sha256"]:
            raise ValueError("collection member checksum/length mismatch")
        ids.append(key); wires[key] = wire; offset += length
    if end + offset != len(bundle) or not ids:
        raise ValueError("collection has trailing bytes or no members")
    return ids, wires


def _object_payload(obj: Any) -> dict[str, Any]:
    from .data import array_order
    return {"schema": dict(obj.schema), "components": {
        name: {"dtype": array.dtype.str, "shape": list(array.shape), "order": array_order(array),
               "data": base64.b64encode(array.tobytes(order=array_order(array))).decode("ascii")}
        for name, array in obj.components.items()}}


def _restore_payload(payload: dict[str, Any]) -> Any:
    import numpy as np
    from .data import DTYPES, MAX_OBJECT_BYTES, TimeSeriesObject
    components, total = {}, 0
    for name, item in payload["components"].items():
        dtype, shape, order = item["dtype"], item["shape"], item["order"]
        if dtype not in DTYPES or order not in {"C", "F"} or not 1 <= len(shape) <= 8 or any(type(x) is not int or x < 0 for x in shape):
            raise ValueError("invalid IPC array descriptor")
        expected = math.prod(shape) * np.dtype(dtype).itemsize
        total += expected
        if total > MAX_OBJECT_BYTES:
            raise ValueError("IPC object exceeds safety ceiling")
        data = base64.b64decode(item["data"], validate=True)
        if len(data) != expected:
            raise ValueError("IPC array length mismatch")
        components[name] = np.frombuffer(data, dtype=dtype).reshape(shape, order=order).copy(order=order)
    return TimeSeriesObject(components, payload["schema"])


class Channel:
    """Nonblocking writes as well as reads: large IPC cannot defeat a deadline."""
    def __init__(self, log: Path, profile: dict[str, Any], command: list[str] | None = None):
        from .runtime import worker_environment
        log.parent.mkdir(parents=True, exist_ok=True)
        self.log = log.open("ab")
        environment = worker_environment(os.environ, profile)
        package = str(Path(__file__).resolve().parent.parent)
        environment["PYTHONPATH"] = package + os.pathsep + environment.get("PYTHONPATH", "")
        self.process = subprocess.Popen(command or [sys.executable, "-m", "tsbench.pool", "--serve"],
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                        env=environment, start_new_session=True, bufsize=0)
        os.set_blocking(self.process.stdin.fileno(), False)
        os.set_blocking(self.process.stdout.fileno(), False)
        self.buffer = bytearray()
        self.closed = False

    def request(self, command: dict[str, Any], deadline: float) -> dict[str, Any]:
        message = canonical_json(command) + b"\n"
        if len(message) > MAX_MESSAGE:
            raise PoolFailure("unsupported", "IPC request exceeds the 64 MiB message ceiling")
        selector = selectors.DefaultSelector()
        selector.register(self.process.stdout, selectors.EVENT_READ, "read")
        selector.register(self.process.stdin, selectors.EVENT_WRITE, "write")
        sent = 0
        try:
            while True:
                if b"\n" in self.buffer:
                    line, _, rest = self.buffer.partition(b"\n")
                    self.buffer = bytearray(rest)
                    result = json.loads(line)
                    if not isinstance(result, dict) or result.get("event") != "result":
                        raise PoolFailure("error", "invalid pool worker protocol")
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PoolFailure("timeout", "collection deadline exceeded", worker_pid=self.process.pid)
                events = selector.select(min(remaining, 0.1))
                if not events and self.process.poll() is not None:
                    # select may time out just before the final result and exit.
                    # Drain it before classifying a dead leader, including close.
                    try:
                        final_block = os.read(self.process.stdout.fileno(), 65536)
                    except BlockingIOError:
                        final_block = b""
                    if final_block:
                        self.buffer.extend(final_block)
                        if len(self.buffer) > MAX_MESSAGE:
                            raise PoolFailure("unsupported", "IPC response exceeds the 64 MiB message ceiling")
                        continue
                    code = self.process.returncode
                    raise PoolFailure("crash", "worker leader exited while a descendant retained its pipe", returncode=code,
                                      signal=-code if code < 0 else None, worker_pid=self.process.pid)
                for key, _ in events:
                    if key.data == "write":
                        try:
                            count = os.write(self.process.stdin.fileno(), memoryview(message)[sent:sent + 65536])
                        except BrokenPipeError:
                            count = 0
                        if not count:
                            raise PoolFailure("crash", "worker pipe closed", returncode=self.process.poll(), worker_pid=self.process.pid)
                        sent += count
                        if sent == len(message):
                            selector.unregister(self.process.stdin)
                    else:
                        block = os.read(self.process.stdout.fileno(), 65536)
                        if not block:
                            code = self.process.poll()
                            raise PoolFailure("crash", "worker exited before result", returncode=code,
                                              signal=-code if code is not None and code < 0 else None, worker_pid=self.process.pid)
                        self.buffer.extend(block)
                        if len(self.buffer) > MAX_MESSAGE:
                            raise PoolFailure("unsupported", "IPC response exceeds the 64 MiB message ceiling")
        finally:
            selector.close()

    def terminate(self) -> None:
        # Kill the group even after its leader exited: native descendants can remain.
        try:
            os.killpg(self.process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass

    def close(self, deadline: float, graceful: bool = True) -> dict[str, Any]:
        result = {}
        try:
            if graceful and self.process.poll() is None:
                result = self.request({"op": "close"}, deadline)
                self.process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as error:
            raise PoolFailure("timeout", "pool process teardown exceeded deadline", worker_pid=self.process.pid) from error
        finally:
            self.terminate()
            if not self.closed:
                self.process.stdin.close(); self.process.stdout.close(); self.log.close()
                self.closed = True
        return result


class ProcessPool:
    """One fresh interpreter per worker; no inherited native/fork state."""
    def __init__(self, count: int, profile: dict[str, Any], log_root: Path):
        self.channels = []
        try:
            for index in range(count):
                self.channels.append(Channel(log_root / f"worker-{index}.log", profile))
        except BaseException:
            self.abort()
            raise

    def abort(self) -> None:
        for channel in self.channels:
            channel.terminate()

    def initialize(self, role: str, config: dict[str, Any], assignments: list[list[str]],
                   objects: dict[str, Any], references: dict[str, Any], deadline: float) -> list[dict[str, Any]]:
        def initialize_one(index: int) -> dict[str, Any]:
            request = {"op": "init", "role": role, "profile": config["profile"],
                       "timeout_s": config["timeout_s"], "asset_root": config["asset_root"], "build_root": config["build_root"]}
            if role == "encode":
                request.update(method=config["method"], task=config["task"], objects={
                    key: {"object": _object_payload(objects[key]), "object_id": references[key]["raw_object_id"],
                          "implementation_id": references[key]["implementation_id"]} for key in assignments[index]})
            result = self.channels[index].request(request, deadline)
            if result.get("status") != "ok":
                raise PoolFailure(result.get("status", "error"), result.get("reason", "pool initialization failed"), worker_result=result)
            return result
        with ThreadPoolExecutor(max_workers=len(self.channels)) as executor:
            return list(executor.map(initialize_one, range(len(self.channels))))

    def execute(self, assignments: list[list[str]], operation: str, deadline: float,
                wires: dict[str, bytes] | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        results, schedule = {}, []
        def worker_tasks(index: int) -> list[tuple[str, dict[str, Any]]]:
            local = []
            for sequence, key in enumerate(assignments[index]):
                command = {"op": operation, "id": key}
                if operation == "decode":
                    command["wire"] = base64.b64encode(wires[key]).decode("ascii")
                result = self.channels[index].request(command, deadline)
                if result.get("status") != "ok" or result.get("id") != key:
                    raise PoolFailure(result.get("status", "error"), result.get("reason", "worker returned a wrong member ID"),
                                      object_id=key, worker_result=result)
                local.append((key, result))
            return local
        with ThreadPoolExecutor(max_workers=len(self.channels)) as executor:
            futures = {executor.submit(worker_tasks, index): index for index in range(len(self.channels))}
            try:
                for future in as_completed(futures):
                    index = futures[future]
                    for sequence, (key, result) in enumerate(future.result()):
                        results[key] = (base64.b64decode(result["wire"], validate=True) if operation == "encode"
                                        else _restore_payload(result["object"]))
                        schedule.append({"object_id": key, "worker": index, "pid": result["pid"], "worker_sequence": sequence})
            except BaseException:
                self.abort()
                raise
        return results, schedule

    def inspect(self, deadline: float) -> list[dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=len(self.channels)) as executor:
            return list(executor.map(lambda channel: channel.request({"op": "inspect"}, deadline), self.channels))

    def close(self, deadline: float, graceful: bool = True) -> list[dict[str, Any]]:
        with ThreadPoolExecutor(max_workers=max(1, len(self.channels))) as executor:
            return list(executor.map(lambda channel: channel.close(deadline, graceful), self.channels))


def _serve() -> int:
    from .worker import classify_error
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1, encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    state: dict[str, Any] = {}
    def resources() -> dict[str, Any]:
        dependencies = list(state.get("runtime_dependencies", []))
        # Decoder evidence is derived from installed implementation records after
        # completion, not from an encoder-supplied method or source directory.
        if state.get("decoded_wire") is not None:
            from .artifact import EncodedObject
            from .registry import Registry
            from .build import artifact_path
            registry = Registry(state["asset_root"])
            descriptor = EncodedObject(state["decoded_wire"]).descriptor
            for key in {part["codec"] for component in descriptor["components"] for part in component["parts"]}:
                key = registry.get(key).key
                if key == "raw-store":
                    continue
                record_path = artifact_path(state["asset_root"], key, build_root=state["build_root"]).parent / "build.json"
                dependencies += json.loads(record_path.read_bytes()).get("runtime_dependencies", [])
        return {**process_resources(dependencies), "effective_profile": state.get("effective")}
    def dispatch(command: dict[str, Any]) -> dict[str, Any]:
        op = command["op"]
        if op == "init":
            from .executors.cpu import apply_profile
            state.update(role=command["role"], asset_root=Path(command["asset_root"]), build_root=Path(command["build_root"]))
            state["effective"] = apply_profile(command["profile"], {"memory_limit_mb": command["profile"].get("memory_limit_mb", 4096)})
            if command["role"] == "encode":
                from .data import fingerprint
                from .schemes import ObjectScheme, capability
                from .worker import implementation_identity
                from .runtime import loaded_runtime
                state.update(method=command["method"], task=command["task"], originals={}, fingerprints={}, identities={})
                for key, item in command["objects"].items():
                    obj = _restore_payload(item["object"])
                    if fingerprint(obj) != item["object_id"]:
                        raise ValueError("canonical input identity changed after admission")
                    support = capability(command["method"], obj, command["task"], command["profile"],
                                         asset_root=state["asset_root"], build_root=state["build_root"])
                    if not support.get("supported"):
                        raise PoolFailure(support.get("status", "unsupported"), support.get("reason", "capability changed"))
                    scheme = ObjectScheme(command["method"], asset_root=state["asset_root"], build_root=state["build_root"])
                    scheme.prepare(obj)
                    effective = state["effective"]
                    effective["effective_native_threads"] = support.get("effective_native_threads")
                    effective["thread_evidence"] = support.get("thread_evidence", "codec capability")
                    effective["requested_runtime_preload"] = command["profile"].get("runtime_preload", [])
                    effective["runtime"] = loaded_runtime(support.get("runtime_dependencies", []))
                    state.setdefault("runtime_dependencies", []).extend(support.get("runtime_dependencies", []))
                    identity = implementation_identity(command["method"], support, state["asset_root"], state["build_root"], effective)
                    if identity != item["implementation_id"]:
                        raise ValueError("implementation/runtime changed after reference admission")
                    state["originals"][key] = (obj, scheme)
                    state["fingerprints"][key] = item["object_id"]
                    state["identities"][key] = identity
            elif command["role"] != "decode":
                raise ValueError("unknown worker role")
            return {"status": "ok", **resources()}
        if op == "encode" and state.get("role") == "encode":
            obj, scheme = state["originals"][command["id"]]
            wire = scheme.encode_once(obj).wire
            return {"status": "ok", "id": command["id"], "pid": os.getpid(), "wire": base64.b64encode(wire).decode("ascii")}
        if op == "decode" and state.get("role") == "decode":
            from .artifact import EncodedObject
            from .schemes import decode_once
            wire = base64.b64decode(command["wire"], validate=True)
            restored = decode_once(EncodedObject(wire),
                                   asset_root=state["asset_root"], build_root=state["build_root"])
            state["decoded_wire"] = wire
            return {"status": "ok", "id": command["id"], "pid": os.getpid(), "object": _object_payload(restored)}
        if op == "inspect":
            from .data import fingerprint
            unchanged = {key: fingerprint(obj) == state["fingerprints"][key]
                         for key, (obj, _) in state.get("originals", {}).items()}
            return {"status": "ok" if all(unchanged.values()) else "error", "input_unchanged": unchanged, **resources()}
        if op == "close":
            return {"status": "ok", **resources()}
        raise ValueError("operation is not supported by this pool role")
    for line in sys.stdin.buffer:
        command = {}
        try:
            if len(line) > MAX_MESSAGE:
                raise PoolFailure("unsupported", "IPC message ceiling exceeded")
            command = json.loads(line)
            result = dispatch(command)
        except BaseException as error:
            result = classify_error(error)
            if isinstance(error, PoolFailure):
                result.update(error.evidence)
        result["event"] = "result"
        encoded = canonical_json(result) + b"\n"
        if len(encoded) > MAX_MESSAGE:
            encoded = canonical_json({"event": "result", "status": "unsupported", "reason": "IPC response ceiling exceeded"}) + b"\n"
        protocol.write(encoded.decode("utf-8")); protocol.flush()
        if command.get("op") == "close":
            return 0
    return 0


def load(path: str | Path) -> dict[str, Any]:
    from .config import resolve
    source = Path(path).resolve(strict=True)
    with source.open("rb") as handle:
        config = tomllib.load(handle)
    allowed = {"schema", "name", "output", "workers", "lifecycles", "sessions", "rounds", "warmup_collections", "timeout_s", "seed", "experiment"}
    if set(config) - allowed or config.get("schema") != "tsbench.pool/1":
        raise ValueError("invalid pool schema or unknown fields")
    config.setdefault("workers", [1, 2]); config.setdefault("lifecycles", ["cold_pool", "persistent_pool"])
    config.setdefault("sessions", 3); config.setdefault("rounds", 7); config.setdefault("warmup_collections", 1)
    config.setdefault("timeout_s", 120); config.setdefault("seed", 20261013)
    for key, minimum in (("sessions", 1), ("rounds", 1), ("warmup_collections", 0)):
        if type(config[key]) is not int or config[key] < minimum:
            raise ValueError(f"{key} must be integer >= {minimum}")
    if not isinstance(config["workers"], list) or not config["workers"] or any(type(x) is not int or not 1 <= x <= 32 for x in config["workers"]) or len(set(config["workers"])) != len(config["workers"]):
        raise ValueError("workers must be unique counts in 1..32")
    if not config["lifecycles"] or len(set(config["lifecycles"])) != len(config["lifecycles"]) or set(config["lifecycles"]) - {"cold_pool", "persistent_pool"}:
        raise ValueError("unknown or duplicate pool lifecycle")
    if type(config["timeout_s"]) is bool or not math.isfinite(float(config["timeout_s"])) or config["timeout_s"] <= 0:
        raise ValueError("timeout_s must be positive finite")
    if type(config["seed"]) is not int:
        raise ValueError("seed must be integer")
    nested=copy.deepcopy(config['experiment'])
    nested.setdefault('task',{}).setdefault('boundary','object_memory')
    nested['task'].setdefault('lifecycle','independent_object')
    experiment = resolve(nested, source.parent)
    if experiment['task']['boundary']!='object_memory':
        raise ValueError('the collection pool requires an explicit object_memory experiment')
    if len(experiment["profiles"]) != 1:
        raise ValueError("pool config requires exactly one per-worker resource profile")
    if max(config["workers"]) > len(experiment["datasets"]):
        raise ValueError("pool cannot have more workers than fixed collection members")
    config["experiment"] = experiment
    config["_config_path"] = str(source)
    output = Path(config.get("output", Path(experiment["_asset_root"]) / "runs" / config.get("name", "object-pool"))).expanduser()
    config["output"] = str(output if output.is_absolute() else (source.parent / output).resolve())
    return config


def run(config: dict[str, Any], output: str | Path | None = None) -> Path:
    """Reference admission is an ordinary object run, explicitly outside pool clocks."""
    from .runner import run as reference_run
    from .data import fingerprint, load_dataset, project, raw_bytes
    from .validate import verify
    from .worker import classify_error
    root = Path(output or config["output"]).resolve()
    if root.exists() and any(root.iterdir()):
        raise FileExistsError("pool output already exists; use a new run directory")
    root.mkdir(parents=True, exist_ok=True)
    experiment = copy.deepcopy(config["experiment"])
    experiment.setdefault('task',{}).setdefault('boundary','object_memory')
    experiment['task'].setdefault('lifecycle','independent_object')
    if experiment['task']['boundary']!='object_memory':
        raise ValueError('the collection pool requires object_memory')
    experiment["execution"].update(sessions=1, rounds=1, warmup_objects=0, save_artifacts=True)
    reference = reference_run(experiment, output=root / "admission")
    reference_manifest = json.loads((reference / "manifest.json").read_bytes())
    reference_rows, _ = read_jsonl(reference / "observations.jsonl")
    reference_trials = {row["case_id"]: row for row in reference_rows if row.get("phase") == "measurement" and row.get("event") == "terminal"}
    profile = experiment["profiles"][0]
    available_cpus = len(profile.get("affinity", os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else range(os.cpu_count() or 1)))
    objects = {item["id"]: project(load_dataset(item, experiment["_base_dir"]), experiment["task"]) for item in experiment["datasets"]}
    canonical_ids = list(objects)
    collection_raw_bytes = sum(raw_bytes(obj) for obj in objects.values())
    if collection_raw_bytes > MAX_COLLECTION:
        raise PoolFailure("unsupported", "raw collection exceeds the 512 MiB add-on safety ceiling")
    run_id = uuid.uuid4().hex
    (root / "source").mkdir()
    (root / "source/pool.py").write_bytes(Path(__file__).read_bytes())
    manifest = {"schema": "tsbench.pool-run/1", "run_id": run_id, "resolved_config": config,
                "pool_code_hash": file_hash(__file__), "reference_manifest_hash": file_hash(reference / "manifest.json"),
                "pool_source_archive": str(root / "source/pool.py"),
                "reference_run_id": reference_manifest["run_id"], "environment": reference_manifest["environment"],
                "input_objects": {key: {"object_id": fingerprint(obj), "raw_bytes": raw_bytes(obj)} for key, obj in objects.items()},
                "collection_raw_bytes": collection_raw_bytes, "requests": [], "schedule": [], "state": "running",
                "pool_policy": "fresh exec processes; one role/pool at a time; no fork native state",
                "parent_pid": os.getpid(),
                "parent_baseline": process_resources(),
                "resource_scope": "parent plus all listed worker PIDs; each operation has W worker processes",
                "timing": {"encode": "dispatch ready tasks through complete charged collection artifact",
                           "decode": "parse collection, dispatch wires through restored ordered object collection",
                           "cold_pool": "includes spawn/input distribution/preparation; shutdown separate",
                           "persistent_pool": "setup/warmup/close separate; includes per-collection IPC/schedule/reassembly",
                           "validation": "outside both collection clocks; every returned object and encoder input checked"}}
    write_json(root / "manifest.json", manifest)
    def record(event: str, **fields: Any) -> None:
        append(root / "observations.jsonl", {"schema": "tsbench.pool-observation/1", "run_id": run_id, "event": event, **fields})
    timeout = float(config["timeout_s"])
    for method_spec in experiment["methods"]:
        cases = {case["dataset_id"]: case for case in reference_manifest["cases"] if case["method_id"] == method_spec["id"]}
        method = next(iter(cases.values()))["method"]
        eligibility = [case for case in cases.values() if case.get("status") != "ready" or reference_trials.get(case["case_id"], {}).get("status") != "ok"]
        for count in config["workers"]:
            for lifecycle in config["lifecycles"]:
                context = {"method_id": method["id"], "workers": count, "native_threads_per_worker": profile["native_threads"], "lifecycle": lifecycle}
                context["workload_id"] = stable_hash({**context, "inputs": manifest["input_objects"], "method": method, "task": experiment["task"]})
                request = {**context, "status": "ready", "planned_collections": config["sessions"] * config["rounds"] * 2}
                if eligibility:
                    reasons = [{"dataset_id": case["dataset_id"], "status": case.get("status") if case.get("status") != "ready" else reference_trials[case["case_id"]]["status"],
                                "reason": case.get("reason") or reference_trials.get(case["case_id"], {}).get("reason")} for case in eligibility]
                    request.update(status=reasons[0]["status"], reason="fixed collection failed reference admission", members=reasons)
                elif count * profile["native_threads"] > available_cpus:
                    request.update(status="unsupported", reason="requested process × native thread budget exceeds allowed CPUs")
                manifest["requests"].append(request)
                write_json(root / "manifest.json", manifest)
                if request["status"] != "ready":
                    record("admission", **request)
                    continue
                cfg = {"profile": profile, "method": method, "task": experiment["task"], "asset_root": experiment["_asset_root"],
                       "build_root": experiment["_build_root"], "timeout_s": timeout}
                for session in range(config["sessions"]):
                    context = {**context, "session": session}
                    order = list(canonical_ids)
                    random.Random(config["seed"] + session).shuffle(order)
                    assignments = [order[index::count] for index in range(count)]
                    references = {key: cases[key] for key in canonical_ids}
                    for key, obj in objects.items():
                        if fingerprint(obj) != references[key]["raw_object_id"]:
                            raise ValueError("parent input changed after admission")
                    bundles: dict[int, Path] = {}
                    for operation in ("encode", "decode"):
                        for round_id in range(config["rounds"]):
                            trial = {**context, "operation": operation, "round": round_id, "attempt": 0}
                            manifest["schedule"].append({**trial, "assignments": assignments})
                            record("planned", **trial)
                    write_json(root / "manifest.json", manifest)
                    for operation in ("encode", "decode"):
                        pool = None
                        broken = None
                        setup_evidence = []
                        label = context["workload_id"].split(":")[1][:16] + "-" + operation
                        try:
                            if lifecycle == "persistent_pool":
                                setup_start = time.perf_counter_ns()
                                pool = ProcessPool(count, profile, root / "logs" / label)
                                setup_evidence = pool.initialize(operation, cfg, assignments, objects, references, time.monotonic() + timeout)
                                setup_ns = time.perf_counter_ns() - setup_start
                                record("setup", **context, operation=operation, setup_ns=setup_ns, workers_evidence=setup_evidence)
                                if config["warmup_collections"]:
                                    warm_wires = {key: Path(reference_trials[cases[key]["case_id"]]["artifact_path"]).read_bytes() for key in canonical_ids}
                                    for warmup in range(config["warmup_collections"]):
                                        results, _ = pool.execute(assignments, operation, time.monotonic() + timeout, warm_wires)
                                        if operation == "encode":
                                            # Validation uses fresh decoder interpreters with the same explicit runtime, not the parent's loader state.
                                            validator = ProcessPool(count, profile, root / "logs" / f"{label}-warmup-decode-{warmup}")
                                            try:
                                                validator.initialize("decode", cfg, assignments, {}, {}, time.monotonic() + timeout)
                                                results, _ = validator.execute(assignments, "decode", time.monotonic() + timeout, results)
                                            finally:
                                                validator.close(time.monotonic() + 3)
                                        checks = {key: verify(objects[key], result, cfg["task"]) for key, result in results.items()}
                                        unchanged = pool.inspect(time.monotonic() + timeout)
                                        if not all(check["passed"] for check in checks.values()) or any(item["status"] != "ok" for item in unchanged):
                                            raise PoolFailure("error", "pool warmup verification failed")
                                        record("warmup", **context, operation=operation, warmup=warmup, verification=checks, workers_evidence=unchanged)
                            for round_id in range(config["rounds"]):
                                trial = {**context, "operation": operation, "round": round_id, "attempt": 0}
                                if broken or operation == "decode" and round_id not in bundles:
                                    record("terminal", **trial, status="not_run", reason="pool_failed" if broken else "encode_collection_unavailable")
                                    continue
                                record("started", **trial)
                                bundle = bundles[round_id].read_bytes() if operation == "decode" else None
                                parent_before = process_resources()
                                started = time.perf_counter_ns()
                                deadline = time.monotonic() + timeout
                                try:
                                    if lifecycle == "cold_pool":
                                        pool = ProcessPool(count, profile, root / "logs" / f"{label}-{round_id}")
                                        setup_evidence = pool.initialize(operation, cfg, assignments, objects, references, deadline)
                                    if operation == "decode":
                                        ids, wires = unpack_collection(bundle)
                                        if ids != canonical_ids:
                                            raise ValueError("collection order differs from fixed workload")
                                    else:
                                        wires = None
                                    results, actual_schedule = pool.execute(assignments, operation, deadline, wires)
                                    if set(results) != set(canonical_ids):
                                        raise ValueError("returned collection members do not match fixed workload")
                                    if operation == "encode":
                                        bundle = pack_collection(canonical_ids, results)
                                    else:
                                        results = {key: results[key] for key in canonical_ids}
                                    # The complete collection is now available. Validation and shutdown are outside this continuous wall interval.
                                    completed = time.perf_counter_ns()
                                    if time.monotonic() > deadline:
                                        raise PoolFailure("timeout", "completed collection exceeded its overall deadline")
                                    parent_completed = process_resources()
                                    inspections = pool.inspect(time.monotonic() + timeout)
                                    inspect_ns = time.perf_counter_ns() - completed
                                    close_evidence = []
                                    close_ns = 0
                                    if lifecycle == "cold_pool":
                                        close_started = time.perf_counter_ns()
                                        close_evidence = pool.close(time.monotonic() + min(timeout, 3))
                                        close_ns = time.perf_counter_ns() - close_started
                                        pool = None
                                    wall_ns = completed - started
                                    if any(item["status"] != "ok" for item in inspections):
                                        raise PoolFailure("error", "encoder canonical input changed", workers_evidence=inspections)
                                    if operation == "encode":
                                        target = root / "artifacts" / (hashlib.sha256(bundle).hexdigest() + ".tsc")
                                        target.parent.mkdir(exist_ok=True)
                                        target.write_bytes(bundle)
                                        bundles[round_id] = target
                                        validator = ProcessPool(count, profile, root / "logs" / f"{label}-s{session}-r{round_id}-verify")
                                        try:
                                            validator.initialize("decode", cfg, assignments, {}, {}, time.monotonic() + timeout)
                                            restored, _ = validator.execute(assignments, "decode", time.monotonic() + timeout, results)
                                            checks = {key: verify(objects[key], restored[key], cfg["task"]) for key in canonical_ids}
                                            if not all(item["passed"] for item in checks.values()):
                                                raise PoolFailure("error", "encoded collection failed independent recovery verification", verification=checks, artifact_path=str(target))
                                        finally:
                                            validator.close(time.monotonic() + min(timeout, 3))
                                    else:
                                        checks = {key: verify(objects[key], results[key], cfg["task"]) for key in canonical_ids}
                                        if not all(item["passed"] for item in checks.values()):
                                            raise PoolFailure("error", "collection recovery/quality verification failed", verification=checks)
                                    payload_wire_bytes = sum(len(wire) for wire in unpack_collection(bundle)[1].values())
                                    record("terminal", **trial, status="ok", collection_wall_ns=wall_ns,
                                           input_inspection_ns=inspect_ns, close_ns=close_ns,
                                           raw_bytes=collection_raw_bytes, stored_bytes=len(bundle), object_wire_bytes=payload_wire_bytes,
                                           collection_index_bytes=len(bundle) - payload_wire_bytes,
                                           throughput_MiB_s=collection_raw_bytes * 1e9 / wall_ns / 1024**2 if wall_ns and collection_raw_bytes else None,
                                           artifact_hash="sha256:" + hashlib.sha256(bundle).hexdigest(),
                                           artifact_path=str(bundles[round_id]), verification=checks, actual_schedule=actual_schedule,
                                           parent_before=parent_before, parent_completed=parent_completed, parent_after_validation=process_resources(),
                                           parent_resource_scope="cumulative snapshots; parent_completed after collection clock, parent_after_validation also includes validation/save/close",
                                           workers_evidence=inspections, startup_evidence=setup_evidence, close_evidence=close_evidence)
                                except BaseException as error:
                                    broken = classify_error(error)
                                    if isinstance(error, PoolFailure):
                                        broken.update(error.evidence)
                                    if isinstance(bundle, bytes):
                                        target = root / "artifacts" / (hashlib.sha256(bundle).hexdigest() + ".tsc")
                                        target.parent.mkdir(exist_ok=True)
                                        target.write_bytes(bundle)
                                        broken.update(artifact_path=str(target), artifact_hash="sha256:" + hashlib.sha256(bundle).hexdigest(), stored_bytes=len(bundle))
                                    record("terminal", **trial, diagnostic_wall_ns=time.perf_counter_ns() - started,
                                           parent_before=parent_before, parent_after=process_resources(), **broken)
                                    if pool:
                                        pool.abort()
                        except BaseException as error:
                            broken = classify_error(error)
                            record("setup_failure", **context, operation=operation, **broken)
                            # Every requested operation retains a terminal even when setup fails.
                            for round_id in range(config["rounds"]):
                                record("terminal", **context, operation=operation, round=round_id, attempt=0, status="not_run", reason="pool_setup_failed", setup_failure=broken)
                        finally:
                            if pool:
                                close_start = time.perf_counter_ns()
                                try:
                                    evidence = pool.close(time.monotonic() + min(timeout, 3), graceful=broken is None)
                                    record("close", **context, operation=operation, close_ns=time.perf_counter_ns() - close_start, workers_evidence=evidence)
                                except BaseException as error:
                                    record("close_failure", **context, operation=operation, **classify_error(error))
    manifest["state"] = "complete"
    manifest["parent_final"] = process_resources()
    write_json(root / "manifest.json", manifest)
    rows, _ = read_jsonl(root / "observations.jsonl")
    groups = []
    import statistics
    for request in manifest["requests"]:
        for operation in ("encode", "decode"):
            terminals = [row for row in rows if row.get("event") == "terminal" and row.get("workload_id") == request["workload_id"] and row.get("operation") == operation]
            ok = [row for row in terminals if row["status"] == "ok"]
            times = [row["collection_wall_ns"] for row in ok]
            groups.append({**request, "operation": operation, "ok": len(ok), "planned": config["sessions"] * config["rounds"] if request["status"] == "ready" else 0,
                           "median_wall_ns": statistics.median(times) if times else None,
                           "min_wall_ns": min(times) if times else None,
                           "scope": "successful collections only" if len(ok) != len(terminals) else "all executed collections",
                           "statuses": {status: sum(row["status"] == status for row in terminals) for status in sorted({row["status"] for row in terminals})}})
    for group in groups:
        session_pairs = []
        def matching(row: dict[str, Any], workers: int, session: int) -> bool:
            return (row.get("event") == "terminal" and row.get("method_id") == group["method_id"] and
                    row.get("lifecycle") == group["lifecycle"] and row.get("operation") == group["operation"] and
                    row.get("workers") == workers and row.get("session") == session)
        for session in range(config["sessions"]):
            baseline = {row["round"]: row for row in rows if matching(row, 1, session)}
            target = {row["round"]: row for row in rows if matching(row, group["workers"], session)}
            paired = [index for index in range(config["rounds"]) if baseline.get(index, {}).get("status") == "ok" and target.get(index, {}).get("status") == "ok"]
            complete = len(paired) == config["rounds"]
            base_median = statistics.median(baseline[index]["collection_wall_ns"] for index in paired) if complete else None
            target_median = statistics.median(target[index]["collection_wall_ns"] for index in paired) if complete else None
            session_pairs.append({"session": session, "paired_ok_rounds": len(paired), "planned_rounds": config["rounds"],
                                  "complete": complete, "baseline_median_ns": base_median, "target_median_ns": target_median,
                                  "speedup": base_median / target_median if complete and target_median else None})
        ratios = [item["speedup"] for item in session_pairs if item["speedup"] is not None]
        group["paired_baseline"] = {"workers": 1, "policy": "same fixed collection, method, lifecycle, operation, session and round; complete sessions only",
                                    "complete_session_pairs": len(ratios), "planned_session_pairs": config["sessions"],
                                    "median_session_speedup": statistics.median(ratios) if ratios else None, "sessions": session_pairs,
                                    "inference": "descriptive fixed schedule; no confidence interval or linear scaling claim"}
    write_json(root / "report.json", {"schema": "tsbench.pool-report/1", "run_id": run_id, "groups": groups})
    lines = ["# Process object-pool workload", "", "Collection wall includes IPC, scheduling, reassembly and the charged collection index. Cold adds process setup; persistent setup and warmup are separate. Pool shutdown and input/quality verification are outside the continuous availability clocks, with separate recorded costs.", "", "Speedup pairs each complete session with the 1-worker baseline of the same method, lifecycle and operation. Failed/incomplete sessions retain their completion denominator and receive no speedup. This fixed schedule gives descriptive evidence, without a linear scaling or uncertainty claim.", "", "| Method | Workers | Lifecycle | Operation | OK/planned | Median wall ns | Paired speedup | Complete session pairs |", "|---|---:|---|---|---:|---:|---:|---:|"]
    lines.extend(f"| {item['method_id']} | {item['workers']} | {item['lifecycle']} | {item['operation']} | {item['ok']}/{item['planned']} | {item['median_wall_ns']} | {item['paired_baseline']['median_session_speedup']} | {item['paired_baseline']['complete_session_pairs']}/{item['paired_baseline']['planned_session_pairs']} |" for item in groups)
    (root / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", nargs="?", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        return _serve()
    if args.config is None:
        parser.error("config is required")
    print(run(load(args.config), args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
