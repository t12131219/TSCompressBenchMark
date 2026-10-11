import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_source_catalog_records_active_entries_and_historical_repository_inventory() -> None:
    catalog = json.loads(
        (PROJECT_ROOT / "registry" / "sources" / "source_catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["summary"]["logical_entry_count"] == len(catalog["logical_entries"]) == 176
    scope = json.loads((PROJECT_ROOT / "registry/algorithm_scope.json").read_text())
    assert all(
        not set(entry["selection_records"]) & set(scope["excluded_plan_records"])
        for entry in catalog["logical_entries"]
    )
    assert catalog["summary"]["repository_entry_count"] == 72
    assert catalog["summary"]["available_repository_count"] == 71
    assert catalog["summary"]["clean_repository_count"] == 71
    assert catalog["summary"]["scanned_file_count_excluding_generated_build_dirs"] > 100_000
    assert catalog["policy"]["evidence_is_qualification"] is False
    assert catalog["policy"]["shared_source_tree_mutated"] is False
