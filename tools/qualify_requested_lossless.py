"""Run all five Benchmark layers for the requested rewritten codecs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-suffix", default="20261006-final")
    args = parser.parse_args()
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    groups = []
    for track in ["value", "system"]:
        config = (
            ROOT / "configs/experiments" / ("requested-lossless-" + track + "-qualification.toml")
        )
        run = initialize_run_set(
            config, ROOT / "runs", run_set_id="requested-lossless-" + track + "-" + args.run_suffix
        )
        results = execute_run_set(run, datasets, codecs)
        report_run_set(run)
        cases = [
            {
                "task_id": r.records[0].task_id if r.records else None,
                "preflight_status": str(r.preflight.status),
                "preflight_reason": r.preflight.reason_code,
                "eligible": r.preflight.eligible_for_formal_repetitions,
                "records": [{"status": str(q.status), "reason": q.reason_code} for q in r.records],
            }
            for r in results
        ]
        group = {
            "track": track.upper(),
            "status": "PASS"
            if results
            and all(
                c["eligible"] and c["records"] and all(r["status"] == "PASS" for r in c["records"])
                for c in cases
            )
            else "FAIL",
            "config_sha256": sha(config),
            "run_path": str(run.path.relative_to(ROOT)),
            "cases": cases,
            "artifacts": [
                {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
                for p in sorted(run.path.rglob("*"))
                if p.is_file()
                and p.name
                in [
                    "report.json",
                    "run_components.jsonl",
                    "tasks.jsonl",
                    "preflight_results.jsonl",
                    "run_records.jsonl",
                    "frozen_config.json",
                ]
            ],
        }
        print(track, group["status"], len(cases), flush=True)
        groups.append(group)
        for c in cases:
            if not c["eligible"] or any(r["status"] != "PASS" for r in c["records"]):
                print(c, flush=True)
    result = {
        "status": "PASS" if all(g["status"] == "PASS" for g in groups) else "FAIL",
        "measurement_mode": "QUALIFICATION",
        "timing_scope": "PIPELINE",
        "groups": groups,
        "driver_sha256": sha(Path(__file__)),
    }
    (ROOT / "docs/requested_lossless_benchmark_qualification.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    raise SystemExit(result["status"] != "PASS")


if __name__ == "__main__":
    main()
