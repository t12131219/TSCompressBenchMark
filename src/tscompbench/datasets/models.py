from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from tscompbench.ids import canonical_json_bytes


class DatasetContractError(ValueError):
    """A dataset or manifest violates the Layer 1 data contract."""


@dataclass(frozen=True)
class DatasetManifest:
    key: str
    path: Path
    source_path: Path
    document: dict[str, Any]
    dataset_id: str

    @property
    def logical(self) -> dict[str, Any]:
        return self.document["logical"]

    @property
    def parser(self) -> dict[str, Any]:
        return self.document["parser"]


@dataclass(frozen=True)
class ValueBuffer:
    name: str
    display_name: str
    array: NDArray[Any]
    unit: str
    entity: str
    feature: str

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "dtype": self.array.dtype.str,
            "shape": list(self.array.shape),
            "strides": list(self.array.strides),
            "unit": self.unit,
            "entity": self.entity,
            "feature": self.feature,
        }


@dataclass(frozen=True)
class CanonicalDataset:
    manifest: DatasetManifest
    timestamp: NDArray[np.int64] | None
    values: tuple[ValueBuffer, ...]
    validity: NDArray[np.bool_] | None
    logical_descriptor: dict[str, Any]
    physical_descriptors: tuple[dict[str, Any], ...]
    loader_provenance: dict[str, Any]

    def __post_init__(self) -> None:
        arrays: list[NDArray[Any]] = [value.array for value in self.values]
        if self.timestamp is not None:
            arrays.append(self.timestamp)
        if self.validity is not None:
            arrays.append(self.validity)
        for array in arrays:
            if array.flags.writeable:
                raise DatasetContractError("canonical arrays must be immutable")

    @property
    def dataset_id(self) -> str:
        return self.manifest.dataset_id

    @property
    def n_rows(self) -> int:
        return int(self.logical_descriptor["n_rows"])

    @property
    def timestamp_raw_bits(self) -> int:
        if self.timestamp is None:
            return 0
        return int(self.timestamp.size * self.timestamp.itemsize * 8)

    @property
    def value_raw_bits(self) -> int:
        return sum(int(item.array.size * item.array.itemsize * 8) for item in self.values)

    @property
    def validity_raw_bits(self) -> int:
        return 0 if self.validity is None else int(self.validity.size)

    @property
    def canonical_raw_bits(self) -> int:
        return self.timestamp_raw_bits + self.value_raw_bits + self.validity_raw_bits

    def content_sha256(self) -> str:
        digest = hashlib.sha256()
        digest.update(canonical_json_bytes(self.logical_descriptor))
        for name, array in self.named_arrays():
            digest.update(name.encode("utf-8"))
            digest.update(array.dtype.str.encode("ascii"))
            digest.update(canonical_json_bytes(list(array.shape)))
            digest.update(array.tobytes(order="C"))
        return digest.hexdigest()

    def named_arrays(self) -> tuple[tuple[str, NDArray[Any]], ...]:
        arrays: list[tuple[str, NDArray[Any]]] = []
        if self.timestamp is not None:
            arrays.append(("timestamp", self.timestamp))
        arrays.extend(
            (f"value/{index:06d}", value.array) for index, value in enumerate(self.values)
        )
        if self.validity is not None:
            arrays.append(("validity", self.validity))
        return tuple(arrays)


def immutable(array: NDArray[Any]) -> NDArray[Any]:
    array.flags.writeable = False
    return array
