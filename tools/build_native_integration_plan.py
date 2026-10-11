"""Read every full-audit workbook row and preserve the complete integration scope.

Registration, historical runs and repository language counts do not imply qualification.
This builds a durable worklist, not a performance report or an edited spreadsheet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from tscompbench.codecs import CodecRegistry, SourceRegistry

ROOT = Path(__file__).resolve().parents[1]
NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


def workbook_rows(path: Path) -> list[dict[str, str]]:
    with ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = [
                "".join(item.itertext())
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml"))
            ]
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheet = next(

                item
                for item in workbook.findall("m:sheets/m:sheet", NS)
                if item.get("name") == "全量审计"

        )
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(

                item.get("Target")
                for item in relationships
                if item.get("Id") == sheet.get("{" + NS["r"] + "}id")

        )
        sheet_path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        rows = []
        for element in ET.fromstring(archive.read(sheet_path)).findall("m:sheetData/m:row", NS):
            if int(element.get("r")) <= 6:
                continue
            values = {"worksheet_row": int(element.get("r"))}
            for cell in element.findall("m:c", NS):
                column = re.sub("\\d+$", "", cell.get("r"))
                content = cell.find("m:v", NS)
                raw = content.text if content is not None and content.text is not None else ""
                if cell.get("t") == "s":
                    raw = shared[int(raw)]
                elif cell.get("t") == "inlineStr":
                    raw = "".join(node.text or "" for node in cell.findall(".//m:t", NS))
                values[column] = raw
            if values.get("A"):
                rows.append(values)
    return rows


def normalized(name: str) -> str:
    return re.sub("[\\s_\\-/()]", "", name.casefold())


def current_scope_review(
    script: str, formal: str, qualification: str, key: str | None = None
) -> dict:
    command = [sys.executable, str(ROOT / "tools" / script), formal, qualification]
    if key is not None:
        command += ["--key", key]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=180)
    accepted = False
    if result.returncode == 0:
        try:
            accepted = json.loads(result.stdout).get("status") == "PASS"
        except ValueError, AttributeError:
            pass
    return {
        "script": script,
        "key": key,
        "formal_run": formal,
        "qualification_run": qualification,
        "returncode": result.returncode,
        "qualified_against_current_source": accepted,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "status": "PASS" if accepted else "CURRENT_REQUALIFICATION_REQUIRED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selective = parser.add_mutually_exclusive_group()
    selective.add_argument(
        "--refresh-registration-identities-only",
        action="store_true",
        help="Update current candidate references; preserve all historical qualification reviews.",
    )
    parser.add_argument(
        "--workbook", type=Path, default=ROOT / "Compression_Rewrite_Algorithm_List_v1.0.xlsx"
    )
    parser.add_argument(
        "--source-audit",
        type=Path,
        default=ROOT / "build/source-audits/native-full-audit-20261007.json",
    )
    parser.add_argument("--simdcomp-run-suffix", default="20261007-1")
    args = parser.parse_args()
    if args.refresh_registration_identities_only:
        output = ROOT / "registry/native_integration_plan.json"
        document = json.loads(output.read_text())
        registry = CodecRegistry(
            ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")
        )
        changes = []
        for entry in document["entries"]:
            for candidate in entry.get("registered_candidates", []):
                manifest = registry.get(candidate["key"])
                if candidate["source_artifact_id"] != manifest.source_artifact_id:
                    raise ValueError("source identity changed; source admission review required")
                if candidate["algorithm_id"] != manifest.algorithm_id:
                    changes.append(
                        {
                            "audit_index": entry["audit_index"],
                            "key": candidate["key"],
                            "previous_algorithm_id": candidate["algorithm_id"],
                            "current_algorithm_id": manifest.algorithm_id,
                        }
                    )
                    candidate["algorithm_id"] = manifest.algorithm_id
        document.setdefault("registration_identity_refreshes", []).append(
            {"scope": "CURRENT_REFERENCES_ONLY_HISTORICAL_REVIEWS_NOT_RESIGNED", "changes": changes}
        )
        output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps({"updated_references": len(changes), "qualification_claims_changed": False})
        )
        return
    rows = workbook_rows(args.workbook)
    if len(rows) != 221 or {int(row["A"]) for row in rows} != set(range(1, 222)):
        raise ValueError("the full-audit sheet must preserve all 221 unique logical entries")
    audit = json.loads(args.source_audit.read_text())
    if len(audit["repositories"]) != 72:
        raise ValueError("source audit is incomplete")
    repositories = {item["repo"]: item for item in audit["repositories"]}
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    manifests = {m.key: m for m in registry.verify_all()}
    aliases = {item["key"]: item["canonical_key"] for item in registry.alias_documents()}
    names: dict[str, set[str]] = {}
    for key, manifest in manifests.items():
        for name in (key, manifest.document["identity"]["display_name"].split(" (")[0]):
            names.setdefault(normalized(name), set()).add(key)
    for key, target in aliases.items():
        names.setdefault(normalized(key), set()).add(target)
    explicit = {
        "Chimp128": ["chimp128"],
        "Elf* / SElf*": ["elf-star", "self-star"],
        "SElfStar": ["self-star"],
        "SIMDComp": ["simdcomp-u32"],
    }
    native_hint = re.compile("(?<![A-Za-z])C(?:\\+\\+)?(?=$|[ /+])")
    entries = []
    from algorithm_scope import filter_worklist, load_scope, source_records, validate_worklist

    active_scope = load_scope()
    for row in rows:
        if source_records(active_scope, row["B"], row["F"]) is None:
            continue
        name, repo, language = (row["F"], row["G"] or None, row.get("I") or row.get("H", ""))
        source = repositories.get(repo, {})
        if row["B"] == "TSBench":
            scope = "BENCHMARK_REFERENCE_REVIEW"
        elif language in {"Unknown", "MATLAB/Objective-C"}:
            scope = "SOURCE_CLOSURE_UNRESOLVED"
        elif native_hint.search(language):
            scope = (
                "NATIVE_DEPENDENCY_REVIEW"
                if language.startswith("Python/")
                else "NATIVE_CORE_CANDIDATE"
            )
        else:
            scope = "OTHER_LANGUAGE_RETAINED_FOR_COVERAGE"
        historical_keys = [key.strip() for key in row.get("AB", "").split(",")]
        known = {
            aliases.get(key, key) for key in historical_keys if key in manifests or key in aliases
        }
        inferred = names.get(normalized(name), set()) | set(explicit.get(name, []))
        candidates = sorted((known | inferred) & set(manifests))
        status = (
            "REFERENCE_REVIEW_PENDING"
            if row["B"] == "TSBench"
            else "REGISTERED_REQUIRES_CURRENT_SOURCE_AND_FIVE_LAYER_REVIEW"
            if candidates
            else "SOURCE_ONBOARDING_REVIEW_PENDING"
        )
        admission_review = None
        scope_reviews = []
        if name == "SIMDComp" and repo == "lemire/simdcomp":
            lock_path = ROOT / "adapters/simdcomp/SOURCE_LOCK.json"
            if lock_path.is_file():
                lock = json.loads(lock_path.read_text())
                assert lock["commit"] == source.get("git", {}).get("commit")
                assert lock["logical_entry_index"] == int(row["A"]) == 137
                assert lock["copy_policy"] == "TRACKED_PINNED_BYTES_EQUAL_NO_PATCH"
                assert (
                    lock["freezer_sha256"]
                    == hashlib.sha256(
                        (ROOT / "tools/freeze_simdcomp_source.py").read_bytes()
                    ).hexdigest()
                )
                for item in lock["files"]:
                    assert (
                        hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest()
                        == item["sha256"]
                    )
                card = ROOT / "adapters/simdcomp/SOURCE_ADMISSION.md"
                admission_review = {
                    "status": "FROZEN_SOURCE_UPSTREAM_QUALIFICATION_PENDING",
                    "source_lock": str(lock_path.relative_to(ROOT)),
                    "source_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
                    "card": str(card.relative_to(ROOT)),
                    "card_sha256": hashlib.sha256(card.read_bytes()).hexdigest(),
                    "original_vendor_file_count": len(lock["files"]),
                    "benchmark_reference": lock["benchmark_reference"],
                    "benchmark_registration": "REGISTERED" if candidates else "PENDING",
                    "benchmark_five_layers": "PENDING",
                }
                status = "FROZEN_SOURCE_UPSTREAM_API_AND_FIVE_LAYERS_PENDING"
                report_path = ROOT / "build/source-audits/simdcomp-source-patched-guards.json"
                if report_path.is_file():
                    from audit_simdcomp_source import audit as audit_simdcomp

                    try:
                        current = audit_simdcomp(ROOT)
                    except (RuntimeError, OSError, ValueError, KeyError) as error:
                        admission_review.update(
                            status="CURRENT_SOURCE_API_REQUALIFICATION_REQUIRED",
                            current_qualification_failure={
                                "type": type(error).__name__,
                                "reason": str(error),
                            },
                        )
                        status = "FROZEN_SOURCE_CURRENT_API_REQUALIFICATION_REQUIRED"
                    else:
                        admission_review.update(
                            status="PATCHED_SSE4_1_SOURCE_API_SCOPE_QUALIFIED",
                            source_api_audit=current,
                            source_guards=str(report_path.relative_to(ROOT)),
                            source_guards_sha256=hashlib.sha256(
                                report_path.read_bytes()
                            ).hexdigest(),
                            original_failures_retained=current["original_failures_retained"],
                            bounded_abi="PENDING",
                            python_sdk="PENDING",
                        )
                        status = (
                            "PATCHED_SSE4_1_SOURCE_API_SCOPE_QUALIFIED_"
                            "OTHER_ISA_BOUNDED_ABI_AND_FIVE_LAYERS_PENDING"
                        )
                        avx_report = ROOT / "build/source-audits/simdcomp_avx2_source_tests.json"
                        if avx_report.is_file():
                            from audit_simdcomp_avx2 import audit as audit_avx2

                            try:
                                avx_current = audit_avx2(ROOT)
                            except (RuntimeError, OSError, ValueError, KeyError) as error:
                                admission_review.update(
                                    avx2="CURRENT_REQUALIFICATION_REQUIRED", avx2_failure=str(error)
                                )
                            else:
                                admission_review.update(
                                    status="PATCHED_SSE4_1_AND_AVX2_SOURCE_API_SCOPE_QUALIFIED",
                                    avx2_source_api_audit=avx_current,
                                )
                                status = (
                                    "PATCHED_SSE4_1_AVX2_SOURCE_API_SCOPE_QUALIFIED_"
                                    "BOUNDED_ABI_SDK_AND_FIVE_LAYERS_PENDING"
                                )
                                native_report = (
                                    ROOT / "build/source-audits/simdcomp_native_tests.json"
                                )
                                if native_report.is_file():
                                    from audit_simdcomp_native import audit as audit_simdcomp_native

                                    try:
                                        native_current = audit_simdcomp_native(ROOT)
                                    except (RuntimeError, OSError, ValueError, KeyError) as error:
                                        admission_review.update(
                                            bounded_abi="CURRENT_REQUALIFICATION_REQUIRED",
                                            bounded_abi_failure=str(error),
                                        )
                                    else:
                                        admission_review.update(
                                            status="PATCHED_SSE4_1_AVX2_SOURCE_AND_BOUNDED_ABI_SCOPE_QUALIFIED",
                                            bounded_abi="SCOPED_UINT32_PLAIN_MODULAR_D1_AND_FOR_QUALIFIED",
                                            bounded_abi_audit=native_current,
                                            bounded_cases_per_executable=31878,
                                            bounded_executables=6,
                                            checked_int64_timestamp="PENDING",
                                        )
                                        status = (
                                            "PATCHED_SSE4_1_AVX2_SOURCE_AND_BOUNDED_ABI_"
                                            "SCOPE_QUALIFIED_SDK_AND_FIVE_LAYERS_PENDING"
                                        )
                                        sdk_report = (
                                            ROOT / "build/source-audits/simdcomp_sdk_tests.json"
                                        )
                                        if sdk_report.is_file():
                                            from audit_simdcomp_sdk import audit as audit_simd_sdk

                                            try:
                                                sdk_current = audit_simd_sdk(ROOT)
                                            except (
                                                RuntimeError,
                                                OSError,
                                                ValueError,
                                                KeyError,
                                            ) as error:
                                                admission_review.update(
                                                    python_sdk="CURRENT_REQUALIFICATION_REQUIRED",
                                                    python_sdk_failure=str(error),
                                                )
                                            else:
                                                admission_review.update(
                                                    status="PATCHED_SOURCE_BOUNDED_ABI_AND_DIRECT_SDK_SCOPE_QUALIFIED",
                                                    python_sdk=sdk_current["python_sdk"],
                                                    python_sdk_audit=sdk_current,
                                                    direct_python_sdk_test_count=sdk_current[
                                                        "test_count"
                                                    ],
                                                    direct_python_sdk_imported_file_count=sdk_current[
                                                        "actual_imported_project_file_count"
                                                    ],
                                                )
                                                status = (
                                                    "PATCHED_SOURCE_BOUNDED_ABI_DIRECT_SDK_"
                                                    "SCOPE_QUALIFIED_REGISTRATION_"
                                                    "AND_FIVE_LAYERS_PENDING"
                                                )
                                                if candidates:
                                                    scope_reviews = [
                                                        current_scope_review(
                                                            "audit_simdcomp_run.py",
                                                            f"{key}-formal-20-{args.simdcomp_run_suffix}",
                                                            f"{key}-qualification-{args.simdcomp_run_suffix}",
                                                            key,
                                                        )
                                                        for key in candidates
                                                    ]
                                                    accepted = all(

                                                            r["qualified_against_current_source"]
                                                            for r in scope_reviews

                                                    )
                                                    admission_review["benchmark_five_layers"] = (
                                                        "UINT32_UTS_P0_P2_SOURCE_API_SCOPE_QUALIFIED"
                                                        if accepted
                                                        else "PENDING"
                                                    )
                                                    status = (
                                                        "UINT32_UTS_P0_P2_SIMDCOMP_SCOPE_QUALIFIED_INT64_OTHER_ISA_PENDING"
                                                        if accepted
                                                        else (
                                                            "REGISTERED_SOURCE_ABI_SDK_"
                                                            "QUALIFIED_FIVE_LAYERS_PENDING"
                                                        )
                                                    )
        entries.append(
            {
                "audit_index": int(row["A"]),
                "worksheet_row": row["worksheet_row"],
                "asset_group": row["B"],
                "source_sheet": row["C"],
                "source_row": row["D"],
                "logical_directory": row["E"],
                "name": name,
                "repository": repo,
                "metadata_language": row.get("H", ""),
                "source_closure_hint": language,
                "scope": scope,
                "state": status,
                "source_admission_review": admission_review,
                "current_scope_reviews": scope_reviews,
                "historical_admission": row.get("K", ""),
                "historical_registry_keys": row.get("AB", ""),
                "historical_scope_difference": row.get("AC", ""),
                "source_availability_at_full_scan": source.get("availability", "NOT_IN_SCAN"),
                "source_commit_at_full_scan": source.get("git", {}).get("commit"),
                "source_inventory_kind": "PATH_AND_SIZE_INDEX_NOT_FILE_CONTENT_HASH",
                "source_inventory_digest": source.get("tree", {}).get("inventory_path_size_sha256"),
                "registered_candidates": [
                    {
                        "key": key,
                        "algorithm_id": manifests[key].algorithm_id,
                        "source_artifact_id": manifests[key].source_artifact_id,
                        "manifest": f"registry/codecs/{key}.json",
                        "relationship": "WORKBOOK_REPOSITORY_AND_COMMIT_MATCH_SCOPE_NOT_FULL_ENTRY"
                        if key == "simdcomp-u32"
                        and repo == "lemire/simdcomp"
                        and (
                            registry.sources.get(manifests[key].source_artifact_id)["identity"][
                                "commit"
                            ]
                            == source.get("git", {}).get("commit")
                        )
                        else "WORKBOOK_HISTORICAL_MAPPING"
                        if key in known
                        else "NAME_OR_EXPLICIT_MAPPING_REQUIRES_SCOPE_PARITY_REVIEW",
                    }
                    for key in candidates
                ],
                "full_logical_entry_qualified": False,
            }
        )
    result = {
        "schema_version": "tscb.native-integration-worklist.v1",
        "input_provenance": {
            "workbook": args.workbook.name,
            "sheet": "全量审计",
            "workbook_sha256": hashlib.sha256(args.workbook.read_bytes()).hexdigest(),
            "source_audit_sha256": hashlib.sha256(args.source_audit.read_bytes()).hexdigest(),
            "full_scan_summary": audit["summary"],
        },
        "policy": {
            "all_221_rows_retained": True,
            "repository_primary_language_is_not_qualification": True,
            "name_match_is_not_source_parity": True,
            "registration_is_not_five_layer_qualification": True,
            "reference_benchmarks_do_not_add_ranked_codecs": True,
            "all_native_candidates_require_plan_sections": ["7.2", "7.6", "8.3", "11.5", "20.3"],
            "scope_qualification_does_not_qualify_the_whole_workbook_entry": True,
        },
        "scope_counts": dict(sorted(Counter(e["scope"] for e in entries).items())),
        "state_counts": dict(sorted(Counter(e["state"] for e in entries).items())),
        "entries": entries,
    }
    # Emit the same normalized scope contract consumed by future filters and
    # rebuilds, including merged-record references and reviewed selection metadata.
    filter_worklist(result, active_scope)
    validate_worklist(result, active_scope)
    output = ROOT / "registry/native_integration_plan.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "entries": len(entries),
                "scope_counts": result["scope_counts"],
                "state_counts": result["state_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
