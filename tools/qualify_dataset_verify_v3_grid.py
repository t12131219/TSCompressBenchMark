"""Stratified full-input qualification, isolated per entry, using the normal runner.

All ten dtypes and four topologies at 4 KiB, N=2, IEEE specials, plus a native
positive per entry. Larger-scale passes are selected for byte/integer baselines;
large learned-method experiments are kept in the separate frozen universe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
import traceback
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from queue import Empty, Queue

from verify_all_timing_scopes import config_text, select_template

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[1]


def selected_entries(index, canonical_key):
    keys = []
    for entry in index["entries"]:
        original = entry.get("original") or {}
        spec = original.get("generation_spec", {})
        if (
            spec.get("group") == "main"
            and spec.get("tier") == "4KiB"
            and spec.get("profile") == "slow"
        ) or entry["group"] in ("boundary_n2", "ieee_special"):
            keys.append(entry["key"])
        # Exercise four payload scales on a compressible input in native integer
        # and generic byte methods without inventing model training budgets.
        if (
            canonical_key
            in (
                "deflate-zlib",
                "zstd-frame",
                "lz4-frame",
                "streamvbyte-u32",
                "simple9-u28",
                "sprintz-fire",
            )
            and spec.get("group") == "main"
            and spec.get("tier") != "4KiB"
            and spec.get("profile") == "slow"
            and spec.get("dtype") in ("uint8", "uint32", "float64", "int16")
        ):
            keys.append(entry["key"])
    keys.append(index["codec_fixtures"][canonical_key])
    return sorted(set(keys))


def main(args):
    if args.jobs < 1:
        raise ValueError("--jobs must be positive")
    available = os.sched_getaffinity(0)
    cpus = args.cpus or [args.cpu]
    if len(set(cpus)) != len(cpus) or not set(cpus) <= available:
        raise ValueError("CPU slots must be distinct and available in the current affinity")
    if args.jobs > len(cpus):
        raise ValueError("--jobs must not exceed the number of CPU slots")
    cpus = cpus[: args.jobs]
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    out.relative_to(ROOT)
    registry_path = ROOT / "Dataset_Verify/v3/registry"
    index = json.loads((registry_path.parent / "index.json").read_text())
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    keys = args.keys or list(codecs)
    if len(set(keys)) != len(keys) or not keys:
        raise ValueError("algorithm keys must be nonempty and distinct")
    for key in keys:
        codecs.get(key)
    source = Path(__file__).read_bytes()
    (out / "driver.py").write_bytes(source)
    summary = {
        "scope": "STRATIFIED_FULL_INPUT_QUALIFICATION_NOT_ALL_UNIVERSE_EXECUTION",
        "performance_claim": False,
        "source_parity_claim": False,
        "scheduler": {
            "kind": "ISOLATED_ENTRY_PROCESSES",
            "jobs": len(cpus) if len(keys) > 1 else 1,
            "cpu_slots": cpus if len(keys) > 1 else [args.cpu],
            "algorithm_internal_threads_changed": False,
            "requested_keys": keys,
        },
        "driver_sha256": hashlib.sha256(source).hexdigest(),
        "entries": [],
        "failures": [],
    }

    def save():
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    if len(keys) > 1:
        pending = Queue()
        completed = Queue()
        for key in keys:
            pending.put(key)

        def launch(key, cpu):
            try:
                with (out / f"{key}.log").open("w") as log:
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "--output",
                            str(out / key),
                            "--keys",
                            key,
                            "--cpu",
                            str(cpu),
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                completed.put((key, cpu, result.returncode, None))
            except Exception as error:
                completed.put((key, cpu, -1, str(error)))

        def work(cpu):
            while True:
                try:
                    key = pending.get_nowait()
                except Empty:
                    return
                launch(key, cpu)

        def collect():
            key, cpu, returncode, error = completed.get()
            child = out / key / "summary.json"
            if child.exists():
                doc = json.loads(child.read_text())
                summary["entries"].extend(doc["entries"])
                summary["failures"].extend(doc["failures"])
            elif not error:
                error = "child process did not save a summary"
            if error:
                summary["failures"].append({"key": key, "error": error})
            if returncode and not any(f["key"] == key for f in summary["failures"]):
                summary["failures"].append({"key": key, "exit_code": returncode})
            save()
            print(key, "PASS" if returncode == 0 else "FAIL", f"CPU={cpu}", flush=True)

        save()
        with ThreadPoolExecutor(max_workers=len(cpus)) as pool:
            futures = [pool.submit(work, cpu) for cpu in cpus]
            for _ in keys:
                collect()
            for future in as_completed(futures):
                future.result()
    else:
        if args.cpu not in available:
            raise ValueError("--cpu must be available in the current affinity")
        os.sched_setaffinity(0, {args.cpu})
        key = keys[0]
        canonical = codecs.get(key).key
        try:
            _, template = select_template(canonical)
            config = deepcopy(template)
            defaults = tomllib.loads(
                (ROOT / "configs/experiments/deflate-zlib-qualification.toml").read_text()
            )
            config["algorithms"] = [key]
            config["datasets"] = selected_entries(index, canonical)
            config["tracks"] = [template["tracks"][0]]
            config["data_preparation"]["characterization_mode"] = "sampled"
            config["data_preparation"]["characterization_sample_rows"] = 64
            config["profile"] = {
                **defaults["profile"],
                **template.get("profile", {}),
                "measurement_mode": "QUALIFICATION",
                "timing_scope": "PIPELINE",
                "cpu_affinity": [args.cpu],
                "repetitions": 1,
                "warmup_min_count": 1,
                "warmup_min_seconds": "0",
                "min_repetition_seconds": "0",
                "query_workload": False,
                "streaming_workload": False,
                # Explicitly frozen AS budget, not an RSS claim. 1 GiB templates
                # can sit below imported numerical-library virtual mappings.
                "memory_limit_bytes": 8589934592,
            }
            config["reporting"] = {
                **defaults["reporting"],
                **template.get("reporting", {}),
                "bootstrap_samples": 100,
            }
            config["sweep"] = {k: [v[0]] for k, v in template.get("sweep", {}).items()}
            if canonical == "oracle-lossy-adapter":
                config["sweep"]["error_bound"] = ["0.01"]
            filename = out / "config.toml"
            filename.write_text(config_text(config))
            run = initialize_run_set(filename, out / "runs", run_set_id="grid")
            execute_run_set(run, DatasetRegistry(registry_path, ROOT), codecs)
            report = report_run_set(run)
            records = [
                json.loads(line)
                for line in (run.path / "run_components.jsonl").read_text().splitlines()
            ]
            counts = Counter(record["status"] for record in records)
            for record in records:
                status = record["status"]
                correctness = (record.get("correctness") or {}).get("status")
                if record["eligibility"] or not (
                    status in ("UNSUPPORTED", "ISA_UNSUPPORTED")
                    or correctness == "PASS"
                    and status in ("PASS", "RESOURCE_PRESSURE", "OVERSUBSCRIBED", "INCOMPARABLE")
                ):
                    summary["failures"].append(
                        {
                            "key": key,
                            "dataset_id": record["dataset_id"],
                            "status": status,
                            "reason": record["reason_code"],
                            "correctness": correctness,
                        }
                    )
            summary["entries"].append(
                {
                    "key": key,
                    "canonical_key": canonical,
                    "datasets": len(config["datasets"]),
                    "records": len(records),
                    "counts": dict(counts),
                    "report_task_count": report.task_count,
                    "summary_count": report.summary_count,
                    "run_path": str(run.path.relative_to(ROOT)),
                }
            )
            assert report.summary_count == 0
        except Exception as error:
            summary["failures"].append(
                {"key": key, "error": str(error), "traceback": traceback.format_exc()}
            )
    summary["status"] = "PASS" if not summary["failures"] else "FAIL"
    summary["record_count"] = sum(item["records"] for item in summary["entries"])
    save()
    print(
        summary["status"],
        summary["record_count"],
        len(summary["failures"]),
        "unexpected outcomes",
        flush=True,
    )
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keys", nargs="+")
    parser.add_argument("--cpu", type=int, default=2, help="CPU for a single entry or serial run")
    parser.add_argument("--jobs", type=int, default=1, help="Concurrent isolated entry processes")
    parser.add_argument(
        "--cpus", type=int, nargs="+", help="Distinct CPU slots for concurrent runs"
    )
    raise SystemExit(main(parser.parse_args()))
