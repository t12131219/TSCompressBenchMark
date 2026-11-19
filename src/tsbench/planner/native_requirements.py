"""Compile the closed first-batch route obligations, without granting qualification."""
from pathlib import Path

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..contracts import load_contract
from .alp import plan_alp
from .corad_inference import plan_corad_inference
from .corad_training import plan_corad_training, retained_paths as corad_training_retained_paths
from .gorilla import plan_gorilla
from .huff0 import plan_huff0, retained_paths as huff0_retained_paths
from .lzbench import plan_lzbench
from .method_boundaries import plan_boundary_cases
from .native_conditions import freeze_conditions
from .pbepla_progressive import plan_pbepla_progressive
from .pcodec import plan_pcodec, SOURCE as PCODEC_SOURCE
from .selfstar import plan_selfstar, retained_paths as selfstar_retained_paths
from .sprintz import plan_sprintz
from .titchy_access import plan_titchy_access
from .titchy_native import plan_titchy_native
from .zfp import plan_zfp, retained_paths as zfp_retained_paths

CONTRACT = "configs/suites/m3_first_batch_native_v1/contract.json"


def plan_native_requirements(root: Path, *, scope: dict | None = None, boundary_cases: dict | None = None,
                             titchy_access: dict | None = None, pbepla: dict | None = None,
                             corad: dict | None = None, gorilla: dict | None = None, alp: dict | None = None,
                             lzbench: dict | None = None, pcodec: dict | None = None,
                             sprintz: dict | None = None, titchy_native: dict | None = None,
                             zfp: dict | None = None, huff0: dict | None = None, selfstar: dict | None = None,
                             corad_training: dict | None = None) -> dict:
    # Import late: the public API also exports this planner.
    from ..api import PlanRequest, plan

    doc = load_json(local_file(root, CONTRACT))
    schema = load_contract(root, "native-requirements")
    schema.validate(doc, CONTRACT)
    if scope is None:
        scope = plan(root, PlanRequest(suite=doc["scope_suite"])).document
    require(scope["suite_id"] == doc["scope_suite"], "native requirements and service scope disagree")
    registry = load_json(local_file(root, "configs/suites/registry.json"))
    suite = load_json(local_file(root, registry["suites"][doc["scope_suite"]]))
    inventory = load_json(local_file(root, suite["native_inventory"]))
    require(content_id(inventory) == scope["bindings"]["native_inventory"], "native inventory differs from the service scope")
    native = {(e["selection"], o["route"]): (e, o) for e in inventory["entries"] for o in e["operations"]}
    routes = {(r["selection"], r["route"]): r for r in doc["groups"]}
    expected = {"selections": len({k[0] for k in native}), "routes": len(native)}
    require(sum(len(e["operations"]) for e in inventory["entries"]) == len(native) and
            len(routes) == len(doc["groups"]) and routes.keys() == native.keys() and expected == doc["expected"],
            "native requirement route closure differs from frozen inventory")
    if boundary_cases is None:
        boundary_cases, _ = plan_boundary_cases(root)
    if titchy_access is None or titchy_native is None:
        access, titchy_cfg, titchy_source = plan_titchy_access(root)
        if titchy_access is None:
            titchy_access = access
        if titchy_native is None:
            titchy_native = plan_titchy_native(titchy_access, titchy_cfg, titchy_source)
    require(titchy_native["access_bundle_id"] == titchy_access["bundle_id"], "Titchy plan bindings differ")
    if pbepla is None:
        pbepla, _, _ = plan_pbepla_progressive(root)
    if corad is None:
        corad, _, _, _ = plan_corad_inference(root)
    if corad_training is None:
        corad_training, _ = plan_corad_training(root)
    require(corad_training['data']['evaluation']['values']['sha256'] == corad['input']['sha256'] and
            corad_training['data']['evaluation']['windows'] == corad['window'],
            'CORAD training evaluation and inference held-out input differ')
    if gorilla is None:
        gorilla, _ = plan_gorilla(root)
    if alp is None:
        alp, _ = plan_alp(root)
    if lzbench is None:
        lzbench = plan_lzbench(root)
    if pcodec is None:
        pcodec, _ = plan_pcodec(root)
    if sprintz is None:
        sprintz = plan_sprintz()
    if zfp is None:
        zfp, _ = plan_zfp(root)
    if huff0 is None:
        huff0, _ = plan_huff0(root)
    if selfstar is None:
        selfstar, _ = plan_selfstar(root)
    bound_groups = {}
    bound_case_count = 0
    for label, by_name, bindings in (
        ("method boundary", {r["row"]["case"]: r for r in boundary_cases["cases"]}, doc["boundary_contracts"]),
        ("Titchy access", {r["name"]: r for r in titchy_access["cases"]}, doc["titchy_access_contracts"]),
        ("Titchy native", {r["name"]: r for r in titchy_native["cases"]}, doc["titchy_native_contracts"]),
        ("PBEPLA", {r["name"]: r for r in pbepla["cases"]}, doc["pbepla_contracts"]),
        ("CORAD inference", {r["name"]: r for r in corad["cases"]}, doc["corad_contracts"]),
        ("CORAD training", {r["name"]: r for r in corad_training["cases"]}, doc["corad_training_contracts"]),
        ("Gorilla", {r["name"]: r for r in gorilla["cases"]}, doc["gorilla_contracts"]),
        ("ALP", {r["name"]: r for r in alp["cases"]}, doc["alp_contracts"]),
        ("lzbench", {r["name"]: r for r in lzbench["cases"]}, doc["lzbench_contracts"]),
        ("pcodec", {r["name"]: r for r in pcodec["cases"]}, doc["pcodec_contracts"]),
        ("Sprintz", {r["name"]: r for r in sprintz["cases"]}, doc["sprintz_contracts"]),
        ("ZFP", {r["name"]: r for r in zfp["cases"]}, doc["zfp_contracts"]),
        ("Huff0", {r["name"]: r for r in huff0["cases"]}, doc["huff0_contracts"]),
        ("SElf*", {r["name"]: r for r in selfstar["cases"]}, doc["selfstar_contracts"]),
    ):
        used, seen_groups = set(), set()
        for binding in bindings:
            k = binding["selection"], binding["route"]
            require(k in routes and k not in seen_groups, "unknown or duplicate case binding group")
            seen_groups.add(k)
            bound = bound_groups.setdefault(k, {})
            for check, names in binding["checks"].items():
                require(check in routes[k]["required"] and check not in bound,
                        f"case binds undeclared required check or overlaps a binding: {k}/{check}")
                require(all(n in by_name and (by_name[n]["selection"], by_name[n]["route"]) == k
                            and by_name[n].get("check", check) == check for n in names),
                        f"case binding refers to unknown or mismatched route: {k}/{check}")
                require(set(names).isdisjoint(used), f"{label} case bound more than once: {k}/{check}")
                used.update(names)
                bound[check] = [by_name[n]["case_id"] for n in names]
        require(used == by_name.keys(), f"not all {label} cases are bound")
        bound_case_count += len(used)
    groups = []
    frozen_count = total = conditional = excluded = 0
    for k, row in routes.items():
        entry, op = native[k]
        require(op["qualification"] == "not_run", f"inventory cannot grant qualification: {k}")
        conditions = {x["require"] for x in row["conditional"]}
        exclusions = {x["claim"] for x in row["out_of_scope"]}
        requires = set(row["required"])
        require(len(conditions) == len(row["conditional"]) and len(exclusions) == len(row["out_of_scope"]) and
                len(requires | conditions | exclusions) == len(requires) + len(conditions) + len(exclusions),
                f"ambiguous required, conditional or excluded checks for {k}")
        bound = bound_groups.get(k, {})
        frozen_count += len(bound)
        total += len(requires)
        conditional += len(conditions)
        excluded += len(exclusions)
        group = {**row, "selection_id": entry["selection_id"], "archive_sha256": entry["archive_sha256"],
                 "native_target": entry["target"], "source_member": op["source_member"],
                 "native_entry_tokens": op["declaration_tokens"], "qualification": "not_run",
                 "required": [{"check": c, "definition_state": "case_input_bound_development_only" if c in bound
                               else "missing_case_and_validator_binding", "cases": bound.get(c, [])} for c in row["required"]],
                 "conditional": [{**item, "resolution": "requires_build_and_workload_evidence"} for item in row["conditional"]],
                 "open": ["formal_case_drivers_and_build_bindings", "resource_and_retention_closure"]}
        if row["quality"] in {"per_case_absolute_error", "observed_only_pending_quality_budget", "model_solver_oracle"}:
            group["open"].append("frozen_original_domain_budget_or_solver_rule")
        if row["protocol"] not in {"batch", "batch_parallel", "model_batch", "model_training"}:
            group["open"].append("service_completion_work_and_access_limits")
        groups.append(group)
    coverage = {**expected, "required_checks": total, "checks_with_bound_development_cases": frozen_count,
                "checks_without_case_binding": total - frozen_count, "conditional_checks": conditional,
                "explicitly_out_of_scope_claims": excluded, "bound_development_cases": bound_case_count,
                "qualified_routes": 0}
    conditional_plan = freeze_conditions(groups,{'alp':alp,'zfp':zfp,'lzbench':lzbench,'huff0':huff0})
    cases = boundary_cases["cases"]
    positive = sum(x["artifact_basename"] is not None for x in cases)
    lzbench_inputs = {x['input']['sha256']:x['input']['bytes'] for x in lzbench['baseline']}
    for session in lzbench['sessions'].values():
        lzbench_inputs.update({x['sha256']:x['bytes'] for x in session['inputs'].values()})
    dictionary = lzbench['dictionary']
    # Count the source samples once, not their concatenated or repeated views.
    for sample in (*dictionary['training_samples'], *dictionary['held_out_samples'],
                   *(spec['input'] for spec in lzbench['workers'].values()),lzbench['xz_baseline']['oversize']):
        lzbench_inputs[sample['sha256']] = sample['bytes']
    lzbench_bytes = sum(lzbench_inputs.values())
    pcodec_inputs = (*pcodec['batch'][PCODEC_SOURCE],*pcodec['intmult']['frames'],*pcodec['intmult']['rejected'])
    pcodec_bytes = sum({r['plain']['sha256']:r['plain']['bytes'] for r in pcodec_inputs}.values())
    sprintz_inputs = {r['original']['sha256']: r['original']['bytes'] for r in sprintz['shapes']}
    sprintz_bytes = sum(sprintz_inputs.values())
    sprintz_frame_bound = sum((32 + 4*r['message_limit_bytes']) * (2 if r['worker_frame'] else 1) +
                              (32 + len(canonical_bytes(sprintz['worker_schema'])) if r['worker_frame'] else 0)
                              for r in sprintz['shapes'])
    titchy_fixture_bytes = sum(r['count']*r['bits_per_sample']//8 for r in titchy_native['batch'] if 'window' not in r)
    zfp_bytes = (zfp['weather']['bytes'] + sum(r['input']['bytes'] for r in zfp['batch'] if 'window' not in r) +
                 sum(r['input']['bytes'] for r in zfp['fields'] if r['id'] != 'rate-tail') + 8*zfp['array']['shape'][0])
    huff0_inputs = [r['input'] for r in huff0['fec1']]
    for profile in huff0['etb1']:
        huff0_inputs.append(profile['training'])
        if profile['profile'] == 'synthetic':
            huff0_inputs.extend(r['input'] for r in profile['blocks'])
    huff0_bytes = sum({r['sha256']:r['bytes'] for r in huff0_inputs}.values())
    selfstar_bytes = sum({r['input']['sha256']:r['input']['bytes']
                          for r in (*selfstar['objects'],*selfstar['limits'])}.values())
    corad_extra_bytes = corad_training['data']['train']['values']['bytes'] + sum(
        v['timestamps']['bytes'] for v in corad_training['data'].values())
    body = {"schema": "bmk.native-requirements-plan/1", "target_stage": "M3", "definition_stage": "M0",
            "runnable": False, "qualification_granted": False, "policies": doc["policies"], "coverage": coverage,
            "conditional_plan": conditional_plan,
            "bindings": {"contract_id": content_id(doc), "schema_id": schema.document_id,
                         "scope_plan_id": scope["plan_content_id"], "native_inventory_id": content_id(inventory),
                         "sources_lock_id": scope["bindings"]["sources"], "boundary_bundle_id": boundary_cases["bundle_id"],
                         "titchy_access_bundle_id": titchy_access["bundle_id"],
                         "titchy_native_bundle_id": titchy_native["bundle_id"], "pbepla_bundle_id": pbepla["bundle_id"],
                         "corad_inference_bundle_id": corad["bundle_id"], "corad_training_bundle_id": corad_training["bundle_id"],
                         "gorilla_bundle_id": gorilla["bundle_id"],
                         "alp_bundle_id": alp["bundle_id"], "lzbench_bundle_id": lzbench["bundle_id"],
                         "pcodec_bundle_id": pcodec["bundle_id"], "sprintz_bundle_id": sprintz["bundle_id"],
                         "zfp_bundle_id": zfp["bundle_id"], "huff0_bundle_id": huff0["bundle_id"],
                         "selfstar_bundle_id": selfstar["bundle_id"]},
            "estimates": {"pbepla_retained_word_bytes": sum(s["word_bytes"] for s in pbepla["inputs"]) +
                          8 * pbepla["failure_policy"]["boundary"][0]["count"],
                          "pbepla_retained_frame_upper_sum_bytes": pbepla["retention"]["max_frame_bytes"] *
                          (sum(len(s["frame_paths"]) for s in pbepla["inputs"]) + 3),
                          "titchy_shared_input_bytes": titchy_access["cases"][0]["input_bytes"],
                          "titchy_generated_fixture_bytes": titchy_fixture_bytes,
                          "titchy_stream_archive_max_bytes": titchy_native["stream"]["max_artifact_bytes"],
                          "titchy_shared_backing_max_bytes": titchy_access["cases"][1]["criteria"]["byte_limits"]["max_backing_bytes"],
                          "corad_shared_input_bytes": corad["input"]["bytes"],
                          "corad_retained_calibration_bytes": corad["quality_policy"]["calibration"]["bytes"],
                          "corad_retained_frame_upper_sum_bytes": sum(r["max_frame_bytes"] for r in corad["frames"]),
                          "corad_extra_training_and_timestamp_bytes": corad_extra_bytes,
                          "corad_training_retention_upper_sum_bytes": len(corad_training_retained_paths(corad_training)) *
                          corad_training['policy']['capacity_bytes_per_artifact'],
                          "gorilla_distinct_tv_input_bytes": sum(16 * f["rows"] for f in gorilla["fixtures"]),
                          "alp_distinct_input_bytes": sum(f["input_bytes"] for f in alp["fixtures"]),
                          "lzbench_distinct_input_bytes": lzbench_bytes,
                          "pcodec_distinct_input_bytes": pcodec_bytes,
                          "sprintz_distinct_input_bytes": sprintz_bytes,
                          "zfp_distinct_input_bytes": zfp_bytes,
                          "zfp_retained_artifact_upper_sum_bytes": len(zfp_retained_paths(zfp))*zfp["data_artifact_max_bytes"],
                          "huff0_distinct_input_bytes": huff0_bytes,
                          "huff0_retained_artifact_upper_sum_bytes": len(huff0_retained_paths(huff0))*huff0["data_artifact_max_bytes"],
                          "selfstar_distinct_input_bytes": selfstar_bytes,
                          "selfstar_retained_artifact_upper_sum_bytes": len(selfstar_retained_paths(selfstar))*selfstar["data_artifact_max_bytes"],
                          "sprintz_retained_frame_upper_sum_bytes": sprintz_frame_bound,
                          "bound_cases_total_logical_input_bytes": sum(x["row"]["input_bytes"] for x in cases) +
                          titchy_access["cases"][0]["input_bytes"] + titchy_fixture_bytes +
                          sum(8 * s["count"] for s in pbepla["inputs"] + pbepla["failure_policy"]["boundary"]) + 24 +
                          corad["input"]["bytes"] + corad_extra_bytes +
                          sum(16 * f["rows"] for f in gorilla["fixtures"]) + sum(f["input_bytes"] for f in alp["fixtures"]) +
                          lzbench_bytes + pcodec_bytes + sprintz_bytes + zfp_bytes + huff0_bytes + selfstar_bytes,
                          "bound_cases_max_frame_bytes": boundary_cases["case_policy"]["max_frame_bytes"],
                          "bound_cases_frame_upper_sum_bytes": positive * boundary_cases["case_policy"]["max_frame_bytes"],
                          "full_suite_peak_memory_bytes": None, "full_suite_peak_disk_bytes": None,
                          "missing_estimates_reason": "unbound_formal_cases_and_resources"},
            "routes": groups, "bound_development_cases": boundary_cases, "titchy_access_cases": titchy_access,
            "pbepla_cases": pbepla, "corad_inference_cases": corad, "corad_training_cases": corad_training,
            "gorilla_cases": gorilla, "alp_cases": alp,
            "lzbench_cases": lzbench, "pcodec_cases": pcodec, "sprintz_cases": sprintz, "titchy_native_cases": titchy_native,
            "zfp_cases": zfp, "huff0_cases": huff0, "selfstar_cases": selfstar}
    return {**body, "plan_content_id": content_id(body)}
