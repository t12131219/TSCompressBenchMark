"""Read-only environment evidence, kept separate from frozen measurements.

An after-the-fact collection cannot establish a frequency, governor or NUMA
policy during an older run. Such run-time facts remain explicitly missing.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

from .records import file_hash, stable_hash, write_json


def field(value: Any = None, reason: str | None = None, source: str | None = None) -> dict[str, Any]:
    return {"value": value, "reason": reason if value is None else None, "source": source}


def read_field(path: Path, convert: Any = str) -> dict[str, Any]:
    try:
        value = path.read_text().strip()
        if not value:
            return field(reason="empty_file", source=str(path))
        return field(convert(value), source=str(path))
    except PermissionError:
        return field(reason="permission_denied", source=str(path))
    except FileNotFoundError:
        return field(reason="not_exposed", source=str(path))
    except (ValueError, OSError) as error:
        return field(reason=f"{type(error).__name__}: {error}", source=str(path))


def cpu_list(value: str) -> list[int]:
    result = set()
    for entry in value.split(","):
        if "-" in entry:
            start, stop = (int(item) for item in entry.split("-", 1))
            if start < 0 or stop < start or stop - start > 1_000_000:
                raise ValueError("invalid CPU/node range")
            result.update(range(start, stop + 1))
        else:
            number = int(entry)
            if number < 0:
                raise ValueError("negative CPU/node ID")
            result.add(number)
    return sorted(result)


def _proc_status(path: Path) -> dict[str, str]:
    try:
        return {key: value.strip() for line in path.read_text().splitlines() if ":" in line for key, value in [line.split(":", 1)]}
    except OSError:
        return {}


def hardware_snapshot(sys_root: Path = Path("/sys"), proc_root: Path = Path("/proc")) -> dict[str, Any]:
    cpu_root = sys_root / "devices/system/cpu"
    online = read_field(cpu_root / "online", cpu_list)
    topology = []
    for cpu in online["value"] or []:
        root = cpu_root / f"cpu{cpu}/topology"
        topology.append({"cpu": cpu,
                         "package": read_field(root / "physical_package_id", int),
                         "core": read_field(root / "core_id", int),
                         "siblings": read_field(root / "thread_siblings_list", cpu_list)})
    complete_topology = bool(topology) and all(row["package"]["value"] is not None and row["core"]["value"] is not None for row in topology)
    core_groups = Counter((row["package"]["value"], row["core"]["value"]) for row in topology) if complete_topology else Counter()
    status = _proc_status(proc_root / "self/status")
    cpuinfo = read_field(proc_root / "cpuinfo")
    models, flags, frequencies = [], [], []
    if cpuinfo["value"] is not None:
        for line in cpuinfo["value"].splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "model name":
                models.append(value.strip())
            elif key.strip() in {"flags", "Features"}:
                flags.append(set(value.split()))
            elif key.strip() == "cpu MHz":
                try:
                    frequencies.append(float(value))
                except ValueError:
                    pass
    policies = []
    for path in sorted((cpu_root / "cpufreq").glob("policy[0-9]*")):
        policies.append({"policy": path.name, **{name: read_field(path / name, cpu_list if name == "related_cpus" else str)
                                                 for name in ("related_cpus", "scaling_driver", "scaling_governor", "scaling_cur_freq", "scaling_min_freq", "scaling_max_freq", "cpuinfo_min_freq", "cpuinfo_max_freq", "energy_performance_preference")}})
    nodes = []
    for path in sorted((sys_root / "devices/system/node").glob("node[0-9]*")):
        nodes.append({"node": int(path.name[4:]), "cpus": read_field(path / "cpulist", cpu_list),
                      "distance": read_field(path / "distance", lambda value: [int(x) for x in value.split()])})
    power = []
    power_root = sys_root / "class/powercap"
    if power_root.exists():
        for name in sorted(power_root.glob("*")):
            if (name / "name").exists():
                power.append({"name": read_field(name / "name"), "enabled": read_field(name / "enabled"),
                              "constraint_0_power_limit_uw": read_field(name / "constraint_0_power_limit_uw", int)})
    gpu_devices = []
    for device in sorted((sys_root / "bus/pci/devices").glob("*")):
        klass = read_field(device / "class")
        if klass["value"] and klass["value"].startswith("0x03"):
            try:
                driver = str((device / "driver").resolve(strict=True))
            except OSError:
                driver = None
            gpu_devices.append({"pci_address": device.name, "class": klass, "vendor": read_field(device / "vendor"),
                                "device": read_field(device / "device"), "numa_node": read_field(device / "numa_node", int),
                                "driver": field(driver, "driver_link_unavailable", str(device / "driver"))})
    return {"scope": "current recorder's exposed procfs/sysfs; possibly container-filtered",
            "cpu": {"model_names": field(sorted(set(models)), source=str(proc_root / "cpuinfo")) if models else field(reason="cpuinfo_model_unavailable"),
                    "isa_common_flags": field(sorted(set.intersection(*flags)), source=str(proc_root / "cpuinfo")) if flags else field(reason="cpuinfo_flags_unavailable"),
                    "online_cpus": online, "topology": topology,
                    "physical_cores_online": field(len(core_groups), source="complete sysfs package/core pairs") if complete_topology else field(reason="incomplete_exposed_topology"),
                    "online_smt_threads_per_core": field(sorted(core_groups.values()), source="complete sysfs package/core pairs") if complete_topology else field(reason="incomplete_exposed_topology"),
                    "smt_active": read_field(cpu_root / "smt/active", int),
                    "recorder_allowed_cpus": field(cpu_list(status["Cpus_allowed_list"]), source=str(proc_root / "self/status")) if status.get("Cpus_allowed_list") else field(reason="proc_status_affinity_unavailable")},
            "numa": {"nodes": nodes, "nodes_available": field(len(nodes), source=str(sys_root / "devices/system/node")) if nodes else field(reason="numa_nodes_not_exposed"),
                     "recorder_allowed_nodes": field(cpu_list(status["Mems_allowed_list"]), source=str(proc_root / "self/status")) if status.get("Mems_allowed_list") else field(reason="proc_status_mems_unavailable"),
                     "memory_policy": field(reason="not_queried; allowed nodes are not placement or allocation policy"),
                     "policy_enforced": False},
            "frequency": {"proc_cpu_mhz_snapshot": field(frequencies, source=str(proc_root / "cpuinfo")) if frequencies else field(reason="cpu_mhz_not_exposed"),
                          "policies": policies, "policy_available": bool(policies),
                          "policy_unavailable_reason": None if policies else "cpufreq_policies_not_exposed",
                          "interpretation": "instantaneous snapshot and policies; not frequency during historical trials; no frequency control"},
            "power": {"powercap": power, "powercap_available": bool(power), "unavailable_reason": None if power else "powercap_domains_not_exposed",
                      "bios_or_system_power_profile": field(reason="not_exposed_by_standard_readonly_interface"), "changed_settings": False,
                      "energy": field(reason="no_energy_sampling_requested")},
            "gpu": {"pci_display_devices": gpu_devices, "driver_version": read_field(proc_root / "driver/nvidia/version"),
                    "runtime": field(reason="GPU runtime API not queried by this read-only recorder"),
                    "memory_bytes": field(reason="requires a real driver/runtime query; not inferred from PCI presence"),
                    "usable_executor": field(reason="not_probed; PCI/driver files do not establish completion capability")},
            "system_memory": read_field(proc_root / "meminfo"),
            "aslr": read_field(proc_root / "sys/kernel/randomize_va_space", int),
            "transparent_hugepage": read_field(sys_root / "kernel/mm/transparent_hugepage/enabled")}


def cgroup_snapshot(proc_root: Path = Path("/proc"), cgroup_root: Path = Path("/sys/fs/cgroup")) -> dict[str, Any]:
    membership = read_field(proc_root / "self/cgroup")
    unified = None
    if membership["value"]:
        unified = next((line.partition("::")[2] for line in membership["value"].splitlines() if line.startswith("0::")), None)
    if unified is None:
        return {"version": None, "reason": "unified_cgroup_v2_membership_not_exposed", "membership": membership,
                "bounds": {}, "enforcement": "recorder does not change cgroup policies"}
    # Container mount roots can expose the current cgroup at /sys/fs/cgroup even
    # when the host membership path is not resolvable inside that namespace.
    candidate = cgroup_root / unified.lstrip("/")
    root = candidate if (candidate / "cgroup.controllers").exists() else cgroup_root
    bounds = {name: read_field(root / name) for name in ("cpu.max", "cpuset.cpus.effective", "cpuset.mems.effective", "memory.max", "memory.high", "memory.swap.max", "pids.max", "cgroup.controllers")}
    return {"version": 2, "membership": membership, "exposed_root": str(root), "bounds": bounds,
            "reason": None, "hierarchical_effective_limits": field(reason="ancestor constraints may be hidden by the mount namespace; exposed leaf fields are not the whole effective budget"),
            "enforcement": "read-only exposed policies; cpu.max is quota/period, not a native thread count"}


def git_snapshot(root: Path) -> dict[str, Any]:
    environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    result = {}
    try:
        for label, command in (("revision", ["git", "rev-parse", "HEAD"]), ("status", ["git", "status", "--porcelain=v1", "-z", "--untracked-files=normal"])):
            completed = subprocess.run(command, cwd=root, env=environment, capture_output=True, timeout=5, check=False)
            if completed.returncode:
                result[label] = field(reason=f"git command failed ({completed.returncode}): " + completed.stderr.decode(errors="replace")[-2000:])
            elif label == "revision":
                result[label] = field(completed.stdout.decode().strip(), source="git rev-parse HEAD")
            else:
                entries = completed.stdout.split(b"\0")
                result[label] = {"dirty": bool(completed.stdout), "porcelain_sha256": "sha256:" + hashlib.sha256(completed.stdout).hexdigest(),
                                 "status_records": sum(bool(entry) for entry in entries), "interpretation": "NUL-separated porcelain records; rename records can include two paths"}
    except (OSError, subprocess.TimeoutExpired) as error:
        result["unavailable"] = f"{type(error).__name__}: {error}"
    return result


def installed_environment() -> dict[str, Any]:
    packages = sorted({(distribution.metadata.get("Name", "unknown"), distribution.version) for distribution in importlib.metadata.distributions()})
    executable = Path(sys.executable).resolve()
    relevant = ("LD_PRELOAD", "LD_LIBRARY_PATH", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "CC", "CXX", "CFLAGS", "CXXFLAGS", "LDFLAGS")
    try:
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        rlimit = field({"soft_bytes": soft if soft >= 0 else "unlimited", "hard_bytes": hard if hard >= 0 else "unlimited"}, source="getrlimit(RLIMIT_AS); recorder process only")
    except (ImportError, OSError) as error:
        rlimit = field(reason=str(error))
    return {"python": sys.version, "executable": str(executable), "executable_hash": file_hash(executable),
            "prefix": sys.prefix, "base_prefix": sys.base_prefix, "platform": platform.platform(), "uname": dict(platform.uname()._asdict()),
            "os_release": read_field(Path("/etc/os-release")), "packages": [{"name": name, "version": version} for name, version in packages],
            "packages_id": stable_hash(packages), "selected_environment": {name: os.environ.get(name) for name in relevant},
            "rlimit_as": rlimit, "lock_interpretation": "installed version inventory and executable hash; not a downloadable dependency lock or portability guarantee"}


def manifest_supplement(manifest_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_bytes())
    admission = None
    case_source = manifest
    if manifest.get("schema") == "tsbench.pool-run/1":
        reference = manifest_path.parent / "admission/manifest.json"
        if reference.is_file():
            actual_hash = file_hash(reference)
            admission = {"path": str(reference), "sha256": actual_hash,
                         "matches_pool_record": actual_hash == manifest.get("reference_manifest_hash")}
            case_source = json.loads(reference.read_bytes())
    records = {}
    for case in case_source.get("cases", []):
        for item in case.get("build_evidence", []):
            records[item["path"]] = item.get("hash")
    checked = []
    for name, recorded_hash in sorted(records.items()):
        path = Path(name)
        item = {"path": name, "recorded_hash": recorded_hash}
        try:
            actual = file_hash(path)
            item.update(current_hash=actual, matches_recorded=actual == recorded_hash)
            build = json.loads(path.read_bytes())
            item.update(compilers=build.get("compilers"), profile=build.get("profile"),
                        commands=build.get("commands"), source_identity=build.get("identity_sha256"),
                        artifact_sha256=build.get("artifact_sha256"), runtime_dependencies=build.get("runtime_dependencies"),
                        toolchain_files=build.get("toolchain_files"), dependency_capture=build.get("dependency_capture"))
        except (OSError, ValueError) as error:
            item.update(current_hash=None, matches_recorded=None, reason=f"{type(error).__name__}: {error}")
        checked.append(item)
    historical_missing = {name: field(reason="not_recorded_at_run; a later host snapshot cannot fill this fact")
                          for name in ("physical_topology", "numa_policy", "frequency", "power_policy", "cgroup_bounds", "git_dirty_revision", "installed_package_lock")}
    return {"path": str(manifest_path), "sha256": file_hash(manifest_path), "run_id": manifest.get("run_id"),
            "recorded_environment": manifest.get("environment"), "recorded_profiles": [{"case_id": case.get("case_id"), "profile": case.get("profile"), "effective_profile": case.get("effective_profile")} for case in case_source.get("cases", [])],
            "referenced_pool_admission": admission,
            "pool_recorded_parent_resources": {key: manifest.get(key) for key in ("parent_pid", "parent_baseline", "parent_final")} if admission else None,
            "observations": {"path": str(manifest_path.parent / "observations.jsonl"),
                             "sha256": file_hash(manifest_path.parent / "observations.jsonl") if (manifest_path.parent / "observations.jsonl").is_file() else None,
                             "scope": "existing actual worker resource/runtime evidence remains in these immutable raw records"},
            "build_records": checked, "historical_missing": historical_missing,
            "scope": "historical manifest facts and verified referenced records; current capture is separate"}


def capture(root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()
    result = {"schema": "tsbench.environment-supplement/1", "captured_started_utc": started,
              "collector_hash": file_hash(__file__), "collection_mode": "retrospective" if manifest_path else "current",
              "settings_changed": False, "hardware": hardware_snapshot(), "cgroup": cgroup_snapshot(),
              "installed_environment": installed_environment(), "git": git_snapshot(root),
              "historical": manifest_supplement(manifest_path) if manifest_path else None,
              "limitations": ["sequential snapshots can change between reads", "exposed container topology is not necessarily complete physical host topology",
                              "later frequency/power/NUMA snapshots are not evidence during an older measurement", "no native codec, GPU runtime, energy or performance workload is executed"]}
    result["captured_finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["supplement_id"] = stable_hash(result)
    return result


def launch(config_path: Path, run_output: Path, supplement_output: Path) -> Path:
    """Collect before/after a new run without changing frozen runner code.

    This records adjacent snapshots, not control of frequency, NUMA or power
    throughout every trial. Runtime settings still come from actual workers.
    """
    from .config import load
    from .runner import run
    if supplement_output.exists():
        raise FileExistsError("environment supplement already exists; choose a new output")
    if (run_output / "manifest.json").exists():
        raise FileExistsError("launch wrapper requires a new measurement run")
    config = load(config_path)
    root = Path(config["_asset_root"])
    record = {"schema": "tsbench.environment-launch/1", "config_path": str(config_path.resolve()),
              "config_sha256": file_hash(config_path), "collector_hash": file_hash(__file__),
              "run_output": str(run_output.resolve()), "before": capture(root), "state": "started",
              "interpretation": "adjacent recorder snapshots; not within-trial resource samples or hardware policy enforcement"}
    write_json(supplement_output, record)
    try:
        result = run(config, output=run_output)
        record["state"] = "complete"
        return result
    except BaseException as error:
        record.update(state="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        record["after"] = capture(root, run_output / "manifest.json" if (run_output / "manifest.json").exists() else None)
        write_json(supplement_output, record)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--manifest", type=Path)
    source.add_argument("--config", type=Path)
    parser.add_argument("--run-output", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.config:
        if args.run_output is None:
            parser.error("--config requires --run-output for a new run")
        print(launch(args.config, args.run_output, args.output))
        return 0
    if args.run_output:
        parser.error("--run-output requires --config")
    if args.output.exists():
        raise FileExistsError("environment supplement already exists; choose a new output")
    write_json(args.output, capture(args.root.resolve(), args.manifest.resolve() if args.manifest else None))
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
