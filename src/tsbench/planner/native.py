"""Bind the complete, bounded M0 native *preflight*, not a qualification plan."""
from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from ..assets import ContractError, content_id, digest, load_json, local_file, parse_json, relative_parts, require
from ..build.environment import check_tsbench
from ..contracts import load_contract
from .alp import plan_alp, retained_paths as alp_retained_paths
from .corad_inference import plan_corad_inference, retained_paths as corad_retained_paths
from .corad_training import plan_corad_training, retained_paths as corad_training_retained_paths
from .frame_batches import plan_frame_batches, retained_paths as batch_retained_paths
from .gorilla import plan_gorilla, retained_paths as gorilla_retained_paths
from .huff0 import plan_huff0, retained_paths as huff0_retained_paths
from .huff0_portable import bind_portable_control
from .lzbench import plan_lzbench, retained_paths as lzbench_retained_paths
from .measurement import measurement_policy
from .method_boundaries import plan_boundary_cases
from .native_admission import compile_native_admission
from .native_requirements import plan_native_requirements
from .pcodec import plan_pcodec
from .pbepla_progressive import plan_pbepla_progressive, retained_paths
from .selfstar import plan_selfstar, retained_paths as selfstar_retained_paths
from .sprintz import plan_sprintz, retained_paths as sprintz_retained_paths
from .titchy_access import plan_titchy_access
from .titchy_native import plan_titchy_native, retained_paths as titchy_retained_paths
from .zfp import plan_zfp, retained_paths as zfp_retained_paths

SUITE = "configs/suites/m0_native_candidate_v1/suite.json"
PLAN_SCHEMA = "bmk.native-preflight-plan/1"


@dataclass(frozen=True, slots=True)
class NativePlanRequest:
    build_dir: Path
    huff0_portable_build: Path | None = None


