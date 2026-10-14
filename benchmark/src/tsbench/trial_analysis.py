"""Pure exact-schedule validation for analyses of append-only observations.

This module never executes a codec or changes a measurement record. A retry is
an additional attempt at the same scheduled trial, not a new denominator.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .records import file_hash


def analysis_dependency_hash() -> str:
    return file_hash(__file__)


def _index(row: dict[str, Any], name: str) -> int:
    value = row.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"trial {name} must be a nonnegative integer: {value!r}")
    return value


def trial_key(row: dict[str, Any]) -> tuple[str, int, int]:
    case_id = row.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("trial case_id must be a nonempty string")
    return case_id, _index(row, "session"), _index(row, "round")


def primary_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, int, int], dict[str, Any]]:
    trials = defaultdict(list)
    seen = set()
    for line, row in enumerate(rows, 1):
        if row.get("phase") != "measurement" or row.get("event") != "terminal":
            continue
        key = trial_key(row)
        attempt = _index({"attempt": row.get("attempt", 0)}, "attempt")
        identity = (*key, attempt)
        if identity in seen:
            raise ValueError(f"duplicate terminal attempt: {identity}")
        seen.add(identity)
        if not isinstance(row.get("status"), str) or not row["status"]:
            raise ValueError(f"terminal attempt has no valid status: {identity}")
        trials[key].append((attempt, line, row))
    selected = {}
    for key, attempts in trials.items():
        executed = [item for item in attempts if item[2]["status"] != "not_run"]
        _, line, row = min(executed or attempts, key=lambda item: (item[0], item[1]))
        selected[key] = {**row, "observation_line": line}
    return selected


def scheduled_rows(manifest: dict[str, Any], rows: list[dict[str, Any]]):
    """Reject unscheduled/duplicate evidence before computing completeness."""
    cases = {case["case_id"] for case in manifest["cases"]}
    if len(cases) != len(manifest["cases"]):
        raise ValueError("duplicate case id in manifest")
    planned = defaultdict(set)
    for trial in manifest["schedule"]:
        key = trial_key(trial)
        if key[0] not in cases or key in planned[key[0]]:
            raise ValueError(f"unknown case or duplicate scheduled trial: {key}")
        planned[key[0]].add(key)
    selected = primary_rows(rows)
    unexpected = set(selected) - set().union(set(), *planned.values())
    if unexpected:
        raise ValueError(f"unscheduled measurement terminal: {sorted(unexpected)}")
    for row in rows:
        if row.get("phase") != "measurement" or row.get("event") != "terminal":
            continue
        if row.get("run_id") is not None and row["run_id"] != manifest["run_id"]:
            raise ValueError("measurement terminal belongs to a different run")
    return selected, planned


def trial_coverage(case_id: str, selected: dict, planned: dict) -> dict[str, Any]:
    expected = planned.get(case_id, set())
    observed = [selected[key] for key in sorted(expected) if key in selected]
    missing = [{"session": key[1], "round": key[2]} for key in sorted(expected) if key not in selected]
    ok = sum(row["status"] == "ok" for row in observed)
    return {"requested_trials": len(expected), "observed_trials": len(observed),
            "missing_trials": len(missing), "missing_trial_keys": missing, "ok_trials": ok,
            "complete": bool(expected) and ok == len(expected),
            "trial_status_counts": dict(Counter(row["status"] for row in observed))}


def case_coverage(manifest: dict, case: dict, selected: dict, planned: dict) -> dict[str, Any]:
    result = trial_coverage(case["case_id"], selected, planned)
    result["execution_source_valid"] = manifest.get("execution_source_unchanged") is not False
    result["complete"] = case.get("status") == "ready" and result["complete"] and result["execution_source_valid"]
    result["invalidity_reason"] = None if result["execution_source_valid"] else "execution_source_changed_during_run"
    return result
