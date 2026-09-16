from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from tscompbench.contracts import PreprocessClass
from tscompbench.ids import stable_id


class PreprocessContractError(ValueError):
    pass


@dataclass(frozen=True)
class PreprocessStage:
    name: str
    stage_class: PreprocessClass
    stage_slot: str
    parameters: dict[str, Any]
    inverse_required: bool
    accounting_components: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.stage_slot not in {"A", "B", "C", "D"}:
            raise PreprocessContractError("pipeline stage slot must be A, B, C, or D")
        if self.stage_class is PreprocessClass.NONE and self.parameters:
            raise PreprocessContractError("NONE preprocess cannot have parameters")


@dataclass(frozen=True)
class PreprocessPlan:
    stages: tuple[PreprocessStage, ...]
    preprocess_plan_id: str

    @classmethod
    def create(cls, stages: tuple[PreprocessStage, ...]) -> PreprocessPlan:
        slots = [stage.stage_slot for stage in stages]
        if slots != sorted(slots) or len(slots) != len(set(slots)):
            raise PreprocessContractError("pipeline stages must be unique and ordered A to D")
        return cls(stages=stages, preprocess_plan_id=stable_id("preprocess-plan", stages))

    @property
    def semantic_class(self) -> PreprocessClass:
        classes = {stage.stage_class for stage in self.stages}
        if PreprocessClass.LOSSY_PREPROCESS in classes:
            return PreprocessClass.LOSSY_PREPROCESS
        if PreprocessClass.TRAINING_LEARNED in classes:
            return PreprocessClass.TRAINING_LEARNED
        if PreprocessClass.LOSSLESS_SEMANTIC in classes:
            return PreprocessClass.LOSSLESS_SEMANTIC
        if PreprocessClass.LOSSLESS_LAYOUT in classes:
            return PreprocessClass.LOSSLESS_LAYOUT
        return PreprocessClass.NONE

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": "tscb.preprocess-plan.v2",
            "stages": self.stages,
            "preprocess_plan_id": self.preprocess_plan_id,
            "semantic_class": self.semantic_class,
        }


def build_preprocess_plan(manifest_document: dict[str, Any]) -> PreprocessPlan:
    semantics = manifest_document["semantics"]
    declared_class = PreprocessClass(semantics["preprocess_class"])
    stages = tuple(
        PreprocessStage(
            name=item["name"],
            stage_class=PreprocessClass(item["stage_class"]),
            stage_slot=item["stage_slot"],
            parameters=item.get("parameters", {}),
            inverse_required=bool(item["inverse_required"]),
            accounting_components=tuple(item.get("accounting_components", [])),
        )
        for item in semantics["preprocess_stages"]
    )
    plan = PreprocessPlan.create(stages)
    if plan.semantic_class is not declared_class:
        raise PreprocessContractError(
            "manifest preprocess_class does not match its explicit pipeline stages"
        )
    return plan


def validate_preprocess(
    original: np.ndarray[Any],
    reconstructed: np.ndarray[Any],
    plan: PreprocessPlan,
    *,
    max_abs_error: str | None = None,
    split_evidence: dict[str, Any] | None = None,
) -> None:
    if original.shape != reconstructed.shape:
        raise PreprocessContractError("preprocess inverse changed logical shape")
    semantic_class = plan.semantic_class
    if semantic_class in {
        PreprocessClass.NONE,
        PreprocessClass.LOSSLESS_LAYOUT,
        PreprocessClass.LOSSLESS_SEMANTIC,
    }:
        restored = reconstructed.astype(original.dtype, copy=False)
        if restored.tobytes(order="C") != original.tobytes(order="C"):
            raise PreprocessContractError("lossless preprocess inverse is not bit-exact")
    elif semantic_class is PreprocessClass.LOSSY_PREPROCESS:
        if max_abs_error is None:
            raise PreprocessContractError("lossy preprocess requires a declared error bound")
        observed = np.max(
            np.abs(reconstructed.astype(np.longdouble) - original.astype(np.longdouble)),
            initial=np.longdouble(0),
        )
        if observed > np.longdouble(max_abs_error):
            raise PreprocessContractError("lossy preprocess violated its declared bound")
    elif semantic_class is PreprocessClass.TRAINING_LEARNED:
        required = {
            "train_id",
            "validation_id",
            "test_id",
            "seed",
            "checkpoint_sha256",
            "model_bits",
        }
        if split_evidence is None or required - set(split_evidence):
            raise PreprocessContractError("learned preprocess lacks split/model evidence")
        split_ids = {
            split_evidence["train_id"],
            split_evidence["validation_id"],
            split_evidence["test_id"],
        }
        if len(split_ids) < 3:
            raise PreprocessContractError("learned train/validation/test identities overlap")
