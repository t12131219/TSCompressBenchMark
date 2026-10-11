"""Run/resume/report the frozen existing-codec V3.2 P2 object lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from tscompbench.comparison.analysis import AnalysisPolicy
from tscompbench.comparison.pipeline_runner import (
    build_real_pipeline_inputs,
    execute_pipeline_comparison,
    pilot_pipeline_comparison,
    prepare_pipeline_comparison,
    qualify_pipeline_comparison,
    report_pipeline_comparison,
)
from tscompbench.ids import canonical_json_bytes
from tscompbench.measurement.v32_protocol import MeasurementProtocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "qualify", "pilot", "run", "report", "all"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--verify-resume", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if args.verify_resume and args.stage not in {"all", "run"}:
        parser.error("--verify-resume requires all or run")
    if args.stage == "all" and (output / "plan.json").exists() and not args.resume:
        parser.error("existing frozen plan requires explicit --resume")
    if args.stage in {"prepare", "all"}:
        datasets = build_real_pipeline_inputs(root, output / "inputs")
        protocol = MeasurementProtocol(
            profile="STEADY_PROCESS",
            timing_scope="PIPELINE",
            outer_repetitions=4,
            encode_min_ns=20_000_000,
            decode_min_ns=20_000_000,
            max_trial_wall_ns=30_000_000_000,
            max_total_wall_ns=1_800_000_000_000,
            warmup_min_count=2,
            warmup_min_ns=20_000_000,
            pilot_repetitions=7,
            thread_monitor_interval_ns=5_000_000,
            max_collector_fraction="0.25",
            max_harness_fraction="0.05",
        )
        prepare_pipeline_comparison(
            root,
            output,
            datasets,
            protocol=protocol,
            policy=AnalysisPolicy(),
            resources={
                "logical_cpus": [args.cpu],
                "threads": 1,
                "memory_limit_bytes": 1_073_741_824,
            },
        )
    if args.stage in {"qualify", "all"}:
        qualify_pipeline_comparison(output)
    if args.stage in {"pilot", "all"}:
        pilot_pipeline_comparison(output)
    if args.stage in {"run", "all"}:
        result = execute_pipeline_comparison(output)
    elif args.stage == "report":
        result = report_pipeline_comparison(output)
    else:
        result = {"stage": args.stage, "output": str(output)}
    if args.verify_resume:
        if result["status"] != "COMPLETE":
            raise SystemExit("P2 incomplete; fixed denominator and evidence retained")
        raw = output / "trials.jsonl"
        before = hashlib.sha256(raw.read_bytes()).hexdigest()
        repeated = execute_pipeline_comparison(output)
        reproduced = report_pipeline_comparison(output)
        after = hashlib.sha256(raw.read_bytes()).hexdigest()
        if before != after or repeated != result or reproduced != result:
            raise ValueError("P2 no-op resume/report changed raw or derived analysis")
        proof = {
            "schema_version": "tscb.no-op-resume-verification.v1",
            "before_sha256": before,
            "after_sha256": after,
            "status": result["status"],
            "report_sha256": hashlib.sha256((output / "report.json").read_bytes()).hexdigest(),
            "performance_execution_required": False,
            "codec_execution_required": True,
            "codec_execution_scope": "READ_ONLY_INDEPENDENT_DECODER_AUDIT",
            "verification": "EXECUTE_RESUME_AND_REPORT_WITHOUT_PERFORMANCE_REMEASUREMENT",
        }
        path = output / "resume_verification.json"
        payload = canonical_json_bytes(proof) + b"\n"
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError("immutable P2 resume verification differs")
        else:
            with path.open("xb") as handle:
                handle.write(payload)
        result = {"report": result, "resume": proof}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
