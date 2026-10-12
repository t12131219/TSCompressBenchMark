"""Independently inspect preparation JSON and source literals, without codec execution.

Only Python's standard library is imported. No production driver is imported,
no source-language oracle is executed and no performance eligibility is granted.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]


def read(path: Path):
    return json.loads(path.read_text())


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(path: Path):
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}


def normalize(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {normalize(key): normalize(item) for key, item in value.items()}
    return value


def canonical(value):
    return json.dumps(normalize(value), ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(",", ":")).encode()


def projection(document):
    result = copy.deepcopy(document)
    for section, fields in {
        "contract": ["revision"],
        "config_map": ["contract_id"],
        "expected_matrix": ["contract_id", "config_map_id"],
        "group": ["revision", "contract_id", "config_map_id", "expected_matrix_id"],
    }.items():
        for field in fields:
            del result[section][field]
    for member in result["group"]["members"]:
        for field in ["source_artifact_id", "source_closure_sha256", "method_id"]:
            del member["implementation"][field]
        del member["method"]["name"]
        member["shared_code_tags"] = [
            "SOURCE_ARTIFACT:BOUND" if tag.startswith("SOURCE_ARTIFACT:") else tag
            for tag in member["shared_code_tags"]]
    for row in result["group"]["method_equivalence"]:
        row["evidence"] = [
            "SOURCE_ARTIFACT:BOUND" if tag.startswith("SOURCE_ARTIFACT:") else tag
            for tag in row["evidence"]]
    return result


def method_id(method):
    payload = {"schema_version": "tscb.method-definition.v1", **method}
    del payload["name"]
    return "v3:method:sha256:" + hashlib.sha256(canonical(payload)).hexdigest()


def check_ref(item):
    path = (ROOT / item["path"]).resolve()
    return path.is_relative_to(ROOT) and path.is_file() and sha(path) == item["sha256"] and (
        "bytes" not in item or path.stat().st_size == item["bytes"])


def observation_keys(value):
    forbidden = {"qualification", "pilot", "raw", "trials", "analysis", "report",
                 "resume_verification", "observations", "formal_results"}
    result = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in forbidden:
                result.append(key)
            result.extend(observation_keys(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(observation_keys(item))
    return result


def literal_assignments(path):
    assignments = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                assignments[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return assignments


def p2_static_review():
    old_path = ROOT / "build/v32-evidence-20261010/current-r2/formal-r2/continuation-r4/pipeline/plan.json"
    old = read(old_path)
    driver_path = ROOT / "tools/run_v32_pipeline_comparison.py"
    runner_path = ROOT / "src/tscompbench/comparison/pipeline_runner.py"
    tree = ast.parse(driver_path.read_text())
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "MeasurementProtocol"]
    explicit_protocol = {kw.arg: ast.literal_eval(kw.value) for kw in calls[0].keywords}
    constants = literal_assignments(runner_path)
    analysis_path = ROOT / "src/tscompbench/comparison/analysis.py"
    analysis = ast.parse(analysis_path.read_text())
    cls = next(node for node in analysis.body if isinstance(node, ast.ClassDef) and node.name == "AnalysisPolicy")
    defaults = {node.target.id: ast.literal_eval(node.value) for node in cls.body
                if isinstance(node, ast.AnnAssign) and node.value is not None}
    defaults["primary_comparisons"] = list(defaults["primary_comparisons"])
    resources = {"logical_cpus": [0], "threads": 1, "memory_limit_bytes": 1073741824}
    recipes = []
    for cell in old["cells"]:
        recipe = cell["recipe"]
        children = list(recipe["value_children"].values())
        children += [recipe[key] for key in ("mask_child", "timestamp_child") if recipe[key] is not None]
        recipes.append(all(child == {"codec_key": cell["method_id"], "parameters": {"native_timing": False}}
                           for child in children)
                       and recipe["block_size"] == 256 and recipe["tail_policy"] == "RAW_TAIL"
                       and recipe["loss_contract"] == {"kind": "LOSSLESS"}
                       and recipe["stages"] == ["TIME_AXIS_TO_FIRST", "LEXICOGRAPHIC_COLUMNS",
                                                "INDEPENDENT_BLOCKS", "TAIL_ENCODE"])
    expected_datasets = {"etth1_f32", "weather_f32", "etth1_mixed_nd_tv_validity", "weather_mixed_nd_tv_validity"}
    checks = {
        "explicit_protocol_literals_match": all(old["protocol"][key] == value for key, value in explicit_protocol.items()),
        "analysis_policy_defaults_match": old["analysis_policy"] == defaults,
        "cpu0_resource_declaration_matches": old["resources"] == resources,
        "pipeline_boundary_and_scope_match": all(old[key.lower()] == constants[key] for key in ("BOUNDARY", "SCOPE")),
        "attempt_policy_matches": old["attempt_policy"] == constants["ATTEMPT_POLICY"],
        "four_dataset_keys_match": {d["dataset_key"] for d in old["datasets"]} == expected_datasets,
        "two_child_method_keys_match": {c["method_id"] for c in old["cells"]} == set(constants["METHODS"]),
        "eight_recipes_match_current_literal_construction": len(recipes) == 8 and all(recipes),
        "historical_source_files_still_hash_match": all(check_ref(r) for d in old["datasets"] for r in d["source_files"]),
    }
    return {"status": "SOURCE_LITERAL_FIELDS_MATCH" if all(checks.values()) else "SOURCE_LITERAL_MISMATCH",
            "checks": checks, "historical_plan": ref(old_path),
            "reviewed_sources": [ref(p) for p in (driver_path, runner_path, analysis_path)],
            "limitation": "No new P2 plan exists here. Source-literal inspection does not replace a frozen full scientific-projection receipt or actual independent decoder/formal audit.",
            "builder_manually_reviewed_lines": [1587, 1708]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan_path, output = args.plan.resolve(), args.output.resolve()
    if output.exists() or not all(p.is_relative_to(ROOT) for p in (plan_path, output)):
        parser.error("choose a new project output and preserve existing evidence")
    plan = read(plan_path)
    references = []
    rows = []
    for receipt in plan["receipts"]:
        name = receipt["lane"]
        base, bundle, proof = [read(ROOT / receipt[key]["path"]) for key in ("base", "bundle", "proof")]
        lane = next(lane for lane in plan["lanes"] if lane["run_set_id"] == name)
        base_members = {m["member_id"]: m for m in base["group"]["members"]}
        checks = {
            "three_receipt_hashes_match": all(check_ref(receipt[key]) for key in ("base", "bundle", "proof")),
            "proof_bundle_refs_match": check_ref(proof["base_bundle"]) and check_ref(proof["output_bundle"]),
            "independent_semantic_projection_unchanged": projection(base) == projection(bundle),
            "projection_hash_matches_proof": hashlib.sha256(canonical(projection(bundle))).hexdigest() == proof["non_source_decisions_sha256"],
            "method_id_hashes_preserved": all(method_id(m["method"]) == method_id(base_members[m["member_id"]]["method"])
                                             == m["implementation"]["method_id"] for m in bundle["group"]["members"]),
            "no_observation_keys_transferred": not observation_keys(bundle),
            "qual_and_formal_transfer_flags_false": proof["qualification_transferred"] is False and proof["formal_results_transferred"] is False,
            "lane_bundle_matches_receipt": lane["bundle"] == receipt["bundle"]["path"],
        }
        if lane["kind"] == "workload":
            checks["protocol_copy_matches_historical_bytes"] = check_ref(lane["historical_protocol"]) and (
                (ROOT / lane["protocol"]).read_bytes() == (ROOT / lane["historical_protocol"]["path"]).read_bytes())
        references.extend(receipt[key] for key in ("base", "bundle", "proof"))
        rows.append({"lane": name, "kind": lane["kind"], "checks": checks,
                     "status": "STATIC_PREPARATION_VALIDATED" if all(checks.values()) else "STATIC_PREPARATION_HAS_GAPS",
                     "preparation_driver_hash_currently_matches": check_ref(proof["preparation_driver"]),
                     "member_count": len(bundle["group"]["members"])})
    result = {"schema_version": "tscb.independent-formal-preparation-static-review.v1",
              "created_at": datetime.now(UTC).isoformat(), "plan": ref(plan_path), "driver": ref(Path(__file__)),
              "status": "FIFTEEN_PLANS_STATIC_VALIDATED" if len(rows) == 15 and all(r["status"] == "STATIC_PREPARATION_VALIDATED" for r in rows) else "STATIC_PREPARATION_HAS_GAPS",
              "lanes": rows, "p2_source_literal_review": p2_static_review(),
              "codec_source_or_test_executed": False, "pilot_or_performance_executed": False,
              "formal_or_complete_N_G_CAP_granted": False,
              "references_unchanged_after_review": all(check_ref(r) for r in references),
              "claim_boundary": "Independent JSON/hash and source-literal inspection only; updated production queue/audit must bind complete declared closures and validate run-local plans against preparation."}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2).encode() + b"\n")
    print(json.dumps({"status": result["status"], "lanes": len(rows), "p2": result["p2_source_literal_review"]["status"], "references_unchanged": result["references_unchanged_after_review"]}))


if __name__ == "__main__":
    main()
