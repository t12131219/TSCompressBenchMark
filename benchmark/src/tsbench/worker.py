"""Isolated CPU worker and wire-only decoder entry point.

The decoder CLI receives a wire path and implementation roots. It receives no
original object, configuration TOML, encoder session, shape template or model
path from the experiment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .records import canonical_json, file_hash, stable_hash, write_json

SUITE_VERSION = "cpu-admission/1"


def classify_error(error: BaseException) -> dict[str, Any]:
    name = type(error).__name__.lower()
    message = str(error)
    declared = getattr(error, "status", None)
    if isinstance(error, MemoryError):
        status = "oom"
    elif isinstance(error, subprocess.TimeoutExpired):
        status = "timeout"
    elif declared in {"unsupported", "unavailable", "error", "crash", "timeout", "oom"}:
        status = declared
    elif "unsupported" in name or message.startswith("unsupported:"):
        status = "unsupported"
    elif isinstance(error, (FileNotFoundError, ImportError)) or "unavailable" in name or message.startswith("unavailable:"):
        status = "unavailable"
    else:
        status = "error"
    result = {"status": status, "reason": message[:8192], "error_type": type(error).__name__}
    if getattr(error, "stage", None):
        result["stage"] = error.stage
    if getattr(error, "measurement_stage", None):
        result["stage"] = error.measurement_stage + "." + result.get("stage", "operation")
    for field in ("diagnostic_encode_ns", "diagnostic_decode_ns"):
        if getattr(error, field, None) is not None:
            result[field] = getattr(error, field)
    for field in ("returncode", "signal"):
        if getattr(error, field, None) is not None:
            result[field] = getattr(error, field)
    if getattr(error,'native_batch',None) is not None:
        result['diagnostic_native_batch']=error.native_batch
    return result


def _decode_wire(wire_path: Path, output: Path, asset_root: Path | None, build_root: Path | None) -> None:
    from .artifact import EncodedObject
    from .schemes import decode_once
    import numpy as np
    restored = decode_once(EncodedObject(wire_path.read_bytes()), asset_root=asset_root, build_root=build_root)
    output.mkdir(parents=True, exist_ok=True)
    components = {}
    for index, (name, array) in enumerate(sorted(restored.components.items())):
        filename = f"{index}.npy"
        np.save(output / filename, array, allow_pickle=False)
        components[name] = filename
    from .runtime import loaded_runtime
    write_json(output / "object.json", {"schema": restored.schema, "components": components, "runtime": loaded_runtime()})


def _wire_recovery(wire: bytes, original: Any, task: dict[str, Any], asset_root: Path,
                   build_root: Path, timeout: float) -> dict[str, Any]:
    """Check an exact input in a genuinely new decoder process."""
    from .data import TimeSeriesObject, object_id
    from .validate import verify
    import numpy as np
    with tempfile.TemporaryDirectory(prefix="tsbench-wire-") as temporary:
        root = Path(temporary)
        wire_path = root / "object.tsb"
        wire_path.write_bytes(wire)
        output = root / "restored"
        command = [sys.executable, "-m", "tsbench.worker", "decode", str(wire_path), str(output),
                   "--asset-root", str(asset_root), "--build-root", str(build_root)]
        completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   timeout=timeout, check=False, env=os.environ.copy())
        if completed.returncode:
            from .errors import BenchError
            error = BenchError("wire-only decoder failed: " + completed.stderr.decode("utf-8", errors="replace")[-8192:], stage="qualification.wire_only_decode")
            if completed.returncode < 0:
                error.status = "crash"
                error.returncode = completed.returncode
                error.signal = -completed.returncode
            raise error
        metadata = json.loads((output / "object.json").read_bytes())
        restored = TimeSeriesObject({name: np.load(output / filename, allow_pickle=False)
                                     for name, filename in metadata["components"].items()}, metadata["schema"])
        validation = verify(original, restored, task)
        if not validation.get("passed"):
            raise ValueError("wire-only recovery validation failed: " + str(validation))
        return {"passed": True, "decoder_process": True, "artifact_hash": "sha256:" + hashlib.sha256(wire).hexdigest(),
                "restored_object_id": object_id(restored), "verification": validation,
                "decoder_returncode": completed.returncode, "decoder_runtime": metadata.get("runtime")}


def implementation_identity(method: dict[str, Any], capability: dict[str, Any], asset_root: Path,
                            build_root: Path, effective: dict[str, Any]) -> str:
    """Hash relevant implementation files; report changes do not revoke admission."""
    import numpy as np
    from .runtime import preload_identity
    from .provenance import execution_files
    package = Path(__file__).resolve().parent
    files = execution_files(package)
    if capability.get('driver'):
        driver=capability['driver']
        files += [Path(driver['binary']),Path(driver['record_path'])]
        files += [Path(entry['path']) for entry in driver.get('compiled_dependencies',[])]
    libraries = capability.get("library_paths") or ([capability["library_path"]] if capability.get("library_path") else [])
    if libraries:
        files += [Path(path) for path in libraries]
        files += [Path(path).parent / "build.json" for path in libraries]
    elif method.get("codec") != "raw-store":
        files += sorted(build_root.rglob("*.so"))
        files += sorted(build_root.rglob("build.json"))
    dependencies = capability.get("runtime_dependencies", [])
    files += [Path(item["path"] if isinstance(item, dict) else item) for item in dependencies]
    cards = {method["codec"]} | {entry["codec"] for entry in method.get("components", {}).values()}
    files += [asset_root / "registry" / "codecs" / (key + ".json") for key in sorted(cards)]
    files += [Path(item["path"]) for item in capability.get("model_dependencies", [])]
    files += [Path(item["path"]) for item in effective.get("runtime", {}).get("libraries", [])]
    files += [Path(item['path']) for item in effective.get('native_runtime',{}).get('libraries',[])]
    identity = {"method": method, "implementation": capability.get("implementation_id"),
                'native_abi':capability.get('native_abi'),'driver_build_id':capability.get('driver',{}).get('build_id'),
                "requested_preload_files": preload_identity(effective.get('requested_runtime_preload', [])),
                "files": [{"path": str(path), "hash": file_hash(path)} for path in files if path.is_file()],
                "effective": effective, "python": sys.version, "numpy": np.__version__,
                "platform": platform.platform(), "machine": platform.machine(), "suite": SUITE_VERSION}
    return stable_hash(identity)


class Worker:
    def __init__(self, send: Any):
        self.send = send
        self.stage = "initialization"
        self.original = None
        self.scheme = None

    def phase(self, stage: str) -> None:
        self.stage = stage
        self.send({"event": "stage", "stage": stage})

    def dispatch(self, command: dict[str, Any]) -> dict[str, Any]:
        operation = command["op"]
        if operation == "init":
            from .executors.cpu import apply_profile
            self.method = command["method"]
            self.task = command["task"]
            self.profile = command["profile"]
            self.execution = command["execution"]
            self.asset_root = Path(command["asset_root"])
            self.build_root = Path(command["build_root"])
            self.base_dir = Path(command["base_dir"])
            self.effective = apply_profile(self.profile, self.execution)
            return {"status": "ok", "effective_profile": self.effective, "pid": os.getpid()}
        if operation == "prepare":
            self.phase("prepare")
            from .data import fingerprint, load_dataset, object_id, project, raw_bytes
            from .schemes import ObjectScheme, capability
            self.original = project(load_dataset(command["dataset"], self.base_dir), self.task)
            self.original_fingerprint = fingerprint(self.original)
            support = capability(self.method, self.original, self.task, self.profile,
                                 asset_root=self.asset_root, build_root=self.build_root)
            if not support.get("supported", False):
                return {"status": support.get("status", "unsupported"), "stage": "capability", "reason": support.get("reason"), "capability": support}
            if support.get("effective_native_threads") is not None:
                self.effective["effective_native_threads"] = support["effective_native_threads"]
                self.effective["thread_evidence"] = support.get("thread_evidence", "codec capability")
            if self.task['boundary'] in {'native_core','native_api'}:
                from .native import NativeMeasurement
                self.scheme=NativeMeasurement(self.method,self.task,self.execution,support,self.asset_root,self.build_root)
            else:
                self.scheme = ObjectScheme(self.method, asset_root=self.asset_root, build_root=self.build_root)
            self.scheme.prepare(self.original)
            from .runtime import loaded_runtime
            self.effective["requested_runtime_preload"] = self.profile.get("runtime_preload", [])
            self.effective["runtime"] = loaded_runtime(support.get("runtime_dependencies", []))
            if self.task['boundary'] in {'native_core','native_api'}:
                self.effective['native_runtime']=self.scheme.runtime
            self.identity = implementation_identity(self.method, support, self.asset_root, self.build_root, self.effective)
            build_evidence = []
            if support.get('driver'):
                build_evidence.append({'kind':'native_driver',**support['driver']})
            for library in support.get("library_paths", []):
                record_path = Path(library).parent / "build.json"
                if record_path.is_file():
                    record = json.loads(record_path.read_bytes())
                    build_evidence.append({"path": str(record_path), "hash": file_hash(record_path),
                                           "build_id": record.get("build_id"), "artifact_sha256": record.get("artifact_sha256"),
                                           "source_identity": record.get("identity_sha256"),
                                           "compilers": record.get("compilers"), "commands": record.get("commands", []),
                                           "profile": record.get("profile")})
            return {"status": "ok", "raw_object_id": object_id(self.original), "raw_bytes": raw_bytes(self.original),
                    "implementation_id": self.identity, "effective_profile": self.effective, "capability": support,
                    "build_evidence": build_evidence}
        if operation == "implementation":
            return self.check_implementation()
        if operation in {"trial", "qualify", "warmup", "calibrate"}:
            from .executors.cpu import measure_object
            if self.original is None or self.scheme is None:
                raise RuntimeError("worker must prepare an eligible case first")
            if self.task['boundary'] in {'native_core','native_api'}:
                from .data import fingerprint
                if fingerprint(self.original)!=self.original_fingerprint:
                    raise ValueError('trusted canonical input changed before native operation')
                row,_=self.scheme.measure(self.original,independent=operation=='qualify',
                                          artifact_dir=command.get('artifact_dir') if command.get('save_wire') or self.execution.get('save_artifacts',True) else None,
                                          on_stage=self.phase)
                if operation=='calibrate':
                    row['clock_diagnostics']={'policy':'fixed configured loops; no overhead subtraction',
                                              'clock':row['native_batch'].get('clock'),
                                              'loops':row['loops'],'inner_loops_are_independent_samples':False}
                row['implementation_id']=self.identity
                return row
            row, wire = measure_object(self.scheme, self.original, self.task, asset_root=self.asset_root,
                                       build_root=self.build_root, on_stage=self.phase,
                                       expected_fingerprint=self.original_fingerprint)
            if operation == "calibrate":
                import statistics
                pairs = []
                for _ in range(64):
                    first = time.perf_counter_ns()
                    second = time.perf_counter_ns()
                    pairs.append(second - first)
                clocks = time.get_clock_info("perf_counter")
                row["clock_diagnostics"] = {"clock": "perf_counter_ns", "resolution_s": clocks.resolution,
                                            "monotonic": clocks.monotonic, "empty_pair_count": len(pairs),
                                            "empty_pair_min_ns": min(pairs), "empty_pair_median_ns": statistics.median(pairs),
                                            "empty_pair_max_ns": max(pairs), "worker_pid": os.getpid(),
                                            "policy": "loops=1; diagnostic only; no overhead subtraction"}
            if operation == "qualify" and row["status"] == "ok":
                self.phase("qualification.wire_only_decode")
                row["independent_recovery"] = _wire_recovery(wire, self.original, self.task, self.asset_root,
                                                            self.build_root, float(self.execution["timeout_s"]))
            if command.get("artifact_dir") and (command.get("save_wire") or row["status"] != "ok"):
                directory = Path(command["artifact_dir"])
                directory.mkdir(parents=True, exist_ok=True)
                target = directory / (row["artifact_hash"].split(":", 1)[1] + ".tsb")
                if not target.exists():
                    target.write_bytes(wire)
                row["artifact_path"] = str(target)
            row["implementation_id"] = self.identity
            return row
        if operation == "close":
            return {"status": "ok", "closed": True}
        raise ValueError(f"unknown worker operation {operation!r}")

    def check_implementation(self) -> dict[str, Any]:
        """Capability-scoped small boundary suite, separate from exact input."""
        from .data import TimeSeriesObject
        from .executors.cpu import measure_object
        from .schemes import capability
        import numpy as np
        evidence = []
        accepted = 0
        for rows in (0, 1, 7, 17):
            components = {}
            for name, array in self.original.components.items():
                shape = (rows, *array.shape[1:])
                values = np.zeros(shape, dtype=array.dtype, order="F" if array.flags.f_contiguous and not array.flags.c_contiguous else "C")
                if rows:
                    # Fixed exactly representable values; never derive a reusable
                    # implementation check from the first real input's content.
                    for index in range(rows):
                        role = self.original.schema.get("roles", {}).get(name, name)
                        values[index] = index % 2 if array.dtype.kind == "b" or role == "mask" else index % 4
                components[name] = values
            fixture = TimeSeriesObject(components, self.original.schema)
            support = capability(self.method, fixture, self.task, self.profile,
                                 asset_root=self.asset_root, build_root=self.build_root)
            if not support.get("supported", False):
                evidence.append({"rows": rows, "status": support.get("status", "unsupported"), "reason": support.get("reason")})
                continue
            self.phase(f"qualification.suite.rows_{rows}")
            try:
                if self.task['boundary'] in {'native_core','native_api'}:
                    row,wire=self.scheme.measure(fixture,loops=1,warmup=0,independent=True,on_stage=self.phase)
                else:
                    row, wire = measure_object(self.scheme, fixture, self.task, asset_root=self.asset_root,
                                               build_root=self.build_root, on_stage=self.phase)
            except BaseException as error:
                rejection = classify_error(error)
                if rejection["status"] != "unsupported":
                    raise
                evidence.append({"rows": rows, **rejection})
                continue
            if row["status"] != "ok":
                return {"status": "error", "stage": "qualification.implementation", "reason": "implementation boundary fixture did not recover", "fixture": rows, "verification": row["verification"]}
            recovery = row['independent_recovery'] if self.task['boundary'] in {'native_core','native_api'} else _wire_recovery(wire, fixture, self.task, self.asset_root, self.build_root,
                                      float(self.execution["timeout_s"]))
            accepted += 1
            evidence.append({"rows": rows, "status": "ok", "artifact_hash": row["artifact_hash"], "independent_recovery": recovery})
        if not accepted:
            return {"status": "unsupported", "stage": "qualification.implementation", "reason": "no fixture in the declared capability was accepted", "suite": evidence}
        return {"status": "ok", "stage": "qualification.implementation", "suite_version": SUITE_VERSION,
                "scope": {name: {"dtype": array.dtype.str, "rank": array.ndim, "trailing_shape": list(array.shape[1:])}
                          for name, array in self.original.components.items()}, "suite": evidence,
                "implementation_id": self.identity}


def serve() -> int:
    # Preserve a dedicated protocol FD; native cout/printf go to the error log.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", buffering=1, encoding="utf-8")
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    def send(value: dict[str, Any]) -> None:
        protocol.write(canonical_json(value).decode("utf-8") + "\n")
        protocol.flush()
    worker = Worker(send)
    for line in sys.stdin:
        try:
            command = json.loads(line)
            result = worker.dispatch(command)
            result["event"] = "result"
            send(result)
            if command["op"] == "close":
                return 0
        except BaseException as error:
            result = {"event": "result", "stage": worker.stage, **classify_error(error)}
            wire = getattr(error, "artifact_wire", None)
            if isinstance(wire, bytes):
                result["artifact_hash"] = "sha256:" + hashlib.sha256(wire).hexdigest()
                result["stored_bytes"] = len(wire)
                if command.get("artifact_dir"):
                    directory = Path(command["artifact_dir"])
                    directory.mkdir(parents=True, exist_ok=True)
                    target = directory / (result["artifact_hash"].split(":", 1)[1] + ".tsb")
                    target.write_bytes(wire)
                    result["artifact_path"] = str(target)
            send(result)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("serve")
    decode = sub.add_parser("decode")
    decode.add_argument("wire", type=Path)
    decode.add_argument("output", type=Path)
    decode.add_argument("--asset-root", type=Path)
    decode.add_argument("--build-root", type=Path)
    arguments = parser.parse_args()
    if arguments.operation == "serve":
        return serve()
    _decode_wire(arguments.wire, arguments.output, arguments.asset_root, arguments.build_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
