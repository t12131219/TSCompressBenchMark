"""Freeze the updated M2 binding between real-corpus gates and timing evidence."""
from dataclasses import dataclass
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require
from .timing import check_plan

SCHEMA = "bmk.m2-real-corpus-plan/1"


@dataclass(frozen=True, slots=True)
class M2RealCorpusPlanRequest:
    m0_receipt: str
    m1_receipt: str
    timing_plan: str


def _ref(root: Path, relative: str, *, receipt_id: str | None = None) -> dict:
    path = local_file(root, relative)
    value = {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}
    if receipt_id is not None:
        value["receipt_id"] = receipt_id
    return value


def _accepted(root: Path, relative: str, schema: str, stage: str) -> dict:
    document = load_json(local_file(root, relative))
    require(document.get("schema") == schema and document.get("stage") == stage and
            document.get("stage_accepted") is True and
            document.get("qualification_granted") is False,
            f"{relative} is not an accepted non-qualification {stage} receipt")
    require(document.get("receipt_id") == content_id({k: v for k, v in document.items() if k != "receipt_id"}),
            f"{relative} receipt ID is stale")
    return document


def plan_m2_real_corpus(root: Path, request: M2RealCorpusPlanRequest) -> dict:
    root = root.resolve(strict=True)
    m0 = _accepted(root, request.m0_receipt, "bmk.m0-real-corpus-stage-receipt/1", "M0")
    m1 = _accepted(root, request.m1_receipt, "bmk.m1-real-corpus-stage-receipt/1", "M1")
    timing = load_json(local_file(root, request.timing_plan))
    check_plan(timing)
    require(timing["target_stage"] == "M2" and timing["formal_performance"] is False,
            "updated M2 must bind a diagnostic timing plan")
    body = {
        "schema": SCHEMA,
        "target_stage": "M2",
        "stage_accepted": False,
        "formal_performance": False,
        "predecessors": {
            "m0_real_corpus_receipt": _ref(root, request.m0_receipt, receipt_id=m0["receipt_id"]),
            "m1_real_corpus_receipt": _ref(root, request.m1_receipt, receipt_id=m1["receipt_id"]),
        },
        "input_binding": {
            "corpus_manifest": m0["evidence"]["binding"]["path"],
            "native_definition": m0["evidence"]["native_definition"]["path"],
            "datasets": m0["coverage"]["datasets"],
            "routes": m0["coverage"]["routes"],
            "m1_inputs": m1["coverage"]["inputs"],
            "m1_slots": m1["coverage"]["slots"],
        },
        "timing": {
            "plan": _ref(root, request.timing_plan),
            "plan_content_id": timing["plan_content_id"],
            "planned_batches": timing["planned_batches"],
            "methods": sorted(timing["method_bindings"]),
            "directions": ["encode", "decode"],
            "verification": "artifact_each_encoded_bytes_and_original_bits_outside_codec_clock",
            "input_context": "diagnostic frame cases plus updated M1 real-input binding",
        },
        "measurement_contract": {
            "cache_cases": ["small", "block_boundary", "cache_inside", "cache_outside"],
            "lifecycle": ["steady", "cold"],
            "lanes": ["dlopen", "linked_entry"],
            "matched_rounds": 3,
            "calibration": "per_group_before_measured_rounds",
            "samples": "one_observation_per_lane_per_matched_round_not_per_inner_loop",
            "scheduler": "serial_batches_parallelism_inside_codec_is_observed_not_suppressed",
            "repeat_runs": 2,
            "resource_policy": "host_local_flock; exclusive_cpu=false is not formal timing admission",
            "numa_policy": "inherited_uncontrolled",
        },
    }
    return {**body, "plan_content_id": content_id(body)}


def check_m2_real_corpus_plan(root: Path, plan: dict) -> None:
    root = root.resolve(strict=True)
    require(plan.get("schema") == SCHEMA and plan.get("target_stage") == "M2" and
            plan.get("stage_accepted") is False and plan.get("formal_performance") is False,
            "invalid updated M2 real-corpus plan header")
    require(plan.get("plan_content_id") == content_id({k: v for k, v in plan.items() if k != "plan_content_id"}),
            "updated M2 plan content ID is stale")
    for key, schema, stage in (
        ("m0_real_corpus_receipt", "bmk.m0-real-corpus-stage-receipt/1", "M0"),
        ("m1_real_corpus_receipt", "bmk.m1-real-corpus-stage-receipt/1", "M1"),
    ):
        ref = plan["predecessors"][key]
        document = _accepted(root, ref["path"], schema, stage)
        require(ref["sha256"] == digest(local_file(root, ref["path"])) and
                ref["receipt_id"] == document["receipt_id"], f"updated M2 predecessor binding is stale: {key}")
    timing_ref = plan["timing"]["plan"]
    timing = load_json(local_file(root, timing_ref["path"]))
    check_plan(timing)
    require(timing["plan_content_id"] == plan["timing"]["plan_content_id"] and
            timing_ref["sha256"] == digest(local_file(root, timing_ref["path"])) and
            plan["timing"]["planned_batches"] == 144 and
            plan["timing"]["directions"] == ["encode", "decode"],
            "updated M2 timing binding is stale or incomplete")
    m0 = load_json(local_file(root, plan["predecessors"]["m0_real_corpus_receipt"]["path"]))
    m1 = load_json(local_file(root, plan["predecessors"]["m1_real_corpus_receipt"]["path"]))
    require(plan["input_binding"]["datasets"] == m0["coverage"]["datasets"] and
            plan["input_binding"]["routes"] == m0["coverage"]["routes"] and
            plan["input_binding"]["m1_inputs"] == m1["coverage"]["inputs"] and
            plan["input_binding"]["m1_slots"] == m1["coverage"]["slots"],
            "updated M2 input binding summary differs from M0/M1 receipts")
