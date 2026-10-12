"""Independent, no-codec checks of actual formal validator function ASTs.

Only the exact pure file/hash validator functions are compiled from the three
drivers. A minimal temporary registry supplies file references; no production
package, codec factory, ELF, model runtime, pytest or performance runner is loaded.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
DRIVER_ROOT = ROOT / "docs/audits/20261011_closure_formal_verification/formal"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(root: Path, relative: str) -> dict:
    path = root / relative
    return {"path": relative, "sha256": sha(path), "bytes": path.stat().st_size}


def json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n")


def functions(path: Path, names: set[str], namespace: dict) -> dict:
    parsed = ast.parse(path.read_text())
    nodes = [node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if {node.name for node in nodes} != names:
        raise RuntimeError("function inventory changed")
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class FixtureSourceRegistry:
    """Only supplies fixture source metadata; production identity code is not tested."""

    def __init__(self, directory: Path):
        self.directory = directory

    def get(self, source_id: str):
        if source_id != "fixture-source-id":
            raise ValueError("unexpected fixture source id")
        return json.loads((self.directory / "fixture.json").read_text())


def make_fixture(root: Path) -> tuple[dict, Path, list[dict]]:
    drivers = root / "docs/audits/20261011_closure_formal_verification/formal"
    drivers.mkdir(parents=True)
    for name in ("prepare_current_queue.py", "run_frozen_queue.py", "audit_current_formal.py"):
        (drivers / name).write_bytes((DRIVER_ROOT / name).read_bytes())
    (root / "tools").mkdir()
    (root / "tools/rebind_v32_comparison_sources.py").write_bytes((ROOT / "tools/rebind_v32_comparison_sources.py").read_bytes())
    (root / "pyproject.toml").write_text("[project]\nname = 'fixture'\n")
    for relative in ("build/native.so", "assets/model.bin", "assets/corpus.bin", "assets/runtime.so"):
        path = root / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(("UNEXECUTED_FILE_SENTINEL:" + relative).encode())
    json_write(root / "registry/algorithm_scope.json", {"registered_codecs": ["demo"]})
    json_write(root / "assets/runtime-profile.json", {"runtime": reference(root, "assets/runtime.so")})
    json_write(root / "registry/sources/fixture.json", {
        "artifact": reference(root, "build/native.so"), "model": reference(root, "assets/model.bin")})
    json_write(root / "registry/codecs/demo.json", {
        "identity": {"source_artifact_id": "fixture-source-id"},
        "adapter": {"artifact_path": "build/native.so", "runtime_profile": reference(root, "assets/runtime-profile.json")}})
    json_write(root / "registry/comparison_datasets/v32_20261010/demo.json", {
        "file": reference(root, "assets/corpus.bin")})
    for name in ("etth1", "weather"):
        json_write(root / "registry/datasets" / (name + ".json"), {"file": reference(root, "assets/corpus.bin")})
    bundle = {"contract": {"revision": "old", "decision": "KEEP"},
              "config_map": {"contract_id": "contract", "settings": {"level": 1}},
              "expected_matrix": {"contract_id": "contract", "config_map_id": "config"},
              "group": {"revision": "old", "contract_id": "contract", "config_map_id": "config",
                        "expected_matrix_id": "expected", "members": [{"method": {"name": "demo"},
                          "implementation": {"method_id": "method", "source_artifact_id": "source",
                                             "source_closure_sha256": "source-hash"},
                          "shared_code_tags": ["SOURCE_ARTIFACT:source"]}], "method_equivalence": []}}
    json_write(root / "history/base.json", bundle)
    new = copy.deepcopy(bundle)
    new["contract"]["revision"] = new["group"]["revision"] = "new"
    json_write(root / "queue/bundle.json", new)
    json_write(root / "history/protocol.json", {"kind": "QUERY", "cache": "COLD"})
    (root / "queue/protocol.json").write_bytes((root / "history/protocol.json").read_bytes())
    json_write(root / "queue/proof.json", {"preparation_driver": reference(root, str(drivers.relative_to(root) / "prepare_current_queue.py")),
                                         "base_bundle": reference(root, "history/base.json")})
    lane = {"kind": "workload", "run_set_id": "fixture", "bundle": "queue/bundle.json",
            "protocol": "queue/protocol.json", "historical_protocol": reference(root, "history/protocol.json")}
    plan = {"lanes": [lane], "receipts": [{"lane": "fixture", "base": reference(root, "history/base.json"),
                                            "bundle": reference(root, "queue/bundle.json"),
                                            "proof": reference(root, "queue/proof.json")}],
            "driver": reference(root, str(drivers.relative_to(root) / "prepare_current_queue.py"))}
    plan_path = root / "queue/release_plan.json"
    json_write(plan_path, plan)
    namespace = {"ROOT": root, "Path": Path, "sys": sys, "json": json, "hashlib": hashlib,
                 "SourceRegistry": FixtureSourceRegistry, "__file__": str(drivers / "run_frozen_queue.py")}
    projection_ns = {"copy": copy}
    functions(ROOT / "tools/rebind_v32_comparison_sources.py", {"semantic_projection"}, projection_ns)
    namespace["semantic_projection"] = projection_ns["semantic_projection"]
    functions(DRIVER_ROOT / "run_frozen_queue.py", {"ref", "preparation_inputs", "registered_inputs", "manifest"}, namespace)
    return namespace, plan_path, [lane]


def run_case(case: str, mutate, operation: str = "preparation_inputs", expected_reject: bool = True) -> dict:
    with tempfile.TemporaryDirectory(prefix="tscb-formal-gate-") as temporary:
        root = Path(temporary) / "project"
        root.mkdir()
        namespace, plan, lanes = make_fixture(root)
        before = namespace["manifest"](plan, lanes)
        mutate(root, plan, lanes)
        exception = None
        changed = False
        try:
            if operation == "registered_inputs":
                namespace[operation]()
            elif operation == "manifest":
                changed = namespace[operation](plan, lanes) != before
                if changed:
                    raise ValueError("actual frozen manifest differs; live main/audit rejects this comparison")
            else:
                namespace[operation](plan, lanes)
        except Exception as error:
            exception = {"type": type(error).__name__, "message": str(error)}
        rejected = exception is not None
        return {"case": case, "operation": operation, "expected_reject": expected_reject,
                "actually_rejected": rejected, "status": "PASS" if rejected == expected_reject else "FAIL",
                "manifest_changed": changed, "exception": exception,
                "scope": "ACTUAL_DRIVER_FUNCTION_AST_ON_MINIMAL_TEMPORARY_PROJECT_NO_CODEC_LOADING"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("retain prior evidence")
    driver_refs = [{"path": str(DRIVER_ROOT / name), "sha256": sha(DRIVER_ROOT / name)}
                   for name in ("prepare_current_queue.py", "run_frozen_queue.py", "audit_current_formal.py")]
    results = [run_case("BASELINE", lambda *_: None, expected_reject=False)]
    for name in ("prepare_current_queue.py", "run_frozen_queue.py", "audit_current_formal.py"):
        def mutate(root, plan, lanes, filename=name):
            target = root / "docs/audits/20261011_closure_formal_verification/formal" / filename
            target.write_bytes(target.read_bytes() + b"\n# independent drift\n")
        results.append(run_case("DRIVER_DRIFT:" + name, mutate, operation="manifest"))
    for case, relative in (("PROOF_BYTE_DRIFT", "queue/proof.json"), ("HISTORICAL_BASE_BYTE_DRIFT", "history/base.json")):
        results.append(run_case(case, lambda root, plan, lanes, p=relative: (root / p).write_bytes((root / p).read_bytes() + b" ")))
    def bad_sha(root, plan, lanes):
        data = json.loads(plan.read_text())
        data["receipts"][0]["proof"]["sha256"] = "0" * 64
        json_write(plan, data)
    results.append(run_case("PROOF_EXPECTED_SHA_WRONG", bad_sha))
    results.append(run_case("PROTOCOL_BYTE_DRIFT", lambda root, plan, lanes: (root / "queue/protocol.json").write_text('{"cache":"WARM"}')))
    def escape_protocol(root, plan, lanes):
        outside = root.parent / "outside-protocol.json"
        outside.write_bytes((root / "history/protocol.json").read_bytes())
        lanes[0]["protocol"] = "../outside-protocol.json"
        data = json.loads(plan.read_text());data["lanes"] = lanes;json_write(plan, data)
    results.append(run_case("PROTOCOL_RELATIVE_PATH_ESCAPE", escape_protocol, operation="manifest"))
    def escape_ref(root, plan, lanes):
        outside = root.parent / "outside-proof.json"
        outside.write_bytes((root / "queue/proof.json").read_bytes())
        data = json.loads(plan.read_text());data["receipts"][0]["proof"] = reference(root, "../outside-proof.json");json_write(plan,data)
    results.append(run_case("PREPARATION_SHA_REFERENCE_PATH_ESCAPE", escape_ref))
    for label, relative in (("NATIVE_SO", "build/native.so"), ("MODEL", "assets/model.bin"),
                            ("CORPUS", "assets/corpus.bin"), ("RUNTIME", "assets/runtime.so")):
        results.append(run_case(label + "_SHA_DRIFT", lambda root, plan, lanes, p=relative: (root / p).write_bytes(b"independent drift"),
                                operation="registered_inputs"))
    def escape_registered(root, plan, lanes):
        outside = root.parent / "outside-model.bin";outside.write_bytes((root / "assets/model.bin").read_bytes())
        target = root / "registry/sources/fixture.json";data=json.loads(target.read_text())
        data["model"] = reference(root, "../outside-model.bin");json_write(target,data)
    results.append(run_case("REGISTERED_RELATIVE_PATH_ESCAPE", escape_registered, operation="registered_inputs"))
    audit_path = DRIVER_ROOT / "audit_current_formal.py"
    history_path = DRIVER_ROOT / "history/audit_current_formal-pre-hardening.py"
    old = ast.parse(history_path.read_text());new = ast.parse(audit_path.read_text())
    old_asserts = [ast.dump(n.test, include_attributes=False) for n in ast.walk(old) if isinstance(n, ast.Assert)]
    requires = [ast.dump(n.args[0], include_attributes=False) for n in ast.walk(new)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "require" and n.args]
    require_ns = {};functions(audit_path, {"require"}, require_ns)
    require_reject = False
    try:require_ns["require"](False, "negative evidence")
    except ValueError:require_reject=True
    optimized = []
    for name in ("run_frozen_queue.py", "audit_current_formal.py"):
        node = next(n for n in ast.parse((DRIVER_ROOT / name).read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        code = "import sys\n" + ast.unparse(ast.Module(body=[node], type_ignores=[])) + "\nmain()\n"
        result = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True)
        optimized.append({"driver": name, "status": "PASS" if result.returncode != 0 and
                          "optimized Python cannot run qualification validators" in result.stderr else "FAIL",
                          "exit_code": result.returncode, "stderr": result.stderr,
                          "execution_scope": "EXACT_MAIN_AST_GUARD_RUN_IN_OPTIMIZED_INTERPRETER_NO_IMPORTS"})
    after = [{"path": x["path"], "sha256": sha(Path(x["path"]))} for x in driver_refs]
    document = {"schema_version": "tscb.formal-static-gate-review.v1", "driver": {"path":str(Path(__file__)),"sha256":sha(Path(__file__))},
                "subject_drivers": driver_refs, "subject_drivers_unchanged": driver_refs == after,
                "cases": results, "optimized_python_rejection": optimized,
                "historical_assert_count": len(old_asserts), "all_historical_assert_conditions_preserved_in_require":
                all(test in requires for test in old_asserts), "new_assert_count": sum(isinstance(n,ast.Assert) for n in ast.walk(new)),
                "require_false_rejected": require_reject, "no_production_imports": True,
                "no_codec_loaded": True, "no_pytest_or_performance": True,
                "status": "PASS" if all(x["status"]=="PASS" for x in results+optimized) and driver_refs==after else "GAPS_FOUND"}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open("x") as stream:json.dump(document,stream,indent=2,sort_keys=True);stream.write("\n")
    print(json.dumps({"status":document["status"],"case_count":len(results),"failed_cases":[x["case"] for x in results if x["status"]!="PASS"],"assert_conditions_preserved":document["all_historical_assert_conditions_preserved_in_require"]},indent=2))
    raise SystemExit(document["status"]!="PASS")


if __name__ == "__main__":
    main()
