"""Execute the registered codec/scope matrix through all five benchmark layers.

This is qualification of mode support on one supported configuration per entry,
not a formal performance run or qualification of every parameter combination.
Existing raw evidence is never overwritten. Run with PYTHONPATH=src on CPU 2.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tomllib
from copy import deepcopy
from pathlib import Path

import numpy as np

from tscompbench.adapters import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[1]
SCOPES = ("CORE", "PIPELINE", "E2E")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config_text(document):
    lines = []
    for key, value in document.items():
        if not isinstance(value, dict):
            lines.append(f"{key} = {json.dumps(value)}")
    for key, table in document.items():
        if isinstance(table, dict):
            lines.append(f"\n[{key}]")
            for field, value in table.items():
                if isinstance(value, dict):
                    raise ValueError("qualification template must have flat tables")
                lines.append(f"{field} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def select_template(key):
    options = []
    for path in sorted((ROOT / "configs/experiments").glob("*.toml")):
        if any(
            word in path.stem
            for word in ("unsupported", "rejection", "streaming", "switch", "query")
        ):
            continue
        doc = tomllib.loads(path.read_text())
        if key in doc.get("algorithms", []):
            options.append(
                (
                    doc.get("profile", {}).get("measurement_mode") != "QUALIFICATION",
                    path.name,
                    path,
                    doc,
                )
            )
    if not options:
        raise ValueError(f"no supported experiment template for {key}")
    _, _, path, doc = sorted(options)[0]
    return path, doc


def nd_registry(out):
    """Supply a real rank-3 input for the deliberately ND-only harness oracle."""
    file = out / "native-nd.npz"
    np.savez(file, values=np.arange(48, dtype="<f8").reshape(4, 3, 4))
    doc = json.loads((ROOT / "registry/datasets/sprintz_i16_mts.json").read_text())
    doc.update(key="timing_scope_native_nd", display_name="Synthetic rank-3 scope qualification")
    doc["source"].update(
        uri="generated:tools/verify_all_timing_scopes.py:nd_registry",
        notes="Deterministic arange(48) float64 rank-3 fixture for mode qualification only",
    )
    doc["file"].update(
        path=str(file.relative_to(ROOT)), bytes=file.stat().st_size, sha256=sha(file)
    )
    doc["logical"].update(topology="NATIVE_ND_ARRAY", axes=["time", "y", "x"])
    doc["logical"]["value"]["array"]["dtype"] = "<f8"
    doc["expected"].update(shape=[4, 3, 4], dtype="<f8")
    directory = out / "nd-registry"
    directory.mkdir()
    (directory / "timing_scope_native_nd.json").write_text(json.dumps(doc, indent=2) + "\n")
    return DatasetRegistry(directory, ROOT)


def validate_record(record, task, scope):
    assert task["status"] in {"PLANNED", "ADAPTER_LOSSY_ROUTED"}, task.get("reason_code")
    assert record["status"] in {"PASS", "RESOURCE_PRESSURE"}, record.get("reason_code")
    assert record["correctness"]["status"] == "PASS"
    assert record["eligibility"] is False  # no qualification record enters rankings
    assert record["algorithm_id"] == task["algorithm_id"]
    timing = record["timing"]
    assert timing["timing_scope"] == scope
    assert timing["min_duration_satisfied"]
    assert timing["inner_iterations"] >= 1
    boundary = "core" if scope == "CORE" else "pipeline"
    assert timing["selected_encode_wall_ns"] == timing[f"{boundary}_encode_wall_ns"] > 0
    assert timing["selected_decode_wall_ns"] == timing[f"{boundary}_decode_wall_ns"] > 0
    assert timing["selected_wall_ns"] == (
        timing["e2e_wall_ns"]
        if scope == "E2E"
        else timing[f"{boundary}_encode_wall_ns"] + timing[f"{boundary}_decode_wall_ns"]
    )
    assert timing["pipeline_encode_wall_ns"] >= timing["core_encode_wall_ns"]
    assert timing["pipeline_decode_wall_ns"] >= timing["core_decode_wall_ns"]
    assert (
        timing["e2e_wall_ns"]
        >= timing["pipeline_encode_wall_ns"] + timing["pipeline_decode_wall_ns"]
    )
    accounting = record["accounting"]
    assert accounting["final_bits"] == accounting["final_physical_bytes"] * 8
    return timing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--keys", nargs="+")
    args = parser.parse_args()
    assert os.sched_getaffinity(0) == {2}, "qualification must use auxiliary CPU 2"
    out = args.output.resolve()
    out.relative_to(ROOT)
    out.mkdir(parents=True, exist_ok=False)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    defaults = tomllib.loads(
        (ROOT / "configs/experiments/deflate-zlib-qualification.toml").read_text()
    )
    keys = args.keys or [*codecs, *[a["key"] for a in codecs.alias_documents()]]
    audit = {
        "scope": "ALL_REGISTERED_ENTRIES_THREE_SCOPE_FIVE_LAYER_QUALIFICATION",
        "performance_claim": False,
        "cases": [],
        "failures": [],
        "factory": [],
        "driver_sha256": sha(Path(__file__)),
    }
    (out / "driver.py").write_bytes(Path(__file__).read_bytes())
    if len(keys) > 1:
        # Loaded model/dependency libraries can consume a large virtual address
        # space. A fresh process per entry prevents a later fork's RLIMIT_AS from
        # inheriting those unrelated mappings and falsely rejecting small codecs.
        for key in keys:
            child_out = out / key
            with (out / f"{key}.log").open("w") as log:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--output",
                        str(child_out),
                        "--keys",
                        key,
                    ],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            if (child_out / "audit.json").is_file():
                child = json.loads((child_out / "audit.json").read_text())
                for field in ("cases", "factory", "failures"):
                    audit[field].extend(child[field])
            if result.returncode and not any(f["key"] == key for f in audit["failures"]):
                audit["failures"].append(
                    {"key": key, "phase": "entry-process", "exit_code": result.returncode}
                )
            print(key, "PASS" if result.returncode == 0 else "FAIL", flush=True)
            audit["status"] = "RUNNING"
            (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
        audit["status"] = "PASS" if not audit["failures"] else "FAIL"
        audit["entry_count"] = len(keys)
        audit["case_count"] = len(audit["cases"])
        (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
        return 0 if audit["status"] == "PASS" else 1
    nd = nd_registry(out)
    for key in keys:
        canonical = codecs.get(key)
        try:
            artifact, supporting = adapter_artifacts(ROOT, canonical)
            adapter = create_adapter(ROOT, canonical)
            params = {
                k: p["default"]
                for k, p in canonical.document["parameters"]["properties"].items()
                if "default" in p
            }
            adapter.create_session(params).close()
            audit["factory"].append(
                {
                    "key": key,
                    "status": "PASS",
                    "artifact_sha256": sha(artifact),
                    "supporting": [{"path": str(p), "sha256": sha(p)} for p in supporting],
                }
            )
        except Exception as error:
            audit["failures"].append({"key": key, "phase": "factory", "error": str(error)})
            print(key, "factory FAIL", str(error), flush=True)
            continue
        path, template = select_template(canonical.key)
        for scope in SCOPES:
            case = {
                "key": key,
                "canonical_key": canonical.key,
                "timing_scope": scope,
                "algorithm_id": canonical.algorithm_id,
                "source_artifact_id": canonical.source_artifact_id,
                "manifest_sha256": sha(ROOT / "registry/codecs" / f"{canonical.key}.json"),
                "template": str(path.relative_to(ROOT)),
                "template_sha256": sha(path),
            }
            try:
                config = deepcopy(template)
                config["algorithms"] = [key]
                config["datasets"] = [config["datasets"][0]]
                config["tracks"] = [config["tracks"][0]]
                config["profile"] = {
                    **defaults["profile"],
                    **config.get("profile", {}),
                    "measurement_mode": "QUALIFICATION",
                    "timing_scope": scope,
                    "cpu_affinity": [2],
                    "warmup_min_count": 1,
                    "warmup_min_seconds": "0",
                    "repetitions": 1,
                    "min_repetition_seconds": "0",
                    "query_workload": False,
                    "streaming_workload": False,
                }
                config["reporting"] = {**defaults["reporting"], "bootstrap_samples": 100}
                config["sweep"] = {k: [v[0]] for k, v in config.get("sweep", {}).items()}
                if canonical.key == "oracle-native-nd-only":
                    config["datasets"] = ["timing_scope_native_nd"]
                if canonical.key == "oracle-lossy-adapter":
                    config["sweep"]["error_bound"] = ["0.01"]
                file = out / f"{key}-{scope.lower()}.toml"
                file.write_text(config_text(config))
                run = initialize_run_set(file, out / "runs", run_set_id=f"{key}-{scope.lower()}")
                result = execute_run_set(
                    run, nd if canonical.key == "oracle-native-nd-only" else datasets, codecs
                )
                assert len(result) == 1 and result[0].preflight.eligible_for_formal_repetitions
                raw = run.path / "run_components.jsonl"
                records = [json.loads(line) for line in raw.read_text().splitlines()]
                tasks = [
                    json.loads(line)
                    for line in (run.path / "task_plan.jsonl").read_text().splitlines()
                ]
                assert len(records) == len(tasks) == 1
                timing = validate_record(records[0], tasks[0], scope)
                report = report_run_set(run)
                assert report.task_count == 1
                for layer in (2, 3, 4, 5):
                    assert next(run.path.glob(f"layer{layer}-*.json"), None)
                assert (report.report_directory / "report.json").is_file()
                case.update(
                    status="PASS",
                    resource_status=records[0]["status"],
                    timing=timing,
                    run_path=str(run.path.relative_to(ROOT)),
                    raw_sha256=sha(raw),
                    task_plan_sha256=sha(run.path / "task_plan.jsonl"),
                    report_sha256=sha(report.report_directory / "report.json"),
                )
            except Exception as error:
                case.update(status="FAIL", error=f"{type(error).__name__}: {error}")
                audit["failures"].append(case.copy())
            audit["cases"].append(case)
            audit["status"] = "RUNNING"
            (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
            print(key, scope, case["status"], case.get("error", ""), flush=True)
    audit["status"] = (
        "PASS" if not audit["failures"] and len(audit["cases"]) == len(keys) * 3 else "FAIL"
    )
    audit["entry_count"] = len(keys)
    audit["case_count"] = len(audit["cases"])
    (out / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(
        audit["status"],
        len(audit["cases"]),
        "cases",
        len(audit["failures"]),
        "failures",
        flush=True,
    )
    return 0 if audit["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
