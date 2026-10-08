"""Execute the actual five-layer RLE path serially and retain immutable run evidence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from audit_fastpfor_simple8b_rle_sdk import audit
from audit_fastpfor_simple8b_rle_native import identity, require
from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[1]
KEY = "fastpfor-simple8b-rle-u32"
SCOPE = "SYNTHETIC_UINT32_VALUE_UTS_MARKED_UNMARKED_RLE_ONLY"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("qualification", "formal"), required=True)
    parser.add_argument("--suffix", default="20261007-2")
    args = parser.parse_args()
    affinity = [0] if args.phase == "formal" else [2]
    require(sorted(os.sched_getaffinity(0)) == affinity, "five-layer driver CPU affinity differs")
    out = ROOT / "build/source-audits" / f"fastpfor-simple8b-rle-{args.phase}-{args.suffix}"
    require(not out.exists(), "preserve existing five-layer evidence")
    sdk = audit()
    before = {p.resolve(): identity(p)["sha256"]
              for directory in (ROOT / "src", ROOT / "tools") for p in directory.rglob("*.py")}
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    manifest = registry.get(KEY)
    kinds = ("formal-20",) if args.phase == "formal" else ("qualification", "unsupported-qualification")
    for kind in kinds:
        require(not (ROOT / "runs" / f"{KEY}-{kind}-{args.suffix}").exists(), "preserve prior RunSetID")
    out.mkdir(parents=True)
    (out / "driver.py").write_bytes(Path(__file__).read_bytes())
    document = {
        "status": "RUNNING", "phase": args.phase, "scope": SCOPE,
        "driver": identity(Path(__file__)), "driver_snapshot": identity(out / "driver.py"),
        "actual_cpu_affinity": affinity, "sdk_current_audit": sdk, "runs": [],
        "full_logical_entry_qualified": False, "independent_run_audit": "PENDING",
    }

    def save() -> None:
        (out / "report.json").write_text(json.dumps(document, indent=2) + "\n")

    save()
    try:
        for kind in kinds:
            config = ROOT / f"configs/experiments/{KEY}-{kind}.toml"
            run_id = f"{KEY}-{kind}-{args.suffix}"
            run = initialize_run_set(config, ROOT / "runs", run_set_id=run_id)
            print("RUNNING", run_id, flush=True)
            results = execute_run_set(run, datasets, registry)
            report_run_set(run)
            records = [json.loads(line) for line in (run.path / "run_components.jsonl").read_text().splitlines()]
            require(len(records) == sum(len(r.records) for r in results), "persisted records differ from actual execution")
            statuses = dict(Counter(r["status"] for r in records))
            document["runs"].append({
                "key": KEY, "kind": kind, "run_set_id": run_id, "config": identity(config),
                "algorithm_id": manifest.algorithm_id, "source_artifact_id": manifest.source_artifact_id,
                "record_count": len(records), "statuses": statuses, "eligible_count": sum(r["eligibility"] for r in records),
                "files": [identity(p) for p in sorted(run.path.rglob("*")) if p.is_file()],
            })
            save()
            if args.phase == "formal":
                require(len(records) == 80 and set(statuses) <= {"PASS", "RESOURCE_PRESSURE"},
                        "formal attempt/status universe differs: " + str(statuses))
            else:
                expected = {"PASS":4} if kind == "qualification" else {"UNSUPPORTED":8}
                require(statuses == expected, "five-layer status/cardinality differs: " + str(statuses))
            print("DONE", run_id, statuses, flush=True)
        paths = {Path(__file__).resolve()}
        for module in list(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name and str(name).endswith(".py") and Path(name).resolve().is_relative_to(ROOT):
                paths.add(Path(name).resolve())
        for path in paths:
            require(before.get(path) == identity(path)["sha256"], "executed Python source changed during runs")
            target = out / "sources" / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
        require(audit() == sdk, "SDK/native evidence changed during runs")
        document.update(status="FIVE_LAYER_RUNS_EXECUTED_INDEPENDENT_AUDIT_PENDING",
                        actual_python_source_closure=[identity(p) for p in sorted(paths)])
    except Exception as error:
        document.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
