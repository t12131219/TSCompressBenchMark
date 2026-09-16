from pathlib import Path

from tscompbench.datasets import DatasetRegistry

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_all_real_dataset_manifests_verify_and_have_stable_ids() -> None:
    registry = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    first = registry.verify_all()
    second = registry.verify_all()
    assert len(first) == 13
    assert [item.dataset_id for item in first] == [item.dataset_id for item in second]
    assert len({item.dataset_id for item in first}) == 13


def test_unknown_manifest_fields_are_not_silently_accepted(tmp_path) -> None:
    manifest_root = tmp_path / "registry"
    manifest_root.mkdir()
    source = tmp_path / "data.csv"
    source.write_text("date,value\n", encoding="utf-8")
    (manifest_root / "bad.json").write_text(
        '{"schema_version":"tscb.dataset-manifest.v2","key":"bad","unexpected":true}',
        encoding="utf-8",
    )
    registry = DatasetRegistry(manifest_root, tmp_path)
    try:
        registry.load("bad")
    except ValueError as error:
        assert "fields mismatch" in str(error)
    else:
        raise AssertionError("unknown manifest field was accepted")
