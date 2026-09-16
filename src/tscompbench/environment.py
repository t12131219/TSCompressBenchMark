from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import os
import platform
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id

_ENVIRONMENT_WHITELIST = (
    "CONDA_DEFAULT_ENV",
    "CONDA_PREFIX",
    "OMP_NUM_THREADS",
    "OMP_PROC_BIND",
    "OMP_PLACES",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "TBB_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "CUDA_VISIBLE_DEVICES",
)


def _read_first(path: Path, default: str = "UNAVAILABLE") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def _cpu_info() -> dict[str, Any]:
    text = _read_first(Path("/proc/cpuinfo"), "")
    records = [record for record in text.split("\n\n") if record.strip()]
    first: dict[str, str] = {}
    if records:
        for line in records[0].splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                first[key.strip()] = value.strip()
    affinity = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else []
    topology: list[dict[str, Any]] = []
    for logical_cpu in affinity:
        topology_root = Path(f"/sys/devices/system/cpu/cpu{logical_cpu}/topology")
        topology.append(
            {
                "logical_cpu": logical_cpu,
                "package_id": _read_first(topology_root / "physical_package_id"),
                "core_id": _read_first(topology_root / "core_id"),
                "core_type": _read_first(topology_root / "core_type"),
                "thread_siblings": _read_first(topology_root / "thread_siblings_list"),
            }
        )
    return {
        "model": first.get("model name", platform.processor() or "UNAVAILABLE"),
        "vendor": first.get("vendor_id", "UNAVAILABLE"),
        "logical_cpu_count": os.cpu_count(),
        "affinity": affinity or None,
        "flags": sorted(first.get("flags", "").split()),
        "topology": topology,
    }


def _memory_info() -> dict[str, Any]:
    fields: dict[str, int] = {}
    for line in _read_first(Path("/proc/meminfo"), "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        pieces = value.strip().split()
        if pieces and pieces[0].isdigit():
            multiplier = 1024 if len(pieces) > 1 and pieces[1] == "kB" else 1
            fields[key] = int(pieces[0]) * multiplier
    return {
        "total_bytes": fields.get("MemTotal"),
        "available_bytes": fields.get("MemAvailable"),
        "swap_total_bytes": fields.get("SwapTotal"),
        "swap_free_bytes": fields.get("SwapFree"),
    }


def _tool_version(name: str) -> dict[str, Any]:
    executable = shutil.which(name)
    if executable is None:
        return {"status": "UNAVAILABLE"}
    try:
        completed = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        line = (completed.stdout or completed.stderr).splitlines()
        return {
            "status": "AVAILABLE",
            "path": executable,
            "version_line": line[0] if line else "UNSPECIFIED",
            "returncode": completed.returncode,
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"status": "PROBE_FAILED", "path": executable, "error": str(error)}


def _command_probe(arguments: list[str]) -> dict[str, Any]:
    executable = shutil.which(arguments[0])
    if executable is None:
        return {"status": "UNAVAILABLE"}
    try:
        completed = subprocess.run(
            [executable, *arguments[1:]],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = (completed.stdout or completed.stderr).strip()
        return {
            "status": "AVAILABLE" if completed.returncode == 0 else "PROBE_FAILED",
            "returncode": completed.returncode,
            "output": output,
        }
    except (OSError, subprocess.SubprocessError) as error:
        return {"status": "PROBE_FAILED", "error": str(error)}


def _python_hash() -> str | None:
    path = Path(sys.executable)
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "UNAVAILABLE"


def capture_environment() -> dict[str, Any]:
    soft_nofile, hard_nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
    manifest: dict[str, Any] = {
        "schema_version": "tscb.environment.v2",
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "glibc": list(platform.libc_ver()),
        },
        "cpu": _cpu_info(),
        "memory": _memory_info(),
        "numa": {
            "online_nodes": _read_first(Path("/sys/devices/system/node/online")),
        },
        "frequency": {
            "governor": _read_first(Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")),
            "turbo_control": _read_first(Path("/sys/devices/system/cpu/intel_pstate/no_turbo")),
        },
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "executable_sha256": _python_hash(),
            "conda_environment": os.environ.get("CONDA_DEFAULT_ENV", "UNSPECIFIED"),
            "conda_prefix": os.environ.get("CONDA_PREFIX", "UNSPECIFIED"),
            "packages": {
                name: _package_version(name)
                for name in ("numpy", "pytest", "pandas", "pyarrow", "psutil")
            },
        },
        "tools": {name: _tool_version(name) for name in ("cc", "c++", "cmake", "make", "git")},
        "accelerators": {"nvidia": _command_probe(["nvidia-smi", "-L"])},
        "measurement_capabilities": {
            "perf_event_paranoid": _read_first(Path("/proc/sys/kernel/perf_event_paranoid")),
            "cgroup_membership": _read_first(Path("/proc/self/cgroup")),
            "transparent_hugepage_enabled": _read_first(
                Path("/sys/kernel/mm/transparent_hugepage/enabled")
            ),
        },
        "container": {
            "docker_marker": Path("/.dockerenv").exists(),
            "container_environment": os.environ.get("container", "UNSPECIFIED"),
        },
        "clocks": {
            name: {
                "implementation": info.implementation,
                "monotonic": info.monotonic,
                "adjustable": info.adjustable,
                "resolution_seconds": format(info.resolution, ".17g"),
            }
            for name in ("perf_counter", "monotonic", "process_time")
            for info in (time.get_clock_info(name),)
        },
        "limits": {"open_files_soft": soft_nofile, "open_files_hard": hard_nofile},
        "thread_environment": {
            key: os.environ.get(key, "UNSPECIFIED") for key in _ENVIRONMENT_WHITELIST
        },
    }
    identity = copy.deepcopy(manifest)
    identity["memory"].pop("available_bytes", None)
    identity["memory"].pop("swap_free_bytes", None)
    identity["python"].pop("executable", None)
    for tool in identity["tools"].values():
        tool.pop("path", None)
    manifest["environment_id"] = stable_id("environment", identity)
    return manifest
