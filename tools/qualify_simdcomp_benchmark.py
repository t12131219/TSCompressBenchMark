"""Run preplanned SIMDComp support/rejection matrices and optional serial formal runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from audit_simdcomp_sdk import audit, require, sha

from tscompbench.codecs import CodecRegistry, SourceRegistry
from tscompbench.datasets import DatasetRegistry
from tscompbench.runner import execute_run_set, initialize_run_set, report_run_set

ROOT = Path(__file__).resolve().parents[1]
KEYS = ("simdcomp-u32", "delta-simdcomp-u32", "for-simdcomp-u32")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-suffix", required=True)
    parser.add_argument("--formal", action="store_true")
    args = parser.parse_args()
    require(Path(args.run_suffix).name == args.run_suffix, "unsafe run suffix")
    evidence = {
        "status": "RUNNING",
        "sdk_audit": audit(),
        "runs": [],
        "driver_sha256": sha(Path(__file__)),
        "formal_requested": args.formal,
    }
    output = ROOT / f"build/source-audits/simdcomp_benchmark_{args.run_suffix}.json"
    before = {str(p.relative_to(ROOT)): sha(p) for p in (ROOT / "src").rglob("*.py")}

    def save() -> None:
        output.write_text(json.dumps(evidence, indent=2) + "\n")

    save()
    try:
        datasets = DatasetRegistry(ROOT / "registry/datasets", ROOT)
        codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
        for suffix in (
            "qualification",
            "unsupported-qualification",
            *(("formal-20",) if args.formal else ()),
        ):
            for key in KEYS:
                run_id = f"{key}-{suffix}-{args.run_suffix}"
                config = ROOT / f"configs/experiments/{key}-{suffix}.toml"
                print("START", run_id, flush=True)
                run = initialize_run_set(config, ROOT / "runs", run_set_id=run_id)
                results = execute_run_set(run, datasets, codecs)
                report = report_run_set(run)
                evidence["runs"].append(
                    {
                        "run_set_id": run_id,
                        "config_sha256": sha(config),
                        "tasks": len(results),
                        "report_tasks": report.task_count,
                        "records_sha256": sha(run.path / "run_components.jsonl"),
                        "report_sha256": sha(run.path / "report/report.json"),
                    }
                )
                save()
                print("DONE", run_id, len(results), flush=True)
        require(
            all(sha(ROOT / path) == digest for path, digest in before.items()),
            "framework changed during qualification/formal execution",
        )
        actual = sorted(
            {
                str(Path(m.__file__).resolve().relative_to(ROOT))
                for m in list(sys.modules.values())
                if getattr(m, "__file__", None)
                and str(m.__file__).endswith(".py")
                and Path(m.__file__).resolve().is_relative_to(ROOT / "src")
            }
        )
        evidence.update(
            status="RUNS_RECORDED_INDEPENDENT_AUDIT_PENDING",
            actual_imported_python_closure=[{"path": p, "sha256": before[p]} for p in actual],
            full_logical_entry_qualified=False,
        )
        save()
    except Exception as error:
        evidence.update(status="FAIL", error=str(error))
        save()
        raise


if __name__ == "__main__":
    main()
