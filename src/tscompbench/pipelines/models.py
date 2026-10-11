"""Standalone logical objects and P2 recipes; legacy canonical wire is unchanged."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import numpy as np

from tscompbench.ids import canonical_json_bytes, stable_id


class PipelineError(ValueError):
    pass


def _logical_dtype(value: Any) -> np.dtype[Any]:
    try:
        dtype = np.dtype(value)
    except (TypeError, ValueError) as error:
        raise PipelineError("invalid logical dtype") from error
    if not isinstance(value, str) or value != dtype.str:
        raise PipelineError("logical dtype must use its explicit canonical NumPy wire spelling")
    return dtype


@dataclass(frozen=True)
class LogicalObjectSchema:
    serialized: bytes

    def __post_init__(self) -> None:
        doc = self.to_document()
        if (
            set(doc) != {"schema_version", "values", "timestamp", "null_recovery_contract"}
            or doc["schema_version"] != "tscb.logical-object-schema.v1"
        ):
            raise PipelineError("invalid standalone logical schema fields/version")
        if doc["null_recovery_contract"] not in {"BITWISE", "SEMANTIC"}:
            raise PipelineError("invalid null recovery contract")
        if not isinstance(doc["values"], list):
            raise PipelineError("ordered values must be an array")
        names = []
        counts = []
        for value in doc["values"]:
            if not isinstance(value, dict) or set(value) != {
                "name",
                "dtype",
                "shape",
                "axes",
                "time_axis",
                "unit",
                "entity",
                "feature",
            }:
                raise PipelineError("invalid ordered value schema")
            if not all(
                isinstance(value[k], str) and value[k]
                for k in ("name", "unit", "entity", "feature")
            ):
                raise PipelineError("ordered value identity and units must be explicit")
            names.append(value["name"])
            dtype = _logical_dtype(value["dtype"])
            if dtype.kind not in "iuf" or dtype.itemsize not in {1, 2, 4, 8}:
                raise PipelineError("unsupported value dtype")
            shape = value["shape"]
            if (
                not isinstance(shape, list)
                or not shape
                or len(shape) > 32
                or any(type(n) is not int or n < 0 for n in shape)
            ):
                raise PipelineError("invalid logical shape")
            if (
                not isinstance(value["axes"], list)
                or len(value["axes"]) != len(shape)
                or len(set(value["axes"])) != len(shape)
                or not all(isinstance(a, str) and a for a in value["axes"])
            ):
                raise PipelineError("axes must uniquely name every logical dimension")
            axis = value["time_axis"]
            if type(axis) is not int or not 0 <= axis < len(shape):
                raise PipelineError("explicit time axis is out of bounds")
            counts.append(shape[axis])
        if (
            not names
            or len(set(names)) != len(names)
            or len(set(counts)) != 1
            or "timestamp" in names
        ):
            raise PipelineError("values require unique names and a common synchronous time axis")
        timestamp = doc["timestamp"]
        if (
            not isinstance(timestamp, dict)
            or set(timestamp) != {"present", "dtype", "unit", "epoch", "pairing"}
            or type(timestamp["present"]) is not bool
        ):
            raise PipelineError("invalid timestamp schema")
        if timestamp["present"]:
            if (
                _logical_dtype(timestamp["dtype"]).kind not in "iu"
                or _logical_dtype(timestamp["dtype"]).itemsize != 8
                or timestamp["pairing"] != "SHARED_TIME_AXIS"
            ):
                raise PipelineError("timestamp must be a shared i64/u64 time axis")
            if not all(isinstance(timestamp[k], str) and timestamp[k] for k in ("unit", "epoch")):
                raise PipelineError("timestamp units and epoch are required")
        elif any(timestamp[k] != "NOT_APPLICABLE" for k in ("dtype", "unit", "epoch", "pairing")):
            raise PipelineError("absent timestamp metadata must be explicitly not applicable")
        if canonical_json_bytes(doc) != self.serialized:
            raise PipelineError("logical schema JSON must be canonical")

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> LogicalObjectSchema:
        return cls(canonical_json_bytes(document))

    def to_document(self) -> dict[str, Any]:
        try:
            document = json.loads(self.serialized)
            if not isinstance(document, dict):
                raise PipelineError("logical schema must be a JSON object")
            return document
        except (ValueError, UnicodeError) as error:
            raise PipelineError("invalid schema JSON") from error

    @property
    def schema_id(self) -> str:
        return stable_id("logical-object-schema", self.to_document(), version="v3")

    @property
    def n(self) -> int:
        value = self.to_document()["values"][0]
        return value["shape"][value["time_axis"]]


@dataclass(frozen=True)
class LogicalObject:
    schema: LogicalObjectSchema
    values: dict[str, np.ndarray[Any]]
    timestamp: np.ndarray[Any] | None = None
    validity: dict[str, np.ndarray[Any]] | None = None

    def __post_init__(self) -> None:
        doc = self.schema.to_document()
        if tuple(self.values) != tuple(v["name"] for v in doc["values"]):
            raise PipelineError("value order differs from logical schema")
        for item in doc["values"]:
            value = self.values[item["name"]]
            if value.dtype.str != np.dtype(item["dtype"]).str or list(value.shape) != item["shape"]:
                raise PipelineError("logical value dtype/shape differs from schema")
        if doc["timestamp"]["present"] != (self.timestamp is not None):
            raise PipelineError("timestamp presence differs from schema")
        if self.timestamp is not None and (
            self.timestamp.shape != (self.schema.n,)
            or self.timestamp.dtype.str != np.dtype(doc["timestamp"]["dtype"]).str
        ):
            raise PipelineError("timestamp dtype/shape violates T/V pairing")
        if self.validity is not None:
            if tuple(self.validity) != tuple(self.values):
                raise PipelineError("validity must cover every ordered value buffer")
            for name, value in self.values.items():
                mask = self.validity[name]
                if mask.dtype != np.bool_ or mask.shape != value.shape:
                    raise PipelineError("per-buffer validity must be a shape-matched boolean mask")

    @property
    def canonical_raw_bits(self) -> int:
        total = 0
        semantic = self.schema.to_document()["null_recovery_contract"] == "SEMANTIC"
        for name, value in self.values.items():
            count = (
                int(np.count_nonzero(self.validity[name]))
                if semantic and self.validity is not None
                else value.size
            )
            total += count * value.dtype.itemsize * 8
        return (
            total
            + (0 if self.timestamp is None else self.timestamp.nbytes * 8)
            + (0 if self.validity is None else sum(mask.size for mask in self.validity.values()))
        )

    @property
    def content_id(self) -> str:
        return self._hash(semantic=True)

    @property
    def underlying_bytes_sha256(self) -> str:
        return self._hash(semantic=False).rsplit(":", 1)[-1]

    def _hash(self, *, semantic: bool) -> str:
        digest = hashlib.sha256(self.schema.serialized)
        digest.update(b"VALIDITY_ABSENT" if self.validity is None else b"VALIDITY_PRESENT")
        normalized = semantic and self.schema.to_document()["null_recovery_contract"] == "SEMANTIC"
        for name, value in self.values.items():
            digest.update(name.encode())
            selected = (
                value[self.validity[name]] if normalized and self.validity is not None else value
            )
            digest.update(selected.tobytes(order="C"))
            if self.validity is not None:
                digest.update(
                    np.packbits(self.validity[name].reshape(-1), bitorder="little").tobytes()
                )
        if self.timestamp is not None:
            digest.update(self.timestamp.tobytes())
        return "v3:logical-object:sha256:" + digest.hexdigest()


@dataclass(frozen=True)
class RestoredObject(LogicalObject):
    """Owned materialized values and schema, usable after decoder close."""


@dataclass(frozen=True, init=False)
class ChildSpec:
    serialized: bytes

    def __init__(self, codec_key: str, parameters: dict[str, Any]) -> None:
        if not isinstance(codec_key, str) or not codec_key or not isinstance(parameters, dict):
            raise PipelineError("invalid child codec specification")
        object.__setattr__(
            self,
            "serialized",
            canonical_json_bytes({"codec_key": codec_key, "parameters": parameters}),
        )

    @property
    def codec_key(self) -> str:
        return self.to_document()["codec_key"]

    @property
    def parameters(self) -> dict[str, Any]:
        return self.to_document()["parameters"]

    def to_document(self) -> dict[str, Any]:
        return json.loads(self.serialized)

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> ChildSpec:
        if not isinstance(document, dict) or set(document) != {"codec_key", "parameters"}:
            raise PipelineError("invalid child codec specification")
        return cls(document["codec_key"], document["parameters"])


def validate_loss_contract(loss: dict[str, str]) -> None:
    if loss == {"kind": "LOSSLESS"}:
        return
    try:
        threshold = Decimal(loss["threshold"])
        valid = (
            set(loss) == {"kind", "threshold"}
            and loss["kind"] == "ABS"
            and isinstance(loss["threshold"], str)
            and threshold.is_finite()
            and threshold >= 0
        )
    except KeyError, TypeError, InvalidOperation:
        valid = False
    if not valid:
        raise PipelineError("pipeline loss contract must be lossless or finite nonnegative ABS")


_STAGES = ("TIME_AXIS_TO_FIRST", "LEXICOGRAPHIC_COLUMNS", "INDEPENDENT_BLOCKS", "TAIL_ENCODE")


@dataclass(frozen=True, init=False)
class PipelineRecipe:
    """Canonical snapshot; all public mapping properties return independent copies."""

    serialized: bytes

    def __init__(
        self,
        value_children: dict[str, ChildSpec],
        timestamp_child: ChildSpec | None,
        mask_child: ChildSpec | None,
        block_size: int,
        tail_policy: str = "RAW_TAIL",
        loss_contract: dict[str, str] | None = None,
        stages: tuple[str, ...] = _STAGES,
    ) -> None:
        if type(block_size) is not int or not 1 <= block_size <= 16_777_216:
            raise PipelineError("block size must be a positive bounded integer")
        if tail_policy not in {"RAW_TAIL", "COMPRESS_TAIL"}:
            raise PipelineError("tail policy must be frozen")
        if stages != _STAGES:
            raise PipelineError("this version executes only the declared ordered reversible stages")
        if (
            not isinstance(value_children, dict)
            or not value_children
            or any(
                not isinstance(name, str) or not name or not isinstance(child, ChildSpec)
                for name, child in value_children.items()
            )
        ):
            raise PipelineError("each original buffer requires a declared child")
        if any(
            child is not None and not isinstance(child, ChildSpec)
            for child in (timestamp_child, mask_child)
        ):
            raise PipelineError("invalid timestamp or mask child")
        loss = {"kind": "LOSSLESS"} if loss_contract is None else loss_contract
        validate_loss_contract(loss)
        object.__setattr__(
            self,
            "serialized",
            canonical_json_bytes(
                {
                    "schema_version": "tscb.pipeline-recipe.v1",
                    "value_children": {
                        key: value.to_document() for key, value in value_children.items()
                    },
                    "timestamp_child": None
                    if timestamp_child is None
                    else timestamp_child.to_document(),
                    "mask_child": None if mask_child is None else mask_child.to_document(),
                    "block_size": block_size,
                    "tail_policy": tail_policy,
                    "loss_contract": loss,
                    "stages": list(stages),
                }
            ),
        )

    def to_document(self) -> dict[str, Any]:
        return json.loads(self.serialized)

    @property
    def value_children(self) -> dict[str, ChildSpec]:
        return {
            name: ChildSpec.from_document(child)
            for name, child in self.to_document()["value_children"].items()
        }

    @property
    def timestamp_child(self) -> ChildSpec | None:
        child = self.to_document()["timestamp_child"]
        return None if child is None else ChildSpec.from_document(child)

    @property
    def mask_child(self) -> ChildSpec | None:
        child = self.to_document()["mask_child"]
        return None if child is None else ChildSpec.from_document(child)

    @property
    def block_size(self) -> int:
        return self.to_document()["block_size"]

    @property
    def tail_policy(self) -> str:
        return self.to_document()["tail_policy"]

    @property
    def loss_contract(self) -> dict[str, str]:
        return self.to_document()["loss_contract"]

    @property
    def stages(self) -> tuple[str, ...]:
        return tuple(self.to_document()["stages"])

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> PipelineRecipe:
        if (
            not isinstance(document, dict)
            or set(document)
            != {
                "schema_version",
                "value_children",
                "timestamp_child",
                "mask_child",
                "block_size",
                "tail_policy",
                "loss_contract",
                "stages",
            }
            or document["schema_version"] != "tscb.pipeline-recipe.v1"
            or not isinstance(document["value_children"], dict)
            or not isinstance(document["stages"], list)
        ):
            raise PipelineError("invalid pipeline recipe fields/version")
        return cls(
            {
                name: ChildSpec.from_document(child)
                for name, child in document["value_children"].items()
            },
            None
            if document["timestamp_child"] is None
            else ChildSpec.from_document(document["timestamp_child"]),
            None
            if document["mask_child"] is None
            else ChildSpec.from_document(document["mask_child"]),
            document["block_size"],
            document["tail_policy"],
            document["loss_contract"],
            tuple(document["stages"]),
        )

    @property
    def recipe_id(self) -> str:
        return stable_id("pipeline-recipe", self.to_document(), version="v3")


@dataclass(frozen=True)
class PipelineLedger:
    canonical_raw_bits: int
    payload_physical_bits: int
    metadata_physical_bits: int
    final_bits: int
    artifact_physical_bits: int
    required_external_bits: int = 0

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in self.__dict__.values()):
            raise PipelineError("pipeline ledger requires nonnegative integer bits")
        if (
            self.payload_physical_bits + self.metadata_physical_bits != self.artifact_physical_bits
            or self.final_bits != self.artifact_physical_bits + self.required_external_bits
        ):
            raise PipelineError("pipeline physical accounting does not close")

    def to_document(self) -> dict[str, Any]:
        return {"schema_version": "tscb.pipeline-ledger.v1", **self.__dict__}


@dataclass(frozen=True)
class PipelineArtifact:
    stream: bytes
    ledger: PipelineLedger
    recipe_id: str
    logical_content_id: str

    def __post_init__(self) -> None:
        if self.ledger.artifact_physical_bits != len(self.stream) * 8:
            raise PipelineError("pipeline ledger differs from actual stored bytes")


def column_count(shape: list[int], time_axis: int) -> int:
    return math.prod(size for index, size in enumerate(shape) if index != time_axis)
