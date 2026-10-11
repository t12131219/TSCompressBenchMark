"""Admission for declared preprocessing; executors require independent review."""

from __future__ import annotations

from typing import Any

from .contracts import PreprocessContractError, PreprocessPlan


def reviewed_pipeline_executor(
    manifest: dict[str, Any], adapter: Any, plan: PreprocessPlan, parameters: dict[str, Any]
) -> bool:
    # The retired integer pipelines were the only registered stage executors.
    # Preserve the gate: future stages cannot run without a reviewed executor.
    return not plan.stages


def validate_pipeline_stages(adapter: Any, routed: Any, parameters: dict[str, Any]) -> dict:
    raise PreprocessContractError("pipeline executor has no independent stage validator")
