from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id

from .models import CodecContractError


def classify_logical_entries(source_catalog: dict[str, Any], rules_path: Path) -> dict[str, Any]:
    try:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CodecContractError(f"cannot read classification rules: {error}") from error
    if rules.get("schema_version") != "tscb.logical-classification-rules.v2":
        raise CodecContractError("unsupported logical classification rules schema")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for entry in source_catalog.get("logical_entries", []):
        source_key = (str(entry["sheet"]), int(entry["row"]))
        if source_key in seen:
            raise CodecContractError(f"duplicate logical source row: {source_key}")
        seen.add(source_key)
        try:
            group_rule = rules["groups"][entry["group"]]
        except KeyError as error:
            raise CodecContractError(f"logical entry has unclassified group: {entry}") from error
        object_levels = list(group_rule["default_object_levels"])
        category = str(entry.get("category") or "")
        for override in rules["category_keyword_overrides"]:
            if any(keyword.casefold() in category.casefold() for keyword in override["keywords"]):
                object_levels = list(override["object_levels"])
                break
        role = group_rule["entry_role"]
        decision = (
            "REFERENCE_ONLY_NO_ALGORITHM_ID"
            if role == "REFERENCE_BENCHMARK"
            else "PENDING_SOURCE_ONBOARDING_REVIEW"
        )
        row = {
            "source_sheet": entry["sheet"],
            "source_row": entry["row"],
            "name": entry["name"],
            "category": category,
            "github_repo": entry.get("github_repo"),
            "track": group_rule["track"],
            "entry_role": role,
            "candidate_object_levels": object_levels,
            "independent_algorithm_decision": decision,
        }
        row["classification_id"] = stable_id("logical-classification", row)
        rows.append(row)
    rows.sort(key=lambda item: (item["source_sheet"], item["source_row"]))
    if len(rows) != source_catalog["summary"]["logical_entry_count"]:
        raise CodecContractError("not every source catalog entry was classified")
    report = {
        "schema_version": "tscb.logical-classification.v2",
        "rules_id": stable_id("logical-classification-rules", rules),
        "entry_count": len(rows),
        "entries": rows,
    }
    report["classification_report_id"] = stable_id("logical-classification-report", report)
    return report
