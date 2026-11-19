"""Recompute the M3 native-function and data-pipeline coverage receipt."""
from pathlib import Path
from collections import Counter

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract

SCHEMA = "bmk.m3-stage-receipt/1"
RECEIPT_CONTRACT = "m3-stage-receipt"


def _file_ref(root: Path, relative: str) -> dict:
    path = local_file(root, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def _check_report(root: Path, relative: str, schema: str, slots: int) -> dict:
    doc = load_json(local_file(root, relative))
    require(doc.get("schema") == schema and
            (doc.get("verified") is True or doc.get("statuses") == {"verified": slots}) and
            doc.get("qualification_granted") is False and doc.get("statuses") == {"verified": slots} and
            len(doc.get("slots", [])) == slots,
            f"M3 specialized report is incomplete: {relative}")
    return doc


def _check_restore(root: Path, relative: str, run_id: str, slots: int) -> None:
    doc = load_json(local_file(root, relative))
    require(doc.get("run_id") == run_id and doc.get("restored_slots") == slots and
            len(doc.get("slots", [])) == slots and doc.get("qualification_granted") is False and
            doc.get("isolation") in {"files_only_bubblewrap", "bubblewrap_network_pid_ipc_sealed_files_only"},
            f"M3 independent restore is incomplete: {relative}")


def audit_m3(root: Path, *, native_report: str, gorilla_report: str, gorilla_restore: str,
             composition_report: str, composition_restore: str, composition_controls: str,
             cross_format_report: str, cross_format_restore: str, cross_format_controls: str,
             limbs_report: str, limbs_restore: str, limbs_controls: str) -> dict:
    root = root.resolve(strict=True)
    contract = load_contract(root, RECEIPT_CONTRACT)

    native = load_json(local_file(root, native_report))
    require(native.get("schema") == "bmk.native-batch-execution-report/1" and
            native.get("planned_products") == 200 and
            native.get("terminal_counts") == {"verified": 174, "expected_rejection": 26} and
            native.get("all_product_expectations_met") is True and
            native.get("qualification_granted") is False and
            native.get("execution_scope", {}).get("total_routes") == 36 and
            native.get("execution_scope", {}).get("bound_routes") == 36 and
            native.get("execution_scope", {}).get("all_native_bindings_complete") is True and
            native.get("execution_scope", {}).get("bound_required_obligations") == 180,
            "M3 native denominator or route closure differs from the frozen first-batch contract")
    states = Counter(v.get("state") for v in native.get("obligation_evidence", {}).values())
    require(states == Counter({"verified_candidate": 184, "quality_rejected": 1, "pending_supported_runtime": 1}),
            "M3 native candidate evidence states differ from the frozen known limitations")

    gorilla = _check_report(root, gorilla_report, "bmk.dev-gorilla-role-report/1", 16)
    _check_restore(root, gorilla_restore, gorilla["run_id"], 16)
    composition = _check_report(root, composition_report, "bmk.dev-tv-report/1", 15)
    _check_restore(root, composition_restore, composition["run_id"], 15)
    cross = _check_report(root, cross_format_report, "bmk.dev-tv-report/2", 12)
    _check_restore(root, cross_format_restore, cross["run_id"], 12)
    limbs = _check_report(root, limbs_report, "bmk.dev-tv-report/1", 4)
    _check_restore(root, limbs_restore, limbs["run_id"], 4)

    composition_ctl = load_json(local_file(root, composition_controls))
    require(composition_ctl.get("schema") == "bmk.dev-tv-controls/1" and
            composition_ctl.get("qualification_granted") is False and
            composition_ctl.get("rejections", {}).get("disabled_t_provider") == "disabled plugin: raw-timestamp" and
            composition_ctl.get("rejections", {}).get("mismatched_value_time_axis"),
            "M3 TV composition controls are incomplete")
    cross_ctl = load_json(local_file(root, cross_format_controls))
    require(cross_ctl.get("schema") == "bmk.dev-tv-ingress-controls/1" and
            cross_ctl.get("cli_api_parity") is True and cross_ctl.get("setup_outside_worker_clock_cases") == 6 and
            cross_ctl.get("qualification_granted") is False,
            "M3 cross-format controls are incomplete")
    limbs_ctl = load_json(local_file(root, limbs_controls))
    require(limbs_ctl.get("schema") == "bmk.dev-tv-limb-controls/1" and
            limbs_ctl.get("qualification_granted") is False and
            limbs_ctl.get("rejections", {}).get("missing_transform"),
            "M3 fixed-T limb controls are incomplete")

    body = {
        "schema": SCHEMA,
        "stage": "M3",
        "stage_accepted": True,
        "qualification_granted": False,
        "timing_admitted": False,
        "scope": "native_function_and_data_pipeline_coverage",
        "evidence": {
            "native_batch": _file_ref(root, native_report),
            "gorilla_roles": _file_ref(root, gorilla_report),
            "gorilla_roles_restore": _file_ref(root, gorilla_restore),
            "tv_composition": _file_ref(root, composition_report),
            "tv_composition_restore": _file_ref(root, composition_restore),
            "tv_composition_controls": _file_ref(root, composition_controls),
            "tv_cross_format": _file_ref(root, cross_format_report),
            "tv_cross_format_restore": _file_ref(root, cross_format_restore),
            "tv_cross_format_controls": _file_ref(root, cross_format_controls),
            "tv_limbs": _file_ref(root, limbs_report),
            "tv_limbs_restore": _file_ref(root, limbs_restore),
            "tv_limbs_controls": _file_ref(root, limbs_controls)
        },
        "open_items": [
            "36/36 原生路线和 180 项必需义务已有同次候选证据，但 formal qualification 仍未签发",
            "ALP f64 AVX512BW 已构建但当前宿主不可运行，保持 pending_supported_runtime",
            "CORAD inference 质量门保持 quality_rejected，不得改写为通过",
            "M3 的复合/跨格式/位片证据证明管线与机制，不替代 M5 的 204 展示格和 264 原子关系",
            "M4 profiling、M5 外置服务矩阵和 M6 稳定版验收仍未完成"
        ]
    }
    document = {**body, "receipt_id": content_id(body)}
    contract.validate(document, "M3 stage receipt")
    return document
