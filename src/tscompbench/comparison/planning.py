from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tscompbench.contracts import RunStatus
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.planning.sweep import expand_sweep

from .models import (
    ComparisonContract,
    CorpusSpec,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    admit_fidelity,
    finite_decimal,
    implementation_id,
    method_id,
)
from .schema import ComparisonSpecError


@dataclass(frozen=True)
class PlannedComparisonCell:
    serialized: bytes

    def to_document(self) -> dict:
        import json

        return json.loads(self.serialized)

    @property
    def id(self) -> str:
        return stable_id("planned-comparison-cell", self.to_document(), version="v3")

    @property
    def dataset_id(self) -> str:
        return self.to_document()["dataset_id"]

    @property
    def member_id(self) -> str:
        return self.to_document()["member_id"]

    @property
    def config_key(self) -> str:
        return self.to_document()["config_key"]


@dataclass(frozen=True)
class ComparisonPlan:
    group_id: str
    contract_id: str
    corpus_id: str
    config_map_id: str
    expected_matrix_id: str
    cells: tuple[PlannedComparisonCell, ...]
    denominator_bytes: bytes

    @property
    def denominators(self) -> dict:
        import json

        return json.loads(self.denominator_bytes)

    @property
    def id(self) -> str:
        return stable_id("comparison-plan", self.to_document(), version="v3")

    def to_document(self) -> dict:
        return {
            "schema_version": "tscb.comparison-plan.v1",
            "group_id": self.group_id,
            "contract_id": self.contract_id,
            "corpus_id": self.corpus_id,
            "config_map_id": self.config_map_id,
            "expected_matrix_id": self.expected_matrix_id,
            "cells": [{"cell_id": c.id, **c.to_document()} for c in self.cells],
            "denominators": self.denominators,
        }


def registered_source_closure_digest(codec_registry: Any, codec_key: str) -> str:
    """Use the audited closure digest, or the complete source-identity digest.

    Rewritten packages describe their closure as hashed API/source manifests
    inside SourceArtifactID rather than a single source_closure_sha256 field.
    """
    manifest = codec_registry.get(codec_key)
    source = codec_registry.sources.get(manifest.source_artifact_id)
    return source.get("identity", {}).get(
        "source_closure_sha256", manifest.source_artifact_id.rsplit(":", 1)[-1]
    )


def _bind_config_guarantee(manifest: Any, parameters: dict, config: dict, member: dict) -> None:
    """Bind the admitted bound to the actual registered mode and parameter.

    The current executable guarantee mapping is pointwise absolute error on
    unchanged values. Other native metrics or lossy input transforms need their
    own total original-domain derivation before they can claim a proven bound.
    """
    if config["loss_mode"] != "ERROR_BOUNDED_LOSSY":
        return
    guarantee = config["guarantee"]
    kind = parameters.get("error_bound_type")
    supported = manifest.document["semantics"]["error_bound_types"]
    if kind not in supported or kind not in {"ABS", "ABSOLUTE"}:
        raise ComparisonSpecError("registered error mode has no executable guarantee mapping")
    if guarantee["metric"] != "MAXAE_V1" or guarantee["unit"] != "ORIGINAL_VALUE_UNITS":
        raise ComparisonSpecError(
            "absolute error configuration requires MAXAE_V1 in original units"
        )
    native_bound = parameters.get("error_bound")
    if not isinstance(native_bound, str) or finite_decimal(native_bound, positive=True) != (
        finite_decimal(guarantee["threshold"], positive=True)
    ):
        raise ComparisonSpecError("guarantee threshold differs from normalized error_bound")
    if guarantee["original_domain_total"] and (
        manifest.document["semantics"]["preprocess_class"] != "NONE"
        or "LOSSY_CAST" in member["allowed_paths"]
    ):
        raise ComparisonSpecError("lossy input transformation lacks a total original-domain bound")


