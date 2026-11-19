"""Complete frozen schedule for the development lossless slice (not admission)."""
from dataclasses import dataclass
import ast
import hashlib
from pathlib import Path
import re
import struct

from ..assets import ContractError, canonical_bytes, content_id, digest, load_json, local_file, require, verify_asset
from ..contracts import load_contract
from ..corpus import check_corpus
from ..plugins import discover
from ..recovery import check_recovery, plan_recovery
from ..runtime import resolve_worker
from ..supervisor.resource import resource_binding
from .corpus_windows import bind_window, read_window
from .measurement import PROFILE, TIMED_SUITE, process_binding, timed
from .smoke_comparison import bind_stage_comparisons
from . import smoke_isolation as isolation

SUITE = "configs/suites/dev_lossless_smoke_v1/suite.json"
PROTOCOL = "bmk.dev-lossless-plan/2"
DEV_SUITE = "dev_lossless_smoke_v1"
STAGE_SUITE = "m1_lossless_candidate_v1"
FORMAL_SUITE = "m1_lossless_formal_v1"
STAGE_SUITES = frozenset({STAGE_SUITE, TIMED_SUITE, isolation.SUITE, FORMAL_SUITE})
STAGE_PROTOCOL = "bmk.lossless-stage-plan/1"
STAGE_PURPOSE = "m1_candidate_preflight"
FORMAL_PURPOSE = "m1_formal_execution"

def stage_purpose(suite_id: str) -> str:
    return FORMAL_PURPOSE if suite_id == FORMAL_SUITE else STAGE_PURPOSE
DTYPE = 10  # BMK_F64
NPY_LIMIT = 64 * 1024 + 2048


@dataclass(frozen=True, slots=True)
class SmokePlanRequest:
    build_lock: str
    suite: str = DEV_SUITE


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def input_schema(count: int) -> bytes:
    return canonical_bytes({"dtype": "f64", "endian": "little", "shape": [count], "role": "value"})


def fixture(root: Path, ref: dict) -> tuple[int, bytes]:
    path = verify_asset(root, ref)
    require(path.stat().st_size == ref["bytes"] <= NPY_LIMIT, "NPY source length outside smoke bound")
    content = path.read_bytes()
    require(len(content) >= 10 and content[:8] == b"\x93NUMPY\x01\x00", "only NPY v1 fixtures are supported")
    end = 10 + struct.unpack_from("<H", content, 8)[0]
    require(10 < end <= min(len(content), 2048) and content[end - 1:end] == b"\n", "invalid NPY header length")
    try:
        pairs = ast.parse(content[10:end].decode("ascii").strip(), mode="eval").body
        require(isinstance(pairs, ast.Dict) and len(pairs.keys) == 3, "invalid NPY header shape")
        header = ast.literal_eval(pairs)
    except (UnicodeError, SyntaxError, ValueError, TypeError, RecursionError) as exc:
        raise ContractError("invalid NPY header") from exc
    require(set(header) == {"descr", "fortran_order", "shape"} and header["descr"] == "<f8" and
            header["fortran_order"] is False, "only dense little-endian binary64 is supported")
    shape = header["shape"]
    require(type(shape) is tuple and len(shape) == 1 and type(shape[0]) is int and 0 <= shape[0] <= 8192 and
            len(content) - end == shape[0] * 8, "NPY length or rank mismatch")
    return shape[0], content[end:]


def _suite(root: Path, suite_id: str = DEV_SUITE) -> dict:
    require(type(suite_id) is str and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", suite_id),
            f"invalid lossless suite ID: {suite_id!r}")
    path = f"configs/suites/{suite_id}/suite.json"
    suite = load_json(local_file(root, path))
    if suite_id in STAGE_SUITES:
        load_contract(root, "lossless-stage-suite").validate(suite, path)
        _stage_denominator(suite)
    else:
        _development_suite(suite, suite_id)
    return suite


