"""Check static review shape/identity/class preservation, never execute codecs."""

import hashlib
import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    output = HERE / "static_integrity_check_r1.json"
    require(not output.exists(), "retain existing static check")
    path = HERE / "acceptance_review_r1.json"
    report = json.loads(path.read_text())
    entries = report["entries"]
    rows = [g for e in entries for g in e["gates"]]
    require(len(entries) == 33 and len(rows) == 220, "entry/gate count")
    require(len({e["codec_key"] for e in entries}) == 33, "duplicate codec")
    require(len({(g["codec_key"], g["gate"]) for g in rows}) == 220, "duplicate gate")
    require(all(g["subitems"] for g in rows), "empty subitem review")
    require(set(g["status"] for g in rows) <= {"PASS", "FAIL", "UNKNOWN", "N/A"}, "invalid standard state")
    require(dict(Counter(g["status"] for g in rows)) == report["gate_status_counts"], "status counts")
    require({(g["codec_key"], g["gate"]) for g in rows if g["status"] == "PASS"}
            == {("abba", "G0"), ("fabba", "G0"), ("deepzip", "G0")}, "unreviewed gate PASS")
    for entry in entries:
        expected = ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "CAP-GATE"] if entry["route"] == "SOURCE_REWRITE" else ["N0", "N1", "N2", "N3", "N4", "N5"]
        require([g["gate"] for g in entry["gates"]] == expected, "wrong applicable gate family")
        require(all(g["codec_key"] == entry["codec_key"] for g in entry["gates"]), "mixed codec row")
    for key, ref in report["inputs"].items():
        current = ROOT / ref["path"]
        data = current.read_bytes()
        require(hashlib.sha256(data).hexdigest() == ref["sha256"] and len(data) == ref["bytes"], "input identity drift: " + key)
    for codec in ("abba", "fabba", "deepzip"):
        identity = report["G0_current_logical_identity_reviews"][codec]
        text = (ROOT / report["inputs"][codec + "_manifest"]["path"]).read_text()
        for key in ("algorithm_id", "implementation_id", "object_level"):
            value = re.search(r"^" + key + r": ([^\n]+)$", text, re.M)
            require(value and value.group(1).strip() == identity[key], "logical identity mismatch")
    original = json.loads((ROOT / report["inputs"]["cap_inventory"]["path"]).read_text())
    old_classes = {(m["codec"], c["capability_id"]): c["parity_class"] for m in original for c in m["capabilities"]}
    new_classes = {(m["codec_key"], c["capability_id"]): c["frozen_original_classification"] for m in report["existing_frozen_capability_reviews"] for c in m["capabilities"]}
    require(old_classes == new_classes, "original capability ID/classification changed")
    required_count = sum(value == "REQUIRED_PARITY" for value in new_classes.values())
    require(required_count == 42, "required obligations changed")
    require(new_classes[("dzip", "reference.gpu_bpc_estimator")] == "REFERENCE_ONLY", "historical class overwritten")
    result = {"schema_version": "tscb.gate-review-static-integrity.v1",
              "status": "PASS_STATIC_REPORT_INTEGRITY_ONLY",
              "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
              "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "entry_count": len(entries), "unique_nonempty_gate_rows": len(rows),
              "gate_status_counts": report["gate_status_counts"],
              "G0_exact_current_logical_ids_checked": ["abba", "fabba", "deepzip"],
              "original_capability_ID_and_classification_sets_exact": True,
              "required_obligations_retained": required_count,
              "four_matrices_checked": len(report["existing_frozen_capability_reviews"]),
              "input_receipt_SHA_and_size_matches": len(report["inputs"]),
              "codec_or_model_execution": False,
              "complete_gate_or_semantic_qualification_granted": False}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
