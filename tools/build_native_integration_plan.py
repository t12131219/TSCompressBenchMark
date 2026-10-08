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
LITTLEINTPACKER_KEYS = [
    "littleintpacker-pack32-u32",
    "littleintpacker-turbo-u32",
    "littleintpacker-sc-u32",
    "littleintpacker-bmi2-u32",
    "littleintpacker-horizontal-u32",
]


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
                column = re.sub(r"\d+$", "", cell.get("r"))
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
    # Keep +/*: Elf, Elf+ and Elf* must never collapse to the same identity.
    return re.sub(r"[\s_\-/()]", "", name.casefold())


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


def littleintpacker_admission_review(commit: str | None) -> tuple[str, dict]:
    from audit_littleintpacker_source import PIN, audit, sha

    component = "adapters/littleintpacker"
    card, lock = ROOT / component / "SOURCE_ADMISSION.md", ROOT / component / "SOURCE_LOCK.json"
    review = {
        "card": str(card.relative_to(ROOT)),
        "card_sha256": sha(card),
        "source_lock": str(lock.relative_to(ROOT)),
        "source_lock_sha256": sha(lock),
        "bounded_abi": "PENDING",
        "python_sdk": "PENDING",
        "benchmark_registration": "PENDING",
        "benchmark_five_layers": "PENDING",
        "full_logical_entries_qualified": False,
    }
    native_started = False
    sdk_qualified = False
    try:
        if commit != PIN:
            raise RuntimeError("workbook source scan commit differs from frozen source")
        kernel_review = audit()
        review.update(
            status="ORIGINAL_SOURCE_AND_PATCHED_KERNELS_QUALIFIED_BOUNDED_ABI_PENDING",
            kernel_audit=kernel_review,
            logical_scope="FIVE_ORIGINAL_UINT32_FIXED_WIDTH_API_PAIRS_SOURCE_ONLY",
            source_padding_required=True,
            original_unsafe_probe_count=kernel_review["original_unsafe_probe_count"],
            patched_api_matrix_cases=kernel_review["patched_api_matrix_cases"],
        )
        if (ROOT / "build/source-audits/littleintpacker_native_tests.json").exists():
            from audit_littleintpacker_native import audit as audit_native

            native_started = True
            native_review = audit_native()
            review.update(
                status="SOURCE_AND_BOUNDED_UINT32_FIVE_API_ABI_QUALIFIED_SDK_PENDING",
                logical_scope="UINT32_FIXED_AND_AUTO_WIDTH_FIVE_ORIGINAL_API_PAIRS_BOUNDED_ABI",
                bounded_abi="QUALIFIED",
                bounded_abi_audit=native_review,
            )
            if (ROOT / "build/source-audits/littleintpacker_sdk_tests.json").exists():
                from audit_littleintpacker_sdk import audit as audit_sdk

                try:
                    sdk_review = audit_sdk()
                except (RuntimeError, OSError, ValueError, KeyError) as error:
                    review.update(
                        status="SOURCE_BOUNDED_ABI_QUALIFIED_CURRENT_SDK_REQUALIFICATION_REQUIRED",
                        python_sdk="CURRENT_REQUALIFICATION_REQUIRED",
                        python_sdk_failure=str(error),
                    )
                    return (
                        "SOURCE_BOUNDED_ABI_QUALIFIED_CURRENT_SDK_REQUALIFICATION_REQUIRED",
                        review,
                    )
                review.update(
                    status="SOURCE_BOUNDED_ABI_AND_DIRECT_UINT32_SDK_QUALIFIED",
                    python_sdk=sdk_review["python_sdk"],
                    python_sdk_audit=sdk_review,
                    direct_python_sdk_test_count=sdk_review["test_count"],
                    direct_python_sdk_imported_file_count=sdk_review[
                        "actual_imported_project_file_count"
                    ],
                )
                sdk_qualified = True
                if all(
                    (ROOT / f"registry/codecs/{key}.json").is_file() for key in LITTLEINTPACKER_KEYS
                ):
                    registry = CodecRegistry(
                        ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources")
                    )
                    for key in LITTLEINTPACKER_KEYS:
                        manifest = registry.get(key)
                        identity = registry.sources.get(manifest.source_artifact_id)["identity"]
                        if (
                            identity["repository"] != "https://github.com/fast-pack/LittleIntPacker"
                            or identity["commit"] != PIN
                            or manifest.document["adapter"]["factory"]
                            != "LITTLEINTPACKER_CTYPES_V1"
                        ):
                            raise ValueError("registered LittleIntPacker source/factory differs")
                    review["benchmark_registration"] = "REGISTERED"
                    from audit_littleintpacker_run import driver_report_path

                    qualification_path = driver_report_path("qualification")
                    if qualification_path.exists():
                        from audit_littleintpacker_run import audit_all as audit_runs

                        qualification = audit_runs("qualification")
                        review.update(
                            five_layer_qualification_review=qualification,
                            benchmark_five_layers="SYNTHETIC_UINT32_QUALIFICATION_PASSED_FORMAL_PENDING",
                        )
                        formal_path = driver_report_path("formal")
                        if formal_path.exists():
                            formal_document = json.loads(formal_path.read_text())
                            review["formal_execution_report_status"] = formal_document["status"]
                            if formal_document["status"] == (
                                "FIVE_LAYER_RUNS_EXECUTED_INDEPENDENT_AUDIT_PENDING"
                            ):
                                formal = audit_runs("formal")
                                review.update(
                                    formal_repetition_review=formal,
                                    benchmark_five_layers="SYNTHETIC_UINT32_VALUE_UTS_SCOPE_QUALIFIED",
                                )
                                return (
                                    "P0_LITTLEINTPACKER_UINT32_SYNTHETIC_UTS_SCOPE_QUALIFIED_"
                                    "OTHER_DATASETS_DOMAINS_PENDING",
                                    review,
                                )
                        return "SYNTHETIC_UINT32_FIVE_LAYERS_PASSED_FORMAL_PENDING", review
                    return "SOURCE_BOUNDED_ABI_SDK_QUALIFIED_REGISTERED_FIVE_LAYERS_PENDING", review
                return (
                    "SOURCE_BOUNDED_ABI_SDK_QUALIFIED_REGISTRATION_AND_FIVE_LAYERS_PENDING",
                    review,
                )
            return (
                "SOURCE_BOUNDED_UINT32_FIVE_API_ABI_QUALIFIED_SDK_AND_FIVE_LAYERS_PENDING",
                review,
            )
        return "PATCHED_SOURCE_KERNELS_QUALIFIED_BOUNDED_ABI_SDK_AND_FIVE_LAYERS_PENDING", review
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        if sdk_qualified:
            review.update(
                status="CURRENT_REGISTRATION_OR_FIVE_LAYER_REQUALIFICATION_REQUIRED",
                benchmark_five_layers="CURRENT_REQUALIFICATION_REQUIRED",
                current_qualification_failure={"reason": str(error)},
            )
            return (
                "SOURCE_BOUNDED_ABI_SDK_QUALIFIED_CURRENT_REGISTRATION_OR_FIVE_LAYER_REVIEW_REQUIRED",
                review,
            )
        review.update(
            status=(
                "CURRENT_BOUNDED_ABI_REQUALIFICATION_REQUIRED"
                if native_started
                else "CURRENT_SOURCE_OR_KERNEL_REQUALIFICATION_REQUIRED"
            ),
            current_qualification_failure={"reason": str(error)},
        )
        if native_started:
            return "SOURCE_KERNELS_QUALIFIED_CURRENT_BOUNDED_ABI_REQUALIFICATION_REQUIRED", review
        return "FROZEN_SOURCE_CURRENT_KERNEL_REQUALIFICATION_REQUIRED", review


