from pathlib import Path

import numpy as np

from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.datasets.characterize import characterize

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = DatasetRegistry(PROJECT_ROOT / "registry" / "datasets", PROJECT_ROOT)


def test_national_illness_preserves_heterogeneous_dtypes() -> None:
    dataset = load_dataset(REGISTRY.load("national_illness"))
    assert dataset.logical_descriptor["value_shape"] == [966, 7]
    assert [item.array.dtype.str for item in dataset.values] == [
        "<f8",
        "<f8",
        "<i8",
        "<i8",
        "<i8",
        "<i8",
        "<i8",
    ]
    assert dataset.timestamp is not None
    assert all(not item.array.flags.writeable for item in dataset.values)
    assert not dataset.timestamp.flags.writeable
    assert dataset.canonical_raw_bits == (966 * 8 + 966 * 7 * 8) * 8


def test_pems_native_nd_shape_is_not_flattened_and_t_is_not_invented() -> None:
    dataset = load_dataset(REGISTRY.load("pems08"))
    assert dataset.timestamp is None
    assert dataset.logical_descriptor["value_shape"] == [17856, 170, 3]
    assert dataset.values[0].array.shape == (17856, 170, 3)
    assert dataset.physical_descriptors[0]["layout"] == "ROW_MAJOR_CONTIG"
    assert not dataset.values[0].array.flags.writeable
    assert not np.isnan(dataset.values[0].array).any()


def test_weather_duplicate_timestamp_is_preserved_not_repaired() -> None:
    dataset = load_dataset(REGISTRY.load("weather"))
    result = characterize(dataset)
    assert result["timestamp"]["duplicate_count"] == 1
    assert result["timestamp"]["out_of_order_count"] == 0
    assert dataset.n_rows == 52696
