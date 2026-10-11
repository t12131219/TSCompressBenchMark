"""Run independently frozen streaming/query profiles without adding a codec."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison.runner import qualify_comparison  # noqa: E402
from tscompbench.comparison.workload_runner import (  # noqa: E402
    WorkloadProtocol,
    execute_workload_comparison,
    pilot_workload_comparison,
    prepare_workload_comparison,
    report_workload_comparison,
)
from tscompbench.datasets import DatasetRegistry  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("qualify", "pilot", "formal", "report"))
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-set-id", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.stage == "report":
        response = report_workload_comparison(args.output_root / args.run_set_id)
    else:
        values = json.loads(args.protocol.read_text())
        protocol = WorkloadProtocol(**values)
        datasets = DatasetRegistry(root / "registry/comparison_datasets/v32_20261010", root)
        codecs = CodecRegistry(root / "registry/codecs", SourceRegistry(root / "registry/sources"))
        run, plan = prepare_workload_comparison(
            args.bundle,
            args.output_root,
            root,
            datasets,
            codecs,
            run_set_id=args.run_set_id,
            protocol=protocol,
            resume=args.resume,
        )
        if args.stage == "qualify":
            response = qualify_comparison(run, datasets)
            response = {k: response[k] for k in ("status", "failure_count", "qualification_id")}
        elif args.stage == "pilot":
            response = pilot_workload_comparison(run, plan, datasets)
            response = {k: response[k] for k in ("status", "pilot_id", "validation")}
        else:
            response = execute_workload_comparison(
                run, plan, json.loads((run.path / "workload_pilot.json").read_text())
            )
    print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
