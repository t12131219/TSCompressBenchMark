#!/usr/bin/env python3
"""Freeze the complete V3.2 specification and its 117 review cross-references.

This is a coverage ledger, not an automatic implementation acceptance oracle.
Every prose/list/table clause outside example code is retained, so implied child
requirements and delivery clauses cannot disappear in a keyword-only inventory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "plan": "TimeSeries_Compression_Benchmark_V3_工程实施总计划.md",
    "review": "docs/reviews/independent_benchmark_review_20261010.md",
    "matrix": "docs/algorithm_capability_support_matrix_20261010.md",
}
OUTPUT = ROOT / "docs/reviews/v32_requirement_ledger_20261010.json"
REQUIRED = re.compile(r"\bMUST\b|必须|必需|不得|禁止|不能|须")
HEADING = re.compile(r"^#{2,4}\s+(\d+(?:\.\d+)*)\.?\s+(.*)")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clauses(path: Path) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    section, title, in_code, inherited = "preamble", "", False, False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        heading = HEADING.match(stripped)
        if heading:
            section, title = heading.groups()
            inherited = False
            continue
        if stripped.startswith("#") or re.fullmatch(r"\|[\s|:-]+\|", stripped):
            continue
        is_list = bool(re.match(r"^(?:[-*]|\d+\.)\s", stripped))
        is_table = stripped.startswith("|")
        required = bool(REQUIRED.search(stripped)) or (is_list and inherited)
        if not is_list and not is_table:
            inherited = required and stripped.endswith((":", "："))
        kind = "NORMATIVE_REQUIREMENT" if required else "SPECIFICATION_CLAUSE"
        if section == "15" and re.match(r"^\| [A-G]\.", stripped):
            kind = "STAGE_DELIVERY"
        elif section == "15.4" and re.match(r"^\| L[0-6]\.", stripped):
            kind = "LONG_TERM_DELIVERY"
        elif section in {"10.6", "17.1", "17.4"} and is_list:
            kind = "COMPLETION_GATE"
        elif section.startswith("23"):
            kind = "IMPLEMENTATION_NOTE"
        elif "交付" in stripped and section in {"15.1", "15.2", "15.3", "16.4", "17.1.1"}:
            kind = "DELIVERY_CLAUSE"
        applicable = "REQUIRES_DOMAIN_AND_TASK_ASSESSMENT"
        reason = "适用条款仍需按冻结任务与能力声明验收；该台账不凭文字或字段授予资格。"
        if section in {"11.1", "11.4"} or (section == "15" and stripped.startswith("| G.")):
            applicable = "OPTIONAL_FOR_CPU_CORE_RELEASE"
            reason = "设备/P3扩展不阻断不依赖该能力的CPU组；未声称设备可用或硬件验收通过。"
        elif section in {"11.2", "11.3"}:
            applicable = "REQUIRED_FOR_EXISTING_DECLARED_QUERY_OR_STREAM_PROFILE"
            reason = "已有query/stream声明仍须独立profile验收；未新增算法不免除此义务。"
        status = "REQUIRES_ACCEPTANCE_EVIDENCE"
        if kind in {"SPECIFICATION_CLAUSE", "IMPLEMENTATION_NOTE"}:
            status = "CONTEXT_ONLY_NO_ACCEPTANCE_CLAIM"
        if section == "15.4" and re.match(r"^\| L[1-6]\.", stripped):
            status = "PARTIAL_SCOPE_DEFERRED_BY_USER"
            reason = "仅新增算法成员延后；现有算法与框架合同的原文交付义务仍保留。"
        clauses.append(
            {
                "requirement_id": f"V32-{section}-L{number:04d}",
                "section": section,
                "section_title": title,
                "source": SOURCES["plan"],
                "line": number,
                "statement": stripped,
                "kind": kind,
                "explicit_must": bool(re.search(r"\bMUST\b", stripped)),
                "normative": required
                or kind
                in {"STAGE_DELIVERY", "LONG_TERM_DELIVERY", "COMPLETION_GATE", "DELIVERY_CLAUSE"},
                "applicability": applicable,
                "applicability_reason": reason,
                "implementation_status": status,
                "accepted_evidence": [],
                "remaining_gap": reason,
            }
        )
    return clauses


def build() -> dict[str, Any]:
    clauses = _clauses(ROOT / SOURCES["plan"])
    review_rows = []
    for number, line in enumerate((ROOT / SOURCES["review"]).read_text().splitlines(), 1):
        if line.startswith("| §"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            review_rows.append(
                {
                    "review_id": f"V31-REVIEW-{len(review_rows) + 1:03d}",
                    "original_section": cells[0],
                    "source": SOURCES["review"],
                    "line": number,
                    "statement": line,
                    "implementation_status": "REQUIRES_INDEPENDENT_ACCEPTANCE_AUDIT",
                    "accepted_evidence": [],
                }
            )
    if len(review_rows) != 117:
        raise ValueError(f"expected all 117 original section review rows, found {len(review_rows)}")
    matrix_rows = []
    for number, line in enumerate((ROOT / SOURCES["matrix"]).read_text().splitlines(), 1):
        if line.startswith("|") and not re.fullmatch(r"\|[\s|:-]+\|", line):
            matrix_rows.append({"source": SOURCES["matrix"], "line": number, "statement": line})
    core = [
        {
            "group_id": group,
            "scope_status": "REQUIRED_EXISTING_ALGORITHMS",
            "minimum_distinct_methods": 2,
            "minimum_independent_real_sources": 2,
            "implementation_status": "REQUIRES_CURRENT_FORMAL_AND_FIXED_CORPUS_EVIDENCE",
            "source_count_rule": "窗口、列、resampling和seed不增加独立来源；失败不缩核心分母。",
        }
        for group in ("G-BYTE-LL", "G-FLOAT-LL-F64", "G-INT-LL-I16", "G-FLOAT-ABS")
    ]
    deferred = [
        {
            "batch": f"L{batch}",
            "subject": "NEW_ALGORITHM_MEMBERS_ONLY",
            "status": "DEFERRED_BY_USER",
            "specification_preserved": True,
            "reason": "用户要求本轮使用已有算法完成V3.2，不新增算法；不删除长期规格。",
            "existing_algorithms_and_framework_obligations": "REQUIRED_WHEN_APPLICABLE",
        }
        for batch in range(1, 7)
    ]
    return {
        "schema_version": "tscb.v32-requirement-ledger.v1",
        "date": "2026-10-10",
        "purpose": "完整规范覆盖、用户范围覆盖与验收证据缺口；不是通过证明。",
        "sources": [
            {"role": role, "path": path, "sha256": digest(ROOT / path)}
            for role, path in SOURCES.items()
        ],
        "user_scope": {
            "new_algorithms": "DEFERRED_BY_USER",
            "existing_algorithms": "ACTIVE_SCOPE_PRESERVED",
            "historical_runs_and_identities": "READ_ONLY",
            "core_tasks": "NOT_NARROWED",
        },
        "coverage": {
            "plan_clause_count": len(clauses),
            "explicit_must_clause_count": sum(c["explicit_must"] for c in clauses),
            "clause_kind_counts": dict(sorted(Counter(c["kind"] for c in clauses).items())),
            "original_review_section_count": len(review_rows),
            "matrix_table_row_count": len(matrix_rows),
        },
        "core_groups": core,
        "deferred_additions": deferred,
        "requirements": clauses,
        "review_cross_references": review_rows,
        "capability_matrix_snapshot": matrix_rows,
        "acceptance_rules": [
            "accepted_evidence必须含可访问artifact与hash、任务域、当前身份及验收结果；候选代码或测试路径不能单独关闭全部条款。",
            "摘要/率验证器通过fixture只能关闭接口性质验证；没有对应实际codec不得声称算法资格或共同组完成。",
            "硬件未知不可写硬件不存在；可选CPU发布范围写OPTIONAL并给理由，"
            "已声明CPU stream/query不自动N/A。",
            "源码闭包、测量协议或身份变化使相关证据失效；历史PASS只读不重签。",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="verify complete source coverage without rewriting"
    )
    args = parser.parse_args()
    document = build()
    if args.check:
        saved = json.loads(OUTPUT.read_text())
        for field in ("sources", "coverage", "deferred_additions"):
            if saved.get(field) != document[field]:
                raise SystemExit(f"requirement ledger source/coverage drift: {field}")
        core_fields = (
            "group_id",
            "scope_status",
            "minimum_distinct_methods",
            "minimum_independent_real_sources",
            "source_count_rule",
        )
        if [{key: c[key] for key in core_fields} for c in saved["core_groups"]] != [
            {key: c[key] for key in core_fields} for c in document["core_groups"]
        ]:
            raise SystemExit("requirement ledger narrowed a core task or its denominator")
        saved_clauses = [(c["requirement_id"], c["statement"]) for c in saved["requirements"]]
        source_clauses = [(c["requirement_id"], c["statement"]) for c in document["requirements"]]
        if saved_clauses != source_clauses:
            raise SystemExit("requirement ledger omitted or changed a specification clause")
        for field in ("review_cross_references", "capability_matrix_snapshot"):
            keys = ("source", "line", "statement")
            observed = [{key: c[key] for key in keys} for c in saved[field]]
            required = [{key: c[key] for key in keys} for c in document[field]]
            if observed != required:
                raise SystemExit(f"requirement ledger omitted or changed source coverage: {field}")
        print(
            "PASS: complete V3.2 clauses, 117 review rows, core scope "
            "and deferred additions verified"
        )
    else:
        OUTPUT.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(document["coverage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
