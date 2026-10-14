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
        raw_bytes = case.get("raw_bytes")
        encode = _distribution([row["encode_ns"] for row in ok if row.get("encode_ns") is not None])
        decode = _distribution([row["decode_ns"] for row in ok if row.get("decode_ns") is not None])
        stored = _distribution([row["stored_bytes"] for row in ok if row.get("stored_bytes") is not None])
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
                   "boundary": case.get("boundary", "object_memory"),
                   "lifecycle": case.get("lifecycle", "independent_object"),
                   "cache_policy": case.get("cache_policy", "natural"),
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
    directory = root / "report"
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "summary.json", report)
    columns = ["case_id", "codec", "profile_id", "case_status", "raw_bytes", "planned_trials",
               "ok_primary_trials", "complete_case", "stored_fraction", "compression_ratio", "encode_MiB_s", "decode_MiB_s"]
    with (directory / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for case in cases:
            writer.writerow({name: case.get(name) for name in columns})
    lines = [f"# {manifest.get('name', manifest['run_id'])}", "",
             f"Requested cases: {len(cases)}; executable cases: {report['executable_cases']}; planned trials: {len(schedule)}.", "",
             "Time and size summaries use successful primary attempts; failures and retries remain in the recorded coverage. A partial case reports performance conditional on success.", "",
             "| Case | Status | OK / planned | Stored fraction | Encode MiB/s | Decode MiB/s |", "|---|---|---:|---:|---:|---:|"]
    def display(value: Any) -> str:
        return "—" if value is None else f"{value:.6g}" if isinstance(value, float) else str(value)
    for case in cases:
        lines.append("| " + " | ".join([case["case_id"], display(case["case_status"]),
                     f"{case['ok_primary_trials']} / {case['planned_trials']}", display(case["stored_fraction"]),
                     display(case["encode_MiB_s"]), display(case["decode_MiB_s"])]) + " |")
    (directory / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


report = generate
