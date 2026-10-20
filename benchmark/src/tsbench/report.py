"""Recomputable descriptive reports that retain every planned denominator."""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .records import file_hash, read_jsonl, stable_hash, write_json
from .trial_analysis import analysis_dependency_hash, case_coverage, scheduled_rows


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[min(lower + 1, len(ordered) - 1)] * weight


def _distribution(values: list[int | float]) -> dict[str, Any]:
    finite = [float(value) for value in values if value is not None and math.isfinite(value)]
    if not finite:
        return {"n": 0, "median": None, "q1": None, "q3": None, "iqr": None,
                "mean": None, "std": None, "min": None, "max": None}
    q1, q3 = _percentile(finite, 0.25), _percentile(finite, 0.75)
    return {"n": len(finite), "median": statistics.median(finite), "q1": q1, "q3": q3,
            "iqr": q3 - q1, "mean": statistics.mean(finite),
            "std": statistics.stdev(finite) if len(finite) > 1 else None,
            "min": min(finite), "max": max(finite)}


def _scope(case: dict[str, Any]) -> tuple[str, str, str]:
    # Missing boundary belongs to the historical object protocol, regardless
    # of the current config parser's defaults.
    boundary = case.get("boundary", "object_memory")
    lifecycle = case.get("lifecycle", "prepared" if boundary in {"native_core", "native_api"} else "independent_object")
    return boundary, lifecycle, case.get("cache_policy", "natural")


def _unique(values: list[Any]) -> list[Any]:
    seen = {}
    for value in values:
        if value is not None:
            seen.setdefault(stable_hash(value), value)
    return list(seen.values())