def littleintpacker_scope_reviews(review: dict) -> list[dict]:
    formal = review.get("formal_repetition_review")
    if not formal:
        return []
    qualification = review["five_layer_qualification_review"]
    return [
        {
            "script": "audit_littleintpacker_run.py",
            "key": run["key"],
            "scope": formal["scope"],
            "status": formal["status"],
            "qualified_against_current_source": formal["status"] == "PASS",
            "formal_run": run["run_set_id"],
            "qualification_run": next(
                r["run_set_id"]
                for r in qualification["runs"]
                if r["key"] == run["key"] and r["kind"] == "qualification"
            ),
            "formal_attempts": run["records"],
            "eligible_repetitions": run["eligible"],
            "full_logical_entry_qualified": False,
        }
        for run in formal["runs"]
    ]


def refresh_littleintpacker_entries(document: dict) -> None:
    entries = document["entries"]
    if len(entries) != 221 or {entry["audit_index"] for entry in entries} != set(range(1, 222)):
        raise ValueError("existing worklist lost logical entries")
    expected = {134: "Fixed-width Bit Packing", 138: "LittleIntPacker"}
    selected = [entry for entry in entries if entry["audit_index"] in expected]
    for entry in selected:
        if (
            entry["name"] != expected[entry["audit_index"]]
            or entry["repository"] != "fast-pack/LittleIntPacker"
            or any(
                candidate["key"] not in LITTLEINTPACKER_KEYS
                for candidate in entry["registered_candidates"]
            )
            or entry["full_logical_entry_qualified"]
        ):
            raise ValueError("selective refresh cannot overwrite unrelated or completed scope")
        entry["state"], entry["source_admission_review"] = littleintpacker_admission_review(
            entry["source_commit_at_full_scan"]
        )
        entry["current_scope_reviews"] = littleintpacker_scope_reviews(
            entry["source_admission_review"]
        )
        registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
        for candidate in entry["registered_candidates"]:
            manifest = registry.get(candidate["key"])
            candidate.update(algorithm_id=manifest.algorithm_id, source_artifact_id=manifest.source_artifact_id)
    document["state_counts"] = dict(sorted(Counter(entry["state"] for entry in entries).items()))


def simple8b_rle_admission_review(commit: str | None) -> tuple[str, dict]:
    from audit_fastpfor_simple8b_rle_source import PIN, audit, sha

    component = ROOT / "adapters/fastpfor_simple8b_rle"
    card, lock = component / "SOURCE_ADMISSION.md", component / "SOURCE_LOCK.json"
    review = {
        "card": str(card.relative_to(ROOT)), "card_sha256": sha(card),
        "source_lock": str(lock.relative_to(ROOT)), "source_lock_sha256": sha(lock),
        "bounded_abi": "PENDING", "python_sdk": "PENDING",
        "benchmark_registration": "PENDING", "benchmark_five_layers": "PENDING",
        "full_logical_entry_qualified": False,
    }
    try:
        if commit != PIN:
            raise ValueError("workbook source commit differs from frozen RLE source")
        review["source_api_audit"] = audit()
        review["status"] = "PATCHED_RLE_VALID_UINT32_SOURCE_SCOPE_QUALIFIED"
        if (ROOT / "build/source-audits/fastpfor-simple8b-rle-native-safety-20261007-1/report.json").exists():
            from audit_fastpfor_simple8b_rle_native import audit as audit_native

            try:
                review["native_abi_audit"] = audit_native()
                review["bounded_abi"] = review["native_abi_audit"]["bounded_abi"]
                review["status"] = "PATCHED_RLE_BOUNDED_UINT32_ABI_SCOPE_QUALIFIED"
                return simple8b_rle_sdk_and_run_review(review)
            except Exception as error:
                review["current_native_qualification_failure"] = {"reason": str(error)}
        return (
            "PATCHED_RLE_VALID_UINT32_SOURCE_SCOPE_QUALIFIED_BOUNDED_ABI_AND_FIVE_LAYERS_PENDING",
            review,
        )
    except Exception as error:
        review["status"] = "CURRENT_SOURCE_REQUALIFICATION_REQUIRED"
        review["current_qualification_failure"] = {"reason": str(error)}
        return "FROZEN_RLE_SOURCE_CURRENT_REQUALIFICATION_REQUIRED", review


