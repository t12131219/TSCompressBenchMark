import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_source_catalog_records_full_existing_inventory_without_qualification() -> None:
    catalog = json.loads(
        (PROJECT_ROOT / "registry" / "sources" / "source_catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["summary"]["logical_entry_count"] == 221
    assert catalog["summary"]["repository_entry_count"] == 72
    assert catalog["summary"]["available_repository_count"] == 71
    assert catalog["summary"]["clean_repository_count"] == 71
    assert catalog["summary"]["scanned_file_count_excluding_generated_build_dirs"] > 100_000
    assert catalog["policy"]["evidence_is_qualification"] is False
    assert catalog["policy"]["shared_source_tree_mutated"] is False
