"""Auditable descriptive extensions of an already frozen comparison analysis.

No codec is called. Source-balanced summaries, quality points and Pareto sets
remain restricted to the complete predeclared corpus and its measured host.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from tscompbench.ids import canonical_json_bytes, stable_id

from .analysis import trial_issues
from .models import CorpusSpec


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation, ValueError, TypeError:
        return None
    return result if result.is_finite() and result >= 0 else None


def _text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _mean(values: list[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        return sum(values, Decimal(0)) / len(values)


def _summary(values: list[Decimal]) -> dict | None:
    if not values:
        return None
    return {"mean": _text(_mean(values)), "min": _text(min(values)), "max": _text(max(values))}


def _quality(records: list[dict], loss_mode: str) -> dict:
    if loss_mode == "LOSSLESS":
        return {
            "status": "EXACT_LOSSLESS_REFERENCE" if records else "NO_OBSERVATIONS",
            "reference_only": True,
            "original_domain_rmse": "0" if records else None,
            "original_domain_max_ae": "0" if records else None,
            "derivation": "ELIGIBLE_BITWISE_CORRECTNESS_IMPLIES_ZERO_ERROR",
            "channels": [],
            "ranking_metrics": {},
        }
    losses = [(record.get("correctness") or {}).get("loss") or {} for record in records]
    invalid = []
    expected_names = None
    collected: dict[str, list[dict]] = defaultdict(list)
    pooled, maxima = [], []
    for loss in losses:
        channels = loss.get("channels") or []
        if (
            loss.get("schema_version") != "tscb.loss-validation.v3"
            or loss.get("quality_valid") is not True
            or loss.get("nonfinite_mismatch_count") != 0
            or not channels
        ):
            invalid.append(loss.get("quality_invalid_reason") or "ORIGINAL_DOMAIN_QUALITY_MISSING")
            continue
        names = [channel.get("name") for channel in channels]
        if len(set(names)) != len(names) or any(not isinstance(name, str) for name in names):
            invalid.append("QUALITY_CHANNEL_IDENTITY_INVALID")
            continue
        if expected_names is None:
            expected_names = names
        if names != expected_names:
            invalid.append("QUALITY_CHANNEL_ORDER_CHANGED")
            continue
        squared, count, maximum = Decimal(0), 0, Decimal(0)
        sample = {}
        for channel in channels:
            rmse, max_ae = _number(channel.get("rmse")), _number(channel.get("max_ae"))
            finite = channel.get("finite_pair_count")
            if (
                channel.get("quality_valid") is not True
                or channel.get("nonfinite_mismatch_count") != 0
                or type(finite) is not int
                or finite <= 0
                or rmse is None
                or max_ae is None
            ):
                invalid.append(channel.get("quality_invalid_reason") or "QUALITY_NONFINITE_OR_NA")
                break
            sample[channel["name"]] = {"rmse": rmse, "max_ae": max_ae, "count": finite}
            with localcontext() as context:
                context.prec = 80
                squared += rmse * rmse * finite
            count += finite
            maximum = max(maximum, max_ae)
        else:
            with localcontext() as context:
                context.prec = 80
                pooled.append((squared / count).sqrt())
            maxima.append(maximum)
            for name, values in sample.items():
                collected[name].append(values)
    if not records or invalid or len(pooled) != len(records):
        return {
            "status": "INVALID_OR_MISSING",
            "reference_only": False,
            "original_domain_rmse": None,
            "original_domain_max_ae": None,
            "channels": [],
            "ranking_metrics": {},
            "reasons": sorted(set(invalid)) or ["NO_ELIGIBLE_OBSERVATIONS"],
        }
    channel_rows, ranking = [], {}
    for name in expected_names or []:
        values = collected[name]
        if len({item["count"] for item in values}) != 1:
            return {
                "status": "INVALID_OR_MISSING",
                "reference_only": False,
                "original_domain_rmse": None,
                "original_domain_max_ae": None,
                "channels": [],
                "ranking_metrics": {},
                "reasons": ["QUALITY_FINITE_POPULATION_CHANGED"],
            }
        rmse = _summary([item["rmse"] for item in values])
        max_ae = _summary([item["max_ae"] for item in values])
        channel_rows.append(
            {"name": name, "finite_pair_count": values[0]["count"], "rmse": rmse, "max_ae": max_ae}
        )
        ranking[f"RMSE_V1:{name}"] = rmse["max"]
        ranking[f"MAXAE_V1:{name}"] = max_ae["max"]
    return {
        "status": "VALID",
        "reference_only": False,
        "original_domain_rmse": _text(_mean(pooled)),
        "original_domain_max_ae": _text(max(maxima)),
        "rmse_observed_range": [_text(min(pooled)), _text(max(pooled))],
        "channels": channel_rows,
        "ranking_metrics": ranking,
        "numeric_reduction": "DECIMAL_80_FROM_ORIGINAL_DOMAIN_CHANNEL_OBSERVATIONS",
        "pooled_rmse_scope": "NUMERIC_ELEMENT_WEIGHTED_DESCRIPTION_NO_UNIT_NORMALIZATION",
        "ranking_scope": "PER_CHANNEL_ORIGINAL_UNITS_NO_COMPOSITE_QUALITY_SCORE",
    }


def _metrics(cell: dict, records: list[dict]) -> dict:
    final_bits, api_bits, encode, decode, rss = [], [], [], [], []
    cost_metric = (
        "api_serialized_bits" if cell.get("cost_boundary") == "NATIVE_COMPONENT" else "final_bits"
    )
    components: dict[str, list[Decimal]] = defaultdict(list)
    for record in records:
        accounting, timing = record.get("accounting") or {}, record.get("timing") or {}
        for name, value in accounting.items():
            if name.endswith("_bits") and name not in {"canonical_raw_bits", "final_bits"}:
                component = _number(value)
                if component is not None:
                    components[name].append(component)
        bits = _number(accounting.get("final_bits"))
        iterations = _number(timing.get("inner_iterations"))
        if bits is not None:
            final_bits.append(bits)
        api = _number(accounting.get("serialized_bits"))
        if api is not None:
            api_bits.append(api)
        for direction, values in (("encode", encode), ("decode", decode)):
            time = _number(timing.get(f"selected_{direction}_wall_ns"))
            if time is not None and iterations is not None and iterations > 0:
                with localcontext() as context:
                    context.prec = 80
                    values.append(time / iterations)
        resources = record.get("resources") or {}
        peak = _number(resources.get("peak_process_rss_bytes"))
        if resources.get("actual_scope") == "PROCESS" and peak is not None:
            rss.append(peak)
    count = len(records)
    samples = {
        "final_bits": final_bits,
        "encode_ns_per_object": encode,
        "decode_ns_per_object": decode,
        "process_rss_bytes": rss,
    }
    if cost_metric == "api_serialized_bits":
        samples[cost_metric] = api_bits
    summaries = {
        name: _summary(values) if len(values) == count and count else None
        for name, values in samples.items()
    }
    objectives = {
        name: summary["max"] if name == "process_rss_bytes" else summary["mean"]
        for name, summary in summaries.items()
        if summary is not None
    }
    if cost_metric != "final_bits":
        objectives.pop("final_bits", None)
    raw = _number(cell.get("canonical_raw_bits"))
    ratio = None
    if raw is not None and raw > 0 and cost_metric in objectives:
        with localcontext() as context:
            context.prec = 80
            ratio = _text(Decimal(objectives[cost_metric]) / raw)
    return {
        "observations": summaries,
        "accounting_components": {
            name: _summary(values) if len(values) == count and count else None
            for name, values in sorted(components.items())
        },
        "accounting_scope": "ACTUAL_ELIGIBLE_RECORD_COMPONENTS_NO_RECONSTRUCTED_COST",
        "objectives": objectives,
        "cost_metric": cost_metric,
        "size_ratio": ratio,
        "missing_metrics": [name for name in samples if name not in objectives],
        "rss_scope": "ABSOLUTE_PROCESS_HIGH_WATER_MAX_OF_PROCESS_OBSERVATIONS",
    }


def _pareto(points: list[dict]) -> list[dict]:
    partitions: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for point in points:
        partitions[(point["dataset_id"], point["public_projection_key"])].append(point)
    result = []
    for (dataset, projection), rows in sorted(partitions.items()):
        cost_metric = rows[0]["metrics"].get("cost_metric", "final_bits")
        quality_required = any(
            row["loss_mode"] in {"UNBOUNDED_LOSSY", "RATE_CONTROLLED_LOSSY"} for row in rows
        )
        quality_names = set().union(*(set(row["quality"]["ranking_metrics"]) for row in rows))
        objectives = (
            [cost_metric, "encode_ns_per_object", "decode_ns_per_object", "process_rss_bytes"]
            + sorted(quality_names)
            if quality_required
            else [cost_metric, "encode_ns_per_object", "decode_ns_per_object", "process_rss_bytes"]
        )
        vectors, unavailable = {}, []
        for row in rows:
            vector = {
                **row["metrics"]["objectives"],
                **(row["quality"]["ranking_metrics"] if quality_required else {}),
            }
            missing = [
                name for name in objectives if name not in vector or _number(vector[name]) is None
            ]
            if (
                not row["formal_complete"]
                or missing
                or (quality_required and row["quality"]["status"] != "VALID")
            ):
                unavailable.append(
                    {
                        "cell_id": row["cell_id"],
                        "status": "N/A",
                        "missing_metrics": missing,
                        "reason": "INCOMPLETE_CELL_OR_QUALITY_OR_OBJECTIVE",
                    }
                )
                continue
            vectors[row["cell_id"]] = {name: Decimal(vector[name]) for name in objectives}
        dominated_by = {}
        for key, vector in vectors.items():
            dominators = [
                other
                for other, candidate in vectors.items()
                if other != key
                and all(candidate[name] <= vector[name] for name in objectives)
                and any(candidate[name] < vector[name] for name in objectives)
            ]
            if dominators:
                dominated_by[key] = sorted(dominators)
        result.append(
            {
                "dataset_id": dataset,
                "public_projection_key": projection,
                "objectives_minimized": objectives,
                "status": "COMPLETE_FIXED_UNIVERSE_FRONTIER"
                if not unavailable
                else "PARTIAL_OBSERVED_FRONTIER",
                "full_universe_frontier": not unavailable,
                "planned_points": len(rows),
                "observed_points": len(vectors),
                "frontier_cell_ids": sorted(set(vectors) - set(dominated_by)),
                "dominated_by": dominated_by,
                "unavailable": unavailable,
                "quality_policy": "PER_CHANNEL_ERROR_OBJECTIVES"
                if quality_required
                else "COMMON_FROZEN_FIDELITY",
                "inference": "DESCRIPTIVE_POINT_ESTIMATES_NO_PARETO_CONFIDENCE_CLAIM",
            }
        )
    return result


def _source_balanced(points: list[dict], corpus: CorpusSpec) -> dict:
    groups = corpus.independent_real_source_groups()
    mapped = {dataset: index for index, group in enumerate(groups) for dataset in group}
    members: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for point in points:
        if point["role"] == "CORE":
            members[(point["member_id"], point["config_label"])].append(point)
    aggregates = []
    for (member, config), rows in sorted(members.items()):
        source_rows = []
        for index, group in enumerate(groups):
            selected = [row for row in rows if mapped.get(row["dataset_id"]) == index]
            complete = bool(selected) and all(
                row["formal_complete"]
                and row["expected_outcome"] == "PASS"
                and all(
                    name in row["metrics"]["objectives"]
                    for name in (
                        row["metrics"].get("cost_metric", "final_bits"),
                        "encode_ns_per_object",
                        "decode_ns_per_object",
                    )
                )
                for row in selected
            )
            raw = sum((Decimal(row["canonical_raw_bits"]) for row in selected), Decimal(0))
            item = {
                "source_group_index": index,
                "dataset_ids": list(group),
                "planned_cells": len(selected),
                "complete_cells": sum(row["formal_complete"] for row in selected),
                "fixed_raw_bits": _text(raw),
                "status": "COMPLETE" if complete and raw > 0 else "INCOMPLETE",
                "size_ratio": None,
                "encode_ns_per_raw_bit": None,
                "decode_ns_per_raw_bit": None,
            }
            if item["status"] == "COMPLETE":
                with localcontext() as context:
                    context.prec = 80
                    for objective, output in (
                        (selected[0]["metrics"].get("cost_metric", "final_bits"), "size_ratio"),
                        ("encode_ns_per_object", "encode_ns_per_raw_bit"),
                        ("decode_ns_per_object", "decode_ns_per_raw_bit"),
                    ):
                        item[output] = _text(
                            sum(
                                (
                                    Decimal(row["metrics"]["objectives"][objective])
                                    for row in selected
                                ),
                                Decimal(0),
                            )
                            / raw
                        )
            source_rows.append(item)
        unmapped = [row["cell_id"] for row in rows if row["dataset_id"] not in mapped]
        complete = (
            bool(groups)
            and not unmapped
            and all(row["status"] == "COMPLETE" for row in source_rows)
        )
        item = {
            "member_id": member,
            "config_label": config,
            "status": "COMPLETE" if complete else "INCOMPLETE",
            "planned_source_groups": len(groups),
            "complete_source_groups": sum(row["status"] == "COMPLETE" for row in source_rows),
            "planned_cells": len(rows),
            "unmapped_cells": unmapped,
            "sources": source_rows,
            "source_balanced_size_ratio": None,
            "source_balanced_encode_ns_per_raw_bit": None,
            "source_balanced_decode_ns_per_raw_bit": None,
        }
        if complete:
            for metric in ("size_ratio", "encode_ns_per_raw_bit", "decode_ns_per_raw_bit"):
                item[f"source_balanced_{metric}"] = _text(
                    _mean([Decimal(row[metric]) for row in source_rows])
                )
        aggregates.append(item)
    return {
        "independent_source_groups": [list(group) for group in groups],
        "independent_source_count": len(groups),
        "within_source_weighting": "FIXED_RAW_BITS_WEIGHTED_WORKLOAD",
        "between_source_weighting": "EQUAL_WEIGHT_PER_INDEPENDENCE_GROUP",
        "missing_policy": "FULL_FIXED_DENOMINATOR_NO_PARTIAL_AGGREGATE",
        "inference": "DESCRIPTIVE_FROZEN_SOURCES_NO_POPULATION_CI",
        "aggregates": aggregates,
    }


def _coverage(points: list[dict], cells: dict[str, dict], trials: list[dict], corpus: dict) -> dict:
    by_dataset = {row["dataset_id"]: row for row in corpus["datasets"]}
    actual: dict[str, list[dict]] = defaultdict(list)
    for trial in trials:
        actual[trial["cell_id"]].append(trial)
    matrices = {
        name: []
        for name in (
            "SourceCapabilityMatrix",
            "StandalonePortMatrix",
            "BenchProfileMatrix",
            "PipelineCoverageMatrix",
        )
    }
    for point in points:
        cell = cells[point["cell_id"]]
        dataset = by_dataset.get(point["dataset_id"], {})
        observed = {
            "formal_complete": point["formal_complete"],
            "eligible_process_count": point["eligible_process_count"],
            "planned_process_count": point["planned_process_count"],
            "terminal_attempts": len(actual[point["cell_id"]]),
            "status_counts": dict(
                sorted(
                    Counter(
                        (t.get("record") or {}).get("status", t.get("status", "NOT_RUN"))
                        for t in actual[point["cell_id"]]
                    ).items()
                )
            ),
        }
        common = {
            "cell_id": point["cell_id"],
            "dataset_id": point["dataset_id"],
            "member_id": point["member_id"],
            "config_label": point["config_label"],
            "source_artifact_id": cell.get("source_artifact_id"),
            "source": dataset.get("source"),
            "parents": dataset.get("parents", []),
            "domain_evidence": dataset.get("domain_evidence", []),
            "expected_outcome": point["expected_outcome"],
            "observed": observed,
        }
        matrices["SourceCapabilityMatrix"].append(
            {
                **common,
                "claim_status": "UNKNOWN",
                "authority": "SOURCE_ARTIFACT_POINTER_ONLY",
                "reason": "ORIGINAL_SOURCE_CAPABILITY_FACTS_NOT_SUPPLIED_BY_EXECUTION_PLAN",
            }
        )
        matrices["StandalonePortMatrix"].append(
            {
                **common,
                "claim_status": "UNKNOWN_OR_NA",
                "authority": "NOT_SUPPLIED",
                "reason": "PORT_SCOPE_AND_EVIDENCE_REQUIRE_THE_VERSIONED_SOURCE_AUDIT",
            }
        )
        matrices["BenchProfileMatrix"].append(
            {
                **common,
                "claim_status": "FROZEN_DECLARATION",
                "authority": "FROZEN_EXECUTION_PLAN",
                "parameters": point["parameters"],
                "loss_mode": point["loss_mode"],
                "guarantee": point["guarantee"],
                "expected_evidence": cell.get("expected", {}).get("evidence", []),
            }
        )
        matrices["PipelineCoverageMatrix"].append(
            {
                **common,
                "claim_status": "MEASURED_TASK" if point["formal_complete"] else "PLANNED_TASK",
                "authority": "FROZEN_PATH_AND_AUDITED_TRIALS",
                "allowed_paths": cell.get("allowed_paths", []),
                "actual_path": cell.get("path"),
                "execution_path_hash": cell.get("execution_path_hash"),
                "final_bits": point["metrics"]["observations"]["final_bits"],
                "recovery": "ELIGIBLE_INDEPENDENT_RECOVERY"
                if point["formal_complete"]
                else "NOT_FORMALLY_COMPLETE",
                "scope": "THIS_CELL_ONLY_NO_GENERAL_DOMAIN_PROMOTION",
            }
        )
    return {
        "fixed_planned_cells": len(cells),
        "views": matrices,
        "policy": "SOURCE_PORT_BENCH_PIPELINE_CLAIMS_REMAIN_SEPARATE; UNKNOWN_IS_NOT_PASS",
    }


def augment_analysis(analysis: dict, plan: dict, trials: list[dict], corpus_doc: dict) -> dict:
    """Return extensions without mutating the base analysis, plan or raw trials."""
    corpus = CorpusSpec.from_document(corpus_doc)
    cells = {row["cell_id"]: row for row in plan["cells"]}
    observed = {row["cell_id"]: row for row in analysis["matrix"]}
    if (
        len(cells) != len(plan["cells"])
        or len(observed) != len(analysis["matrix"])
        or set(cells) != set(observed)
    ):
        raise ValueError("analysis extensions require the complete fixed planned matrix")
    trial_index = {trial["trial_id"]: trial for trial in trials}
    if len(trial_index) != len(trials) or any(trial["cell_id"] not in cells for trial in trials):
        raise ValueError("duplicate or unplanned raw trial in analysis extensions")
    digest = hashlib.sha256(
        b"".join(canonical_json_bytes(trial) + b"\n" for trial in trials)
    ).hexdigest()
    if analysis.get("audited_trials_sha256", digest) != digest:
        raise ValueError("analysis extensions raw observations differ from the audited analysis")
    points, audit_issues = [], []
    for key, cell in cells.items():
        row = observed[key]
        for field in ("dataset_id", "member_id", "config_label"):
            if row.get(field) != cell.get(field):
                raise ValueError("analysis matrix execution identity differs from frozen plan")
        selected = []
        identifiers = row.get("trial_ids", [])
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate selected TrialID in analysis matrix")
        for identifier in identifiers:
            trial = trial_index.get(identifier)
            issues = (
                ["SELECTED_TRIAL_MISSING"] if trial is None else trial_issues(trial, cell, plan)
            )
            if issues:
                audit_issues.append({"cell_id": key, "trial_id": identifier, "issues": issues})
            else:
                selected.append(trial["record"])
        planned = plan["planned_repetitions_per_cell"]
        complete = (
            row.get("formal_complete") is True
            and len(selected) == planned
            and cell["expected_outcome"] == "PASS"
        )
        mode = cell.get("loss_mode", "UNDECLARED")
        point = {
            "cell_id": key,
            "dataset_id": cell["dataset_id"],
            "member_id": cell["member_id"],
            "method_id": cell.get("method_id"),
            "method_equivalence_class": cell.get("method_equivalence_class", cell.get("method_id")),
            "config_label": cell["config_label"],
            "config_id": cell.get("config_id"),
            "parameters": cell.get("parameters", {}),
            "framework_parameters": cell.get("framework_parameters", {}),
            "loss_mode": mode,
            "guarantee": cell.get("guarantee", {}),
            "public_projection_key": cell["public_projection_key"],
            "role": cell["role"],
            "expected_outcome": cell["expected_outcome"],
            "canonical_raw_bits": cell["canonical_raw_bits"],
            "eligible_process_count": len(selected),
            "planned_process_count": planned,
            "formal_complete": complete,
            "trial_ids": identifiers,
            "run_ids": [record["run_id"] for record in selected],
            "metrics": _metrics(cell, selected),
            "quality": _quality(selected, mode),
        }
        point["quality_curve_eligible"] = complete and point["quality"]["status"] == "VALID"
        point["declared_guarantee_verified_in_cell"] = (
            complete
            and mode == "ERROR_BOUNDED_LOSSY"
            and point["guarantee"].get("kind") == "PROVEN_BOUND"
            and point["guarantee"].get("original_domain_total") is True
        )
        fidelity = plan.get("contract", {}).get("fidelity", plan.get("fidelity", {}))
        point["fixed_error_ranking_eligible"] = (
            point["declared_guarantee_verified_in_cell"] and fidelity.get("kind") == "FIXED_ERROR"
        )
        points.append(point)
    document = {
        "schema_version": "tscb.comparison-analysis-extensions.v1",
        "analysis_id": analysis.get("analysis_id"),
        "comparison_id": plan.get("comparison_id"),
        "audited_trials_sha256": digest,
        "corpus_id": corpus.id,
        "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "quality_curve": {
            "status": "DESCRIPTIVE_PER_CONFIGURATION_POINTS",
            "points": points,
            "lossless_policy": "DISCLOSED_EXACT_REFERENCE_ONLY",
            "guarantee_policy": "EMPIRICAL_QUALITY_NEVER_PROMOTES_UNBOUNDED_OR_RATE_TO_FIXED_ERROR",
            "quality_policy": (
                "NONFINITE_OR_NA_QUALITY_EXCLUDED_FROM_QUALITY_FRONTIER; METRICS_REMAIN_NULL"
            ),
        },
        "pareto": _pareto(points),
        "source_balanced": _source_balanced(points, corpus),
        "coverage_matrices": _coverage(points, cells, trials, corpus_doc),
        "audit_issues": audit_issues,
        "conclusion_scope": "FROZEN_CORPUS_AND_HOST_ONLY_NO_GLOBAL_RANKING",
    }
    document["extension_id"] = stable_id("comparison-analysis-extensions", document, version="v3")
    return document