def _development_suite(suite: dict, suite_id: str) -> None:
    require(isinstance(suite, dict) and suite.keys() == {"schema", "id", "verification", "timeout_seconds_per_operation",
            "fixture_manifest", "fixtures", "methods"} and suite["schema"] == "bmk.dev-lossless-suite/1" and
            suite["id"] == suite_id and type(suite_id) is str and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", suite_id)
            and suite_id not in STAGE_SUITES and suite["verification"] == "artifact_each", "invalid smoke suite")
    require(type(suite["timeout_seconds_per_operation"]) is int and 1 <= suite["timeout_seconds_per_operation"] <= 60,
            "invalid operation timeout bound")
    require(isinstance(suite["fixtures"], list) and 1 <= len(suite["fixtures"]) <= 32 and
            all(type(x) is str and x for x in suite["fixtures"]) and len(set(suite["fixtures"])) == len(suite["fixtures"]),
            "invalid or duplicate fixtures")
    require(isinstance(suite["methods"], list) and 1 <= len(suite["methods"]) <= 32, "invalid smoke methods count")
    for method in suite["methods"]:
        require(type(method) is dict and method.keys() == {"plugin", "role", "options"} and
                isinstance(method["plugin"], str) and method["role"] in {"bytes", "value"} and
                type(method["options"]) is dict, "invalid smoke method declaration")
    require(len({m["plugin"] for m in suite["methods"]}) == len(suite["methods"]), "duplicate smoke method")


def _stage_denominator(suite: dict) -> None:
    nc, nm = len(suite["cases"]), len(suite["methods"])
    require(len({c["id"] for c in suite["cases"]}) == nc and len({m["plugin"] for m in suite["methods"]}) == nm,
            "duplicate lossless stage case or method ID")
    require(suite["expected"] == {"cases": nc, "methods": nm, "slots": nc * nm},
            "lossless stage denominator does not match declaration")


def _slots(suite: dict, inputs: dict, methods: dict, scope: str) -> list[dict]:
    stage = suite["id"] in STAGE_SUITES
    labels = [case["id"] for case in suite["cases"]] if stage else suite["fixtures"]
    return [{"slot_id": content_id([scope, label, method["plugin"]]), "input_id": label, "method_id": method["plugin"],
             "task": suite["task"] if stage else "V_to_V", "original_sha256": inputs[label]["raw_sha256"],
             "configuration_id": methods[method["plugin"]]["configuration_id"]}
            for label in labels for method in suite["methods"]]


def read_input(root: Path, source: dict) -> tuple[int, bytes]:
    kind = source.get("kind", "fixture")
    if kind == "fixture":
        return fixture(root, source["asset"])
    if kind == "empty_f64":
        return 0, b""
    require(kind == "corpus_window", "unknown input kind")
    raw = read_window(root, source["window"])
    return len(raw) // 8, raw


def _input(root: Path, source: dict) -> dict:
    n, raw = read_input(root, source)
    return {**source, "count": n, "bytes": len(raw), "raw_sha256": sha(raw),
            "schema_sha256": sha(input_schema(n)), "dtype": DTYPE}


def _estimates(suite, inputs, recovery=None):
    count = len(suite["methods"]) * len(inputs)
    result = {"distinct_input_logical_bytes": sum(a["bytes"] for a in inputs.values()),
            "all_slot_logical_input_bytes": len(suite["methods"]) * sum(a["bytes"] for a in inputs.values()),
            "max_planned_case_logical_input_bytes": max(a["bytes"] for a in inputs.values()),
            "max_worker_operations": 2 * count,
            "serialized_successful_artifacts_ceiling_bytes": count * suite["max_serialized_bytes_per_slot"],
            "peak_rss_estimate_bytes": None, "peak_disk_estimate_bytes": None,
            "unestimated_reason": "process_allocator_log_and_workspace_bounds_not_measured"}
    if recovery is not None:
        result["recovery_bundle_logical_bytes"] = sum(row["bytes"] for row in recovery["files"].values())
    return result


