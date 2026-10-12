"""Independently audit the completed frozen queue without rewriting raw runs.

The original auditor retains its byte-serialization mismatch result. This
supplement compares JSON bundle objects semantically and records the exact
remaining lane gaps; it does not execute codecs or performance measurements.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
RUNS = ROOT / "build/closure-formal-verification-20261011/formal-r3/runs"
PLAN_PATH = (
    ROOT / "build/closure-formal-verification-20261011/formal-r3/preparation/release_plan.json"
)
OUT = RUNS / "formal_audit_post_queue_semantic.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path) -> dict:
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}


def read(path: Path):
    return json.loads(path.read_text())


def main() -> None:
    plan = read(PLAN_PATH)
    queue = read(RUNS / "queue_result.json")
    if OUT.exists():
        raise ValueError("preserve prior post-queue audit")
    lanes = plan["lanes"]
    attempts = [
        json.loads(line) for line in (RUNS / "queue_attempts.jsonl").read_text().splitlines()
    ]
    by_lane = {row["lane"]: row for row in attempts}
    aux = read(RUNS / "post_queue_auxiliary" / "summary.json")
    aux_by_lane = {}
    for row in aux["results"]:
        aux_by_lane.setdefault(row["lane"], {})[row["audit"]] = row
    rows, observed = [], []
    for lane in lanes:
        name, kind = lane["run_set_id"], lane["kind"]
        run = RUNS / name
        attempt = by_lane[name]
        row = {
            "lane": name,
            "kind": kind,
            "driver_exit_code": attempt["exit_code"],
            "input_snapshot_unchanged": attempt["input_snapshot_unchanged"],
            "attempt_log": attempt["log"],
            "auxiliary": {
                key: {"exit_code": value["exit_code"], "log": value["log"]}
                for key, value in aux_by_lane.get(name, {}).items()
            },
            "status": "GAP",
            "gaps": [],
        }
        if attempt["exit_code"] != 0:
            row["gaps"].append("LANE_DRIVER_EXIT_NONZERO")
        if lane.get("bundle"):
            frozen = read(ROOT / lane["bundle"])
            actual = read(run / "bundle.json")
            row["bundle_semantically_equal"] = frozen == actual
            row["bundle_byte_equal"] = sha(ROOT / lane["bundle"]) == sha(run / "bundle.json")
            if frozen != actual:
                row["gaps"].append("BUNDLE_SEMANTIC_MISMATCH")
            if not row["bundle_byte_equal"]:
                row["gaps"].append("BUNDLE_SERIALIZATION_DIFFERENCE_RETAINED")
        if kind == "comparison" and attempt["exit_code"] == 0:
            analysis = read(run / "analysis.json")
            raw = run / "comparison_trials.jsonl"
            row.update(
                analysis_status=analysis["status"],
                raw=ref(raw),
                analysis=ref(run / "analysis.json"),
                raw_hash_matches_analysis=analysis["raw_sha256"] == sha(raw),
            )
            if analysis["status"] == "CORE_COMPLETE":
                observed.extend(
                    cell["codec_key"]
                    for cell in analysis["matrix"]
                    if cell.get("formal_complete")
                )
                row["status"] = "VERIFIED_CURRENT_FORMAL_LANE"
            else:
                row["gaps"].append("CORE_INCOMPLETE")
        elif kind == "workload" and attempt["exit_code"] == 0:
            analysis = read(run / "workload_analysis.json")
            raw = run / "workload_trials.jsonl"
            row.update(
                analysis_status=analysis["status"],
                raw=ref(raw),
                analysis=ref(run / "workload_analysis.json"),
                raw_hash_matches_analysis=analysis["raw_sha256"] == sha(raw),
            )
            if analysis["status"] == "PROFILE_COMPLETE":
                row["status"] = "VERIFIED_CURRENT_FORMAL_LANE"
            else:
                row["gaps"].append("PROFILE_INCOMPLETE")
        elif kind == "pipeline":
            pilot = read(run / "pilot.json") if (run / "pilot.json").exists() else {}
            row["pilot_eligible"] = pilot.get(
                "eligible", pilot.get("validation", {}).get("eligible")
            )
            row["pilot"] = ref(run / "pilot.json") if (run / "pilot.json").exists() else None
            row["gaps"].append("PIPELINE_PILOT_INELIGIBLE")
        if row["status"] == "GAP" and not row["gaps"]:
            row["gaps"].append("UNVERIFIED")
        rows.append(row)
    document = {
        "schema_version": "tscb.current-formal-post-queue-semantic-audit.v1",
        "status": "CURRENT_FORMAL_SCOPE_HAS_GAPS",
        "plan": ref(PLAN_PATH),
        "queue_result": ref(RUNS / "queue_result.json"),
        "queue_attempts": ref(RUNS / "queue_attempts.jsonl"),
        "post_queue_auxiliary": ref(RUNS / "post_queue_auxiliary" / "summary.json"),
        "input_snapshot_unchanged": queue["input_snapshot_unchanged"],
        "lane_count": len(rows),
        "successful_lane_driver_count": sum(row["driver_exit_code"] == 0 for row in rows),
        "verified_current_formal_lane_count": sum(
            row["status"] == "VERIFIED_CURRENT_FORMAL_LANE" for row in rows
        ),
        "two_independent_real_source_complete_codecs": sorted(set(observed)),
        "full_upstream_parity_granted": False,
        "all_N_G_CAP_gates_granted": False,
        "performance_remeasured_by_audit": False,
        "codec_execution_by_audit": "NONE",
        "original_auditor_byte_serialization_gap": True,
        "claim_boundary": (
            "Frozen current CPU profiles only; incomplete lanes and statistical "
            "limitations remain gaps."
        ),
        "lanes": rows,
    }
    OUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: document[k] for k in (
        "status", "lane_count", "successful_lane_driver_count",
        "verified_current_formal_lane_count", "two_independent_real_source_complete_codecs"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
