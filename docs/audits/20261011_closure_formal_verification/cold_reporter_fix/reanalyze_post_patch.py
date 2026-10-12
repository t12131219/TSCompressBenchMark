"""Rebuild cold analysis in a separate output after the null-record fix.

The frozen FORMAL run directory is never rewritten. This is a diagnostic
analysis of its retained raw trials and does not remeasure performance.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tscompbench.comparison.analysis import AnalysisPolicy, analyze_comparison
from tscompbench.comparison.runner import audit_trial_artifacts

ROOT = Path(__file__).resolve().parents[4]
RUN = ROOT / "build/closure-formal-verification-20261011/formal-r3/runs/cold"
OUT = Path(__file__).resolve().parent / "reanalysis"


def main() -> None:
    raw_path = RUN / "comparison_trials.jsonl"
    raw_before = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    bundle = json.loads((RUN / "bundle.json").read_text())
    plan_path = RUN / "qualified_execution_plan.json"
    if not plan_path.exists():
        plan_path = RUN / "execution_plan.json"
    plan = json.loads(plan_path.read_text())
    trials = [json.loads(line) for line in raw_path.read_text().splitlines()]
    artifact_audit = audit_trial_artifacts(RUN, trials, plan)
    analysis = analyze_comparison(
        plan,
        trials,
        AnalysisPolicy.from_document(bundle["analysis_policy"]),
        raw_file_sha256=raw_before,
        artifact_audit=artifact_audit,
    )
    OUT.mkdir(exist_ok=True)
    with (OUT / "analysis.json").open("x") as handle:
        json.dump(analysis, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    raw_after = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    result = {
        "schema_version": "tscb.cold-reporter-post-patch-reanalysis.v1",
        "status": analysis["status"],
        "analysis": (
            "docs/audits/20261011_closure_formal_verification/"
            "cold_reporter_fix/reanalysis/analysis.json"
        ),
        "raw_trials": (
            "build/closure-formal-verification-20261011/formal-r3/runs/"
            "cold/comparison_trials.jsonl"
        ),
        "raw_sha256_before": raw_before,
        "raw_sha256_after": raw_after,
        "raw_unchanged": raw_before == raw_after,
        "performance_remeasured": False,
        "codec_executed": False,
        "formal_qualification_granted": False,
        "coverage": analysis["coverage"],
        "core_gaps": len(analysis["core_gaps"]),
    }
    with (OUT / "receipt.json").open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
