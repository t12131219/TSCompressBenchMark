"""Pre-measurement decision contracts, derived without reading any observations.

The v1 comparison bundle remains unchanged. This separate versioned document
binds its intended decision, population and estimands to the frozen inputs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from tscompbench.ids import canonical_json_bytes, stable_id

from .models import ComparisonContract, CorpusSpec, GroupSpec

SCHEMA = "tscb.experiment-decision.v3.2"
FILENAME = "experiment_decision.json"


def _seal(body: dict[str, Any]) -> dict[str, Any]:
    # Own a canonical copy, so mutation of caller inputs cannot change a contract.
    document = json.loads(canonical_json_bytes(body))
    document["decision_id"] = stable_id("experiment-decision", document, version="v3")
    return document


def _valid(document: dict[str, Any]) -> None:
    fields = {
        "schema_version",
        "declaration_stage",
        "decision_context",
        "research_question",
        "target_population",
        "primary_estimands",
        "boundaries",
        "selection_policy",
        "conclusion_scope",
        "bindings",
        "decision_id",
    }
    if set(document) != fields or document["schema_version"] != SCHEMA:
        raise ValueError("decision contract has unknown/missing fields or version")
    if document["declaration_stage"] != "BEFORE_QUALIFICATION_PILOT_AND_FORMAL_MEASUREMENT":
        raise ValueError("decision contract must be declared before any measurement")
    if document["decision_id"] != stable_id(
        "experiment-decision",
        {k: v for k, v in document.items() if k != "decision_id"},
        version="v3",
    ):
        raise ValueError("decision contract identity drift")
    for key in ("decision_context", "research_question"):
        if not isinstance(document[key], str) or not document[key].strip():
            raise ValueError("decision contract needs an explicit " + key)


def comparison_decision(
    bundle: dict[str, Any],
    *,
    environment_id: str,
    control_plane_sha256: str,
    workload_protocol: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe the declared fixed-corpus decision, never an observed winner."""
    contract = ComparisonContract.from_document(bundle["contract"])
    corpus = CorpusSpec.from_document(bundle["corpus"])
    group = GroupSpec.from_document(bundle["group"])
    c = contract.to_document()
    research_question = c["research_question"]
    if not research_question.strip() or c["estimand"]["population"] != "FIXED_CORPUS":
        raise ValueError("implemented decision contract requires a question and FIXED_CORPUS")
    if not environment_id or not control_plane_sha256:
        raise ValueError("decision contract requires frozen environment and source identities")
    profile = bundle["protocol"]["profile"]
    kind = workload_protocol["kind"] if workload_protocol is not None else c["workload"]
    if kind == "STREAM":
        action = (
            "Assess the declared native stream methods for known-length fixed-row sessions "
            "through finalized full output and fresh exact recovery."
        )
        timing = "FINALIZED_SESSION_ENCODE_AND_FULL_DECODE_PER_OBJECT"
        unit = "INDEPENDENT_SPAWN_SESSION_SCHEDULE_BLOCK"
    elif kind == "QUERY":
        action = (
            "Assess the declared query variants for frozen point/range/column requests "
            "with owned original-domain output under the declared session/cache policy."
        )
        timing = "DECLARED_QUERY_API_AND_OWNED_COPY_INCLUDING_FRESH_SESSION_IF_SELECTED"
        unit = "INDEPENDENT_SPAWN_SESSION_SCHEDULE_BLOCK"
    elif c["mode"] == "COMMON_NATIVE_API":
        action = (
            "Assess interchangeable registered native components receiving identical "
            "actual input schemas and bytes under the declared CPU resources."
        )
        timing = "EXTERNAL_CORE_API_WALL_NS"
        unit = "PAIRED_PROCESS_SCHEDULE_BLOCK"
    elif c["fidelity"]["kind"] == "FIXED_ERROR":
        action = (
            "Assess complete-object storage and pipeline time among configurations that "
            "satisfy the declared original-domain fixed error and recovery contract."
        )
        timing = "INDEPENDENT_OBJECT_PIPELINE_WALL_NS"
        unit = "PAIRED_PROCESS_SCHEDULE_BLOCK"
    elif c["fidelity"]["kind"] == "QUALITY_CURVE":
        action = (
            "Assess storage/time/empirical quality tradeoffs on the predeclared quality "
            "grid, retaining every legal grid point without selecting on test outcomes."
        )
        timing = "INDEPENDENT_OBJECT_PIPELINE_WALL_NS"
        unit = "PAIRED_PROCESS_SCHEDULE_BLOCK"
    else:
        action = (
            "Assess complete-object storage and independent-object pipeline time for "
            "the declared fidelity and recovery contract under equal CPU resources."
        )
        timing = (
            "SPAWN_THROUGH_OUTPUT_MATERIALIZATION_WALL_NS"
            if profile == "COLD_PROCESS"
            else ("INDEPENDENT_OBJECT_PIPELINE_WALL_NS")
        )
        unit = "PAIRED_PROCESS_SCHEDULE_BLOCK"
    datasets = corpus.to_document()["datasets"]
    domain_evidence = [item for d in datasets for item in d["domain_evidence"]]
    model_symbols = any("BASE4_SYMBOL_STREAM" in item for item in domain_evidence)
    if model_symbols:
        action += " The measured objects are derived uint8 base4 symbols."
    limits = [
        "FIXED_DECLARED_CORPUS_AND_FROZEN_HOST_ONLY",
        "NO_UNSEEN_SOURCE_OR_MACHINE_POPULATION_GENERALIZATION",
        "SOURCE_PARITY_AND_DECODER_QUALIFICATION_ARE_SEPARATE_EVIDENCE",
        "SOURCE_WINDOWS_COLUMNS_AND_CASTS_DO_NOT_ADD_INDEPENDENT_SOURCES",
        "NO_POST_RESULT_MEMBER_CORPUS_CONFIG_OR_PRIMARY_ESTIMAND_SELECTION",
    ]
    if c["cost_boundary"] == "SCHEMA_BOUND_OBJECT":
        limits.append("PAID_SCHEMA_BOUND_CONTEXT_NOT_A_SELF_DESCRIBING_SINGLE_STREAM")
    if c["mode"] == "COMMON_NATIVE_API":
        limits.append("NATIVE_COMPONENT_COST_AND_CORE_TIME_NOT_COMPLETE_OBJECT_DEPLOYMENT")
    if c["fidelity"]["kind"] == "QUALITY_CURVE":
        limits.append("EMPIRICAL_QUALITY_GRID_NOT_A_FIXED_ERROR_GUARANTEE")
    if model_symbols:
        limits.extend(
            [
                "UINT8_BASE4_SYMBOL_TASK_NOT_ORIGINAL_FLOATING_OBJECT",
                "MODEL_TRAINING_TEST_OVERLAP_UNKNOWN_NO_UNSEEN_DATA_GENERALIZATION",
            ]
        )
    if kind == "STREAM":
        limits.append("KNOWN_LENGTH_FINALIZED_OUTPUT_NO_UNKNOWN_LENGTH_OR_BACKPRESSURE_CLAIM")
    if kind == "QUERY":
        limits.extend(
            [
                "RELATED_IMPLEMENTATION_VARIANTS_RESEARCH_SCOPE",
                "LOGICAL_BYTES_TOUCHED_NOT_HARDWARE_MEMORY_TRAFFIC",
                "SESSION_REPETITIONS_DO_NOT_INCREASE_INDEPENDENT_SOURCE_COUNT",
            ]
        )
    return _seal(
        {
            "schema_version": SCHEMA,
            "declaration_stage": "BEFORE_QUALIFICATION_PILOT_AND_FORMAL_MEASUREMENT",
            "decision_context": action + " Research question: " + research_question,
            "research_question": research_question,
            "target_population": {
                "kind": "FIXED_CORPUS",
                "corpus_id": corpus.id,
                "datasets": datasets,
                "independent_real_source_groups": sorted(corpus.independent_real_source_groups()),
                "sampling_design": corpus.to_document()["sampling_design"],
            },
            "primary_estimands": {
                "declared": c["estimand"],
                "storage": c["cost_boundary"],
                "time": timing,
                "paired_unit": unit,
                "quality": c["fidelity"],
                "analysis_policy": bundle["analysis_policy"],
            },
            "boundaries": {
                "mode": c["mode"],
                "track": c["track"],
                "state": c["state"],
                "cost_boundary": c["cost_boundary"],
                "timing_boundary": c["timing_boundary"],
                "recovery": c["recovery"],
                "fidelity": c["fidelity"],
                "resources": c["resources"],
                "cpu_affinity": bundle["cpu_affinity"],
                "measurement_protocol": bundle["protocol"],
                "workload_protocol": workload_protocol,
            },
            "selection_policy": {
                "policy": c["selection_policy"],
                "corpus_selection_rule": corpus.to_document()["selection_rule"],
                "corpus_exclusion_rule": corpus.to_document()["exclusion_rule"],
                "group": group.to_document(),
                "config_map": bundle["config_map"],
            },
            "conclusion_scope": limits,
            "bindings": {
                "contract_id": contract.id,
                "corpus_id": corpus.id,
                "group_id": group.id,
                "measurement_protocol_id": c["measurement_protocol_id"],
                "analysis_policy_id": c["analysis_policy_id"],
                "environment_id": environment_id,
                "control_plane_sha256": control_plane_sha256,
                "bundle_sha256_id": stable_id("comparison-bundle", bundle, version="v3"),
            },
        }
    )


