#!/usr/bin/env python3
"""Read-only scope joins for current active entries, stages and frozen groups.

Build a content-addressed documentation snapshot; never edit the candidate CSV,
scope, registration, retirement decisions, or grant qualification. Validation
rebuilds from explicitly frozen inputs and rejects changed documentation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from candidate_integration_ledger import validate_ledger  # noqa: E402

from tscompbench.comparison import GroupSpec, method_id  # noqa: E402
from tscompbench.ids import stable_id  # noqa: E402

DEFAULT_BUNDLES = (
    "configs/comparisons/g-byte-ll-v32-20261010-v3.json",
    "configs/comparisons/g-float-ll-f64-v32-20261010-v3.json",
    "configs/comparisons/g-int-ll-i16-v32-20261011-port-v2.json",
    "configs/comparisons/g-float-abs-v32-20261010-v3.json",
    "configs/comparisons/g-quality-v32-20261011-port-v2.json",
    "configs/comparisons/g-byte-model-v32-20261010-v5.json",
    "configs/comparisons/g-timestamp-v32-20261011-port-v2.json",
    "configs/comparisons/g-float-ll-f32-v32-20261010-v1.json",
    "configs/comparisons/g-stream-ll-v32-20261010.json",
    "configs/comparisons/g-query-ll-variants-v32-20261011-port-v2.json",
)
BYTE_KEYS = {
    "brotli-stream",
    "deflate-zlib",
    "lz4-frame",
    "lzss-dipperstein-c",
    "lzss-raw",
    "snappy-raw",
    "xz-stream",
    "zstd-frame",
}
RELATIONSHIPS = (
    {
        "keys": ["alp", "alp-rd"],
        "relationship": "SHARED_SOURCE_DISTINCT_DECIMAL_AND_RD_METHODS",
        "equivalence_policy": "FOLLOW_TASK_GROUPSPEC_DISTINCT_CLASSES",
    },
    {
        "keys": ["abba", "fabba"],
        "relationship": "RELATED_APPROXIMATION_FAMILY_DISTINCT_DIGITIZATION_METHODS",
        "equivalence_policy": "FOLLOW_TASK_GROUPSPEC_DISTINCT_CLASSES",
    },
    {
        "keys": ["neats-lossless-i64", "leats-lossless-i64"],
        "relationship": "SHARED_SOURCE_DISTINCT_NEATS_LEATS_METHODS",
        "equivalence_policy": "FOLLOW_TASK_GROUPSPEC_DISTINCT_CLASSES",
    },
    {
        "keys": ["sprintz-delta", "sprintz-delta-u8"],
        "relationship": "SAME_PREDICTOR_DIFFERENT_NATIVE_TYPED_ENTRY",
        "equivalence_policy": "U8_ENTRY_NOT_AN_ADDITIONAL_I16_COMMON_METHOD",
    },
    {
        "keys": ["sprintz-fire", "sprintz-fire-u8", "sprintz-fire-huff0"],
        "relationship": "SHARED_FIRE_PREDICTOR_SEPARATE_ENTROPY_PIPELINE",
        "equivalence_policy": "U8_NOT_EXTRA_I16_METHOD_HUFF0_PIPELINE_DISTINCT_IN_GROUP",
    },
    {
        "keys": ["huff0", "sprintz-fire-huff0"],
        "relationship": "HUFF0_IS_ENTROPY_CHILD_AND_SEPARATE_COMPLETE_BYTE_ENTRY",
        "equivalence_policy": "CHILD_CALLS_DO_NOT_ADD_INDEPENDENT_PIPELINE_METHODS",
    },
    {
        "keys": ["lzss-raw", "lzss-dipperstein-c"],
        "relationship": "LZSS_FAMILY_DIFFERENT_SOURCE_IMPLEMENTATIONS",
        "equivalence_policy": "FOLLOW_TASK_GROUPSPEC_EQUIVALENCE_NOT_IMPLEMENTATION_ENTRY_COUNT",
    },
)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def declared_stages(key: str) -> tuple[list[str], str]:
    if key == "simdcomp-u32":
        return ["UINT32_BITPACK_PRIMITIVE"], "API_PRIMITIVE"
    if key in {"fse", "huff0"}:
        return ["ENTROPY_BACKEND", "COMPLETE_BYTE_FRAME"], "COMPLETE_CODEC_AND_CHILD_COMPONENT"
    if key == "sprintz-fire-huff0":
        return ["FIRE_PREDICTION_RLE", "HUFF0_ENTROPY", "PIPELINE_FRAME"], "COMPLETE_PIPELINE"
    if key in {"deepzip", "dzip"}:
        return ["MODEL_PROBABILITY", "ENTROPY_CODING", "MODEL_RECOVERY_FRAME"], "COMPLETE_PIPELINE"
    if key in {"abba", "fabba"}:
        return [
            "APPROXIMATE_REPRESENTATION",
            "CODEBOOK_AND_RECONSTRUCTION_FRAME",
        ], "COMPLETE_PIPELINE"
    if key in BYTE_KEYS:
        return ["BYTE_BACKEND", "COMPLETE_BYTE_FRAME"], "COMPLETE_CODEC_AND_PIPELINE_BACKEND"
    if key in {"serf-qt", "serf-xor", "zfp-accuracy-1d"}:
        return ["BOUNDED_LOSSY_VALUE_CODING", "RECOVERY_FRAME"], "COMPLETE_CODEC"
    if key.startswith("sprintz-"):
        return ["INTEGER_PREDICTION_RLE", "INTEGER_FRAME"], "COMPLETE_CODEC"
    if key in {"neats-lossless-i64", "leats-lossless-i64"}:
        return ["INTEGER_MODEL_AND_EXCEPTIONS", "INDEXED_RECOVERY_FRAME"], "COMPLETE_CODEC"
    return ["LOSSLESS_NUMERIC_VALUE_CODING", "RECOVERY_FRAME"], "COMPLETE_CODEC"


def build_document(root: Path, bundles: tuple[str, ...]) -> dict:
    provenance = validate_ledger(root)
    scope = json.loads((root / "registry/algorithm_scope.json").read_text())
    active = set(scope["registered_codecs"])
    excluded = set(scope["framework_oracles"]) | set(scope["retained_out_of_scope_registrations"])
    if len(active) != 33 or active & excluded:
        raise ValueError("this V3.2 snapshot requires the reviewed 33-entry active denominator")
    memberships: dict[str, list[dict]] = {}
    group_rows = []
    observed_names = set()
    dependencies = {"registry/algorithm_scope.json", "registry/candidate_integration_ledger.json"}
    for relative in bundles:
        raw = json.loads((root / relative).read_text())
        group = GroupSpec.from_document(raw["group"])
        document = group.to_document()
        name = document["name"]
        if name in observed_names:
            raise ValueError("select exactly one explicit frozen bundle per common group")
        observed_names.add(name)
        eq = {member: row for row in document["method_equivalence"] for member in row["members"]}
        for member in document["members"]:
            key = member["codec_key"]
            if key not in active:
                raise ValueError(f"frozen group contains a non-active entry: {key}")
            memberships.setdefault(key, []).append(
                {
                    "group_name": name,
                    "group_id": group.id,
                    "bundle": relative,
                    "bundle_sha256": file_sha(root / relative),
                    "member_id": member["member_id"],
                    "role": member["role"],
                    "method_id": method_id(member["method"]),
                    "method_equivalence": eq[member["member_id"]],
                    "shared_code_tags": member["shared_code_tags"],
                    "admission_status": "FROZEN_SPEC_ONLY_NOT_EXECUTION_PASS",
                }
            )
        group_rows.append(
            {
                "group_name": name,
                "group_id": group.id,
                "bundle": relative,
                "bundle_sha256": file_sha(root / relative),
                "revision": document["revision"],
                "member_count": len(document["members"]),
                "core_equivalence_class_count": len(
                    {
                        eq[m["member_id"]]["class_id"]
                        for m in document["members"]
                        if m["role"] == "CORE"
                    }
                ),
                "status": "FROZEN_SPEC_ONLY_NOT_EXECUTION_PASS",
            }
        )
        dependencies.add(relative)
    rows = []
    for key in sorted(active):
        manifest_path = f"registry/codecs/{key}.json"
        manifest = json.loads((root / manifest_path).read_text())
        candidates = [
            row
            for row in provenance["records"]
            if any(
                r["key"] == key and r["scope_status"] == "IN_SCOPE" for r in row["registrations"]
            )
        ]
        if {row["original_ref"]["id"] for row in candidates} != set(
            scope["registered_codecs"][key]
        ):
            raise ValueError(f"candidate mapping changed active provenance: {key}")
        stages, role = declared_stages(key)
        frozen = memberships.get(key, [])
        mids = {row["method_id"] for row in frozen}
        if len(mids) > 1:
            raise ValueError(f"cross-group MethodID is inconsistent: {key}")
        aliases = []
        for alias_path in sorted((root / "registry/codecs/aliases").glob("*.json")):
            alias = json.loads(alias_path.read_text())
            if alias.get("canonical_key") == key:
                aliases.append(alias.get("key", alias_path.stem))
            dependencies.add(alias_path.relative_to(root).as_posix())
        rows.append(
            {
                "codec_key": key,
                "manifest": manifest_path,
                "manifest_sha256": file_sha(root / manifest_path),
                "source_artifact_id": manifest["identity"]["source_artifact_id"],
                "declared_family": manifest["identity"]["family"],
                "object_level": manifest["classification"]["object_level"],
                "declared_tracks": manifest["classification"]["tracks"],
                "stage_roles": stages,
                "solution_role": role,
                "stage_evidence_status": "DECLARED_ROLES_NOT_AN_EXECUTION_TRACE",
                "stage_evidence": [manifest_path, *manifest["identity"].get("citations", [])],
                "candidate_provenance": [
                    {
                        field: row[field]
                        for field in (
                            "candidate_id",
                            "record_id",
                            "name",
                            "original_ref",
                            "legacy_candidate_id",
                            "mapping_status",
                            "merged_sources",
                            "related_retired_implementation_keys",
                        )
                    }
                    for row in candidates
                ],
                "method_id": next(iter(mids), None),
                "equivalence_status": "TASK_GROUPSPEC_FROZEN"
                if frozen
                else "NOT_FROZEN_FOR_COMMON_TASK",
                "comparison_memberships": frozen,
                "aliases_do_not_increase_denominator": sorted(aliases),
                "family_relationships": [
                    relation for relation in RELATIONSHIPS if key in relation["keys"]
                ],
                "declared_extension_features": manifest["features"],
                "qualification_status": "READ_SEPARATE_FRESH_EVIDENCE_NOT_GRANTED_BY_ROLE_LEDGER",
                "remaining_group_condition": None
                if frozen
                else ("FREEZE_TASK_CORPUS_EQUIVALENCE_CONFIG_AND_PERFORMANCE_EVIDENCE"),
            }
        )
        dependencies.add(manifest_path)
    counts = Counter(row["mapping_status"] for row in provenance["records"])
    document = {
        "schema_version": "tscb.active-stage-role-ledger.v1",
        "status": "CURRENT_ACTIVE_SCOPE_PROVENANCE_AND_DECLARED_ROLES_ONLY",
        "policy": {
            "no_new_algorithms": True,
            "scope_csv_retirement_and_registration_unchanged": True,
            "group_admission_is_not_qualification_or_formal_completion": True,
            "equivalence_is_task_specific_not_a_global_family_count": True,
            "stage_roles_are_not_measured_stage_traces": True,
            "long_term_majority_candidate_integration_complete": False,
        },
        "historical_mapping": {
            "selection": provenance["selection"],
            "legacy_scope": provenance["legacy_scope"],
            "review_status": provenance["review_status"],
            "content_sha256": provenance["content_sha256"],
            "mapping_counts": dict(sorted(counts.items())),
            "coverage_denominator": provenance["coverage_denominator"],
            "records": [
                {
                    field: row[field]
                    for field in (
                        "candidate_id",
                        "record_id",
                        "name",
                        "original_ref",
                        "legacy_candidate_id",
                        "mapping_status",
                        "merged_sources",
                        "related_retired_implementation_keys",
                        "destinations",
                    )
                }
                for row in provenance["records"]
            ],
        },
        "active_entry_count": len(rows),
        "active_candidate_record_count": len(
            {record["candidate_id"] for row in rows for record in row["candidate_provenance"]}
        ),
        "entries_in_selected_groups": sum(bool(row["comparison_memberships"]) for row in rows),
        "entries_without_selected_group": [
            row["codec_key"] for row in rows if not row["comparison_memberships"]
        ],
        "groups": group_rows,
        "entries": rows,
        "input_files": [
            {"path": relative, "sha256": file_sha(root / relative)}
            for relative in sorted(dependencies)
        ],
    }
    document["ledger_id"] = stable_id("active-stage-role-ledger-v32", document)
    return document


def markdown(document: dict) -> str:
    mapping = document["historical_mapping"]
    lines = [
        "# V3.2 当前活动入口的 stage、方法等价与共同组映射",
        "",
        "本表只连接现有 33 个入口的声明角色与冻结 GroupSpec；不授予资格或正式完成。",
        "未入选组的入口保留待冻结条件，alias、参数、build/ISA 和 child 调用不新增方法分母。",
        "",
        f"台账身份：`{document['ledger_id']}`。",
        "",
        f"当前 CSV {mapping['selection']['record_count']} 条"
        f"（SHA `{mapping['selection']['sha256']}`）；",
        f"旧 scope {mapping['legacy_scope']['record_count']} 条"
        f"（清单 SHA `{mapping['legacy_scope']['selection_sha256']}`）。",
        "163 条旧记录保留明确名称/来源/变体映射，3 条新记录不获准入；"
        "历史退出关系与合并来源保留在 JSON。",
        "使用清单 SHA + 记录 ID 连接命名空间，不用重编号后的裸 V/T ID 解释退出决定。",
        "",
        f"33 个活动 key 对应 {document['active_candidate_record_count']} 条候选记录；",
        f"选定 {len(document['groups'])} 组涉及 {document['entries_in_selected_groups']} 个入口。"
        "候选记录、不同方法、实现入口与完成组是不同口径。",
        "长期多数候选的适用方法/角色分母仍未冻结，本表不声明长期多数集成完成。",
        "",
        "| 入口 | 当前 / 旧候选 ID | stage 声明 | 方法等价类 / 状态 | 冻结组角色 |",
        "|---|---|---|---|---|",
    ]
    for row in document["entries"]:
        ids = ", ".join(
            f"{c['record_id']}/{c['original_ref']['id']}" for c in row["candidate_provenance"]
        )
        memberships = row["comparison_memberships"]
        eq = (
            ", ".join(sorted({m["method_equivalence"]["class_id"] for m in memberships}))
            or "共同任务未冻结"
        )
        groups = (
            "; ".join(f"{m['group_name']}:{m['role']}" for m in memberships)
            or "未入选定组，仍需适用资格"
        )
        lines.append(
            f"| {row['codec_key']} | {ids} | {', '.join(row['stage_roles'])} | {eq} | {groups} |"
        )
    lines += [
        "",
        "stage 是 manifest/规格支持的角色，不是从时间差推导出的实测子阶段。",
        "共享 family/source 不自动等价；ALP/ALP-RD、ABBA/fABBA、NeaTS/LeaTS、"
        "Sprintz predictor/entropy",
        "按实际 GroupSpec 保留不同类。u8 Sprintz 入口不增加 i16 任务的方法数量。两个 LZSS 实现",
        "遵循各任务 GroupSpec 冻结的方法等价规则，不自动以两个入口计为两个方法；",
        "未入选共同任务的快照不声明它们已有冻结的共同等价关系。",
        "",
        "默认选定 bundle 的 revision 与 SHA 均保留在 JSON；"
        "新冻结版本需显式 --bundles 并生成新台账。",
        "该工具不读取本地 build 成败推断活动，也不把既有历史 parity 转成 fresh PASS。",
        "",
    ]
    return "\n".join(lines)


def write_or_verify(path: Path, payload: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != payload:
            raise ValueError(f"immutable ledger already exists with different content: {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--bundles", nargs="+", default=DEFAULT_BUNDLES)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.output.resolve() in {
        ROOT / "registry/candidate_integration_ledger.json",
        ROOT / "registry/algorithm_scope.json",
        ROOT / "algorithm_implementation_plan.csv",
    }:
        parser.error("role documentation cannot overwrite reviewed scope or candidate evidence")
    document = build_document(ROOT, tuple(args.bundles))
    encoded = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.validate:
        if json.loads(args.output.read_text()) != document:
            raise ValueError("role ledger or frozen inputs changed; generate a new snapshot")
        if args.markdown_output and args.markdown_output.read_text() != markdown(document):
            raise ValueError("role ledger markdown differs from the frozen JSON")
    else:
        write_or_verify(args.output, encoded)
        if args.markdown_output:
            write_or_verify(args.markdown_output, markdown(document))
    print(
        json.dumps(
            {
                "status": "PASS_DECLARED_ROLE_PROVENANCE_ONLY",
                "ledger_id": document["ledger_id"],
                "active_entries": document["active_entry_count"],
                "selected_group_entries": document["entries_in_selected_groups"],
                "mapping_counts": document["historical_mapping"]["mapping_counts"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
