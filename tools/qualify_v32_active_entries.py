#!/usr/bin/env python3
"""Qualify the frozen active codec scope and produce four separate V3.2 matrices.

The selected registered fixture/configuration is a finite qualification domain.
Neither source declarations nor historical standalone audits grant a current
benchmark or performance PASS. Run --plan-only while implementation is changing;
run --execute only after the runtime is stable. Resume refuses frozen drift.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
import tomllib
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tscompbench.accounting import AccountingLedger
from tscompbench.adapters import adapter_artifacts, create_adapter
from tscompbench.codecs import CodecRegistry, SourceRegistry, negotiate
from tscompbench.codecs.negotiation import descriptor_from_dataset
from tscompbench.configuration import _load_profile
from tscompbench.contracts import BenchmarkTrack, CapabilityStatus, RunStatus
from tscompbench.datasets import DatasetRegistry, load_dataset
from tscompbench.datasets.canonical import read_canonical, write_canonical
from tscompbench.environment import capture_environment
from tscompbench.execution.preflight import preflight_task
from tscompbench.execution.recovery import DecodeContext
from tscompbench.execution.routing import route_canonical_artifact
from tscompbench.ids import canonical_json_bytes, stable_id
from tscompbench.measurement.resource_lease import ResourceLease
from tscompbench.planning import (
    build_comparability_keys,
    create_task,
    expand_sweep,
    resolve_execution,
)
from tscompbench.preprocess import build_preprocess_plan
from tscompbench.validation import validate_routed_input
from tscompbench.version import __version__

MATRIX_NAMES = (
    "SourceCapabilityMatrix",
    "StandalonePortMatrix",
    "BenchProfileMatrix",
    "PipelineCoverageMatrix",
)
GROUP_PATHS = (
    "configs/comparisons/g-byte-ll-v32-20261010.json",
    "configs/comparisons/g-float-ll-f64-v32-20261010.json",
    "configs/comparisons/g-int-ll-i16-v32-20261010.json",
    "configs/comparisons/g-float-abs-v32-20261010.json",
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = json.loads(canonical_json_bytes(value))
    encoded = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(encoded + "\n", encoding="utf-8")
    temporary.replace(path)


def active_keys(root: Path, registry: CodecRegistry) -> tuple[str, ...]:
    """Read activity from the scope, never infer it from a successful local build."""
    scope = json.loads((root / "registry/algorithm_scope.json").read_text())
    keys = tuple(sorted(scope["registered_codecs"]))
    registered = set(registry.keys())
    excluded = set(scope["retained_out_of_scope_registrations"]) | set(scope["framework_oracles"])
    if not keys or set(keys) & excluded or set(keys) - registered:
        raise ValueError("active codec scope overlaps exclusions or lacks a manifest")
    unexplained = registered - set(keys) - excluded
    if unexplained:
        raise ValueError(f"registered entries lack an explicit scope role: {sorted(unexplained)}")
    return keys


def file_evidence(root: Path, path: str | Path, expected: str | None = None) -> dict[str, Any]:
    candidate = Path(path)
    absolute = candidate if candidate.is_absolute() else root / candidate
    actual = sha256(absolute) if absolute.is_file() else None
    return {
        "path": str(candidate),
        "expected_sha256": expected,
        "actual_sha256": actual,
        "status": "MISSING"
        if actual is None
        else "HASH_MATCH"
        if expected == actual
        else ("HASH_MISMATCH" if expected is not None else "HASH_OBSERVED"),
    }


def _source_tree_files(root: Path, relative: str) -> list[dict[str, Any]]:
    tree = root / relative
    return (
        [
            file_evidence(root, path.relative_to(root))
            for path in sorted(tree.rglob("*"))
            if path.is_file() and not path.is_symlink()
        ]
        if tree.is_dir()
        else []
    )


def _patch_file_reference(root: Path, item: Any) -> bool:
    """Descriptions are retained as annotations, never probed as file paths.

    Missing path-like references still fail. This distinguishes the historical
    explanatory strings from real patch declarations without silently ignoring
    an absent .patch/.diff or repository path.
    """
    if isinstance(item, dict):
        return isinstance(item.get("path"), str)
    if not isinstance(item, str):
        return False
    candidate = Path(item)
    return (
        candidate.suffix.lower() in {".patch", ".diff"}
        or candidate.is_absolute()
        or item.startswith(("./", "../", "adapters/", "tools/", "native/", "build/"))
        or (len(item.split()) == 1 and "/" in item and "://" not in item)
        or (len(item) < 4096 and (root / candidate).is_file())
    )


def source_evidence(root: Path, source: dict[str, Any]) -> dict[str, Any]:
    identity, build = source.get("identity", {}), source.get("build", {})
    selected = list(identity.get("source_closure", []))
    entries = list(identity.get("api_files", [])) + selected
    entries += list(build.get("source_closure", []))
    patches = list(build.get("patches", []))
    entries += [item for item in patches if _patch_file_reference(root, item)]
    annotations = [item for item in patches if not _patch_file_reference(root, item)]
    references = []
    for name in ("frozen_lock", "admission_card"):
        if build.get(name):
            references.append(file_evidence(root, build[name]))
    if build.get("frozen_lock"):
        lock = root / build["frozen_lock"]
        if lock.is_file():
            packages = json.loads(lock.read_text()).get("packages", {})
            package = build.get("standalone_package", identity.get("package"))
            entries += packages.get(package, {}).get("files", [])
    entries = [{"path": item} if isinstance(item, str) else item for item in entries]
    unique = {(item["path"], item.get("sha256")): item for item in entries}
    files = [
        file_evidence(root, path, expected)
        for path, expected in sorted(unique, key=lambda item: item[0])
    ]
    selected_closure = None
    if selected:
        protocol = identity.get("source_closure_digest_format")
        expected = identity.get("source_closure_sha256")
        digest = hashlib.sha256()
        observed = None
        if protocol == "SORTED_REPOSITORY_RELATIVE_PATH_UTF8_NUL_THEN_FILE_BYTES":
            selected_paths = [item if isinstance(item, str) else item["path"] for item in selected]
            if len(selected_paths) == len(set(selected_paths)) and all(
                (root / path).is_file() for path in selected_paths
            ):
                for relative in sorted(selected_paths):
                    digest.update(relative.encode("utf-8") + b"\0" + (root / relative).read_bytes())
                observed = digest.hexdigest()
            state = "HASH_MATCH" if observed == expected and expected is not None else "DRIFT"
            if identity.get("source_closure_file_count", len(selected_paths)) != len(
                selected_paths
            ):
                state = "DRIFT"
        else:
            state = "UNKNOWN_SELECTED_CLOSURE_OR_HASH_PROTOCOL_NOT_EQUIVALENT"
        selected_closure = {
            "file_count": len(selected),
            "declared_sha256": expected,
            "observed_sha256": observed,
            "hash_protocol": protocol,
            "state": state,
        }
    observed_trees = []
    tree_paths = {identity["source_path"]} if identity.get("source_path") else set()
    if not tree_paths:
        paths = build.get("translation_units", []) + source.get("license", {}).get("files", [])
        for path in paths:
            if "/vendor/" in path:
                prefix, relative = path.split("/vendor/", 1)
                candidate = prefix + "/vendor/" + relative.split("/", 1)[0]
                # LICENSE/source files immediately inside vendor are file
                # references, not nonexistent directory roots.
                if "/" not in relative:
                    if not any(item["path"] == candidate for item in files):
                        files.append(file_evidence(root, candidate))
                else:
                    tree_paths.add(candidate)
    for relative in sorted(tree_paths):
        tree = root / relative
        inventory = _source_tree_files(root, relative)
        digest = hashlib.sha256()
        for item in inventory:
            path = root / item["path"]
            digest.update(path.relative_to(tree).as_posix().encode() + b"\0" + path.read_bytes())
        actual = digest.hexdigest() if inventory else None
        expected = identity.get("source_closure_sha256")
        observed_trees.append(
            {
                "path": relative,
                "file_count": len(inventory),
                "files": inventory,
                "observed_sha256": actual,
                "declared_sha256": expected,
                "hash_protocol": "RELATIVE_PATH_NUL_FILE_BYTES_V1",
                "state": "MISSING"
                if not tree.is_dir()
                else "HASH_MATCH"
                if actual == expected and actual is not None
                else "UNKNOWN_SELECTED_CLOSURE_OR_HASH_PROTOCOL_NOT_EQUIVALENT",
            }
        )
    has_drift = any(item["status"] in {"MISSING", "HASH_MISMATCH"} for item in files + references)
    has_drift |= selected_closure is not None and selected_closure["state"] == "DRIFT"
    has_drift |= any(tree["state"] == "MISSING" for tree in observed_trees)
    locked_files = bool(files) and all(item["status"] == "HASH_MATCH" for item in files)
    observed_files = any(item["status"] == "HASH_OBSERVED" for item in files)
    if has_drift:
        closure_status = "DRIFT"
    elif selected_closure is not None and selected_closure["state"] == "HASH_MATCH":
        closure_status = "HASHES_VERIFIED_SELECTED_CLOSURE"
    elif observed_trees and all(tree["state"] == "HASH_MATCH" for tree in observed_trees):
        closure_status = "HASHES_VERIFIED_VENDOR_TREES"
    elif observed_trees or selected_closure is not None:
        closure_status = "UNKNOWN_SELECTED_CLOSURE_OR_HASH_PROTOCOL_NOT_EQUIVALENT"
    elif locked_files:
        closure_status = "LOCKED_FILE_HASHES_VERIFIED_CLOSURE_UNKNOWN"
    elif files:
        closure_status = (
            "UNKNOWN_PARTIALLY_LOCKED_FILES"
            if any(item["status"] == "HASH_MATCH" for item in files)
            else "UNKNOWN_OBSERVED_HASHES_ONLY"
        )
    else:
        closure_status = "UNKNOWN_NO_FILE_CLOSURE"
    return {
        "source_artifact_id": source["source_artifact_id"],
        "record_sha256": hashlib.sha256(canonical_json_bytes(source)).hexdigest(),
        "identity": identity,
        "license": source.get("license"),
        "availability": source.get("availability", "NOT_EXPLICITLY_RECORDED"),
        "files": files,
        "references": references,
        "patch_annotations": annotations,
        "selected_source_closure": selected_closure,
        "observed_vendor_trees": observed_trees,
        "closure_status": closure_status,
        "file_hash_validation": "DRIFT"
        if has_drift
        else "LOCKED_HASHES_VERIFIED"
        if locked_files
        else "PARTIALLY_LOCKED"
        if observed_files and any(item["status"] == "HASH_MATCH" for item in files)
        else "OBSERVED_ONLY"
        if observed_files
        else "NO_FILE_HASHES",
        "actual_build_runtime_closure_validation": "UNKNOWN_NOT_CHECKED_BY_SOURCE_INVENTORY",
        "source_domain_validation": "UNKNOWN_NOT_INFERRED_FROM_HASHES",
    }


def standalone_evidence(root: Path, key: str, manifest: Any) -> dict[str, Any]:
    """Keep old standalone results and domains readable without re-signing them."""
    path = root / "docs/completed_rewrite_integration_audit.json"
    records = []
    if path.is_file():
        document = json.loads(path.read_text())
        for package in document.get("inventory", []):
            for record in package.get("codecs", []):
                if record.get("algorithm") == key:
                    records.append(
                        {
                            "package": package["package"],
                            "rewrite_status": package.get("rewrite_status"),
                            "algorithm_id": record.get("algorithm_id"),
                            "source_artifact_id": record.get("source_artifact_id"),
                            "status_as_recorded": record.get("status"),
                            "qualification_scope": record.get("qualification_scope"),
                            "admitted_input": record.get("admitted_input"),
                            "known_limitations": record.get("known_limitations"),
                            "binary_sha256_as_recorded": record.get("binary_sha256"),
                            "raw": file_evidence(
                                root,
                                Path(record["run_path"]) / "run_components.jsonl",
                                record.get("raw_sha256"),
                            ),
                            "identity_matches_current": record.get("algorithm_id")
                            == manifest.algorithm_id
                            and record.get("source_artifact_id") == manifest.source_artifact_id,
                        }
                    )
    primary = root / manifest.document["adapter"]["artifact_path"]
    build_path = primary.parent / "build-record.json"
    build_record = json.loads(build_path.read_text()) if build_path.is_file() else None
    native_audits = []
    for profile in ("release", "sanitizer"):
        audit = root / "docs/completed_rewrites" / f"{key}-native-{profile}.json"
        if audit.is_file():
            record = json.loads(audit.read_text())
            native_audits.append(
                {
                    "artifact": file_evidence(root, audit),
                    "status_as_recorded": record.get("status"),
                    "scope_as_recorded": record.get("scope"),
                    "log": file_evidence(root, record["log"], record.get("log_sha256"))
                    if record.get("log")
                    else None,
                    "build_record_sha256_as_recorded": record.get("build_record_sha256"),
                    "binary_sha256_as_recorded": record.get("artifact_sha256"),
                }
            )
    return {
        "current_artifact": file_evidence(
            root, primary, (build_record or {}).get("artifact_sha256")
        ),
        "build_record": file_evidence(root, build_path),
        "build_status_as_recorded": (build_record or {}).get("status", "NOT_RECORDED"),
        "historical_audit": file_evidence(root, path),
        "historical_records": records,
        "historical_native_audits": native_audits,
        "current_standalone_qualification": "UNKNOWN_NOT_REEXECUTED",
        "historical_pass_promoted": False,
    }


def _candidate_templates(root: Path, registry: CodecRegistry, key: str) -> list[tuple[Path, dict]]:
    candidates = []
    for path in sorted((root / "configs/experiments").glob("*qualification.toml")):
        raw = tomllib.loads(path.read_text())
        canonical = {registry.get(algorithm).key for algorithm in raw.get("algorithms", [])}
        if key not in canonical:
            continue
        priority = (
            "unsupported" in path.name,
            not all(
                dataset.startswith(("rewrite_", "sprintz_", "streamvbyte_"))
                for dataset in raw.get("datasets", [])
            ),
            len(raw.get("algorithms", [])),
            path.name,
        )
        candidates.append((priority, path, raw))
    return [(path, raw) for _, path, raw in sorted(candidates)]


def _qualification_descriptor(dataset, track):
    # The retained canonical file guarantees byte alignment only. Planning must
    # not bind a transient NumPy allocation address to the frozen task identity;
    # negotiate explicitly inserts any stronger required ALIGNED_COPY.
    return replace(descriptor_from_dataset(dataset, track), alignment_bytes=1)


def select_cases(
    root: Path,
    registry: CodecRegistry,
    key: str,
    cpu: int,
    model_cpus: tuple[int, ...] = (0, 2, 4),
) -> list[dict[str, Any]]:
    """Choose one legal config/fixture per declared track, recording all failed probes."""
    manifest = registry.get(key)
    datasets = DatasetRegistry(root / "registry/datasets", root)
    templates = _candidate_templates(root, registry, key)
    cache: dict[str, Any] = {}
    cases = []
    for track in manifest.tracks:
        rejected = []
        selected = None
        for path, raw in templates:
            configs = expand_sweep(
                manifest, raw.get("sweep", {}), framework_parameters={"benchmark_seed": 20261010}
            )
            for dataset_key in raw.get("datasets", []):
                if dataset_key not in cache:
                    cache[dataset_key] = load_dataset(datasets.load(dataset_key))
                dataset = cache[dataset_key]
                if track is BenchmarkTrack.TIMESTAMP and dataset.timestamp is None:
                    continue
                descriptor = _qualification_descriptor(dataset, track)
                for config in configs:
                    compatibility = negotiate(manifest, descriptor, parameters=config.parameters)
                    if (
                        config.status is not RunStatus.PLANNED
                        or compatibility.status is CapabilityStatus.UNSUPPORTED
                    ):
                        rejected.append(
                            {
                                "template": str(path.relative_to(root)),
                                "dataset": dataset_key,
                                "config_id": config.config_id,
                                "reason": config.reason_code
                                if config.status is not RunStatus.PLANNED
                                else compatibility.reason_code,
                            }
                        )
                        continue
                    profile_raw = dict(raw.get("profile", {}))
                    requested_threads = profile_raw.get("threads", 1)
                    frozen_threads = 3 if key == "dzip" else requested_threads
                    frozen_cpus = list(model_cpus) if key == "dzip" else [cpu]
                    if frozen_threads > len(frozen_cpus) or (
                        key == "dzip" and len(set(frozen_cpus)) != 3
                    ):
                        raise ValueError("qualification must preserve the declared thread budget")
                    requested_budget = {
                        "threads": requested_threads,
                        "cpu_affinity": profile_raw.get("cpu_affinity"),
                        "memory_limit_bytes": profile_raw.get("memory_limit_bytes"),
                        "processes": profile_raw.get("processes", 1),
                    }
                    profile_raw.pop("qualification_repetitions", None)
                    profile_raw.update(
                        measurement_mode="QUALIFICATION",
                        timing_scope="PIPELINE",
                        cpu_affinity=frozen_cpus,
                        threads=frozen_threads,
                        processes=1,
                        warmup_min_count=0,
                        warmup_min_seconds="0",
                        repetitions=1,
                        min_repetition_seconds="0",
                        max_inner_iterations=1,
                        query_workload=False,
                        streaming_workload=False,
                    )
                    profile = _load_profile(profile_raw)
                    selected = {
                        "codec_key": key,
                        "track": track.value,
                        "dataset_key": dataset_key,
                        "descriptor": descriptor.identity_document(),
                        "descriptor_alignment_basis": (
                            "SERIALIZED_CANONICAL_BYTE_ALIGNMENT_GUARANTEE"
                        ),
                        "dataset_manifest": file_evidence(root, datasets.load(dataset_key).path),
                        "dataset_source": file_evidence(
                            root,
                            datasets.load(dataset_key).source_path,
                            dataset.manifest.document["file"]["sha256"],
                        ),
                        "template": file_evidence(root, path),
                        "parameters": config.parameters,
                        "config_id": config.config_id,
                        "profile": profile.as_document(),
                        "profile_id": profile.profile_id,
                        "resource_budget": {
                            "template_requested": requested_budget,
                            "frozen_applied": {
                                "threads": profile.threads,
                                "cpu_affinity": list(profile.cpu_affinity),
                                "memory_limit_bytes": profile.memory_limit_bytes,
                                "processes": profile.processes,
                            },
                            "worker_thread_high_water": "NOT_GRANTED_BY_OBJECT_PREFLIGHT",
                        },
                        "template_extension_profiles": {
                            name: bool(raw.get("profile", {}).get(name))
                            for name in ("query_workload", "streaming_workload")
                        },
                        "compatibility": compatibility.to_document(),
                        "selection_rejections": rejected,
                        "qualification_scope": "ONE_REGISTERED_FINITE_FIXTURE_PER_DECLARED_TRACK",
                    }
                    selected["case_id"] = stable_id("active-entry-qualification-case-v32", selected)
                    break
                if selected is not None:
                    break
            if selected is not None:
                break
        if selected is None:
            cases.append(
                {
                    "codec_key": key,
                    "track": track.value,
                    "status": "NOT_PLANNED",
                    "reason": "NO_DECLARED_LEGAL_REGISTERED_FIXTURE_CONFIG",
                    "selection_rejections": rejected,
                }
            )
        else:
            cases.append(selected)
    return cases


def role_ledger(root: Path, registry: CodecRegistry, keys: tuple[str, ...]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = {}
    for relative in GROUP_PATHS:
        document = json.loads((root / relative).read_text())
        for member in document["group"]["members"]:
            groups.setdefault(member["codec_key"], []).append(
                {"group": document["group"]["name"], "role": member["role"], "bundle": relative}
            )
    rows = []
    for key in keys:
        manifest = registry.get(key)
        if key in {"abba", "fabba"}:
            role, reason = (
                "UNBOUNDED_QUALITY_RESEARCH_ENTRY",
                "须冻结质量指标/域后单独比较；不能冒称通用ABS或无损资格。",
            )
        elif key in {"deepzip", "dzip"}:
            role, reason = (
                "FROZEN_MODEL_ALPHABET_RESEARCH_ENTRY",
                "已有u8/alphabet完整恢复任务；模型成本计入，typed byte桥接须另冻结方案。",
            )
        elif key == "simdcomp-u32":
            role, reason = (
                "P0_UINT32_PRIMITIVE",
                "原生uint32 API组；完整typed对象须计入descriptor/变换/尾部方案成本。",
            )
        elif key in {"fse", "huff0"}:
            role, reason = (
                "ENTROPY_COMPLETE_BYTE_ENTRY_AND_PIPELINE_CHILD",
                "保留完整byte入口及组合子codec角色；长度/字节域限制必须显式验证。",
            )
        elif key.startswith("sprintz-") and key.endswith("-u8"):
            role, reason = (
                "UINT8_SPECIALIZED_METHOD_VARIANT",
                "原生u8 UTS变体；和i16入口共享机制但配置/域及身份单独保留。",
            )
        else:
            role, reason = (
                "BYTE_LOSSLESS_EXTENSION_ENTRY",
                "当前byte完整方案候选；独立资格不能代替加入冻结共同组的FORMAL测量。",
            )
        rows.append(
            {
                "codec_key": key,
                "algorithm_id": manifest.algorithm_id,
                "source_artifact_id": manifest.source_artifact_id,
                "object_level": manifest.object_level.value,
                "comparison_memberships": groups.get(key, []),
                "in_four_initial_groups": key in groups,
                "scope_status": "ACTIVE_REQUIRED_WHEN_APPLICABLE",
                "role": "FROZEN_COMPARISON_MEMBER" if key in groups else role,
                "reason": "见冻结GroupSpec；登记/资格/正式测量分别授予。"
                if key in groups
                else reason,
            }
        )
    return rows


def runtime_evidence(root: Path) -> list[dict[str, Any]]:
    files = sorted((root / "src/tscompbench").rglob("*.py"))
    files += [root / "tools/qualify_v32_active_entries.py", root / "registry/algorithm_scope.json"]
    files += sorted((root / "registry/codecs").glob("*.json"))
    files += sorted((root / "registry/sources").glob("*.json"))
    return [file_evidence(root, path.relative_to(root)) for path in files]


def build_plan(
    root: Path,
    cpu: int,
    selected_keys: list[str] | None = None,
    model_cpus: tuple[int, ...] = (0, 2, 4),
) -> dict[str, Any]:
    registry = CodecRegistry(root / "registry/codecs", SourceRegistry(root / "registry/sources"))
    keys = active_keys(root, registry)
    chosen = tuple(sorted(selected_keys)) if selected_keys else keys
    if len(chosen) != len(set(chosen)) or set(chosen) - set(keys):
        raise ValueError("selected keys must be unique active entries")
    entries = []
    for key in chosen:
        manifest = registry.get(key)
        artifact_error = None
        try:
            primary, support = adapter_artifacts(root, manifest)
        except RuntimeError as error:
            primary, support = root / manifest.document["adapter"]["artifact_path"], ()
            artifact_error = {"error_type": type(error).__name__, "message": str(error)}
        entries.append(
            {
                "codec_key": key,
                "algorithm_id": manifest.algorithm_id,
                "source_artifact_id": manifest.source_artifact_id,
                "declared_domain": manifest.document["input"],
                "declared_adapter_domain": manifest.document["adapter"].get("input_contract"),
                "loss_modes": [value.value for value in manifest.loss_modes],
                "declared_features": manifest.document["features"],
                "declared_execution": manifest.document["execution"],
                "source": source_evidence(root, registry.sources.get(manifest.source_artifact_id)),
                "standalone": standalone_evidence(root, key, manifest),
                "execution_files": [file_evidence(root, path) for path in (primary, *support)],
                "artifact_resolution_error": artifact_error,
                "cases": select_cases(root, registry, key, cpu, model_cpus),
            }
        )
    roles = role_ledger(root, registry, keys)
    document = {
        "schema_version": "tscb.active-entry-qualification-plan.v3.2",
        "active_keys": list(keys),
        "selected_keys": list(chosen),
        "cpu": cpu,
        "model_cpus": list(model_cpus),
        "performance_claim": False,
        "runtime_files": runtime_evidence(root),
        "entries": entries,
        "role_ledger": roles,
        "matrix_names": list(MATRIX_NAMES),
        "scope_rule": "FINITE_FIXTURE_AND_BOUNDARY_QUALIFICATION_IS_NOT_FULL_DECLARED_DOMAIN_PASS",
    }
    document["plan_id"] = stable_id("active-entry-qualification-plan-v32", document)
    return document


def validate_frozen(plan: dict[str, Any], root: Path) -> None:
    identity = {key: value for key, value in plan.items() if key != "plan_id"}
    if stable_id("active-entry-qualification-plan-v32", identity) != plan["plan_id"]:
        raise ValueError("frozen qualification plan identity mismatch")
    saved = [
        {"path": item["path"], "actual_sha256": item["actual_sha256"]}
        for item in plan["runtime_files"]
    ]
    current = [
        {"path": item["path"], "actual_sha256": item["actual_sha256"]}
        for item in runtime_evidence(root)
    ]
    if saved != current:
        raise ValueError("qualification runtime/registry drift; create a new frozen plan/output")
    for entry in plan["entries"]:
        evidence = list(entry["execution_files"])
        evidence += entry["source"]["files"] + entry["source"]["references"]
        for tree in entry["source"].get("observed_vendor_trees", []):
            current_files = _source_tree_files(root, tree["path"])
            if current_files != tree["files"]:
                raise ValueError(f"qualification source tree inventory drift: {tree['path']}")
            evidence += tree["files"]
        standalone = entry["standalone"]
        evidence += [
            standalone[name] for name in ("current_artifact", "build_record", "historical_audit")
        ]
        evidence += [record["raw"] for record in standalone["historical_records"]]
        for record in standalone.get("historical_native_audits", []):
            evidence.append(record["artifact"])
            if record.get("log"):
                evidence.append(record["log"])
        for case in entry["cases"]:
            if "case_id" in case:
                evidence += [case["template"], case["dataset_manifest"], case["dataset_source"]]
        for item in evidence:
            actual = file_evidence(root, item["path"])["actual_sha256"]
            if actual != item["actual_sha256"]:
                raise ValueError(f"qualification dependency drift: {item['path']}")


def preflight_acceptance(document: dict[str, Any]) -> dict[str, Any]:
    """Do not grant scoped PASS if any mandatory recovery/cost/safety proof is absent."""
    recovery = document.get("diagnostics", {}).get("independent_recovery", {})
    ledger, boundary = document.get("accounting") or {}, document.get("boundary") or {}
    try:
        parsed_ledger = AccountingLedger(
            **{
                key: BenchmarkTrack(value) if key == "track" else value
                for key, value in ledger.items()
                if key not in {"schema_version", "compression_factor", "size_ratio"}
            }
        )
        complete_ledger = canonical_json_bytes(parsed_ledger.to_document()) == canonical_json_bytes(
            ledger
        )
    except TypeError, ValueError:
        complete_ledger = False
    checks = {
        "preflight_pass": document.get("status") == "PASS",
        "correctness_pass": (document.get("correctness") or {}).get("status") == "PASS",
        "boundary_safety_pass": boundary.get("passed") is True
        and bool(boundary.get("observations")),
        "complete_cost_ledger": complete_ledger,
        "independent_recovery": recovery.get("start_method") == "spawn"
        and recovery.get("encoder_session_available") is False
        and recovery.get("original_input_available") is False
        and recovery.get("output_owned_in_worker") is True,
        "stream_hash_bound": bool(document.get("bitstream_sha256"))
        and recovery.get("stream_sha256") == document.get("bitstream_sha256"),
        "context_cost_bound": isinstance(recovery.get("decode_context_sha256"), str)
        and len(recovery["decode_context_sha256"]) == 64
        and type(recovery.get("required_external_bits")) is int
        and recovery["required_external_bits"] > 0
        and ledger.get("external_side_information_bits") == recovery["required_external_bits"],
        "independent_worker_exit": document.get("diagnostics", {})
        .get("independent_recovery_worker_lifecycle", {})
        .get("worker_exit_confirmed")
        is True
        and document.get("diagnostics", {})
        .get("independent_recovery_worker_lifecycle", {})
        .get("exit_code")
        == 0,
    }
    return {
        "status": "SCOPED_PASS" if all(checks.values()) else "NOT_ACCEPTED",
        "checks": checks,
        "rejection_safety": [
            observation
            for observation in boundary.get("observations", [])
            if "REJECT" in observation.get("reason", "")
        ],
        "unexecuted_domains": "UNKNOWN_NOT_PROMOTED",
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _resolve_case(root: Path, entry: dict, case: dict, environment: dict, artifact):
    """Rebuild the exact selected task and recovery context without invoking a codec."""
    registry = CodecRegistry(root / "registry/codecs", SourceRegistry(root / "registry/sources"))
    manifest = registry.get(entry["codec_key"])
    _require(
        case["codec_key"] == entry["codec_key"] and manifest.algorithm_id == entry["algorithm_id"],
        "selected codec/algorithm identity differs from frozen entry",
    )
    dataset = load_dataset(
        DatasetRegistry(root / "registry/datasets", root).load(case["dataset_key"])
    )
    for key, path in (
        ("dataset_manifest", dataset.manifest.path),
        ("dataset_source", dataset.manifest.source_path),
    ):
        _require(
            file_evidence(root, path)["actual_sha256"] == case[key]["actual_sha256"],
            "selected fixture source/manifest drift",
        )
    with tempfile.TemporaryDirectory(prefix="tscb-active-fixture-") as temporary:
        expected = write_canonical(dataset, Path(temporary) / "expected.tscb")
        _require(
            artifact.sha256 == expected.sha256,
            "saved canonical bytes differ from the original planned fixture",
        )
    descriptor = _qualification_descriptor(dataset, BenchmarkTrack(case["track"]))
    config = expand_sweep(
        manifest,
        {k: [v] for k, v in case["parameters"].items()},
        framework_parameters={"benchmark_seed": 20261010},
    )[0]
    _require(
        config.config_id == case["config_id"],
        "frozen selected configuration no longer resolves identically",
    )
    _require(
        canonical_json_bytes(descriptor.identity_document())
        == canonical_json_bytes(case["descriptor"]),
        "frozen selected fixture descriptor no longer resolves identically: "
        + str(
            {
                key: (case["descriptor"].get(key), value)
                for key, value in descriptor.identity_document().items()
                if canonical_json_bytes(case["descriptor"].get(key)) != canonical_json_bytes(value)
            }
        ),
    )
    profile = _load_profile(case["profile"])
    _require(
        profile.profile_id == case["profile_id"], "frozen qualification profile identity drift"
    )
    profile_doc = {**profile.as_document(), "runner_version": __version__}
    compatibility = negotiate(manifest, descriptor, parameters=config.parameters)
    _require(
        canonical_json_bytes(compatibility.to_document())
        == canonical_json_bytes(case["compatibility"]),
        "frozen qualification descriptor/compatibility differs",
    )
    primary, support = adapter_artifacts(root, manifest)
    execution = resolve_execution(
        manifest,
        config,
        compatibility,
        environment,
        artifact_path=primary,
        supporting_artifact_paths=support,
        profile=profile_doc,
    )
    task = create_task(
        descriptor=descriptor,
        manifest=manifest,
        config=config,
        profile_id=profile.profile_id,
        compatibility=compatibility,
        preprocess=build_preprocess_plan(manifest.document, config.parameters),
        execution=execution,
        comparability=build_comparability_keys(
            manifest, descriptor, config, compatibility, execution, profile=profile_doc
        ),
        resource_limits={
            "timeout_seconds": profile.timeout_seconds,
            "memory_limit_bytes": profile.memory_limit_bytes,
        },
    )
    routed = route_canonical_artifact(artifact, task.track)
    input_report = validate_routed_input(routed, task).to_document()
    context = DecodeContext.from_routed(
        routed, compatibility, adapter_id=execution.adapter_id, parameters=config.parameters
    )
    return manifest, dataset, descriptor, config, profile, task, routed, input_report, context


def _preflight_binding(
    entry: dict, case: dict, artifact, task, descriptor, routed, context, observed
):
    return {
        "schema_version": "tscb.active-entry-preflight-binding.v1",
        "case_id": case["case_id"],
        "codec_key": entry["codec_key"],
        "task_id": task.task_id,
        "task_sha256": hashlib.sha256(canonical_json_bytes(task.to_document())).hexdigest(),
        "algorithm_id": task.algorithm_id,
        "config_id": task.config_id,
        "profile_id": task.profile_id,
        "dataset_id": task.dataset_id,
        "track": task.track,
        "source_artifact_id": entry["source_artifact_id"],
        "execution_path_hash": task.execution.execution_path_hash,
        "canonical_sha256": artifact.sha256,
        "dataset_content_sha256": artifact.metadata["dataset_content_sha256"],
        "input_sha256": routed.input_sha256,
        "descriptor": descriptor.identity_document(),
        "descriptor_alignment_basis": "SERIALIZED_CANONICAL_BYTE_ALIGNMENT_GUARANTEE",
        "decode_context": context.to_document(),
        "decode_context_sha256": context.sha256,
        "required_external_bits": len(context.serialized) * 8,
        "bitstream_sha256": observed.get("bitstream_sha256"),
        "status": observed.get("status"),
        "binding_scope": "ACTUAL_PREFLIGHT_ARGUMENTS_AND_REPORTED_STREAM_CONTEXT",
        "codec_invoked_by_binding_audit": False,
        "worker_lifecycle_scope": (
            "INDEPENDENT_RECOVERY_SPAWN_WORKER_LIFECYCLE_EXPORTED_IN_DIAGNOSTICS"
        ),
    }


def validate_case_evidence(
    result: dict[str, Any],
    plan: dict[str, Any],
    entry: dict | None = None,
    case: dict | None = None,
    *,
    root: Path = ROOT,
    output: Path | None = None,
    environment: dict | None = None,
) -> None:
    _require(isinstance(plan, dict), "case audit requires the full frozen qualification plan")
    if result.get("plan_id") != plan["plan_id"]:
        raise ValueError("saved case evidence belongs to another frozen plan")
    payload = {key: value for key, value in result.items() if key != "evidence_id"}
    if stable_id("active-entry-qualification-evidence-v32", payload) != result.get("evidence_id"):
        raise ValueError("saved case evidence content/hash mismatch")
    if result.get("preflight") and result.get("acceptance") != preflight_acceptance(
        result["preflight"]
    ):
        raise ValueError("saved case acceptance differs from its recovery/cost/safety proof")
    matches = [
        (e, c)
        for e in plan["entries"]
        for c in e["cases"]
        if c.get("case_id") == result.get("case_id")
    ]
    _require(len(matches) == 1, "saved case is not a unique frozen qualification slot")
    expected_entry, expected_case = matches[0]
    _require(
        (entry is None or entry == expected_entry) and (case is None or case == expected_case),
        "supplied frozen entry/case identity differs",
    )
    entry, case = expected_entry, expected_case
    if not result.get("preflight"):
        _require(
            result.get("acceptance", {}).get("status") != "SCOPED_PASS",
            "missing bound preflight cannot qualify",
        )
        return
    canonical = result.get("canonical") or {}
    path = Path(canonical.get("path", ""))
    path = path if path.is_absolute() else root / path
    _require(
        path.is_file() and sha256(path) == canonical.get("actual_sha256"),
        "saved canonical artifact is missing or its actual hash changed",
    )
    if output is None:
        output = path.resolve().parent.parent
    _require(
        path.resolve() == (output / "datasets" / f"{case['dataset_key']}.tscb").resolve(),
        "canonical artifact is not bound to the planned fixture path",
    )
    if environment is None:
        environment_path = output / "environment.json"
        _require(environment_path.is_file(), "missing frozen qualification environment")
        environment = json.loads(environment_path.read_text())
    artifact = read_canonical(path)
    resolved = _resolve_case(root, entry, case, environment, artifact)
    _, _, descriptor, _, _, task, routed, input_report, context = resolved
    _require(
        canonical_json_bytes(result.get("task")) == canonical_json_bytes(task.to_document()),
        "qualification task algorithm/config/profile/dataset/execution identity differs",
    )
    observed = result["preflight"]
    captured = observed.get("diagnostics", {}).get("qualification_artifacts")
    if captured or result.get("acceptance", {}).get("status") == "SCOPED_PASS":
        _require(
            isinstance(captured, dict),
            "encoded preflight lacks retained actual stream/context artifacts",
        )
        capture_root = output / "qualification_artifacts" / case["case_id"].rsplit(":", 1)[-1]
        _require(
            (capture_root / "binding.json").is_file()
            and json.loads((capture_root / "binding.json").read_bytes()) == captured,
            "retained preflight binding file differs from the saved observation",
        )
        saved = {}
        for name, filename in (("stream", "stream.bin"), ("context", "context.json")):
            item = captured.get(name) or {}
            artifact_path = Path(item.get("path", ""))
            _require(
                artifact_path.resolve() == (capture_root / filename).resolve()
                and artifact_path.is_file()
                and type(item.get("bytes")) is int
                and item["bytes"] == artifact_path.stat().st_size
                and item.get("sha256") == sha256(artifact_path),
                "retained preflight stream/context file identity differs",
            )
            saved[name] = artifact_path.read_bytes()
        expected_binding = {
            "task_id": task.task_id,
            "dataset_id": task.dataset_id,
            "algorithm_id": task.algorithm_id,
            "config_id": task.config_id,
            "execution_path_hash": task.execution.execution_path_hash,
            "track": task.track,
            "input_sha256": routed.input_sha256,
            "canonical_raw_bits": routed.canonical_raw_bits,
            "adapter_id": task.execution.adapter_id,
            "parameters": case["parameters"],
        }
        _require(
            canonical_json_bytes(captured.get("binding")) == canonical_json_bytes(expected_binding),
            "captured preflight task/algorithm/config/input binding differs",
        )
        _require(
            saved["context"] == context.serialized
            and captured["stream"]["sha256"] == observed["bitstream_sha256"],
            "retained preflight stream hash or actual paid recovery context differs",
        )
        ledger = observed.get("accounting") or {}
        _require(
            ledger.get("serialized_bits") == len(saved["stream"]) * 8
            and ledger.get("final_physical_bytes") == len(saved["stream"])
            and ledger.get("external_side_information_bits") == len(saved["context"]) * 8
            and ledger.get("final_bits") == (len(saved["stream"]) + len(saved["context"])) * 8,
            "retained preflight actual stream/context cost does not close",
        )
    if observed.get("input_validation") is not None:
        _require(
            canonical_json_bytes(observed["input_validation"])
            == canonical_json_bytes(input_report),
            "preflight input/shape/dtype/semantic hash differs from the planned fixture",
        )
    binding = _preflight_binding(entry, case, artifact, task, descriptor, routed, context, observed)
    _require(
        canonical_json_bytes(observed.get("run_record")) == canonical_json_bytes(binding),
        "preflight nested task/input/bitstream/context binding differs",
    )
    if result["acceptance"]["status"] == "SCOPED_PASS":
        _require(
            observed.get("input_validation") is not None,
            "accepted preflight lacks original input validation",
        )
        ledger, recovery = observed["accounting"], observed["diagnostics"]["independent_recovery"]
        _require(
            ledger["canonical_raw_bits"] == routed.canonical_raw_bits
            and ledger["track"] == case["track"],
            "preflight ledger original denominator/track differs",
        )
        _require(
            recovery.get("decode_context_sha256") == context.sha256
            and recovery.get("required_external_bits") == len(context.serialized) * 8
            and ledger["external_side_information_bits"] == len(context.serialized) * 8,
            "preflight decoder context/configuration/paid cost differs",
        )
        lifecycle = observed["diagnostics"].get("independent_recovery_worker_lifecycle") or {}
        _require(
            lifecycle.get("start_method") == "spawn"
            and lifecycle.get("worker_exit_confirmed") is True
            and lifecycle.get("exit_code") == 0
            and type(lifecycle.get("worker_pid")) is int
            and lifecycle["worker_pid"] > 0
            and lifecycle["worker_pid"] == recovery.get("worker_pid")
            and lifecycle["worker_pid"] != lifecycle.get("parent_pid"),
            "preflight independent decoder worker lifecycle is unbound or incomplete",
        )


def run_case(
    root: Path, output: Path, entry: dict, case: dict, environment: dict
) -> dict[str, Any]:
    registry = CodecRegistry(root / "registry/codecs", SourceRegistry(root / "registry/sources"))
    manifest = registry.get(entry["codec_key"])
    dataset = load_dataset(
        DatasetRegistry(root / "registry/datasets", root).load(case["dataset_key"])
    )
    canonical = output / "datasets" / f"{case['dataset_key']}.tscb"
    if not canonical.exists():
        write_canonical(dataset, canonical)
    artifact = read_canonical(canonical)
    resolved = _resolve_case(root, entry, case, environment, artifact)
    _, _, descriptor, config, profile, task, routed, _, context = resolved
    preflight, _ = preflight_task(
        task,
        manifest,
        registry.sources.get(manifest.source_artifact_id),
        artifact,
        create_adapter(root, manifest),
        config.parameters,
        cpu_affinity=profile.cpu_affinity,
        capture_directory=output / "qualification_artifacts" / case["case_id"].rsplit(":", 1)[-1],
    )
    observed = preflight.to_document()
    observed["run_record"] = _preflight_binding(
        entry, case, artifact, task, descriptor, routed, context, observed
    )
    return {
        "schema_version": "tscb.active-entry-qualification-evidence.v3.2",
        "case_id": case["case_id"],
        "codec_key": manifest.key,
        "canonical": file_evidence(root, canonical),
        "task": task.to_document(),
        "preflight": observed,
        "acceptance": preflight_acceptance(observed),
        "performance_eligible": False,
    }


def build_matrices(plan: dict, results: dict[str, dict]) -> dict[str, Any]:
    matrices = {name: [] for name in MATRIX_NAMES}
    for entry in plan["entries"]:
        common = {
            "codec_key": entry["codec_key"],
            "algorithm_id": entry["algorithm_id"],
            "source_artifact_id": entry["source_artifact_id"],
            "plan_id": plan["plan_id"],
        }
        matrices["SourceCapabilityMatrix"].append(
            {
                **common,
                "declaration": entry["declared_domain"],
                "evidence": entry["source"],
                "state": entry["source"]["source_domain_validation"],
            }
        )
        matrices["StandalonePortMatrix"].append(
            {
                **common,
                "declaration": entry["declared_adapter_domain"],
                "evidence": entry["standalone"],
                "state": "UNKNOWN_NOT_REEXECUTED",
            }
        )
        for case in entry["cases"]:
            result = results.get(case.get("case_id"), {})
            state = result.get("acceptance", {}).get("status", "NOT_RUN")
            evidence = result.get("evidence_file")
            matrices["BenchProfileMatrix"].append(
                {
                    **common,
                    "case": case,
                    "evidence": evidence,
                    "state": state,
                    "preflight": result.get("preflight"),
                    "acceptance": result.get("acceptance"),
                    "formal_performance": "NOT_GRANTED_BY_QUALIFICATION",
                    "declared_features": entry["declared_features"],
                    "independent_query_stream_profile": "NOT_RUN_BY_OBJECT_PREFLIGHT",
                    "declared_execution": entry["declared_execution"],
                }
            )
            task = result.get("task", {})
            matrices["PipelineCoverageMatrix"].append(
                {
                    **common,
                    "case_id": case.get("case_id"),
                    "track": case["track"],
                    "state": state,
                    "evidence": evidence,
                    "compatibility": case.get("compatibility"),
                    "preprocess": task.get("preprocess"),
                    "independent_recovery": result.get("preflight", {})
                    .get("diagnostics", {})
                    .get("independent_recovery"),
                    "accounting": result.get("preflight", {}).get("accounting"),
                    "unexecuted_pipeline_recipes": "UNKNOWN_NOT_PROMOTED",
                }
            )
    return {
        "schema_version": "tscb.four-capability-matrices.v3.2",
        "plan_id": plan["plan_id"],
        "performance_claim": False,
        "matrices": matrices,
    }


def execute(plan: dict, root: Path, output: Path) -> dict[str, Any]:
    validate_frozen(plan, root)
    environment_path = output / "environment.json"
    if environment_path.exists():
        environment = json.loads(environment_path.read_text())
    else:
        environment = capture_environment()
        write_json(environment_path, environment)
    results = {}
    for entry in plan["entries"]:
        for case in entry["cases"]:
            if "case_id" not in case:
                continue
            path = output / "cases" / (case["case_id"].rsplit(":", 1)[-1] + ".json")
            if path.exists():
                result = json.loads(path.read_text())
                validate_case_evidence(
                    result, plan, entry, case, root=root, output=output, environment=environment
                )
            else:
                if entry["source"]["closure_status"] == "DRIFT" or entry.get(
                    "artifact_resolution_error"
                ):
                    result = {
                        "case_id": case["case_id"],
                        "acceptance": {"status": "NOT_ACCEPTED"},
                        "reason": "ARTIFACT_RESOLUTION_FAILED"
                        if entry.get("artifact_resolution_error")
                        else "SOURCE_CLOSURE_HASH_DRIFT",
                        "artifact_resolution_error": entry.get("artifact_resolution_error"),
                    }
                else:
                    limits = case["profile"]
                    with ResourceLease(
                        run_set_id=output.name + "-active-qualification",
                        logical_cpus=tuple(limits["cpu_affinity"]),
                        threads=limits["threads"],
                        memory_limit_bytes=limits["memory_limit_bytes"],
                    ) as lease:
                        before = lease.to_document()
                        started = time.perf_counter_ns()
                        try:
                            result = run_case(root, output, entry, case, environment)
                        except Exception as error:
                            result = {
                                "case_id": case["case_id"],
                                "acceptance": {"status": "NOT_ACCEPTED"},
                                "reason": "QUALIFICATION_DRIVER_EXCEPTION",
                                "error_type": type(error).__name__,
                                "message": str(error),
                            }
                        result.update(
                            started_ns=started,
                            finished_ns=time.perf_counter_ns(),
                            lease_before=before,
                            lease_after=lease.to_document(),
                            resource_budget={
                                **case["resource_budget"],
                                "observed_owner_affinity": sorted(os.sched_getaffinity(0)),
                                "affinity_scope": "LEASE_OWNER_AND_INHERITING_WORKERS",
                            },
                        )
                validate_frozen(plan, root)
                result["plan_id"] = plan["plan_id"]
                result["evidence_id"] = stable_id("active-entry-qualification-evidence-v32", result)
                validate_case_evidence(
                    result, plan, entry, case, root=root, output=output, environment=environment
                )
                write_json(path, result)
            result["evidence_file"] = file_evidence(root, path)
            results[case["case_id"]] = result
            print(
                json.dumps(
                    {
                        "codec_key": entry["codec_key"],
                        "track": case["track"],
                        "status": result["acceptance"]["status"],
                    }
                ),
                flush=True,
            )
    matrices = build_matrices(plan, results)
    write_json(output / "four_matrices.json", matrices)
    statuses = Counter(result["acceptance"]["status"] for result in results.values())
    expected = sum(len(entry["cases"]) for entry in plan["entries"])
    summary = {
        "schema_version": "tscb.active-entry-qualification-summary.v3.2",
        "plan_id": plan["plan_id"],
        "active_entry_count": len(plan["active_keys"]),
        "selected_entry_count": len(plan["selected_keys"]),
        "expected_track_cases": expected,
        "observed_track_cases": len(results),
        "status_counts": dict(statuses),
        "status": "SCOPED_QUALIFICATION_COMPLETE"
        if len(results) == expected and statuses.get("SCOPED_PASS", 0) == expected
        else "INCOMPLETE_OR_FAILED",
        "entire_active_scope_selected": plan["selected_keys"] == plan["active_keys"],
        "performance_claim": False,
        "full_source_domain_claim": False,
        "matrices": file_evidence(root, output / "four_matrices.json"),
    }
    write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu", type=int, default=min(os.sched_getaffinity(0)))
    parser.add_argument("--model-cpus", type=int, nargs=3, default=[0, 2, 4])
    parser.add_argument("--keys", nargs="+")
    parser.add_argument("--resume", action="store_true")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--plan-only", action="store_true")
    action.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    plan_path = output / "plan.json"
    if plan_path.exists():
        if not args.resume:
            parser.error("output already has a frozen plan; use --resume or a new output")
        plan = json.loads(plan_path.read_text())
        if (
            args.cpu != plan["cpu"]
            or args.model_cpus != plan["model_cpus"]
            or (args.keys and sorted(args.keys) != plan["selected_keys"])
        ):
            parser.error("resume CPU/selected keys differ from the frozen plan")
        validate_frozen(plan, ROOT)
    else:
        plan = build_plan(ROOT, args.cpu, args.keys, tuple(args.model_cpus))
        write_json(plan_path, plan)
        write_json(
            output / "role_ledger.json",
            {"plan_id": plan["plan_id"], "entries": plan["role_ledger"]},
        )
    if args.execute:
        summary = execute(plan, ROOT, output)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        if summary["status"] != "SCOPED_QUALIFICATION_COMPLETE":
            raise SystemExit(1)
    else:
        write_json(output / "four_matrices.json", build_matrices(plan, {}))
        print(
            json.dumps(
                {
                    "status": "PLAN_ONLY_NOT_QUALIFIED",
                    "plan_id": plan["plan_id"],
                    "selected_entries": len(plan["entries"]),
                    "planned_track_cases": sum(len(e["cases"]) for e in plan["entries"]),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
