"""Write the final review from current qualified standalone and Benchmark evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from tscompbench.codecs import CodecRegistry, SourceRegistry

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(path):
    return {"path": str(path.relative_to(ROOT)), "sha256": sha(path)}


def read_pass(path):
    document = json.loads(path.read_text())
    assert document["status"] == "PASS", path
    return document


def main():
    review_path = ROOT / "docs/requested_lossless_rewrite_review.json"
    previous = json.loads(review_path.read_text())
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    frozen_path = ROOT / "adapters/rewrite_lossless/FROZEN_APIS.json"
    lock = json.loads(frozen_path.read_text())
    release_path = (
        ROOT / "Compression_Rewrite/Release/requested-lossless-20261006/RELEASE_INDEX.json"
    )
    releases = json.loads(release_path.read_text())["deliveries"]
    deliveries = {entry["algorithm"]: entry for entry in releases}
    benchmark_path = ROOT / "docs/requested_lossless_benchmark_qualification.json"
    benchmark = read_pass(benchmark_path)
    native_path = ROOT / "docs/requested_lossless_native_abi_qualification.json"
    native = read_pass(native_path)
    assert native["frozen_lock_sha256"] == sha(frozen_path)
    consumption_path = ROOT / "docs/requested_lossless_release_consumption.json"
    consumption = read_pass(consumption_path)
    assert consumption["release_index_sha256"] == sha(release_path)
    assert consumption["frozen_lock_sha256"] == sha(frozen_path)
    pytest_log = ROOT / "build/rewrite_review/final-pytest.log"
    match = re.search(r"(\d+) passed in ([\d.]+)s", pytest_log.read_text())
    assert match and "failed" not in pytest_log.read_text()
    results = []
    for name in previous["scope"]:
        pkg = lock["algorithms"][name]["package"]
        package = ROOT / "Compression_Rewrite/ReWrite" / pkg
        current = package / "validation/current/report.json"
        qualification = read_pass(current)
        differential = package / (
            "validation/original-public-api/report.json"
            if pkg == "prometheus-xor-chunk"
            else "validation/differential/report.json"
        )
        read_pass(differential)
        codec = registry.get(name)
        records = []
        task_count = 0
        for group in benchmark["groups"]:
            run = ROOT / group["run_path"]
            rows = [
                json.loads(line) for line in (run / "run_components.jsonl").read_text().splitlines()
            ]
            matching = [row for row in rows if row["algorithm_id"] == codec.algorithm_id]
            for row in matching:
                assert row["status"] == row["correctness"]["status"] == "PASS"
                assert row["timing"]["timing_scope"] == "PIPELINE"
                assert row["eligibility"] is False
            task_count += len(matching)
            if matching:
                records.append(evidence(run / "run_components.jsonl"))
        assert task_count == 3, (name, task_count)
        delivery = deliveries[pkg]
        result = {
            "key": name,
            "package": pkg,
            "rewrite_status": "REWRITE_DONE",
            "benchmark_integration_status": "PASS",
            "source_commit": delivery["source_commit"],
            "algorithm_id": codec.algorithm_id,
            "source_artifact_id": codec.source_artifact_id,
            "source_oracle_cases_per_package": delivery["all_cases"],
            "dataset_cases_per_package": delivery["dataset_cases"],
            "oracle_dataset_selection": "ALL_ROWS_ALL_VALUE_COLUMNS_OF_FOUR_CSV_FILES"
            if (pkg == "prometheus-xor-chunk")
            else "FIRST_1000_ROWS_EVERY_VALUE_COLUMN_OF_THREE_CSV_FILES; binary32/64",
            "standalone_qualification": evidence(current),
            "differential": evidence(differential),
            "declared_platforms": qualification["declared_platforms"],
            "port_manifest": evidence(package / "PORT_MANIFEST.yaml"),
            "sbom": evidence(package / "SBOM.json"),
            "archive": delivery["archive"],
            "native_abi_status": "PASS",
            "onboarding": evidence(ROOT / "registry/onboarding" / (name + ".json")),
            "benchmark_tasks": task_count,
            "benchmark_records": records,
            "value_domain": codec.document["input"].get(
                "value_domain", "IEEE_BITS_AND_INT64_MODULAR_TIMESTAMPS"
            ),
            "license_spdx": registry.sources.get(codec.source_artifact_id)["license"]["spdx"],
        }
        results.append(result)
    review = {
        "status": "COMPLETE_LOCAL_SCOPE",
        "review_date": "2026-10-06",
        "scope": previous["scope"],
        "skipped_by_user": previous["skipped_by_user"],
        "inputs": previous["inputs"],
        "document_instruction_precedence": (
            "The user's integration request authorizes separate Benchmark "
            "adapters/registry changes; "
            "the document's rewrite-only boundary still governs standalone packages. "
            "The explicit local license exception covers Elf/Elf+/Elf*/SElf*."
        ),
        "aliases": [
            item
            for item in registry.alias_documents()
            if item["canonical_key"] == "prometheus-xor-chunk"
        ],
        "results": results,
        "unique_standalone_packages": len(deliveries),
        "independent_registered_identities": len(results),
        "validation": {
            "pytest_passed": int(match[1]),
            "pytest_log": evidence(pytest_log),
            "benchmark_qualification": evidence(benchmark_path),
            "benchmark_tasks_passed": 21,
            "native_abi": evidence(native_path),
            "release_consumption": evidence(consumption_path),
            "frozen_apis": evidence(frozen_path),
            "release_index": evidence(release_path),
        },
        "known_limits": [
            "Qualification performance records do not enter formal rankings; PIPELINE only",
            "Linux x86_64 GCC11/Clang14 only; no ARM/Windows/macOS verification claim",
            "ASan/UBSan passed, detect_leaks=0; no leak-clean claim",
            "Elf family NOASSERTION, user-authorized local workflow only; no external publication",
            "Source-domain failure is bounded rejection, never raw fallback",
            "Chimp/Chimp128 share one standalone package and its combined oracle case counts",
        ],
        "preserved_diagnostics": [
            {
                "path": "runs/requested-lossless-value-20261006-final-v2",
                "reason": (
                    "Two RESOURCE_PRESSURE measurements caused by SYSTEM_VMSTAT swap observation; "
                    "preflight passed. Preserved and excluded from final qualification evidence."
                ),
            },
            {
                "path": "runs/requested-lossless-value-20261006-final-v5",
                "reason": (
                    "Four SYSTEM_VMSTAT swap observations invalidated timing; "
                    "all preflights passed. "
                    "Preserved and excluded from final qualification evidence."
                ),
            },
            {
                "path": "runs/requested-lossless-value-20261006-final",
                "reason": (
                    "Initial boundary contract diagnostics; retained after role-dtype "
                    "and source-domain fixes."
                ),
            },
        ],
        "source_closure_restoration": [
            evidence(
                ROOT
                / "Compression_Rewrite/Source"
                / pkg
                / "SOURCE_CLOSURE_RESTORATION_20261006.json"
            )
            for pkg in ["elf-plus", "self-star"]
        ],
        "user_decisions": evidence(ROOT / "Compression_Rewrite/USER_DECISIONS.md"),
    }
    review_path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n")
    print("final review COMPLETE_LOCAL_SCOPE", len(results), "identities", match[1], "tests")


if __name__ == "__main__":
    main()
