"""Independent run-level resource profiling, separate from primary observations."""
from __future__ import annotations

import copy
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path


def _linux_process_tree(root_pid: int) -> list[dict]:
    """Read all descendants without requiring a non-core dependency."""
    pending = [root_pid]
    seen: set[int] = set()
    result = []
    ticks = os.sysconf("SC_CLK_TCK")
    page_size = os.sysconf("SC_PAGE_SIZE")
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        proc = Path(f"/proc/{pid}")
        try:
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            # Following the comm field: state is field 3; rss is field 24.
            result.append({"pid": pid, "start_ticks": int(fields[19]),
                           "rss_bytes": int(fields[21]) * page_size,
                           "cpu_ns": int((int(fields[11]) + int(fields[12])) * 1e9 / ticks),
                           "threads": int(fields[17])})
            for task in (proc / "task").iterdir():
                try:
                    pending.extend(int(v) for v in (task / "children").read_text().split())
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    pass
        except (FileNotFoundError, PermissionError, ProcessLookupError, IndexError, ValueError):
            continue  # A process can finish between directory and stat reads.
    return result


def snapshot(root_pid: int) -> dict:
    if not sys.platform.startswith("linux"):
        return {"available": False, "reason": "procfs_sampler_unavailable_on_platform",
                "processes": [], "rss_bytes": None, "threads": None}
    processes = _linux_process_tree(root_pid)
    if not processes:
        return {"available": False, "reason": "procfs_processes_unreadable",
                "processes": [], "rss_bytes": None, "threads": None}
    return {"available": True, "reason": None, "processes": processes,
            "rss_bytes": sum(p["rss_bytes"] for p in processes),
            "threads": sum(p["threads"] for p in processes)}


def run_profile(manifest_path: str | Path, interval_ms: float = 10) -> Path:
    """Replay a resolved experiment into a new pass with sampled RSS/CPU data.

    Samples cover the profiling runner and descendants, including qualification
    decoder processes. They do not estimate per-trial peak memory or energy.
    """
    from .runner import run

    if not 1 <= interval_ms <= 60_000:
        raise ValueError("interval_ms must be between 1 and 60000")
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if "resolved_config" not in manifest:
        raise ValueError("manifest has no replayable resolved_config")
    config = copy.deepcopy(manifest["resolved_config"])
    config["_pass_kind"] = "profile"
    pass_id = f"pass-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:8]}"
    destination = manifest_path.parent / "profile" / pass_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    started_ns = time.perf_counter_ns()
    baseline = snapshot(os.getpid())
    samples = []
    stop = threading.Event()

    def sample() -> None:
        while not stop.is_set():
            samples.append({"elapsed_ns": time.perf_counter_ns() - started_ns,
                            **snapshot(os.getpid())})
            stop.wait(interval_ms / 1000)

    sampler = threading.Thread(target=sample, name="tsbench-profile-sampler", daemon=True)
    sampler.start()
    error = None
    try:
        result = run(config, output=destination)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        stop.set()
        sampler.join()
        samples.append({"elapsed_ns": time.perf_counter_ns() - started_ns, **snapshot(os.getpid())})
        destination.mkdir(parents=True, exist_ok=True)
        maxima: dict[tuple[int, int], int] = {}
        baseline_cpu = {(p["pid"], p["start_ticks"]): p["cpu_ns"] for p in baseline["processes"]}
        for row in samples:
            for process in row["processes"]:
                key = (process["pid"], process["start_ticks"])
                maxima[key] = max(maxima.get(key, 0), process["cpu_ns"])
        rss_values = [row["rss_bytes"] for row in samples if row["rss_bytes"] is not None]
        actual_intervals = [samples[i]["elapsed_ns"] - samples[i - 1]["elapsed_ns"] for i in range(1, len(samples))]
        summary = {
            "schema": "tsbench.profile/1", "pass_kind": "profile", "pass_id": pass_id,
            "source_manifest": str(manifest_path), "source_run_id": manifest.get("run_id"),
            "scope": "profiling_runner_and_all_observed_descendant_processes",
            "sampling_interval_requested_ms": interval_ms, "sample_count": len(samples),
            "sampling_interval_max_observed_ns": max(actual_intervals) if actual_intervals else None,
            "baseline_rss_bytes": baseline["rss_bytes"],
            "total_rss_observed_peak_bytes": max(rss_values) if rss_values else None,
            "observed_cpu_consumed_ns": sum(max(0, value - baseline_cpu.get(key, 0)) for key, value in maxima.items()) if maxima else None,
            "peak_interpretation": "sampled lower bound; sum of RSS may count shared pages repeatedly",
            "cpu_interpretation": "process tick samples; short-lived unobserved processes may be omitted",
            "per_trial_peak": None, "per_trial_peak_reason": "run-level sampling scope",
            "gpu_memory": None, "gpu_memory_reason": "CPU profiling pass",
            "energy": None, "energy_reason": "energy collector not enabled",
            "unavailable_reason": baseline["reason"], "error": error,
            "wall_ns": time.perf_counter_ns() - started_ns,
        }
        (destination / "resources.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        with (destination / "resource_samples.jsonl").open("w", encoding="utf-8") as stream:
            for row in samples:
                stream.write(json.dumps(row, separators=(",", ":"), allow_nan=False) + "\n")
    return Path(result)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--interval-ms", type=float, default=10)
    args = parser.parse_args()
    print(run_profile(args.manifest, args.interval_ms))
