from __future__ import annotations

import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

from tscompbench.contracts import (
    BenchmarkTrack,
    ImplementationClass,
    LossMode,
    ObjectLevel,
    PreprocessClass,
    ReconstructionMode,
    Topology,
    ValidityShape,
    ValueCouplingMode,
)
from tscompbench.ids import stable_id

from .models import CodecContractError, CodecManifest


def _require_keys(
    value: dict[str, Any],
    *,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
    label: str,
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing or unknown:
        raise CodecContractError(
            f"{label} fields mismatch: missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


class SourceRegistry:
    """Read-only index of audited external and explicitly declared built-in sources."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        catalog_path = self.root / "source_catalog.json"
        try:
            self.catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodecContractError(f"cannot read source catalog: {error}") from error
        if self.catalog.get("schema_version") != "tscb.source-catalog.v2":
            raise CodecContractError("unsupported source catalog schema")
        self._artifacts: dict[str, dict[str, Any]] = {}
        for record in self.catalog.get("repositories", []):
            source_id = record.get("source_artifact_id")
            if source_id:
                self._add(source_id, record)
        for path in sorted(self.root.glob("*.artifact.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise CodecContractError(f"cannot read source artifact {path}: {error}") from error
            _require_keys(
                record,
                required={
                    "schema_version",
                    "key",
                    "kind",
                    "identity",
                    "license",
                    "build",
                },
                label=f"source artifact {path.name}",
            )
            if record["schema_version"] != "tscb.source-artifact.v2":
                raise CodecContractError(f"unsupported source artifact schema: {path.name}")
            source_id = stable_id("source-artifact", record["identity"])
            record["source_artifact_id"] = source_id
            self._add(source_id, record)

    def _add(self, source_id: str, record: dict[str, Any]) -> None:
        if source_id in self._artifacts:
            raise CodecContractError(f"duplicate SourceArtifactID: {source_id}")
        self._artifacts[source_id] = record

    def get(self, source_artifact_id: str) -> dict[str, Any]:
        try:
            return self._artifacts[source_artifact_id]
        except KeyError as error:
            raise CodecContractError(f"unknown SourceArtifactID: {source_artifact_id}") from error

    def __contains__(self, source_artifact_id: object) -> bool:
        return source_artifact_id in self._artifacts

    def __len__(self) -> int:
        return len(self._artifacts)


class CodecRegistry:
    def __init__(self, root: Path, sources: SourceRegistry):
        self.root = root.resolve()
        self.sources = sources
        self._manifests: dict[str, CodecManifest] = {}
        for path in sorted(self.root.glob("*.json")):
            if path.name.endswith("classification_rules.json"):
                continue
            manifest = self._load(path)
            if manifest.key in self._manifests:
                raise CodecContractError(f"duplicate codec key: {manifest.key}")
            self._manifests[manifest.key] = manifest
        self._aliases: dict[str, dict[str, Any]] = {}
        for path in sorted((self.root / "aliases").glob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise CodecContractError(f"cannot read codec alias {path}: {error}") from error
            _require_keys(document, required={
                "schema_version", "key", "canonical_key", "canonical_algorithm_id",
                "source_artifact_id", "mapping_kind", "evidence", "limitations",
            }, label=f"codec alias {path.name}")
            for field in ("schema_version", "key", "canonical_key",
                          "canonical_algorithm_id", "source_artifact_id", "mapping_kind"):
                if not isinstance(document[field], str) or not document[field].strip():
                    raise CodecContractError(f"codec alias requires a string {field}: {path.name}")
            if (document["schema_version"] != "tscb.codec-alias.v2"
                    or document["mapping_kind"] != "SPREADSHEET_SOURCE_MAPPING_NOT_NEW_CODEC"):
                raise CodecContractError(f"unsupported codec alias schema or kind: {path.name}")
            key = document["key"]
            if key != path.stem or key in self._manifests or key in self._aliases:
                raise CodecContractError(f"invalid or colliding codec alias key: {path.name}")
            target = self._manifests.get(document["canonical_key"])
            if target is None:
                raise CodecContractError(f"alias requires a canonical codec, not a chain: {key}")
            if (target.algorithm_id != document["canonical_algorithm_id"]
                    or target.source_artifact_id != document["source_artifact_id"]):
                raise CodecContractError(f"codec alias identity differs from target: {key}")
            for field in ("evidence", "limitations"):
                if (not isinstance(document[field], list) or not document[field]
                        or not all(isinstance(item, str) and item.strip()
                                   for item in document[field])):
                    raise CodecContractError(f"codec alias requires nonempty {field}: {key}")
            self._aliases[key] = document

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._manifests))

    def __iter__(self) -> Iterator[str]:
        return iter(self.keys())

    def __len__(self) -> int:
        return len(self._manifests)

    def get(self, key: str) -> CodecManifest:
        if key in self._aliases:
            key = self._aliases[key]["canonical_key"]
        try:
            return self._manifests[key]
        except KeyError as error:
            raise CodecContractError(f"unknown codec key: {key}") from error

    def alias_documents(self) -> tuple[dict[str, Any], ...]:
        """Disclose logical names without introducing duplicate algorithm identities."""
        return tuple(
            {**deepcopy(document), "codec_alias_id": stable_id("codec-alias", document)}
            for _, document in sorted(self._aliases.items())
        )

    def verify_all(self) -> tuple[CodecManifest, ...]:
        return tuple(self._manifests[key] for key in self.keys())

    def _load(self, path: Path) -> CodecManifest:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodecContractError(f"cannot read codec manifest {path}: {error}") from error
        _require_keys(
            document,
            required={
                "schema_version",
                "key",
                "identity",
                "classification",
                "input",
                "semantics",
                "lifecycle",
                "execution",
                "features",
                "parameters",
                "adapter",
            },
            label=f"codec manifest {path.name}",
        )
        if document["schema_version"] != "tscb.codec-manifest.v2":
            raise CodecContractError(f"unsupported codec manifest schema: {path.name}")
        if path.stem != document["key"]:
            raise CodecContractError(f"codec key must match filename: {path.name}")
        identity = document["identity"]
        _require_keys(
            identity,
            required={"display_name", "family", "citations", "source_artifact_id"},
            label=f"{path.name}.identity",
        )
        if identity["source_artifact_id"] not in self.sources:
            raise CodecContractError(f"{path.name} references an unaudited source artifact")
        classification = document["classification"]
        _require_keys(
            classification,
            required={"object_level", "implementation_class", "tracks", "subtracks"},
            label=f"{path.name}.classification",
        )
        ObjectLevel(classification["object_level"])
        ImplementationClass(classification["implementation_class"])
        tracks = tuple(BenchmarkTrack(item) for item in classification["tracks"])
        if not tracks or len(set(tracks)) != len(tracks):
            raise CodecContractError(f"{path.name} must declare unique tracks")
        input_contract = document["input"]
        _require_keys(
            input_contract,
            required={
                "topologies",
                "dtypes",
                "ranks",
                "layouts",
                "endianness",
                "alignment_bytes",
                "min_n",
                "max_n",
                "min_m",
                "max_m",
                "validity_shapes",
                "value_coupling_mode",
                "timestamp_semantics",
            },
            optional={"homogeneous_itemsize", "max_total_raw_bytes"},
            label=f"{path.name}.input",
        )
        for value in input_contract["topologies"]:
            Topology(value)
        for value in input_contract["validity_shapes"]:
            ValidityShape(value)
        ValueCouplingMode(input_contract["value_coupling_mode"])
        if (
            "homogeneous_itemsize" in input_contract
            and type(input_contract["homogeneous_itemsize"]) is not bool
        ):
            raise CodecContractError(
                f"{path.name}.input homogeneous_itemsize must be boolean"
            )
        if (
            "max_total_raw_bytes" in input_contract
            and (
                type(input_contract["max_total_raw_bytes"]) is not int
                or input_contract["max_total_raw_bytes"] <= 0
            )
        ):
            raise CodecContractError(
                f"{path.name}.input max_total_raw_bytes must be a positive integer"
            )
        if input_contract["min_n"] < 0 or input_contract["min_m"] < 0:
            raise CodecContractError(f"{path.name} has negative input bounds")
        semantics = document["semantics"]
        _require_keys(
            semantics,
            required={
                "loss_modes",
                "error_bound_types",
                "reconstruction_modes",
                "rebuild_protocol",
                "preprocess_class",
                "preprocess_stages",
                "decodability_profile",
                "bitstream_separability",
            },
            label=f"{path.name}.semantics",
        )
        if not semantics["loss_modes"]:
            raise CodecContractError(f"{path.name} must declare a loss mode")
        for value in semantics["loss_modes"]:
            LossMode(value)
        for value in semantics["reconstruction_modes"]:
            ReconstructionMode(value)
        PreprocessClass(semantics["preprocess_class"])
        if not isinstance(semantics["preprocess_stages"], list):
            raise CodecContractError(f"{path.name} preprocess_stages must be an array")
        lifecycle = document["lifecycle"]
        _require_keys(
            lifecycle,
            required={
                "block_semantics",
                "state_semantics",
                "reset",
                "finalize",
                "safe_overread_bytes",
                "tail_policy",
                "dictionary",
                "model",
                "index",
            },
            label=f"{path.name}.lifecycle",
        )
        execution = document["execution"]
        _require_keys(
            execution,
            required={
                "backends",
                "isa",
                "devices",
                "threading",
                "fallback_policy",
                "runtime_dispatch",
            },
            label=f"{path.name}.execution",
        )
        features = document["features"]
        _require_keys(
            features,
            required={"streaming", "query", "random_access"},
            label=f"{path.name}.features",
        )
        if not all(isinstance(features[key], bool) for key in features):
            raise CodecContractError(f"{path.name} feature flags must be boolean")
        parameters = document["parameters"]
        _require_keys(
            parameters,
            required={"type", "additionalProperties", "properties", "constraints"},
            label=f"{path.name}.parameters",
        )
        if parameters["type"] != "object" or parameters["additionalProperties"] is not False:
            raise CodecContractError(f"{path.name} parameter schema must be a closed object")
        algorithm_id = stable_id("algorithm", document)
        return CodecManifest(key=document["key"], document=document, algorithm_id=algorithm_id)
