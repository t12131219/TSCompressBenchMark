"""Qualify, pilot, measure and verify resume of one immutable V3.2 comparison."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from run_v32_comparison import stage_evidence  # noqa: E402

from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison.runner import (  # noqa: E402
    execute_comparison,
    prepare_comparison,
    report_comparison,
)
from tscompbench.datasets import DatasetRegistry  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-set-id", required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    datasets = DatasetRegistry(ROOT / "registry/comparison_datasets/v32_20261010", ROOT)
    codecs = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    run = prepare_comparison(
        args.bundle,
        args.output_root,
        ROOT,
        datasets,
        codecs,
        run_set_id=args.run_set_id,
        resume=args.resume,
    )
    qualification, qualification_reused = stage_evidence(
        run, datasets, "qualify", resume=args.resume
    )
    print(
        json.dumps(
            {
                "stage": "qualification",
                "status": qualification["status"],
                "failures": qualification["failure_count"],
                "evidence_reused": qualification_reused,
            }
        ),
        flush=True,
    )
    if qualification["status"] != "PASS":
        raise SystemExit("qualification incomplete; retain this run and fix under a new identity")
    pilot, pilot_reused = stage_evidence(run, datasets, "pilot", resume=args.resume)
    print(
        json.dumps({"stage": "pilot", "status": pilot["status"], "evidence_reused": pilot_reused}),
        flush=True,
    )
    if pilot["status"] != "PASS":
        raise SystemExit("pilot incomplete; no formal eligibility granted")
    report = execute_comparison(run, pilot)
    print(json.dumps({"stage": "formal", **report}), flush=True)
    if report["status"] != "CORE_COMPLETE":
        raise SystemExit("core incomplete; fixed denominator and failures retained")
    raw = run.path / "comparison_trials.jsonl"
    before = hashlib.sha256(raw.read_bytes()).hexdigest()
    resumed = prepare_comparison(
        args.bundle,
        args.output_root,
        ROOT,
        datasets,
        codecs,
        run_set_id=args.run_set_id,
        resume=True,
    )
    repeated = execute_comparison(resumed, pilot)
    reproduced = report_comparison(run.path)
    after = hashlib.sha256(raw.read_bytes()).hexdigest()
    if before != after or repeated != report or reproduced != report:
        raise ValueError("no-op resume/report changed the raw observations or analysis identity")
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
