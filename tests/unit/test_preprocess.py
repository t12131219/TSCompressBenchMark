import numpy as np
import pytest

from tscompbench.contracts import PreprocessClass
from tscompbench.preprocess import (
    PreprocessContractError,
    PreprocessPlan,
    PreprocessStage,
    validate_preprocess,
)


def test_preprocess_is_separate_from_adapter_and_validated_by_declared_semantics() -> None:
    stage = PreprocessStage(
        name="checked-delta",
        stage_class=PreprocessClass.LOSSLESS_SEMANTIC,
        stage_slot="A",
        parameters={"overflow": "REJECT"},
        inverse_required=True,
        accounting_components=("HEADER_BITS",),
    )
    plan = PreprocessPlan.create((stage,))
    original = np.array([1, 2, 5, 9], dtype="<i8")
    validate_preprocess(original, original.copy(), plan)
    with pytest.raises(PreprocessContractError, match="not bit-exact"):
        validate_preprocess(original, np.array([1, 2, 5, 8], dtype="<i8"), plan)


def test_lossy_preprocess_cannot_validate_without_its_own_bound() -> None:
    plan = PreprocessPlan.create(
        (
            PreprocessStage(
                name="quantize",
                stage_class=PreprocessClass.LOSSY_PREPROCESS,
                stage_slot="A",
                parameters={"step": "0.1"},
                inverse_required=True,
                accounting_components=(),
            ),
        )
    )
    original = np.array([0.0, 1.0], dtype="<f8")
    with pytest.raises(PreprocessContractError, match="declared error bound"):
        validate_preprocess(original, original.copy(), plan)
