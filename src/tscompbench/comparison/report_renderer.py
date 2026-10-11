"""Escaped standalone HTML for frozen comparison evidence; no codec execution."""

from __future__ import annotations

import html
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import unquote, urlsplit


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _number(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return "N/A"
    try:
        number = Decimal(str(value))
    except InvalidOperation, TypeError, ValueError:
        return "N/A"
    if not number.is_finite():
        return "N/A"
    if number == 0:
        return "0"
    if abs(number) >= 1_000_000 or abs(number) < Decimal("0.0001"):
        return format(number, ".5E")
    return format(number, ".6g")


def _json(value: Any) -> str:
    return "<pre>" + _escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"


def _details(label: str, value: Any) -> str:
    return "<details><summary>" + _escape(label) + "</summary>" + _json(value) + "</details>"


def _badge(value: Any) -> str:
    positive = value in {"CORE_COMPLETE", "COMPLETE", "FORMAL_COMPLETE", "PASS", "VALID"}
    return (
        '<span class="badge' + (" complete" if positive else "") + '">' + _escape(value) + "</span>"
    )


def _table(headers: list[str], rows: list[list[str]], *, caption: str) -> str:
    if not rows:
        return '<p class="muted">N/A · 未提供该项证据。</p>'
    return (
        '<div class="table-wrap"><table><caption>'
        + _escape(caption)
        + "</caption><thead><tr>"
        + "".join('<th scope="col">' + _escape(h) + "</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join("<tr>" + "".join("<td>" + c + "</td>" for c in row) + "</tr>" for row in rows)
        + "</tbody></table></div>"
    )


def _safe_link(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    decoded = unquote(value)
    if any(ord(char) < 32 for char in decoded) or "\\" in decoded or decoded.startswith("//"):
        return None
    try:
        parts = urlsplit(decoded)
    except ValueError:
        return None
    if parts.scheme and parts.scheme.lower() not in {"https", "http"}:
        return None
    if parts.scheme and not parts.netloc:
        return None
    return html.escape(value, quote=True)


def _raw_links(links: dict[str, str]) -> str:
    items = []
    for label, value in links.items():
        safe = _safe_link(value)
        if safe is None:
            raise ValueError("report artifact link uses an unsupported URL")
        items.append('<a href="' + safe + '">' + _escape(label) + "</a>")
    return '<div class="artifact-links">' + "".join(items) + "</div>" if items else ""


def _members(bundle: dict, matrix: list[dict]) -> list[list[str]]:
    declarations = {m["member_id"]: m for m in bundle.get("group", {}).get("members", [])}
    groups: dict[str, list[dict]] = {}
    for cell in matrix:
        groups.setdefault(cell["member_id"], []).append(cell)
    rows = []
    for member, cells in groups.items():
        declared = declarations.get(member, {})
        method = declared.get("method", {})
        configs = sorted({cell.get("config_label", "N/A") for cell in cells})
        identities = {
            name: sorted({str(c.get(name, "N/A")) for c in cells})
            for name in (
                "method_id",
                "method_equivalence_class",
                "algorithm_id",
                "source_artifact_id",
                "implementation_id",
            )
        }
        identities.update(
            source_implementation=declared.get("implementation"),
            shared_code_tags=declared.get("shared_code_tags", []),
        )
        rows.append(
            [
                _escape(member),
                _escape(method.get("name", member)),
                _escape(declared.get("role", cells[0].get("role", "N/A"))),
                _escape(", ".join(configs)),
                _escape(str(len(cells))),
                _details("方法 / 来源身份", identities),
            ]
        )
    return rows


def _observed(point: dict, key: str, statistic: str = "mean") -> Any:
    return ((point.get("metrics") or {}).get("observations", {}).get(key) or {}).get(statistic)


def _cell_rows(
    matrix: list[dict], points: dict[str, dict], disclosures: dict[str, dict]
) -> list[list[str]]:
    rows = []
    for cell in matrix:
        point = points.get(cell["cell_id"], {})
        directions = cell.get("directions") or {}
        cost_metric = point.get("metrics", {}).get("cost_metric", "final_bits")
        bits = (
            _observed(point, cost_metric)
            if point
            else (cell.get("comparison_cost_bits") or cell.get("final_bits") or {}).get("mean")
        )
        encode = (
            _observed(point, "encode_ns_per_object")
            if point
            else (directions.get("encode") or {}).get("mean")
        )
        decode = (
            _observed(point, "decode_ns_per_object")
            if point
            else (directions.get("decode") or {}).get("mean")
        )
        quality = point.get("quality") or {}
        quality_text = (
            "LOSSLESS · 精确参考"
            if quality.get("reference_only")
            else "RMSE "
            + _number(quality.get("original_domain_rmse"))
            + " / MaxAE "
            + _number(quality.get("original_domain_max_ae"))
        )
        cell_details = {
            "cell_id": cell["cell_id"],
            "parameters": cell.get("parameters", {}),
            "framework_parameters": cell.get("framework_parameters", {}),
            "loss_mode": cell.get("loss_mode"),
            "guarantee": cell.get("guarantee"),
            "accounting_components": point.get("metrics", {}).get("accounting_components"),
            "comparison_cost_metric": cost_metric,
            "full_recovery_final_bits": _observed(point, "final_bits"),
            "quality": quality or None,
            "quality_curve_eligible": point.get("quality_curve_eligible"),
            "fixed_error_ranking_eligible": point.get("fixed_error_ranking_eligible"),
            "allowed_paths": cell.get("allowed_paths"),
            "path": cell.get("path"),
            "execution_path_hash": cell.get("execution_path_hash"),
            "task_id": cell.get("task_id"),
            "execution_job_id": cell.get("execution_job_id"),
            "public_projection_key": cell.get("public_projection_key"),
            "trial_ids": cell.get("trial_ids", []),
            "run_ids": cell.get("run_ids", []),
            "saved_job_disclosures": disclosures.get(cell["cell_id"]),
        }
        status = cell["status"]
        if point and cell.get("formal_complete") and not point.get("formal_complete"):
            status = "EVIDENCE_RECHECK_FAILED"
        rows.append(
            [
                _escape(cell["dataset_id"]),
                _escape(cell["member_id"]) + "<small>" + _escape(cell["config_label"]) + "</small>",
                _escape(cell["role"])
                + "<small>预期 "
                + _escape(cell["expected_outcome"])
                + "</small>",
                _badge(status),
                _escape(
                    str(point.get("eligible_process_count", cell["eligible_process_count"]))
                    + " / "
                    + str(cell["planned_process_count"])
                ),
                _number(bits),
                _number(
                    point.get("metrics", {}).get("size_ratio") if point else cell.get("size_ratio")
                ),
                _number(encode),
                _number(decode),
                _number(_observed(point, "process_rss_bytes", "max")),
                _escape(quality_text),
                _details("单元证据", cell_details),
            ]
        )
    return rows


def _pair_rows(comparisons: list[dict]) -> list[list[str]]:
    rows = []
    for comparison in comparisons:
        for direction, effect in comparison.get("directions", {}).items():
            interval = effect.get("confidence_interval")
            ci = (
                "[" + _number(interval[0]) + ", " + _number(interval[1]) + "]"
                if isinstance(interval, list) and len(interval) == 2
                else "N/A"
            )
            rows.append(
                [
                    _escape(comparison["dataset_id"]),
                    _escape(comparison["first_member_id"] + " / " + comparison["second_member_id"]),
                    _escape(direction),
                    _escape(comparison.get("inference_role", "N/A")),
                    _number(effect.get("estimate")),
                    _escape(ci),
                    _escape(str(effect.get("paired_blocks", "N/A"))),
                    _badge(effect.get("status", "INCONCLUSIVE")),
                    _details("区间与配对证据", effect),
                ]
            )
    return rows


def _aggregate_rows(analysis: dict) -> list[list[str]]:
    rows = []
    for item in analysis.get("corpus_aggregates", []):
        directions = item.get("directions") or {}
        rows.append(
            [
                _escape(item["member_id"]),
                _escape(item["config_label"]),
                _badge(item["status"]),
                _escape(str(item["complete_cell_count"]) + " / " + str(item["core_cell_count"])),
                _number(item.get("size_ratio")),
                _number((directions.get("encode") or {}).get("semantic_mb_per_second")),
                _number((directions.get("decode") or {}).get("semantic_mb_per_second")),
            ]
        )
    return rows


def _source_rows(extension: dict) -> list[list[str]]:
    rows = []
    for item in extension.get("source_balanced", {}).get("aggregates", []):
        rows.append(
            [
                _escape(item["member_id"]),
                _escape(item["config_label"]),
                _badge(item["status"]),
                _escape(
                    str(item["complete_source_groups"]) + " / " + str(item["planned_source_groups"])
                ),
                _number(item.get("source_balanced_size_ratio")),
                _number(item.get("source_balanced_encode_ns_per_raw_bit")),
                _number(item.get("source_balanced_decode_ns_per_raw_bit")),
                _details("固定来源与权重", item["sources"]),
            ]
        )
    return rows


def _pareto_rows(extension: dict) -> list[list[str]]:
    return [
        [
            _escape(item["dataset_id"]),
            _badge(item["status"]),
            _escape(str(item["observed_points"]) + " / " + str(item["planned_points"])),
            _escape(", ".join(item["frontier_cell_ids"])) or "N/A",
            _details("目标、支配关系与缺口", item),
        ]
        for item in extension.get("pareto", [])
    ]


_STYLE = """
:root{color-scheme:light dark;--bg:#f3f5f8;--card:#fff;--fg:#18273b;--muted:#56647a;
--line:#dce3ee;--accent:#215c96;--ok:#176f53;--pill:#f3e8d1}
@media(prefers-color-scheme:dark){:root{--bg:#101822;--card:#182332;--fg:#e4eaf3;
--muted:#a9b7cb;--line:#324259;--accent:#86bafa;--ok:#76d5b6;--pill:#443b28}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1600px;margin:auto;padding:32px 24px 64px}header{margin-bottom:26px}
h1{font-size:30px;line-height:1.2;margin:6px 0 14px}h2{font-size:21px;margin:0 0 12px}
h3{font-size:17px}p{margin:8px 0}.eyebrow{letter-spacing:.12em;color:var(--accent);font-size:12px}
nav,.artifact-links{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}a{color:var(--accent)}
nav a,.artifact-links a{padding:5px 10px;border:1px solid var(--line);border-radius:6px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:22px;margin:18px 0;scroll-margin-top:16px}.scope{border-left:4px solid var(--accent)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:18px 0}
.card{padding:15px;border:1px solid var(--line);border-radius:8px}
.card strong{display:block;font-size:23px}
.muted,small{color:var(--muted)}small{display:block;font-size:12px}.badge{display:inline-block;
background:var(--pill);border-radius:4px;padding:2px 6px;white-space:nowrap;font-size:12px}
.badge.complete{color:var(--ok);background:transparent;border:1px solid var(--ok)}
.table-wrap{overflow:auto}table{border-collapse:collapse;min-width:850px;width:100%;font-size:13px}
caption{text-align:left;color:var(--muted);padding:6px 0 12px}th,td{text-align:left;
padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{white-space:nowrap}
td{overflow-wrap:anywhere}details{max-width:100%;margin:8px 0}
summary{cursor:pointer;color:var(--accent)}
pre{background:var(--bg);border-radius:6px;padding:14px;white-space:pre-wrap;overflow-wrap:anywhere;
font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;max-height:500px;overflow:auto}
.identity{overflow-wrap:anywhere;font:12px/1.6 ui-monospace,monospace}
@media(max-width:650px){main{padding:18px 10px}section{padding:14px}h1{font-size:25px}}
@media print{body{background:#fff;color:#000}main{padding:0}section{break-inside:avoid}
.table-wrap{overflow:visible}table{min-width:0;font-size:9px}nav{display:none}}
"""


def render_comparison_report(
    analysis: dict,
    *,
    plan: dict | None = None,
    bundle: dict | None = None,
    extensions: dict | None = None,
    raw_links: dict[str, str] | None = None,
    disclosures: dict[str, dict] | None = None,
) -> str:
    """Render saved analysis with fixed denominators and explicit unavailable fields.

    Links accept HTTP(S), local paths or relative artifact paths, rejecting active
    URL schemes. Optional documents must refer to the same frozen comparison.
    """
    if analysis.get("schema_version") != "tscb.comparison-analysis.v1":
        raise ValueError("unsupported comparison report analysis")
    matrix = analysis["matrix"]
    cells = {row["cell_id"]: row for row in matrix}
    if len(cells) != len(matrix) or analysis["coverage"]["planned_cells"] != len(matrix):
        raise ValueError("report requires the full fixed analysis matrix")
    if plan is not None:
        planned = {row["cell_id"]: row for row in plan["cells"]}
        if (
            plan.get("comparison_id") != analysis.get("comparison_id")
            or len(planned) != len(plan["cells"])
            or set(planned) != set(cells)
        ):
            raise ValueError("report plan differs from the frozen analysis")
    extension = extensions or {}
    points = {row["cell_id"]: row for row in extension.get("quality_curve", {}).get("points", [])}
    if extensions is not None and (
        extension.get("schema_version") != "tscb.comparison-analysis-extensions.v1"
        or extension.get("analysis_id") != analysis.get("analysis_id")
        or extension.get("comparison_id") != analysis.get("comparison_id")
        or extension.get("audited_trials_sha256") != analysis.get("audited_trials_sha256")
        or set(points) != set(cells)
        or len(points) != len(extension.get("quality_curve", {}).get("points", []))
    ):
        raise ValueError("report extensions differ from the audited analysis")
    if disclosures is not None and set(disclosures) - set(cells):
        raise ValueError("report disclosures reference an unplanned cell")
    frozen = bundle or {}
    contract = frozen.get("contract") or (plan or {}).get("contract") or {}
    protocol = (plan or {}).get("protocol") or frozen.get("protocol") or {}
    title = contract.get("name", "TSBenchMark 冻结比较")
    coverage = analysis["coverage"]
    audit_issues = extension.get("audit_issues", [])
    status = "EVIDENCE_RECHECK_FAILED" if audit_issues else analysis["status"]
    core_complete = (
        sum(
            p["role"] == "CORE" and p["formal_complete"] and p["expected_outcome"] == "PASS"
            for p in points.values()
        )
        if points
        else coverage["core_formal_complete_cells"]
    )
    cards = [
        (
            "核心正式完成 / 固定核心",
            str(core_complete) + " / " + str(coverage["core_planned_cells"]),
        ),
        (
            "已执行单元 / 固定全矩阵",
            str(coverage["terminal_cells"]) + " / " + str(coverage["planned_cells"]),
        ),
        ("独立真实来源", str(analysis.get("independent_real_source_count", "N/A"))),
        ("核心方法等价类", str(analysis.get("distinct_core_methods", "N/A"))),
    ]
    sections = [
        '<section class="scope" id="scope"><h2>完成状态与结论范围</h2>'
        + _badge(status)
        + "<p>结论仅覆盖事前冻结的数据对象、配置、执行路径和本次机器。"
        + "预期 PASS、REJECT、BLOCKED 与缺失单元均保留在原分母。</p>"
        + '<div class="cards">'
        + "".join(
            '<div class="card"><strong>'
            + _escape(v)
            + "</strong><span>"
            + _escape(k)
            + "</span></div>"
            for k, v in cards
        )
        + "</div>"
        + _details(
            "核心缺口与排除证据",
            {
                "core_gaps": analysis.get("core_gaps", []),
                "exclusions": analysis.get("exclusions", []),
                "extension_audit_issues": audit_issues,
            },
        )
        + "</section>",
        '<section id="methods"><h2>方法、配置与来源身份</h2><p class="muted">'
        + "参数点和实现副本按已冻结的方法等价类披露。</p>"
        + _table(
            ["成员", "方法", "声明角色", "配置", "固定单元数", "身份 / 共用来源"],
            _members(frozen, matrix),
            caption="所有冻结成员；保持计划顺序",
        )
        + "</section>",
        '<section id="protocol"><h2>测量协议与对象边界</h2>'
        + _details(
            "事前决策问题、目标总体、主要估计量与结论边界",
            (plan or {}).get("decision") or "N/A · 未提供事前决策契约",
        )
        + _details("研究问题、恢复、误差、成本、资源与选择政策", contract or "N/A · 未提供合同")
        + _details("测量协议", protocol or "N/A · 未提供协议")
        + _details(
            "分析政策与实现",
            {
                "policy": analysis.get("analysis_policy"),
                "implementation": analysis.get("analysis_implementation"),
                "extension_implementation_sha256": extension.get("implementation_sha256"),
            },
        )
        + _details(
            "CPU affinity 与语料来源",
            {
                "cpu_affinity": frozen.get("cpu_affinity"),
                "corpus": frozen.get("corpus"),
                "denominators": (plan or {}).get("denominators"),
            },
        )
        + "</section>",
        '<section id="cells"><h2>逐单元实际成本、时间、资源与质量</h2>'
        + '<p class="muted">FinalBits 包含实际串行化对象与必要外部信息；'
        + "大小比为 FinalBits / RawBits。"
        + "时间为独立对象的进程观测均值；RSS 为完整 PROCESS 观测的绝对高水位最大值。"
        + "缺失值显示 N/A。逐列质量保留原值单位；汇总 RMSE 仅作数值描述。</p>"
        + _table(
            [
                "数据对象",
                "成员 / 配置",
                "角色 / 预期",
                "状态",
                "有效 / 计划进程",
                "比较成本 bits",
                "大小比",
                "编码 ns/对象",
                "解码 ns/对象",
                "PROCESS RSS bytes",
                "原域质量",
                "证据",
            ],
            _cell_rows(matrix, points, disclosures or {}),
            caption="完整固定矩阵；部分观测保留单元状态，不取得完成资格",
        )
        + "</section>",
        '<section id="workload"><h2>固定工作负载与来源平衡</h2>'
        + '<p class="muted">工作负载汇总保留全部核心单元；缺口阻止该成员的汇总。'
        + "来源平衡先按源内 RawBits 加权，再对独立来源组等权；它是固定来源的描述量。</p>"
        + _table(
            ["成员", "配置", "状态", "完成 / 固定单元", "大小比", "编码 MB/s", "解码 MB/s"],
            [] if audit_issues else _aggregate_rows(analysis),
            caption="完整固定核心工作负载；吞吐使用语义 raw bytes",
        )
        + _table(
            [
                "成员",
                "配置",
                "状态",
                "完成 / 固定来源",
                "等权大小比",
                "编码 ns/raw bit",
                "解码 ns/raw bit",
                "证据",
            ],
            _source_rows(extension),
            caption="独立来源等权描述；没有总体来源置信区间",
        )
        + "</section>",
        '<section id="inference"><h2>配对效应与置信区间</h2>'
        + '<p class="muted">比值为第一成员平均进程时间 / 第二成员平均进程时间；'
        + "区间由配对 schedule block 重采样。预登记与探索比较分开披露，"
        + "区间反映本语料和机器的运行噪声。</p>"
        + _table(
            [
                "数据对象",
                "第一 / 第二",
                "方向",
                "推断角色",
                "时间比",
                "CI",
                "配对 blocks",
                "判定",
                "证据",
            ],
            [] if audit_issues else _pair_rows(analysis.get("paired_comparisons", [])),
            caption="原始统计政策、实际配对数、精度与实践差异阈值见证据",
        )
        + "</section>",
        '<section id="pareto"><h2>实际成本 Pareto 与能力视图</h2>'
        + '<p class="muted">Pareto 按合同比较完整恢复 FinalBits 或 API serialized bits，'
        + "以及编码时间、解码时间和 PROCESS RSS；"
        + "无界或率控方法还须具备有效的逐列原域质量目标。部分观测前沿明确保留缺口。"
        + "前沿是描述性点估计；经验质量不会授予固定误差资格。</p>"
        + _table(
            ["数据对象", "前沿范围", "观察 / 固定点", "前沿单元", "目标 / 缺口"],
            _pareto_rows(extension),
            caption="按相同数据对象与公共投影分区",
        )
        + "".join(
            _details(name, rows)
            for name, rows in extension.get("coverage_matrices", {}).get("views", {}).items()
        )
        + '<p class="muted">SOURCE、PORT、BENCH 与 PIPELINE 证据分开；'
        + "UNKNOWN 保持未知。</p></section>",
        '<section id="evidence"><h2>原始证据与完整身份</h2>'
        + _raw_links(raw_links or {})
        + _details(
            "证据身份与校验摘要",
            {
                key: analysis.get(key)
                for key in (
                    "comparison_id",
                    "analysis_id",
                    "analysis_policy_id",
                    "raw_sha256",
                    "audited_trials_sha256",
                    "artifact_audit",
                    "conclusion_scope",
                )
            },
        )
        + _details(
            "扩展身份与范围",
            {
                key: extension.get(key)
                for key in ("extension_id", "schema_version", "corpus_id", "conclusion_scope")
            },
        )
        + "</section>",
    ]
    navigation = (
        '<nav aria-label="报告导航">'
        + "".join(
            '<a href="#' + target + '">' + label + "</a>"
            for target, label in (
                ("scope", "范围"),
                ("methods", "方法"),
                ("protocol", "协议"),
                ("cells", "单元"),
                ("workload", "汇总"),
                ("inference", "CI"),
                ("pareto", "Pareto"),
                ("evidence", "原始证据"),
            )
        )
        + "</nav>"
    )
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        + '<meta name="viewport" content="width=device-width,initial-scale=1">'
        + "<title>"
        + _escape(title)
        + " · TSBenchMark</title><style>"
        + _STYLE
        + "</style></head><body><main>"
        + '<header><div class="eyebrow">TSBENCHMARK · V3.2 · FROZEN COMPARISON</div><h1>'
        + _escape(title)
        + '</h1><p class="identity">'
        + _escape(analysis.get("comparison_id", "N/A"))
        + "</p>"
        + navigation
        + "</header>"
        + "".join(sections)
        + "</main></body></html>"
    )