def simple8b_rle_sdk_and_run_review(review: dict) -> tuple[str, dict]:
    from audit_fastpfor_simple8b_rle_sdk import DEFAULT_REPORT, audit as audit_sdk

    if not DEFAULT_REPORT.exists():
        return "PATCHED_RLE_BOUNDED_UINT32_ABI_QUALIFIED_SDK_AND_FIVE_LAYERS_PENDING", review
    try:
        sdk = audit_sdk()
        review.update(python_sdk=sdk["python_sdk"], python_sdk_audit=sdk,
                      status="PATCHED_RLE_BOUNDED_ABI_AND_SDK_SCOPE_QUALIFIED")
    except Exception as error:
        review.update(python_sdk="CURRENT_REQUALIFICATION_REQUIRED", python_sdk_failure=str(error))
        return "PATCHED_RLE_BOUNDED_ABI_QUALIFIED_CURRENT_SDK_REQUALIFICATION_REQUIRED", review
    try:
        from audit_fastpfor_simple8b_rle_run import KEY, audit_all, source_and_runtime

        registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
        source_and_runtime(registry)
        review["benchmark_registration"] = "REGISTERED"
        qualification_path = ROOT / "build/source-audits/fastpfor-simple8b-rle-qualification-20261007-2/report.json"
        if not qualification_path.exists():
            return "PATCHED_RLE_BOUNDED_ABI_SDK_REGISTERED_FIVE_LAYERS_PENDING", review
        qualification = audit_all("qualification")
        review.update(five_layer_qualification_review=qualification,
                      benchmark_five_layers="SYNTHETIC_UINT32_QUALIFICATION_PASSED_FORMAL_PENDING",
                      formal_measurement="PENDING")
        formal_path = ROOT / "build/source-audits/fastpfor-simple8b-rle-formal-20261007-2/report.json"
        if formal_path.exists():
            formal_document = json.loads(formal_path.read_text())
            review["formal_execution_report_status"] = formal_document["status"]
            if formal_document["status"] == "FIVE_LAYER_RUNS_EXECUTED_INDEPENDENT_AUDIT_PENDING":
                formal = audit_all("formal")
                review.update(formal_repetition_review=formal, formal_measurement=formal["formal_measurement"],
                              benchmark_five_layers="SYNTHETIC_UINT32_VALUE_UTS_SCOPE_QUALIFIED",
                              status="PATCHED_RLE_SOURCE_ABI_SDK_AND_SYNTHETIC_FIVE_LAYERS_QUALIFIED")
                return "P0_FASTPFOR_SIMPLE8B_RLE_UINT32_SYNTHETIC_UTS_SCOPE_QUALIFIED_OTHER_DATASETS_DOMAINS_PENDING", review
        return "RLE_SYNTHETIC_UINT32_FIVE_LAYERS_PASSED_FORMAL_PENDING", review
    except Exception as error:
        review["current_registration_or_run_failure"] = str(error)
        if "five_layer_qualification_review" in review:
            review["formal_measurement"] = "CURRENT_REQUALIFICATION_REQUIRED"
            return "RLE_SYNTHETIC_UINT32_FIVE_LAYERS_PASSED_FORMAL_REQUALIFICATION_REQUIRED", review
        review["benchmark_five_layers"] = "CURRENT_REQUALIFICATION_REQUIRED"
        return "PATCHED_RLE_ABI_SDK_QUALIFIED_CURRENT_REGISTRATION_OR_FIVE_LAYER_REVIEW_REQUIRED", review


def simple8b_rle_scope_reviews(review: dict) -> list[dict]:
    if "formal_repetition_review" not in review:
        return []
    formal = review["formal_repetition_review"]
    return [{
        "script": "audit_fastpfor_simple8b_rle_run.py", "key": "fastpfor-simple8b-rle-u32", "scope": formal["scope"],
        "status": formal["status"], "qualified_against_current_source": formal["status"] == "PASS",
        "formal_run": formal["runs"][0]["run_set_id"],
        "qualification_run": review["five_layer_qualification_review"]["runs"][0]["run_set_id"],
        "formal_attempts": formal["records"], "eligible_repetitions": formal["eligible"],
        "full_logical_entry_qualified": False,
    }]


