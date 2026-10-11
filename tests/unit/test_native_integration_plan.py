"""Candidate worklists must not recreate explicitly withdrawn registrations."""

import json
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry

ROOT = Path(__file__).resolve().parents[2]


def test_worklist_candidates_resolve_to_current_registration():
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    plan = json.loads((ROOT / "registry/native_integration_plan.json").read_text())
    scope = json.loads((ROOT / "registry/algorithm_scope.json").read_text())
    removed = set(scope["removed_codecs"])
    for entry in plan["entries"]:
        for candidate in entry.get("registered_candidates", []):
            assert candidate["key"] not in removed
            manifest = registry.get(candidate["key"])
            assert candidate["algorithm_id"] == manifest.algorithm_id
            assert candidate["source_artifact_id"] == manifest.source_artifact_id


def test_worklist_keeps_active_catalog_rows_and_original_audit_indices():
    catalog = json.loads((ROOT / "registry/sources/source_catalog.json").read_text())
    plan = json.loads((ROOT / "registry/native_integration_plan.json").read_text())
    expected = {(entry["group"], entry["name"]) for entry in catalog["logical_entries"]}
    actual = {(entry["asset_group"], entry["name"]) for entry in plan["entries"]}
    assert actual == expected
    indices = [entry["audit_index"] for entry in plan["entries"]]
    assert len(indices) == len(set(indices))
