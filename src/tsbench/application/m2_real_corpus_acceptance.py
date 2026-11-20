"""Accept the updated M2 measurement protocol without admitting ranking."""
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract
from ..planner.m2_real_corpus import check_m2_real_corpus_plan
from ..planner.timing import check_plan

SCHEMA = "bmk.m2-real-corpus-stage-receipt/1"
RECEIPT_CONTRACT = "m2-real-corpus-stage-receipt"


def _file_ref(root: Path, relative: str) -> dict:
    path = local_file(root, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def _accepted(root: Path, relative: str, schema: str, stage: str) -> dict:
    value = load_json(local_file(root, relative))
    require(value.get("schema") == schema and value.get("stage") == stage and
            value.get("stage_accepted") is True and value.get("qualification_granted") is False,
            f"{stage} predecessor is not an accepted non-qualification receipt")
    require(value.get("receipt_id") == content_id({k: v for k, v in value.items() if k != "receipt_id"}),
            f"{stage} predecessor receipt ID is stale")
    return value


def _report(root: Path, relative: str, plan_content_id: str) -> dict:
    value = load_json(local_file(root, relative))
    require(value.get("schema") == "bmk.timing-report/1" and
            value.get("plan_content_id") == plan_content_id and
            value.get("planned_batches") == 144 and value.get("all_batches_verified") is True and
            value.get("statuses") == {"verified": 144} and value.get("formal_performance") is False,
            f"{relative} is not a complete diagnostic timing repeat")
    require(all(row.get("sample", {}).get("encode_batch_ns", 0) >= 0 and
                row.get("sample", {}).get("decode_batch_ns", 0) >= 0
                for row in value.get("observations", []) if row.get("status") == "verified"),
            f"{relative} lacks two-direction timing observations")
    run = root / "results" / value["run_id"]
    require(run.is_dir() and load_json(run / "completion.json").get("schema") == "bmk.timing-seal/1",
            f"{relative} timing run seal is missing")
    return value


def audit_m2_real_corpus(root: Path, *, plan: str, report_a: str, report_b: str,
                         repeat: str, controls: str) -> dict:
    root = root.resolve(strict=True)
    contract = load_contract(root, RECEIPT_CONTRACT)
    plan_doc = load_json(local_file(root, plan))
    check_m2_real_corpus_plan(root, plan_doc)
    m0_ref = plan_doc["predecessors"]["m0_real_corpus_receipt"]["path"]
    m1_ref = plan_doc["predecessors"]["m1_real_corpus_receipt"]["path"]
    m0 = _accepted(root, m0_ref, "bmk.m0-real-corpus-stage-receipt/1", "M0")
    m1 = _accepted(root, m1_ref, "bmk.m1-real-corpus-stage-receipt/1", "M1")
    require(plan_doc["predecessors"]["m0_real_corpus_receipt"]["receipt_id"] == m0["receipt_id"] and
            plan_doc["predecessors"]["m1_real_corpus_receipt"]["receipt_id"] == m1["receipt_id"],
            "updated M2 plan is not bound to current M0/M1 receipts")
    timing = load_json(local_file(root, plan_doc["timing"]["plan"]["path"]))
    check_plan(timing)
    reports = [_report(root, ref, timing["plan_content_id"]) for ref in (report_a, report_b)]
    require(reports[0]["run_id"] != reports[1]["run_id"], "M2 repeats must be independent runs")
    comparison = load_json(local_file(root, repeat))
    require(comparison.get("schema") == "bmk.timing-repeat-comparison/1" and
            comparison.get("plan_content_id") == timing["plan_content_id"] and
            comparison.get("runs") == [r["run_id"] for r in reports] and
            comparison.get("formal_performance") is False and comparison.get("samples_pooled") is False and
            all(v == {"verified": 144} for v in comparison.get("statuses", {}).values()),
            "updated M2 repeat comparison is incomplete")
    control = load_json(local_file(root, controls))
    require(control.get("schema") == "bmk.m2-real-corpus-controls/1" and
            control.get("plan_content_id") == plan_doc["plan_content_id"] and
            control.get("timing_plan_content_id") == timing["plan_content_id"] and
            control.get("m0_receipt_id") == m0["receipt_id"] and
            control.get("m1_receipt_id") == m1["receipt_id"] and
            control.get("cli_api_same_plan") is True and
            control.get("directions_verified") == ["encode", "decode"] and
            control.get("repeat_runs") == 2 and control.get("parallel_batches") == 1 and
            control.get("exclusive_cpu") is False and
            control.get("numa_memory_policy") == "inherited_uncontrolled" and
            control.get("cancelled_run_statuses") == {"blocked_calibration": 108, "cancelled": 36} and
            control.get("missing_library_run_statuses") == {"blocked_calibration": 24, "dependency_failed": 8, "verified": 112} and
            control.get("lock_contention_rejected_before_publication") is True and
            control.get("resealed_changed_loop_rejected") is True,
            "updated M2 controls are incomplete")
    body = {
        "schema": SCHEMA,
        "stage": "M2",
        "stage_accepted": True,
        "qualification_granted": False,
        "timing_admitted": False,
        "scope": "updated_real_corpus_measurement_and_scheduler_protocol",
        "evidence": {
            "plan": _file_ref(root, plan),
            "m0_real_corpus_receipt": _file_ref(root, m0_ref),
            "m1_real_corpus_receipt": _file_ref(root, m1_ref),
            "report_a": _file_ref(root, report_a),
            "report_b": _file_ref(root, report_b),
            "repeat_comparison": _file_ref(root, repeat),
            "controls": _file_ref(root, controls),
        },
        "coverage": {
            "real_corpus_datasets_bound": m0["coverage"]["datasets"],
            "native_routes_bound": m0["coverage"]["routes"],
            "m1_inputs_bound": m1["coverage"]["inputs"],
            "timing_batches_per_repeat": 144,
            "repeats": 2,
            "directions": ["encode", "decode"],
            "cache_cases": ["small", "block_boundary", "cache_inside", "cache_outside"],
            "verified_batches": 288,
        },
        "open_items": [
            "当前宿主 exclusive_cpu=false，NUMA memory policy=inherited_uncontrolled；本收据不授予正式性能排名",
            "parallel_batches=1；算法内部多线程仍可在 codec 内部运行，但外部批次并行未作为正式性能比较因素",
            "M2 仅接纳新版 M0/M1 绑定、双向计量和调度负对照；不授予 36 条路线原生资格",
            "M3 仍需以一个统一真实语料计划执行适用的 23 文件、36 路线原生义务",
        ],
    }
    document = {**body, "receipt_id": content_id(body)}
    contract.validate(document, "updated M2 real-corpus stage receipt")
    return document
