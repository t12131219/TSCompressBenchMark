"""Recompute the M2 measurement/scheduling protocol receipt."""
from pathlib import Path
import re

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract

SCHEMA = "bmk.m2-stage-receipt/1"
RECEIPT_CONTRACT = "m2-stage-receipt"


def _file_ref(root: Path, relative: str) -> dict:
    path = local_file(root, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def _run_dir(root: Path, run_id: str) -> str:
    require(isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id), "invalid M2 run ID")
    path = root / "results" / run_id
    require(path.is_dir(), f"M2 run directory is missing: {run_id}")
    return f"results/{run_id}"


def audit_m2(root: Path, *, plan: str, report_a: str, report_b: str,
             repeat: str, negative_controls: str) -> dict:
    root = root.resolve(strict=True)
    contract = load_contract(root, RECEIPT_CONTRACT)
    plan_doc = load_json(local_file(root, plan))
    require(plan_doc.get("schema") == "bmk.timing-plan/1" and plan_doc.get("target_stage") == "M2" and
            plan_doc.get("stage_accepted") is False and plan_doc.get("formal_performance") is False,
            "M2 plan is not the frozen diagnostic timing plan")
    require(plan_doc.get("planned_batches") == 144 and plan_doc.get("policy", {}).get("parallel_batches") == 1,
            "M2 plan denominator or serial scheduler policy differs from the frozen contract")
    cases = plan_doc.get("batches", {}).get("cases", [])
    outside = next((c for c in cases if c.get("id") == "large-copy-outside"), None)
    l3 = max((c.get("bytes", 0) for c in plan_doc.get("environment", {}).get("cache_topology", [])
              if c.get("level") == 3), default=0)
    require(outside is not None and outside.get("bytes", 0) > l3,
            "M2 plan lacks a workload larger than the selected CPU L3")

    reports = []
    for ref in (report_a, report_b):
        doc = load_json(local_file(root, ref))
        require(doc.get("schema") == "bmk.timing-report/1" and
                doc.get("plan_content_id") == plan_doc.get("plan_content_id") and
                doc.get("all_batches_verified") is True and doc.get("planned_batches") == 144 and
                doc.get("statuses") == {"verified": 144} and doc.get("formal_performance") is False,
                "M2 repeat is not a complete 144-batch verified diagnostic run")
        reports.append(doc)
        run_dir = _run_dir(root, doc["run_id"])
        require(load_json(local_file(root, f"{run_dir}/completion.json")).get("schema") == "bmk.timing-seal/1",
                "M2 timing run seal is missing")

    comparison = load_json(local_file(root, repeat))
    require(comparison.get("schema") == "bmk.timing-repeat-comparison/1" and
            comparison.get("plan_content_id") == plan_doc.get("plan_content_id") and
            comparison.get("runs") == [r["run_id"] for r in reports] and
            comparison.get("formal_performance") is False and comparison.get("samples_pooled") is False and
            all(v == {"verified": 144} for v in comparison.get("statuses", {}).values()),
            "M2 repeat comparison is not bound to two complete independent runs")

    controls = load_json(local_file(root, negative_controls))
    require(controls.get("schema") is None and controls.get("plan_content_id") == plan_doc.get("plan_content_id") and
            controls.get("cli_api_same_plan") is True and
            "resource is already reserved" in controls.get("lock_contention_rejected_before_publication", "") and
            controls.get("cancelled_run_statuses") == {"blocked_calibration": 108, "cancelled": 36} and
            controls.get("missing_library_run_statuses") == {"blocked_calibration": 24, "dependency_failed": 8, "verified": 112} and
            controls.get("resealed_changed_loop_rejected"),
            "M2 scheduler negative controls are incomplete")

    body = {
        "schema": SCHEMA,
        "stage": "M2",
        "stage_accepted": True,
        "qualification_granted": False,
        "timing_admitted": False,
        "scope": "controlled_measurement_and_scheduler_protocol",
        "evidence": {
            "plan": _file_ref(root, plan),
            "report_a": _file_ref(root, report_a),
            "report_b": _file_ref(root, report_b),
            "repeat_comparison": _file_ref(root, repeat),
            "negative_controls": _file_ref(root, negative_controls)
        },
        "open_items": [
            "当前宿主只提供 cooperative host-local flock，exclusive_cpu=false；不得将本轮结果作为正式性能排名",
            "NUMA 内存策略仍为 inherited_uncontrolled，频率与外部干扰仅作观测，不作因果归因",
            "本轮 parallel_batches=1，尚未建立外部并行整体墙钟与算法内部多线程的分离对照",
            "M2 不授予首批算法资格；M3 原生功能、T/V 组合和完整数据管线仍未验收",
            "M4 profiling 扰动、L0/L1/L2 分层和融合/opaque codec 观测仍未验收"
        ]
    }
    document = {**body, "receipt_id": content_id(body)}
    contract.validate(document, "M2 stage receipt")
    return document
