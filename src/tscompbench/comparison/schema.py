"""Closed JSON schemas and dependency-free validation for comparison v1."""

from __future__ import annotations

import re
from typing import Any


class ComparisonSpecError(ValueError):
    """A frozen experiment specification or its execution binding is invalid."""


def obj(properties: dict, *, optional: tuple[str, ...] = ()) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [key for key in properties if key not in optional],
        "properties": properties,
    }


def arr(items: dict, *, minimum: int = 0, unique: bool = False) -> dict:
    return {"type": "array", "items": items, "minItems": minimum, "uniqueItems": unique}


TEXT = {"type": "string", "minLength": 1}
SHA = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
INTEGER = {"type": "integer", "minimum": 0}
POSITIVE = {"type": "integer", "minimum": 1}
NULL_TEXT = {"type": ["string", "null"]}
PARAMETERS = {"type": "object", "additionalProperties": {"type": ["string", "integer", "boolean"]}}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


FIDELITY = obj(
    {
        "kind": enum("LOSSLESS", "FIXED_ERROR", "QUALITY_CURVE"),
        "error_metric": NULL_TEXT,
        "threshold": NULL_TEXT,
        "unit": TEXT,
        "quality_metrics": arr(TEXT, unique=True),
    }
)
RECOVERY = obj(
    {
        "mode": enum("EXACT_GRID", "APPROX_GRID"),
        "null_semantics": enum("BITWISE", "SEMANTIC"),
        "coordinate_policy": enum("PRESERVE_ORIGINAL_GRID", "NOT_APPLICABLE"),
    }
)
RESOURCE = obj(
    {
        "device": {"const": "CPU"},
        "threads": POSITIVE,
        "processes": POSITIVE,
        "memory_limit_bytes": POSITIVE,
        "machine_policy_id": TEXT,
        "isa_policy": enum("ANY_AVAILABLE", "FIXED"),
        "allowed_isa": arr(TEXT, unique=True),
    }
)
SELECTION = obj(
    {
        "kind": enum("FROZEN_DEFAULT", "FULL_GRID", "VALIDATION_SELECT"),
        "max_configs_per_method": POSITIVE,
        "selection_dataset_ids": arr(TEXT, unique=True),
        "objective": NULL_TEXT,
        "tie_break": TEXT,
        "selection_cost_policy": TEXT,
    }
)
METHOD = obj(
    {
        "name": TEXT,
        "mechanism": TEXT,
        "variant": TEXT,
        "semantic_version": TEXT,
        "definition_sha256": SHA,
    }
)
IMPLEMENTATION = obj(
    {
        "method_id": TEXT,
        "source_artifact_id": TEXT,
        "source_closure_sha256": SHA,
        "implementation_variant": TEXT,
    }
)
GUARANTEE = obj(
    {
        "kind": enum("LOSSLESS", "PROVEN_BOUND", "UNBOUNDED", "RATE_CONTROLLED"),
        "metric": NULL_TEXT,
        "threshold": NULL_TEXT,
        "unit": TEXT,
        "original_domain_total": {"type": "boolean"},
    }
)
SOURCE = obj(
    {"family": TEXT, "entity": TEXT, "independence_unit": TEXT, "evidence": arr(TEXT, minimum=1)}
)
PARENT = obj(
    {
        "dataset_id": TEXT,
        "source_kind": enum("REAL", "SYNTHETIC"),
        "family": TEXT,
        "entity": TEXT,
        "independence_unit": TEXT,
    }
)
EXPECTED = obj(
    {
        "outcome": enum("PASS", "REJECT", "BLOCKED"),
        "origin": enum("TASK", "SOURCE_DOMAIN", "ADAPTER", "COMPOSITION", "ENVIRONMENT", "SOURCE"),
        "stage": TEXT,
        "reason": TEXT,
        "evidence": arr(TEXT, minimum=1),
    }
)
PATHS = enum(
    "DIRECT",
    "EXACT_WIDEN",
    "LOSSY_CAST",
    "BYTE_SERIALIZATION",
    "COLUMN_INDEPENDENT",
    "JOINT",
    "SOURCE_REJECT_RAW",
)


def versioned(name: str, properties: dict) -> dict:
    schema = obj({"schema_version": {"const": f"tscb.{name}.v1"}, **properties})
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"tscb.{name}.v1",
        **schema,
    }


