#!/usr/bin/env python3
"""Freeze existing timestamp/f32 methods on explicit original or derived tasks.

No codec is executed and no registration is created. New canonical manifests
use dataset-content.v2; old source, candidate and comparison evidence is intact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from build_v32_comparison_bundles import (  # noqa: E402
    SOURCES,
    BundleBuilder,
    configurations_for,
    from_columns,
    synthetic,
    write_or_verify,
)

from tscompbench.adapters import adapter_artifacts  # noqa: E402
from tscompbench.codecs import descriptor_from_dataset, negotiate  # noqa: E402
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
from tscompbench.contracts import BenchmarkTrack, CapabilityStatus  # noqa: E402
from tscompbench.datasets import load_dataset  # noqa: E402
from tscompbench.datasets.canonical import (  # noqa: E402
    read_canonical,
    semantic_content_sha256,
    write_canonical,
)
from tscompbench.datasets.canonical_source import canonical_source_document  # noqa: E402
from tscompbench.datasets.models import CanonicalDataset, immutable  # noqa: E402
from tscompbench.datasets.prepare import load_preparation_result, prepare_dataset  # noqa: E402
from tscompbench.ids import canonical_json_bytes  # noqa: E402

TIMESTAMP_KEYS = (
    "lz4-frame",
    "zstd-frame",
    "snappy-raw",
    "deflate-zlib",
    "brotli-stream",
    "xz-stream",
    "lzss-raw",
    "lzss-dipperstein-c",
)
F32_KEYS = ("alp", "alp-rd", "chimp", "chimp128", "elf", "elf-plus", "elf-star", "self-star")
PATTERNS = ("regular", "jitter", "duplicate", "out_of_order")


def with_timestamp(
    dataset: CanonicalDataset, timestamp: np.ndarray, metadata: dict
) -> CanonicalDataset:
    logical = json.loads(json.dumps(dataset.logical_descriptor))
    logical["timestamp"] = {**metadata, "present": True, "dtype": "<i8"}
    return replace(
        dataset,
        timestamp=immutable(np.ascontiguousarray(timestamp, dtype="<i8")),
        logical_descriptor=logical,
        physical_descriptors=(
            {
                "view_id": "timestamp-le-i64",
                "layout": "ROW_MAJOR_CONTIG",
                "dtype": "<i8",
                "shape": [timestamp.size],
                "endianness": "little",
            },
            *dataset.physical_descriptors,
        ),
    )


class ExtendedBuilder(BundleBuilder):
    def register(self, key, dataset, spec, *, source=None, split="TEST", proof=None):
        if key in self.entries:
            return self.entries[key]
        path = self.payload_root / "sources" / f"{key}.tscb"
        if path.exists():
            artifact = read_canonical(path, include_buffers=False)
            if artifact.metadata["dataset_content_sha256"] != dataset.content_sha256():
                raise ValueError(f"frozen canonical source changed: {key}")
        else:
            artifact = write_canonical(dataset, path)
        doc = canonical_source_document(
            path,
            ROOT,
            key,
            identity_policy="tscb.dataset-content.v2",
            split={
                "policy": split,
                "learned_eligible": False,
                "reason": "Fixed typed task; synthetic pilot is independent; no model training.",
            },
            license_info=source.manifest.document["license"]
            if source
            else {
                "spdx": "CC0-1.0",
                "status": "RUN_ALLOWED",
            },
        )
        doc["source"].update(
            uri=source.manifest.document["source"]["uri"] if source else "local:synthetic",
            retrieved_at=source.manifest.document["source"]["retrieved_at"]
            if source
            else "LOCAL_GENERATED",
            notes=json.dumps(
                {
                    "generation_spec": spec,
                    "domain_proof": proof,
                    "source_manifest": str(source.manifest.path.relative_to(ROOT))
                    if source
                    else None,
                    "source_sha256": source.manifest.document["file"]["sha256"] if source else None,
                    "source_lineage_authentication": (
                        "LOCAL_MANIFEST_ONLY_NOT_EXTERNALLY_AUTHENTICATED"
                    )
                    if source
                    else "GENERATOR_FULL_SPEC",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
        write_or_verify(self.manifests / f"{key}.json", doc)
        output = self.payload_root / "prepared"
        prepared = (
            load_preparation_result(self.datasets, key, output)
            if (output / key / "preparation-record.json").exists()
            else prepare_dataset(self.datasets, key, output)
        )
        current = read_canonical(prepared.canonical.path, include_buffers=False)
        entry = {
            "key": key,
            "dataset_id": prepared.dataset_id,
            "artifact_sha256": prepared.canonical.sha256,
            "logical_content_id": semantic_content_sha256(
                current.metadata, policy="tscb.dataset-content.v2"
            ),
            "generation_spec": spec,
            "domain_proof": proof,
        }
        self.entries[key] = entry
        return entry

    def real_timestamps(self):
        rows = []
        for source_key in ("etth1", "weather"):
            source = self.original(source_key)
            if (
                source.timestamp is None
                or source.logical_descriptor["timestamp"]["origin"] != "SOURCE_COLUMN"
            ):
                raise ValueError(
                    "real timestamp source column required; synthesized T is forbidden"
                )
            for start in (0, 4096):
                stop = min(start + 4096, source.n_rows)
                key = f"v32_{source_key}_original_t_i64_{start}_v2"
                spec = {
                    "kind": "REAL_ORIGINAL_TIMESTAMP_WINDOW",
                    "source_key": source_key,
                    "parent_dataset_id": source.dataset_id,
                    "parent_file_sha256": source.manifest.document["file"]["sha256"],
                    "row_start": start,
                    "row_stop": stop,
                    "timestamp_policy": "PRESERVE_SOURCE_COLUMN_ORDER_VALUES_UNIT_EPOCH",
                    "value_carrier_policy": "FIRST_ORIGINAL_VALUE_COLUMN_OUTSIDE_TIMESTAMP_TASK",
                    "selected_value_carrier": source.values[0].name,
                }
                carrier = replace(source.values[0], array=source.values[0].array[start:stop])
                dataset = from_columns(
                    key, [carrier], spec, source.manifest.document["file"]["bytes"]
                )
                t = source.timestamp[start:stop]
                dataset = with_timestamp(dataset, t, source.logical_descriptor["timestamp"])
                proof = {
                    "timestamp_bytes_unchanged": dataset.timestamp.tobytes() == t.tobytes(),
                    "dtype": "<i8",
                    "count": int(t.size),
                    "unit": source.logical_descriptor["timestamp"]["unit"],
                    "epoch": source.logical_descriptor["timestamp"]["epoch"],
                    "source_timestamp_column": source.manifest.logical["timestamp"]["column"],
                    "sort_or_rebase_or_delta": False,
                    "task_raw_bits": int(t.nbytes * 8),
                    "value_carrier_is_not_task_input": True,
                }
                rows.append(
                    (self.register(key, dataset, spec, source=source, proof=proof), source, "CORE")
                )
        return rows

    def real_f32(self):
        rows = []
        for source_key in ("etth1", "weather"):
            source = self.original(source_key)
            for m in (1, 4):
                key = f"v32_{source_key}_derived_f32_{'uts' if m == 1 else 'mts'}_v2"
                columns = [
                    replace(c, array=np.asarray(c.array[:8192], dtype="<f4"))
                    for c in source.values[:m]
                ]
                if not all(np.all(np.isfinite(c.array)) for c in columns):
                    raise ValueError("finite derived f32 task required")
                spec = {
                    "kind": "REAL_DERIVED_F32_NEW_GROUND_TRUTH",
                    "source_key": source_key,
                    "parent_dataset_id": source.dataset_id,
                    "parent_file_sha256": source.manifest.document["file"]["sha256"],
                    "row_start": 0,
                    "row_stop": min(8192, source.n_rows),
                    "selected_columns": [c.name for c in columns],
                    "dtype_policy": "EXPLICIT_IEEE_F64_TO_F32_ROUNDING_NEW_TYPED_OBJECT",
                    "original_f64_recovery_claim": False,
                    "timestamp_policy": "VALUE_TRACK_TIMESTAMP_OUTSIDE_OBJECT",
                }
                proof = {
                    "finite": True,
                    "dtype": "<f4",
                    "original_f64_recovery_claim": False,
                    "lossless_task_ground_truth": "DERIVED_F32_BITS",
                    "rounded_parent_value_count": sum(
                        int(
                            np.count_nonzero(c.array.astype("<f8") != source.values[i].array[:8192])
                        )
                        for i, c in enumerate(columns)
                    ),
                }
                rows.append(
                    (
                        self.register(
                            key,
                            from_columns(
                                key, columns, spec, source.manifest.document["file"]["bytes"]
                            ),
                            spec,
                            source=source,
                            proof=proof,
                        ),
                        source,
                        "CORE",
                    )
                )
        return rows

    def auxiliary_timestamps(self):
        keys = []
        for pattern in PATTERNS:
            key = f"v32_qual_original_t_{pattern}_v2"
            n = 129
            t = np.arange(n, dtype="<i8") * 7 + 1000
            if pattern == "jitter":
                t = np.cumsum(np.resize(np.asarray([1, 2, 1, 3], dtype="<i8"), n)) + 1000
            elif pattern == "duplicate":
                t[1] = t[0]
            elif pattern == "out_of_order":
                t[2] = t[0] - 1
            self.register_t_pattern(key, t, pattern)
            keys.append(key)
        key = "v32_dev_original_t_jitter_v2"
        t = (
            np.cumsum(
                np.random.Generator(np.random.PCG64(20261011)).integers(1, 8, 257, dtype="<i8")
            )
            - 2000
        )
        self.register_t_pattern(key, t, "development_jitter")
        missing_key = "v32_t_missing_required_timestamp_test_v2"
        dataset, spec = synthetic(missing_key, "<f8", "constant", seed=20261012, n=17, m=1)
        spec.update(kind="NEGATIVE_TASK_FIXTURE", reason="MISSING_REQUIRED_TIMESTAMP")
        entry = self.register(
            missing_key, dataset, spec, split="TEST", proof={"timestamp_present": False}
        )
        return key, keys, (entry, None, "EXTENSION")

    def register_t_pattern(self, key, t, pattern):
        dataset, spec = synthetic(key, "<f8", "constant", seed=20261010, n=len(t), m=1)
        spec.update(
            kind="SYNTHETIC_TIMESTAMP",
            pattern=pattern,
            values_outside_timestamp_task=True,
            timestamp_payload_sha256=hashlib.sha256(t.tobytes()).hexdigest(),
        )
        dataset = with_timestamp(
            dataset,
            t,
            {"origin": "GENERATED", "unit": "s", "epoch": "UNIX", "order_policy": "PRESERVE"},
        )
        self.register(key, dataset, spec, split="VALIDATION")

    def auxiliary_f32(self):
        keys = []
        for pattern in ("constant", "linear", "periodic", "random"):
            key = f"v32_qual_derived_f32_{pattern}_v2"
            dataset, spec = synthetic(key, "<f4", pattern, seed=20261010, n=129, m=4)
            self.register(key, dataset, spec, split="VALIDATION")
            keys.append(key)
        key = "v32_dev_derived_f32_random_v2"
        dataset, spec = synthetic(key, "<f4", "random", seed=20261011, n=257, m=4)
        self.register(key, dataset, spec, split="VALIDATION")
        return key, keys

    def member(self, key, role):
        manifest = self.codecs.get(key)
        definition = {
            "name": manifest.document["identity"]["display_name"],
            "mechanism": manifest.document["identity"]["family"],
            "variant": key,
            "semantic_version": "1",
            "definition_sha256": hashlib.sha256(
                canonical_json_bytes(
                    {
                        field: manifest.document[field]
                        for field in ("classification", "semantics", "input", "lifecycle")
                    }
                )
            ).hexdigest(),
        }
        return {
            "member_id": key,
            "codec_key": key,
            "role": role,
            "method": definition,
            "implementation": {
                "method_id": method_id(definition),
                "source_artifact_id": manifest.source_artifact_id,
                "source_closure_sha256": registered_source_closure_digest(self.codecs, key),
                "implementation_variant": "REGISTERED_SOURCE_CPU",
            },
            "allowed_paths": ["SOURCE_REJECT_RAW"]
            if key == "alp"
            else ["DIRECT", "EXACT_WIDEN", "BYTE_SERIALIZATION", "COLUMN_INDEPENDENT", "JOINT"],
            "shared_code_tags": [f"SOURCE_ARTIFACT:{manifest.source_artifact_id}"],
        }

    def build_extended(self, group_key, base_bundle):
        timestamp = group_key == "timestamp"
        name = "G-TIMESTAMP" if timestamp else "G-FLOAT-LL-F32"
        track = BenchmarkTrack.TIMESTAMP if timestamp else BenchmarkTrack.VALUE
        core = TIMESTAMP_KEYS if timestamp else F32_KEYS
        references = () if timestamp else ("lz4-frame", "zstd-frame")
        if not set((*core, *references)) <= self.active:
            raise ValueError("group attempts to admit a non-active codec")
        base = json.loads(base_bundle.read_text())
        contract_document = dict(base["contract"])
        contract_document.update(
            name=name,
            revision=self.revision,
            track=track.value,
            research_question=(
                "Original source-column int64 timestamps, preserved sequence/unit/epoch: "
                "complete schema-bound storage and PIPELINE time on this fixed corpus; "
                "byte backends only, no claim of specialized delta timestamp methods."
                if timestamp
                else "Derived finite f32 typed objects from declared real source windows: "
                "bitwise lossless storage and PIPELINE time; "
                "no recovery claim for original f64 parents."
            ),
        )
        contract = ComparisonContract.from_document(contract_document)
        if timestamp:
            real = self.real_timestamps()
            dev, qual, rejection = self.auxiliary_timestamps()
            real.append(rejection)
        else:
            real = self.real_f32()
            dev, qual = self.auxiliary_f32()
        corpus_rows = []
        for entry, original, role in real:
            source_key = original.manifest.key if original else "missing_timestamp_fixture"
            family, entity, _ = (
                SOURCES[source_key] if original else ("SYNTHETIC", "MISSING_TIMESTAMP", None)
            )
            source = {
                "family": family,
                "entity": entity,
                "independence_unit": source_key,
                "evidence": [
                    f"GENERATION_SPEC:{self.manifests.relative_to(ROOT)}/{entry['key']}.json",
                    "COLUMNS_AND_WINDOWS_OF_ONE_SOURCE_ARE_ONE_INDEPENDENCE_UNIT",
                ],
            }
            if original:
                source["evidence"] += [
                    f"LOCAL_SOURCE_MANIFEST:{original.manifest.path.relative_to(ROOT)}",
                    f"RAW_SHA256:{original.manifest.document['file']['sha256']}",
                ]
            corpus_rows.append(
                {
                    "dataset_id": entry["dataset_id"],
                    "logical_content_id": entry["logical_content_id"],
                    "artifact_sha256": entry["artifact_sha256"],
                    "role": role,
                    "source_kind": "REAL" if original else "SYNTHETIC",
                    "source": source,
                    "parents": [
                        {
                            "dataset_id": original.dataset_id,
                            "source_kind": "REAL",
                            "family": family,
                            "entity": entity,
                            "independence_unit": source_key,
                        }
                    ]
                    if original
                    else [],
                    "derivation": "WINDOW"
                    if timestamp and original
                    else "QUANTIZED"
                    if original
                    else "SYNTHETIC",
                    "split": "TEST",
                    "weight": "1",
                    "domain_evidence": [
                        f"MANIFEST:{self.manifests.relative_to(ROOT)}/{entry['key']}.json",
                        "ORIGINAL_T_ORDER_UNIT_EPOCH_PRESERVED"
                        if timestamp
                        else "DERIVED_F32_NEW_GROUND_TRUTH",
                    ],
                }
            )
        corpus = CorpusSpec.from_document(
            {
                "schema_version": "tscb.corpus-spec.v1",
                "content_identity_policy": "tscb.dataset-content.v2",
                "name": name + "-real-core",
                "revision": self.revision,
                "selection_rule": (
                    "Predeclared source windows and columns; no result-dependent selection."
                ),
                "sampling_design": (
                    "Fixed two local source families; related windows/columns share "
                    "independence unit. Synthetic validation is disjoint; no generalization claim."
                ),
                "exclusion_rule": base["corpus"]["exclusion_rule"],
                "datasets": corpus_rows,
            }
        )
        members = [
            self.member(key, "CORE" if key in core else "REFERENCE") for key in (*core, *references)
        ]
        configs = MethodConfigMap.from_document(
            {
                "schema_version": "tscb.method-config-map.v1",
                "contract_id": contract.id,
                "selection_policy": contract_document["selection_policy"],
                "members": [
                    {"member_id": key, "configs": configurations_for(self.codecs.get(key), "byte")}
                    for key in (*core, *references)
                ],
            }
        )
        equivalence = []
        for member in members:
            key = member["codec_key"]
            if timestamp and key == "lzss-dipperstein-c":
                continue
            cls = "lzss-family" if timestamp and key == "lzss-raw" else key
            equivalents = ["lzss-raw", "lzss-dipperstein-c"] if cls == "lzss-family" else [key]
            equivalence.append(
                {
                    "class_id": cls,
                    "members": equivalents,
                    "basis": (
                        "Conservative LZSS family equivalence for this byte task; "
                        "implementation paths stay separate."
                    )
                    if cls == "lzss-family"
                    else (
                        "Frozen mechanism/variant class; aliases/parameters/builds add no methods."
                    ),
                    "evidence": [f"MANIFEST:registry/codecs/{k}.json" for k in equivalents],
                }
            )
        expected_rows = []
        for entry, _, role in real:
            dataset = load_dataset(self.datasets.load(entry["key"]))
            descriptor = descriptor_from_dataset(dataset, track)
            for config_row in configs.to_document()["members"]:
                key = config_row["member_id"]
                config = config_row["configs"][0]
                compatible = negotiate(
                    self.codecs.get(key), descriptor, parameters=config["parameters"]
                )
                reject = role == "EXTENSION"
                if (compatible.status is CapabilityStatus.UNSUPPORTED) != reject:
                    raise ValueError(f"frozen structural expectation failed: {key}/{entry['key']}")
                expected_rows.append(
                    {
                        "dataset_id": entry["dataset_id"],
                        "member_id": key,
                        "config_key": config["config_key"],
                        "expected": {
                            "outcome": "REJECT" if reject else "PASS",
                            "origin": "TASK",
                            "stage": "INPUT_NEGOTIATION" if reject else "COMPLETE_RECOVERY",
                            "reason": compatible.reason_code
                            if reject
                            else "STRUCTURALLY_LEGAL_REQUIRES_REAL_QUALIFICATION",
                            "evidence": [
                                f"MANIFEST:registry/codecs/{key}.json",
                                f"DOMAIN_PROOF:{self.manifests.relative_to(ROOT)}/{entry['key']}.json",
                            ],
                        },
                    }
                )
        expected = ExpectedOutcomeMatrix.from_document(
            {
                "schema_version": "tscb.expected-outcome-matrix.v1",
                "contract_id": contract.id,
                "corpus_id": corpus.id,
                "config_map_id": configs.id,
                "entries": expected_rows,
            }
        )
        group = GroupSpec.from_document(
            {
                "schema_version": "tscb.group-spec.v1",
                "name": name,
                "revision": self.revision,
                "contract_id": contract.id,
                "corpus_id": corpus.id,
                "config_map_id": configs.id,
                "expected_matrix_id": expected.id,
                "scope": "CORE_COMPARISON",
                "minimum_distinct_methods": 2,
                "minimum_independent_real_sources": 2,
                "completion_policy": "ALL_CORE_LEGAL_CONFIGS_AND_EXPECTED_TERMINALS",
                "members": members,
                "method_equivalence": equivalence,
            }
        )
        plan = compile_group_plan(
            group,
            contract,
            corpus,
            configs,
            expected,
            codec_registry=self.codecs,
            active_codec_keys=self.active,
        )
        bundle = {
            **{
                k: base[k]
                for k in ("schema_version", "protocol", "analysis_policy", "cpu_affinity", "seed")
            },
            "contract": contract.to_document(),
            "corpus": corpus.to_document(),
            "group": group.to_document(),
            "config_map": configs.to_document(),
            "expected_matrix": expected.to_document(),
            "dataset_bindings": {entry["dataset_id"]: entry["key"] for entry, _, _ in real},
            "development_dataset": dev,
            "qualification_datasets": qual,
        }
        target = (
            ROOT / "configs/comparisons" / f"{name.lower()}-v32-20261010{self.revision_suffix}.json"
        )
        write_or_verify(target, bundle)
        write_or_verify(
            self.payload_root / "plans" / f"{name}{self.revision_suffix}.json", plan.to_document()
        )
        artifacts = {}
        for key in (*core, *references):
            primary, supporting = adapter_artifacts(ROOT, self.codecs.get(key))
            artifacts[key] = [
                {
                    "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                    if path.is_file()
                    else None,
                }
                for path in (primary, *supporting)
            ]
        write_or_verify(
            self.payload_root / "provenance" / f"{name}{self.revision_suffix}.json",
            {
                "schema_version": "tscb.comparison-build-provenance.v1",
                "bundle_sha256": hashlib.sha256(canonical_json_bytes(bundle)).hexdigest(),
                "base_bundle": str(base_bundle.relative_to(ROOT)),
                "base_bundle_sha256": hashlib.sha256(base_bundle.read_bytes()).hexdigest(),
                "denominators": plan.denominators,
                "build_artifacts": artifacts,
                "datasets": [entry for entry, _, _ in real],
                "development_dataset": self.entries[dev],
                "qualification_datasets": [self.entries[key] for key in qual],
                "scientific_scope": {
                    "original_timestamp_task": timestamp,
                    "derived_f32_new_ground_truth": not timestamp,
                    "original_f64_recovery_claim": False
                    if not timestamp
                    else "NOT_APPLICABLE_TIMESTAMP_TASK",
                    "timestamp_values_carrier_outside_task": timestamp,
                    "missing_timestamp_reject_cells": 8 if timestamp else 0,
                    "boundary_suite": (
                        "EXISTING_PREFLIGHT_TIMESTAMP_EXTREME_EPOCH_AND_CAPACITY_REJECTION"
                    ),
                    "status": "FROZEN_SPECS_NOT_EXECUTED",
                },
            },
        )
        return {
            "bundle": str(target.relative_to(ROOT)),
            "cells": len(plan.cells),
            "denominators": plan.denominators,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--groups", nargs="+", choices=("timestamp", "f32"), default=["timestamp", "f32"]
    )
    parser.add_argument(
        "--base-bundle",
        type=Path,
        default=ROOT / "configs/comparisons/g-byte-ll-v32-20261010-v3.json",
    )
    parser.add_argument(
        "--payload-root", type=Path, default=ROOT / "artifacts/comparisons/v32_20261010"
    )
    parser.add_argument("--revision", type=int, default=1)
    args = parser.parse_args()
    base = json.loads(args.base_bundle.read_text())
    builder = ExtendedBuilder(args.payload_root, base["cpu_affinity"], revision=args.revision)
    for group in args.groups:
        print(
            json.dumps(
                builder.build_extended(group, args.base_bundle.resolve()), ensure_ascii=False
            )
        )


if __name__ == "__main__":
    main()
