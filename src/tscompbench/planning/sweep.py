from __future__ import annotations

import itertools
from decimal import Decimal, InvalidOperation
from typing import Any

from tscompbench.codecs import CodecManifest
from tscompbench.contracts import RunStatus
from tscompbench.ids import stable_id

from .models import ResolvedConfig


class PlanningError(ValueError):
    pass


def _normalize_value(value: Any, specification: dict[str, Any]) -> Any:
    expected = specification["type"]
    if expected == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise PlanningError("expected integer")
        normalized = value
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise PlanningError("expected boolean")
        normalized = value
    elif expected == "string":
        if not isinstance(value, str):
            raise PlanningError("expected string")
        normalized = value
    elif expected == "decimal-string":
        if not isinstance(value, str):
            raise PlanningError("decimal parameters must be strings, never binary floats")
        try:
            decimal = Decimal(value)
        except InvalidOperation as error:
            raise PlanningError("invalid decimal string") from error
        if not decimal.is_finite():
            raise PlanningError("decimal parameter must be finite")
        normalized = format(decimal.normalize(), "f")
    else:
        raise PlanningError(f"unsupported parameter type: {expected}")
    if "enum" in specification and normalized not in specification["enum"]:
        raise PlanningError("value is outside enum")
    if "minimum" in specification and normalized < specification["minimum"]:
        raise PlanningError("value is below minimum")
    if "maximum" in specification and normalized > specification["maximum"]:
        raise PlanningError("value is above maximum")
    return normalized


def _validate_constraints(parameters: dict[str, Any], constraints: list[dict[str, Any]]) -> None:
    for constraint in constraints:
        kind = constraint.get("kind")
        if kind == "forbid_combination":
            matches = constraint.get("when", {})
            if all(parameters.get(key) == value for key, value in matches.items()):
                raise PlanningError(constraint.get("reason", "forbidden parameter combination"))
        elif kind == "requires":
            when = constraint.get("when", {})
            if all(parameters.get(key) == value for key, value in when.items()):
                required = constraint.get("required", {})
                if not all(parameters.get(key) in values for key, values in required.items()):
                    raise PlanningError(constraint.get("reason", "conditional requirement failed"))
        else:
            raise PlanningError(f"unknown parameter constraint kind: {kind}")


def expand_sweep(
    manifest: CodecManifest,
    sweep: dict[str, tuple[Any, ...] | list[Any]],
    *,
    framework_parameters: dict[str, Any] | None = None,
) -> tuple[ResolvedConfig, ...]:
    schema = manifest.document["parameters"]
    properties = schema["properties"]
    parameter_names = sorted(set(properties) | set(sweep))
    values: list[tuple[Any, ...]] = []
    for name in parameter_names:
        if name in sweep:
            candidates = tuple(sweep[name])
            if not candidates:
                candidates = (None,)
        elif name in properties and "default" in properties[name]:
            candidates = (properties[name]["default"],)
        else:
            candidates = (None,)
        values.append(candidates)

    framework_parameters = dict(framework_parameters or {})
    resolved: list[ResolvedConfig] = []
    for combination in itertools.product(*values):
        raw = dict(zip(parameter_names, combination, strict=True))
        status = RunStatus.PLANNED
        reason = "VALID"
        normalized: dict[str, Any] = {}
        try:
            unknown = set(raw) - set(properties)
            if unknown:
                raise PlanningError(f"unknown parameters: {sorted(unknown)}")
            for name, value in raw.items():
                if value is None:
                    raise PlanningError(f"parameter lacks value/default: {name}")
                normalized[name] = _normalize_value(value, properties[name])
            _validate_constraints(normalized, schema["constraints"])
        except PlanningError as error:
            status = RunStatus.SCHEMA_ERROR
            reason = str(error)
            normalized = raw
        identity = {
            "algorithm_id": manifest.algorithm_id,
            "parameters": normalized,
            "framework_parameters": framework_parameters,
            "parameter_schema_version": "tscb.codec-parameters.v2",
        }
        resolved.append(
            ResolvedConfig(
                algorithm_id=manifest.algorithm_id,
                parameters=normalized,
                framework_parameters=framework_parameters,
                status=status,
                reason_code=reason,
                config_id=stable_id("config", identity),
            )
        )
    return tuple(resolved)
