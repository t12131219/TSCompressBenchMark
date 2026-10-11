"""Keep active registrations and regenerated worklists within the reviewed CSV."""

import copy
import json
import sys
from pathlib import Path

import pytest

from tscompbench.codecs import CodecRegistry, SourceRegistry

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from algorithm_scope import (  # noqa: E402
    filter_catalog,
    filter_worklist,
    load_scope,
    source_records,
)


def test_selected_registry_is_complete_and_preserves_framework_oracles():
    scope = load_scope()
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    ids = [r["id"] for r in scope["records"]]
    assert len(ids) == len(set(ids)) == scope["selection"]["record_count"] == 163
    assert set(registry.keys()) == set(scope["registered_codecs"]) | set(
        scope["framework_oracles"]
    ) | set(scope["retained_out_of_scope_registrations"])
    assert all(
        set(records) <= set(ids) and records for records in scope["registered_codecs"].values()
    )
    assert {"主集合保留", "扩展保留", "组件/配置/来源保留"} == {
        r["recommendation"] for r in scope["records"]
    }
    assert not set(scope["removed_codecs"]) & set(registry.keys())


def test_merged_variants_and_reference_roles_survive_filtering():
    scope = load_scope()
    assert source_records(scope, "ValueCompress", "NeaTS") == ["V100"]
    assert source_records(scope, "TimeStampCompress", "IoTDB SPRINTZ + LZ4") == ["T113"]
    assert source_records(scope, "TimeStampCompress", "InfluxDB TSM Delta preprocessing") is None
    assert source_records(scope, "TSBench", "lzbench") == []
    assert source_records(scope, "ValueCompress", "TerraCodec FlexTEC") is None
    catalog = json.loads((ROOT / "registry/sources/source_catalog.json").read_text())
    worklist = json.loads((ROOT / "registry/native_integration_plan.json").read_text())
    original_catalog, original_worklist = copy.deepcopy(catalog), copy.deepcopy(worklist)
    catalog["logical_entries"].append({"group": "ValueCompress", "name": "Unselected new codec"})
    worklist["entries"].append({"asset_group": "ValueCompress", "name": "Unselected new codec"})
    filter_catalog(catalog, scope)
    filter_worklist(worklist, scope)
    assert catalog == original_catalog
    assert worklist == original_worklist
    assert len({e["audit_index"] for e in worklist["entries"]}) == len(worklist["entries"])


def test_local_csv_change_requires_explicit_scope_review(tmp_path):
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/algorithm_scope.json").write_bytes(
        (ROOT / "registry/algorithm_scope.json").read_bytes()
    )
    assert load_scope(tmp_path)["selection"]["record_count"] == 163
    (tmp_path / "algorithm_implementation_plan.csv").write_text("changed selection")
    with pytest.raises(ValueError, match="CSV selection changed"):
        load_scope(tmp_path)


def test_rewrite_selection_preserves_every_retained_package():
    scope = load_scope()
    if not (ROOT / "Compression_Rewrite").is_dir():
        pytest.skip("local rewrite assets are excluded from Git")
    for area in ("Source", "ReWrite"):
        actual = {p.name for p in (ROOT / "Compression_Rewrite" / area).iterdir() if p.is_dir()}
        assert actual == set(scope["rewrite_package_inventory"])
        assert set(scope["rewrite_packages"]) <= actual
    assert not set(scope["removed_rewrite_packages"]) & actual
    assert {key for keys in scope["rewrite_packages"].values() for key in keys} <= (
        set(scope["registered_codecs"])
    )
