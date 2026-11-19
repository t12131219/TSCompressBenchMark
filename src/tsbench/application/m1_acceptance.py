"""Recompute the M1 minimum lossless vertical-slice receipt."""
from pathlib import Path
import re

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract

SCHEMA = "bmk.m1-stage-receipt/1"
RECEIPT_CONTRACT = "m1-stage-receipt"


def _file_ref(root: Path, relative: str) -> dict:
    path = local_file(root, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def _run_dir(root: Path, run_id: str) -> str:
    require(isinstance(run_id, str) and re.fullmatch(r"[0-9a-f]{32}", run_id), "invalid M1 run ID")
    path = root / "results" / run_id
    require(path.is_dir(), f"M1 run directory is missing: {run_id}")
    return f"results/{run_id}"


def audit_m1(root: Path, *, plan: str, report: str, restore: str) -> dict:
    root = root.resolve(strict=True)
    contract = load_contract(root, RECEIPT_CONTRACT)
    plan_doc = load_json(local_file(root, plan))
    require(plan_doc.get("schema") == "bmk.lossless-stage-plan/1" and
            plan_doc.get("purpose") == "m1_formal_execution" and
            plan_doc.get("qualification_granted") is False,
            "M1 plan is not the frozen formal lossless plan")
    require(len(plan_doc.get("slots", [])) == 18, "M1 plan denominator must be 18 slots")
    require(plan_doc.get("contract_bindings", {}).get("m0_receipt", {}).get("receipt_id"),
            "M1 plan is not bound to an M0 receipt")
    receipt_ref = plan_doc["contract_bindings"]["m0_receipt"]
    receipt_path = receipt_ref["path"]
    receipt = load_json(local_file(root, receipt_path))
    require(receipt.get("schema") == "bmk.m0-stage-receipt/1" and receipt.get("stage_accepted") is True and
            receipt.get("qualification_granted") is False and receipt.get("timing_admitted") is False,
            "M1 predecessor M0 receipt is not accepted")
    require(receipt.get("receipt_id") == receipt_ref.get("receipt_id") and
            digest(local_file(root, receipt_path)) == receipt_ref.get("sha256"),
            "M1 M0 receipt binding does not match the frozen plan")

    run_id = None
    report_doc = load_json(local_file(root, report))
    require(report_doc.get("schema") == "bmk.dev-lossless-report/1" and
            report_doc.get("plan_content_id") == plan_doc.get("plan_content_id") and
            report_doc.get("planned_slots") == 18 and report_doc.get("all_verified") is True and
            report_doc.get("statuses") == {"verified": 18} and
            report_doc.get("qualification_granted") is False,
            "M1 report is not a complete 18-slot verified run")
    run_id = report_doc.get("run_id")
    run_dir = _run_dir(root, run_id)
    cases = report_doc.get("cases", [])
    require(len(cases) == 18 and all(case.get("status") == "verified" for case in cases),
            "M1 report does not verify every actual artifact")
    require(all(case.get("workspace", {}).get("action") == "verified_released" for case in cases),
            "M1 verified workspaces were not released according to the ledger")

    restore_doc = load_json(local_file(root, restore))
    require(restore_doc.get("schema") == "bmk.dev-smoke-restore-audit/1" and
            restore_doc.get("run_id") == run_id and restore_doc.get("planned_slots") == 18 and
            restore_doc.get("restored_verified_slots") == 18 and
            restore_doc.get("isolation") == "bubblewrap_network_pid_ipc_sealed_files_only",
            "M1 independent restore audit is incomplete")
    recovery = load_json(local_file(root, f"{run_dir}/recovery.json"))
    require(recovery.get("status") == "ready" and recovery.get("recovery_id") == restore_doc.get("recovery_id"),
            "M1 recovery binding is not ready")
    completion = load_json(local_file(root, f"{run_dir}/completion.json"))
    require(completion.get("schema") == "bmk.dev-lossless-seal/1" and completion.get("run_id") == run_id,
            "M1 run seal is missing")

    body = {
        "schema": SCHEMA,
        "stage": "M1",
        "stage_accepted": True,
        "qualification_granted": False,
        "timing_admitted": False,
        "scope": "minimum_lossless_vertical_slice",
        "evidence": {
            "m0_receipt": _file_ref(root, receipt_path),
            "plan": _file_ref(root, plan),
            "run": _file_ref(root, f"{run_dir}/run.json"),
            "report": _file_ref(root, report),
            "restore": _file_ref(root, restore),
            "recovery": _file_ref(root, f"{run_dir}/recovery.json"),
            "completion": _file_ref(root, f"{run_dir}/completion.json")
        },
        "open_items": [
            "M1 仅证明 raw-store/Zstd/ALP 的最小无损闭环，不授予首批原生资格",
            "M2 仍需冻结并执行受控 session、预热校准、匹配重复和资源协议",
            "M3 仍需完成首批原生功能、数据管线及 Gorilla TV/T/V 资格清单",
            "M4 仍需完成独立 profiling、L0/L1/L2 对照及观测扰动报告",
            "ALP AVX512BW 条件能力和 CORAD 质量拒绝保持原 M0 收据状态"
        ]
    }
    document = {**body, "receipt_id": content_id(body)}
    contract.validate(document, "M1 stage receipt")
    return document