def refresh_simple8b_rle_entry(document: dict) -> None:
    entries = document["entries"]
    if len(entries) != 221 or {entry["audit_index"] for entry in entries} != set(range(1, 222)):
        raise ValueError("existing worklist lost logical entries")
    selected = next(entry for entry in entries if entry["audit_index"] == 148)
    if (
        selected["name"] != "FastPFOR Simple8b_RLE"
        or selected["repository"] != "fast-pack/FastPFOR"
        or any(c["key"] != "fastpfor-simple8b-rle-u32" for c in selected["registered_candidates"])
        or selected["full_logical_entry_qualified"]
    ):
        raise ValueError(
            "selective RLE refresh cannot overwrite unrelated or completed scope"
        )
    selected["state"], selected["source_admission_review"] = simple8b_rle_admission_review(
        selected["source_commit_at_full_scan"]
    )
    selected["current_scope_reviews"] = []
    registry = CodecRegistry(ROOT / "registry/codecs", SourceRegistry(ROOT / "registry/sources"))
    key = "fastpfor-simple8b-rle-u32"
    if (ROOT / f"registry/codecs/{key}.json").exists():
        manifest = registry.get(key)
        source = registry.sources.get(manifest.source_artifact_id)
        if (source["identity"]["repository"] != "https://github.com/fast-pack/FastPFOR"
                or source["identity"]["commit"] != selected["source_commit_at_full_scan"]):
            raise ValueError("RLE registry repository/pin differs from workbook")
        selected["registered_candidates"] = [{
            "key": key, "algorithm_id": manifest.algorithm_id, "source_artifact_id": manifest.source_artifact_id,
            "manifest": f"registry/codecs/{key}.json",
            "relationship": "WORKBOOK_REPOSITORY_AND_COMMIT_MATCH_SCOPE_NOT_FULL_ENTRY",
        }]
    selected["current_scope_reviews"] = simple8b_rle_scope_reviews(selected["source_admission_review"])
    document["state_counts"] = dict(sorted(Counter(entry["state"] for entry in entries).items()))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    selective = parser.add_mutually_exclusive_group()
    selective.add_argument(
        "--refresh-littleintpacker-only",
        action="store_true",
        help="Reaudit the two frozen source rows while retaining all other existing worklist rows.",
    )
    selective.add_argument(
        "--refresh-simple8b-rle-only", action="store_true",
        help="Reaudit RLE source row148 without changing any other worklist row.",
    )
    parser.add_argument(
        "--workbook", type=Path, default=ROOT / "Compression_Rewrite_Algorithm_List_v1.0.xlsx"
    )
    parser.add_argument(
        "--source-audit",
        type=Path,
        default=ROOT / "build/source-audits/native-full-audit-20261007.json",
    )
    parser.add_argument("--formal-run-set-id", default="streamvbyte-u32-formal-20261007-8")
    parser.add_argument("--simdcomp-run-suffix", default="20261007-1")
    parser.add_argument(
        "--qualification-run-set-id", default="streamvbyte-u32-qualification-20261007-7"
    )
    parser.add_argument(
        "--pipeline-formal-run-set-id", default="delta-zigzag-streamvbyte64-formal-20261007-4"
    )
    parser.add_argument(
        "--pipeline-qualification-run-set-id",
        default="delta-zigzag-streamvbyte64-switch-qualification-20261007-4",
    )
    parser.add_argument(
        "--modern-formal-run-set-id", default="streamvbyte-modern-u32-formal-20261007-1"
    )
    parser.add_argument(
        "--modern-qualification-run-set-id",
        default="streamvbyte-modern-u32-qualification-20261007-1",
    )
    parser.add_argument(
        "--modern-pipeline-formal-run-set-id",
        default="delta-zigzag-streamvbyte-modern64-formal-20261007-1",
    )
    parser.add_argument(
        "--modern-pipeline-qualification-run-set-id",
        default="delta-zigzag-streamvbyte-modern64-switch-qualification-20261007-1",
    )
    parser.add_argument(
        "--fast-differential-formal-run-set-id",
        default="fast-differential-u32-formal-20261007-1",
    )
    parser.add_argument(
        "--fast-differential-qualification-run-set-id",
        default="fast-differential-u32-qualification-20261007-1",
    )
    parser.add_argument(
        "--maskedvbyte-formal-run-set-id", default="maskedvbyte-u32-formal-20261007-2"
    )
    parser.add_argument(
        "--maskedvbyte-qualification-run-set-id",
        default="maskedvbyte-u32-qualification-20261007-2",
    )
    parser.add_argument(
        "--maskedvbyte-delta-formal-run-set-id", default="delta-maskedvbyte-u32-formal-20261007-2"
    )
    parser.add_argument(
        "--maskedvbyte-delta-qualification-run-set-id",
        default="delta-maskedvbyte-u32-qualification-20261007-2",
    )
    args = parser.parse_args()
    if args.refresh_littleintpacker_only or args.refresh_simple8b_rle_only:
        output = ROOT / "registry/native_integration_plan.json"
        document = json.loads(output.read_text())
        if (
            hashlib.sha256(args.workbook.read_bytes()).hexdigest()
            != document["input_provenance"]["workbook_sha256"]
        ):
            raise ValueError("workbook changed; full worklist rebuild required")
        if args.refresh_littleintpacker_only:
            refresh_littleintpacker_entries(document)
            updated = [134, 138]
        else:
            refresh_simple8b_rle_entry(document)
            updated = [148]
        output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps({"entries": len(document["entries"]), "updated_audit_indices": updated})
        )
        return
    rows = workbook_rows(args.workbook)
    if len(rows) != 221 or {int(row["A"]) for row in rows} != set(range(1, 222)):
        raise ValueError("the full-audit sheet must preserve all 221 unique logical entries")
    audit = json.loads(args.source_audit.read_text())
    if len(audit["logical_entries"]) != 221 or len(audit["repositories"]) != 72:
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
        "Delta-of-Delta / Second-order Difference": ["prometheus-xor-chunk"],
        "Delta + Stream VByte": ["delta-zigzag-streamvbyte64", "delta-zigzag-streamvbyte-modern64"],
        "Stream VByte": ["streamvbyte-u32", "streamvbyte-modern-u32"],
        "SIMD Differential Coding": ["fast-differential-u32"],
        "Masked VByte": ["maskedvbyte-u32"],
        "Delta + Masked VByte": ["delta-maskedvbyte-u32"],
        "SIMDComp": ["simdcomp-u32", "delta-simdcomp-u32", "for-simdcomp-u32"],
        "Simple-9": ["simple9-u28", "simple9hacked-u28"],
        "Simple-16": ["simple16-u28"],
        "FastPFOR Simple8b_RLE": ["fastpfor-simple8b-rle-u32"],
        "Fixed-width Bit Packing": LITTLEINTPACKER_KEYS,
        "LittleIntPacker": LITTLEINTPACKER_KEYS,
    }
    native_hint = re.compile(r"(?<![A-Za-z])C(?:\+\+)?(?=$|[ /+])")
    entries = []
    simple_run_reviews = {}
    for row in rows:
        name, repo, language = row["F"], row["G"] or None, row.get("I") or row.get("H", "")
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
        if repo == "fast-pack/FastPFOR" and name == "FastPFOR Simple8b_RLE":
            if int(row["A"]) != 148:
                raise ValueError("RLE source/workbook row identity differs")
            if (ROOT / "adapters/fastpfor_simple8b_rle/SOURCE_LOCK.json").exists():
                status, admission_review = simple8b_rle_admission_review(
                    source.get("git", {}).get("commit")
                )
                scope_reviews = simple8b_rle_scope_reviews(admission_review)
        if repo == "fast-pack/LittleIntPacker" and name in {
            "Fixed-width Bit Packing",
            "LittleIntPacker",
        }:
            status, admission_review = littleintpacker_admission_review(
                source.get("git", {}).get("commit")
            )
            scope_reviews = littleintpacker_scope_reviews(admission_review)
        if repo == "fast-pack/FastPFOR" and name in {"Simple-9", "Simple-16"}:
            from audit_fastpfor_simple_native import audit as audit_simple_native
            from audit_fastpfor_simple_source import sha as simple_sha

            component = "adapters/fastpfor_simple"
            lock_path = ROOT / component / "SOURCE_LOCK.json"
            card = ROOT / component / "SOURCE_ADMISSION.md"
            admission_review = {
                "card": str(card.relative_to(ROOT)),
                "card_sha256": simple_sha(card),
                "source_lock": str(lock_path.relative_to(ROOT)),
                "source_lock_sha256": simple_sha(lock_path),
                "benchmark_registration": "REGISTERED" if candidates else "PENDING",
                "python_sdk": "PENDING",
                "benchmark_five_layers": "PENDING",
                "simple9_original_full_upstream_unit": "PENDING",
                "logical_scope": "UINT28_P0_ORIGINAL_MARKED_AND_UNMARKED",
            }
            try:
                lock = json.loads(lock_path.read_text())
                if (
                    lock["repository"] != "https://github.com/" + repo
                    or lock["commit"] != source.get("git", {}).get("commit")
                    or lock["logical_entries"]
                    != [
                        {"audit_index": 145, "name": "Simple-9"},
                        {"audit_index": 146, "name": "Simple-16"},
                    ]
                    or int(row["A"]) != {"Simple-9": 145, "Simple-16": 146}[name]
                ):
                    raise ValueError("Simple source/workbook identity differs")
                current = audit_simple_native(ROOT)
                admission_review.update(
                    status="ORIGINAL_SOURCE_AND_BOUNDED_UINT28_ABI_QUALIFIED",
                    source_api_audit=current["source_probe_audit"],
                    bounded_abi="SCOPED_UINT28_MARKED_AND_UNMARKED_QUALIFIED",
                    bounded_abi_audit=current,
                    bounded_native_report="build/source-audits/fastpfor_simple_native_tests.json",
                    bounded_native_report_sha256=current["native_report_sha256"],
                    bounded_native_cases=current["native_cases"],
                    bounded_native_fault_checks=current["native_fault_checks"],
                    original_unsafe_probe_count=current["source_probe_audit"][
                        "original_unsafe_probe_count"
                    ],
                    benchmark_difference="LZBENCH_NO_PUBLIC_SIMPLE9_SIMPLE16_ENTRY_UNBOUNDED_WRAPPER",
                    input_domain="UINT32_STORAGE_VALUES_0_TO_268435455_ONLY",
                    original_vendor_file_count=len(lock["files"]),
                )
                status = (
                    "SOURCE_BOUNDED_UINT28_ABI_QUALIFIED_"
                    "SIMPLE9_UPSTREAM_SDK_REGISTRATION_AND_FIVE_LAYERS_PENDING"
                )
                from audit_fastpfor_simple_sdk import audit as audit_simple_sdk

                try:
                    sdk_current = audit_simple_sdk(ROOT)
                except (RuntimeError, OSError, ValueError, KeyError) as error:
                    admission_review.update(
                        status=(
                            "ORIGINAL_SOURCE_AND_BOUNDED_UINT28_ABI_QUALIFIED_"
                            "CURRENT_SDK_REQUALIFICATION_REQUIRED"
                        ),
                        python_sdk="CURRENT_REQUALIFICATION_REQUIRED",
                        python_sdk_failure=str(error),
                    )
                    status = (
                        "SOURCE_BOUNDED_UINT28_ABI_QUALIFIED_"
                        "CURRENT_SDK_AND_FIVE_LAYER_REQUALIFICATION_REQUIRED"
                    )
                else:
                    admission_review.update(
                        status="ORIGINAL_SOURCE_UPSTREAM_BOUNDED_UINT28_AND_SDK_QUALIFIED",
                        python_sdk=sdk_current["python_sdk"],
                        python_sdk_audit=sdk_current,
                        direct_python_sdk_test_count=sdk_current["test_count"],
                        direct_python_sdk_imported_file_count=sdk_current[
                            "actual_imported_project_file_count"
                        ],
                        simple9_original_full_upstream_unit="RELEASE_ASSERTIONS_ENABLED_QUALIFIED",
                        full_original_upstream_audit=sdk_current["upstream_audit"],
                    )
                    status = (
                        "SOURCE_UPSTREAM_BOUNDED_UINT28_SDK_QUALIFIED_"
                        "REGISTERED_FIVE_LAYERS_PENDING"
                        if candidates
                        else "SOURCE_UPSTREAM_BOUNDED_UINT28_SDK_QUALIFIED_REGISTRATION_PENDING"
                    )
                    if candidates:
                        from audit_fastpfor_simple_run import audit_all as audit_simple_runs

                        for phase in ("qualification", "formal"):
                            if phase not in simple_run_reviews:
                                try:
                                    simple_run_reviews[phase] = audit_simple_runs(phase)
                                except (RuntimeError, OSError, ValueError, KeyError) as error:
                                    simple_run_reviews[phase] = {
                                        "status": "CURRENT_REQUALIFICATION_REQUIRED",
                                        "phase": phase,
                                        "reason": str(error),
                                    }
                        qualification = simple_run_reviews["qualification"]
                        formal = simple_run_reviews["formal"]
                        admission_review.update(
                            five_layer_qualification_review=qualification,
                            formal_repetition_review=formal,
                        )
                        for key in candidates:
                            run = next((r for r in formal.get("runs", []) if r["key"] == key), None)
                            scope_reviews.append(
                                {
                                    "script": "audit_fastpfor_simple_run.py",
                                    "key": key,
                                    "scope": "SYNTHETIC_UINT28_VALUE_UTS_MARKED_AND_UNMARKED_ONLY",
                                    "qualified_against_current_source": formal["status"] == "PASS",
                                    "status": formal["status"],
                                    "formal_run": run["run_set_id"] if run else None,
                                    "formal_attempts": run["records"] if run else 0,
                                    "eligible_repetitions": run["eligible"] if run else 0,
                                    "full_logical_entry_qualified": False,
                                }
                            )
                        if qualification["status"] == "PASS":
                            admission_review["benchmark_five_layers"] = (
                                "SYNTHETIC_UINT28_QUALIFICATION_PASSED_FORMAL_PENDING"
                            )
                            status = "SYNTHETIC_UINT28_FIVE_LAYERS_PASSED_FORMAL_PENDING"
                        if formal["status"] == "PASS":
                            admission_review["benchmark_five_layers"] = (
                                "SYNTHETIC_UINT28_VALUE_UTS_SCOPE_QUALIFIED"
                            )
                            status = (
                                "P0_SIMPLE_UINT28_SYNTHETIC_UTS_SCOPE_QUALIFIED_"
                                "OTHER_DATASETS_DOMAINS_PENDING"
                            )
            except (RuntimeError, OSError, ValueError, KeyError) as error:
                admission_review.update(
                    status="CURRENT_SOURCE_OR_NATIVE_REQUALIFICATION_REQUIRED",
                    bounded_abi="CURRENT_REQUALIFICATION_REQUIRED",
                    current_qualification_failure={
                        "type": type(error).__name__,
                        "reason": str(error),
                    },
                )
                status = "FROZEN_SOURCE_CURRENT_NATIVE_REQUALIFICATION_REQUIRED"
        if repo == "fast-pack/MaskedVByte" and name in {"Masked VByte", "Delta + Masked VByte"}:
            from audit_maskedvbyte_native import audit as audit_masked_native
            from audit_maskedvbyte_sdk import audit as audit_masked_sdk
            from audit_maskedvbyte_source import audit as audit_masked_source
            from audit_maskedvbyte_source import sha as masked_sha

            try:
                current = audit_masked_source(ROOT)
                native_current = audit_masked_native(ROOT)
                sdk_current = audit_masked_sdk(ROOT)
                card = ROOT / "adapters/maskedvbyte/SOURCE_ADMISSION.md"
                require_commit = json.loads(
                    (ROOT / "adapters/maskedvbyte/SOURCE_LOCK.json").read_text()
                )["commit"]
                assert require_commit == source.get("git", {}).get("commit")
                admission_review = {
                    "card": str(card.relative_to(ROOT)),
                    "card_sha256": masked_sha(card),
                    "status": "PATCHED_SOURCE_BOUNDED_NATIVE_AND_DIRECT_SDK_QUALIFIED",
                    "source_lock": "adapters/maskedvbyte/SOURCE_LOCK.json",
                    "source_lock_sha256": current["source_lock_sha256"],
                    "source_tests": "build/source-audits/maskedvbyte-source-both-tests.json",
                    "source_tests_sha256": current["report_sha256"],
                    "patch_sha256": current["patch_sha256"],
                    "original_failure_retained": current["original_failure_retained"],
                    "benchmark_difference": "FASTPFOR_PLAIN_ONLY_32BIT_PADDING_OTHER_PUBLIC_API",
                    "bounded_abi": "SCOPED_UINT32_PLAIN_AND_MODULAR_DELTA_QUALIFIED",
                    "bounded_native_report": "build/source-audits/maskedvbyte-native-tests.json",
                    "bounded_native_report_sha256": native_current["native_report_sha256"],
                    "bounded_cases_per_executable": native_current["bounded_cases_per_executable"],
                    "bounded_executables": native_current["bounded_executables"],
                    "direct_python_sdk_report": "build/source-audits/maskedvbyte-sdk-tests.json",
                    "direct_python_sdk_report_sha256": sdk_current["sdk_report_sha256"],
                    "direct_python_sdk_test_count": sdk_current["test_count"],
                    "direct_python_sdk_imported_file_count": sdk_current[
                        "actual_imported_project_file_count"
                    ],
                    "python_sdk": "SCOPED_UINT32_PLAIN_AND_MODULAR_DELTA_QUALIFIED",
                    "benchmark_registration": "REGISTERED" if candidates else "PENDING",
                    "benchmark_five_layers": "PENDING",
                    "logical_scope": "P0_PLAIN_UINT32"
                    if name == "Masked VByte"
                    else "P2_ORIGINAL_MODULAR_UINT32_D1_LEB128_INT64_TIMESTAMP_PIPELINE_PENDING",
                }
                status = (
                    "SOURCE_BOUNDED_ABI_DIRECT_SDK_QUALIFIED_REGISTERED_FIVE_LAYERS_PENDING"
                    if candidates
                    else (
                        "SOURCE_BOUNDED_ABI_DIRECT_SDK_QUALIFIED_"
                        "REGISTRATION_AND_FIVE_LAYERS_PENDING"
                    )
                )
                if candidates:
                    plain = name == "Masked VByte"
                    scope_reviews = [
                        current_scope_review(
                            "audit_maskedvbyte_run.py",
                            args.maskedvbyte_formal_run_set_id
                            if plain
                            else args.maskedvbyte_delta_formal_run_set_id,
                            args.maskedvbyte_qualification_run_set_id
                            if plain
                            else args.maskedvbyte_delta_qualification_run_set_id,
                            "maskedvbyte-u32" if plain else "delta-maskedvbyte-u32",
                        )
                    ]
                    if scope_reviews[0]["qualified_against_current_source"]:
                        admission_review["benchmark_five_layers"] = (
                            "P0_PLAIN_UINT32_SCOPE_QUALIFIED"
                            if plain
                            else "P2_ORIGINAL_MODULAR_UINT32_SCOPE_QUALIFIED"
                        )
                        status = (
                            "P0_PLAIN_MASKEDVBYTE_UINT32_SCOPE_QUALIFIED_OTHER_DOMAINS_PENDING"
                            if plain
                            else (
                                "P2_ORIGINAL_MODULAR32_MASKEDVBYTE_SCOPE_QUALIFIED_"
                                "INT64_TIMESTAMP_PENDING"
                            )
                        )
            except (RuntimeError, OSError, ValueError, KeyError) as error:
                card = ROOT / "adapters/maskedvbyte/SOURCE_ADMISSION.md"
                admission_review = {
                    "status": "CURRENT_NATIVE_OR_SDK_REQUALIFICATION_REQUIRED",
                    "card": str(card.relative_to(ROOT)),
                    "card_sha256": masked_sha(card),
                    "benchmark_registration": "REGISTERED" if candidates else "PENDING",
                    "benchmark_five_layers": "REQUALIFICATION_REQUIRED",
                    "current_qualification_failure": {
                        "type": type(error).__name__,
                        "reason": str(error),
                    },
                }
                scope_reviews = [
                    current_scope_review(
                        "audit_maskedvbyte_run.py",
                        args.maskedvbyte_formal_run_set_id
                        if name == "Masked VByte"
                        else args.maskedvbyte_delta_formal_run_set_id,
                        args.maskedvbyte_qualification_run_set_id
                        if name == "Masked VByte"
                        else args.maskedvbyte_delta_qualification_run_set_id,
                        "maskedvbyte-u32" if name == "Masked VByte" else "delta-maskedvbyte-u32",
                    )
                ]
                status = "REGISTERED_CURRENT_SOURCE_OR_FIVE_LAYER_REQUALIFICATION_REQUIRED"
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
                        == (item["sha256"])
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
                                            "PATCHED_SSE4_1_AVX2_SOURCE_AND_BOUNDED_ABI_SCOPE_"
                                            "QUALIFIED_SDK_AND_FIVE_LAYERS_PENDING"
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
                                                    "PATCHED_SOURCE_BOUNDED_ABI_DIRECT_SDK_SCOPE_"
                                                    "QUALIFIED_REGISTRATION_AND_FIVE_LAYERS_PENDING"
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
                                                            "REGISTERED_SOURCE_ABI_SDK_QUALIFIED_"
                                                            "FIVE_LAYERS_PENDING"
                                                        )
                                                    )
        if name == "SIMD Differential Coding":
            path = ROOT / "adapters/fast_differential/SOURCE_LOCK.json"
            lock = json.loads(path.read_text())
            assert repo == "lemire/FastDifferentialCoding"
            assert lock["repository"] == "https://github.com/" + repo
            assert lock["commit"] == source.get("git", {}).get("commit")
            for item in lock["files"]:
                assert (
                    hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() == item["sha256"]
                )
            card = ROOT / "adapters/fast_differential/SOURCE_ADMISSION.md"
            admission_review = {
                "card": str(card.relative_to(ROOT)),
                "card_sha256": hashlib.sha256(card.read_bytes()).hexdigest(),
                "source_lock": str(path.relative_to(ROOT)),
                "source_lock_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "status": "SOURCE_REVIEW_ONLY_UPSTREAM_AND_BOUNDED_TESTS_PENDING",
                "benchmark_difference": "FASTPFOR_DELTA_SIMD_D4_VS_SOURCE_D1",
            }
            qualification = ROOT / "build/source-audits/fast-differential-source-tests.json"
            qualified = json.loads(qualification.read_text())
            assert qualified["status"] == "PASS"
            assert qualified["source_lock_sha256"] == admission_review["source_lock_sha256"]
            assert (
                qualified["driver_sha256"]
                == hashlib.sha256(
                    (ROOT / "adapters/fast_differential/tests/run_source_tests.py").read_bytes()
                ).hexdigest()
            )
            assert {(t["kind"], t["profile"]) for t in qualified["tests"]} == {
                (kind, profile)
                for kind in ("upstream", "source_guard")
                for profile in ("release", "debug", "sanitizer")
            }
            assert len(qualified["tests"]) == 6
            for test in qualified["tests"]:
                assert test["returncode"] == 0
                filename = (
                    "adapters/fast_differential/tests/source_guard.c"
                    if test["kind"] == "source_guard"
                    else "adapters/fast_differential/vendor/FastDifferentialCoding/tests/unit.c"
                )
                assert (
                    test["test_sha256"]
                    == hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
                )
            admission_review.update(
                status="ORIGINAL_SOURCE_API_QUALIFIED_BENCHMARK_ADAPTER_PENDING",
                source_tests=str(qualification.relative_to(ROOT)),
                source_tests_sha256=hashlib.sha256(qualification.read_bytes()).hexdigest(),
            )
            status = "SOURCE_API_QUALIFIED_BOUNDED_ABI_AND_FIVE_LAYERS_PENDING"
            native_report = ROOT / "build/source-audits/fast-differential-native-tests.json"
            try:
                if native_report.is_file():
                    from audit_fast_differential_native import audit as audit_fast_native
                    from audit_fast_differential_native import require, sha

                    current_native = audit_fast_native(ROOT)
                    admission_review.update(
                        status="SOURCE_AND_BOUNDED_ABI_QUALIFIED_PYTHON_SDK_PENDING",
                        bounded_native_tests=str(native_report.relative_to(ROOT)),
                        bounded_native_tests_sha256=sha(native_report),
                        bounded_cases_per_executable=current_native["bounded_cases_per_executable"],
                        bounded_executables=current_native["bounded_executables"],
                        benchmark_registration="REGISTERED"
                        if "fast-differential-u32" in manifests
                        else "PENDING",
                        benchmark_five_layers="PENDING",
                    )
                    status = "SOURCE_BOUNDED_ABI_QUALIFIED_PYTHON_SDK_AND_FIVE_LAYERS_PENDING"
                    sdk_path = ROOT / "build/source-audits/fast-differential-sdk-tests.json"
                    if sdk_path.is_file():
                        sdk = json.loads(sdk_path.read_text())
                        require(
                            sdk["status"] == "PASS", "FastDifferential SDK qualification not PASS"
                        )
                        require(
                            sdk["native_current_audit"] == current_native,
                            "FastDifferential SDK/native evidence differs",
                        )
                        for dependency in sdk["source_snapshot"]:
                            require(
                                sha(ROOT / dependency["path"]) == dependency["sha256"],
                                "FastDifferential SDK dependency drift",
                            )
                        totals = sdk["test_totals"]
                        require(
                            totals["tests"] >= 103
                            and not any(totals[key] for key in ("failures", "errors", "skipped")),
                            "FastDifferential SDK test matrix incomplete",
                        )
                        require(
                            sha(ROOT / "build/source-audits/fast-differential-sdk/pytest.xml")
                            == sdk["junit_sha256"],
                            "FastDifferential SDK JUnit drift",
                        )
                        admission_review.update(
                            status="SOURCE_BOUNDED_ABI_AND_DIRECT_PYTHON_SDK_QUALIFIED",
                            direct_python_sdk_tests=str(sdk_path.relative_to(ROOT)),
                            direct_python_sdk_tests_sha256=sha(sdk_path),
                            direct_python_sdk_test_count=totals["tests"],
                        )
                        status = "SOURCE_BOUNDED_ABI_PYTHON_SDK_QUALIFIED_FIVE_LAYERS_PENDING"
                        if "fast-differential-u32" in manifests:
                            scope_reviews = [
                                current_scope_review(
                                    "audit_fast_differential_run.py",
                                    args.fast_differential_formal_run_set_id,
                                    args.fast_differential_qualification_run_set_id,
                                )
                            ]
                            accepted = scope_reviews[0]["qualified_against_current_source"]
                            admission_review["benchmark_five_layers"] = (
                                "UINT32_D1_SCOPE_QUALIFIED"
                                if accepted
                                else "REQUALIFICATION_REQUIRED"
                            )
                            status = (
                                "P0_D1_UINT32_FOUR_APIS_SCOPE_QUALIFIED_OTHER_DOMAINS_PIPELINES_PENDING"
                                if accepted
                                else (
                                    "REGISTERED_CURRENT_SOURCE_OR_FIVE_LAYER_"
                                    "REQUALIFICATION_REQUIRED"
                                )
                            )
            except (RuntimeError, OSError, ValueError, AssertionError) as error:
                admission_review.update(
                    status="CURRENT_NATIVE_OR_SDK_REQUALIFICATION_REQUIRED",
                    benchmark_registration="REGISTERED"
                    if "fast-differential-u32" in manifests
                    else "PENDING",
                    benchmark_five_layers="REQUALIFICATION_REQUIRED",
                    current_qualification_failure={
                        "type": type(error).__name__,
                        "reason": str(error),
                    },
                )
                status = "REGISTERED_CURRENT_SOURCE_OR_FIVE_LAYER_REQUALIFICATION_REQUIRED"
                if "fast-differential-u32" in manifests:
                    scope_reviews = [
                        current_scope_review(
                            "audit_fast_differential_run.py",
                            args.fast_differential_formal_run_set_id,
                            args.fast_differential_qualification_run_set_id,
                        )
                    ]
        if name == "Delta + Stream VByte":
            scope_reviews = [
                current_scope_review(
                    "audit_streamvbyte_pipeline_run.py",
                    args.pipeline_formal_run_set_id,
                    args.pipeline_qualification_run_set_id,
                ),
                current_scope_review(
                    "audit_streamvbyte_pipeline_run.py",
                    args.modern_pipeline_formal_run_set_id,
                    args.modern_pipeline_qualification_run_set_id,
                    "delta-zigzag-streamvbyte-modern64",
                ),
            ]
            status = (
                "P2_MODERN_1234_CHECKED_INT64_SCOPE_QUALIFIED_OTHER_API_VARIANTS_PENDING"
                if all(review["qualified_against_current_source"] for review in scope_reviews)
                else "REGISTERED_CURRENT_SOURCE_OR_FIVE_LAYER_REQUALIFICATION_REQUIRED"
            )
        elif name == "Stream VByte":
            # Prove the scoped qualification from current files, never from registration alone.
            scope_reviews = [
                current_scope_review(
                    "audit_streamvbyte_run.py",
                    args.formal_run_set_id,
                    args.qualification_run_set_id,
                ),
                current_scope_review(
                    "audit_streamvbyte_run.py",
                    args.modern_formal_run_set_id,
                    args.modern_qualification_run_set_id,
                    "streamvbyte-modern-u32",
                ),
            ]
            status = (
                "P0_MODERN_1234_U32_SCOPE_QUALIFIED_OTHER_API_VARIANTS_PENDING"
                if all(review["qualified_against_current_source"] for review in scope_reviews)
                else "REGISTERED_CURRENT_SOURCE_OR_FIVE_LAYER_REQUALIFICATION_REQUIRED"
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
                        "relationship": (
                            "WORKBOOK_REPOSITORY_AND_COMMIT_MATCH_SCOPE_NOT_FULL_ENTRY"
                            if key
                            in {
                                "streamvbyte-modern-u32",
                                "delta-zigzag-streamvbyte-modern64",
                                "maskedvbyte-u32",
                                "delta-maskedvbyte-u32",
                                "simdcomp-u32",
                                "delta-simdcomp-u32",
                                "for-simdcomp-u32",
                                "simple9-u28",
                                "simple9hacked-u28",
                                "simple16-u28",
                                "fastpfor-simple8b-rle-u32",
                                *LITTLEINTPACKER_KEYS,
                            }
                            and repo
                            in {
                                "fast-pack/streamvbyte",
                                "fast-pack/MaskedVByte",
                                "lemire/simdcomp",
                                "fast-pack/FastPFOR",
                                "fast-pack/LittleIntPacker",
                            }
                            and registry.sources.get(manifests[key].source_artifact_id)["identity"][
                                "commit"
                            ]
                            == source.get("git", {}).get("commit")
                            else "WORKBOOK_HISTORICAL_MAPPING"
                            if key in known
                            else "NAME_OR_EXPLICIT_MAPPING_REQUIRES_SCOPE_PARITY_REVIEW"
                        ),
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
