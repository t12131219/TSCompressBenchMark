"""Run environment imports/empty TF sessions and index actually consumed libraries.

No original model, oracle, compressor, trainer or performance worker is run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).resolve().parent
BUILD = ROOT / "build/legacy-oracle-recovery-20261011/oracle-recovery-r1"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def ref(path):
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def save(path, document):
    with path.open("x") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", choices=["ordinary-sandbox", "sandbox-external"], required=True)
    args = parser.parse_args()
    out = BUILD / ("environment-probes-" + args.context)
    out.mkdir(exist_ok=False)
    base = BUILD / "deepzip-tf18"
    specs = [("deepzip-tf18", "1.8.0", base / "lib", "0"),
             ("dzip-tf114-cpu", "1.14.0", base / "lib", ""),
             ("dzip-tf114-gpu", "1.14.0", BUILD / "cuda10-runtime/lib", "0")]
    rows, library_hashes = [], {}
    for key, tensorflow, runtime, visibility in specs:
        prefix = BUILD / key
        python = prefix / "bin/python"
        row = {"environment": key, "prefix": str(prefix), "expected_tensorflow": tensorflow,
               "expected_keras": "2.2.2", "expected_numpy": "1.16.4", "execution_context": args.context}
        if not python.exists():
            row.update(status="PREFIX_PYTHON_MISSING")
            rows.append(row)
            continue
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment.update(LD_LIBRARY_PATH=str(runtime) + ":" + str(base / "lib"),
                           CUDA_VISIBLE_DEVICES=visibility, TF_FP16_RNN_USE_FP32_COMPUTE="0",
                           PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1", OPENBLAS_NUM_THREADS="1",
                           OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", TF_CPP_MIN_LOG_LEVEL="0",
                           KERAS_HOME=str(out / (key + "-keras-config")), TMPDIR=str(BUILD / "tmp"))
        command = [str(python), str(AUDIT / "environment_probe.py")]
        result = subprocess.run(command, cwd=BUILD, env=environment, capture_output=True, text=True, timeout=120)
        stdout, stderr = out / (key + ".stdout.log"), out / (key + ".stderr.log")
        with stdout.open("x") as handle:
            handle.write(result.stdout)
        with stderr.open("x") as handle:
            handle.write(result.stderr)
        row.update(command=command, exit_code=result.returncode, stdout=ref(stdout), stderr=ref(stderr), python_binary=ref(python.resolve()))
        try:
            probe = json.loads(next(line for line in reversed(result.stdout.splitlines()) if line.startswith('{"base_prefix"')))
            save(out / (key + ".probe.json"), probe)
            versions = {name: module.get("version") for name, module in probe["modules"].items()}
            versions_ok = (versions.get("tensorflow") == tensorflow and versions.get("keras") == "2.2.2"
                           and versions.get("numpy") == "1.16.4" and versions.get("h5py") == "2.10.0"
                           and probe["python"].startswith("3.6.13"))
            devices = probe.get("device_probe") or {}
            cuda_required = key != "dzip-tf114-cpu" and args.context == "sandbox-external"
            gpu_seen = any(device["device_type"] == "GPU" for device in devices.get("devices", []))
            runtime_ok = devices.get("status") == "SESSION_INITIALIZED_DEVICES_ENUMERATED" and (gpu_seen if cuda_required else True)
            row.update(status="ENVIRONMENT_IMPORT_VERSION_DEVICE_PROBE_PASS" if versions_ok and runtime_ok else "ENVIRONMENT_PROBE_HAS_GAPS",
                       versions=versions, versions_match_lock=versions_ok, runtime_initialized=runtime_ok,
                       gpu_device_enumerated=gpu_seen, probe=ref(out / (key + ".probe.json")))
            libraries = []
            for value in probe["mapped_file_paths"]:
                path = Path(value)
                if not path.is_file():
                    continue
                if path not in library_hashes:
                    library_hashes[path] = ref(path)
                libraries.append(library_hashes[path])
            save(out / (key + ".mapped-file-hashes.json"), {"files": libraries, "source": "ACTUAL_PROCESS_MAPS_AFTER_IMPORT_AND_EMPTY_TF_SESSION"})
            targets = [python.resolve()]
            targets += [Path(value) for value in probe["mapped_file_paths"] if "_pywrap_tensorflow_internal.so" in value]
            links = []
            for target in targets:
                link = subprocess.run(["ldd", str(target)], env=environment, capture_output=True, text=True, timeout=30)
                links.append({"target": ref(target), "command": ["ldd", str(target)], "exit_code": link.returncode,
                              "stdout": link.stdout, "stderr": link.stderr})
            save(out / (key + ".ldd.json"), {"links": links, "same_environment_as_import_probe": True})
        except Exception as error:
            row.update(status="PROBE_OUTPUT_OR_INVENTORY_FAILED", error_type=type(error).__name__, error=str(error))
        rows.append(row)
        print(json.dumps({"environment": key, "status": row["status"], "versions": row.get("versions"),
                          "gpu_device_enumerated": row.get("gpu_device_enumerated")}), flush=True)
    complete = len(rows) == 3 and all(row["status"] == "ENVIRONMENT_IMPORT_VERSION_DEVICE_PROBE_PASS" for row in rows)
    document = {"schema_version": "tscb.restored-legacy-environment-probe-audit.v1", "execution_context": args.context,
                "driver": ref(Path(__file__)), "child_probe": ref(AUDIT / "environment_probe.py"),
                "status": "ALL_RESTORED_ENVIRONMENT_PROBES_PASS" if complete else "RESTORED_ENVIRONMENT_PROBES_HAVE_GAPS",
                "environments": rows, "source_oracle_codec_training_or_performance_executed": False,
                "full_G1_G3_G5_CAP_or_PARITY_granted": False,
                "claim_boundary": "Versions/imports and empty-session device enumeration only. This does not validate source model constructors, checkpoints, prediction, training or compression."}
    save(out / "report.json", document)
    if not complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