def verify_stage_bindings(root: Path, plan: dict) -> None:
    """Reject a stale binding before launch; missing binary/input is still a ledger outcome."""
    suite = plan["suite"]
    docs = {key: load_json(local_file(root, suite[key])) for key in ("fixture_manifest", "corpus_manifest", "direct_control")}
    binding = {"suite_schema": load_contract(root, "lossless-stage-suite").document_id,
               "fixture_manifest": content_id(docs["fixture_manifest"]), "corpus": content_id(docs["corpus_manifest"]),
               "direct_control": content_id(docs["direct_control"])}
    if suite["id"] == FORMAL_SUITE:
        receipt = load_json(local_file(root, suite["m0_receipt"]))
        require(receipt.get("stage_accepted") is True and receipt.get("qualification_granted") is False,
                "formal M1 M0 receipt is not accepted")
        binding["m0_receipt"] = {"path": suite["m0_receipt"],
                                  "sha256": digest(local_file(root, suite["m0_receipt"])),
                                  "receipt_id": receipt["receipt_id"]}
    if timed(suite):
        binding["measurement"] = process_binding(root)
        binding["resource"] = resource_binding(root)
        recovery = plan["contract_bindings"].get("recovery")
        if recovery is not None:
            # Validate the binding structurally; a vanished binary is a slot outcome.
            binding["recovery"] = recovery
        if isolation.active(suite):
            binding["isolation"] = isolation.bind(suite)
        binding["comparison"] = bind_stage_comparisons(root,suite,plan["inputs"],binding["measurement"],
                                                       recovery=recovery, isolation=binding.get("isolation"))
    require(plan["contract_bindings"] == binding, "stage contract bindings differ from frozen definitions")
    for case in suite["cases"]:
        spec, actual = case["input"], plan["inputs"][case["id"]]
        if spec["kind"] == "corpus_window":
            window = bind_window(root, suite["corpus_manifest"], binding["corpus"], spec)
            require(actual["window"] == window, f"stage window binding differs: {case['id']}")
        elif spec["kind"] == "fixture":
            require(actual["asset"] == docs["fixture_manifest"]["files"][spec["name"]], f"stage fixture differs: {case['id']}")


def plan_smoke(root: Path, request: SmokePlanRequest) -> dict:
    suite = _suite(root, request.suite)
    registry = discover(root, selected={method["plugin"] for method in suite["methods"]})
    for method in suite["methods"]:
        name = method["plugin"]
        require(name in registry, f"unknown plugin: {name}")
        require(registry[name]["enabled"], f"disabled plugin: {name}")
        manifest = registry[name]["manifest"]
        require(method["role"] in manifest["roles"], f"plugin role not declared: {name}")
        require("linear_f64_bitwise" in manifest.get("supported_tasks", []),
                f"plugin has no declared dense bitwise f64 task: {name}")
    build = load_json(local_file(root, request.build_lock))
    manifest = load_json(local_file(root, suite["fixture_manifest"]))
    require(manifest["schema"] == "bmk.fixtures/1", "unknown fixture manifest")
    inputs, methods = {}, {}
    stage = request.suite in STAGE_SUITES
    extra = {}
    if stage:
        corpus = check_corpus(root, suite["corpus_manifest"])
        controls = load_json(local_file(root, suite["direct_control"]))
        require(controls["schema"] == "bmk.direct-control/1" and
                all(m["plugin"] in controls["cases"] for m in suite["methods"]), "direct-control plan lacks candidate methods")
        for case in suite["cases"]:
            spec = case["input"]
            source = {"kind": spec["kind"]}
            if spec["kind"] == "fixture":
                require(spec["name"] in manifest["files"], f"unknown fixture: {spec['name']}")
                source["asset"] = manifest["files"][spec["name"]]
            elif spec["kind"] == "corpus_window":
                source["window"] = bind_window(root, suite["corpus_manifest"], corpus["corpus_id"], spec)
            inputs[case["id"]] = _input(root, source)
        extra = {"contract_bindings": {"suite_schema": load_contract(root, "lossless-stage-suite").document_id,
                                       "corpus": corpus["corpus_id"], "fixture_manifest": content_id(manifest),
                                       "direct_control": content_id(controls)}, "estimates": _estimates(suite, inputs)}
        if request.suite == FORMAL_SUITE:
            receipt = load_json(local_file(root, suite["m0_receipt"]))
            require(receipt.get("schema") == "bmk.m0-stage-receipt/1" and receipt.get("stage_accepted") is True
                    and receipt.get("qualification_granted") is False,
                    "formal M1 requires an accepted M0 freeze receipt")
            extra["contract_bindings"]["m0_receipt"] = {
                "path": suite["m0_receipt"], "sha256": digest(local_file(root, suite["m0_receipt"])),
                "receipt_id": receipt["receipt_id"]}
        if timed(suite):
            binding = extra["contract_bindings"]
            binding["measurement"] = process_binding(root)
            binding["resource"] = resource_binding(root)
            recovery = plan_recovery(root, build, [m["plugin"] for m in suite["methods"]])
            binding["recovery"] = recovery
            extra["estimates"] = _estimates(suite, inputs, recovery)
            if isolation.active(suite):
                binding["isolation"] = isolation.bind(suite)
            binding["comparison"] = bind_stage_comparisons(root,suite,inputs,binding["measurement"],
                                                           recovery=recovery, isolation=binding.get("isolation"))
    else:
        for label in suite["fixtures"]:
            require(label in manifest["files"], f"unknown fixture: {label}")
            inputs[label] = _input(root, {"asset": manifest["files"][label]})
    for method in suite["methods"]:
        name = method["plugin"]
        binding = resolve_worker(root, build, name, method["options"], registry=registry)
        methods[name] = {**method, "options": binding["options"], "configuration_id": binding["configuration_id"],
                         "route": "byte-codec-on-canonical-values" if method["role"] == "bytes" else "typed-value"}
    body = {"schema": STAGE_PROTOCOL if stage else PROTOCOL, "purpose": stage_purpose(request.suite) if stage else "development_only",
            "suite": suite, "build": build, **extra,
            "inputs": inputs, "methods": methods, "qualification_granted": False,
            "observation_schema_id": load_contract(root, "observation").document_id}
    scope = content_id(body)
    body.update(scope_id=scope, slots=_slots(suite, inputs, methods, scope))
    return {**body, "plan_content_id": content_id(body)}


