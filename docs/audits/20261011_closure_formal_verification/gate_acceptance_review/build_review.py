"""Read-only acceptance review of the frozen 33-entry/220-gate ledger.

This consumes small receipt/contract files only. It does not load production
modules, hash archives or binaries, execute a codec, rebuild or measure performance.
Existing receipts are evidence of their stated scope, not new execution here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
AUDIT = ROOT / "docs/audits/20261011_closure_formal_verification"
PORT = ROOT / "docs/audits/20261011_porting_standard"
STANDARD = ROOT / "Compression_Algorithm_CPP_Porting_Standard_v3.0.md"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text())


def ref(path):
    data = path.read_bytes()
    return {"path": str(path.relative_to(ROOT)),
            "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def subitem(key, status, finding, evidence=()):
    return {"id": key, "review_status": status, "finding": finding,
            "evidence_keys": list(evidence)}


def main():
    output = HERE / "acceptance_review_r1.json"
    require(not output.exists(), "retain the frozen review; use a new supplement")
    paths = {
        "standard": STANDARD,
        "ledger": AUDIT / "gate_ledger/current_complete_gate_ledger.json",
        "routes": PORT / "rewrite_routes.json",
        "cap_inventory": AUDIT / "gate_audit/capability_inventory.json",
        "sources_r4": AUDIT / "source_closure/r4/report.json",
        "source_supplement_r2": AUDIT / "source_closure/supplement-r2.json",
        "upstream_authority_r3": AUDIT / "upstream_authority_r3/verification.json",
        "environment_recovery": AUDIT / "oracle_recovery_network_r1/completion_supplement.json",
        "fresh_scoped_source": PORT / "fresh_source_summary.json",
        "current_completed_api": PORT / "completed_native_r1-summary/report.json",
        "current_bench_qualification": ROOT / "build/port-standard-v30-20261011/active33-r2/summary.json",
        "current_four_matrices": ROOT / "build/port-standard-v30-20261011/active33-r2/four_matrices.json",
        "old_build_gap_inventory": AUDIT / "build_link/inventory_v1.json",
        "build_independent_review_r1": AUDIT / "formal_static_review/build-link-independent-review-r1.json",
        "fresh_fixed_weight_source_r2": AUDIT / "learned_source_oracle_r1/summary-r2.json",
        "dzip_source_comparability": AUDIT / "learned_source_oracle_r1/dzip_comparability_boundary.json",
    }
    for codec in ("abba", "fabba", "deepzip", "dzip"):
        paths[f"{codec}_manifest"] = ROOT / f"adapters/completed_rewrites/vendor/{codec}/PORT_MANIFEST.yaml"
        paths[f"{codec}_matrix"] = ROOT / f"adapters/completed_rewrites/vendor/{codec}/NATIVE_CAPABILITY_MATRIX.yaml"
    inputs = {key: ref(path) for key, path in paths.items()}
    ledger = read(paths["ledger"])
    route_map = {item["codec"]: item for item in read(paths["routes"])["entries"]}
    source_map = {item["codec_key"]: item for item in read(paths["sources_r4"])["rows"]}
    cap_map = {item["codec"]: item for item in read(paths["cap_inventory"])}
    recovery = read(paths["environment_recovery"])
    source_supplement = read(paths["source_supplement_r2"])
    upstream = read(paths["upstream_authority_r3"])
    qualification = read(paths["current_bench_qualification"])
    completed = read(paths["current_completed_api"])
    learned = read(paths["fresh_fixed_weight_source_r2"])
    require(len(ledger["entries"]) == 33, "expected 33 entries")
    require(ledger["applicable_gate_row_count"] == 220, "expected 220 gates")
    require(all(row["installed_source_closure"]["status"] == "PASS" for row in source_map.values()),
            "the selected-source-tree receipt no longer states 33 PASS")
    require(qualification["status_counts"] == {"SCOPED_PASS": 41}, "unexpected current Bench result")
    require(recovery["environment_probe_status"] == "ALL_RESTORED_ENVIRONMENT_PROBES_PASS",
            "unexpected environment receipt")
    require(upstream["all_source_gitlinks_exact_commits_verified"], "authority supplement incomplete")
    require(learned["checks"]["CDF_independently_predicted_full15"] == "FAIL_1_OF15_DIFFERENT",
            "unexpected fresh source diagnostic result; do not erase mismatch")

    # These three existing package manifests contain explicit stable logical IDs,
    # P2 classification, source mapping and G0 duplicate-stage decisions. The
    # receipt is re-reviewed here only for G0; historical G1-G6 claims are not reused.
    identity_reviews = {}
    for codec in ("abba", "fabba", "deepzip", "dzip"):
        text = paths[f"{codec}_manifest"].read_text()
        def top_value(key):
            match = re.search(r"^" + re.escape(key) + r": ([^\n]+)$", text, re.M)
            return match.group(1).strip() if match else None
        identity_reviews[codec] = {
            "algorithm_id": top_value("algorithm_id"),
            "implementation_id": top_value("implementation_id"),
            "object_level": top_value("object_level"),
            "source_mapping_and_G0_decision_present": "  G0:\n    status: PASS" in text and "source:\n" in text,
            "current_manifest": inputs[f"{codec}_manifest"],
        }
    for codec in ("abba", "fabba", "deepzip"):
        item = identity_reviews[codec]
        require(item["algorithm_id"] == codec and item["implementation_id"]
                and item["object_level"] == "P2_PIPELINE"
                and item["source_mapping_and_G0_decision_present"], "G0 identity precondition")

    pending = [
        {"key": "build_trace_v5", "status": "PENDING_AT_REVIEW_FREEZE",
         "owner": "/root", "scope": "Final independent observed compile/link/toolchain consumption closure; old inventory and r1 review remain preserved.",
         "grant_transfer": "A successful build-trace result can satisfy affected N1/G1 build subitems; it does not grant semantics, CAP or independent delivery."},
        {"key": "deepzip_independent_CDF_discrepancy_and_full_required_pipeline", "status": "PENDING_AFTER_FROZEN_SCOPED_DIFFERENCE",
         "owner": "/root/source_closure_verify", "scope": "Fixed-weight biGRU/alphabet4/three-context fresh source diagnostic is now complete. Independent prediction CDF has one retained integer difference; all trained checkpoints, required source/native GPU/codec/dataset paths remain unclosed.",
         "grant_transfer": "Probability tolerance PASS and same-source CDF conversion PASS cannot grant independent CDF/bitstream equality. Resolve or explicitly classify the difference under the unchanged frozen compatibility target; never alter expected or shrink required scope."},
        {"key": "formal_final_results", "status": "PENDING_AT_REVIEW_FREEZE",
         "owner": "/root", "scope": "Separate frozen Bench scientific protocol qualification/measurement and auxiliary/reference cost artifacts.",
         "grant_transfer": "FORMAL is not required by N5 and cannot substitute N/G/CAP gates."},
    ]

    capability_reviews = []
    cap_by_codec = {}
    for codec, matrix in cap_map.items():
        rows = []
        for item in matrix["capabilities"]:
            classification = item["parity_class"]
            required = classification == "REQUIRED_PARITY"
            missing = []
            scoped = []
            if required:
                if codec == "abba":
                    scoped = ["74 stage-composed source cases and 64 alternate cases are retained as finite scoped semantic evidence."]
                    missing = ["Current complete original-call-graph/source-contract review and required platform/dataset/API coverage have not been accepted; historical AArch64 and package reports remain historical."]
                elif codec == "fabba":
                    scoped = ["73 cases: 26 unchanged source aggregation, 46 stabilized digitization and one decode-only; 32 partition cases are retained with that oracle boundary."]
                    missing = ["Complete required original-source behavior, parallel execution/race/platform coverage and current independent API tests are not accepted; stabilized digitization is not unmodified-source parity."]
                elif codec == "deepzip":
                    scoped = ["17 CPU model fixtures/51 archived TF contexts remain finite replay evidence; 152 original trained HDF5 assets are inventoried.",
                              "Fresh current biGRU/alphabet4/three-context fixed-weight diagnostic: source weight reexport EXACT, 4 actual GPU CudnnRNN nodes, 12 probabilities PASS (maxabs1.4901161193847656e-08 < frozen3e-5), same-source probabilities to15CDF integers EXACT. Independently predicted full15CDF has1 difference (source total10000004/native10000003)."]
                    missing = ["Full required checkpoint/predictor/native GPU/source codec and dataset differential remains NOT_TESTED. The new fixed-weight diagnostic retains an independent-CDF semantic difference; finite probability tolerance does not grant source bitstream or complete CAP parity."]
                else:
                    scoped = ["Current native seeded CPU model/frame/update API tests and archived source/training/CUDA reports remain scoped evidence."]
                    missing = ["Current complete original TF initializer/trained PRNN, bootstrap/combined/training/online Adam/GPU and source codec dataset parity is NOT_TESTED at this freeze; native seeded initialization is a different model contract."]
            rows.append({
                "capability_id": item["capability_id"],
                "frozen_original_classification": classification,
                "historical_recorded_validation": item["historical_recorded_validation"],
                "historical_PASS_rewritten_or_demoted": False,
                "required_obligation_retained": required,
                "current_full_scope_validation": "NOT_TESTED" if required else "CLASSIFICATION_REVIEW_PENDING",
                "test_status_meaning": "NOT_TESTED concerns still-unverified mandatory full-scope subitems, not all previous finite executions.",
                "retained_scoped_evidence": scoped,
                "unmet_subitems": missing,
                "new_legal_four_state_classification_required": classification not in {
                    "REQUIRED_PARITY", "OPTIONAL_OPTIMIZATION", "UNAVAILABLE_WITH_WAIVER", "NOT_APPLICABLE"},
                "implementation_or_codec_execution_failure_recorded": False,
                "scoped_source_comparison_difference_recorded": codec == "deepzip" and item["capability_id"] in {"pipeline.lossless_encode_decode", "entropy.numpy_float64_cumsum_cast", "execution.gpu_prediction", "predictor.biGRU"},
            })
        result = {"codec_key": codec, "current_matrix": inputs[f"{codec}_matrix"],
                  "original_class_counts": matrix["class_counts"], "capabilities": rows,
                  "current_full_scope_CAP_GATE_status": "FAIL",
                  "failure_kind": "ACCEPTANCE_NOT_TESTED_REQUIRED_SUBITEMS",
                  "recorded_execution_failure": False,
                  "four_state_review_issue": "reference.gpu_bpc_estimator keeps historical REFERENCE_ONLY; a new justified legal four-state review is required." if codec == "dzip" else None,
                  "full_parity_granted": False}
        capability_reviews.append(result)
        cap_by_codec[codec] = result

    gate_rows = []
    entries = []
    for entry in ledger["entries"]:
        codec = entry["codec_key"]
        route = route_map[codec]
        current_limitations = route["limitations"]
        if codec == "deepzip":
            current_limitations = "Exact TF-GPU1.8/Keras2.2.2/NumPy1.16.4 runtime and source GPU execution are now available. Current fixed-weight four-symbol biGRU has a retained independent-prediction CDF difference; finite fixed-weight/archived context evidence does not cover all original trained checkpoints, native GPU, complete source codec or full required dataset/capability scope. No valid waiver/full parity."
        elif codec == "dzip":
            current_limitations = "Exact TF1.14 CPU/GPU runtime is restored and probed. Current public native-seeded untrained initialization is distinct from original TF initialization and trained PRNN; no DZip source model/training/codec execution occurred in the fresh diagnostic. Full required capabilities and legal four-state classification remain unclosed."
        elif codec == "lzss-dipperstein-c":
            current_limitations = "New r3 supplement verifies exact original lzss/bitfile/optlist authority trees/gitlinks and selected vendor bytes. Original native API/affected-path semantic baseline, complete capability and isolated delivery still need acceptance; the earlier local missing-authority snapshot is historical."
        source = source_map[codec]
        rewrite = entry["route"] == "SOURCE_REWRITE"
        environment = codec in {"deepzip", "dzip"}
        scoped_source = entry["prior_scoped_evidence"]
        family_rows = []
        for old in entry["gates"]:
            gate = old["gate"]
            status = "UNKNOWN"
            failure_kind = None
            checks = []
            if gate in {"G0", "N0"}:
                checks = [
                    subitem("route_object_declared_profile", "SATISFIED", "Actual core route, P0/P1/P2 role, declared input/ISA/feature scope and Bench source identity are explicitly recorded; no algorithms added.", ("routes",)),
                    subitem("selected_source_identity", "SATISFIED", f"Current selected source tree has an exact-set byte PASS ({source['installed_source_closure'].get('expected_count', 'composite')} files); this does not establish the complete public source capability universe.", ("sources_r4",)),
                ]
                if gate == "G0" and codec in {"abba", "fabba", "deepzip"}:
                    checks.append(subitem("logical_identity_and_duplicate_stage_decision", "SATISFIED", "Existing package owns stable logical AlgorithmID and ImplementationID, P2 pipeline classification and explicit duplicate-stage decision; this review checked the current manifest bytes.", (f"{codec}_manifest", "routes")))
                    status = "PASS"
                elif gate == "G0":
                    finding = "DZip manifest has algorithm_id/object_level/G0 decision but no top-level implementation_id; cross-file independent implementation identity review is pending." if codec == "dzip" else "Bench content IDs and core provenance are recorded; a current independent logical AlgorithmID/ImplementationID plus duplicate/object gate sign-off is not in the reviewed inputs."
                    checks.append(subitem("independent_logical_identity_review", "PENDING", finding, ("routes",)))
                else:
                    checks.append(subitem("complete_source_capability_universe_and_profile_mapping", "PENDING", "Current target is declared, but full upstream public API/build/docs/tests/CI capability discovery and its mapping to the native target have not been independently closed. §114 permits a predeclared limited target; unopened capabilities must remain in SourceCapabilityMatrix.", ("routes", "current_four_matrices")))
            elif gate in {"G1", "N1"}:
                checks = [
                    subitem("selected_source_tree_and_authority", "SATISFIED", "33/33 selected-tree exact byte/set receipts are retained, with independent pinned Git or prior immutable selection locks as stated per row.", ("sources_r4",)),
                    subitem("declared_execution_dependencies", "SATISFIED_SCOPED", entry["declared_execution_dependency_result"] + "; existing factory-checked dependencies are not a complete toolchain consumption trace.", ("ledger",)),
                    subitem("actual_complete_source_build_runtime_closure", "PENDING", "Full TU/include/generated/linker-script/CRT/static/archive/tool/interpreter/runtime/model consumption closure and per-consumption identity await build v5 review; old 67-profile inventory and independent r1 findings remain recorded.", ("old_build_gap_inventory", "build_independent_review_r1")),
                    subitem("license_SBOM_and_complete_public_capability_inventory", "PENDING", "Existing provenance and license decisions are retained. This review has not closed all per-file roles/generated provenance, redistribution scope, SBOM and source public/API/build/docs/tests/CI capabilities.", ("routes",)),
                ]
                if codec == "lzss-dipperstein-c":
                    checks.append(subitem("dipperstein_external_authority", "SATISFIED", "The newer r3 supplement recovered exact lzss, bitfile and optlist Git trees/gitlinks and matched selected vendor bytes; the earlier local-only missing-authority snapshot remains historical.", ("upstream_authority_r3",)))
                if codec == "elf":
                    checks.append(subitem("elf_pinned_full_tree", "SATISFIED", "The correct VLDB2023 release full Git tree is verified by the new r3 supplement; the old wrong/missing-tree snapshot is preserved.", ("upstream_authority_r3",)))
                if codec in {"fabba", "deepzip", "dzip"}:
                    recovered = next(i for i in source_supplement["retained_source_snapshots"] if i["codec_key"] == codec)
                    checks.append(subitem("old_source_snapshot_recovered", "SATISFIED_SCOPED", f"Original selected {recovered['snapshot_file_count']}-file source snapshot recovered to a new audit directory and exact-set checked; the incomplete original local snapshot remains unchanged.", ("source_supplement_r2",)))
                if environment:
                    checks.append(subitem("exact_legacy_environment_and_device", "SATISFIED_SCOPED", "71 exact SHA/size locked packages were acquired; TF1.8 DeepZip and TF1.14 DZip CPU/GPU isolated environments import/device/runtime probes PASS. 8170 base code/data and DZip 3073 CPU/2934 GPU Python/ELF files MATCH. No model/codec/training executed by this recovery.", ("environment_recovery",)))
            elif gate in {"G2", "N2"}:
                checks = [
                    subitem("current_Bench_domain_state_parameters", "SATISFIED_SCOPED", route["registered_profile_scope"] + "; dtype/topology/config/device/rejection and explicit wrapper boundaries are declared before existing current qualification.", ("routes", "current_four_matrices")),
                    subitem("raw_frame_oracle_deviation_boundary", "SATISFIED_SCOPED", current_limitations, ("routes", "fresh_scoped_source", "fresh_fixed_weight_source_r2") if codec == "deepzip" else ("routes", "fresh_scoped_source")),
                    subitem("complete_independent_contract_and_before_execution_test_plan", "PENDING", "Current independent mathematical/bitstream/error/API/resource/source-defect contract, exact oracle, compatible real-data plan and all required CAP owner/test/platform classifications still need joint review; Bench manifests do not replace this contract.", ("routes", "current_four_matrices")),
                ]
                if codec == "dzip":
                    checks.append(subitem("legal_four_state_classification", "UNMET", "Historical reference.gpu_bpc_estimator=REFERENCE_ONLY is outside the standard four classes. Preserve it and conduct a new evidence-based classification; do not silently recast it as NOT_APPLICABLE.", ("dzip_matrix",)))
                    status = "FAIL"
                    failure_kind = "ACCEPTANCE_CLASSIFICATION_CONTRACT_UNMET"
            elif gate in {"G3", "N3"}:
                checks = [
                    subitem("current_native_Bench_correctness_and_independent_recovery", "SATISFIED_SCOPED", "Current active33-r2 has 41 SCOPED_PASS cases: correctness, boundary/preflight, stream identity, physical cost and a new independent worker recovery. This evidence is for the declared current input/fixture/config cases.", ("current_bench_qualification", "current_four_matrices")),
                    subitem("current_direct_CPP_tests_and_sanitizer_boundary", "SATISFIED_SCOPED" if codec in cap_map else "PENDING", "For ABBA/fABBA/DeepZip/DZip the current package/core and framework release/sanitizer report contains 8 profiles/32 nonempty CTests, preserving external-uninstrumented runtime limitations. Other direct-API test mapping requires final review.", ("current_completed_api",)),
                    subitem("same_source_canonical_real_data_and_full_required_safety", "PENDING", "Each promised independent API must map ownership/capacity/guard/length/malformed/failure/reuse/finalize/reset and source/canonical same-data tests to its frozen contract; current Bench success alone cannot complete this mapping.", ("routes", "fresh_scoped_source")),
                ]
                if rewrite:
                    checks.append(subitem("saved_source_differential", "SATISFIED_SCOPED", scoped_source + " " + current_limitations, ("fresh_scoped_source", "routes")))
                if codec == "deepzip":
                    checks += [
                        subitem("fresh_current_fixed_weights_source_GPU_probabilities", "SATISFIED_SCOPED", "Current biGRU/alphabet4/3 contexts: original exporter reexport EXACT current model bytes; 4 source CudnnRNN GPU nodes actually executed; 12 probabilities satisfy the before-execution frozen3e-5 absolute tolerance (maxabs1.4901161193847656e-08). Current registered .so actual loading is observed by the source receipt.", ("fresh_fixed_weight_source_r2",)),
                        subitem("same_source_probability_CDF_conversion", "SATISFIED_SCOPED", "Original NumPy and current conversion receive identical source probabilities; all15CDF integers match exactly.", ("fresh_fixed_weight_source_r2",)),
                        subitem("independent_prediction_full_CDF", "FAIL_SCOPED_SOURCE_COMPARISON", "1/15 CDF integers differs: arange(64)%4 context final total source10000004, native10000003. All commands in r2 exit0; this is an observed semantic difference, not a crash. Probability tolerance must not hide it or grant source bitstream parity.", ("fresh_fixed_weight_source_r2",)),
                    ]
                if codec in cap_map:
                    checks.append(subitem("complete_REQUIRED_canonical_source_functionality", "NOT_TESTED", cap_by_codec[codec]["capabilities"][0]["unmet_subitems"][0], ("cap_inventory", "fresh_scoped_source", "environment_recovery") if environment else ("cap_inventory", "fresh_scoped_source")))
                    status = "FAIL"
                    failure_kind = "ACCEPTANCE_REQUIRED_FUNCTIONAL_SUBITEMS_NOT_TESTED"
            elif gate == "G4":
                checks = [
                    subitem("package_owned_CPP_API_and_CLI_present", "SATISFIED_SCOPED", "Current package/core public headers and standalone CLI/preflight reports are preserved; the selected source-tree receipt binds the installed files.", ("sources_r4", "current_completed_api", "routes")),
                    subitem("current_Bench_binding_and_FinalBits", "SATISFIED_SCOPED", "41 current scoped qualification cases verify independent recovery and complete physical-cost accounting; direct independent API acceptance remains a separate evidence boundary.", ("current_bench_qualification",)),
                    subitem("all_required_independent_API_lifecycle_and_capacity_tests", "PENDING", "Every original required capability must be callable/queryable through the package's own API with lifecycle/capacity/malformed/cold-recovery tests outside Bench. A current complete required-to-API test mapping is not accepted.", ("routes", "cap_inventory")),
                ]
                if environment:
                    checks.append(subitem("required_source_model_GPU_training_API_execution", "NOT_TESTED", "Current CPU seeded/fixed fixture API tests do not execute the required original checkpoint/model/training/GPU functionality via independent APIs.", ("cap_inventory", "current_completed_api")))
                    status = "FAIL"
                    failure_kind = "ACCEPTANCE_REQUIRED_API_SUBITEMS_NOT_TESTED"
            elif gate == "G5":
                if codec == "abba":
                    checks = [subitem("frozen_CAP_no_required_optimized_variant", "SATISFIED_SCOPED", "The existing frozen matrix marks SIMD/internal threading NOT_APPLICABLE and its two REQUIRED rows are functional paths; no optimization is invented to fill this gate.", ("abba_matrix",)),
                              subitem("full_source_inventory_confirmation", "PENDING", "A complete source public/build/runtime inventory must confirm this classification before full G5 N/A can be signed; historical AArch64 portability evidence is kept separately.", ("abba_matrix", "routes"))]
                elif codec == "fabba":
                    checks = [subitem("finite_partition_oracle_cases", "SATISFIED_SCOPED", "32 partition cases retain their exact stabilized-source oracle scope; historical bounded-worker/tail/concurrency/TSan/AArch64 claims remain historical.", ("fresh_scoped_source", "fabba_matrix")),
                              subitem("complete_required_threading_variant_observed_and_differential", "NOT_TESTED", "Current full original-source required threading execution, same real data, concurrency/race/platform and deterministic tail contract is not accepted.", ("fabba_matrix",))]
                    status = "FAIL"
                    failure_kind = "ACCEPTANCE_REQUIRED_OPTIMIZED_SUBITEMS_NOT_TESTED"
                elif environment:
                    checks = [subitem("runtime_device_availability", "SATISFIED_SCOPED", "Restored legacy TF GPU environment/device/runtime probes PASS on an accessible RTX2070. The ordinary sandbox's old exit9 is not evidence that the host has no GPU.", ("environment_recovery",)),
                              subitem("complete_required_GPU_prediction_or_bootstrap_execution", "NOT_TESTED", "Required source/native GPU predictors or CUDA bootstrap training, exact model/state/CDF same-real-data differential and resource/tail/platform validation are not executed in the restored environment at this freeze.", (f"{codec}_matrix", "environment_recovery"))]
                    status = "FAIL"
                    failure_kind = "ACCEPTANCE_REQUIRED_OPTIMIZED_SUBITEMS_NOT_TESTED"
                else:
                    checks = [subitem("declared_current_variant", "SATISFIED_SCOPED", "Current execution scope and original source raw/semantic evidence are explicit; no imaginary scalar/SIMD/GPU qualification is added.", ("routes", "fresh_scoped_source")),
                              subitem("complete_required_variant_inventory_and_execution", "PENDING", "The independent original capability inventory must first establish applicable optimized requirements or justify N/A; finite profile tests do not decide all source API variants.", ("routes",))]
            elif gate in {"G6", "CAP-GATE"}:
                checks = [
                    subitem("preserved_historical_and_current_scoped_evidence", "SATISFIED_SCOPED", scoped_source + "; no historical PASS or original required classification is overwritten.", ("ledger", "fresh_scoped_source", "current_completed_api")),
                    subitem("complete_CAP_inventory_classification_function_API_optimized_closure", "NOT_TESTED" if codec in cap_map else "MISSING_CURRENT_COMPLETE_REVIEW", "Current complete G1-CAP/G2-CAP/G3-CAP/G4-CAP/G5-CAP/G6-CAP acceptance is missing. Required full-scope test subitems remain NOT_TESTED; seven minimal-core entries have no accepted complete four-state capability review in the reviewed inputs. This is an acceptance condition failure, not a codec execution failure.", ("cap_inventory", "routes")),
                ]
                if gate == "G6":
                    checks += [
                        subitem("current_independent_release_and_report_index", "PENDING", "A current isolated consumer source/API/driver/dependency/cold-build/test release, SBOM/license/reproducibility/index and dataset_validation_report must be accepted independently of Bench.", ("routes", "sources_r4")),
                        subitem("independent_performance_and_portability", "PENDING", "Current package's applicable independent performance/portability/security/docs evidence must be reviewed; Bench FORMAL does not replace it.", ("routes",)),
                    ]
                status = "FAIL"
                failure_kind = "ACCEPTANCE_REQUIRED_CAPABILITY_NOT_TESTED_OR_CLOSURE_MISSING"
            elif gate == "N4":
                checks = [
                    subitem("independent_pinned_source_baseline_bytes", "SATISFIED_SCOPED", "Independent pinned source/selected original bytes are now available according to source r4 and newer authority supplements; bytes alone do not execute an oracle.", ("sources_r4", "upstream_authority_r3")),
                    subitem("current_Bench_source_domain_profile", "SATISFIED_SCOPED", scoped_source + " " + current_limitations, ("routes", "current_four_matrices")),
                    subitem("native_original_API_or_patched_affected_path_differential", "PENDING", "For NATIVE_REUSE run the frozen original/public API driver and verify actual source call; for NATIVE_PORT compare original and patched affected paths with same input/config/state/model and frozen raw/frame target. Complete current independent source-driver evidence is not accepted.", ("routes",)),
                    subitem("compatible_real_data_requested_available_actual_variants", "PENDING", "Same canonical real-data artifacts and declared ISA/threads/platform execution, tail/resources/parallel boundaries must be mapped to the native contract; unopened source capabilities remain recorded.", ("routes",)),
                ]
            elif gate == "N5":
                checks = [
                    subitem("selected_source_API_build_records_and_dependencies_available", "SATISFIED_SCOPED", "Frozen selected source/API and existing build/factory dependency receipts are indexed; source tree and Bench binding qualification remain distinct.", ("sources_r4", "old_build_gap_inventory", "current_bench_qualification")),
                    subitem("isolated_independent_consumer_build_test_recovery", "PENDING", "Current independent consumption must build/test/cold-restore using only the declared source/public API/driver/dependencies and recovery assets, with replayable patches plus product/SBOM/license/report indexes; no final isolated release receipt is in the reviewed inputs.", ("routes",)),
                    subitem("Bench_handoff_scope", "SATISFIED_SCOPED", "Current Bench consumption interface/input/features/unsupported scope is explicit in registry and route review.", ("routes",)),
                    subitem("FORMAL_prerequisite", "NOT_APPLICABLE", "§114.7 explicitly says N5 does not require formal performance; pending FORMAL cannot be used to defer independent delivery.", ("standard",)),
                ]
            else:
                raise ValueError("unhandled gate " + gate)
            require(checks, f"empty gate review {codec}:{gate}")
            item = {"codec_key": codec, "gate": gate, "status": status,
                    "criterion_key": old["criterion_key"], "criterion": old["criterion"],
                    "scope": entry["scope_for_next_acceptance"],
                    "reviewer": "/root/matrix_sync_review",
                    "subitems": checks,
                    "failure_kind": failure_kind,
                    "recorded_execution_failure": False,
                    "recorded_source_differential_failure": codec == "deepzip" and gate in {"G3", "G6", "CAP-GATE"},
                    "recorded_codec_roundtrip_failure": False,
                    "new_codec_execution": False,
                    "historical_scoped_PASS_preserved": True,
                    "complete_acceptance_granted": status == "PASS",
                    "status_reason": "All G0 identity/dedup/object subitems re-reviewed against current immutable input references." if status == "PASS" else "Required complete acceptance subitems are explicitly unmet/NOT_TESTED; previous finite test success remains valid only for its scope." if status == "FAIL" else "Listed satisfied subitems are retained; named closure/contract/API/variant/independent-delivery review remains pending."}
            family_rows.append(item)
            gate_rows.append(item)
        entries.append({"codec_key": codec, "route": entry["route"],
                        "object_level": entry["object_level"],
                        "scope": entry["scope_for_next_acceptance"],
                        "registered_profile": entry["registered_profile"],
                        "registered_input_and_execution": {"input": route["declared_input"], "execution": route["declared_execution"]},
                        "prior_scoped_evidence": scoped_source,
                        "historical_route_limitations_preserved": route["limitations"],
                        "current_limitations_after_new_receipts": current_limitations,
                        "full_upstream_scope_not_reduced_to_Bench_profile": True,
                        "all_required_gates_accepted": all(g["status"] in {"PASS", "N/A"} for g in family_rows),
                        "gates": family_rows})
    counts = dict(Counter(item["status"] for item in gate_rows))
    require(len(entries) == 33 and len(gate_rows) == 220, "incorrect review shape")
    require(counts.get("PASS") == 3, "only three explicitly reviewed G0 may pass")
    require(all(not item["recorded_execution_failure"] for item in gate_rows), "static review cannot invent execution failures")
    require(all(ref(paths[key]) == value for key, value in inputs.items()), "input changed during static review")
    result = {"schema_version": "tscb.independent-gate-acceptance-review.v1",
              "created_at": datetime.now(timezone.utc).isoformat(),
              "review_kind": "READ_ONLY_CONTRACT_AND_RECEIPT_REVIEW_NO_CODEC_OR_HEAVY_HASHING",
              "status": "COMPLETE_REVIEW_WITH_EXPLICIT_ACCEPTANCE_FAILURES_AND_PENDING_SUBITEMS",
              "driver": ref(Path(__file__)), "inputs": inputs,
              "entry_count": len(entries), "applicable_gate_row_count": len(gate_rows),
              "gate_status_counts": counts,
              "acceptance_failure_is_not_execution_failure": True,
              "standard_rules": {
                  "required_missing_fail_not_tested": "§3 CAP-GATE: any REQUIRED_PARITY MISSING/FAIL/NOT_TESTED makes CAP-GATE FAIL and blocks REWRITE_DONE.",
                  "G6_requires_CAP_closure": "§3 G6: all required PASS, valid waiver, no UNCLASSIFIED/NOT_TESTED/fallback; current independent release mandatory.",
                  "native_profile": "§114.1/114.7 permits predeclared current profile, retaining complete source capabilities; every applicable N0-N5 required item must pass.",
                  "independent_delivery": "N5 has no FORMAL prerequisite; Bench consumption/FORMAL and source package acceptance are separate.",
                  "evidence": "§115 current identity/scope/change validity; historical replay cannot become fresh source parity.",
              },
              "G0_current_logical_identity_reviews": identity_reviews,
              "pending_new_evidence": pending,
              "existing_frozen_capability_reviews": capability_reviews,
              "entries": entries,
              "recorded_codec_roundtrip_failure_count": 0,
              "external_fresh_source_diagnostic": {
                  "source_receipt": inputs["fresh_fixed_weight_source_r2"],
                  "scope": learned["scope"], "checks": learned["checks"],
                  "current_attempt_command_failures": 0,
                  "scoped_independent_CDF_comparison_failures": 1,
                  "preserved_first_attempt_execution_failure": learned["execution_failures"]["r1"],
                  "executed_by_this_review": False,
                  "source_bitstream_full_pipeline_CAP_granted": False,
              },
              "new_codec_training_model_or_performance_execution": False,
              "full_N_G_CAP_acceptance_granted": False,
              "FULL_PARITY_REWRITE_DONE_or_FORMAL_granted": False,
              "main_matrix_or_historical_evidence_modified": False,
              "inputs_unchanged": True,
              "claim_boundary": "This current full-scope acceptance review grants exactly three G0 identity gates. FAIL means a mandatory acceptance condition is not satisfied, never that an unexecuted codec run failed. The prior 220 UNKNOWN inventory is preserved as its earlier snapshot; exact environment and newer source-authority recovery resolve those earlier availability findings without rewriting history. Append new evidence in a separate supplement."}
    with output.open("xb") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2).encode() + b"\n")
    print(json.dumps({"entry_count": len(entries), "gate_rows": len(gate_rows),
                      "gate_status_counts": counts, "execution_failures": 0,
                      "inputs_unchanged": True}))


if __name__ == "__main__":
    main()
