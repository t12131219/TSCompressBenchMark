from pathlib import Path

from tscompbench.datasets import DatasetRegistry, load_dataset, read_canonical, write_canonical

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_canonical_bytes_are_deterministic_and_self_checking(tmp_path) -> None:
    registry = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    dataset = load_dataset(registry.load("national_illness"))
    first = write_canonical(dataset, tmp_path / "first.tscb")
    second = write_canonical(dataset, tmp_path / "second.tscb")
    assert first.sha256 == second.sha256
    assert first.sha256 == "b5ba97f7fb9dc6e24087d465c6094980c59f712427cdda9d48c59d1b14f122bb"
    assert first.path.read_bytes() == second.path.read_bytes()

    loaded = read_canonical(first.path)
    assert len(loaded.buffers) == 8
    assert loaded.metadata["accounting"]["canonical_raw_bits"] == dataset.canonical_raw_bits
    assert loaded.metadata["accounting"]["source_file_bytes_provenance_only"] == 67620
    assert loaded.metadata["dataset_content_sha256"] == dataset.content_sha256()