def check_plan(plan: dict, suite: dict | None = None) -> None:
    require(isinstance(plan, dict), "not a lossless plan")
    stage = plan.get("schema") == STAGE_PROTOCOL
    common = {"schema", "purpose", "suite", "build", "inputs", "methods", "qualification_granted", "scope_id", "slots",
              "plan_content_id", "observation_schema_id"}
    require(plan.keys() == common | ({"contract_bindings", "estimates"} if stage else set()), "not a supported lossless plan")
    require((stage and plan["purpose"] == stage_purpose(plan["suite"]["id"]) and plan["suite"]["id"] in STAGE_SUITES or
             plan["schema"] == PROTOCOL and plan["purpose"] == "development_only")
            and plan["qualification_granted"] is False, "lossless preflight plans do not grant qualification")
    if not stage:
        _development_suite(plan["suite"], plan["suite"]["id"])
    require(type(plan["observation_schema_id"]) is str and re.fullmatch(r"[a-f0-9]{64}", plan["observation_schema_id"]),
            "invalid observation schema ID")
    require(plan["plan_content_id"] == content_id({k: v for k, v in plan.items() if k != "plan_content_id"}),
            "plan content ID mismatch")
    require(plan["scope_id"] == content_id({k: v for k, v in plan.items() if k not in {"scope_id", "slots", "plan_content_id"}}),
            "plan scope ID mismatch")
    require(suite is None or suite == plan["suite"], "requested suite differs from frozen smoke scope")
    if stage:
        _stage_denominator(plan["suite"])
        bindings = plan["contract_bindings"]
        require(isinstance(bindings, dict) and ("measurement" in bindings) == timed(plan["suite"]) and
                plan["suite"]["measurement"]["mode"] == (PROFILE if timed(plan["suite"]) else "not_collected"),
                "stage measurement differs from frozen suite")
        cases, methods = plan["suite"]["cases"], plan["suite"]["methods"]
        require(plan["inputs"].keys() == {c["id"] for c in cases} and
                plan["methods"].keys() == {m["plugin"] for m in methods}, "wrong case or method binding set")
        for case in cases:
            src = plan["inputs"][case["id"]]
            require(src["kind"] == case["input"]["kind"] and src["dtype"] == DTYPE and
                    type(src["count"]) is int and 0 <= src["count"] <= 8192 and src["bytes"] == src["count"] * 8,
                    f"invalid stage input binding: {case['id']}")
        for decl in methods:
            method = plan["methods"][decl["plugin"]]
            require(method["plugin"] == decl["plugin"] and method["role"] == decl["role"], "invalid stage method binding")
        recovery = bindings.get("recovery")
        require(("isolation" in bindings) == isolation.active(plan["suite"]), "isolation binding differs from suite")
        if isolation.active(plan["suite"]):
            isolation.check(plan["suite"], bindings["isolation"])
            require(recovery is not None, "isolated execution requires an ELF closure")
        if "recovery" in bindings:
            require(timed(plan["suite"]) and "resource" in bindings and "comparison" in bindings,
                    "recovery requires the timed candidate contracts")
            check_recovery(recovery, plan["build"], plan["methods"])
        require(plan["estimates"] == _estimates(plan["suite"], plan["inputs"], recovery), "candidate budget estimate changed")
    require(plan["slots"] == _slots(plan["suite"], plan["inputs"], plan["methods"], plan["scope_id"]) and plan["slots"],
            "plan omits or alters a required slot")
