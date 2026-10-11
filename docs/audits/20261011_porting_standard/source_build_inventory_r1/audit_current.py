"""Snapshot current registrations and real factory dependency hash checks.

This read-only inventory does not execute codecs, build source oracles, grant
G0-G6, or import historical qualification as current acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from qualify_v32_active_entries import active_keys, source_evidence  # noqa: E402

from tscompbench.adapters import adapter_artifacts  # noqa: E402
from tscompbench.codecs import CodecRegistry, SourceRegistry  # noqa: E402


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def reference(path: Path) -> dict:
    return {"path": str(path), "sha256": sha(path)}


def frozen_registration() -> list[dict]:
    paths = [ROOT / "registry/algorithm_scope.json"]
    for directory in ("codecs", "sources", "onboarding"):
        paths += sorted((ROOT / "registry" / directory).rglob("*.json"))
    return [reference(path) for path in paths]


def lzss_source_oracle_relation(report_path: Path, artifact: Path, current_record: dict) -> dict:
    """Associate an explicitly measured older path without rewriting its report."""
    report = json.loads(report_path.read_text())
    measured = Path(report["library"]["path"])
    measured_sha = sha(measured)
    if measured_sha != report["library"]["sha256"]:
        raise RuntimeError("measured LZSS library drifted from source-oracle report")
    measured_record_path = measured.parent / "build-record.json"
    measured_record = json.loads(measured_record_path.read_text())
    if measured_record["artifact_sha256"] != measured_sha:
        raise RuntimeError("measured LZSS build record differs from the reported artifact")
    measured_closure = {
        entry["path"]: entry["sha256"] for entry in measured_record["compiled_source_closure"]
    }
    current_closure = {
        entry["path"]: entry["sha256"] for entry in current_record["compiled_source_closure"]
    }
    sources = []
    for relative in (
        "adapters/lzss_raw/native/lzss_raw_codec.cc",
        "adapters/lzss_raw/native/lzss_raw_codec.h",
        "adapters/lzss_raw/native/tscb_lzss_raw.cc",
    ):
        actual = sha(ROOT / relative)
        previous, current = measured_closure.get(relative), current_closure.get(relative)
        if previous != actual or current != actual:
            raise RuntimeError("LZSS measured/current compiled core or shim differs: " + relative)
        sources.append(
            {
                "path": relative,
                "measured_build_sha256": previous,
                "current_build_sha256": current,
                "actual_sha256": actual,
            }
        )
    current_sha = sha(artifact)
    return {
        "source_oracle_report": reference(report_path),
        "source_oracle_scope": report["scope"],
        "measured_library": reference(measured),
        "measured_build_record": reference(measured_record_path),
        "current_registered_library": reference(artifact),
        "current_registered_path_was_direct_oracle_target": measured.resolve()
        == artifact.resolve(),
        "shared_library_byte_equality": measured_sha == current_sha,
        "compiled_core_and_shim_sources": sources,
        "relation_scope": "ACTUAL_ARTIFACT_BYTE_AND_DECLARED_COMPILED_SOURCE_ASSOCIATION",
        "current_benchmark_python_wrapper_qualification": "NOT_GRANTED_BY_LOW_LEVEL_SOURCE_ORACLE",
        "full_native_capability_parity": "NOT_GRANTED",
        "complete_n1_build_link_trace": "NOT_GRANTED",
        "historical_source_oracle_report_rewritten": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-report", type=Path, action="append", default=[])
    parser.add_argument("--lzss-oracle-report", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("existing evidence must be preserved: " + str(args.output))
    before = frozen_registration()
    sources = SourceRegistry(ROOT / "registry/sources")
    registry = CodecRegistry(ROOT / "registry/codecs", sources)
    rows = []
    for key in active_keys(ROOT, registry):
        manifest = registry.get(key)
        source = sources.get(manifest.source_artifact_id)
        row = {
            "codec_key": key,
            "algorithm_id": manifest.algorithm_id,
            "source_artifact_id": manifest.source_artifact_id,
            "source_kind": source.get("kind"),
            "adapter_factory": manifest.document["adapter"].get("factory"),
            "implementation_class": manifest.document["classification"]["implementation_class"],
            "source_inventory": source_evidence(ROOT, source),
            "source_semantic_parity": "NOT_GRANTED_BY_FILE_HASH_INVENTORY",
            "standalone_g0_g6": "NOT_GRANTED_BY_THIS_INVENTORY",
            "bench_profile_qualification": "NOT_EXECUTED_BY_THIS_INVENTORY",
            "formal_performance": "NOT_EXECUTED_BY_THIS_INVENTORY",
        }
        try:
            artifact, dependencies = adapter_artifacts(ROOT, manifest)
            row["registered_execution_dependencies"] = {
                "status": "CURRENT_DECLARED_HASHES_VERIFIED_BY_ACTUAL_ADAPTER_FACTORY",
                "scope": "DECLARED_DEPENDENCY_HASHES_NOT_UNDECLARED_BUILD_CLOSURE_PROOF",
                "artifact": reference(artifact),
                "dependencies": [reference(path) for path in dependencies],
            }
            record_path = artifact.parent / "build-record.json"
            record = json.loads(record_path.read_text())
            row["declared_build_closure"] = {
                "build_record": reference(record_path),
                "compiler_closure_file_count": len(record.get("compiled_source_closure", [])),
                "compiler_depfile_count": len(record.get("compiler_dependency_files", [])),
                "toolchain_file_count": len(record.get("toolchain_files", [])),
                "toolchain_program_count": len(record.get("toolchain_programs", [])),
                "runtime_file_count": len(record.get("runtime_dependencies", [])),
                "declared_ctest_test_count": len(record.get("ctest_tests", [])),
                "actual_compiler_dependency_universe_recomputed_by_this_inventory": False,
                "complete_n1_compile_and_link_trace": "UNKNOWN_DECLARED_HASH_INVENTORY_ONLY",
            }
            if key == "lzss-raw" and args.lzss_oracle_report is not None:
                row["source_oracle_current_artifact_relation"] = lzss_source_oracle_relation(
                    args.lzss_oracle_report.resolve(), artifact, record
                )
        except Exception as error:
            row["registered_execution_dependencies"] = {
                "status": "FAIL_CURRENT_DEPENDENCY_CHECK",
                "error_type": type(error).__name__,
                "error": str(error),
            }
        rows.append(row)
    after = frozen_registration()
    if before != after:
        raise RuntimeError("registration changed during snapshot; retain no final inventory")
    report = {
        "schema_version": "tscb.current-source-build-inventory.v1",
        "created_at": datetime.now(UTC).isoformat(),
        "root": str(ROOT),
        "driver": reference(Path(__file__)),
        "active_codec_count": len(rows),
        "registration_snapshot": after,
        "source_inventory_status_counts": dict(
            Counter(row["source_inventory"]["closure_status"] for row in rows)
        ),
        "execution_dependency_status_counts": dict(
            Counter(row["registered_execution_dependencies"]["status"] for row in rows)
        ),
        "referenced_evidence_reports": [reference(path.resolve()) for path in args.evidence_report],
        "referenced_evidence_semantic_status_promoted": False,
        "historical_evidence_rewritten": False,
        "full_parity_granted": False,
        "rewrite_done_granted": False,
        "formal_granted": False,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "active_codec_count",
                    "source_inventory_status_counts",
                    "execution_dependency_status_counts",
                )
            },
            indent=2,
        )
    )
    raise SystemExit(
        any(
            row["registered_execution_dependencies"]["status"].startswith("FAIL")
            or row["source_inventory"]["closure_status"] == "DRIFT"
            for row in rows
        )
    )


if __name__ == "__main__":
    main()