SCHEMAS = {
    "task-spec": versioned(
        "task-spec",
        {
            "dataset_id": TEXT,
            "logical_content_id": TEXT,
            "logical_schema": obj(
                {
                    "track": enum("VALUE", "TIMESTAMP", "SYSTEM"),
                    "topology": enum(
                        "UTS", "SYNCHRONOUS_MTS", "ASYNCHRONOUS_MTS", "NATIVE_ND_ARRAY"
                    ),
                    "dtypes": arr(TEXT, minimum=1),
                    "shape": arr(INTEGER, minimum=1),
                    "axes": arr(TEXT, minimum=1),
                    "channel_ids": arr(TEXT, minimum=1, unique=True),
                    "units": arr(TEXT, minimum=1),
                    "timestamp_unit": TEXT,
                    "timestamp_epoch": TEXT,
                    "validity": enum("NONE", "ROW", "CELL", "PER_CHANNEL_RAGGED"),
                    "order": {"const": "PRESERVE_ORIGINAL"},
                    "pairing": TEXT,
                }
            ),
            "recovery": RECOVERY,
            "fidelity": FIDELITY,
            "cost_boundary": enum(
                "SCHEMA_BOUND_OBJECT", "SELF_CONTAINED_OBJECT", "NATIVE_COMPONENT"
            ),
            "workload": enum("WHOLE_OBJECT", "API_COMPONENT"),
            "state": enum("INDEPENDENT_OBJECT", "CONTINUOUS_STREAM"),
        },
    ),
    "comparison-contract": versioned(
        "comparison-contract",
        {
            "name": TEXT,
            "revision": TEXT,
            "research_question": TEXT,
            "estimand": obj(
                {
                    "population": enum("FIXED_CORPUS", "SOURCE_GENERALIZATION"),
                    "outcome": TEXT,
                    "aggregation": TEXT,
                    "weight_unit": enum("DATASET", "SOURCE", "RAW_BITS"),
                }
            ),
            "mode": enum("COMPLETE_OBJECT", "COMMON_NATIVE_API"),
            "track": enum("VALUE", "TIMESTAMP", "SYSTEM"),
            "recovery": RECOVERY,
            "fidelity": FIDELITY,
            "cost_boundary": enum(
                "SCHEMA_BOUND_OBJECT", "SELF_CONTAINED_OBJECT", "NATIVE_COMPONENT"
            ),
            "timing_boundary": enum("PIPELINE", "E2E", "CORE_API"),
            "workload": enum("WHOLE_OBJECT", "API_COMPONENT"),
            "state": enum("INDEPENDENT_OBJECT", "CONTINUOUS_STREAM"),
            "resources": RESOURCE,
            "selection_policy": SELECTION,
            "measurement_protocol_id": TEXT,
            "analysis_policy_id": TEXT,
        },
    ),
    "group-spec": versioned(
        "group-spec",
        {
            "name": TEXT,
            "revision": TEXT,
            "contract_id": TEXT,
            "corpus_id": TEXT,
            "config_map_id": TEXT,
            "expected_matrix_id": TEXT,
            "scope": enum("CORE_COMPARISON", "RESEARCH"),
            "minimum_distinct_methods": POSITIVE,
            "minimum_independent_real_sources": POSITIVE,
            "completion_policy": {"const": "ALL_CORE_LEGAL_CONFIGS_AND_EXPECTED_TERMINALS"},
            "members": arr(
                obj(
                    {
                        "member_id": TEXT,
                        "codec_key": TEXT,
                        "role": enum("CORE", "EXTENSION", "REFERENCE"),
                        "method": METHOD,
                        "implementation": IMPLEMENTATION,
                        "allowed_paths": arr(PATHS, minimum=1, unique=True),
                        "shared_code_tags": arr(TEXT, unique=True),
                    }
                ),
                minimum=1,
            ),
            "method_equivalence": arr(
                obj(
                    {
                        "class_id": TEXT,
                        "members": arr(TEXT, minimum=1, unique=True),
                        "basis": TEXT,
                        "evidence": arr(TEXT, minimum=1),
                    }
                ),
                minimum=1,
            ),
        },
    ),
    "corpus-spec": versioned(
        "corpus-spec",
        {
            "name": TEXT,
            "revision": TEXT,
            "selection_rule": TEXT,
            "sampling_design": TEXT,
            "exclusion_rule": TEXT,
            "datasets": arr(
                obj(
                    {
                        "dataset_id": TEXT,
                        "logical_content_id": TEXT,
                        "artifact_sha256": SHA,
                        "role": enum("CORE", "EXTENSION"),
                        "source_kind": enum("REAL", "SYNTHETIC"),
                        "source": SOURCE,
                        "parents": arr(PARENT),
                        "derivation": enum(
                            "ORIGINAL",
                            "RESAMPLE",
                            "COLUMN",
                            "WINDOW",
                            "QUANTIZED",
                            "SERIALIZATION",
                            "SYNTHETIC",
                        ),
                        "split": enum("TEST", "VALIDATION", "TRAIN", "UNSPLIT"),
                        "weight": TEXT,
                        "domain_evidence": arr(TEXT, minimum=1),
                    }
                ),
                minimum=1,
            ),
        },
    ),
    "method-config-map": versioned(
        "method-config-map",
        {
            "contract_id": TEXT,
            "selection_policy": SELECTION,
            "members": arr(
                obj(
                    {
                        "member_id": TEXT,
                        "configs": arr(
                            obj(
                                {
                                    "config_key": TEXT,
                                    "parameters": PARAMETERS,
                                    "framework_parameters": PARAMETERS,
                                    "loss_mode": enum(
                                        "LOSSLESS",
                                        "ERROR_BOUNDED_LOSSY",
                                        "UNBOUNDED_LOSSY",
                                        "RATE_CONTROLLED_LOSSY",
                                    ),
                                    "guarantee": GUARANTEE,
                                }
                            ),
                            minimum=1,
                        ),
                    }
                ),
                minimum=1,
            ),
        },
    ),
    "expected-outcome-matrix": versioned(
        "expected-outcome-matrix",
        {
            "contract_id": TEXT,
            "corpus_id": TEXT,
            "config_map_id": TEXT,
            "entries": arr(
                obj(
                    {
                        "dataset_id": TEXT,
                        "member_id": TEXT,
                        "config_key": TEXT,
                        "expected": EXPECTED,
                    }
                ),
                minimum=1,
            ),
        },
    ),
    "execution-job": versioned(
        "execution-job",
        {
            "task_spec_id": TEXT,
            "member_id": TEXT,
            "method_id": TEXT,
            "implementation_id": TEXT,
            "algorithm_id": TEXT,
            "config_id": TEXT,
            "recipe_id": TEXT,
            "view_id": TEXT,
            "execution_path_hash": TEXT,
            "source_artifact_id": TEXT,
            "build_id": TEXT,
            "runtime_id": TEXT,
            "original_content_id": TEXT,
            "actual_input_id": TEXT,
            "actual_input_schema_id": TEXT,
            "path": PATHS,
            "backend": TEXT,
            "actual_isa": TEXT,
            "timing_boundary": enum("PIPELINE", "E2E", "CORE_API"),
            "state": enum("INDEPENDENT_OBJECT", "CONTINUOUS_STREAM"),
            "resources": RESOURCE,
            "loss_mode": enum(
                "LOSSLESS", "ERROR_BOUNDED_LOSSY", "UNBOUNDED_LOSSY", "RATE_CONTROLLED_LOSSY"
            ),
            "guarantee": GUARANTEE,
        },
    ),
    "method-definition": versioned("method-definition", METHOD["properties"]),
    "implementation-definition": versioned(
        "implementation-definition", IMPLEMENTATION["properties"]
    ),
}


