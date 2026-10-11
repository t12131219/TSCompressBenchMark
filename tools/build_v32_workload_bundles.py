#!/usr/bin/env python3
"""Derive five registered stream codecs and two related query variants, without adding codecs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402
from tscompbench.comparison import (  # noqa: E402
    ComparisonContract,
    CorpusSpec,
    ExpectedOutcomeMatrix,
    GroupSpec,
    MethodConfigMap,
    compile_group_plan,
    method_id,
    registered_source_closure_digest,
)
from tscompbench.comparison.workload_runner import WorkloadProtocol  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402
from tscompbench.measurement.v32_protocol import MeasurementProtocol  # noqa: E402
from tscompbench.planning.sweep import expand_sweep  # noqa: E402

STREAM_KEYS = ("deflate-zlib", "lz4-frame", "zstd-frame", "brotli-stream", "xz-stream")
QUERY_KEYS = ("neats-lossless-i64", "leats-lossless-i64")


def derive(
    document: dict,
    kind: str,
    *,
    block_rows: int = 65536,
    revision: str = "20261010-v32-workload",
) -> dict:
    if kind not in {"STREAM", "QUERY"}:
        raise ValueError("unsupported workload kind")
    bundle = json.loads(json.dumps(document))
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    keys = STREAM_KEYS if kind == "STREAM" else QUERY_KEYS
    members, configs, equivalence = [], [], []
    for key in keys:
        manifest = registry.get(key)
        d = manifest.document
        if not d["features"]["streaming" if kind == "STREAM" else "query"]:
            raise ValueError("registered native workload capability is missing: " + key)
        method = {
            "name": d["identity"]["display_name"],
            "mechanism": d["identity"]["family"],
            "variant": key,
            "semantic_version": "1",
            "definition_sha256": hashlib.sha256(
                canonical_json_bytes(
                    {k: d[k] for k in ("classification", "semantics", "input", "lifecycle")}
                )
            ).hexdigest(),
        }
        members.append(
            {
                "member_id": key,
                "codec_key": key,
                "role": "CORE",
                "method": method,
                "implementation": {
                    "method_id": method_id(method),
                    "source_artifact_id": manifest.source_artifact_id,
                    "source_closure_sha256": registered_source_closure_digest(registry, key),
                    "implementation_variant": "REGISTERED_SOURCE_CPU",
                },
                "allowed_paths": [
                    "DIRECT",
                    "EXACT_WIDEN",
                    "BYTE_SERIALIZATION",
                    "COLUMN_INDEPENDENT",
                    "JOINT",
                ],
                "shared_code_tags": ["SOURCE_ARTIFACT:" + manifest.source_artifact_id],
            }
        )
        parameters = {
            k: v["default"] for k, v in d["parameters"]["properties"].items() if "default" in v
        }
        if kind == "STREAM":
            parameters["block_size"] = block_rows
        resolved = expand_sweep(
            manifest,
            {k: [v] for k, v in parameters.items()},
            framework_parameters={"benchmark_seed": 20261010},
        )[0]
        if resolved.status.value != "PLANNED":
            raise ValueError("invalid native workload parameters: " + key)
        configs.append(
            {
                "member_id": key,
                "configs": [
                    {
                        "config_key": "frozen-native-workload",
                        "parameters": resolved.parameters,
                        "framework_parameters": resolved.framework_parameters,
                        "loss_mode": "LOSSLESS",
                        "guarantee": {
                            "kind": "LOSSLESS",
                            "metric": None,
                            "threshold": None,
                            "unit": "BITWISE",
                            "original_domain_total": True,
                        },
                    }
                ],
            }
        )
        if kind == "STREAM":
            equivalence.append(
                {
                    "class_id": key,
                    "members": [key],
                    "basis": "Distinct registered compression mechanism.",
                    "evidence": d["identity"]["citations"],
                }
            )
    if kind == "QUERY":
        equivalence = [
            {
                "class_id": "neats-related-query-implementations",
                "members": list(keys),
                "basis": (
                    "Conservative implementation-variant study of related NeaTS/LeaTS source; "
                    "no independent-method winner claim."
                ),
                "evidence": ["MANIFEST:registry/codecs/" + k + ".json" for k in keys],
            }
        ]
    c = bundle["contract"]
    c.update(
        name="G-STREAM-LL" if kind == "STREAM" else "G-QUERY-LL-VARIANTS",
        revision=revision,
        research_question=(
            "Known-length fixed-row native stream sessions through finalized full output and "
            "fresh recovery, including transform/container/context cost."
            if kind == "STREAM"
            else "Frozen point/range queries with owned exact original-domain output; independent "
            "worker sessions on two real sources; related implementation variants only."
        ),
    )
    c["estimand"]["outcome"] = (
        "FINAL_BITS_AND_NATIVE_STREAM_PIPELINE_NS"
        if kind == "STREAM"
        else "FINAL_BITS_AND_OWNED_QUERY_LATENCY_NS"
    )
    contract = ComparisonContract.from_document(c)
    corpus = CorpusSpec.from_document(bundle["corpus"])
    config_map = MethodConfigMap.from_document(
        {**bundle["config_map"], "contract_id": contract.id, "members": configs}
    )
    entries = []
    templates = {r["dataset_id"]: r for r in bundle["expected_matrix"]["entries"]}
    for dataset, template in templates.items():
        for key in keys:
            expected = json.loads(json.dumps(template["expected"]))
            expected["evidence"] = [
                e for e in expected["evidence"] if not e.startswith("MANIFEST:")
            ]
            expected["evidence"].append("MANIFEST:registry/codecs/" + key + ".json")
            entries.append(
                {
                    "dataset_id": dataset,
                    "member_id": key,
                    "config_key": "frozen-native-workload",
                    "expected": expected,
                }
            )
    matrix = ExpectedOutcomeMatrix.from_document(
        {
            **bundle["expected_matrix"],
            "contract_id": contract.id,
            "corpus_id": corpus.id,
            "config_map_id": config_map.id,
            "entries": entries,
        }
    )
    group = GroupSpec.from_document(
        {
            **bundle["group"],
            "name": c["name"],
            "revision": c["revision"],
            "contract_id": contract.id,
            "corpus_id": corpus.id,
            "config_map_id": config_map.id,
            "expected_matrix_id": matrix.id,
            "members": members,
            "method_equivalence": equivalence,
            "scope": "CORE_COMPARISON" if kind == "STREAM" else "RESEARCH",
            "minimum_distinct_methods": 2 if kind == "STREAM" else 1,
        }
    )
    compile_group_plan(
        group,
        contract,
        corpus,
        config_map,
        matrix,
        codec_registry=registry,
        active_codec_keys=json.loads((ROOT / "registry/algorithm_scope.json").read_text())[
            "registered_codecs"
        ],
    )
    MeasurementProtocol.from_document(bundle["protocol"])
    bundle.update(
        contract=contract.to_document(),
        corpus=corpus.to_document(),
        group=group.to_document(),
        config_map=config_map.to_document(),
        expected_matrix=matrix.to_document(),
    )
    return bundle


def _write(path, value):
    if path.exists():
        if json.loads(path.read_text()) != value:
            raise ValueError("refusing to overwrite frozen workload configuration: " + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=ROOT / "configs/comparisons")
    p.add_argument(
        "--byte-base",
        type=Path,
        default=ROOT / "configs/comparisons/g-byte-ll-v32-20261010-v3.json",
    )
    p.add_argument(
        "--int-base",
        type=Path,
        default=ROOT / "configs/comparisons/g-int-ll-i16-v32-20261011-port-v2.json",
    )
    p.add_argument("--revision", default="v2", help="New frozen workload filename suffix")
    args = p.parse_args()
    result = []
    for kind, base in (
        ("STREAM", args.byte_base),
        ("QUERY", args.int_base),
    ):
        if not args.revision or any(
            c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for c in args.revision
        ):
            raise ValueError("revision must be a nonempty filename-safe suffix")
        bundle = derive(
            json.loads(base.read_text()), kind, revision="20261010-v32-workload-" + args.revision
        )
        protocol = WorkloadProtocol(kind, outer_sessions=8, pilot_pairs=5)
        stem = (
            ("g-stream-ll-v32-20261010" if kind == "STREAM" else "g-query-ll-variants-v32-20261010")
            + "-"
            + args.revision
        )
        bundle_path = args.output_dir / (stem + ".json")
        protocol_path = args.output_dir / (stem + "-protocol.json")
        _write(bundle_path, bundle)
        _write(protocol_path, asdict(protocol))
        result.append(
            {
                "kind": kind,
                "bundle": str(bundle_path),
                "protocol": str(protocol_path),
                "group_id": GroupSpec.from_document(bundle["group"]).id,
                "workload_protocol_id": protocol.protocol_id,
            }
        )
        if kind == "QUERY":
            fresh = WorkloadProtocol(
                kind, outer_sessions=8, pilot_pairs=5, query_cache_policy="FRESH_SESSION_PER_QUERY"
            )
            fresh_path = args.output_dir / (stem + "-fresh-protocol.json")
            _write(fresh_path, asdict(fresh))
            result.append(
                {
                    "kind": "QUERY_FRESH_SESSION",
                    "bundle": str(bundle_path),
                    "protocol": str(fresh_path),
                    "group_id": GroupSpec.from_document(bundle["group"]).id,
                    "workload_protocol_id": fresh.protocol_id,
                }
            )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
