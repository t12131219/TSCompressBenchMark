"""Acquire exact locked archives and restore only new isolated oracle prefixes.

Acquisition and installation are separate stages. No source oracle, codec,
training or performance is executed. All failures and partial files are kept.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).resolve().parent
BUILD = ROOT / "build/legacy-oracle-recovery-20261011/oracle-recovery-r1"


def read(path):
    return json.loads(path.read_text())


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ref(path):
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def save(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def package_path(item):
    return BUILD / "downloads" / item["kind"] / item["filename"]


def exact(path, item):
    return path.is_file() and path.stat().st_size == item["bytes"] and sha(path) == item["sha256"]


def acquire(item):
    target = package_path(item)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"filename": item["filename"], "kind": item["kind"], "expected_bytes": item["bytes"],
              "expected_sha256": item["sha256"], "started_at": datetime.now(UTC).isoformat(), "attempts": []}
    if target.exists():
        record.update(status="EXACT_CACHE_REUSED" if exact(target, item) else "EXISTING_CACHE_MISMATCH", artifact=ref(target))
        return record
    candidates = [Path(p) for p in item["previous_local_matches"]]
    small = item.get("small_download_probe", {})
    if small.get("exact_lock_bytes_verified"):
        candidates.insert(0, Path(small["artifact"]["path"]))
    for source in candidates:
        if not source.is_absolute():
            source = ROOT / source
        if exact(source, item):
            shutil.copyfile(source, target)
            record.update(status="EXACT_LOCAL_ARCHIVE_COPIED", source=ref(source), artifact=ref(target))
            print(json.dumps({"stage": "acquisition", "filename": item["filename"], "status": record["status"]}), flush=True)
            return record
    for attempt in (1, 2):
        partial = target.with_name(target.name + ".partial-attempt-" + str(attempt))
        n = 0
        digest = hashlib.sha256()
        next_progress = time.monotonic() + 20
        try:
            request = urllib.request.Request(item["resolved_url"], headers={"User-Agent": "TSBench-Legacy-Lock-Recovery/1"})
            with urllib.request.urlopen(request, timeout=30) as response, partial.open("xb") as handle:
                while block := response.read(1024 * 1024):
                    n += len(block)
                    if n > item["bytes"]:
                        raise ValueError("archive exceeds original locked size")
                    handle.write(block)
                    digest.update(block)
                    if time.monotonic() >= next_progress:
                        print(json.dumps({"stage": "acquisition_progress", "filename": item["filename"], "bytes": n, "expected_bytes": item["bytes"]}), flush=True)
                        next_progress = time.monotonic() + 20
            actual = digest.hexdigest()
            if n != item["bytes"] or actual != item["sha256"]:
                raise ValueError("exact archive size or SHA mismatch")
            partial.rename(target)
            record["attempts"].append({"attempt": attempt, "status": "SHA_SIZE_VERIFIED", "bytes": n, "sha256": actual})
            record.update(status="EXACT_PUBLIC_ARCHIVE_ACQUIRED", artifact=ref(target))
            break
        except Exception as error:
            record["attempts"].append({"attempt": attempt, "status": "FAILED_RETAINED", "bytes": n,
                                       "partial_path": str(partial), "error_type": type(error).__name__, "error": str(error)})
            record.update(status="ACQUISITION_FAILED")
    record["ended_at"] = datetime.now(UTC).isoformat()
    print(json.dumps({"stage": "acquisition", "filename": item["filename"], "status": record["status"]}), flush=True)
    return record


def acquisition_stage(items):
    output = BUILD / "acquisition-attempt-1.json"
    if output.exists():
        raise FileExistsError("preserve completed acquisition report")
    started = datetime.now(UTC).isoformat()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(acquire, sorted(items, key=lambda item: item["bytes"])))
    valid = all(exact(package_path(item), item) for item in items)
    result = {"schema_version": "tscb.exact-legacy-acquisition.v1", "started_at": started,
              "ended_at": datetime.now(UTC).isoformat(), "status": "ALL_EXACT_ARCHIVES_VERIFIED" if valid else "EXACT_ACQUISITION_HAS_GAPS",
              "driver": ref(Path(__file__)), "network_report": ref(AUDIT / "network_recovery_report.json"),
              "archive_count": len(items), "total_unique_archive_bytes": sum(item["bytes"] for item in items),
              "records": rows, "environment_installed": False, "oracle_codec_or_training_executed": False}
    save(output, result)
    print(json.dumps({"status": result["status"], "archives": len(items), "total_bytes": result["total_unique_archive_bytes"]}), flush=True)
    if not valid:
        raise SystemExit(1)


def restore_stage(items):
    for item in items:
        if not exact(package_path(item), item):
            raise ValueError("incomplete exact cache: " + item["filename"])
    output = BUILD / "restoration-attempt-1.json"
    if output.exists():
        raise FileExistsError("preserve restoration report")
    recipe = BUILD / "recipe/deepzip"
    recipe.mkdir(parents=True, exist_ok=False)
    for source, name in [("Source__deepzip__restore_environment.py", "restore_environment.py"),
                         ("Source__deepzip__ORACLE_ENVIRONMENT_LOCK.json", "ORACLE_ENVIRONMENT_LOCK.json"),
                         ("derived_selected_oracle_requirements.txt", "oracle-requirements.txt")]:
        shutil.copyfile(AUDIT / source, recipe / name)
    environment = dict(os.environ)
    environment.update(CONDA_PKGS_DIRS=str(BUILD / "conda-extracted-cache"),
                       CONDA_ENVS_PATH=str(BUILD / "conda-envs"), PYTHONDONTWRITEBYTECODE="1",
                       PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", CUDA_VISIBLE_DEVICES="",
                       OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    base = BUILD / "deepzip-tf18"
    cpu = BUILD / "dzip-tf114-cpu"
    gpu = BUILD / "dzip-tf114-gpu"
    runtime = BUILD / "cuda10-runtime"
    rows = []

    def run(name, command):
        log = BUILD / "logs" / (name + ".log")
        log.parent.mkdir(exist_ok=True)
        started = datetime.now(UTC).isoformat()
        print(json.dumps({"stage": name, "status": "START"}), flush=True)
        with log.open("xb") as handle:
            process = subprocess.run(command, cwd=recipe, env=environment, stdout=handle, stderr=subprocess.STDOUT)
        row = {"stage": name, "command": command, "started_at": started,
               "ended_at": datetime.now(UTC).isoformat(), "exit_code": process.returncode, "log": ref(log)}
        rows.append(row)
        print(json.dumps({"stage": name, "exit_code": process.returncode, "log": str(log)}), flush=True)
        return process.returncode == 0

    base_ok = run("deepzip-original-restore", [sys.executable, str(recipe / "restore_environment.py"),
              "--conda", "/home/fzg/anaconda3/bin/conda", "--conda-cache", str(BUILD / "downloads/conda"),
              "--pip-cache", str(BUILD / "downloads/pip"), "--prefix", str(base)])
    cpu_ok = gpu_ok = False
    if base_ok:
        cpu_lock = read(AUDIT / "Source__dzip__ORACLE_ENVIRONMENT_LOCK.json")
        cpu_archives = [str(BUILD / "downloads/pip" / item["filename"]) for item in cpu_lock["overlay_archives"]]
        cpu_ok = run("dzip-cpu-venv", [str(base / "bin/python"), "-m", "venv", "--system-site-packages", str(cpu)])
        if cpu_ok:
            cpu_ok = run("dzip-cpu-locked-overlay", [str(cpu / "bin/python"), "-m", "pip", "install", "--no-index", "--no-deps", *cpu_archives])
        gpu_lock = read(AUDIT / "Source__dzip__GPU_ORACLE_ENVIRONMENT_LOCK.json")
        try:
            import conda_package_handling.api as conda
            runtime.mkdir(exist_ok=False)
            for item in gpu_lock["packages"]:
                if item["name"].endswith(".conda"):
                    path = BUILD / "downloads/conda" / item["name"]
                    conda.extract(str(path), dest_dir=str(runtime))
                    (runtime / (item["name"] + ".extracted")).write_text(item["sha256"] + "\n")
            rows.append({"stage": "dzip-cuda10-extract", "exit_code": 0, "runtime": str(runtime), "extractor": ref(Path(conda.__file__))})
            gpu_ok = run("dzip-gpu-venv", [str(base / "bin/python"), "-m", "venv", "--system-site-packages", str(gpu)])
            if gpu_ok:
                archives = [str(BUILD / "downloads/pip" / item["name"]) for item in gpu_lock["packages"] if not item["name"].endswith(".conda")]
                gpu_ok = run("dzip-gpu-locked-overlay", [str(gpu / "bin/python"), "-m", "pip", "install", "--no-index", "--ignore-installed", "--no-deps", *archives])
        except Exception as error:
            rows.append({"stage": "dzip-cuda10-extract", "exit_code": 1, "error_type": type(error).__name__, "error": str(error)})
    result = {"schema_version": "tscb.isolated-legacy-oracle-restoration.v1", "driver": ref(Path(__file__)),
              "status": "LOCKED_PREFIXES_INSTALLED_ENVIRONMENT_PROBES_PENDING" if base_ok and cpu_ok and gpu_ok else "RESTORATION_HAS_GAPS",
              "base_installed": base_ok, "cpu_overlay_installed": cpu_ok, "gpu_overlay_installed": gpu_ok,
              "prefixes": {"deepzip_tf18": str(base), "dzip_tf114_cpu": str(cpu), "dzip_tf114_gpu": str(gpu), "cuda10_runtime": str(runtime)},
              "recipes": [ref(path) for path in sorted(recipe.iterdir()) if path.is_file()], "steps": rows,
              "source_locks_rewritten": False, "existing_environments_modified": False,
              "oracle_codec_training_or_performance_executed": False, "complete_gate_granted": False}
    save(output, result)
    print(json.dumps({key: result[key] for key in ("status", "base_installed", "cpu_overlay_installed", "gpu_overlay_installed")}), flush=True)
    if not (base_ok and cpu_ok):
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["acquire", "restore"])
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    items = read(AUDIT / "network_recovery_report.json")["archives"]
    if args.stage == "acquire":
        acquisition_stage(items)
    else:
        restore_stage(items)


if __name__ == "__main__":
    main()
