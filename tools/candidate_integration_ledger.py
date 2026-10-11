"""Versioned candidate provenance; this ledger never grants codec admission.

Run ``python tools/candidate_integration_ledger.py validate`` to verify the
reviewed snapshot. ``draft --output ...`` creates a proposal for a new review;
it cannot overwrite the reviewed ledger or approve a changed CSV.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tscompbench.ids import canonical_json_bytes, stable_id  # noqa: E402

LEDGER_PATH = "registry/candidate_integration_ledger.json"
SCHEMA = "tscb.candidate-integration-ledger.v1"
REVIEWED = "REVIEWED_PROVENANCE_MAPPING_ONLY"
RECOMMENDATIONS = {"主集合保留", "扩展保留", "组件/配置/来源保留"}
NEW_REGISTRATIONS = {
    ("V131", "bzip2"): "bzip2-stream",
    ("V132", "lzsse2"): "lzsse2-raw",
    ("V133", "lzsse8"): "lzsse8-raw",
}
# These are implementation relationships, including retained constituent
# mechanisms. A retired combination does not retire each constituent method.
RETIRED_RELATIONSHIPS = {
    "corad": ["V11"],
    "delta-maskedvbyte-u32": ["T4"],
    "delta-simdcomp-u32": ["T1", "T53"],
    "delta-varint": ["T2", "T3"],
    "delta-zigzag-streamvbyte-modern64": ["T5"],
    "delta-zigzag-streamvbyte64": ["T5"],
    "fast-differential-u32": ["T1"],
    "fastpfor-simple8b-rle-u32": ["T65"],
    "for-simdcomp-u32": ["T66", "T53"],
    "influxdb-tsm-adaptive-timestamp": ["T121"],
    "maskedvbyte-u32": ["T28"],
    "prometheus-float-histogram-st": ["T108"],
    "prometheus-histogram-st": ["T108"],
    "prometheus-xor-chunk": ["T105", "T12"],
    "prometheus-xor2-chunk": ["T106"],
    "simple16-u28": ["T63"],
    "simple9-u28": ["T62"],
    "simple9hacked-u28": ["T62"],
    "streamvbyte-modern-u32": ["T27"],
    "streamvbyte-u32": ["T27"],
    "tristan": ["V10"],
    "walloc-1d": ["V108"],
    **{
        f"littleintpacker-{variant}-u32": ["T54", "T50"]
        for variant in ("bmi2", "horizontal", "pack32", "sc", "turbo")
    },
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def candidate_id(selection_sha256: str, record_id: str) -> str:
    return f"v1:candidate:sha256:{selection_sha256}:{record_id}"


def seal_ledger(document: dict) -> None:
    """Detect damaged snapshots, including when the local CSV is absent."""
    payload = {key: value for key, value in document.items() if key != "content_sha256"}
    document["content_sha256"] = sha256(canonical_json_bytes(payload))


def read_selection(path: Path) -> tuple[str, list[dict[str, str]]]:
    data = path.read_bytes()
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    required = {
        "记录ID",
        "来源表",
        "算法名称",
        "Benchmark建议",
        "原始记录ID",
        "合并来源原始ID",
        "合并来源明细JSON",
    }
    headers = reader.fieldnames or []
    if len(headers) != len(set(headers)) or not required <= set(headers):
        raise ValueError("candidate CSV has missing or duplicate headers")
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("candidate CSV has incomplete or excess columns")
    for column in ("记录ID", "原始记录ID"):
        ids = [row[column] for row in rows]
        if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[VT][1-9][0-9]*", x) for x in ids):
            raise ValueError(f"candidate CSV has duplicate or invalid {column}")
    if any(row["Benchmark建议"] not in RECOMMENDATIONS for row in rows):
        raise ValueError("candidate CSV has unreviewed recommendation category")
    return sha256(data), rows


def _original_ref(selection_sha: str, record_id: str) -> dict:
    # New V131..V133 and merged original IDs are NOT records of the old scope.
    return {
        "namespace": "CSV_DECLARED_ORIGINAL_RECORD_ID",
        "declared_by_selection_sha256": selection_sha,
        "id": record_id,
    }


def _role_and_batch(row: dict) -> tuple[str, str]:
    original = row["原始记录ID"]
    if original in {"V111", "V116", "V118"}:
        return "BACKEND_OR_PROVIDER", "L6"
    if original == "V130":
        return "SOURCE_FRAMEWORK_REFERENCE", "L0"
    if original in {"V123", "V124", "V127"}:
        return "QUALITY_OR_TRAINING_POLICY", "L3" if original != "V127" else "L4"
    role = (
        "COMPONENT_OR_CONFIGURATION"
        if row["Benchmark建议"] == "组件/配置/来源保留"
        else "METHOD_OR_SOLUTION_CANDIDATE"
    )
    category = row["一级分类"]
    if original.startswith("T"):
        batch = "L5" if "Hybrid TSDB" in category else "L2"
    elif "函数逼近" in category or original in {"V19", "V20", "V83", "V84", "V85", "V87"}:
        batch = "L3"
    elif "神经网络" in category or original in {"V10", "V11"}:
        batch = "L4"
    elif original in {"V112", "V113", "V114"}:
        batch = "L6"
    else:
        batch = "L1"
    return role, batch


def _merge_details(row: dict, selection_sha: str, current_ids: set[str]) -> list[dict]:
    try:
        details = json.loads(row["合并来源明细JSON"])
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid merged source JSON: {row['记录ID']}") from error
    if not isinstance(details, list):
        raise ValueError("merged source details must be a list")
    ids = [detail.get("来源ID") for detail in details if isinstance(detail, dict)]
    declared = [x.strip() for x in row["合并来源原始ID"].split(",") if x.strip()]
    if len(ids) != len(details) or len(ids) != len(set(ids)) or sorted(ids) != sorted(declared):
        raise ValueError(f"merged source IDs disagree: {row['记录ID']}")
    result = []
    for detail in details:
        targets = detail.get("合并目标", [])
        originals = detail.get("原始合并目标", [])
        if (
            detail.get("来源ID命名空间") != "原始记录ID"
            or detail.get("合并目标命名空间") != "记录ID"
            or not isinstance(targets, list)
            or not targets
            or len(targets) != len(set(targets))
            or row["记录ID"] not in targets
            or not set(targets) <= current_ids
            or not isinstance(originals, list)
            or row["原始记录ID"] not in originals
            or len(originals) != len(targets)
            or not isinstance(detail.get("来源字段"), dict)
        ):
            raise ValueError(f"ambiguous merged source namespace: {row['记录ID']}")
        result.append(
            {
                "source_ref": _original_ref(selection_sha, detail["来源ID"]),
                "target_candidate_ids": [candidate_id(selection_sha, x) for x in targets],
                "original_target_refs": [_original_ref(selection_sha, x) for x in originals],
                "preserved_difference": detail["保留差异"],
                "source_fields": detail["来源字段"],
            }
        )
    return result


def _registration(root: Path, key: str, in_scope: bool) -> dict:
    relative = f"registry/codecs/{key}.json"
    data = (root / relative).read_bytes()
    document = json.loads(data)
    return {
        "key": key,
        "scope_status": "IN_SCOPE" if in_scope else "RETAINED_OUT_OF_SCOPE",
        "manifest": relative,
        "manifest_sha256": sha256(data),
        "existing_v2_algorithm_id": stable_id("algorithm", document),
        "source_artifact_id": document["identity"]["source_artifact_id"],
        "implementation_id": None,
        "identity_status": "V2_REGISTRATION_SNAPSHOT_NOT_V3_METHOD_IDENTITY",
    }


def build_ledger(root: Path = ROOT, *, registration_snapshots: dict | None = None) -> dict:
    scope_data = (root / "registry/algorithm_scope.json").read_bytes()
    scope = json.loads(scope_data)
    selection_sha, rows = read_selection(root / scope["selection"]["path"])
    old_sha = scope["selection"]["sha256"]
    legacy = {record["id"]: record for record in scope["records"]}
    if len(legacy) != len(scope["records"]) or len(legacy) != scope["selection"]["record_count"]:
        raise ValueError("legacy scope contains duplicate or incomplete records")
    if set(RETIRED_RELATIONSHIPS) != set(scope["removed_codecs"]):
        raise ValueError("retired implementation relationships require a new scope review")
    current_ids = {row["记录ID"] for row in rows}
    original_to_current = {row["原始记录ID"]: row["记录ID"] for row in rows}
    if not set(legacy) <= set(original_to_current):
        raise ValueError("candidate mapping omits records from the frozen legacy scope")
    excluded = set(scope["excluded_plan_records"])
    if not excluded <= set(legacy):
        raise ValueError("legacy exclusions refer to unknown records")
    records = []

    def registration(key: str, in_scope: bool) -> dict:
        if registration_snapshots is not None:
            return registration_snapshots[key]
        return _registration(root, key, in_scope)

    for row in rows:
        record_id, original_id = row["记录ID"], row["原始记录ID"]
        old = legacy.get(original_id)
        merged = _merge_details(row, selection_sha, current_ids)
        if any(
            [original_to_current.get(ref["id"]) for ref in detail["original_target_refs"]]
            != [target.rsplit(":", 1)[-1] for target in detail["target_candidate_ids"]]
            for detail in merged
        ):
            raise ValueError(f"merged target mapping disagrees: {record_id}")
        group = "ValueCompress" if record_id.startswith("V") else "TimeStampCompress"
        names = {(group, row["算法名称"])}
        for detail in merged:
            fields = detail["source_fields"]
            source_group = (
                "ValueCompress"
                if detail["source_ref"]["id"].startswith("V")
                else "TimeStampCompress"
            )
            names.add((source_group, fields.get("算法/方法") or fields.get("具体算法/变体")))
        if old is not None and (
            old["name"] != row["算法名称"]
            or old["recommendation"] != row["Benchmark建议"]
            or set(old["merged_ids"]) != {x["source_ref"]["id"] for x in merged}
            or {(x["group"], x["name"]) for x in old["source_names"]} != names
        ):
            raise ValueError(f"ambiguous legacy name/source/variant mapping: {record_id}")
        active_keys = (
            sorted(key for key, ids in scope["registered_codecs"].items() if original_id in ids)
            if old
            else []
        )
        if original_id in excluded and active_keys:
            raise ValueError("excluded legacy candidate has an active registration")
        retained_key = (
            NEW_REGISTRATIONS.get((original_id, row["算法名称"])) if old is None else None
        )
        if retained_key and retained_key not in scope["retained_out_of_scope_registrations"]:
            raise ValueError("new candidate registration is not retained out of scope")
        role, batch = _role_and_batch(row)
        destinations = []
        if original_id in excluded:
            destinations.append(
                {
                    "kind": "EXPLICITLY_RETIRED",
                    "decision": "registry/algorithm_scope.json#/excluded_plan_records",
                    "legacy_candidate_id": candidate_id(old_sha, original_id),
                    "required_change": "EXPLICIT_NEW_SCOPE_DECISION_AND_NEW_QUALIFICATION",
                }
            )
        else:
            if active_keys:
                destinations.append({"kind": "ACTIVE_REGISTRATION", "keys": active_keys})
            if retained_key:
                destinations.append(
                    {
                        "kind": "RETAINED_OUT_OF_SCOPE_REGISTRATION",
                        "keys": [retained_key],
                        "missing_conditions": [
                            "EXPLICIT_SCOPE_ADMISSION",
                            "BUILD_AND_QUALIFICATION",
                        ],
                    }
                )
            destinations.append(
                {
                    "kind": "PLANNED_BATCH_EVALUATION",
                    "batch": batch,
                    "role": role,
                    "required_evidence": [
                        "SOURCE_AND_IMPLEMENTATION_REVIEW",
                        "TASK_RECOVERY_AND_COST_CONTRACT",
                        "BUILD_AND_QUALIFICATION",
                        "FROZEN_COMMON_GROUP_AND_CORPUS",
                    ],
                }
            )
        records.append(
            {
                "candidate_id": candidate_id(selection_sha, record_id),
                "record_id": record_id,
                "csv_row_sha256": sha256(canonical_json_bytes(row)),
                "name": row["算法名称"],
                "source_sheet": row["来源表"],
                "recommendation": row["Benchmark建议"],
                "declared_role": row.get("角色/时序专用程度") or row.get("层级/角色"),
                "planned_role": role,
                "original_ref": _original_ref(selection_sha, original_id),
                "original_numeric_id": row.get("原始ID"),
                "legacy_candidate_id": candidate_id(old_sha, original_id) if old else None,
                "mapping_status": "EXACT_NAME_SOURCE_VARIANT_MATCH"
                if old
                else "NEW_RECORD_NO_ADMISSION",
                "source_names": [{"group": g, "name": n} for g, n in sorted(names)],
                "source_urls": row.get("开源/实现网址", ""),
                "reference_urls": row.get("论文/官方资料") or row.get("论文/官方文档", ""),
                "merged_sources": merged,
                "method_id": None,
                "method_identity_status": "REQUIRES_SOURCE_REVIEW_AND_EQUIVALENCE_POLICY",
                "registrations": [registration(key, True) for key in active_keys]
                + ([registration(retained_key, False)] if retained_key else []),
                "related_retired_implementation_keys": sorted(
                    key for key, ids in RETIRED_RELATIONSHIPS.items() if original_id in ids
                )
                if old
                else [],
                "destinations": destinations,
                "comparison_group_ids": [],
                "comparison_group_status": "NOT_FROZEN",
            }
        )
    counts = Counter(record["mapping_status"] for record in records)
    document = {
        "schema_version": SCHEMA,
        "review_status": "DRAFT_REQUIRES_EXPLICIT_REVIEW",
        "selection": {
            "path": scope["selection"]["path"],
            "sha256": selection_sha,
            "record_count": len(rows),
        },
        "legacy_scope": {
            "path": "registry/algorithm_scope.json",
            "file_sha256": sha256(scope_data),
            "selection_sha256": old_sha,
            "record_count": len(legacy),
        },
        "policy": {
            "scope_and_retirement_decisions_unchanged": True,
            "registration_and_qualification_not_granted": True,
            "original_ids_declared_by_current_csv_are_not_legacy_scope_membership": True,
            "existing_v2_algorithm_ids_are_not_v3_method_or_implementation_ids": True,
            "candidate_records_are_not_independent_method_counts": True,
            "unresolved_mappings_block_automatic_scope_mutation": True,
        },
        "coverage_denominator": {
            "raw_record_count": len(rows),
            "excluded_legacy_record_count": len(excluded),
            "planned_record_count": len(rows) - len(excluded),
            "independent_method_denominator": None,
            "status": "METHOD_EQUIVALENCE_AND_APPLICABLE_ROLE_SET_NOT_FROZEN",
        },
        "mapping_counts": dict(sorted(counts.items())),
        "retirement_relationship_evidence": "docs/algorithm_retirement_20261010.md",
        "retired_implementation_legacy_records": RETIRED_RELATIONSHIPS,
        "records": records,
    }
    seal_ledger(document)
    return document


def _validate_snapshot(document: dict, scope: dict, scope_data: bytes) -> None:
    if document.get("schema_version") != SCHEMA or document.get("review_status") != REVIEWED:
        raise ValueError("candidate ledger is not a reviewed provenance mapping")
    payload = {key: value for key, value in document.items() if key != "content_sha256"}
    if document.get("content_sha256") != sha256(canonical_json_bytes(payload)):
        raise ValueError("candidate ledger content checksum mismatch")
    if document.get("legacy_scope") != {
        "path": "registry/algorithm_scope.json",
        "file_sha256": sha256(scope_data),
        "selection_sha256": scope["selection"]["sha256"],
        "record_count": scope["selection"]["record_count"],
    }:
        raise ValueError("candidate ledger does not bind the frozen legacy scope")
    selection = document["selection"]
    if (
        selection["path"] != scope["selection"]["path"]
        or not re.fullmatch(r"[a-f0-9]{64}", selection["sha256"])
        or document["retired_implementation_legacy_records"] != RETIRED_RELATIONSHIPS
        or set(RETIRED_RELATIONSHIPS) != set(scope["removed_codecs"])
    ):
        raise ValueError("candidate ledger changes selection or retirement provenance")
    records = document["records"]
    ids = [record["record_id"] for record in records]
    originals = [record["original_ref"]["id"] for record in records]
    if len(records) != selection["record_count"] or len(ids) != len(set(ids)):
        raise ValueError("candidate ledger contains duplicate or incomplete records")
    if len(originals) != len(set(originals)):
        raise ValueError("candidate ledger has ambiguous original IDs")
    legacy = {r["id"]: r for r in scope["records"]}
    if not set(legacy) <= set(originals):
        raise ValueError("candidate ledger omits frozen legacy records")
    excluded = set(scope["excluded_plan_records"])
    for record in records:
        original = record["original_ref"]["id"]
        old = legacy.get(original)
        expected_status = "EXACT_NAME_SOURCE_VARIANT_MATCH" if old else "NEW_RECORD_NO_ADMISSION"
        if (
            record["candidate_id"] != candidate_id(selection["sha256"], record["record_id"])
            or record["original_ref"] != _original_ref(selection["sha256"], original)
            or record["mapping_status"] != expected_status
            or record["legacy_candidate_id"]
            != (candidate_id(scope["selection"]["sha256"], original) if old else None)
            or (old and record["name"] != old["name"])
            or (old and record["recommendation"] != old["recommendation"])
            or (old and record["source_names"] != old["source_names"])
            or (
                old
                and set(old["merged_ids"])
                != {detail["source_ref"]["id"] for detail in record["merged_sources"]}
            )
        ):
            raise ValueError("candidate ledger has an ambiguous version/name mapping")
        kinds = {d["kind"] for d in record["destinations"]}
        if ("EXPLICITLY_RETIRED" in kinds) != (original in excluded):
            raise ValueError("candidate ledger reinterprets a legacy retirement decision")
        if original in excluded and record["destinations"] != [
            {
                "kind": "EXPLICITLY_RETIRED",
                "decision": "registry/algorithm_scope.json#/excluded_plan_records",
                "legacy_candidate_id": candidate_id(scope["selection"]["sha256"], original),
                "required_change": "EXPLICIT_NEW_SCOPE_DECISION_AND_NEW_QUALIFICATION",
            }
        ]:
            raise ValueError("retired candidate cannot acquire a planned admission destination")
        if original not in excluded and (
            not kinds
            <= {
                "ACTIVE_REGISTRATION",
                "RETAINED_OUT_OF_SCOPE_REGISTRATION",
                "PLANNED_BATCH_EVALUATION",
            }
            or "PLANNED_BATCH_EVALUATION" not in kinds
        ):
            raise ValueError("candidate ledger has no concrete batch evaluation destination")
        in_scope = {r["key"] for r in record["registrations"] if r["scope_status"] == "IN_SCOPE"}
        expected = {key for key, refs in scope["registered_codecs"].items() if original in refs}
        if in_scope != expected:
            raise ValueError("candidate ledger changes active registration relationships")
        retained = {
            r["key"]
            for r in record["registrations"]
            if r["scope_status"] == "RETAINED_OUT_OF_SCOPE"
        }
        retained_key = NEW_REGISTRATIONS.get((original, record["name"])) if old is None else None
        if retained != ({retained_key} if retained_key else set()):
            raise ValueError("candidate ledger changes retained out-of-scope relationships")
        if len(record["registrations"]) != len(in_scope | retained):
            raise ValueError("candidate ledger has duplicate or invalid registration status")
        active_destinations = [
            d for d in record["destinations"] if d["kind"] == "ACTIVE_REGISTRATION"
        ]
        if active_destinations != (
            [{"kind": "ACTIVE_REGISTRATION", "keys": sorted(expected)}] if expected else []
        ):
            raise ValueError("candidate destination disagrees with active scope")
        if record["related_retired_implementation_keys"] != sorted(
            key for key, refs in RETIRED_RELATIONSHIPS.items() if original in refs
        ):
            raise ValueError("candidate ledger loses retired implementation relationships")
        for registration in record["registrations"]:
            if (
                registration["manifest"] != f"registry/codecs/{registration['key']}.json"
                or not re.fullmatch(r"[a-f0-9]{64}", registration["manifest_sha256"])
                or not registration["existing_v2_algorithm_id"].startswith("v2:algorithm:sha256:")
                or not registration["source_artifact_id"].startswith("v2:source-artifact:sha256:")
            ):
                raise ValueError("candidate ledger has invalid registration provenance")
        for detail in record["merged_sources"]:
            source_ref = detail["source_ref"]
            if source_ref != _original_ref(selection["sha256"], source_ref["id"]):
                raise ValueError("merged source ID has an ambiguous namespace")
            target_ids = detail["target_candidate_ids"]
            target_originals = detail["original_target_refs"]
            by_original = dict(zip(originals, ids, strict=True))
            if (
                record["candidate_id"] not in target_ids
                or len(target_ids) != len(set(target_ids))
                or any(
                    ref != _original_ref(selection["sha256"], ref["id"]) for ref in target_originals
                )
                or [
                    candidate_id(selection["sha256"], by_original.get(ref["id"], ""))
                    for ref in target_originals
                ]
                != target_ids
            ):
                raise ValueError("merged source targets disagree with versioned original IDs")


def validate_ledger(root: Path = ROOT, *, check_registrations: bool = False) -> dict:
    scope_data = (root / "registry/algorithm_scope.json").read_bytes()
    scope = json.loads(scope_data)
    try:
        document = json.loads((root / LEDGER_PATH).read_text(encoding="utf-8"))
        _validate_snapshot(document, scope, scope_data)
        selected = root / scope["selection"]["path"]
        if selected.exists():
            current_sha = sha256(selected.read_bytes())
            if current_sha != document["selection"]["sha256"]:
                raise ValueError("CSV selection changed; candidate ledger review required")
            # Reconstruct all provenance, namespace, role and decision fields from
            # the actual CSV and frozen scope. Registrations are reviewed snapshots:
            # unrelated later manifest changes do not invalidate the CSV mapping.
            snapshots = None
            if not check_registrations:
                snapshots = {}
                for record in document["records"]:
                    for registration in record["registrations"]:
                        key = registration["key"]
                        if key in snapshots and snapshots[key] != registration:
                            raise ValueError(
                                "candidate ledger has conflicting registration snapshots"
                            )
                        snapshots[key] = registration
            rebuilt = build_ledger(root, registration_snapshots=snapshots)
            rebuilt["review_status"] = REVIEWED
            seal_ledger(rebuilt)
            if rebuilt != document:
                raise ValueError("candidate ledger differs from verified CSV/scope provenance")
        elif check_registrations:
            for record in document["records"]:
                for registration in record["registrations"]:
                    if registration != _registration(
                        root, registration["key"], registration["scope_status"] == "IN_SCOPE"
                    ):
                        raise ValueError("candidate registration snapshot changed; review required")
        return document
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot validate candidate ledger: {error}") from error


def resolve_candidate(*, selection_sha256: str, record_id: str, root: Path = ROOT) -> dict:
    """Resolve an ID only in an explicitly supplied selection namespace."""
    ledger = validate_ledger(root)
    requested = candidate_id(selection_sha256, record_id)
    for record in ledger["records"]:
        if requested in {record["candidate_id"], record["legacy_candidate_id"]}:
            return record
    raise ValueError("candidate ID is unknown in the specified selection version")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="read-only validation of reviewed ledger")
    validate.add_argument("--check-registrations", action="store_true")
    draft = subparsers.add_parser("draft", help="write an unapproved mapping proposal")
    draft.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate":
        document = validate_ledger(check_registrations=args.check_registrations)
        print(
            json.dumps(
                {
                    "status": "PASS_PROVENANCE_MAPPING_ONLY",
                    "selection": document["selection"],
                    "mapping_counts": document["mapping_counts"],
                    "coverage_denominator": document["coverage_denominator"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        if args.output.resolve() in {
            (ROOT / LEDGER_PATH).resolve(),
            (ROOT / "registry/algorithm_scope.json").resolve(),
            (ROOT / "algorithm_implementation_plan.csv").resolve(),
        }:
            parser.error("draft output cannot overwrite reviewed ledger, scope or CSV")
        document = build_ledger()
        args.output.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Draft only: {args.output}")


if __name__ == "__main__":
    main()
