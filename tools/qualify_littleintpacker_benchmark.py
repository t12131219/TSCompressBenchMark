"""Persist serial original Simple source runs with current Python execution closure."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from audit_littleintpacker_sdk import audit, require, sha

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[1]
KEYS = (
    "littleintpacker-pack32-u32",
    "littleintpacker-turbo-u32",
    "littleintpacker-sc-u32",
    "littleintpacker-bmi2-u32",
    "littleintpacker-horizontal-u32",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("qualification", "formal"), required=True)
    parser.add_argument("--suffix", default="20261007-2")
    args = parser.parse_args()
    require(args.suffix and "/" not in args.suffix and ".." not in args.suffix, "invalid run suffix")
    affinity = [0] if args.phase == "formal" else [2]
    require(sorted(os.sched_getaffinity(0)) == affinity, "five-layer driver affinity differs")
    before = {
        p.resolve(): sha(p)
        for directory in (ROOT / "src", ROOT / "tools")
        for p in directory.rglob("*.py")
    }
    sdk = audit()
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
    out = ROOT / "build/source-audits" / f"littleintpacker-{args.phase}-{args.suffix}"
    require(not out.exists(), "preserve previous five-layer execution directory")
    out.mkdir(parents=True)
    output = out / "report.json"
    (out / "driver.py").write_bytes(Path(__file__).read_bytes())
    document = {
        "status": "RUNNING",
        "phase": args.phase,
        "execution_suffix": args.suffix,
        "actual_cpu_affinity": affinity,
        "output_directory": str(out.relative_to(ROOT)),
        "driver": {"path": str(Path(__file__).relative_to(ROOT)), "sha256": sha(Path(__file__))},
        "sdk_current_audit": sdk,
        "runs": [],
        "full_logical_entries_qualified": False,
        "qualification_scope": "SYNTHETIC_UINT32_VALUE_UTS_FIXED_AUTO_FIVE_APIS_ONLY",
    }

    def save() -> None:
        output.write_text(json.dumps(document, indent=2) + "\n")

    save()
    try:
        kinds = (
            ("formal-20",)
            if args.phase == "formal"
            else (
                "qualification",
                "unsupported-qualification",
                "source-domain-rejection-qualification",
            )
        )
        for key in KEYS:
            for kind in kinds:
                config = ROOT / f"configs/experiments/{key}-{kind}.toml"
                run_id = f"{key}-{kind}-{args.suffix}"
                # Existing runs are never replaced by a fresh qualification attempt.
                require(not (ROOT / "runs" / run_id).exists(), "run id already exists: " + run_id)
                manifest = registry.get(key)
                run = initialize_run_set(config, ROOT / "runs", run_set_id=run_id)
                print("RUNNING", run_id, flush=True)
                results = execute_run_set(run, datasets, registry)
                report_run_set(run)
                records = [
                    json.loads(line)
                    for line in (run.path / "run_components.jsonl").read_text().splitlines()
                ]
                require(
                    len(records) == sum(len(result.records) for result in results),
                    "persisted repetition count differs from actual task results",
                )
                files = [
                    {"path": str(p.relative_to(ROOT)), "sha256": sha(p)}
                    for p in sorted(run.path.rglob("*"))
                    if p.is_file()
                ]
                statuses = {}
                for record in records:
                    statuses[record["status"]] = statuses.get(record["status"], 0) + 1
                document["runs"].append(
                    {
                        "key": key,
                        "kind": kind,
                        "run_set_id": run_id,
                        "config": {"path": str(config.relative_to(ROOT)), "sha256": sha(config)},
                        "algorithm_id": manifest.algorithm_id,
                        "source_artifact_id": manifest.source_artifact_id,
                        "record_count": len(records),
                        "statuses": statuses,
                        "eligible_count": sum(r["eligibility"] for r in records),
                        "files": files,
                    }
                )
                save()
                print("DONE", run_id, statuses, flush=True)
        paths = {Path(__file__).resolve()}
        for module in list(sys.modules.values()):
            name = getattr(module, "__file__", None)
            if name and str(name).endswith(".py") and Path(name).resolve().is_relative_to(ROOT):
                paths.add(Path(name).resolve())
        require(
            all(before.get(p) == sha(p) for p in paths), "executed Python source changed during run"
        )
        for path in paths:
            frozen = out / "sources" / path.relative_to(ROOT)
            frozen.parent.mkdir(parents=True, exist_ok=True)
            frozen.write_bytes(path.read_bytes())
        require(audit() == sdk, "SDK/source evidence changed during five-layer runs")
        document.update(
            status="FIVE_LAYER_RUNS_EXECUTED_INDEPENDENT_AUDIT_PENDING",
            actual_python_source_closure=[
                {"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in sorted(paths)
            ],
        )
    except Exception as error:
        document.update(status="FAIL", error=str(error))
        raise
    finally:
        save()


if __name__ == "__main__":
    main()
