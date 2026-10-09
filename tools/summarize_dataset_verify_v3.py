"""Recheck qualification receipts against current identities and preserve attempts.

This creates a new analysis artifact. It does not amend run records, infer
source parity, or promote qualification observations to formal performance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from verify_all_timing_scopes import validate_record

from tscompbench.adapters.factory import adapter_artifacts
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]


def main(args):
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    analyzer_snapshot = output / "analyzer.py"
    analyzer_snapshot.write_bytes(Path(__file__).read_bytes())
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    datasets = DatasetRegistry(ROOT / "Dataset_Verify/v3/registry", ROOT)
    roots = set(codecs.keys())
    selectable = roots | {alias["key"] for alias in codecs.alias_documents()}
    hashes = {}

    def sha(path):
        if path not in hashes:
            with path.open("rb") as handle:
                hashes[path] = hashlib.file_digest(handle, "sha256").hexdigest()
        return hashes[path]

    def receipt(path):
        path = path.resolve()
        path.relative_to(ROOT)
        return {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}

    artifacts = {}
    for key in roots:
        primary, supporting = adapter_artifacts(ROOT, codecs.get(key))
        components = [
            {"role": "PRIMARY_ADAPTER", "sha256": sha(primary)},
            *[
                {"role": f"SUPPORTING_COMPONENT_{i}", "sha256": sha(path)}
                for i, path in enumerate(supporting)
            ],
        ]
        artifacts[key] = (
            hashlib.sha256(canonical_json_bytes(components)).hexdigest()
            if supporting
            else sha(primary)
        )

    def read_run(key, path):
        run = ROOT / path
        records = [
            json.loads(line) for line in (run / "run_components.jsonl").read_text().splitlines()
        ]
        tasks = [json.loads(line) for line in (run / "task_plan.jsonl").read_text().splitlines()]
        by_task = {task["task_id"]: task for task in tasks}
        assert len(records) == len(tasks) == len(by_task), "incomplete qualification task universe"
        manifest = codecs.get(key)
        snapshot = json.loads((run / "codec_registry_snapshot.json").read_text())
        frozen = next(item for item in snapshot["codecs"] if item["key"] == manifest.key)
        assert frozen["manifest"] == manifest.document, f"{key}: stale codec snapshot"
        config = json.loads((run / "frozen_config.json").read_text())
        # The runner snapshot wraps the normalized configuration in document.
        config = config.get("document", config)
        assert config["profile"]["measurement_mode"] == "QUALIFICATION"
        for dataset_key in config["datasets"]:
            manifest_dataset = datasets.load(dataset_key)
            assert manifest_dataset.dataset_id in {task["dataset_id"] for task in tasks}
        for record in records:
            task = by_task[record["task_id"]]
            assert task["algorithm_id"] == record["algorithm_id"] == manifest.algorithm_id
            assert task["execution"]["cpu_affinity"] == config["profile"]["cpu_affinity"]
            assert task["execution"]["artifact_sha256"] == artifacts[manifest.key], (
                f"{key}: stale execution artifact"
            )
            assert not record["eligibility"], "qualification cannot be formal-eligible"
        report = json.loads((run / "report/report.json").read_text())
        assert report["task_count"] == len(tasks) and report["summary_count"] == 0
        return (
            records,
            by_task,
            [
                receipt(run / filename)
                for filename in (
                    "run_components.jsonl",
                    "task_plan.jsonl",
                    "codec_registry_snapshot.json",
                    "report/report.json",
                    "frozen_config.json",
                )
            ],
        )

    result = {
        "schema_version": "tscb.dataset-verify-v3-analysis.v1",
        "measurement_mode": "QUALIFICATION",
        "performance_claim": False,
        "source_parity_claim": False,
        "all_universe_execution_claim": False,
        "independent_expected_rejection_matrix_complete": False,
        "attempts": [],
        "positive_cases": [],
        "grid_entries": [],
        "errors": [],
    }
    cases = {}
    for directory in args.entries:
        path = directory / "audit.json"
        audit = json.loads(path.read_text())
        assert audit["status"] in ("PASS", "FAIL"), "entry attempt is still running"
        result["attempts"].append(
            {
                "kind": "positive",
                **receipt(path),
                "status": audit["status"],
                "failures": audit["failures"],
            }
        )
        for case in audit["cases"]:
            cases[(case["key"], case["scope"])] = case
    assert set(cases) == {
        (key, scope) for key in selectable for scope in ("CORE", "PIPELINE", "E2E")
    }
    for (key, scope), case in sorted(cases.items()):
        try:
            assert case["status"] == "PASS", case.get("error")
            records, tasks, files = read_run(key, case["run_path"])
            assert len(records) == 1
            validate_record(records[0], tasks[records[0]["task_id"]], scope)
            result["positive_cases"].append(
                {
                    "key": key,
                    "scope": scope,
                    "status": "PASS",
                    "run_status": records[0]["status"],
                    "files": files,
                }
            )
        except Exception as error:
            result["errors"].append({"key": key, "scope": scope, "error": str(error)})
    grids = {}
    for directory in args.grids:
        path = directory / "summary.json"
        audit = json.loads(path.read_text())
        assert audit.get("status") in ("PASS", "FAIL", "INTERRUPTED"), (
            "grid attempt is still running"
        )
        if audit.get("driver_sha256"):
            assert sha(directory / "driver.py") == audit["driver_sha256"], (
                "qualification driver snapshot differs"
            )
        result["attempts"].append(
            {
                "kind": "grid",
                **receipt(path),
                "status": audit["status"],
                "failures": audit["failures"],
                "scheduler": audit.get("scheduler"),
                "driver_snapshot": receipt(directory / "driver.py")
                if audit.get("driver_sha256")
                else None,
            }
        )
        for entry in audit["entries"]:
            grids[entry["key"]] = entry
    assert not args.grids or set(grids) == roots
    counts, reasons = Counter(), Counter()
    for key, entry in sorted(grids.items()):
        try:
            records, tasks, files = read_run(key, entry["run_path"])
            assert len(records) == entry["datasets"] == entry["report_task_count"]
            for record in records:
                assert record["status"] in ("UNSUPPORTED", "ISA_UNSUPPORTED") or (
                    (record.get("correctness") or {}).get("status") == "PASS"
                    and record["status"]
                    in ("PASS", "RESOURCE_PRESSURE", "OVERSUBSCRIBED", "INCOMPARABLE")
                ), f"{record['status']}: {record['reason_code']}"
                counts[record["status"]] += 1
                reasons[record["reason_code"]] += 1
            result["grid_entries"].append(
                {
                    **entry,
                    "correct_roundtrips": sum(
                        (record.get("correctness") or {}).get("status") == "PASS"
                        for record in records
                    ),
                    "native_encode_observations": sum(
                        (record.get("timing") or {}).get("native_encode_wall_ns") is not None
                        for record in records
                    ),
                    "native_decode_observations": sum(
                        (record.get("timing") or {}).get("native_decode_wall_ns") is not None
                        for record in records
                    ),
                    "files": files,
                }
            )
        except Exception as error:
            result["errors"].append({"key": key, "kind": "grid", "error": str(error)})
    result.update(
        status="FAIL" if result["errors"] else "PASS",
        root_entries=len(roots),
        real_entries=sum(
            codecs.get(key).document["identity"]["family"] != "HARNESS_ORACLE" for key in roots
        ),
        selectable_entries=len(selectable),
        positive_case_count=len(result["positive_cases"]),
        grid_requested=bool(args.grids),
        grid_record_count=sum(counts.values()),
        grid_status_counts=dict(counts),
        grid_reason_counts=dict(reasons),
        analyzer=receipt(Path(__file__)),
        analyzer_source_snapshot=receipt(analyzer_snapshot),
        dataset_index=receipt(ROOT / "Dataset_Verify/v3/index.json"),
    )
    (output / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if args.grids:
        with (output / "algorithm_coverage.csv").open("x", newline="") as handle:
            columns = (
                "key",
                "family",
                "algorithm_id",
                "records",
                "correct_roundtrips",
                "unsupported",
                "resource_pressure",
                "native_encode_observations",
                "native_decode_observations",
                "measurement_mode",
                "source_parity_claim",
            )
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for entry in result["grid_entries"]:
                manifest = codecs.get(entry["key"])
                writer.writerow(
                    {
                        **{
                            key: entry[key]
                            for key in (
                                "key",
                                "records",
                                "correct_roundtrips",
                                "native_encode_observations",
                                "native_decode_observations",
                            )
                        },
                        "family": manifest.document["identity"]["family"],
                        "algorithm_id": manifest.algorithm_id,
                        "unsupported": entry["counts"].get("UNSUPPORTED", 0),
                        "resource_pressure": entry["counts"].get("RESOURCE_PRESSURE", 0),
                        "measurement_mode": "QUALIFICATION",
                        "source_parity_claim": False,
                    }
                )
    print(
        json.dumps(
            {
                k: result[k]
                for k in (
                    "status",
                    "positive_case_count",
                    "grid_record_count",
                    "grid_status_counts",
                    "errors",
                )
            },
            indent=2,
        )
    )
    return int(bool(result["errors"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--entries", type=Path, nargs="+", required=True, help="Attempts in chronological order"
    )
    parser.add_argument(
        "--grids", type=Path, nargs="+", default=[], help="Attempts in chronological order"
    )
    raise SystemExit(main(parser.parse_args()))
