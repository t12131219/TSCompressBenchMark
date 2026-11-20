"""Versioned application entry points used by both Python and the CLI."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from .assets import ContractError, content_id, digest, load_json, local_file, require, verify_asset
from .contracts import Contract, load_contract
from .corpus import BOUNDARY_GENERATOR, MANIFEST_V3, check_corpus, load_boundary_fixtures, load_feature_policy
from .corpus_ingress import check_full_corpus
from .plugins import discover


@dataclass(frozen=True, slots=True)
class PlanRequest:
    suite: str = "first_batch_service_v3"
    max_workers: int = 1


@dataclass(frozen=True, slots=True)
class PlanResult:
    document: dict

    @property
    def content_id(self) -> str:
        return self.document["plan_content_id"]


def profile_corpus(root: Path) -> dict:
    from .analysis.corpus_features import profile_corpus as profile

    return profile(root)


def load_request(root: Path, config: str) -> PlanRequest:
    try:
        requested = tomllib.loads(local_file(root, config).read_text(encoding="utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ContractError(f"invalid request TOML: {exc}") from exc
    unknown = requested.keys() - {"schema", "suite", "max_workers"}
    require(not unknown, f"unknown request fields: {', '.join(sorted(unknown))}")
    require(type(requested.get("schema")) is int and requested["schema"] == 1,
            "request TOML requires schema = 1")
    load_contract(root, "experiment").validate(requested, config)
    return PlanRequest(**{name: value for name, value in requested.items() if name != "schema"})


def _document(root: Path, relative: str, schema: str, contract: Contract | None = None) -> dict:
    doc = load_json(local_file(root, relative))
    require(isinstance(doc, dict) and doc.get("schema") == schema,
            f"invalid document schema: {relative}; expected {schema}")
    if contract is not None:
        contract.validate(doc, relative)
    return doc


def _keyed(items: list[dict], key: str) -> dict:
    result = {}
    for item in items:
        name = item[key]
        require(name not in result, f"duplicate {key}: {name}")
        result[name] = item
    return result


def check_sources(root: Path, *, source_ids: set[str] | None = None) -> dict:
    """Check the requested source closure; default to the whole first batch."""
    lock = _document(root, "third_party/sources.lock.json", "bmk.sources/1")
    verify_asset(root, lock["selection_csv"])
    upstream = load_json(verify_asset(root, lock["selection_manifest"]))
    published = _keyed(upstream["repositories"], "repository")
    selections = _keyed(lock["selections"], "number")
    require(upstream["selection_sha256"] == lock["selection_csv"]["sha256"],
            "local selection CSV differs from frozen published manifest")
    require(set(lock["sources"]) == {entry["source_id"] for entry in selections.values()},
            "source/selection closure differs")
    require(source_ids is None or source_ids <= lock["sources"].keys(), "unknown requested source package")
    sources = {key: value for key, value in lock["sources"].items() if source_ids is None or key in source_ids}
    verified_files = 2
    for source_id, source in sources.items():
        require(source_id in published, f"unrecognized source: {source_id}")
        require(source["archive"]["sha256"] == published[source_id]["archive_sha256"],
                f"local archive lock differs from published hash: {source_id}")
        verify_asset(root, source["archive"])
        manifest = load_json(verify_asset(root, source["source_manifest"]))
        validation = load_json(verify_asset(root, source["historical_validation"]))
        require(manifest["sha256"] == validation["archive_sha256"] == source["archive"]["sha256"] and
                len(manifest["files"]) == source["files"], f"source metadata disagrees: {source_id}")
        verified_files += 3
    for number, entry in selections.items():
        if entry["source_id"] not in sources:
            continue
        expected = _keyed(published[entry["source_id"]]["selections"], "id").get(str(number))
        field = content_id(entry["selection_note"])
        require(expected is not None and entry["selection_note"] == expected["selection"] and
                entry["algorithm"] == expected["algorithm"] and entry["target"] == expected["target"] and
                entry["selection_field_sha256"] == field and
                entry["selection_id"] == content_id({"number": number,
                    "csv_sha256": lock["selection_csv"]["sha256"], "selection_field_sha256": field}),
                f"selection identity mismatch: {number}")
    return {"sources_lock_id": content_id(lock), "verified_assets": verified_files,
            "selections": [entry for entry in selections.values() if entry["source_id"] in sources],
            "sources": sources}


def _fixtures(root: Path, path: str) -> tuple[dict, int]:
    fixtures = _document(root, path, "bmk.fixtures/1")
    for name, asset in fixtures["files"].items():
        file = verify_asset(root, asset)
        require(file.stat().st_size == asset["bytes"], f"fixture bytes mismatch: {name}")
    for name, obj in fixtures["objects"].items():
        for files in obj["formats"].values():
            require(bool(files) and all(file in fixtures["files"] for file in files),
                    f"invalid fixture references: {name}")
    return fixtures, sum(x["bytes"] for x in fixtures["files"].values())


def plan(root: Path, request: PlanRequest) -> PlanResult:
    """Expand a registered stage suite without hiding unimplemented requirements.

    Scope plans do not grant admission or qualification. An atomic relation
    identifies a required selection/atom, not a worker or sample.
    """
    require(isinstance(request.suite, str) and re.fullmatch(r"[a-z0-9_-]+", request.suite) is not None,
            "invalid suite name")
    require(type(request.max_workers) is int and request.max_workers >= 1,
            "max_workers must be a positive integer")
    contracts = {name: load_contract(root, name) for name in (
        "experiment", "plugin", "suite", "matrix", "required-capabilities", "case-catalog", "native-inventory", "corpus")}
    contracts["experiment"].validate({"schema": 1, "suite": request.suite, "max_workers": request.max_workers},
                                     "plan request")
    registry = _document(root, "configs/suites/registry.json", "bmk.suite-registry/1")
    require(request.suite in registry["suites"], f"unknown suite: {request.suite}")
    suite_path = registry["suites"][request.suite]
    suite = load_json(local_file(root, suite_path))
    from .planner.service_scope import SCHEMA as SERVICE_SUITE_SCHEMA, plan_service_scope
    if isinstance(suite, dict) and suite.get("schema") == SERVICE_SUITE_SCHEMA:
        return PlanResult(plan_service_scope(root,request,suite,suite_path,registry))
    require(isinstance(suite,dict) and suite.get("schema")=="bmk.suite/1",f"invalid suite document: {suite_path}")
    contracts["suite"].validate(suite,suite_path)
    require(request.suite == suite["id"], "suite registry/contract identity mismatch")
    require(suite["state"] == "draft_m0", "this planner only supports M0 draft suite expansion")
    require(request.max_workers <= suite["policies"]["max_validation_workers"],
            "max_workers exceeds suite validation worker budget")
    source_check = check_sources(root)
    selections = _keyed(source_check["selections"], "number")
    inventory = _document(root, suite["native_inventory"], "bmk.native-inventory/1", contracts["native-inventory"])
    native = _keyed(inventory["entries"], "selection")
    required = _document(root, suite["requirements"], "bmk.required-capabilities/1", contracts["required-capabilities"])
    fixtures, fixture_bytes = _fixtures(root, suite["fixtures"])
    corpus = check_corpus(root, suite["corpus"], contract=contracts["corpus"])
    if suite["corpus"] == MANIFEST_V3:
        contracts["corpus-domain-intake"] = load_contract(root, "corpus-domain-intake")
    feature_policy, contracts["corpus-feature-policy"] = load_feature_policy(root, suite["corpus_feature_policy"])
    require(feature_policy["corpus_manifest"] == suite["corpus"] and feature_policy["fixture_manifest"] == suite["fixtures"],
            "feature policy must describe the suite's declared corpus and fixtures")
    boundaries, contracts["corpus-boundary-fixtures"], _ = load_boundary_fixtures(root, feature_policy["boundary_manifest"])
    boundary_id = content_id({"manifest": content_id(boundaries), "generator_sha256": digest(local_file(root, BOUNDARY_GENERATOR))})
    scenarios = _document(root, suite["draft_cases"], "bmk.case-catalog/1", contracts["case-catalog"])
    by_atom = {}
    for case in _keyed(scenarios["cases"], "id").values():
        for fixture in case["development_fixtures"]:
            require(fixture in fixtures["objects"], f"unknown fixture in draft case: {fixture}")
        for atom in case["atoms"]:
            by_atom.setdefault(atom, []).append(case["id"])
    groups = _keyed(required["groups"], "id")
    atoms = [atom for group in groups.values() for atom in group["atoms"]]
    require(len(set(atoms)) == len(atoms) and set(atoms) == required["semantics"].keys() == by_atom.keys(),
            "display groups, atomic requirement semantics and draft cases do not form a closed scope")
    numbers = suite["selections"]
    require(len(numbers) == len(set(numbers)) and set(numbers) == selections.keys() == native.keys(),
            "suite/source/native-inventory selection coverage differs")
    expected = suite["expected_counts"]
    counts = {"selections": len(numbers), "groups": len(groups), "atomic_requirements": len(atoms),
              "display_cells": len(numbers) * len(groups), "atomic_relations": len(numbers) * len(atoms)}
    require(counts == expected, "suite denominator disagrees with expected counts")
    bindings = {"suite": content_id(suite), "plugin_catalog": content_id(discover(root)), "requirements": content_id(required),
                "native_inventory": content_id(inventory), "fixture_manifest": content_id(fixtures),
                "real_corpus": corpus["corpus_id"], "corpus_feature_policy": content_id(feature_policy),
                "corpus_boundary_fixtures": boundary_id,
                "draft_cases": content_id(scenarios), "sources": source_check["sources_lock_id"],
                "contract_schemas": content_id({name: contract.document_id for name, contract in contracts.items()})}
    scope_id = content_id(bindings)
    rows, display = [], []
    for number in numbers:
        selected = selections[number]
        source = source_check["sources"][selected["source_id"]]
        native_row = native[number]
        require(native_row["selection_id"] == selected["selection_id"] and
                native_row["target"] == selected["target"] and
                native_row["archive_sha256"] == source["archive"]["sha256"],
                f"native inventory/source binding mismatch: {number}")
        for group, definition in groups.items():
            slots = []
            for atom in definition["atoms"]:
                slot_id = content_id([scope_id, selected["selection_id"], atom])
                slots.append(slot_id)
                rows.append({"slot_id": slot_id, "selection": number,
                             "selection_id": selected["selection_id"], "group": group,
                             "requirement": atom, "draft_cases": by_atom[atom], "status": "not_run",
                             "reasons": ["m0_suite_contract_not_final", "no_qualified_method_binding"]})
            display.append({"selection": number, "group": group, "slots": slots, "status": "not_run"})
    body = {"schema": "bmk.plan/1", "planner_protocol": "m0-scope-planner/2", "scope_id": scope_id,
            "suite_id": request.suite, "suite_state": suite["state"], "target_stage": suite["stage"],
            "runnable": False, "bindings": bindings, "policies": suite["policies"], "corpus": corpus,
            "resolved_execution": {"max_validation_workers": request.max_workers,
                                   "performance_candidates_concurrent": False},
            "coverage": {**counts, "executed": 0, "qualified": 0,
                         "unverified_atomic_relations": len(rows)},
            "estimates": {"included_distinct_fixture_source_bytes": fixture_bytes,
                          "full_corpus_bytes": None, "estimated_peak_memory_bytes": None,
                          "estimated_peak_disk_bytes": None,
                          "missing_estimates_reason": "production_cases_and_method_bounds_not_frozen"},
            "selection_rows": [selections[number] for number in numbers],
            "display_groups": list(groups.values()), "atomic_semantics": required["semantics"],
            "draft_cases": scenarios["cases"], "display_cells": display, "required_slots": rows}
    document = {**body, "plan_content_id": content_id(body)}
    contracts["matrix"].validate(document, "generated plan")
    return PlanResult(document)


# The development execution API shares exactly the same application code as bmk.
from .planner.smoke import SmokePlanRequest, plan_smoke  # noqa: E402,F401
from .application.smoke import report_smoke, run_smoke  # noqa: E402,F401
from .application.restore import audit_smoke_restore  # noqa: E402,F401
from .planner.native import NativePlanRequest, plan_native  # noqa: E402,F401
from .planner.native_requirements import plan_native_requirements  # noqa: E402,F401
from .planner.native_admission import plan_native_admission  # noqa: E402,F401
from .planner.native_corpus import plan_native_corpus, verify_native_corpus_plan  # noqa: E402,F401
from .application.native import report_native, run_native  # noqa: E402,F401

from .planner.comparison import plan_comparison  # noqa: E402,F401

from .planner.tv import plan_tv  # noqa: E402,F401
from .application.tv import report_tv, restore_tv, run_tv  # noqa: E402,F401

from .planner.batch_execution import plan_batch_execution  # noqa: E402,F401
from .application.batch_execution import audit_batch_execution, report_batch_execution, run_batch_execution  # noqa: E402,F401

from .planner.timing import TimingPlanRequest, plan_timing  # noqa: E402,F401
from .planner.m2_real_corpus import M2RealCorpusPlanRequest, plan_m2_real_corpus  # noqa: E402,F401
from .application.m2_real_corpus_acceptance import audit_m2_real_corpus  # noqa: E402,F401
from .planner.m3_real_corpus import M3RealCorpusPlanRequest, check_m3_real_corpus_plan, plan_m3_real_corpus  # noqa: E402,F401
def run_m3_real_corpus(root, plan, results, **preflight):
    """Dispatch only the explicit versioned execution contract to the new engine."""
    from .planner.m3_in_run_measurement_v2 import SCHEMA as MEASUREMENT_V2

    from .planner.m3_in_run_measurement_v3 import SCHEMA as MEASUREMENT_V3

    from .planner.m3_in_run_measurement_v4 import SCHEMA as MEASUREMENT_V4
    from .planner.m3_in_run_measurement_v5 import SCHEMA as MEASUREMENT_V5
    from .planner.m3_in_run_measurement_v6 import SCHEMA as MEASUREMENT_V6
    from .planner.m3_in_run_measurement_v7 import SCHEMA as MEASUREMENT_V7
    from .planner.m3_in_run_measurement_v8 import SCHEMA as MEASUREMENT_V8

    from .planner.m3_in_run_measurement_v9 import SCHEMA as MEASUREMENT_V9

    from .planner.m3_in_run_measurement_v10 import SCHEMA as MEASUREMENT_V10

    from .planner.m3_in_run_measurement_v11 import SCHEMA as MEASUREMENT_V11

    from .planner.m3_in_run_measurement_v12 import SCHEMA as MEASUREMENT_V12

    from .planner.m3_in_run_measurement_v13 import SCHEMA as MEASUREMENT_V13

    from .planner.m3_in_run_measurement_v14 import SCHEMA as MEASUREMENT_V14

    schema = plan.get('measurement', {}).get('schema')
    if schema == MEASUREMENT_V14:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_in_run_corad_pipeline import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V13:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v13 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V12:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v12 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V11:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v11 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V10:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v10 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V9:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v9 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V8:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v8 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V7:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v7 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V6:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v6 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V5:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_primary_measurement_v5 import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if schema == MEASUREMENT_V4:
        from .application.m3_real_corpus_primary import run_m3_real_corpus as execute
        from .application.m3_in_run_gorilla import observe
        return execute(root, plan, results, observer=observe, **preflight)
    if 'corad_specialist_amendment' in plan:
        from .application.m3_real_corpus_amended import run_m3_real_corpus as execute
    elif schema == MEASUREMENT_V3:
        from .application.m3_real_corpus_measured import run_m3_real_corpus as execute
    elif schema == MEASUREMENT_V2:
        from .application.m3_real_corpus_execution_v4 import run_m3_real_corpus as execute
    elif 'measurement' in plan:
        from .application.m3_real_corpus_execution_v3 import run_m3_real_corpus as execute
    elif 'pbepla_repair' in plan.get('build', {}):
        from .application.m3_real_corpus_execution_v2 import run_m3_real_corpus as execute
    else:
        from .application.m3_real_corpus_execution import run_m3_real_corpus as execute
    return execute(root, plan, results, **preflight)
from .planner.m3_input_switch import plan_input_switch as plan_m3_input_switch  # noqa: E402,F401
from .application.m3_intmult_audit import audit_m3_intmult_run  # noqa: E402,F401
from .application.timing import report_timing, run_timing  # noqa: E402,F401
from .analysis.timing_repeat import compare_timing_repeats  # noqa: E402,F401

from .application.profiling import plan_profile, report_profile, run_profile  # noqa: E402,F401

from .planner.service_scope import verify_service_plan  # noqa: E402,F401
