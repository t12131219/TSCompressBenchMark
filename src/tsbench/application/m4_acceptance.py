"""Recompute the M4 native profiling and measurement-controls receipt."""
from collections import Counter
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require
from ..contracts import load_contract

SCHEMA = "bmk.m4-stage-receipt/1"
RECEIPT_CONTRACT = "m4-stage-receipt"
PLAN_SCHEMA = "bmk.native-profile-plan/1"
REPORT_SCHEMA = "bmk.native-profile-report/1"


def _file_ref(root: Path, relative: str) -> dict:
    path = local_file(root, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def _trial_modes(report: dict) -> Counter:
    return Counter((trial.get("case"), trial.get("mode")) for trial in report.get("trials", []))


def _directions(report: dict) -> set[str]:
    return {obs.get("direction") for trial in report.get("trials", []) for obs in trial.get("observations", [])}


def _visibility(report: dict) -> set[str]:
    return {obs.get("l2_visibility") for trial in report.get("trials", [])
            for obs in trial.get("observations", [])}


def audit_m4(root: Path, *, plan: str, report: str, controls: str) -> dict:
    root = root.resolve(strict=True)
    contract = load_contract(root, RECEIPT_CONTRACT)
    plan_doc = load_json(local_file(root, plan))
    require(plan_doc.get("schema") == PLAN_SCHEMA and
            plan_doc.get("formal_performance") is False and
            plan_doc.get("qualification_granted") is False and
            plan_doc.get("extent") == "prepare_native_operation_cleanup_write_and_close_not_input_read_or_external_verify" and
            isinstance(plan_doc.get("plan_content_id"), str),
            "M4 plan is not the frozen non-ranking native profiling plan")
    require(plan_doc["plan_content_id"] == content_id({k: v for k, v in plan_doc.items() if k != "plan_content_id"}),
            "M4 plan content identity is invalid")
    require(set(plan_doc.get("builds", {})) == {"plain", "profile"} and
            plan_doc["builds"]["plain"] != plan_doc["builds"]["profile"],
            "M4 plan does not bind distinct plain and profile builds")
    require(set(plan_doc.get("artifacts", {})) == {"plain", "profile"} and
            all(plan_doc["artifacts"][mode] for mode in ("plain", "profile")),
            "M4 plan is missing plain/profile artifact identities")
    schedule = plan_doc.get("schedule", [])
    require(len(schedule) == 28 and {x.get("mode") for x in schedule} == {"trace_off", "timing_only", "profiled"} and
            {x.get("case") for x in schedule} == {"alp-fused", "zstd-mt", "xz-opaque"} and
            Counter(x.get("mode") for x in schedule) == Counter({"profiled": 10, "trace_off": 9, "timing_only": 9}) and
            Counter(x.get("capacity") for x in schedule) == Counter({0: 18, 128: 9, 2: 1}),
            "M4 plan schedule denominator or execution arms differ")

    report_doc = load_json(local_file(root, report))
    require(report_doc.get("schema") == REPORT_SCHEMA and
            report_doc.get("plan_content_id") == plan_doc["plan_content_id"] and
            report_doc.get("all_verified") is True and
            report_doc.get("statuses") == {"verified": 28} and
            report_doc.get("formal_performance") is False and
            report_doc.get("qualification_granted") is False and
            report_doc.get("stage_accepted") is False and
            report_doc.get("l0_extent") == plan_doc["extent"] and
            len(report_doc.get("trials", [])) == 28,
            "M4 report is not a complete 28-trial non-ranking profiling report")
    trials = report_doc["trials"]
    require({t.get("status") for t in trials} == {"verified"} and
            {t.get("case") for t in trials} == {"alp-fused", "zstd-mt", "xz-opaque"} and
            {t.get("mode") for t in trials} == {"trace_off", "timing_only", "profiled"} and
            _directions(report_doc) == {"encode", "decode"},
            "M4 report lacks verified bidirectional profiling coverage")
    require(all(len(t.get("observations", [])) == 2 for t in trials),
            "M4 verified trials must contain encode and decode observations")
    modes = _trial_modes(report_doc)
    require(modes["alp-fused", "profiled"] >= 3 and modes["zstd-mt", "profiled"] >= 3 and
            modes["xz-opaque", "profiled"] >= 3 and
            all(modes[case, mode] >= 3 for case in ("alp-fused", "zstd-mt", "xz-opaque")
                for mode in ("trace_off", "timing_only", "profiled") if (case, mode) in modes),
            "M4 matched case/mode profiling coverage is incomplete")
    require({"fused", "measured", "opaque"} <= _visibility(report_doc) and
            "disabled" in _visibility(report_doc) and
            "not_measured" in _visibility(report_doc),
            "M4 L2 visibility does not cover fused, multithreaded, opaque and disabled limits")
    require(isinstance(report_doc.get("perturbation"), list) and len(report_doc["perturbation"]) == 6 and
            all(x.get("planned_rounds") == 3 and len(x.get("complete_matched_rounds", [])) == 3
                for x in report_doc["perturbation"]),
            "M4 perturbation comparison is incomplete")
    require(report_doc.get("frame_bytes_by_case") and
            set(report_doc["frame_bytes_by_case"]) == {"alp-fused", "zstd-mt", "xz-opaque"},
            "M4 bitwise frame identity evidence is incomplete")

    controls_doc = load_json(local_file(root, controls))
    require(controls_doc.get("plan_content_id") == plan_doc["plan_content_id"] and
            controls_doc.get("run_id") == report_doc.get("run_id") and
            controls_doc.get("cli_api_same_plan") is True and
            controls_doc.get("profiles_overlap_observed") is True and
            controls_doc.get("replay_byte_identical") is True and
            isinstance(controls_doc.get("lost_event_relabel_rejected"), str) and
            isinstance(controls_doc.get("worker_interval_outside_l0_rejected"), str) and
            controls_doc.get("clean_and_profile_elf_needed", {}).get("plain") and
            controls_doc.get("clean_and_profile_elf_needed", {}).get("profile"),
            "M4 measurement controls are incomplete")

    body = {
        "schema": SCHEMA,
        "stage": "M4",
        "stage_accepted": True,
        "qualification_granted": False,
        "timing_admitted": False,
        "scope": "native_profiling_and_measurement_controls",
        "evidence": {
            "plan": _file_ref(root, plan),
            "report": _file_ref(root, report),
            "controls": _file_ref(root, controls)
        },
        "open_items": [
            "本收据只接纳 ALP fused、Zstd 多线程和 XZ opaque 的剖析/对照协议，不把 profiling 时间变成正式性能排名",
            "profile build 使用 trace overlay，插桩扰动已单独披露；正式主计时仍须使用独立的 plain build",
            "L2 对不暴露内部阶段的 XZ 保持 opaque/not_measured，不从缺失插桩推断内部成本或线程行为",
            "当前宿主的专核、NUMA、频率和外部干扰约束仍未构成正式 timing admission",
            "36 条原生路线的正式 qualification、M5 204 展示格与 264 原子关系仍未完成",
            "ALP AVX512/AVX512BW 路线保留为 pending_supported_runtime，不因本机缺少指令集而删除"
        ]
    }
    document = {**body, "receipt_id": content_id(body)}
    contract.validate(document, "M4 stage receipt")
    return document
