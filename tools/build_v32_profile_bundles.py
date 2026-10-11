#!/usr/bin/env python3
"""Freeze cold-object and external API comparisons from an existing byte corpus."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.comparison import (  # noqa: E402
    ComparisonContract,
    CorpusSpec,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
)
from tscompbench.measurement.v32_protocol import MeasurementProtocol  # noqa: E402


def derive(document: dict, profile: str) -> dict:
    bundle = json.loads(json.dumps(document))
    protocol = MeasurementProtocol.from_document(bundle["protocol"])
    if profile == "cold":
        protocol = replace(
            protocol,
            profile="COLD_PROCESS",
            warmup_min_count=0,
            warmup_min_ns=0,
            max_inner_iterations=1,
            cache_policy="OS_CACHE_UNCONTROLLED",
            cold_start_boundary="SPAWN_THROUGH_OUTPUT_MATERIALIZATION",
            encode_min_ns=1_000_000,
            decode_min_ns=1_000_000,
        )
    elif profile == "api":
        protocol = replace(protocol, profile="STEADY_PROCESS", timing_scope="CORE")
    else:
        raise ValueError("unknown derived profile")
    c = bundle["contract"]
    c["name"] += "-COLD" if profile == "cold" else "-API"
    c["revision"] += "-" + profile
    c["measurement_protocol_id"] = protocol.protocol_id
    c["research_question"] = (
        "Fresh independent encode/decode processes through parent owned materialization "
        "under fixed CPU budgets on the same original corpus."
        if profile == "cold"
        else "Registered byte codecs on identical actual input arrays: external public API "
        "encode+finalize and decode calls, with serialized API output cost. "
        "Complete recovery side information remains disclosed separately."
    )
    c["estimand"]["outcome"] = (
        "FINAL_BITS_AND_SPAWN_THROUGH_OWNED_OUTPUT_WALL_NS"
        if profile == "cold"
        else "API_SERIALIZED_BITS_AND_EXTERNAL_CORE_API_WALL_NS"
    )
    if profile == "api":
        c.update(
            mode="COMMON_NATIVE_API",
            cost_boundary="NATIVE_COMPONENT",
            timing_boundary="CORE_API",
            workload="API_COMPONENT",
        )
        if any("SOURCE_REJECT_RAW" in m["allowed_paths"] for m in bundle["group"]["members"]):
            raise ValueError("composite recovery recipes are not native API components")
    contract = ComparisonContract.from_document(c)
    corpus = CorpusSpec.from_document(bundle["corpus"])
    bundle["config_map"]["contract_id"] = contract.id
    config_map = MethodConfigMap.from_document(bundle["config_map"])
    expected = bundle["expected_matrix"]
    expected.update(contract_id=contract.id, corpus_id=corpus.id, config_map_id=config_map.id)
    matrix = ExpectedOutcomeMatrix.from_document(expected)
    g = bundle["group"]
    g.update(
        name=c["name"],
        revision=c["revision"],
        contract_id=contract.id,
        corpus_id=corpus.id,
        config_map_id=config_map.id,
        expected_matrix_id=matrix.id,
    )
    group = GroupSpec.from_document(g)
    bundle.update(
        contract=contract.to_document(),
        corpus=corpus.to_document(),
        config_map=config_map.to_document(),
        expected_matrix=matrix.to_document(),
        group=group.to_document(),
        protocol=protocol.to_document(),
    )
    return bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_bundle", type=Path)
    parser.add_argument("--profile", choices=("cold", "api"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = derive(json.loads(args.base_bundle.read_text()), args.profile)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        if json.loads(args.output.read_text()) != result:
            raise ValueError("refusing to overwrite an immutable profile bundle")
    else:
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "group_id": GroupSpec.from_document(result["group"]).id,
                "output": str(args.output),
                "profile": args.profile,
            }
        )
    )


if __name__ == "__main__":
    main()
