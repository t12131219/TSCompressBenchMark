"""Accept the updated M1 two-input lossless slice, not timing qualification."""
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract
from ..planner.smoke import check_plan, _suite
from .smoke import report_smoke

SCHEMA = "bmk.m1-real-corpus-stage-receipt/1"
RECEIPT_CONTRACT = "m1-real-corpus-stage-receipt"
SUITE = "m1_lossless_full_corpus_preflight_v1"


def _file_ref(root: Path, relative: str) -> dict:
    path = local_file(root, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def audit_m1_real_corpus(root: Path, *, predecessor: str, plan: str, report: str,
                         restore: str, controls: str) -> dict:
    root = root.resolve(strict=True)
    contract = load_contract(root, RECEIPT_CONTRACT)
    m0 = load_json(local_file(root, predecessor))
    require(m0.get("schema") == "bmk.m0-real-corpus-stage-receipt/1" and
            m0.get("stage_accepted") is True and m0.get("qualification_granted") is False,
            "updated M1 requires an accepted real-corpus M0 receipt")

    plan_doc = load_json(local_file(root, plan))
    require(plan_doc.get("purpose") == "m1_candidate_preflight" and
            plan_doc.get("qualification_granted") is False and
            plan_doc.get("suite", {}).get("id") == SUITE and len(plan_doc.get("slots", [])) == 6,
            "M1 updated plan is not the frozen six-slot full-corpus slice")
    check_plan(plan_doc, _suite(root, SUITE, plan_doc["suite"].get("input_config")), root)
    binding = plan_doc.get("contract_bindings", {}).get("native_corpus_definition")
    require(binding and binding.get("plan_content_id") == m0["evidence"]["native_definition"].get("sha256")
            or binding and binding.get("plan_content_id") == load_json(local_file(root, m0["evidence"]["native_definition"]["path"])).get("plan_content_id"),
            "M1 plan is not bound to the accepted M0 native definition")

    report_doc = load_json(local_file(root, report))
    require(report_doc.get("schema") == "bmk.dev-lossless-report/1" and
            report_doc.get("plan_content_id") == plan_doc.get("plan_content_id") and
            report_doc.get("planned_slots") == 6 and report_doc.get("all_verified") is True and
            report_doc.get("statuses") == {"verified": 6} and
            report_doc.get("qualification_granted") is False and
            len(report_doc.get("cases", [])) == 6,
            "M1 updated report is not a complete six-slot artifact_each run")
    run_id = report_doc["run_id"]
    run_dir = root / "results" / run_id
    require(run_dir.is_dir() and load_json(run_dir / "completion.json").get("run_id") == run_id,
            "M1 updated run seal is missing")
    recomputed = report_smoke(root, run_id)
    require(recomputed == report_doc, "M1 report cannot be recomputed byte-for-byte from the sealed run")

    restore_doc = load_json(local_file(root, restore))
    require(restore_doc.get("schema") == "bmk.dev-smoke-restore-audit/1" and
            restore_doc.get("run_id") == run_id and
            restore_doc.get("planned_slots") == 6 and
            restore_doc.get("restored_verified_slots") == 6 and
            restore_doc.get("isolation") == "bubblewrap_network_pid_ipc_sealed_files_only",
            "M1 updated independent restore is incomplete")

    control = load_json(local_file(root, controls))
    require(control.get("scope") == "updated_m1_real_corpus" and
            control.get("plan_content_id") == plan_doc["plan_content_id"] and
            control.get("cli_api_plan_equal") is True and
            control.get("report_byte_identical") is True and
            control.get("incompatible_input", {}).get("run_created") is False and
            control.get("isolated_restored_slots") == 6,
            "M1 updated input/configuration controls are incomplete")

    body = {
        "schema": SCHEMA,
        "stage": "M1",
        "stage_accepted": True,
        "qualification_granted": False,
        "timing_admitted": False,
        "scope": "updated_real_input_lossless_vertical_slice",
        "evidence": {
            "m0_real_corpus_receipt": _file_ref(root, predecessor),
            "plan": _file_ref(root, plan),
            "report": _file_ref(root, report),
            "restore": _file_ref(root, restore),
            "controls": _file_ref(root, controls),
        },
        "coverage": {"cases": 2, "methods": 3, "slots": 6, "verified": 6,
                     "restored_verified_slots": 6, "verification": "artifact_each",
                     "inputs": ["economics-heldout", "bitcoin-heldout"]},
        "open_items": [
            "M1 只证明两个合法真实输入上的 raw-store/Zstd/ALP 最小无损闭环",
            "当前 run 的资源与时钟仍是候选诊断，不授予正式性能排名",
            "M2 仍需绑定本新版 M1 并完成双向计量、资源和重复策略",
            "M3 仍需执行 23 文件、36 路线的统一真实语料原生计划",
        ],
    }
    document = {**body, "receipt_id": content_id(body)}
    contract.validate(document, "updated M1 real-corpus stage receipt")
    return document
