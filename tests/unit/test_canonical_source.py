from __future__ import annotations

import copy
import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.datasets.canonical import (
    MAGIC,
    read_canonical,
    semantic_content_sha256,
    write_canonical,
)
from tscompbench.datasets.canonical_source import register_canonical_source
from tscompbench.datasets.models import DatasetContractError
from tscompbench.datasets.prepare import load_preparation_result, prepare_dataset
from tscompbench.ids import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[2]


def sample(tmp_path):
    source = load_dataset(
        DatasetRegistry(ROOT / "registry/datasets", ROOT).load("streamvbyte_u32_uts")
    )
    logical = copy.deepcopy(source.logical_descriptor)
    logical["value_shape"] = [source.n_rows]
    return write_canonical(replace(source, logical_descriptor=logical), tmp_path / "extensionless")


def test_import_prepare_resume_and_identity_has_no_transport_cycle(tmp_path):
    artifact = sample(tmp_path)
    registry_root = tmp_path / "registry"
    register_canonical_source(
        artifact.path,
        tmp_path,
        registry_root,
        "first",
        license_info={"spdx": "CC0-1.0", "status": "RUN_ALLOWED"},
    )
    registry = DatasetRegistry(registry_root, tmp_path)
    manifest = registry.load("first")
    dataset = load_dataset(manifest)
    assert manifest.dataset_id != artifact.metadata["dataset_id"]
    assert dataset.logical_descriptor["value_shape"] == [dataset.n_rows]
    prepared = prepare_dataset(registry, "first", tmp_path / "prepared")
    assert prepared.canonical.metadata["dataset_id"] == manifest.dataset_id
    # Re-importing a stream containing the new DatasetID cannot change that ID.
    register_canonical_source(
        prepared.canonical.path,
        tmp_path,
        registry_root,
        "second",
        license_info={"spdx": "CC0-1.0", "status": "RUN_ALLOWED"},
    )
    assert registry.load("second").dataset_id == manifest.dataset_id
    assert prepared.canonical.sha256 != artifact.sha256
    assert (
        load_preparation_result(registry, "first", tmp_path / "prepared").dataset_id
        == manifest.dataset_id
    )
    with pytest.raises(FileExistsError):
        register_canonical_source(artifact.path, tmp_path, registry_root, "first")


def test_semantic_identity_ignores_physical_stride_but_preserves_units(tmp_path):
    metadata = sample(tmp_path).metadata
    changed = copy.deepcopy(metadata)
    changed["dataset_id"] = "another transport"
    changed["logical_descriptor"]["value_columns"][0]["strides"] = [999]
    changed["physical_descriptors"] = []
    assert semantic_content_sha256(metadata) == semantic_content_sha256(changed)
    changed["logical_descriptor"]["value_columns"][0]["unit"] = "another unit"
    assert semantic_content_sha256(metadata) != semantic_content_sha256(changed)


def rewrite_metadata(path, mutate):
    data = path.read_bytes()
    _, major, minor, size, count = struct.unpack("<8sHHQI", data[:24])
    metadata = json.loads(data[24 : 24 + size])
    mutate(metadata)
    encoded = canonical_json_bytes(metadata)
    path.write_bytes(
        struct.pack("<8sHHQI", MAGIC, major, minor, len(encoded), count)
        + encoded
        + data[24 + size :]
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m["buffers"][0].update(dtype="|O"),
        lambda m: m["buffers"][0].update(shape=[2**63, 2**63]),
        lambda m: m["buffers"][0].update(logical_bits=0),
        lambda m: m["accounting"].update(canonical_raw_bits=1),
        lambda m: m["logical_descriptor"].update(value_shape=[1, 3, 4]),
        lambda m: m["logical_descriptor"]["timestamp"].update(present=True),
    ],
)
def test_reader_rejects_semantic_or_accounting_corruption(tmp_path, mutate):
    artifact = sample(tmp_path)
    rewrite_metadata(artifact.path, mutate)
    for include in (True, False):
        with pytest.raises(DatasetContractError):
            read_canonical(artifact.path, include_buffers=include)


def test_reader_rejects_huge_header_without_allocation(tmp_path):
    path = tmp_path / "malicious"
    path.write_bytes(struct.pack("<8sHHQI", MAGIC, 1, 0, 2**64 - 1, 1))
    with pytest.raises(DatasetContractError, match="limits"):
        read_canonical(path)


def test_import_rejects_source_change_after_registry_verification(tmp_path):
    artifact = sample(tmp_path)
    register_canonical_source(artifact.path, tmp_path, tmp_path / "registry", "source")
    manifest = DatasetRegistry(tmp_path / "registry", tmp_path).load("source")
    with artifact.path.open("ab") as handle:
        handle.write(b"changed")
    with pytest.raises(DatasetContractError, match="changed"):
        load_dataset(manifest)


def test_validity_bitmap_raw_bits_and_padding_are_independently_checked(tmp_path):
    import numpy as np

    from tscompbench.datasets.models import immutable

    source = load_dataset(
        DatasetRegistry(ROOT / "registry/datasets", ROOT).load("streamvbyte_u32_uts")
    )
    mask = immutable(np.arange(source.n_rows) % 2 == 0)
    logical = copy.deepcopy(source.logical_descriptor)
    logical["validity_shape"] = "ROW"
    artifact = write_canonical(
        replace(source, validity=mask, logical_descriptor=logical), tmp_path / "masked"
    )
    assert artifact.metadata["accounting"]["validity_raw_bits"] == mask.size
    register_canonical_source(artifact.path, tmp_path, tmp_path / "registry", "masked")
    loaded = load_dataset(DatasetRegistry(tmp_path / "registry", tmp_path).load("masked"))
    assert np.array_equal(loaded.validity, mask)
    rewrite_metadata(
        artifact.path, lambda m: m["accounting"].update(validity_raw_bits=mask.nbytes * 8)
    )
    with pytest.raises(DatasetContractError, match="accounting"):
        read_canonical(artifact.path, include_buffers=False)


def test_ieee_extreme_characterization_remains_json_finite_and_read_only(tmp_path):
    import numpy as np

    from tscompbench.datasets import characterize
    from tscompbench.datasets.models import immutable

    source = load_dataset(
        DatasetRegistry(ROOT / "registry/datasets", ROOT).load("streamvbyte_u32_uts")
    )
    array = immutable(
        np.array(
            [-np.finfo("f8").max, np.finfo("f8").max, np.nan, np.inf, -np.inf, 0, -0.0], dtype="<f8"
        )
    )
    buffer = replace(source.values[0], array=array)
    logical = {
        **source.logical_descriptor,
        "n_rows": 7,
        "value_shape": [7],
        "value_columns": [buffer.descriptor()],
    }
    dataset = replace(source, values=(buffer,), logical_descriptor=logical)
    digest = dataset.content_sha256()
    stats = characterize(dataset)
    json.dumps(stats, allow_nan=False)
    assert stats["value"]["channels"][0]["range"] is None
    assert stats["value"]["channels"][0]["nan_count"] == 1
    assert dataset.content_sha256() == digest