def _file(base: Path, relative: str) -> dict:
    path = local_file(base, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def _by_name(rows, key):
    result = {}
    for row in rows:
        name = row[key]
        require(name not in result, f"duplicate {key}: {name}")
        result[name] = row
    return result


def _ctest(build: Path) -> dict:
    exe = shutil.which("ctest", path=os.defpath)
    require(exe is not None, "system ctest is required for configured test discovery")
    try:
        result = subprocess.run([exe, "--test-dir", str(build), "--show-only=json-v1"], check=False,
                                capture_output=True, timeout=30, env={"LC_ALL": "C", "PATH": os.defpath})
    except subprocess.TimeoutExpired as exc:
        raise ContractError("CTest discovery exceeded 30 seconds") from exc
    require(result.returncode == 0, f"CTest discovery failed: {result.stderr.decode(errors='replace')}")
    doc = parse_json(result.stdout.decode("utf-8"), "CTest discovery")
    require(doc.get("kind") == "ctestInfo" and doc.get("version", {}).get("major") == 1,
            "unknown CTest discovery protocol")
    return _by_name(doc["tests"], "name")


def _resolve_groups(inventory: dict, suite: dict, declared: dict) -> list[dict]:
    rows = _by_name(inventory["entries"], "selection")
    bindings = _by_name(suite["groups"], "selection")
    require(rows.keys() == bindings.keys(), "preflight selection closure differs from native inventory")
    groups = []
    for number, row in rows.items():
        binding = bindings[number]
        ops = _by_name(row["operations"], "route")
        require(set(binding["routes"]) == ops.keys(), f"preflight route closure differs for selection {number}")
        test = declared.get(binding["test"])
        require(test is not None and test.get("evidence"), f"native routes require a test with evidence: {number}")
        for route, op in ops.items():
            require(op["qualification"] == "not_run", "preflight cannot inherit qualification")
            groups.append({"selection": number, "selection_id": row["selection_id"], "archive_sha256": row["archive_sha256"],
                           "target": row["target"], "operation": op, "test": test["name"]})
    return groups


def _resolve_test(spec, configured, root, build, python, assets):
    name = spec["name"]
    properties = _by_name(configured["properties"], "name")
    require(properties.keys() <= {"LABELS", "WORKING_DIRECTORY", "TIMEOUT", "SKIP_RETURN_CODE"},
            f"unsupported CTest execution properties: {name}")
    working = Path(properties["WORKING_DIRECTORY"]["value"])
    require(working.is_absolute() and working.resolve(strict=True).is_relative_to(build),
            f"unexpected CTest working directory: {name}")
    timeout = properties.get("TIMEOUT", {}).get("value", 30)
    require(type(timeout) in (int, float) and int(timeout) == timeout and 0 < timeout <= 180,
            f"invalid CTest timeout: {name}")
    skip = properties.get("SKIP_RETURN_CODE", {}).get("value")
    require(skip is None or type(skip) is int and 1 <= skip <= 125, f"invalid CTest skip return code: {name}")
    output = spec.get("output_arg")
    evidence = spec.get("evidence", [])
    binary = spec.get("binary_evidence", [])
    require(not (set(evidence) & set(binary)) and (not binary or evidence), f"inconsistent binary evidence: {name}")
    for path in (*evidence, *binary):
        parts = relative_parts(path)
        if '{run_id}' in parts:
            require(path in evidence and len(parts)==3 and parts[0]==output and parts[1]=='{run_id}' and
                    parts.count('{run_id}')==1, f'invalid nested diagnostic evidence contract: {name}')
    smoke = spec.get("smoke_export", False)
    require(not (output and smoke) and (bool(evidence) == bool(output or smoke)),
            f"inconsistent evidence contract: {name}")
    if output or smoke:
        base = output or "smoke"
        sibling = Path(base).parent if output and output in evidence else None
        require(all(path == base or path.startswith(base + "/") for path in evidence) and
                all(path.startswith(base + "/") or Path(path).parent == sibling for path in binary),
                f"expected evidence outside test output: {name}")
    command, seen_output = [], False
    for i, value in enumerate(configured.get("command", [])):
        require(isinstance(value, str) and bool(value), f"invalid CTest argument: {name}")
        path = Path(value)
        if not path.is_absolute():
            require(i > 0 and re.fullmatch(r"[-a-zA-Z0-9_.]+", value), f"unbound CTest argument: {name}")
            command.append({"literal": value})
        elif i == 0 and path.resolve() == python:
            command.append({"python": True})
        elif output and path == build / output:
            require(i > 0 and not seen_output, f"ambiguous CTest evidence destination: {name}")
            command.append({"output": output})
            seen_output = True
        else:
            resolved = path.resolve(strict=True)
            name_of_root, base = next(((label, base) for label, base in (("build", build), ("project", root))
                                       if resolved.is_relative_to(base) and path.is_relative_to(base)), (None, None))
            require(base is not None, f"CTest input outside frozen roots: {name}: {value}")
            relative = path.relative_to(base).as_posix()
            key = f"{name_of_root}:{relative}"
            if key not in assets:
                assets[key] = {"root": name_of_root, **_file(base, relative)}
            command.append({"asset": key})
    require(command and ("python" in command[0] or command[0].get("asset", "").startswith("build:")),
            f"CTest executable missing or unbound: {name}")
    require(not output or seen_output, f"CTest evidence argument is not bound: {name}")
    if "python" in command[0]:
        require(len(command) > 3 and command[1:3] == [{"literal": "-I"}, {"literal": "-B"}] and
                command[3].get("asset", "").startswith("project:tests/"), f"unbound Python test driver: {name}")
    body = {"test": name, "command": command, "timeout_seconds": int(timeout), "skip_returncode": skip,
            "evidence": evidence, "smoke_export": smoke}
    if binary:
        body["binary_evidence"] = binary
    return {"slot_id": content_id(body), **body}


def _project_inputs(root):
    # Includes transitive Python helpers, case contracts/fixtures and build recipes,
    # not caches, old results, raw intake duplicates or historical output paths.
    paths = {"bmk", "CMakeLists.txt", "pyproject.toml"}
    for directory in ("src", "tests", "schemas", "configs", "catalog", "cmake", "include", "native", "plugins", "tools",
                      "environment", "datasets/fixtures", "datasets/manifests", "datasets/generators",
                      "assets/models", "assets/manifests"):
        paths.update(p.relative_to(root).as_posix() for p in (root / directory).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts and not p.name.startswith(".") and
                     p.suffix not in (".pyc", ".pyo"))
    return [_file(root, p) for p in sorted(paths)]


def plan_native(root: Path, request: NativePlanRequest) -> dict:
    # Lazy import because this planner is itself re-exported by the common API.
    from ..api import PlanRequest, plan
    from ..corpus import MANIFEST_V1, check_corpus

    root, build = root.resolve(strict=True), request.build_dir.resolve(strict=True)
    require(sys.platform == "linux" and platform.machine() == "x86_64", "native preflight requires Linux x86_64")
    require(build != root and build.is_dir(), "provide a configured native build directory")
    environment_id = check_tsbench(root)
    python = Path(sys.executable).resolve(strict=True)
    contract = load_contract(root, "native-preflight-suite")
    suite = load_json(local_file(root, SUITE))
    contract.validate(suite, SUITE)
    scope = plan(root, PlanRequest(suite=suite["scope_suite"])).document
    scope_suite = load_json(local_file(root, f'configs/suites/{suite["scope_suite"]}/suite.json'))
    inventory = load_json(local_file(root, scope_suite["native_inventory"]))
    declared = _by_name(suite["tests"], "name")
    groups = _resolve_groups(inventory, suite, declared)
    configured = _ctest(build)
    require(configured.keys() == declared.keys(),
            f"configured test closure differs: missing {sorted(declared.keys()-configured.keys())}; "
            f"unexpected {sorted(configured.keys()-declared.keys())}")
    assets = {}
    slots = [_resolve_test(s, configured[s["name"]], root, build, python, assets) for s in suite["tests"]]
    require(len({s["slot_id"] for s in slots}) == len(slots), "duplicate native preflight slots")
    boundaries, _ = plan_boundary_cases(root)
    titchy, titchy_cfg, titchy_source = plan_titchy_access(root)
    titchy_native = plan_titchy_native(titchy, titchy_cfg, titchy_source)
    pbepla, _, _ = plan_pbepla_progressive(root)
    corad, _, _, _ = plan_corad_inference(root)
    corad_training, _ = plan_corad_training(root)
    calibration = corad['quality_policy']['calibration']
    require(all(calibration[k]==corad_training['data']['train']['values'][k] for k in ('sha256','bytes')) and
            calibration['windows']==corad_training['data']['train']['windows'],
            'CORAD calibration is not bound to the frozen training source')
    alp, _ = plan_alp(root)
    lzbench = plan_lzbench(root)
    pcodec, _ = plan_pcodec(root)
    [pcodec_slot] = [s for s in slots if s['test'] == pcodec['test']]
    require(pcodec_slot['evidence'] == [pcodec['evidence_path']] and
            set(pcodec_slot.get('binary_evidence',[])) == set(pcodec['binary']),'pcodec retention differs from frozen plan')
    [lzbench_slot] = [s for s in slots if s["test"] == lzbench["test"]]
    require(lzbench_slot["evidence"] == [lzbench["evidence_path"]] and
            set(lzbench_slot.get("binary_evidence", [])) == set(lzbench_retained_paths(lzbench)),
            "lzbench retention differs from frozen plan")
    [alp_slot] = [s for s in slots if s["test"] == alp["test"]]
    require(alp_slot["evidence"] == [alp["evidence_path"]] and
            set(alp_slot.get("binary_evidence", [])) == set(alp_retained_paths(alp)),
            "ALP retention differs from frozen plan")
    gorilla, _ = plan_gorilla(root)
    [gorilla_slot] = [s for s in slots if s["test"] == gorilla["test"]]
    require(gorilla_slot["evidence"] == [gorilla["evidence_path"]] and
            set(gorilla_slot.get("binary_evidence", [])) == set(gorilla_retained_paths(gorilla)),
            "Gorilla retention differs from frozen plan")
    batches = plan_frame_batches(root)
    [batch_slot] = [s for s in slots if s["test"] == batches["test"]]
    directory = Path(batches["evidence_path"]).parent
    require(batch_slot["evidence"] == [batches["evidence_path"]] and
            set(batch_slot.get("binary_evidence", [])) == {(directory / p).as_posix() for p in batch_retained_paths(batches)},
            "frame-batch retention differs from frozen plan")
    sprintz = plan_sprintz()
    [sprintz_slot] = [s for s in slots if s["test"] == sprintz["test"]]
    require(sprintz_slot["evidence"] == [sprintz["evidence_path"]] and
            set(sprintz_slot.get("binary_evidence", [])) == sprintz_retained_paths(sprintz),
            "Sprintz retention differs from frozen plan")
    zfp, _ = plan_zfp(root)
    [zfp_slot] = [s for s in slots if s["test"] == zfp["test"]]
    require(zfp_slot["evidence"] == [zfp["evidence_path"]] and
            set(zfp_slot.get("binary_evidence", [])) == zfp_retained_paths(zfp),
            "ZFP retention differs from frozen plan")
    huff0, _ = plan_huff0(root)
    [huff0_slot] = [s for s in slots if s["test"] == huff0["test"]]
    require(huff0_slot["evidence"] == [huff0["evidence_path"]] and
            set(huff0_slot.get("binary_evidence", [])) == huff0_retained_paths(huff0),
            "Huff0 retention differs from frozen plan")
    extensions = {}
    if request.huff0_portable_build is not None:
        portable = request.huff0_portable_build.resolve(strict=True)
        [archive] = {g['archive_sha256'] for g in groups if g['selection']==29}
        portable_slot, binding = bind_portable_control(root,build,portable,huff0_slot,huff0,archive,assets,_file)
        slots.append(portable_slot)
        extensions['huff0_portable_control'] = binding
    selfstar, _ = plan_selfstar(root)
    [selfstar_slot] = [s for s in slots if s["test"] == selfstar["test"]]
    require(selfstar_slot["evidence"] == [selfstar["evidence_path"]] and
            set(selfstar_slot.get("binary_evidence", [])) == selfstar_retained_paths(selfstar),
            "SElf* retention differs from frozen plan")
    requirements = plan_native_requirements(root, scope=scope, boundary_cases=boundaries, titchy_access=titchy, pbepla=pbepla,
                                             corad=corad, gorilla=gorilla, alp=alp, lzbench=lzbench, pcodec=pcodec,
                                             sprintz=sprintz, titchy_native=titchy_native, zfp=zfp, huff0=huff0,
                                             selfstar=selfstar, corad_training=corad_training)
    admission = compile_native_admission(root, requirements)
    [corad_slot] = [s for s in slots if s["test"] == corad["test"]]
    require(corad_slot["evidence"] == [corad["evidence_path"]] and
            set(corad_slot.get("binary_evidence", [])) == set(corad_retained_paths(corad)), "CORAD retention differs from frozen cases")
    [training_slot] = [s for s in slots if s["test"] == corad_training["test"]]
    require(training_slot["evidence"] == [corad_training["evidence_path"]] and
            set(training_slot.get("binary_evidence", [])) == corad_training_retained_paths(corad_training),
            "CORAD training retention differs from frozen cases")
    [bridge] = [assets[x["asset"]] for x in training_slot["command"] if "asset" in x and
                Path(assets[x["asset"]]["path"]).name == "train.py"]
    require(bridge["sha256"] == corad_training["bridge_sha256"], "CORAD configured training bridge differs from frozen source")
    [pbepla_slot] = [s for s in slots if s["test"] == pbepla["test"]]
    require(pbepla_slot["evidence"] == [pbepla["evidence_path"]] and
            set(pbepla_slot.get("binary_evidence", [])) == set(retained_paths(pbepla)), "PBEPLA retention differs from frozen cases")
    [titchy_slot] = [s for s in slots if s["test"] == titchy["test"]]
    require(titchy_slot["evidence"] == [titchy["evidence_path"]] and
            set(titchy_slot.get("binary_evidence", [])) == titchy_retained_paths(titchy_native),
            "Titchy retention differs from frozen cases")
    [boundary_slot] = [s for s in slots if s["test"] == boundaries["test"]]
    directory = Path(boundaries["evidence_path"]).parent
    require(boundaries["evidence_path"] in boundary_slot["evidence"] and
            set(boundary_slot["binary_evidence"]) == {(directory / c["artifact_basename"]).as_posix()
                                                      for c in boundaries["cases"] if c["artifact_basename"]},
            "method-boundary retention differs from frozen cases")
    body = {"schema": PLAN_SCHEMA, "suite_id": suite["id"], "target_stage": "M0", "runnable": True,
            "evidence_scope": suite["state"], "qualification_granted": False, "policies": suite["policies"],
            "bindings": {"suite_id": content_id(suite), "suite_schema_id": contract.document_id,
                         "scope_plan_id": scope["plan_content_id"], "scope_id": scope["scope_id"],
                         "corpus_v1_id": check_corpus(root, MANIFEST_V1)["corpus_id"],
                         "scope_bindings": scope["bindings"], "tsbench_environment_id": environment_id,
                         "native_requirements_plan_id": requirements["plan_content_id"], "native_admission": admission,
                         "method_boundaries": boundaries,
                         "native_conditional_plan": requirements["conditional_plan"],
                         "titchy_access": titchy, "titchy_native": titchy_native,
                         "pbepla": pbepla, "corad_inference": corad, "corad_training": corad_training,
                         "frame_batches": batches, "gorilla": gorilla, "alp": alp, "lzbench": lzbench, "pcodec": pcodec,
                         "sprintz": sprintz, "zfp": zfp, "huff0": huff0, "selfstar": selfstar,
                         "measurement_policy": measurement_policy(root),
                         "python_version": sys.version, "python_sha256": digest(python),
                         "project_inputs": _project_inputs(root), "command_inputs": assets, **extensions},
            "coverage": {"selections": len(inventory["entries"]), "native_groups": len(groups), "slots": len(slots),
                         "display_cells": scope["coverage"]["display_cells"],
                         "atomic_relations": scope["coverage"]["atomic_relations"]},
            "estimates": {"serial_probe_timeout_sum_seconds": sum(s["timeout_seconds"] for s in slots),
                          "distinct_corpus_logical_bytes": scope["corpus"]["logical_bytes"],
                          "peak_memory_bytes": None, "peak_disk_bytes": None,
                          "unestimated_reason": "development_probe_aggregate_bounds_not_measured"},
            "groups": groups, "slots": slots}
    return {**body, "plan_content_id": content_id(body)}
