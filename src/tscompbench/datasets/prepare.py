from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import CanonicalArtifact, read_canonical, write_canonical
from .characterize import CharacterizationProfile, characterize
from .loaders import load_dataset
from .registry import DatasetRegistry


@dataclass(frozen=True)
class PreparationResult:
    dataset_key: str
    dataset_id: str
    canonical: CanonicalArtifact
    manifest_snapshot: Path
    characterization_path: Path
    preparation_record_path: Path


def load_preparation_result(
    registry: DatasetRegistry,
    key: str,
    output_root: Path,
) -> PreparationResult:
    """Validate and reuse an already completed Layer 1 dataset artifact set."""

    manifest = registry.load(key, verify_source=True)
    dataset_root = output_root.resolve() / key
    preparation_record_path = dataset_root / "preparation-record.json"
    if not preparation_record_path.is_file():
        raise FileNotFoundError(f"preparation record is missing for dataset {key}")
    try:
        record = json.loads(preparation_record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid preparation record for dataset {key}") from error
    if record.get("schema_version") != "tscb.data-preparation-record.v2":
        raise ValueError(f"unsupported preparation record for dataset {key}")
    if record.get("dataset_key") != key or record.get("dataset_id") != manifest.dataset_id:
        raise ValueError(f"preparation record identity mismatch for dataset {key}")

    artifact_names = {
        "canonical": record.get("canonical_artifact"),
        "characterization": record.get("characterization_artifact"),
        "manifest": record.get("manifest_artifact"),
    }
    if not all(
        isinstance(value, str) and Path(value).name == value for value in artifact_names.values()
    ):
        raise ValueError(f"preparation record contains unsafe artifact names for dataset {key}")
    canonical_path = dataset_root / str(artifact_names["canonical"])
    characterization_path = dataset_root / str(artifact_names["characterization"])
    manifest_snapshot = dataset_root / str(artifact_names["manifest"])
    if not characterization_path.is_file() or not manifest_snapshot.is_file():
        raise FileNotFoundError(f"Layer 1 evidence is incomplete for dataset {key}")

    canonical = read_canonical(canonical_path, include_buffers=False)
    if canonical.sha256 != record.get("canonical_artifact_sha256"):
        raise ValueError(f"canonical artifact hash mismatch for dataset {key}")
    if canonical.metadata.get("dataset_id") != manifest.dataset_id:
        raise ValueError(f"canonical DatasetID mismatch for dataset {key}")
    characterization = json.loads(characterization_path.read_text(encoding="utf-8"))
    snapshot = json.loads(manifest_snapshot.read_text(encoding="utf-8"))
    if characterization.get("dataset_id") != manifest.dataset_id:
        raise ValueError(f"characterization DatasetID mismatch for dataset {key}")
    if snapshot.get("dataset_id") != manifest.dataset_id:
        raise ValueError(f"manifest snapshot DatasetID mismatch for dataset {key}")

    return PreparationResult(
        dataset_key=key,
        dataset_id=manifest.dataset_id,
        canonical=canonical,
        manifest_snapshot=manifest_snapshot,
        characterization_path=characterization_path,
        preparation_record_path=preparation_record_path,
    )


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(value, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)


def prepare_dataset(
    registry: DatasetRegistry,
    key: str,
    output_root: Path,
    *,
    characterization_profile: CharacterizationProfile | None = None,
) -> PreparationResult:
    manifest = registry.load(key, verify_source=True)
    dataset = load_dataset(manifest)
    output_root = output_root.resolve()
    dataset_root = output_root / key
    dataset_root.mkdir(parents=True, exist_ok=True)
    canonical_path = dataset_root / f"{key}.canonical.tscb"
    characterization_path = dataset_root / f"{key}.characterization.json"
    manifest_snapshot = dataset_root / f"{key}.manifest.json"
    preparation_record_path = dataset_root / "preparation-record.json"
    targets = (
        canonical_path,
        characterization_path,
        manifest_snapshot,
        preparation_record_path,
    )
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"refusing to overwrite Layer 1 artifacts: {existing}")

    characterization = characterize(dataset, characterization_profile)
    canonical = write_canonical(dataset, canonical_path)
    _write_json_atomic(characterization_path, characterization)
    _write_json_atomic(
        manifest_snapshot,
        {**manifest.document, "dataset_id": manifest.dataset_id},
    )
    preparation_record = {
        "schema_version": "tscb.data-preparation-record.v2",
        "dataset_key": key,
        "dataset_id": dataset.dataset_id,
        "source_sha256": manifest.document["file"]["sha256"],
        "canonical_artifact": canonical_path.name,
        "canonical_artifact_sha256": canonical.sha256,
        "canonical_content_sha256": canonical.metadata["dataset_content_sha256"],
        "characterization_artifact": characterization_path.name,
        "manifest_artifact": manifest_snapshot.name,
        "loader_provenance": dataset.loader_provenance,
        "self_check": {
            "source_bytes_not_used_as_raw_bits": True,
            "hidden_transforms": [],
            "timestamp_origin": manifest.logical["timestamp"]["origin"],
            "native_shape_preserved": dataset.logical_descriptor["value_shape"]
            == manifest.document["expected"].get(
                "shape", dataset.logical_descriptor["value_shape"]
            ),
            "characterization_read_only": characterization["read_only_verified"],
        },
    }
    _write_json_atomic(preparation_record_path, preparation_record)
    return PreparationResult(
        dataset_key=key,
        dataset_id=dataset.dataset_id,
        canonical=canonical,
        manifest_snapshot=manifest_snapshot,
        characterization_path=characterization_path,
        preparation_record_path=preparation_record_path,
    )