def pipeline_decision(
    *,
    datasets: list[dict[str, Any]],
    protocol: dict[str, Any],
    analysis_policy: dict[str, Any],
    resources: dict[str, Any],
    closure: dict[str, Any],
    boundary: str,
    scope: str,
) -> dict[str, Any]:
    """P2 complete-object intent from predeclared objects/recipe implementation."""
    if not datasets or not closure or not resources or not boundary or not scope:
        raise ValueError("pipeline decision requires fixed objects, resources and source closure")
    question = (
        "For the fixed declared timestamp/value/validity objects, compare registered P2 "
        "recipes' finalized complete-object bits and steady independent-object encode/decode "
        "pipeline wall time under the same single-worker CPU resources and exact recovery."
    )
    return _seal(
        {
            "schema_version": SCHEMA,
            "declaration_stage": "BEFORE_QUALIFICATION_PILOT_AND_FORMAL_MEASUREMENT",
            "decision_context": (
                "Assess the declared P2 object recipes for this fixed corpus and host."
            ),
            "research_question": question,
            "target_population": {"kind": "FIXED_CORPUS", "datasets": datasets},
            "primary_estimands": {
                "storage": "FINALIZED_COMPLETE_OBJECT_BITS_INCLUDING_T_AND_VALIDITY",
                "time": "INDEPENDENT_OBJECT_ENCODE_AND_DECODE_PIPELINE_WALL_NS",
                "paired_unit": "PAIRED_PROCESS_SCHEDULE_BLOCK",
                "analysis_policy": analysis_policy,
            },
            "boundaries": {
                "boundary": boundary,
                "scope": scope,
                "resources": resources,
                "measurement_protocol": protocol,
                "fidelity": "EXACT_ORIGINAL_OBJECT_UNDER_DECLARED_NULL_SEMANTICS",
                "object_schemas": [d["test"]["schema"] for d in datasets],
            },
            "selection_policy": {
                "members": sorted(closure.get("children", closure.get("codecs", {}))),
                "kind": "PREDECLARED_FIXED_RECIPES_NO_TEST_SELECTION",
            },
            "conclusion_scope": [
                "FIXED_DECLARED_CORPUS_AND_FROZEN_HOST_ONLY",
                "NO_UNSEEN_SOURCE_MACHINE_OR_ALL_RECIPE_POPULATION_GENERALIZATION",
                "P2_RECIPE_COST_NOT_NATIVE_COMPONENT_ONLY_COST",
                "SOURCE_PARITY_IS_SEPARATE_EVIDENCE",
            ],
            "bindings": {
                "inputs_id": stable_id("pipeline-decision-inputs", datasets, version="v3"),
                "implementation_closure_id": stable_id(
                    "pipeline-decision-closure", closure, version="v3"
                ),
                "protocol_id": stable_id("pipeline-decision-protocol", protocol, version="v3"),
            },
        }
    )


