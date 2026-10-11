"""Apply the reviewed CSV selection without treating source inventory as codecs.

The checked-in snapshot supports installations without the ignored local CSV.
A changed CSV can have a reviewed versioned provenance mapping; it does not
reinterpret this scope's IDs or admit candidates into the active registry.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_scope(root: Path = ROOT) -> dict:
    scope = json.loads((root / "registry/algorithm_scope.json").read_text(encoding="utf-8"))
    selected = root / scope["selection"]["path"]
    if (
        selected.exists()
        and hashlib.sha256(selected.read_bytes()).hexdigest() != scope["selection"]["sha256"]
    ):
        from candidate_integration_ledger import validate_ledger

        try:
            validate_ledger(root)
        except ValueError as error:
            raise ValueError(
                "CSV selection changed; a verified CandidateIntegrationLedger mapping is required"
            ) from error
    return scope


def source_records(scope: dict, group: str, name: str) -> list[str] | None:
    if group == "TSBench":
        records = scope["benchmark_references"].get(name)
        if records is None or not records:
            return records
        retained = sorted(set(records) - set(scope.get("excluded_plan_records", [])))
        return retained if retained else None
    records = {
        record["id"]
        for record in scope["records"]
        if {"group": group, "name": name} in record["source_names"]
    }
    for alias in scope["source_aliases"]:
        if alias["group"] == group and alias["name"] == name:
            records.update(alias["records"])
    records.difference_update(scope.get("excluded_plan_records", []))
    return sorted(records) if records else None


def filter_catalog(document: dict, scope: dict) -> None:
    entries = []
    for entry in document["logical_entries"]:
        records = source_records(scope, entry["group"], entry["name"])
        if records is not None:
            entry["selection_records"] = records
            entries.append(entry)
    document["logical_entries"] = entries
    document["summary"]["logical_entry_count"] = len(entries)
    document["algorithm_selection"] = scope["selection"]
    document["policy"]["repository_inventory_role"] = (
        "HISTORICAL_SOURCE_PROVENANCE_NOT_ACTIVE_ALGORITHMS"
    )


def filter_worklist(document: dict, scope: dict) -> None:
    entries = []
    allowed = (
        set(scope["registered_codecs"])
        | set(scope["framework_oracles"])
        | set(scope.get("retained_out_of_scope_registrations", []))
    )
    for entry in document["entries"]:
        records = source_records(scope, entry["asset_group"], entry["name"])
        if records is not None:
            entry["selection_records"] = records
            entry["registered_candidates"] = [
                candidate
                for candidate in entry.get("registered_candidates", [])
                if candidate["key"] in allowed
            ]
            entries.append(entry)
    document["entries"] = entries
    document["scope_counts"] = dict(sorted(Counter(e["scope"] for e in entries).items()))
    document["state_counts"] = dict(sorted(Counter(e["state"] for e in entries).items()))
    document["input_provenance"]["algorithm_selection"] = scope["selection"]
    document["policy"].pop("all_221_rows_retained", None)
    document["policy"]["csv_selected_entries_and_merged_variants_only"] = True
    document["policy"]["original_audit_indices_preserved"] = True


def validate_worklist(document: dict, scope: dict) -> None:
    entries = document["entries"]
    indices = [entry["audit_index"] for entry in entries]
    if len(indices) != len(set(indices)) or any(
        source_records(scope, entry["asset_group"], entry["name"]) is None for entry in entries
    ):
        raise ValueError(
            "worklist contains duplicate indices or algorithms outside the CSV selection"
        )
