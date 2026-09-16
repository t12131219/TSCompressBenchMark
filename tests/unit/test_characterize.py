from pathlib import Path

from tscompbench.datasets import (
    CharacterizationProfile,
    DatasetRegistry,
    characterize,
    load_dataset,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_characterization_is_read_only_and_records_exact_mode() -> None:
    registry = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    dataset = load_dataset(registry.load("national_illness"))
    before = dataset.content_sha256()
    result = characterize(dataset, CharacterizationProfile(mode="exact"))
    assert result["read_only_verified"] is True
    assert dataset.content_sha256() == before
    assert result["timestamp"]["regularity_ratio"] == 1.0
    assert result["value"]["channel_count"] == 7
    assert all(channel["metric_mode"] == "exact" for channel in result["value"]["channels"])


def test_sampled_characterization_is_seeded() -> None:
    registry = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)
    dataset = load_dataset(registry.load("etth1"))
    profile = CharacterizationProfile(mode="sampled", sample_rows=128, seed=42)
    assert characterize(dataset, profile) == characterize(dataset, profile)