def compile_group_plan(
    group: GroupSpec,
    contract: ComparisonContract,
    corpus: CorpusSpec,
    config_map: MethodConfigMap,
    expected_matrix: ExpectedOutcomeMatrix,
    *,
    codec_registry: Any,
    active_codec_keys: set[str],
) -> ComparisonPlan:
    """Expand the full frozen matrix and validate configs against real manifests.

    Aliases and retired/out-of-scope registrations cannot be admitted by a group.
    The compiler never observes results or removes failing rows from its universe.
    """
    g, c, d, m, e = (
        spec.to_document() for spec in (group, contract, corpus, config_map, expected_matrix)
    )
    refs = {
        "contract_id": contract.id,
        "corpus_id": corpus.id,
        "config_map_id": config_map.id,
        "expected_matrix_id": expected_matrix.id,
    }
    if any(g[key] != value for key, value in refs.items()):
        raise ComparisonSpecError("group references do not bind the frozen specification bundle")
    if m["contract_id"] != contract.id or m["selection_policy"] != c["selection_policy"]:
        raise ComparisonSpecError("method config policy differs from comparison contract")
    if any(e[key] != refs[key] for key in ("contract_id", "corpus_id", "config_map_id")):
        raise ComparisonSpecError("expected matrix does not bind corpus/config/contract")
    members = {member["member_id"]: member for member in g["members"]}
    configurations = {member["member_id"]: member["configs"] for member in m["members"]}
    if set(members) != set(configurations):
        raise ComparisonSpecError("method config map must include every frozen member")
    selected = set(c["selection_policy"]["selection_dataset_ids"])
    by_dataset = {row["dataset_id"]: row for row in d["datasets"]}
    if not selected <= set(by_dataset) or any(
        by_dataset[dataset_id]["split"] not in {"VALIDATION", "TRAIN"} for dataset_id in selected
    ):
        raise ComparisonSpecError("selection data must be frozen development members of the corpus")
    evaluation_datasets = [row for row in d["datasets"] if row["split"] in {"TEST", "UNSPLIT"}]
    test_ids = {
        row["dataset_id"]
        for row in d["datasets"]
        if row["role"] == "CORE" and row["split"] in {"TEST", "UNSPLIT"}
    }
    if selected & test_ids:
        raise ComparisonSpecError("configuration selection data overlaps core test data")
    evaluation_contents = {row["logical_content_id"] for row in evaluation_datasets}
    if any(
        by_dataset[dataset_id]["logical_content_id"] in evaluation_contents
        for dataset_id in selected
    ):
        raise ComparisonSpecError(
            "selection and evaluation datasets share the same logical content"
        )
    core_classes = {
        eq["class_id"]
        for eq in g["method_equivalence"]
        if any(members[mid]["role"] == "CORE" for mid in eq["members"])
    }
    source_groups = corpus.independent_real_source_groups()
    if len(core_classes) < g["minimum_distinct_methods"]:
        raise ComparisonSpecError(
            "frozen core lacks distinct methods; build/config copies do not count"
        )
    if len(source_groups) < g["minimum_independent_real_sources"]:
        raise ComparisonSpecError("frozen corpus lacks independent real source families/entities")
    expected = {
        (row["dataset_id"], row["member_id"], row["config_key"]): row["expected"]
        for row in e["entries"]
    }
    universe = {
        (dataset["dataset_id"], mid, config["config_key"])
        for dataset in evaluation_datasets
        for mid in members
        for config in configurations[mid]
    }
    if set(expected) != universe:
        raise ComparisonSpecError(
            "expected matrix must cover the full frozen universe without extra cells"
        )
    cells = []
    per_method_configs: dict[str, set[str]] = {}
    registration_keys = set(codec_registry.keys())
    for mid, member in sorted(members.items()):
        key = member["codec_key"]
        if "SOURCE_REJECT_RAW" in member["allowed_paths"] and (
            key != "alp" or c["mode"] != "COMPLETE_OBJECT"
        ):
            raise ComparisonSpecError("source-reject RAW is an explicit complete-object ALP recipe")
        if key not in registration_keys or key not in active_codec_keys:
            raise ComparisonSpecError(
                "member is an alias, retired, or outside the active codec scope"
            )
        manifest = codec_registry.get(key)
        if member["implementation"]["source_artifact_id"] != manifest.source_artifact_id:
            raise ComparisonSpecError("implementation source differs from the active registration")
        if member["implementation"]["source_closure_sha256"] != registered_source_closure_digest(
            codec_registry, key
        ):
            raise ComparisonSpecError(
                "implementation closure differs from the frozen source artifact"
            )
        if c["track"] not in {track.value for track in manifest.tracks}:
            raise ComparisonSpecError("registered codec does not declare the group track")
        member_config_ids = set()
        for config in configurations[mid]:
            if set(config["framework_parameters"]) - {"benchmark_seed"}:
                raise ComparisonSpecError(
                    "unknown framework parameter; codec parameters must be method-local"
                )
            if "benchmark_seed" in config["framework_parameters"] and (
                type(config["framework_parameters"]["benchmark_seed"]) is not int
                or config["framework_parameters"]["benchmark_seed"] < 0
            ):
                raise ComparisonSpecError("benchmark_seed must be a nonnegative integer")
            admit_fidelity(c["fidelity"], config)
            if config["loss_mode"] not in {mode.value for mode in manifest.loss_modes}:
                raise ComparisonSpecError(
                    "configuration loss mode is not declared by the active codec"
                )
            resolved = expand_sweep(
                manifest,
                {name: [value] for name, value in config["parameters"].items()},
                framework_parameters=config["framework_parameters"],
            )
            if len(resolved) != 1 or resolved[0].status is not RunStatus.PLANNED:
                raise ComparisonSpecError(
                    f"illegal configuration for {key}: {resolved[0].reason_code}"
                )
            normalized = resolved[0]
            _bind_config_guarantee(manifest, normalized.parameters, config, member)
            config_document = {
                "method_id": method_id(member["method"]),
                "parameters": normalized.parameters,
                "framework_parameters": normalized.framework_parameters,
                "loss_mode": config["loss_mode"],
                "guarantee": config["guarantee"],
            }
            config_id = stable_id("method-config", config_document, version="v3")
            if config_id in member_config_ids:
                raise ComparisonSpecError(
                    "duplicate normalized configuration cannot create a new curve point"
                )
            member_config_ids.add(config_id)
            unique_points = per_method_configs.setdefault(method_id(member["method"]), set())
            unique_points.add(config_id)
            if len(unique_points) > c["selection_policy"]["max_configs_per_method"]:
                raise ComparisonSpecError(
                    "implementations jointly exceed the per-method selection budget"
                )
            for dataset in sorted(evaluation_datasets, key=lambda row: row["dataset_id"]):
                expectation = expected[(dataset["dataset_id"], mid, config["config_key"])]
                cells.append(
                    PlannedComparisonCell(
                        canonical_json_bytes(
                            {
                                "schema_version": "tscb.planned-comparison-cell.v1",
                                "group_id": group.id,
                                "dataset_id": dataset["dataset_id"],
                                "logical_content_id": dataset["logical_content_id"],
                                "artifact_sha256": dataset["artifact_sha256"],
                                "dataset_role": dataset["role"],
                                "member_id": mid,
                                "member_role": member["role"],
                                "codec_key": key,
                                "algorithm_id": manifest.algorithm_id,
                                "source_artifact_id": manifest.source_artifact_id,
                                "method_id": method_id(member["method"]),
                                "implementation_id": implementation_id(member["implementation"]),
                                "config_key": config["config_key"],
                                "config_id": config_id,
                                "legacy_config_id": normalized.config_id,
                                "parameters": normalized.parameters,
                                "framework_parameters": normalized.framework_parameters,
                                "loss_mode": config["loss_mode"],
                                "guarantee": config["guarantee"],
                                "allowed_paths": member["allowed_paths"],
                                "expected": expectation,
                            }
                        )
                    )
                )
    core = [
        cell.to_document()
        for cell in cells
        if cell.to_document()["dataset_role"] == "CORE"
        and cell.to_document()["member_role"] == "CORE"
    ]
    denominators = {
        "all_cells": len(cells),
        "core_cells": len(core),
        "core_expected_pass_cells": sum(cell["expected"]["outcome"] == "PASS" for cell in core),
        "core_expected_reject_cells": sum(cell["expected"]["outcome"] == "REJECT" for cell in core),
        "core_expected_blocked_cells": sum(
            cell["expected"]["outcome"] == "BLOCKED" for cell in core
        ),
        "core_members": sum(member["role"] == "CORE" for member in members.values()),
        "distinct_core_methods": len(core_classes),
        "independent_real_sources": len(source_groups),
        "independent_real_source_groups": source_groups,
    }
    return ComparisonPlan(
        group.id,
        contract.id,
        corpus.id,
        config_map.id,
        expected_matrix.id,
        tuple(cells),
        canonical_json_bytes(denominators),
    )


def validate_job_for_cell(
    group: GroupSpec,
    cell: PlannedComparisonCell,
    task: Any,
    job: Any,
) -> None:
    """Bind measured job disclosures to the admitted frozen member/config/path."""
    planned, t, j = cell.to_document(), task.to_document(), job.to_document()
    if planned["group_id"] != group.id:
        raise ComparisonSpecError("comparison cell belongs to another frozen group")
    if (
        t["dataset_id"] != planned["dataset_id"]
        or t["logical_content_id"] != planned["logical_content_id"]
    ):
        raise ComparisonSpecError("execution task differs from the frozen corpus cell")
    for key in (
        "member_id",
        "method_id",
        "implementation_id",
        "algorithm_id",
        "config_id",
        "source_artifact_id",
        "loss_mode",
        "guarantee",
    ):
        if j[key] != planned[key]:
            raise ComparisonSpecError(f"execution job differs from its frozen cell: {key}")
    if j["path"] not in planned["allowed_paths"]:
        raise ComparisonSpecError(
            "execution recipe path is not admitted by the frozen group member"
        )
