"""Dataset_Verify canonical sources through the five-layer qualification runner.

Fresh process per codec, no source-gate bypass, immutable per-attempt evidence.
A successful qualification is not a formal performance or source parity claim.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from copy import deepcopy
from pathlib import Path

from verify_all_timing_scopes import config_text, select_template, validate_record

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[1]


def run(args):
    out = args.output.resolve()
    out.relative_to(ROOT)
    out.mkdir(parents=True, exist_ok=False)
    registry_root = args.registry.resolve()
    fixtures = json.loads((registry_root.parent / "index.json").read_text())["codec_fixtures"]
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    defaults = tomllib.loads(
        (ROOT / "configs/experiments/deflate-zlib-qualification.toml").read_text()
    )
    keys = args.keys or [*codecs, *[alias["key"] for alias in codecs.alias_documents()]]
    audit = {
        "schema_version": "tscb.dataset-verify-qualification.v1",
        "measurement_mode": "QUALIFICATION",
        "performance_claim": False,
        "source_parity_claim": False,
        "cases": [],
        "failures": [],
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "registry": str(registry_root.relative_to(ROOT)),
        "scopes": args.scopes,
    }

    def save():
        (out / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n")

    if len(keys) > 1:
        for key in keys:
            with (out / f"{key}.log").open("w") as log:
                try:
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).resolve()),
                            "--output",
                            str(out / key),
                            "--registry",
                            str(registry_root),
                            "--keys",
                            key,
                            "--cpu",
                            str(args.cpu),
                            "--scopes",
                            *args.scopes,
                        ],
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        timeout=args.entry_timeout,
                    )
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    code = "DRIVER_TIMEOUT"
            child_path = out / key / "audit.json"
            if child_path.exists():
                child = json.loads(child_path.read_text())
                audit["cases"].extend(child["cases"])
                audit["failures"].extend(child["failures"])
            if code and not any(f["key"] == key for f in audit["failures"]):
                audit["failures"].append({"key": key, "phase": "entry_process", "exit_code": code})
            audit["status"] = "RUNNING"
            save()
            print(key, "PASS" if code == 0 else "FAIL", flush=True)
    else:
        key = keys[0]
        manifest = codecs.get(key)
        _, template = select_template(manifest.key)
        for scope in args.scopes:
            case = {"key": key, "canonical_key": manifest.key, "scope": scope}
            try:
                config = deepcopy(template)
                config["profile"] = {**defaults["profile"], **config.get("profile", {})}
                config["reporting"] = {**defaults["reporting"], **config.get("reporting", {})}
                config.update(
                    algorithms=[key],
                    datasets=[fixtures[manifest.key]],
                    tracks=[config["tracks"][0]],
                )
                config["profile"].update(
                    measurement_mode="QUALIFICATION",
                    timing_scope=scope,
                    cpu_affinity=[args.cpu],
                    warmup_min_count=1,
                    warmup_min_seconds="0",
                    repetitions=1,
                    min_repetition_seconds="0",
                    query_workload=False,
                    streaming_workload=False,
                )
                config["reporting"]["bootstrap_samples"] = 100
                config["sweep"] = {k: [v[0]] for k, v in config.get("sweep", {}).items()}
                if manifest.key == "oracle-lossy-adapter":
                    config["sweep"]["error_bound"] = ["0.01"]
                filename = out / f"{scope}.toml"
                filename.write_text(config_text(config))
                run_set = initialize_run_set(filename, out / "runs", run_set_id=scope.lower())
                execute_run_set(run_set, DatasetRegistry(registry_root, ROOT), codecs)
                raw = run_set.path / "run_components.jsonl"
                records = [json.loads(line) for line in raw.read_text().splitlines()]
                tasks = [
                    json.loads(line)
                    for line in (run_set.path / "task_plan.jsonl").read_text().splitlines()
                ]
                assert len(records) == len(tasks) == 1
                timing = validate_record(records[0], tasks[0], scope)
                report = report_run_set(run_set)
                assert report.task_count == 1 and report.summary_count == 0
                case.update(
                    status="PASS",
                    run_status=records[0]["status"],
                    reason=records[0]["reason_code"],
                    timing=timing,
                    accounting=records[0]["accounting"],
                    correctness=records[0]["correctness"],
                    run_path=str(run_set.path.relative_to(ROOT)),
                    raw_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                    algorithm_id=tasks[0]["algorithm_id"],
                    dataset_id=tasks[0]["dataset_id"],
                )
            except Exception as error:
                case.update(status="FAIL", error=f"{type(error).__name__}: {error}")
                audit["failures"].append(case.copy())
            audit["cases"].append(case)
            audit["status"] = "RUNNING"
            save()
            print(key, scope, case["status"], case.get("error", ""), flush=True)
    audit.update(
        status="PASS"
        if not audit["failures"] and len(audit["cases"]) == len(keys) * len(args.scopes)
        else "FAIL",
        entry_count=len(keys),
        case_count=len(audit["cases"]),
    )
    save()
    return 0 if audit["status"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--registry", type=Path, default=ROOT / "Dataset_Verify/v3/registry")
    parser.add_argument("--keys", nargs="+")
    parser.add_argument(
        "--scopes",
        nargs="+",
        choices=("CORE", "PIPELINE", "E2E"),
        default=["CORE", "PIPELINE", "E2E"],
    )
    parser.add_argument("--cpu", type=int, default=2)
    parser.add_argument("--entry-timeout", type=int, default=1800)
    raise SystemExit(run(parser.parse_args()))
