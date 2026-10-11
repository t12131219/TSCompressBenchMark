"""Qualify, pilot, measure and verify resume of an immutable V3.2 workload."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison.runner import (  # noqa: E402
    qualify_comparison,
    validate_qualification_evidence,
)
from tscompbench.comparison.workload_runner import (  # noqa: E402
    WorkloadProtocol,
    execute_workload_comparison,
    pilot_workload_comparison,
    prepare_workload_comparison,
    report_workload_comparison,
)
from tscompbench.datasets import DatasetRegistry  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-set-id", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    protocol = WorkloadProtocol(**json.loads(args.protocol.read_text()))
    run, plan = prepare_workload_comparison(
        args.bundle,
        args.output_root,
        ROOT,
        datasets,
        codecs,
        run_set_id=args.run_set_id,
        protocol=protocol,
        resume=args.resume,
    )
    qualification_path = run.path / "qualification.json"
    if qualification_path.exists():
        qualification = json.loads(qualification_path.read_text())
        validate_qualification_evidence(run, qualification)
    else:
        qualification = qualify_comparison(run, datasets)
    print(json.dumps({"stage": "qualification", "status": qualification["status"]}), flush=True)
    if qualification["status"] != "PASS":
        raise SystemExit("qualification incomplete; preserve evidence under this identity")
    pilot_path = run.path / "workload_pilot.json"
    pilot = (
        json.loads(pilot_path.read_text())
        if pilot_path.exists()
        else pilot_workload_comparison(run, plan, datasets)
    )
    print(json.dumps({"stage": "pilot", "status": pilot["status"]}), flush=True)
    if pilot["status"] != "PASS":
        raise SystemExit("pilot incomplete; formal eligibility not granted")
    report = execute_workload_comparison(run, plan, pilot)
    print(json.dumps({"stage": "formal", **report}), flush=True)
    if report["status"] != "PROFILE_COMPLETE":
        raise SystemExit("workload incomplete; fixed denominator and failures retained")
    raw = run.path / "workload_trials.jsonl"
    before = hashlib.sha256(raw.read_bytes()).hexdigest()
    resumed, resumed_plan = prepare_workload_comparison(
        args.bundle,
        args.output_root,
        ROOT,
        datasets,
        codecs,
        run_set_id=args.run_set_id,
        protocol=protocol,
        resume=True,
    )
    repeated = execute_workload_comparison(resumed, resumed_plan, pilot)
    reproduced = report_workload_comparison(run.path)
    after = hashlib.sha256(raw.read_bytes()).hexdigest()
    if before != after or repeated != report or reproduced != report:
        raise ValueError("no-op resume/report changed raw observations or analysis identity")
    proof = {
        "schema_version": "tscb.no-op-resume-verification.v1",
        "before_sha256": before,
        "after_sha256": after,
        "status": report["status"],
        "analysis_id": report["analysis_id"],
        "codec_execution_required": False,
        "performance_execution_required": False,
        "verification": "PREPARE_RESUME_EXECUTE_AND_READ_ONLY_REPORT",
    }
    proof_path = run.path / "resume_verification.json"
    payload = canonical_json_bytes(proof) + b"\n"
    if proof_path.exists():
        if proof_path.read_bytes() != payload:
            raise ValueError("immutable resume verification differs")
    else:
        with proof_path.open("xb") as handle:
            handle.write(payload)
    print(json.dumps({"stage": "resume", **proof}), flush=True)


if __name__ == "__main__":
    main()