# Optional, versioned identity policy preserves existing v1 documents and IDs.
SCHEMAS["corpus-spec"]["properties"]["content_identity_policy"] = enum(
    "tscb.dataset-content.v1", "tscb.dataset-content.v2"
)


def validate_schema(value: Any, schema: dict, path: str = "$") -> None:
    """Validate the explicit JSON Schema subset used by the closed v1 specs."""
    if "const" in schema and value != schema["const"]:
        raise ComparisonSpecError(f"{path}: unsupported constant/version")
    if "enum" in schema and value not in schema["enum"]:
        raise ComparisonSpecError(f"{path}: value outside allowed domain")
    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        valid = any(
            {
                "object": isinstance(value, dict),
                "array": isinstance(value, list),
                "string": isinstance(value, str),
                "integer": type(value) is int,
                "boolean": type(value) is bool,
                "null": value is None,
            }[kind]
            for kind in types
        )
        if not valid:
            raise ComparisonSpecError(f"{path}: expected {expected}")
    if isinstance(value, dict):
        required, properties = set(schema.get("required", [])), schema.get("properties", {})
        missing = required - set(value)
        unknown = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if missing or (additional is False and unknown):
            raise ComparisonSpecError(
                f"{path}: missing={sorted(missing)}, unknown={sorted(unknown)}"
            )
        for key, item in value.items():
            child = properties.get(key, additional if isinstance(additional, dict) else {})
            validate_schema(item, child, f"{path}.{key}")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            raise ComparisonSpecError(f"{path}: insufficient entries")
        if schema.get("uniqueItems") and any(
            item in value[:index] for index, item in enumerate(value)
        ):
            raise ComparisonSpecError(f"{path}: duplicate entries")
        for index, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{path}[{index}]")
    elif isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or (
            "pattern" in schema and not re.fullmatch(schema["pattern"], value)
        ):
            raise ComparisonSpecError(f"{path}: invalid string")
    elif type(value) is int and value < schema.get("minimum", value):
        raise ComparisonSpecError(f"{path}: below minimum")
