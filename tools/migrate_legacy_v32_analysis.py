#!/usr/bin/env python3
"""Create a new descriptive analysis of legacy raw without changing its evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from collections import defaultdict
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.ids import canonical_json_bytes, stable_id  # noqa: E402


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summary(values: list[int]) -> dict[str, Any] | None:
    if not values:
        return None
    with localcontext() as context:
        context.prec = 80
        mean = Decimal(sum(values)) / len(values)
    return {"n": len(values), "mean": format(mean, "f"), "min": min(values), "max": max(values)}


def migrate(run_path: Path, output_path: Path, *, project_root: Path = ROOT) -> dict[str, Any]:
    """Keep legacy qualifications historical; never infer missing experimental design."""
    run_path, output_path = run_path.resolve(), output_path.resolve()
    if output_path.is_relative_to(run_path):
        raise ValueError("derived analysis must be written outside the immutable legacy Run")
    if output_path.exists():
        raise FileExistsError("use a new output path for each immutable migration")
    components = run_path / "run_components.jsonl"
    if not components.is_file():
        raise ValueError("legacy run_components.jsonl is required")
    inputs = [p for p in sorted(run_path.rglob("*")) if p.is_file() and not p.is_symlink()]
    hashes = {str(p.relative_to(run_path)): _hash(p) for p in inputs}
    raw = components.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("interrupted legacy JSONL append cannot be migrated")
    records = [json.loads(line) for line in raw.splitlines()]
    identifiers = [row.get("run_id") for row in records]
    if any(not isinstance(identifier, str) or not identifier for identifier in identifiers):
        raise ValueError("legacy records require RunIDs")
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("duplicate legacy RunID")
    groups = defaultdict(list)
    excluded = []
    for row in records:
        if row.get("schema_version") != "tscb.run-record.v2":
            raise ValueError("only explicitly versioned legacy v2 records are supported")
        reasons = []
        if row.get("status") != "PASS" or row.get("record_kind") != "FORMAL_REPETITION":
            reasons.append("NOT_A_SUCCESSFUL_LEGACY_FORMAL_REPETITION")
        if row.get("eligibility") is not True:
            reasons.append("LEGACY_ELIGIBILITY_NOT_PASS")
        if (row.get("correctness") or {}).get("status") != "PASS":
            reasons.append("LEGACY_CORRECTNESS_NOT_PASS")
        ledger = row.get("accounting") or {}
        required_bits = ("final_bits", "serialized_bits", "external_side_information_bits")
        if any(type(ledger.get(k)) is not int or ledger[k] < 0 for k in required_bits):
            reasons.append("LEGACY_COST_EVIDENCE_MISSING")
        elif (
            ledger["final_bits"]
            != ledger["serialized_bits"] + ledger["external_side_information_bits"]
        ):
            reasons.append("LEGACY_COST_NOT_CLOSED")
        timing = row.get("timing") or {}
        for key in ("selected_encode_wall_ns", "selected_decode_wall_ns", "inner_iterations"):
            if type(timing.get(key)) is not int or timing[key] <= 0:
                reasons.append("LEGACY_TIMING_INVALID")
        key = tuple(
            row.get(k)
            for k in (
                "algorithm_id",
                "config_id",
                "dataset_id",
                "track",
                "execution_path_hash",
                "execution_comparability_key",
                "resource_profile_key",
            )
        )
        if any(not isinstance(item, str) or not item for item in key):
            reasons.append("LEGACY_EXACT_EXECUTION_IDENTITY_MISSING")
        if reasons:
            excluded.append({"run_id": row["run_id"], "reasons": sorted(set(reasons))})
        else:
            groups[key].append(row)
    summaries = []
    for key, rows in sorted(groups.items()):
        summaries.append(
            {
                "legacy_exact_execution_identity": list(key),
                "run_ids": [r["run_id"] for r in rows],
                "final_bits": _summary([r["accounting"]["final_bits"] for r in rows]),
                "direction_wall_ns": {
                    direction: _summary(
                        [r["timing"][f"selected_{direction}_wall_ns"] for r in rows]
                    )
                    for direction in ("encode", "decode")
                },
                "inner_iterations": [r["timing"]["inner_iterations"] for r in rows],
                "native_auxiliary_status": "HISTORICAL_OBSERVATION_ONLY_NOT_NEW_NATIVE_FORMAL",
            }
        )
    code_paths = [
        Path(__file__),
        *sorted((project_root / "src/tscompbench/comparison").glob("*.py")),
        *sorted((project_root / "src/tscompbench/ids").glob("*.py")),
    ]
    code = [{"path": str(p.relative_to(project_root)), "sha256": _hash(p)} for p in code_paths]
    dependencies = {
        "python": platform.python_version(),
        "packages": {
            d.metadata["Name"]: d.version
            for d in importlib.metadata.distributions()
            if d.metadata.get("Name")
        },
    }
    document = {
        "schema_version": "tscb.legacy-analysis-migration.v1",
        "derived_from": {"run_path": str(run_path), "input_files": hashes},
        "projection_version": "LEGACY_EXACT_EXECUTION_IDENTITY_V1",
        "code_manifest": code,
        "code_sha256": hashlib.sha256(canonical_json_bytes(code)).hexdigest(),
        "dependency_manifest": dependencies,
        "dependency_sha256": hashlib.sha256(canonical_json_bytes(dependencies)).hexdigest(),
        "fixed_records": len(records),
        "described_records": sum(len(rows) for rows in groups.values()),
        "excluded_records": excluded,
        "summaries": summaries,
        "v32_formal_eligible": False,
        "new_pairing_or_warmup_observations_generated": False,
        "inference": {
            "status": "NOT_PERFORMED",
            "reason": "LEGACY_DESIGN_NOT_RECONSTRUCTED_FROM_RESULT_ROWS",
        },
        "promotion_refusals": [
            "NO_RETROACTIVE_RANDOM_SCHEDULE_OR_PAIR_IDS",
            "NO_RETROACTIVE_WORKER_LOCAL_WARMUP",
            "NO_RETROACTIVE_RESOURCE_LEASE",
            "NO_NATIVE_AUXILIARY_TO_NATIVE_FORMAL_PROMOTION",
            "NO_NEW_CROSS_METHOD_PUBLIC_PROJECTION_FROM_DELETED_LEGACY_KEYS",
        ],
    }
    document["analysis_id"] = stable_id("legacy-derived-analysis", document, version="v3")
    after = {str(p.relative_to(run_path)): _hash(p) for p in inputs}
    if hashes != after:
        raise ValueError("legacy inputs changed during migration")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as handle:
        handle.write(canonical_json_bytes(document) + b"\n")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_path", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = migrate(args.run_path, args.output)
    print(
        json.dumps(
            {
                "analysis_id": result["analysis_id"],
                "fixed_records": result["fixed_records"],
                "described_records": result["described_records"],
                "v32_formal_eligible": False,
            }
        )
    )


if __name__ == "__main__":
    main()
