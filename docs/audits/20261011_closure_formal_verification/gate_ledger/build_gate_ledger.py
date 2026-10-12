"""Build an explicit current acceptance ledger from independent static inventory.

This adds no execution and grants no gate. Historical scoped PASS evidence and
required classifications remain separate from current complete acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
INVENTORY = ROOT / "docs/audits/20261011_closure_formal_verification/gate_audit"
CRITERIA = {
    "N0": ("SOURCE_OBJECT_SCOPE", "Complete reviewed source/capability universe and current target; core route, object role, logical implementation identity and deduplication."),
    "N1": ("SOURCE_BUILD_BASELINE", "Actual TU/include/generated/link/startup/runtime/model closure, licenses and independent original baseline; reproducible build and patch recipe."),
    "N2": ("CONTRACT_DEVIATION_FREEZE", "Pre-execution canonical domain, parameters, raw/frame/state/error/resource and compatibility target; patch/source-defect/CAP/oracle/platform plan."),
    "N3": ("CORE_API_SAFETY", "Applicable ownership, guard/padding/capacity, checked lengths, malformed, failure/reuse, finalize/EOF/reset, concurrency, sanitizer and cold restore tests."),
    "N4": ("SOURCE_PARITY_CAPABILITY", "Independent native API/source baseline and affected-path differential on identical inputs/configuration/state; real datasets and declared ISA/thread/platform execution."),
    "N5": ("INDEPENDENT_DELIVERY", "Isolated consumer build/test/cold restore using only declared source/API/driver/dependencies, reproducible patch, SBOM/license and report index; no FORMAL prerequisite."),
    "G0": ("ASSET_IDENTITY", "Independent logical AlgorithmID/ImplementationID, route/object/source mappings and reviewed deduplication; Bench IDs do not replace package IDs."),
    "G1": ("SOURCE_LICENSE_CAPABILITY", "Complete original-language executable closure/runtime/models, per-file provenance/license/SBOM and full public/API/build/docs/CI/tests capability universe."),
    "G2": ("CONTRACT_ORACLE_CAP_FREEZE", "Formula/state/error/bitstream/API compatibility and executable independent oracle; four-state CAP owner/platform/test and compatible real-data plan frozen before execution."),
    "G3": ("CANONICAL_CORRECTNESS", "All required canonical paths, golden/differential/cross-decode, same real data/preprocessing/config/model/reset boundaries; edge/malformed/sanitizer and source-defect rejection separately."),
    "G4": ("INDEPENDENT_PUBLIC_API", "Own standalone API/CLI exposing every required capability, lifecycle/ownership/capacity/FinalBits/cold recovery; qualification outside Bench binding."),
    "G5": ("REQUIRED_OPTIMIZED_PATHS", "Every required ISA/thread/GPU variant forced and observed, differentially checked on real data with tail/resource/concurrency/platform gates; no unavailable-device PASS."),
    "G6": ("INDEPENDENT_RELEASE", "Current package isolated release/build/test, correctness/security/portability/performance/license/docs/reproducibility, dataset report and complete CAP closure."),
    "CAP-GATE": ("COMPLETE_CAPABILITY_CLOSURE", "G1 inventory/G2 valid classification/G3 functionality/G4 independent API/G5 optimized variants/G6 report all complete; original required set preserved, any waiver explicit and valid."),
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path):
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT):
        parser.error("retain existing evidence and select a new project output")
    names = ("report.json", "capability_inventory.json", "environment_inventory.json", "source_assets.json", "gate_requirements.json")
    inputs = [ref(INVENTORY / name) for name in names]
    report = read(INVENTORY / "report.json")
    entries = []
    gates_total = 0
    for item in report["entries"]:
        gates = ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "CAP-GATE"] if item["route"] == "SOURCE_REWRITE" else ["N0", "N1", "N2", "N3", "N4", "N5"]
        rows = [{"gate": gate, "current_complete_gate_status": "UNKNOWN", "criterion": CRITERIA[gate][1],
                 "criterion_key": CRITERIA[gate][0], "reason": "Complete current acceptance was not executed or independently signed by this static inventory; prior scoped evidence remains available.",
                 "responsible_role": "SOURCE_OR_NATIVE_ACCEPTANCE_REVIEWER",
                 "acceptance_required": True, "recorded_execution_failure": False}
                for gate in gates]
        gates_total += len(rows)
        entries.append({"codec_key": item["codec_key"], "route": item["route"], "object_level": item["object_level"],
                        "scope_for_next_acceptance": "FULL_FROZEN_REQUIRED_CAPABILITY_SET" if item["route"] == "SOURCE_REWRITE" else "PREDECLARED_CURRENT_NATIVE_PROFILE",
                        "registered_profile": item["registered_profile"],
                        "prior_scoped_evidence": item["already_saved_scoped_evidence"],
                        "declared_execution_dependency_result": item["current_declared_execution_dependency_status"],
                        "source_inventory_status_not_automatic_N1_failure": item["source_closure_status_is_not_automatically_n1_failure"],
                        "entry_specific_next_action": item["entry_specific_action"],
                        "external_asset_or_execution_blockers": item["external_blockers"],
                        "all_required_gates_accepted": False, "gates": rows})
    capabilities = []
    valid_classes = {"REQUIRED_PARITY", "OPTIONAL_OPTIMIZATION", "UNAVAILABLE_WITH_WAIVER", "NOT_APPLICABLE"}
    for matrix in read(INVENTORY / "capability_inventory.json"):
        rows = []
        for item in matrix["capabilities"]:
            old_class = item["parity_class"]
            rows.append({"capability_id": item["capability_id"], "frozen_original_classification": old_class,
                         "classification_preserved_without_demotion": old_class in valid_classes,
                         "new_valid_classification_review_required": old_class not in valid_classes,
                         "historical_recorded_validation": item["historical_recorded_validation"],
                         "current_complete_cap_acceptance_status": "UNKNOWN",
                         "history_migrated_as_current_pass": False,
                         "required_implementation_obligation_retained": old_class == "REQUIRED_PARITY"})
        capabilities.append({"codec_key": matrix["codec"], "matrix": matrix["matrix"],
                             "original_class_counts": matrix["class_counts"], "capabilities": rows,
                             "full_parity_currently_granted": False})
    result = {"schema_version": "tscb.current-complete-gate-acceptance-ledger.v1",
              "created_at": datetime.now(UTC).isoformat(), "driver": ref(Path(__file__)), "inputs": inputs,
              "status": "COMPLETE_GATE_LEDGER_RECORDED_ACCEPTANCE_PENDING",
              "entry_count": len(entries), "applicable_gate_row_count": gates_total,
              "gate_status_counts": {"PASS": 0, "FAIL": 0, "UNKNOWN": gates_total, "N/A": 0},
              "entries": entries, "existing_frozen_capability_matrices": capabilities,
              "claim_boundary": "UNKNOWN here concerns complete current gate sign-off. It neither cancels historical finite PASS nor changes required classification, nor asserts current codec/test failure.",
              "full_upstream_parity_or_REWRITE_DONE_granted": False,
              "native_complete_acceptance_granted": False, "formal_granted": False,
              "new_execution": False,
              "inputs_unchanged": all(sha(ROOT / item["path"]) == item["sha256"] for item in inputs)}
    if result["entry_count"] != 33 or gates_total != 220 or not result["inputs_unchanged"]:
        raise ValueError("ledger count or immutable input validation failed")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2).encode() + b"\n")
    print(json.dumps({"status": result["status"], "entries": len(entries), "gate_rows": gates_total,
                      "capability_matrices": len(capabilities), "inputs_unchanged": result["inputs_unchanged"]}))


if __name__ == "__main__":
    main()
