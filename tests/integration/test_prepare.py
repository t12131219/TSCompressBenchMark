import json
from pathlib import Path

from tscompbench.datasets import DatasetRegistry
from tscompbench.datasets.prepare import prepare_dataset

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_prepare_dataset_emits_complete_layer_1_evidence(tmp_path) -> None:
    registry = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    result = prepare_dataset(registry, "national_illness", tmp_path)
    record = json.loads(result.preparation_record_path.read_text(encoding="utf-8"))
    assert result.canonical.path.is_file()
    assert result.manifest_snapshot.is_file()
    assert result.characterization_path.is_file()
    assert record["self_check"]["source_bytes_not_used_as_raw_bits"] is True
    assert record["self_check"]["hidden_transforms"] == []
    assert record["canonical_artifact_sha256"] == result.canonical.sha256
