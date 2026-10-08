"""Admission and evidence validation for explicitly reviewed pipeline executors."""

from __future__ import annotations

from typing import Any

from .contracts import PreprocessContractError, PreprocessPlan, build_preprocess_plan
from .maskedvbyte import EXECUTOR_ID as MASKED_EXECUTOR_ID
from .maskedvbyte import STAGE_SPEC as MASKED_STAGE_SPEC
from .maskedvbyte import validate_stage_snapshot as validate_masked_snapshot
from .simdcomp import EXECUTOR_IDS as SIMD_EXECUTOR_IDS
from .simdcomp import STAGE_SPECS as SIMD_STAGE_SPECS
from .simdcomp import validate_stage_snapshot as validate_simd_snapshot
from .streamvbyte import EXECUTOR_ID, STAGE_SPEC, validate_stage_snapshot
from .streamvbyte_modern import EXECUTOR_ID as MODERN_EXECUTOR_ID
from .streamvbyte_modern import STAGE_SPEC as MODERN_STAGE_SPEC

_EXECUTORS = {
    **{
        key: ("SIMDCOMP_CTYPES_V1", executor, SIMD_STAGE_SPECS[key])
        for key, executor in SIMD_EXECUTOR_IDS.items()
    },
    "delta-maskedvbyte-u32": ("MASKEDVBYTE_CTYPES_V1", MASKED_EXECUTOR_ID, MASKED_STAGE_SPEC),
    "delta-zigzag-streamvbyte64": ("STREAMVBYTE_PIPELINE_CTYPES_V1", EXECUTOR_ID, STAGE_SPEC),
    "delta-zigzag-streamvbyte-modern64": (
        "STREAMVBYTE_MODERN_PIPELINE_CTYPES_V1",
        MODERN_EXECUTOR_ID,
        MODERN_STAGE_SPEC,
    ),
}


def reviewed_pipeline_executor(
    manifest: dict[str, Any], adapter: Any, plan: PreprocessPlan, parameters: dict[str, Any]
) -> bool:
    if not plan.stages:
        return True
    registered = _EXECUTORS.get(manifest["key"])
    if registered is None:
        return False
    factory, executor_id, stage_spec = registered
    return (
        manifest["adapter"].get("factory") == factory
        and manifest["adapter"].get("pipeline_executor_id") == executor_id
        and manifest["semantics"]["preprocess_stages"] == stage_spec
        and manifest["semantics"]["preprocess_class"]
        == (
            "LOSSLESS_SEMANTIC"
            if executor_id in {MASKED_EXECUTOR_ID, *SIMD_EXECUTOR_IDS.values()}
            else "LOSSLESS_LAYOUT"
        )
        and getattr(adapter, "pipeline_executor_id", None) == executor_id
        and plan == build_preprocess_plan(manifest, parameters)
        and parameters.get("stage_d", True) is True
    )


def validate_pipeline_stages(adapter: Any, routed: Any, parameters: dict[str, Any]) -> dict:
    executor_id = getattr(adapter, "pipeline_executor_id", None)
    if executor_id in SIMD_EXECUTOR_IDS.values():
        return validate_simd_snapshot(adapter.inspect_preprocess(routed, parameters))
    if executor_id == MASKED_EXECUTOR_ID:
        return validate_masked_snapshot(adapter.inspect_preprocess(routed, parameters))
    if executor_id not in {EXECUTOR_ID, MODERN_EXECUTOR_ID}:
        raise PreprocessContractError("pipeline executor has no independent stage validator")
    return validate_stage_snapshot(
        adapter.inspect_preprocess(routed, parameters), executor_id=executor_id
    )