def freeze_experiment_decision(
    run_path: Path,
    document: dict[str, Any],
    *,
    resume: bool = False,
) -> None:
    """Write once before work; missing or changed resume proof is never backfilled."""
    _valid(document)
    path = run_path / FILENAME
    encoded = json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True)
    payload = (encoded + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("existing frozen experiment decision differs")
        return
    if resume:
        raise ValueError("resume requires the original pre-measurement experiment decision")
    measured_files = (
        "qualification.json",
        "qualification_intent.json",
        "qualification_failure.json",
        "qualification_interruption_audit.json",
        "pilot.json",
        "comparison_trials.jsonl",
        "workload_pilot.json",
        "workload_trials.jsonl",
        "pipeline_events.jsonl",
        "trials.jsonl",
        "events.jsonl",
        "workload_events.jsonl",
    )
    if any((run_path / name).exists() for name in measured_files):
        raise ValueError("cannot backfill an experiment decision after measurement started")
    run_path.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def validate_experiment_decision(
    run_path: Path,
    plan: dict[str, Any],
    expected_document: dict[str, Any],
) -> None:
    """Read-only comparison to independently rederived predeclared frozen inputs."""
    _valid(expected_document)
    if not (run_path / FILENAME).is_file():
        raise ValueError("missing pre-measurement experiment decision")
    document = json.loads((run_path / FILENAME).read_text(encoding="utf-8"))
    _valid(document)
    if (
        document != expected_document
        or plan.get("decision") != document
        or plan.get("decision_id") != document["decision_id"]
    ):
        raise ValueError("experiment decision sidecar/plan/frozen input identity differs")