def _measurement_trace(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Preserve actual timer/batch evidence without inventing measurements for
    # legacy rows. An absent field remains absent, not a newly inferred clock.
    fields = {"boundary", "measurement_scope", "lifecycle", "loops", "clock", "timer",
              "clock_resolution_ns", "native_timer", "native_clock", "native_timing",
              "native_encode_total_ns", "native_decode_total_ns", "encode_total_ns", "decode_total_ns",
              "encode_batch_ns", "decode_batch_ns", "sampling_unit", "driver_build_id", "driver_binary_hash",
              "native_output_bytes", "codec_complete_bytes", "codec_complete_bytes_null_reason",
              "output_accounting_status", "output_accounting", "validation_coverage",
              "verified_outputs", "encoded_outputs", "decoded_outputs", "native_batch",
              "native_driver", "driver", "setup_ns", "close_ns", "prepare_ns"}
    trace = []
    for row in rows:
        evidence = {key: value for key, value in row.items()
                    if key in fields or key.startswith(("native_", "batch_", "clock_", "validation_"))}
        trace.append({"session": row["session"], "round": row["round"],
                      "attempt": row.get("attempt", 0), "status": row["status"],
                      "observation_line": row["observation_line"], **evidence})
    return trace


def generate(run_dir: str | Path) -> dict[str, Any]:
    root = Path(run_dir).resolve()
    manifest = json.loads((root / "manifest.json").read_bytes())
    observations, tail = read_jsonl(root / "observations.jsonl")
    selected, planned = scheduled_rows(manifest, observations)
    terminal = [row for row in observations if row.get("event") == "terminal" and row.get("phase") == "measurement"]
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in terminal:
        by_case[row["case_id"]].append(row)
    schedule = manifest.get("schedule", [])
    cases = []
    total_status = Counter()
    for case in manifest.get("cases", []):
        case_id = case["case_id"]
        rows = by_case[case_id]
        statuses = Counter(row["status"] for row in rows)
        latest = {}
        for row in rows:
            key = (row.get("session"), row.get("round"))
            if key not in latest or row.get("attempt", 0) >= latest[key].get("attempt", 0):
                latest[key] = row
        # An executed failure remains primary even after a successful retry.
        # Missing keys cannot be replaced by extra successful observations.
        expected = planned.get(case_id, set())
        primary = [selected[key] for key in sorted(expected) if key in selected]
        coverage = case_coverage(manifest, case, selected, planned)
        ok = [row for row in primary if row["status"] == "ok"]
        n_planned = coverage["requested_trials"]
        executed = sum(row["status"] != "not_run" for row in primary)
        all_success = coverage["complete"]
        total_status.update(statuses)
        quality_parameters = {}
        for row in primary:
            metadata = row.get("codec_quality_metadata")
            if not metadata or not metadata.get("parts"):
                continue
            key = stable_hash(metadata)
            entry = quality_parameters.setdefault(key, {"metadata_id": key, "metadata": metadata, "trial_trace": []})
            entry["trial_trace"].append({"session": row["session"], "round": row["round"],
                                         "attempt": row.get("attempt", 0), "status": row["status"],
                                         "observation_line": row["observation_line"]})
        boundary, lifecycle, cache_policy = _scope(case)
        native = boundary in {"native_core", "native_api"}
        for row in rows:
            for field, expected_scope in zip(("boundary", "lifecycle", "cache_policy"),
                                              (boundary, lifecycle, cache_policy)):
                if row.get(field) is not None and row[field] != expected_scope:
                    raise ValueError(f"measurement {field} differs from case scope: {case_id}")
        raw_bytes = case.get("raw_bytes")
        encode = _distribution([row["encode_ns"] for row in ok if row.get("encode_ns") is not None])
        decode = _distribution([row["decode_ns"] for row in ok if row.get("decode_ns") is not None])
        size_field = "codec_complete_bytes" if native else "stored_bytes"
        known_sizes = [row[size_field] for row in ok if row.get(size_field) is not None]
        size_complete = bool(ok) and len(known_sizes) == len(ok)
        # A median over only known native sizes must not hide missing output
        # accounting in other successful trials.
        stored = _distribution(known_sizes if not native or size_complete else [])
        size_reasons = _unique([row.get("codec_complete_bytes_null_reason") for row in ok
                                if row.get("codec_complete_bytes") is None]) if native else []
        if native and not size_complete and not size_reasons:
            size_reasons = ["codec complete output size not recorded" if ok else "no successful primary trials"]
        size_reason = "; ".join(str(reason) for reason in size_reasons) or None
        def rate(duration: Any) -> float | None:
            return raw_bytes * 1e9 / duration / 2**20 if raw_bytes and duration and duration > 0 else None
        def fraction(size: Any) -> float | None:
            return size / raw_bytes if size is not None and raw_bytes and raw_bytes > 0 else None
        summary = {"case_id": case_id, "dataset_id": case.get("dataset_id"), "method_id": case.get("method_id"),
                   "codec": case.get("codec"), "profile_id": case.get("profile_id"),
                   "case_status": case.get("status"), "reason": case.get("reason"),
                   "raw_bytes": raw_bytes, "planned_trials": n_planned,
                   "completed_primary_trials": len(primary), "executed_primary_trials": executed,
                   "missing_trials": coverage["missing_trials"], "missing_trial_keys": coverage["missing_trial_keys"],
                   "primary_trial_status_counts": coverage["trial_status_counts"],
                   "execution_source_valid": coverage["execution_source_valid"], "performance_invalidity_reason": coverage["invalidity_reason"],
                   "primary_trace": [{"session": row["session"], "round": row["round"],
                                      "attempt": row.get("attempt", 0), "observation_line": row["observation_line"],
                                      "status": row["status"]} for row in primary],
                   "ok_primary_trials": len(ok), "attempts": len(rows), "status_counts": dict(statuses),
                   "latest_attempt_status_counts": dict(Counter(row["status"] for row in latest.values())),
                   "complete_case": all_success, "performance_scope": "diagnostic only; execution source changed" if not coverage["execution_source_valid"] else "all planned trials" if all_success else "conditional on successful primary trials",
                   "encode_ns": encode, "decode_ns": decode, "stored_bytes": stored,
                   "stored_fraction": fraction(stored["median"]),
                   "compression_ratio": raw_bytes / stored["median"] if raw_bytes and stored["median"] and stored["median"] > 0 else None,
                   "encode_MiB_s": rate(encode["median"]), "decode_MiB_s": rate(decode["median"]),
                   "boundary": boundary, "lifecycle": lifecycle, "cache_policy": cache_policy,
                   "payload_bytes": _distribution([row["payload_bytes"] for row in ok if row.get("payload_bytes") is not None]),
                   "header_bytes": _distribution([row["header_bytes"] for row in ok if row.get("header_bytes") is not None]),
                   "bits_per_value": _distribution([row["bits_per_value"] for row in ok if row.get("bits_per_value") is not None]),
                   "bits_per_timestamp": _distribution([row["bits_per_timestamp"] for row in ok if row.get("bits_per_timestamp") is not None]),
                   "quality": {name: _distribution([row.get("verification", {}).get(name) for row in ok
                                                     if row.get("verification", {}).get(name) is not None])
                               for name in ("max_abs", "rmse", "nrmse", "psnr_db")},
                   "quality_all_primary_attempts": {name: _distribution([row.get("verification", {}).get(name) for row in primary
                                                                          if row.get("verification", {}).get(name) is not None])
                                                    for name in ("max_abs", "rmse", "nrmse", "psnr_db")},
                   "quality_target": {name: manifest.get("resolved_config", {}).get("task", {}).get(name)
                                      for name in ("fidelity", "error_bound", "relative_floor", "special_values", "invalid_values")},
                   "codec_quality_parameters": list(quality_parameters.values()),
                   "codec_quality_parameters_null_reason": None if quality_parameters else "no native quality parameters extracted for this codec" if any(row.get("codec_quality_metadata") is not None for row in primary) else "not_recorded_in_original_measurements; task bound is not native effective tolerance",
                   "effective_absolute_bound": _distribution([row.get("verification", {}).get("effective_absolute_bound") for row in primary
                                                              if row.get("verification", {}).get("effective_absolute_bound") is not None]),
                   "metric_null_reasons": {"stored_fraction": "empty task" if not raw_bytes else None,
                                           "compression_ratio": "empty task" if not raw_bytes else None,
                                           "encode_MiB_s": "empty task or nonpositive time" if not raw_bytes or not encode["median"] else None,
                                           "decode_MiB_s": "empty task or nonpositive time" if not raw_bytes or not decode["median"] else None}}
        summary.update({
            "measurement_scope": "; ".join(str(value) for value in _unique([row.get("measurement_scope") for row in primary])) or boundary,
            "report_role": "primary" if (boundary, lifecycle) == ("native_core", "prepared") else "auxiliary",
            "size_scope": "codec_complete_output" if native else "complete_object_wire",
            "time_scope": "native_driver_per_operation" if native else "completed_object_wall" if boundary == "object_memory" else boundary,
            "codec_complete_bytes": stored if native else _distribution([]),
            "codec_complete_bytes_known_subset": _distribution(known_sizes) if native else _distribution([]),
            "codec_complete_bytes_null_reason": size_reason if native else "not measured in object protocol",
            "codec_size_complete_for_successful_trials": size_complete if native else None,
            "native_output_bytes": _distribution([row.get("native_output_bytes") for row in ok]),
            "encode_batch_ns": _distribution([row.get("encode_batch_ns") for row in ok]),
            "decode_batch_ns": _distribution([row.get("decode_batch_ns") for row in ok]),
            "native_encode_total_ns": _distribution([row.get("encode_batch_ns", row.get("native_encode_total_ns")) for row in ok]),
            "native_decode_total_ns": _distribution([row.get("decode_batch_ns", row.get("native_decode_total_ns")) for row in ok]),
            "sampling_units": _unique([row.get("sampling_unit") for row in primary]),
            "loops": _distribution([row.get("loops") for row in ok]),
            "value_count": _distribution([row.get("value_count") for row in ok]),
            "timestamp_count": _distribution([row.get("timestamp_count") for row in ok]),
            "reported_measurement_scopes": _unique([row.get("measurement_scope") for row in primary]),
            "clock_metadata": _unique([{key: value for key, value in source.items()
                                         if key in {"clock", "timer", "native_timer", "native_clock"} or key.startswith("clock_")}
                                        for row in primary for source in (row, row.get("native_batch", {}))
                                        if isinstance(source, dict) and (any(key in source for key in ("clock", "timer", "native_timer", "native_clock"))
                                        or any(key.startswith("clock_") for key in source))]),
            "measurement_trace": _measurement_trace(primary),
            "primary_reasons": dict(Counter(str(row["reason"]) for row in primary if row.get("reason"))),
        })
        if native:
            for metric, count_field in (("bits_per_value", "value_count"), ("bits_per_timestamp", "timestamp_count")):
                summary[metric] = _distribution([8 * row["codec_complete_bytes"] / row[count_field] for row in ok
                                                  if size_complete and row.get(count_field) and row[count_field] > 0])
            for metric in ("stored_fraction", "compression_ratio"):
                summary["metric_null_reasons"][metric] = "empty task" if not raw_bytes else size_reason
            summary["metric_null_reasons"]["bits_per_value"] = size_reason or ("no values" if not summary["bits_per_value"]["n"] else None)
            summary["metric_null_reasons"]["bits_per_timestamp"] = size_reason or ("no timestamps" if not summary["bits_per_timestamp"]["n"] else None)
        for field in ("codec_complete_bytes", "native_output_bytes", "bits_per_value", "bits_per_timestamp"):
            summary[field + "_median"] = summary[field]["median"]
        cases.append(summary)
    report = {"schema": "tsbench.report/1", "run_id": manifest["run_id"],
              "analysis_code_hash": file_hash(__file__), "trial_analysis_hash": analysis_dependency_hash(),
              "manifest_hash": file_hash(root / "manifest.json"), "observations_hash": file_hash(root / "observations.jsonl"),
              "analysis_id": stable_hash({"schema": "describe/2", "code_hash": file_hash(__file__), "trial_analysis_hash": analysis_dependency_hash(), "retry": "earliest-executed-attempt", "quantiles": "linear", "cases": cases}),
              "requested_cases": len(cases), "executable_cases": sum(case["planned_trials"] > 0 for case in cases),
              "planned_trials": len(schedule), "terminal_measurement_attempts": len(terminal),
              "status_counts": dict(total_status), "interrupted_jsonl_tail": tail,
              "requested_case_status_counts": dict(Counter(case.get("status", "unknown") for case in manifest.get("cases", []))),
              "admission_counts": dict(Counter(case.get("status", "unknown") for case in manifest.get("cases", []))),
              "cases": cases, "retry_policy": "earliest executed attempt; successful retry never replaces executed failure; unexecuted placeholders are skipped when execution exists"}
    groups = []
    grouped = defaultdict(list)
    for case in cases:
        grouped[(case["boundary"], case["lifecycle"], case["cache_policy"])].append(case)
    for (boundary, lifecycle, cache_policy), members in sorted(grouped.items()):
        groups.append({"boundary": boundary, "lifecycle": lifecycle, "cache_policy": cache_policy,
                       "report_role": members[0]["report_role"], "requested_cases": len(members),
                       "executable_cases": sum(member["planned_trials"] > 0 for member in members),
                       "planned_trials": sum(member["planned_trials"] for member in members),
                       "ok_primary_trials": sum(member["ok_primary_trials"] for member in members),
                       "complete_cases": sum(member["complete_case"] for member in members),
                       "case_ids": [member["case_id"] for member in members],
                       "case_status_counts": dict(Counter(member["case_status"] for member in members))})
    report.update({"measurement_groups": groups,
                   "primary_case_ids": [case["case_id"] for case in cases if case["report_role"] == "primary"],
                   "auxiliary_case_ids": [case["case_id"] for case in cases if case["report_role"] != "primary"],
                   "primary_metric_scope": "native_core/prepared; every other boundary or lifecycle is auxiliary; no cross-boundary ranking"})
    directory = root / "report"
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "summary.json", report)
    columns = ["case_id", "codec", "profile_id", "boundary", "lifecycle", "cache_policy", "measurement_scope",
               "report_role", "size_scope", "time_scope", "case_status", "reason", "raw_bytes", "planned_trials",
               "ok_primary_trials", "complete_case", "codec_complete_bytes_median", "native_output_bytes_median",
               "codec_complete_bytes_null_reason", "stored_fraction", "compression_ratio", "bits_per_value_median",
               "bits_per_timestamp_median", "encode_MiB_s", "decode_MiB_s"]
    with (directory / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for case in cases:
            writer.writerow({name: case.get(name) for name in columns})
    lines = [f"# {manifest.get('name', manifest['run_id'])}", "",
             f"Requested cases: {len(cases)}; executable cases: {report['executable_cases']}; planned trials: {len(schedule)}.", "",
             "Time and size summaries use successful primary attempts; failures and retries remain in coverage. Partial cases are conditional on success.", "",
             "The primary table uses native_core/prepared. Native API, first requests, and complete object measurements are auxiliary and are never ranked across boundaries. Historical rows without a boundary retain object_memory semantics.", "",
             "Native size means verified complete codec output, including required headers, parameters, models, indices and finalization. Unknown size stays null; API output is not a substitute. Object size remains complete framework wire."]
    def display(value: Any) -> str:
        text = "—" if value is None else f"{value:.6g}" if isinstance(value, float) else str(value)
        return text.replace("|", "\\|").replace("\n", " ")
    for role, title in (("primary", "Primary: native core with prepared context/buffer"),
                        ("auxiliary", "Auxiliary measurements")):
        lines.extend(["", "## " + title, ""])
        matching = [group for group in groups if group["report_role"] == role]
        if not matching:
            lines.append("No requested cases in this measurement scope.")
        for group in matching:
            size_label = "complete object wire" if group["boundary"] == "object_memory" else "verified complete codec output"
            lines.extend([f"### {group['boundary']} / {group['lifecycle']} / {group['cache_policy']}", "",
                          f"Requested: {group['requested_cases']}; executable: {group['executable_cases']}; complete: {group['complete_cases']}; OK / planned trials: {group['ok_primary_trials']} / {group['planned_trials']}.", "",
                          f"Compression ratio = effective raw bytes / {size_label} bytes (larger is better). Throughput uses effective raw bytes and the named measurement boundary.", "",
                          "| Case | Status | OK / planned | Ratio (raw/compressed) | Bits/value | Stored fraction | Encode MiB/s | Decode MiB/s | Reason / null size |",
                          "|---|---|---:|---:|---:|---:|---:|---:|---|"])
            for case in cases:
                if case["case_id"] not in group["case_ids"]:
                    continue
                reason = case.get("reason") or "; ".join(case["primary_reasons"]) or (case.get("codec_complete_bytes_null_reason") if case["boundary"] in {"native_core", "native_api"} else None)
                lines.append("| " + " | ".join([display(case["case_id"]), display(case["case_status"]),
                             f"{case['ok_primary_trials']} / {case['planned_trials']}", display(case["compression_ratio"]),
                             display(case["bits_per_value_median"]), display(case["stored_fraction"]),
                             display(case["encode_MiB_s"]), display(case["decode_MiB_s"]), display(reason)]) + " |")
    (directory / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


report = generate
