"""Explicit canonical source policy, independent of legacy CSV/NPZ identities."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np

from .canonical import read_canonical, semantic_content_sha256
from .models import CanonicalDataset, DatasetContractError, DatasetManifest, ValueBuffer, immutable

SCHEMA = "tscb.canonical-source-manifest.v1"
PARSER = {"name": "tscb.canonical", "version": "1", "identity_policy": "tscb.dataset-content.v1"}


def identity_payload(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "content_sha256": document["expected"]["semantic_content_sha256"],
        "parser": document["parser"],
        "split": document["split"],
    }


def validate_manifest(document: dict[str, Any]) -> None:
    def fields(value, required, label):
        if not isinstance(value, dict) or set(value) != set(required):
            raise DatasetContractError(f"{label} fields mismatch")

    fields(document["file"], ("path", "bytes", "sha256", "format"), "file")
    if document["file"]["format"] != "canonical" or document["parser"] != PARSER:
        raise DatasetContractError("unsupported canonical source policy")
    fields(document["source"], ("uri", "retrieved_at", "notes"), "source")
    fields(document["license"], ("spdx", "status"), "license")
    if document["license"]["status"] not in {
        "RUN_ALLOWED",
        "REVIEW_REQUIRED",
        "REDISTRIBUTION_RESTRICTED",
        "BLOCKED",
    }:
        raise DatasetContractError("invalid license.status")
    fields(
        document["expected"],
        ("shape", "n_rows", "canonical_raw_bits", "semantic_content_sha256"),
        "expected",
    )
    fields(document["split"], ("policy", "learned_eligible", "reason"), "split")
    if (
        document["split"]["policy"] == "UNSPECIFIED"
        and document["split"]["learned_eligible"] is not False
    ):
        raise DatasetContractError("an unspecified split cannot be learned-eligible")
    for sha in (document["file"]["sha256"], document["expected"]["semantic_content_sha256"]):
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise DatasetContractError("invalid canonical source hash")
    if type(document["file"]["bytes"]) is not int or document["file"]["bytes"] < 0:
        raise DatasetContractError("invalid canonical source size")
    if not isinstance(document["logical"], dict):
        raise DatasetContractError("invalid canonical source logical descriptor")


def canonical_source_document(
    path: Path,
    project_root: Path,
    key: str,
    *,
    split: dict[str, Any] | None = None,
    license_info: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", key):
        raise DatasetContractError("invalid dataset key")
    path, project_root = path.resolve(), project_root.resolve()
    if not path.is_relative_to(project_root):
        raise DatasetContractError("canonical source must be inside project root")
    artifact = read_canonical(path, include_buffers=False)
    logical = artifact.metadata["logical_descriptor"]
    return {
        "schema_version": SCHEMA,
        "key": key,
        "display_name": key,
        "source": {
            "uri": "local:canonical",
            "retrieved_at": "LOCAL",
            "notes": "Transport hash is provenance; identity uses verified semantic content.",
        },
        "license": license_info or {"spdx": "NOASSERTION", "status": "REVIEW_REQUIRED"},
        "file": {
            "path": path.relative_to(project_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": artifact.sha256,
            "format": "canonical",
        },
        "parser": PARSER.copy(),
        "logical": logical,
        "expected": {
            "shape": logical["value_shape"],
            "n_rows": logical["n_rows"],
            "canonical_raw_bits": artifact.metadata["accounting"]["canonical_raw_bits"],
            "semantic_content_sha256": semantic_content_sha256(artifact.metadata),
        },
        "split": split
        or {
            "policy": "UNSPECIFIED",
            "learned_eligible": False,
            "reason": "Qualification only; no training split claimed.",
        },
    }


def load_canonical_source(manifest: DatasetManifest) -> CanonicalDataset:
    artifact = read_canonical(manifest.source_path)
    document, metadata = manifest.document, artifact.metadata
    logical = metadata["logical_descriptor"]
    if artifact.sha256 != document["file"]["sha256"]:
        raise DatasetContractError("canonical source transport hash mismatch")
    if (
        logical != document["logical"]
        or logical["value_shape"] != document["expected"]["shape"]
        or logical["n_rows"] != document["expected"]["n_rows"]
    ):
        raise DatasetContractError("canonical source logical contract mismatch")
    if metadata["accounting"]["canonical_raw_bits"] != document["expected"]["canonical_raw_bits"]:
        raise DatasetContractError("canonical source raw bits mismatch")
    if semantic_content_sha256(metadata) != document["expected"]["semantic_content_sha256"]:
        raise DatasetContractError("canonical source semantic hash mismatch")
    arrays = {}
    for item in metadata["buffers"]:
        payload = artifact.buffers[item["name"]]
        if item["dtype"] == "bitmap-lsb0":
            count = item["logical_bits"]
            array = (
                np.unpackbits(np.frombuffer(payload, dtype=np.uint8), bitorder="little")[:count]
                .astype(np.bool_)
                .reshape(item["shape"])
            )
        else:
            array = np.frombuffer(payload, dtype=np.dtype(item["dtype"])).reshape(item["shape"])
        arrays[item["name"]] = immutable(array)
    values = tuple(
        ValueBuffer(
            column["name"],
            column["display_name"],
            arrays[f"value/{i:06d}"],
            column["unit"],
            column["entity"],
            column["feature"],
        )
        for i, column in enumerate(logical["value_columns"])
    )
    dataset = CanonicalDataset(
        manifest,
        arrays.get("timestamp"),
        values,
        arrays.get("validity"),
        logical,
        tuple(metadata["physical_descriptors"]),
        {
            "loader": "tscompbench.datasets.canonical_source",
            "source_sha256": artifact.sha256,
            "embedded_legacy_dataset_id": metadata["dataset_id"],
            "identity_policy": PARSER["identity_policy"],
            "hidden_transforms": [],
        },
    )
    if dataset.content_sha256() != metadata["dataset_content_sha256"]:
        raise DatasetContractError("canonical legacy content hash mismatch")
    return dataset


def register_canonical_source(
    path: Path, project_root: Path, manifest_root: Path, key: str, **kwargs
) -> Path:
    document = canonical_source_document(path, project_root, key, **kwargs)
    manifest_root.mkdir(parents=True, exist_ok=True)
    target = manifest_root / f"{key}.json"
    # Registration never silently rewrites an existing identity or snapshot.
    with target.open("x", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
        handle.write("\n")
    return target
