from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tscompbench.ids import stable_id

from .models import DatasetContractError, DatasetManifest

_TOP_LEVEL_KEYS = {
    "schema_version",
    "key",
    "display_name",
    "source",
    "license",
    "file",
    "parser",
    "logical",
    "expected",
    "split",
}


def _validate_keys(
    value: Any,
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    label: str,
) -> None:
    if not isinstance(value, dict):
        raise DatasetContractError(f"{label} must be an object")
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing or unknown:
        raise DatasetContractError(
            f"{label} fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _identity_payload(document: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": document["schema_version"],
        "content": {
            "bytes": document["file"]["bytes"],
            "sha256": document["file"]["sha256"],
            "format": document["file"]["format"],
        },
        "parser": document["parser"],
        "logical": document["logical"],
        "expected": document["expected"],
        "split": document["split"],
    }


class DatasetRegistry:
    def __init__(self, manifest_root: Path, project_root: Path):
        self.manifest_root = manifest_root.resolve()
        self.project_root = project_root.resolve()

    def keys(self) -> tuple[str, ...]:
        return tuple(
            path.stem
            for path in sorted(self.manifest_root.glob("*.json"))
            if not path.name.startswith("_")
        )

    def load(self, key: str, *, verify_source: bool = True) -> DatasetManifest:
        if Path(key).name != key or key.startswith("_"):
            raise DatasetContractError(f"invalid dataset key: {key!r}")
        manifest_path = self.manifest_root / f"{key}.json"
        if not manifest_path.is_file():
            raise DatasetContractError(f"dataset manifest not found: {key}")
        try:
            document = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DatasetContractError(f"cannot read manifest {key}: {error}") from error
        self._validate_document(document, expected_key=key)

        relative = Path(document["file"]["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise DatasetContractError(
                "dataset file path must be project-relative and non-escaping"
            )
        source_path = (self.project_root / relative).resolve()
        if not source_path.is_relative_to(self.project_root):
            raise DatasetContractError("dataset source path escapes project root")
        if verify_source:
            self._verify_source(document, source_path)

        return DatasetManifest(
            key=key,
            path=manifest_path,
            source_path=source_path,
            document=document,
            dataset_id=stable_id("dataset", _identity_payload(document)),
        )

    def verify_all(self) -> tuple[DatasetManifest, ...]:
        return tuple(self.load(key, verify_source=True) for key in self.keys())

    @staticmethod
    def _validate_document(document: Any, *, expected_key: str) -> None:
        if not isinstance(document, dict):
            raise DatasetContractError("manifest root must be an object")
        _validate_keys(document, required=_TOP_LEVEL_KEYS, label="manifest")
        if document["schema_version"] != "tscb.dataset-manifest.v2":
            raise DatasetContractError("unsupported dataset manifest schema_version")
        if document["key"] != expected_key:
            raise DatasetContractError("manifest key must match its filename")
        file_info = document["file"]
        _validate_keys(
            file_info,
            required={"path", "bytes", "sha256", "format"},
            optional={"header_bytes_sha256", "raw_header_hex"},
            label="file",
        )
        if file_info["format"] not in {"csv", "npz"}:
            raise DatasetContractError("only csv and npz are supported in Layer 1")
        _validate_keys(
            document["source"],
            required={"uri", "retrieved_at"},
            optional={"notes"},
            label="source",
        )
        _validate_keys(document["license"], required={"spdx", "status"}, label="license")
        if document["license"]["status"] not in {
            "RUN_ALLOWED",
            "REVIEW_REQUIRED",
            "REDISTRIBUTION_RESTRICTED",
            "BLOCKED",
        }:
            raise DatasetContractError("invalid license.status")
        parser = document["parser"]
        if file_info["format"] == "csv":
            _validate_keys(
                parser,
                required={
                    "name",
                    "version",
                    "encoding",
                    "encoding_errors",
                    "delimiter",
                    "decimal",
                    "header",
                    "strict_column_count",
                },
                label="parser",
            )
            if parser["name"] != "python.csv" or parser["delimiter"] != ",":
                raise DatasetContractError("unsupported CSV parser policy")
        else:
            _validate_keys(
                parser,
                required={"name", "version", "allow_pickle", "array_key", "expected_keys"},
                label="parser",
            )
            if parser["name"] != "numpy.npz" or parser["allow_pickle"] is not False:
                raise DatasetContractError("NPZ parser must disable pickle")
        logical = document["logical"]
        _validate_keys(
            logical,
            required={"topology", "axes", "timestamp", "value", "validity", "canonical"},
            label="logical",
        )
        timestamp = logical["timestamp"]
        if timestamp.get("origin") == "NONE":
            _validate_keys(timestamp, required={"origin", "reason"}, label="logical.timestamp")
        else:
            _validate_keys(
                timestamp,
                required={
                    "origin",
                    "column",
                    "dtype",
                    "unit",
                    "epoch",
                    "formats",
                    "timezone_interpretation",
                    "order_policy",
                    "allow_duplicates",
                    "allow_out_of_order",
                },
                label="logical.timestamp",
            )
        value = logical["value"]
        if value.get("kind") == "CSV_COLUMNS":
            _validate_keys(
                value,
                required={
                    "kind",
                    "column_selection",
                    "default_column",
                    "overrides",
                    "display_name_overrides",
                    "representation",
                },
                label="logical.value",
            )
            _validate_keys(
                value["column_selection"],
                required={"kind", "excluded", "expected_count"},
                label="logical.value.column_selection",
            )
            _validate_keys(
                value["default_column"],
                required={"dtype", "unit", "entity", "feature"},
                label="logical.value.default_column",
            )
            for name, override in value["overrides"].items():
                _validate_keys(
                    override,
                    required=set(),
                    optional={"dtype", "unit", "entity", "feature"},
                    label=f"logical.value.overrides[{name!r}]",
                )
        elif value.get("kind") == "NPZ_ARRAY":
            _validate_keys(
                value,
                required={"kind", "array", "representation"},
                label="logical.value",
            )
            _validate_keys(
                value["array"],
                required={"dtype", "unit", "entity", "feature", "required_layout"},
                label="logical.value.array",
            )
        else:
            raise DatasetContractError("unsupported logical.value.kind")
        _validate_keys(
            logical["validity"],
            required={"shape", "missing_tokens", "nan_is_null"},
            label="logical.validity",
        )
        _validate_keys(
            logical["canonical"],
            required={"format_version", "byte_order"},
            label="logical.canonical",
        )
        if logical["canonical"].get("format_version") != "tscb-canonical-v1":
            raise DatasetContractError("canonical format version must be tscb-canonical-v1")
        if logical["canonical"].get("byte_order") != "little":
            raise DatasetContractError("Layer 1 canonical byte order must be little")
        expected_keys = (
            {"rows", "columns"}
            if file_info["format"] == "csv"
            else {
                "shape",
                "dtype",
                "array_keys",
            }
        )
        _validate_keys(document["expected"], required=expected_keys, label="expected")
        _validate_keys(
            document["split"],
            required={"policy", "learned_eligible"},
            optional={"reason"},
            label="split",
        )
        if document["split"].get("policy") == "UNSPECIFIED" and document["split"].get(
            "learned_eligible", True
        ):
            raise DatasetContractError("an unspecified split cannot be learned-eligible")

    @staticmethod
    def _verify_source(document: dict[str, Any], source_path: Path) -> None:
        if not source_path.is_file():
            raise DatasetContractError(f"dataset source does not exist: {source_path}")
        actual_bytes = source_path.stat().st_size
        if actual_bytes != document["file"]["bytes"]:
            raise DatasetContractError(
                f"source size mismatch for {source_path.name}: {actual_bytes} != "
                f"{document['file']['bytes']}"
            )
        actual_hash = sha256_file(source_path)
        if actual_hash != document["file"]["sha256"]:
            raise DatasetContractError(f"source sha256 mismatch for {source_path.name}")
        header_hash = document["file"].get("header_bytes_sha256")
        raw_header_hex = document["file"].get("raw_header_hex")
        if header_hash or raw_header_hex:
            with source_path.open("rb") as handle:
                raw_header = handle.readline()
                actual_header_hash = hashlib.sha256(raw_header).hexdigest()
            if raw_header_hex and raw_header.hex() != raw_header_hex:
                raise DatasetContractError(f"raw header bytes mismatch for {source_path.name}")
        if header_hash:
            if actual_header_hash != header_hash:
                raise DatasetContractError(f"raw header hash mismatch for {source_path.name}")
