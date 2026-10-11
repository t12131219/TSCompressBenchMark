#!/usr/bin/env python3
"""Publish clause-level V3.2 acceptance from revalidated current release evidence.

``map`` writes a reviewable obligation-to-proof map, with no acceptance claims.
``publish`` first repeats the release audit, then writes separate, immutable
proofs and an enriched copy of the complete requirement ledger. It never edits
the three specification sources, old runs, or the coverage-only source ledger.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "docs/reviews/v32_requirement_ledger_20261010.json"
MAPPING = ROOT / "docs/reviews/v32_acceptance_mapping_20261010.json"
COMPARISONS = (
    "byte",
    "f64",
    "f32",
    "i16",
    "abs",
    "quality",
    "model",
    "cold",
    "api",
    "timestamp",
    "entropy",
    "u8",
)
WORKLOADS = ("stream", "query-fresh", "query-warm")

# These are independently assessed proof obligations, not keyword-derived PASS
# rules. The materialized map retains one explicit row per original source row.
FACETS: dict[str, dict[str, Any]] = {
    "decision_context": {
        "claim": (
            "Every formal experiment freezes its specific user decision, research question, "
            "fixed target population, primary estimands and scope before measurement."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": [
            "experiment_decision.json",
            "execution_plan.json",
            "workload_plan.json",
            "plan.json",
        ],
        "sources": [
            "src/tscompbench/comparison/decision.py",
            "src/tscompbench/comparison/runner.py",
            "src/tscompbench/comparison/workload_runner.py",
            "src/tscompbench/comparison/pipeline_runner.py",
        ],
        "tests": [
            "tests/unit/test_experiment_decision.py",
            "tests/unit/test_pipeline_decision_binding.py",
        ],
    },
    "uncompressed_reference": {
        "claim": (
            "Independent size baseline preserves the complete uncompressed original object "
            "and a paid schema reference at the matched Track/object boundary; "
            "native API sizes stay separate and no formal performance is fabricated."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": ["uncompressed_reference.json", "uncompressed_reference.md"],
        "sources": ["tools/audit_v32_uncompressed_reference.py"],
        "tests": ["tests/unit/test_v32_uncompressed_reference.py"],
    },
    "channel_collection": {
        "claim": (
            "Versioned asynchronous/ragged channel collections preserve independent "
            "T/V/validity, ordered topology, identities and paid full collection recovery."
        ),
        "lanes": [],
        "files": [],
        "sources": [
            "src/tscompbench/pipelines/channel_collection.py",
            "tools/qualify_v32_channel_collection.py",
        ],
        "tests": ["tests/unit/test_channel_collection.py"],
    },
    "rate_summary_interfaces": {
        "claim": (
            "Dedicated rate/summary output-property validator interfaces and failure "
            "fixtures only; no registered rate/summary algorithm or formal group."
        ),
        "lanes": [],
        "files": [],
        "sources": ["src/tscompbench/validation/task_validators.py"],
        "tests": ["tests/unit/test_lossy_validation.py"],
    },
    "interruption_resume": {
        "claim": (
            "Durable STARTED attempts, interruption/budget accounting and immutable "
            "attempt artifacts; no unknown attempt rerun or raw replacement."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": [
            "events.jsonl",
            "workload_events.jsonl",
            "pipeline_events.jsonl",
            "comparison_trials.jsonl",
            "workload_trials.jsonl",
            "trials.jsonl",
            "resume_verification.json",
        ],
        "sources": [
            "src/tscompbench/comparison/runner.py",
            "src/tscompbench/comparison/workload_runner.py",
            "src/tscompbench/comparison/pipeline_runner.py",
        ],
        "tests": [
            "tests/unit/test_v32_schedule.py",
            "tests/unit/test_v32_comparison_stage_resume.py",
            "tests/integration/test_v32_pipeline_comparison.py",
            "tests/unit/test_pipeline_interrupted_resume.py",
        ],
    },
    "specs": {
        "claim": (
            "Closed versioned task/corpus/config/measurement/analysis contracts and identities."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": ["bundle.json", "execution_plan.json", "workload_plan.json", "plan.json"],
        "sources": [
            "src/tscompbench/comparison/models.py",
            "src/tscompbench/comparison/schema.py",
            "src/tscompbench/comparison/projection.py",
            "src/tscompbench/ids/canonical_json.py",
        ],
        "tests": [
            "tests/unit/test_comparison_specs.py",
            "tests/unit/test_v32_measurement_protocol.py",
        ],
    },
    "canonical": {
        "claim": "Canonical reader/importer, semantic whitelist v2 and legacy identity separation.",
        "lanes": ["byte", "f32", "f64", "i16", "timestamp", "pipeline"],
        "files": ["bundle.json", "execution_plan.json", "qualification.json", "plan.json"],
        "sources": [
            "src/tscompbench/datasets/canonical.py",
            "src/tscompbench/datasets/canonical_source.py",
        ],
        "tests": [
            "tests/unit/test_canonical_source.py",
            "tests/unit/test_canonical.py",
            "tests/contracts/test_dataset_manifests.py",
        ],
    },
    "corpus": {
        "claim": "Frozen real-source derivation/splits and fixed original work denominators.",
        "lanes": list(COMPARISONS),
        "files": ["bundle.json", "execution_plan.json", "analysis.json"],
        "sources": [
            "src/tscompbench/comparison/planning.py",
            "src/tscompbench/comparison/runner.py",
        ],
        "tests": [
            "tests/unit/test_v32_comparison_bundles.py",
            "tests/unit/test_v32_quality_model_bundles.py",
            "tests/unit/test_comparison_specs.py",
        ],
    },
    "candidate": {
        "claim": (
            "166 current records mapped to legacy 163 namespace and explicit "
            "destinations; no majority claim."
        ),
        "lanes": ["active"],
        "files": ["plan.json", "role_ledger.json"],
        "sources": [
            "registry/candidate_integration_ledger.json",
            "registry/algorithm_scope.json",
            "tools/build_v32_active_role_ledger.py",
        ],
        "tests": [
            "tests/contracts/test_candidate_integration_ledger.py",
            "tests/contracts/test_algorithm_scope.py",
        ],
    },
    "admission": {
        "claim": (
            "Predeclared roles/expectations, precise refusal origin and "
            "unchanged core denominators."
        ),
        "lanes": [*COMPARISONS, "active"],
        "files": [
            "execution_plan.json",
            "qualification.json",
            "analysis.json",
            "four_matrices.json",
        ],
        "sources": [
            "src/tscompbench/comparison/planning.py",
            "src/tscompbench/codecs/negotiation.py",
        ],
        "tests": [
            "tests/unit/test_comparison_specs.py",
            "tests/unit/test_comparison_analysis.py",
            "tests/unit/test_source_domain_rejection.py",
        ],
    },
    "active": {
        "claim": (
            "All 33 active entries and 41 declared-track fixture/config cases "
            "complete scoped qualification."
        ),
        "lanes": ["active"],
        "files": ["plan.json", "summary.json", "four_matrices.json", "role_ledger.json"],
        "sources": [
            "tools/qualify_v32_active_entries.py",
            "src/tscompbench/execution/preflight.py",
        ],
        "tests": [
            "tests/unit/test_v32_active_entries.py",
            "tests/contracts/test_codec_registry.py",
        ],
    },
    "recovery": {
        "claim": (
            "Clean independent decoder receives only paid stream/context and "
            "materializes restored objects."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline", "active"],
        "files": [
            "qualification.json",
            "comparison_trials.jsonl",
            "workload_trials.jsonl",
            "trials.jsonl",
            "summary.json",
        ],
        "sources": [
            "src/tscompbench/execution/recovery.py",
            "src/tscompbench/execution/repetition.py",
            "src/tscompbench/pipelines/runtime.py",
        ],
        "tests": [
            "tests/unit/test_pipeline_objects.py",
            "tests/integration/test_v32_comparison_runner.py",
            "tests/unit/test_source_reject_composite.py",
        ],
    },
    "pipeline": {
        "claim": (
            "Real LZ4/Zstd P2 f32 and mixed ND T/V/validity tasks, all "
            "columns/blocks/raw tail and cold recovery."
        ),
        "lanes": ["pipeline"],
        "files": [
            "plan.json",
            "qualification.json",
            "pilot.json",
            "trials.jsonl",
            "report.json",
            "buffer_cost_audit.json",
        ],
        "sources": [
            "src/tscompbench/pipelines/models.py",
            "src/tscompbench/pipelines/runtime.py",
            "src/tscompbench/pipelines/adapter.py",
        ],
        "tests": [
            "tests/unit/test_pipeline_objects.py",
            "tests/unit/test_pipeline_adapter.py",
            "tests/integration/test_v32_pipeline_comparison.py",
        ],
    },
    "cost": {
        "claim": (
            "Original/adapted/codec/native/final costs, paid dependencies, "
            "exact physical bits and separate auxiliary observations."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": [
            "analysis.json",
            "analysis_extensions.json",
            "workload_analysis.json",
            "report.json",
            "buffer_cost_audit.json",
        ],
        "sources": ["src/tscompbench/accounting/ledger.py", "tools/audit_v32_buffer_costs.py"],
        "tests": [
            "tests/unit/test_accounting.py",
            "tests/unit/test_v32_buffer_costs.py",
            "tests/unit/test_comparison_analysis_extensions.py",
        ],
    },
    "api": {
        "claim": (
            "Independent COMMON_NATIVE_API/CORE profile with identical actual "
            "API data and declared external-clock boundary."
        ),
        "lanes": ["api"],
        "files": [
            "bundle.json",
            "execution_plan.json",
            "qualification.json",
            "pilot.json",
            "comparison_trials.jsonl",
            "analysis.json",
            "buffer_cost_audit.json",
        ],
        "sources": [
            "src/tscompbench/comparison/projection.py",
            "src/tscompbench/execution/repetition.py",
        ],
        "tests": [
            "tests/unit/test_comparison_specs.py",
            "tests/integration/test_v32_workload_runner.py",
            "tests/unit/test_comparison_analysis_extensions.py",
        ],
    },
    "measurement": {
        "claim": (
            "Development pilots, worker-local warmup or measured cold "
            "startup, real clocks/harness gates and frozen budgets."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": [
            "bundle.json",
            "pilot.json",
            "workload_pilot.json",
            "comparison_trials.jsonl",
            "workload_trials.jsonl",
            "trials.jsonl",
        ],
        "sources": [
            "src/tscompbench/measurement/v32_protocol.py",
            "src/tscompbench/execution/cold_driver.py",
            "src/tscompbench/execution/workload_driver.py",
        ],
        "tests": [
            "tests/unit/test_v32_measurement_protocol.py",
            "tests/integration/test_v32_workload_runner.py",
        ],
    },
    "resources": {
        "claim": (
            "Serial shared-host leases, actual affinity/NUMA/threads and "
            "fixed model pools; collector unavailability remains explicit."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline", "active"],
        "files": [
            "bundle.json",
            "plan.json",
            "comparison_trials.jsonl",
            "workload_trials.jsonl",
            "trials.jsonl",
            "summary.json",
        ],
        "sources": [
            "src/tscompbench/measurement/resource_lease.py",
            "src/tscompbench/measurement/thread_monitor.py",
            "src/tscompbench/execution/isolation.py",
        ],
        "tests": [
            "tests/unit/test_v32_resource_lease.py",
            "tests/unit/test_execution_validation.py",
        ],
    },
    "schedule": {
        "claim": (
            "Frozen interleaved schedules, real trial/block pairing and immutable no-op resume."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": [
            "execution_plan.json",
            "comparison_trials.jsonl",
            "workload_trials.jsonl",
            "trials.jsonl",
            "resume_verification.json",
        ],
        "sources": [
            "src/tscompbench/execution/schedule.py",
            "src/tscompbench/comparison/runner.py",
        ],
        "tests": [
            "tests/unit/test_v32_schedule.py",
            "tests/unit/test_v32_comparison_stage_resume.py",
        ],
    },
    "analysis": {
        "claim": (
            "Versioned paired block analysis, fixed-corpus inference, "
            "multiplicity/rank/Pareto and honest INCONCLUSIVE."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": [
            "analysis.json",
            "analysis_extensions.json",
            "workload_analysis.json",
            "report.json",
        ],
        "sources": [
            "src/tscompbench/comparison/analysis.py",
            "src/tscompbench/comparison/analysis_extensions.py",
        ],
        "tests": [
            "tests/unit/test_comparison_analysis.py",
            "tests/unit/test_comparison_analysis_extensions.py",
            "tests/unit/test_v32_analysis_calibration.py",
        ],
    },
    "report": {
        "claim": (
            "All twelve comparison groups and three workloads/P2 rebuild reports "
            "from raw with current full coverage."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline"],
        "files": [
            "analysis.json",
            "report.html",
            "workload_analysis.json",
            "workload_report.html",
            "report.json",
        ],
        "sources": [
            "src/tscompbench/comparison/report_renderer.py",
            "tools/audit_v32_completion.py",
        ],
        "tests": [
            "tests/unit/test_comparison_report_renderer.py",
            "tests/unit/test_v32_completion_audit.py",
        ],
    },
    "loss": {
        "claim": (
            "Exact original-domain error/IEEE/null validation and "
            "rate/summary output-property interfaces."
        ),
        "lanes": ["abs", "quality", "pipeline"],
        "files": [
            "qualification.json",
            "comparison_trials.jsonl",
            "analysis_extensions.json",
            "report.json",
        ],
        "sources": [
            "src/tscompbench/validation/lossy.py",
            "src/tscompbench/validation/correctness.py",
            "src/tscompbench/validation/task_validators.py",
        ],
        "tests": ["tests/unit/test_lossy_validation.py", "tests/unit/test_execution_validation.py"],
    },
    "quality": {
        "claim": (
            "Real complete-grid ABBA/fABBA empirical quality curves and "
            "separately guaranteed ABS methods."
        ),
        "lanes": ["abs", "quality"],
        "files": [
            "bundle.json",
            "comparison_trials.jsonl",
            "analysis.json",
            "analysis_extensions.json",
        ],
        "sources": [
            "tools/build_v32_comparison_bundles.py",
            "src/tscompbench/comparison/analysis_extensions.py",
        ],
        "tests": [
            "tests/unit/test_v32_quality_model_bundles.py",
            "tests/unit/test_comparison_specs.py",
        ],
    },
    "model": {
        "claim": (
            "DeepZip/DZip on derived UINT8 base-4 symbols with complete model "
            "frames and actual thread budgets; training overlap UNKNOWN."
        ),
        "lanes": ["model"],
        "files": [
            "bundle.json",
            "qualification.json",
            "pilot.json",
            "comparison_trials.jsonl",
            "analysis.json",
            "analysis_extensions.json",
            "buffer_cost_audit.json",
        ],
        "sources": [
            "src/tscompbench/adapters/completed_rewrites.py",
            "src/tscompbench/pipelines/byte_symbol_bridge.py",
        ],
        "tests": [
            "tests/unit/test_v32_quality_model_bundles.py",
            "tests/adapters/test_completed_rewrites.py",
        ],
    },
    "stream": {
        "claim": (
            "Five real incremental methods, known-length fixed-block "
            "finalized-object profile and independent complete recovery."
        ),
        "lanes": ["stream"],
        "files": [
            "workload_plan.json",
            "workload_pilot.json",
            "workload_trials.jsonl",
            "workload_analysis.json",
            "buffer_cost_audit.json",
        ],
        "sources": [
            "src/tscompbench/execution/workload_driver.py",
            "src/tscompbench/adapters/native_streaming.py",
        ],
        "tests": [
            "tests/unit/test_workload_driver.py",
            "tests/integration/test_v32_workload_runner.py",
            "tests/adapters/test_native_streaming_codecs.py",
        ],
    },
    "query": {
        "claim": (
            "Actual compressed point/range/column projection API; separate "
            "fresh/reused sessions, owned results and logical amplification."
        ),
        "lanes": ["query-fresh", "query-warm"],
        "files": [
            "workload_plan.json",
            "workload_pilot.json",
            "workload_trials.jsonl",
            "workload_analysis.json",
            "buffer_cost_audit.json",
        ],
        "sources": [
            "src/tscompbench/execution/workload_driver.py",
            "src/tscompbench/adapters/neats.py",
        ],
        "tests": [
            "tests/unit/test_workload_driver.py",
            "tests/integration/test_v32_workload_runner.py",
        ],
    },
    "safety": {
        "claim": (
            "Actual entry preflight/boundary evidence and current SIMDComp "
            "SDK independent safety audit."
        ),
        "lanes": ["active", "sdk"],
        "files": ["summary.json", "plan.json"],
        "sources": [
            "src/tscompbench/validation/boundary.py",
            "src/tscompbench/adapters/native_buffers.py",
            "tools/audit_simdcomp_sdk.py",
        ],
        "tests": [
            "tests/unit/test_execution_validation.py",
            "tests/unit/test_simdcomp_source_evidence.py",
            "tests/unit/test_simdcomp_avx2_native_evidence.py",
        ],
    },
    "legacy": {
        "claim": (
            "Read-only original legacy records and descriptive migration "
            "without fabricated new qualification."
        ),
        "lanes": [],
        "files": [],
        "sources": ["tools/migrate_legacy_v32_analysis.py"],
        "tests": ["tests/unit/test_legacy_v32_migration.py"],
    },
    "release": {
        "claim": (
            "Current CPU scope release only after lane-specific audit, full "
            "suite, SDK, resume and auxiliary cost gates."
        ),
        "lanes": [*COMPARISONS, *WORKLOADS, "pipeline", "active", "sdk"],
        "files": [
            "analysis.json",
            "workload_analysis.json",
            "report.json",
            "summary.json",
            "resume_verification.json",
        ],
        "sources": ["tools/audit_v32_completion.py", "tools/publish_v32_requirement_acceptance.py"],
        "tests": ["tests/unit/test_v32_completion_audit.py"],
    },
}

SECTION_FACETS = {
    "preamble": "release legacy candidate",
    "0": "specs corpus report",
    "0.1": "active report recovery",
    "0.2": "specs pipeline api stream query",
    "0.3": "admission active analysis",
    "0.4": "specs legacy candidate",
    "0.5": "specs corpus analysis",
    "0.6": "specs admission report",
    "1": "legacy candidate",
    "1.4": "canonical recovery measurement loss",
    "1.6": "candidate active",
    "2": "specs recovery report",
    "2.1": "specs recovery measurement",
    "2.2": "specs pipeline loss",
    "2.3": "specs legacy",
    "2.4": "canonical pipeline recovery",
    "2.5": "specs schedule legacy",
    "3": "canonical corpus pipeline",
    "3.1": "canonical pipeline loss",
    "3.2": "canonical specs legacy",
    "3.3": "canonical recovery",
    "3.4": "corpus model quality",
    "3.5": "canonical pipeline active safety",
    "4": "admission active",
    "4.1": "admission pipeline",
    "4.2": "specs admission corpus",
    "4.3": "admission active analysis",
    "4.4": "admission analysis",
    "5": "pipeline recovery cost",
    "5.1": "specs pipeline",
    "5.2": "canonical pipeline cost",
    "5.3": "pipeline cost",
    "5.4": "pipeline stream cost",
    "5.5": "pipeline canonical",
    "5.6": "pipeline model loss",
    "5.7": "recovery cost",
    "5.8": "active recovery stream query safety",
    "5.9": "pipeline recovery cost quality",
    "6": "cost recovery",
    "6.1": "cost",
    "6.2": "cost pipeline",
    "6.3": "cost recovery",
    "6.4": "cost model",
    "6.5": "cost",
    "6.6": "cost api model",
    "7": "specs api measurement analysis",
    "7.1": "specs api cost",
    "7.2": "measurement recovery cost",
    "7.3": "api measurement",
    "7.4": "api cost measurement",
    "7.5": "specs api",
    "7.6": "specs corpus",
    "7.7": "specs corpus admission",
    "7.8": "report corpus active",
    "7.9": "quality loss model",
    "7.10": "measurement resources stream query",
    "7.11": "candidate report pipeline model",
    "8": "active safety legacy",
    "8.1": "active candidate",
    "8.2": "active safety",
    "8.3": "active safety specs",
    "8.4": "active safety legacy",
    "9": "recovery loss measurement",
    "9.1": "measurement recovery resources",
    "9.2": "safety active",
    "9.3": "canonical loss pipeline",
    "9.4": "loss quality",
    "10": "measurement schedule analysis report",
    "10.1": "measurement analysis legacy",
    "10.2": "resources",
    "10.3": "schedule analysis",
    "10.4": "admission analysis active",
    "10.5": "report cost analysis",
    "10.6": "release admission specs analysis",
    "11": "stream query pipeline",
    "11.1": "pipeline cost",
    "11.2": "query cost measurement",
    "11.3": "stream resources cost",
    "11.4": "resources",
    "12": "candidate specs active",
    "12.1": "specs active candidate",
    "12.2": "active pipeline model loss",
    "12.3": "admission active",
    "12.4": "admission pipeline loss",
    "12.5": "loss safety pipeline",
    "12.6": "recovery model active",
    "12.7": "specs pipeline quality cost",
    "12.8": "safety canonical pipeline loss",
    "12.9": "active legacy",
    "13": "candidate active report",
    "13.1": "candidate active recovery report",
    "13.2": "specs active candidate",
    "13.3": "active admission report analysis",
    "13.4": "release specs legacy",
    "14": "specs canonical legacy",
    "14.1": "specs canonical legacy",
    "14.2": "legacy specs recovery",
    "14.3": "specs quality legacy",
    "15": "release candidate measurement pipeline",
    "15.1": "report corpus measurement recovery",
    "15.2": "quality model pipeline stream query",
    "15.3": "admission release schedule",
    "15.4": "candidate active report",
    "16": "active safety release",
    "16.1": "active safety specs",
    "16.2": "safety specs analysis recovery",
    "16.3": "specs report legacy",
    "16.4": "release schedule resources cost",
    "17": "release candidate report",
    "17.1": "release active recovery cost",
    "17.1.1": "report analysis corpus",
    "17.2": "admission recovery resources analysis",
    "17.3": "release specs",
    "17.4": "candidate report active corpus stream query model",
    "18": "legacy",
    "19": "legacy canonical recovery measurement loss candidate",
    "20": "candidate active legacy",
    "21": "legacy",
    "22": "release specs",
    "23": "legacy",
}

LIMITS = {
    "domain": (
        "Finite frozen objects/configurations; 33 entries/41 cases are "
        "not mathematical full-domain or full-parameter proof."
    ),
    "source_parity": (
        "Source/standalone parity UNKNOWN stays UNKNOWN; historical "
        "source receipts are not fresh replay."
    ),
    "corpus": (
        "Two independent real sources satisfy minimum delivery only; "
        "derived windows/dtypes do not add sources or establish "
        "population representativeness."
    ),
    "schema_bound": (
        "Ordinary complete-scheme groups deliberately use "
        "SCHEMA_BOUND_OBJECT with frozen accessible schema/context and "
        "full external cost; no self-describing-stream claim."
    ),
    "model": (
        "Derived UINT8 base-4 symbol task, not original floating-point "
        "compression; pretrained training/test overlap UNKNOWN; opaque "
        "embedded models paid once."
    ),
    "stream": (
        "Known total length and frozen block policy; full output consumed "
        "after finalize. First emitted bytes may be header; no "
        "unknown-length, strict bounded memory, incremental sample "
        "consumption or production/backpressure claim."
    ),
    "query": (
        "Related NeaTS/LeaTS variants remain RESEARCH; point/range and "
        "column projection only; bytes/amplification are logical "
        "estimates, not hardware traffic; p99 unavailable below required "
        "requests/session evidence."
    ),
    "auxiliary_cost": (
        "Preparation replay is an independent AUXILIARY_COST_AUDIT, never "
        "a same-trial performance observation. Opaque native "
        "access/allocation/peak fields are null with reasons."
    ),
    "calibration": (
        "400 experiments per four finite lognormal paired-noise "
        "scenarios; empirical coverage 0.8925/0.9/0.94/0.9225 documents "
        "small-sample undercoverage, not a universal or verified 95% "
        "guarantee."
    ),
    "optional_cpu": (
        "Device/P3/file E2E, process-tree/cgroup, hard RSS, NUMA memory "
        "binding and advanced collectors are not claimed. Basic "
        "shared-host leases/affinity/NUMA topology and actual thread "
        "budgets are required."
    ),
    "new_algorithms": (
        "Only additional algorithm members/long-term majority integration "
        "are deferred by explicit user scope; existing "
        "algorithm/framework/profile obligations remain required."
    ),
    "rate_summary": (
        "No active rate-controlled/summary codec. Dedicated validator "
        "fixtures prove only framework interfaces, never algorithm "
        "qualification or formal group completion."
    ),
    "async_ragged": (
        "Channel-collection qualification proves explicit per-channel preservation "
        "and existing LZ4/Zstd P2 recovery only; it does not grant native asynchronous "
        "support to the 33 codecs or constitute asynchronous FORMAL performance."
    ),
    "kernel": (
        "External native API/CORE includes the declared API work. "
        "Optional internal native timers and pure-kernel causal speedup "
        "claims are not obtained from PIPELINE or SDK correctness."
    ),
    "git": (
        "Reviewable working-tree changes and artifacts; no Git commit/PR/public deployment claim."
    ),
}


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_test_manifest(document: dict, project_root: Path = ROOT) -> None:
    from audit_v32_completion import file_evidence as verification_file
    from audit_v32_completion import test_source_manifest

    require(
        document.get("test_source_manifest") == test_source_manifest(project_root),
        "full-suite test definitions/fixtures are absent or not current",
    )
    require(
        document.get("test_configuration") == [verification_file(project_root / "pyproject.toml")],
        "full-suite pytest configuration is absent or not current",
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def section_facets(section: str) -> list[str]:
    probe = section.removeprefix("§")
    while probe not in SECTION_FACETS:
        require("." in probe, f"unreviewed section: {section}")
        probe = probe.rsplit(".", 1)[0]
    return SECTION_FACETS[probe].split()


def disposition(row: dict, *, review: bool = False) -> tuple[str, str]:
    section = row.get("section", row.get("original_section", "")).removeprefix("§")
    statement = row["statement"]
    if section in {"1.1", "1.2", "1.3", "18", "21", "23"} or (section == "1.5" and not review):
        return (
            "HISTORICAL_CONTEXT",
            "Original dated facts retained; no current runtime or fresh parity promotion.",
        )
    if section in {"11.4"} or (section == "15" and statement.startswith("| G.")):
        return "OPTIONAL_CPU_EXTENSION", LIMITS["optional_cpu"]
    if section == "17.4" and (row.get("line") in {1341, 1343, 1346, 1352} or review):
        return "LONG_TERM_MAJORITY_DEFERRED", LIMITS["new_algorithms"]
    if section == "15.4" and statement.startswith("| L") and not statement.startswith("| L0."):
        return "EXISTING_SUBSET_REQUIRED_NEW_MEMBERS_DEFERRED", LIMITS["new_algorithms"]
    if section == "7.11":
        return "EXISTING_SUBSET_REQUIRED_NEW_MEMBERS_DEFERRED", LIMITS["new_algorithms"]
    if statement in {">", "项目有三个独立完成维度：", "完整闭环增加比较组规划："}:
        return "SPECIFICATION_CONTEXT", "Structural prose; no executable acceptance claim."
    if statement.startswith("|"):
        first = statement.split("|")[1].strip()
        if first in {
            "维度",
            "方向",
            "项目",
            "指标",
            "矩阵",
            "功能",
            "阶段",
            "批次",
            "风险",
            "用户问题",
            "层次",
            "状态层",
            "层",
            "当前CSV分类",
            "比较任务族",
            "Profile族",
            "比较目标",
            "范围",
            "边界",
            "参考",
            "数据维度",
            "语料",
            "期待/准入结论",
            "四态",
            "参数政策",
            "字段",
            "长期任务/组族",
            "用户目标 / 后续工作",
            "证据范围",
        }:
            return (
                "SPECIFICATION_CONTEXT",
                "Table column definitions retained; child obligations assessed individually.",
            )
    return (
        "REQUIRED_CURRENT_SCOPE",
        "Accept only the referenced task/domain and proof obligations; limits remain explicit.",
    )


def row_limits(row: dict) -> list[str]:
    text = row["statement"].lower()
    limits = ["domain", "source_parity", "corpus"]
    for key, tokens in {
        "model": ("模型", "learned", "deepzip", "dzip"),
        "stream": ("stream", "流式", "流主", "背压"),
        "query": ("query", "查询", "random access", "随机访问"),
        "auxiliary_cost": ("stage", "buffer", "allocation", "内存", "read/write", "adapted"),
        "rate_summary": ("summary", "摘要", "rate_controlled", "率控制", "专属"),
        "async_ragged": ("async", "ragged", "异步", "任意轴"),
        "kernel": ("kernel", "native", "计时", "simd"),
        "optional_cpu": ("device", "gpu", "fpga", "qat", "p3", "cgroup", "硬rss"),
        "schema_bound": ("独立对象", "成本边界", "完整方案", "schema"),
        "new_algorithms": ("长期", "候选", "新增"),
        "calibration": ("区间", "统计", "bootstrap", "ci", "confidence"),
        "git": ("提交", "issue", "pr"),
    }.items():
        if any(token in text for token in tokens):
            limits.append(key)
    return list(dict.fromkeys(limits))


def matrix_facets(line: int, statement: str) -> tuple[list[str], str]:
    if line in {26, 40, 71, 93, 130, 163, 189, 231, 250}:
        return ["specs"], "SPECIFICATION_CONTEXT"
    if 73 <= line <= 83 or 252 <= line <= 257:
        return ["canonical", "legacy"], "HISTORICAL_CONTEXT"
    if line in {104, 107, 113, 114, 140, 201}:
        return ["resources"], "OPTIONAL_CPU_EXTENSION"
    if line in {29, 239}:
        return ["active", "safety"], "SOURCE_PARITY_NOT_PROMOTED"
    if line in {53}:
        return ["channel_collection", "admission"], "REQUIRED_CURRENT_SCOPE"
    if line == 134:
        return ["safety", "active"], "SIMD_PATH_QUALIFICATION_NOT_SPEEDUP_PROFILE"
    if line == 137:
        return ["resources", "model"], "FIXED_BACKGROUND_POOL_NOT_MT_SWEEP"
    if line in {103, 136, 197}:
        return ["stream", "measurement", "cost"], "REQUIRED_CURRENT_SCOPE"
    if line in {112, 139, 198}:
        return ["query", "measurement", "cost"], "REQUIRED_CURRENT_SCOPE"
    if line in {110, 138, 168, 169, 170}:
        return ["loss", "quality"], "REQUIRED_CURRENT_SCOPE"
    if line in {111, 171, 172}:
        return ["model", "resources", "cost"], "REQUIRED_CURRENT_SCOPE"
    if 165 <= line <= 179:
        return ["active", "report", "safety"], "REQUIRED_CURRENT_SCOPE"
    special = {
        28: "active recovery cost",
        30: "admission report",
        42: "canonical active",
        43: "canonical active safety",
        44: "canonical report",
        45: "canonical safety admission",
        46: "canonical",
        47: "pipeline report",
        48: "canonical pipeline",
        49: "canonical pipeline report",
        50: "canonical admission",
        51: "canonical pipeline loss channel_collection",
        52: "canonical pipeline",
        54: "canonical pipeline cost safety",
        55: "pipeline safety",
        56: "model legacy",
        95: "active recovery",
        96: "report measurement cost",
        97: "admission active",
        98: "safety active",
        99: "stream pipeline safety",
        100: "active stream recovery",
        101: "recovery cost",
        102: "pipeline cost",
        105: "safety active",
        106: "model resources",
        108: "active pipeline cost",
        109: "canonical pipeline cost",
        115: "report active",
        132: "report resources cost",
        133: "api measurement",
        135: "pipeline cost",
        191: "canonical",
        192: "admission pipeline",
        193: "recovery measurement",
        194: "pipeline",
        195: "recovery pipeline",
        196: "api measurement",
        199: "model resources",
        200: "pipeline canonical admission channel_collection",
        233: "active admission",
        234: "active admission",
        235: "admission",
        236: "active analysis",
        237: "admission",
        238: "loss recovery",
        240: "cost safety",
        241: "report measurement",
        242: "release active",
    }
    require(line in special, f"matrix row needs explicit assessment: {line}: {statement}")
    return special[line].split(), "REQUIRED_CURRENT_SCOPE"


def clause_facets(identifier: str, defaults: list[str], statement: str) -> list[str]:
    """Assess the actual completion gates rather than only their chapter label."""
    explicit = {
        "V32-15-L1152": "candidate legacy",
        "V32-15-L1153": "specs canonical pipeline",
        "V32-15-L1154": "corpus recovery cost report",
        "V32-15-L1155": "measurement resources schedule analysis",
        "V32-15-L1156": "quality model loss corpus",
        "V32-15-L1157": "pipeline channel_collection stream query active",
        "V32-15-L1158": "resources",
        "V32-10.6-L0886": "specs admission corpus",
        "V32-10.6-L0887": "active recovery safety cost",
        "V32-10.6-L0888": "measurement report quality api analysis",
        "V32-10.6-L0889": "specs loss quality api",
        "V32-10.6-L0890": "report analysis admission",
        "V32-17.1-L1288": "candidate active canonical",
        "V32-17.1-L1289": "active safety cost",
        "V32-17.1-L1290": "report corpus analysis measurement",
        "V32-17.1-L1291": "recovery pipeline cost rate_summary_interfaces",
        "V32-17.1-L1292": "cost measurement resources specs analysis",
        "V32-17.1-L1293": "admission report active",
        "V32-17.1-L1294": "legacy report specs",
        "V32-3.1-L0235": "canonical channel_collection",
        "V32-3.5-L0301": "canonical pipeline loss channel_collection",
        "V32-3.5-L0302": "pipeline channel_collection",
        "V31-REVIEW-018": "canonical channel_collection pipeline",
        "V31-REVIEW-022": "canonical channel_collection pipeline active",
        "V32-0.5-L0082": "decision_context specs corpus analysis",
        "V31-REVIEW-045": "decision_context specs corpus analysis",
        "V32-6.6-L0526": "uncompressed_reference cost recovery",
    }
    facets = explicit.get(identifier, " ".join(defaults)).split()
    if any(
        token in statement for token in ("SUMMARY_ONLY", "RATE_CONTROLLED", "摘要专属", "率控制")
    ):
        facets.append("rate_summary_interfaces")
    if any(token in statement for token in ("resume", "中断", "重跑", "旧失败不删除")):
        facets.append("interruption_resume")
    if any(token in statement for token in ("decision_context", "用户决策", "研究问题、目标总体")):
        facets.append("decision_context")
    if "未压缩完整对象" in statement:
        facets.append("uncompressed_reference")
    return list(dict.fromkeys(facets))


def build_mapping() -> dict:
    from build_v32_requirement_ledger import build

    ledger = read(LEDGER)
    regenerated = build()
    for field in ("sources", "coverage"):
        require(ledger[field] == regenerated[field], f"source ledger drift: {field}")
    rows = []
    for source_kind, field in (
        ("plan", "requirements"),
        ("review", "review_cross_references"),
        ("matrix", "capability_matrix_snapshot"),
    ):
        require(
            [(r["source"], r["line"], r["statement"]) for r in ledger[field]]
            == [(r["source"], r["line"], r["statement"]) for r in regenerated[field]],
            f"missing source rows: {source_kind}",
        )
        for original in ledger[field]:
            if source_kind == "matrix":
                identifier = f"V32-MATRIX-L{original['line']:04d}"
                facets, mode = matrix_facets(original["line"], original["statement"])
                reason = (
                    "Matrix axis and actual implementation evidence; baseline "
                    "declaration is not runtime proof."
                )
            else:
                identifier = original.get("requirement_id", original.get("review_id"))
                facets = section_facets(original.get("section", original.get("original_section")))
                mode, reason = disposition(original, review=source_kind == "review")
                facets = clause_facets(identifier, facets, original["statement"])
            rows.append(
                {
                    "requirement_id": identifier,
                    "source_kind": source_kind,
                    "source": original["source"],
                    "line": original["line"],
                    "statement": original["statement"],
                    "normative": original.get("normative", source_kind != "plan"),
                    "disposition": mode,
                    "reason": reason,
                    "required_proofs": facets,
                    "claim_limits": row_limits(original),
                    "status": "AWAITING_CURRENT_RELEASE_EVIDENCE",
                    "accepted_evidence": [],
                }
            )
    require(len(rows) == 911, "complete source row denominator changed")
    require(len({r["requirement_id"] for r in rows}) == len(rows), "duplicate clause ID")
    require(
        all(r["required_proofs"] and set(r["required_proofs"]) <= set(FACETS) for r in rows),
        "clause has no explicit proof obligations",
    )
    return {
        "schema_version": "tscb.v32-acceptance-mapping.v1",
        "baseline_date": "2026-10-10",
        "status": "MAPPING_ONLY_NOT_ACCEPTANCE",
        "ledger": {"path": str(LEDGER.relative_to(ROOT)), "sha256": sha(LEDGER)},
        "sources": ledger["sources"],
        "coverage": ledger["coverage"],
        "scope": "EXISTING_ALGORITHMS_CURRENT_CPU_TASKS_NO_ADDITIONAL_ALGORITHMS",
        "proof_obligations": FACETS,
        "claim_limits": LIMITS,
        "rows": rows,
        "release_evidence_hint": "build/v32-evidence-20261010/current-r2/completion.json",
        "rules": [
            (
                "Revalidate all real lane evidence and current closure before "
                "publishing; a saved PASS string is insufficient."
            ),
            (
                "Only clause-specific proof bundles close applicable obligations; "
                "full-suite source/test paths cannot grant algorithm FORMAL."
            ),
            "Historical/context/optional/deferred rows are accounted for, not marked runtime PASS.",
            (
                "Stream/query are required real profiles; rate/summary interfaces "
                "do not invent active algorithms."
            ),
        ],
    }


def file_evidence(path: Path, *, role: str, identity: dict, domain: dict, result: str) -> dict:
    path = path.resolve()
    require(path.is_relative_to(ROOT), "evidence escapes project")
    require(path.is_file(), f"evidence missing: {path}")
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": sha(path),
        "bytes": path.stat().st_size,
        "role": role,
        "current_identity": identity,
        "task_domain": domain,
        "result": result,
    }


def _test_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    return sorted(
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")
    )


def _lane_directory(evidence_root: Path, declaration: dict, lane: str) -> Path | None:
    if lane in declaration["comparisons"]:
        value = declaration["comparisons"][lane]
    elif lane in declaration["workloads"]:
        value = declaration["workloads"][lane]
    elif lane == "sdk":
        return None
    else:
        value = declaration[lane]
    path = (evidence_root / value).resolve()
    require(
        path.is_relative_to(evidence_root.resolve()) and "history" not in path.parts,
        "proof lane escapes current release",
    )
    return path


def _proof(facet: str, evidence_root: Path, completion: dict, completion_path: Path) -> dict:
    declaration, current = completion["declaration"], completion["control_plane"]
    identity = {
        "release_acceptance_id": completion["acceptance_id"],
        "control_plane_sha256": hashlib.sha256(
            json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    spec = FACETS[facet]
    evidence, domains, findings = [], {}, []
    if facet in {"channel_collection", "release"}:
        from qualify_v32_channel_collection import validate_collection_qualification

        require("channel_collection" in declaration, "required async/ragged evidence is missing")
        path = (evidence_root / declaration["channel_collection"]).resolve()
        require(path.is_relative_to(evidence_root.resolve()), "channel evidence escapes release")
        qualification = validate_collection_qualification(path)
        require(isinstance(qualification, dict), "channel qualification must return audited facts")
        require(
            qualification["status"] == "SCOPED_QUALIFICATION_COMPLETE"
            and qualification["codec_execution_required"] is True
            and qualification["performance_execution_required"] is False
            and qualification["codec_execution_scope"] == "READ_ONLY_INDEPENDENT_DECODER_AUDIT",
            "structural-only channel evidence cannot grant complete recovery qualification",
        )
        domains["channel_collection"] = {
            "scope": "ASYNC_RAGGED_EXPLICIT_PER_CHANNEL_P2_QUALIFICATION_ONLY",
            "performance_remeasured": False,
            "qualification": qualification,
        }
        findings.append(
            {
                "gate": "REVALIDATED_CURRENT_PER_CHANNEL_CONTENT_TO_CLEAN_DECODE_AND_COMPLETE_COST",
                "qualification": qualification,
            }
        )
        evidence.append(
            file_evidence(
                path,
                role="REQUIRED_ASYNC_RAGGED_P2_QUALIFICATION",
                identity=identity,
                domain=domains["channel_collection"],
                result="SCOPED_QUALIFICATION",
            )
        )
    for lane in spec["lanes"]:
        group = completion["groups"][lane]
        domains[lane] = group.get(
            "domain", {"lane": lane, "scope": group.get("scope", group.get("profile"))}
        )
        lane_identity = {**identity, "lane": lane}
        for key in ("analysis_id", "comparison_id", "plan_id", "audit_id"):
            if key in group:
                lane_identity[key] = group[key]
        path = _lane_directory(evidence_root, declaration, lane)
        if path is None:
            path = evidence_root / declaration["sdk"]
            evidence.append(
                file_evidence(
                    path,
                    role="CURRENT_SDK_INDEPENDENT_AUDIT",
                    identity=lane_identity,
                    domain=domains[lane],
                    result=group["status"],
                )
            )
            continue
        found = [path / name for name in spec["files"] if (path / name).is_file()]
        require(bool(found), f"no actual {facet}/{lane} evidence")
        if facet == "interruption_resume":
            journal_name = (
                "pipeline_events.jsonl"
                if lane == "pipeline"
                else "workload_events.jsonl"
                if lane in WORKLOADS
                else "events.jsonl"
            )
            require((path / journal_name).is_file(), f"durable attempt journal missing: {lane}")
        if facet == "decision_context":
            from tscompbench.comparison.decision import (
                comparison_decision,
                pipeline_decision,
                validate_experiment_decision,
            )

            if lane == "pipeline":
                plan = read(path / "plan.json")
                decision = pipeline_decision(
                    datasets=plan["datasets"],
                    protocol=plan["protocol"],
                    analysis_policy=plan["analysis_policy"],
                    resources=plan["resources"],
                    closure=plan["closure"],
                    boundary=plan["boundary"],
                    scope=plan["scope"],
                )
            else:
                base = read(path / "execution_plan.json")
                plan = read(path / "workload_plan.json") if lane in WORKLOADS else base
                decision = comparison_decision(
                    read(path / "bundle.json"),
                    environment_id=read(path / "environment.json")["environment_id"],
                    control_plane_sha256=read(path / "control_plane.json")["sha256"],
                    workload_protocol=base.get("decision_workload_protocol"),
                )
                if lane in WORKLOADS:
                    require(
                        plan["protocol"] == base["decision_workload_protocol"],
                        f"pre-measurement workload decision differs: {lane}",
                    )
                validate_experiment_decision(path, base, decision)
            validate_experiment_decision(path, plan, decision)
            findings.append(
                {
                    "lane": lane,
                    "gate": "PREMEASUREMENT_DECISION_REDERIVED_FROM_FROZEN_INPUTS",
                    "decision_id": decision["decision_id"],
                    "conclusion_scope": decision["conclusion_scope"],
                }
            )
        if facet == "uncompressed_reference":
            from audit_v32_uncompressed_reference import validate_uncompressed_reference

            reference_kind = (
                "pipeline"
                if lane == "pipeline"
                else "workload"
                if lane in WORKLOADS
                else "comparison"
            )
            reference = validate_uncompressed_reference(path, reference_kind)
            require(
                reference["status"] == "UNCOMPRESSED_REFERENCE_AUDIT"
                and reference["baseline_kind"] == "SIZE_BASELINE"
                and reference["statistical_method_count"] == 0
                and reference["formal_eligible"] is False
                and reference["codec_invoked"] is False
                and reference["performance_remeasured"] is False,
                "size reference cannot fabricate a measured codec or method count",
            )
            for obj in reference["objects"]:
                for item in obj["files"]:
                    evidence.append(
                        file_evidence(
                            Path(item["path"]),
                            role="SAVED_UNCOMPRESSED_OBJECT_AND_PAID_CONTEXT",
                            identity=lane_identity,
                            domain=domains[lane],
                            result="SIZE_BASELINE_ONLY",
                        )
                    )
            findings.append(
                {
                    "lane": lane,
                    "gate": "INDEPENDENT_UNCOMPRESSED_OBJECT_SIZE_REFERENCE",
                    "reference_id": reference["reference_id"],
                    "formal_performance": False,
                    "statistical_method_count": 0,
                }
            )
        for candidate in found:
            evidence.append(
                file_evidence(
                    candidate,
                    role=f"{facet.upper()}_{lane.upper()}",
                    identity=lane_identity,
                    domain=domains[lane],
                    result=group.get("result", group.get("status", "AUDITED_CURRENT")),
                )
            )
        if lane == "active":
            plan = read(path / "plan.json")
            for entry in plan["entries"]:
                for case in entry["cases"]:
                    case_path = path / "cases" / (case["case_id"].rsplit(":", 1)[-1] + ".json")
                    case_document = read(case_path)
                    evidence.append(
                        file_evidence(
                            case_path,
                            role="RAW_SCOPED_TRACK_QUALIFICATION",
                            identity={**lane_identity, "case_id": case["case_id"]},
                            domain=case_document["task"],
                            result="SCOPED_PASS",
                        )
                    )
        findings.append(
            {
                "lane": lane,
                "gate": "REVALIDATED_LANE_SPECIFIC_CURRENT_RAW_AND_CLOSURE",
                "result": group.get("result", group.get("status")),
                "domain": domains[lane],
            }
        )
    validation_path = evidence_root / declaration["validation"]
    validation = read(validation_path)
    validate_test_manifest(validation)
    evidence.append(
        file_evidence(
            validation_path,
            role="UNFILTERED_CURRENT_FULL_SUITE",
            identity=identity,
            domain={"claim": "framework regression only; no invented algorithm formal"},
            result="PASS",
        )
    )
    for item in validation["artifacts"]:
        evidence.append(
            file_evidence(
                ROOT / item["path"],
                role=item["role"],
                identity=identity,
                domain={"tests_passed": validation["tests_passed"]},
                result="PASS",
            )
        )
    framework_files = []
    for name in [*spec["sources"], *spec["tests"]]:
        candidate = ROOT / name
        require(candidate.is_file(), f"mapped implementation/test missing: {name}")
        item = file_evidence(
            candidate,
            role="FRAMEWORK_IMPLEMENTATION_OR_TEST_SCOPE",
            identity=identity,
            domain={"facet": facet},
            result="IMPLEMENTATION_REFERENCE_NOT_FORMAL",
        )
        if name in spec["tests"]:
            item["test_functions"] = _test_names(candidate)
            item["test_result_limit"] = (
                "Definitions frozen with the unfiltered suite; its actual skip/count "
                "log remains authoritative. No per-node execution attestation invented."
            )
        framework_files.append(item)
    if facet in {"analysis", "release"}:
        path = evidence_root / declaration["calibration"]
        calibration = read(path)
        require(
            len(calibration["scenarios"]) == 4
            and all(s["experiments"] >= 400 for s in calibration["scenarios"]),
            "required four-scenario calibration is missing",
        )
        findings.append(
            {
                "calibration_scope": calibration["scope"],
                "scenarios": calibration["scenarios"],
                "coverage_guarantee": False,
                "small_sample_undercoverage": True,
            }
        )
        evidence.append(
            file_evidence(
                path,
                role="FINITE_SIMULATION_CALIBRATION",
                identity=identity,
                domain={"scenarios": 4, "population_inference": False},
                result="LIMITED_CALIBRATION",
            )
        )
    if facet in {"candidate", "release"}:
        path = evidence_root / declaration["stage_mapping"]
        evidence.append(
            file_evidence(
                path,
                role="CURRENT_CANDIDATE_METHOD_GROUP_MAPPING",
                identity=identity,
                domain={"active_keys": 33, "majority_completed": False},
                result="SCOPED_MAPPING",
            )
        )
    if facet in {"legacy", "release"}:
        path = evidence_root / declaration["legacy"]
        legacy = read(path)
        require(legacy["v32_formal_eligible"] is False, "legacy migration cannot grant formal")
        evidence.append(
            file_evidence(
                path,
                role="READ_ONLY_LEGACY_DERIVED_ANALYSIS",
                identity=identity,
                domain={"legacy_run": legacy["derived_from"]["run_path"]},
                result="HISTORICAL_ONLY",
            )
        )
    evidence.append(
        file_evidence(
            completion_path,
            role="REVALIDATED_RELEASE_DEPENDENCY",
            identity=identity,
            domain={"scope": "EXISTING_CURRENT_CPU"},
            result=completion["status"],
        )
    )
    document = {
        "schema_version": "tscb.v32-clause-proof.v1",
        "facet": facet,
        "claim": spec["claim"],
        "result": (
            "ACCEPTED_FRAMEWORK_INTERFACE_ONLY_NO_ALGORITHM_FORMAL"
            if facet == "rate_summary_interfaces"
            else "ACCEPTED_WITH_EXPLICIT_SCOPE"
        ),
        "current_identity": identity,
        "task_domain": domains,
        "findings": findings,
        "evidence": evidence,
        "framework_references": framework_files,
        "claim_limits": LIMITS,
    }
    document["proof_sha256"] = hashlib.sha256(
        json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    return document


def validate_mapping(mapping: dict) -> None:
    expected = build_mapping()
    require(
        mapping == expected,
        "acceptance mapping omitted/changed clauses, disposition or proof obligations",
    )


def publish(completion_path: Path, output: Path, *, mapping_path: Path = MAPPING) -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from audit_v32_completion import audit

    from tscompbench.ids import stable_id

    mapping = read(mapping_path)
    validate_mapping(mapping)
    completion_path, output = completion_path.resolve(), output.resolve()
    require(
        output.is_relative_to(completion_path.parent),
        "accepted ledger must stay in current release directory",
    )
    require(not output.exists(), "acceptance artifact is immutable; choose a new output")
    completion = read(completion_path)
    require(completion["status"] == "CURRENT_CPU_SCOPE_COMPLETE", "current release is incomplete")
    revalidated = audit(completion_path.parent, completion["declaration"])
    require(
        completion == revalidated,
        "saved release differs from independently revalidated current evidence",
    )
    proof_root = output.parent / (output.stem + "_proofs")
    require(
        not proof_root.exists(), "proof directory already exists; choose a new acceptance artifact"
    )
    # Build and validate all content before creating any output artifacts.
    proofs = {
        facet: _proof(facet, completion_path.parent, completion, completion_path)
        for facet in FACETS
    }
    proof_root.mkdir(parents=True)
    proof_evidence = {}
    for facet, proof in proofs.items():
        path = proof_root / f"{facet}.json"
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        proof_evidence[facet] = file_evidence(
            path,
            role="CLAUSE_SPECIFIC_REVALIDATED_PROOF",
            identity=proof["current_identity"],
            domain=proof["task_domain"],
            result=proof["result"],
        )
    rows = []
    for row in mapping["rows"]:
        updated = dict(row)
        mode = row["disposition"]
        updated["accepted_evidence"] = [proof_evidence[f] for f in row["required_proofs"]]
        updated["status"] = {
            "HISTORICAL_CONTEXT": "ACCOUNTED_HISTORICAL_NO_CURRENT_PROMOTION",
            "SPECIFICATION_CONTEXT": "ACCOUNTED_CONTEXT_NO_RUNTIME_CLAIM",
            "OPTIONAL_CPU_EXTENSION": "OPTIONAL_NOT_CLAIMED",
            "LONG_TERM_MAJORITY_DEFERRED": "DEFERRED_BY_USER_NOT_COMPLETE",
            "SOURCE_PARITY_NOT_PROMOTED": "ACCOUNTED_SOURCE_PARITY_UNCHANGED",
            "SIMD_PATH_QUALIFICATION_NOT_SPEEDUP_PROFILE": (
                "ACCEPTED_QUALIFICATION_NO_SPEEDUP_CLAIM"
            ),
            "FIXED_BACKGROUND_POOL_NOT_MT_SWEEP": "ACCEPTED_FIXED_POOL_NO_SWEEP_CLAIM",
            "EXISTING_SUBSET_REQUIRED_NEW_MEMBERS_DEFERRED": (
                "ACCEPTED_EXISTING_SUBSET_NEW_MEMBERS_DEFERRED"
            ),
            "REQUIRED_CURRENT_SCOPE": "ACCEPTED_CURRENT_SCOPE",
        }[mode]
        updated["remaining_gap"] = None if mode == "REQUIRED_CURRENT_SCOPE" else row["reason"]
        rows.append(updated)
    source_ledger = read(LEDGER)
    by_id = {row["requirement_id"]: row for row in rows}
    accepted = dict(source_ledger)
    for field, identifier in (
        ("requirements", "requirement_id"),
        ("review_cross_references", "review_id"),
    ):
        accepted[field] = [
            {
                **original,
                **{
                    key: by_id[original[identifier]][key]
                    for key in (
                        "status",
                        "disposition",
                        "required_proofs",
                        "accepted_evidence",
                        "claim_limits",
                        "remaining_gap",
                    )
                },
            }
            for original in source_ledger[field]
        ]
        for row in accepted[field]:
            row["implementation_status"] = row["status"]
    group_lanes = {
        "G-BYTE-LL": "byte",
        "G-FLOAT-LL-F64": "f64",
        "G-INT-LL-I16": "i16",
        "G-FLOAT-ABS": "abs",
    }
    accepted["core_groups"] = [
        {
            **group,
            "implementation_status": "CURRENT_FORMAL_FIXED_CORPUS_ACCEPTED",
            "current_group": completion["groups"][group_lanes[group["group_id"]]],
            "accepted_evidence": [proof_evidence["report"], proof_evidence["corpus"]],
        }
        for group in source_ledger["core_groups"]
    ]
    accepted["capability_matrix_snapshot"] = [
        {**original, **by_id[f"V32-MATRIX-L{original['line']:04d}"]}
        for original in source_ledger["capability_matrix_snapshot"]
    ]
    accepted.update(
        {
            "schema_version": "tscb.v32-accepted-requirement-ledger.v1",
            "status": "CURRENT_EXISTING_CPU_SCOPE_ACCEPTED_WITH_LIMITS",
            "purpose": (
                "Clause-specific current acceptance and explicit "
                "historical/optional/deferred accounting."
            ),
            "source_ledger_sha256": sha(LEDGER),
            "mapping_sha256": sha(mapping_path),
            "release_artifact": file_evidence(
                completion_path,
                role="CURRENT_RELEASE_AUDIT",
                identity={"acceptance_id": completion["acceptance_id"]},
                domain={"scope": mapping["scope"]},
                result=completion["status"],
            ),
            "proofs": proof_evidence,
            "claim_limit_definitions": LIMITS,
            "acceptance_counts": dict(sorted(Counter(row["status"] for row in rows).items())),
        }
    )
    accepted["acceptance_id"] = stable_id("v32-accepted-requirement-ledger", accepted, version="v3")
    with output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(accepted, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return accepted


def self_test() -> None:
    """Meaningful failure checks without codecs or performance observations."""
    import copy
    import tempfile

    mapping = build_mapping()
    validate_mapping(mapping)
    for mutate in (
        lambda m: m["rows"].pop(),
        lambda m: m["rows"][0].update(required_proofs=["release"]),
        lambda m: m["rows"][0].update(statement="forged clause"),
        lambda m: m["rows"].reverse(),
        lambda m: m["sources"][0].update(sha256="0" * 64),
    ):
        bad = copy.deepcopy(mapping)
        mutate(bad)
        try:
            validate_mapping(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("tampered mapping was accepted")
    require(
        len([r for r in mapping["rows"] if r["source_kind"] == "plan" and r["normative"]]) == 277,
        "normative/delivery denominator changed",
    )
    for line in (103, 112, 136, 139, 197, 198):
        row = next(r for r in mapping["rows"] if r["requirement_id"] == f"V32-MATRIX-L{line:04d}")
        require(
            row["disposition"] == "REQUIRED_CURRENT_SCOPE", "stream/query wrongly made optional"
        )
    for identifier in ("V32-3.5-L0302", "V32-MATRIX-L0053", "V31-REVIEW-018"):
        row = next(r for r in mapping["rows"] if r["requirement_id"] == identifier)
        require("channel_collection" in row["required_proofs"], "async/ragged obligation omitted")
    for identifier in ("V32-0.5-L0082", "V31-REVIEW-045"):
        row = next(r for r in mapping["rows"] if r["requirement_id"] == identifier)
        require("decision_context" in row["required_proofs"], "decision obligation omitted")
    reference_row = next(r for r in mapping["rows"] if r["requirement_id"] == "V32-6.6-L0526")
    require(
        "uncompressed_reference" in reference_row["required_proofs"],
        "uncompressed complete-object baseline obligation omitted",
    )
    with tempfile.TemporaryDirectory(dir="/tmp") as temporary:
        path = Path(temporary) / "proof.json"
        path.write_text("real evidence")
        # Reject evidence outside the repository instead of accepting arbitrary
        # paths or a plausible saved PASS document.
        try:
            file_evidence(path, role="test", identity={}, domain={}, result="PASS")
        except ValueError:
            pass
        else:
            raise AssertionError("out-of-project evidence accepted")
        project = Path(temporary) / "project"
        (project / "tests").mkdir(parents=True)
        test_file = project / "tests" / "test_contract.py"
        test_file.write_text("def test_contract():\n    assert True\n")
        (project / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        import audit_v32_completion as completion_audit

        real_root = completion_audit.ROOT
        completion_audit.ROOT = project
        try:
            validation = {
                "test_source_manifest": completion_audit.test_source_manifest(project),
                "test_configuration": [completion_audit.file_evidence(project / "pyproject.toml")],
            }
            validate_test_manifest(validation, project)
            test_file.write_text("def test_contract():\n    assert False\n")
            for bad_validation in (validation, {}):
                try:
                    validate_test_manifest(bad_validation, project)
                except ValueError:
                    pass
                else:
                    raise AssertionError("changed or absent test definitions accepted")
            validation["test_source_manifest"] = completion_audit.test_source_manifest(project)
            (project / "pyproject.toml").write_text(
                "[tool.pytest.ini_options]\naddopts='-k subset'\n"
            )
            try:
                validate_test_manifest(validation, project)
            except ValueError:
                pass
            else:
                raise AssertionError("changed pytest configuration accepted")
            (project / "tests" / "ignored.pyo").write_bytes(b"not a test definition")
            require(
                validation["test_source_manifest"]
                == completion_audit.test_source_manifest(project),
                "compiled pyo unexpectedly changed source manifest",
            )
        finally:
            completion_audit.ROOT = real_root
    print(
        "PASS: full 911-row coverage, 277 normative/delivery clauses, "
        "tamper and scope negative checks"
    )


def main() -> None:
    sys.path.insert(0, str(ROOT / "tools"))
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("map")
    sub.add_parser("check")
    sub.add_parser("self-test")
    command = sub.add_parser("publish")
    command.add_argument("completion", type=Path)
    command.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "map":
        document = build_mapping()
        MAPPING.write_text(
            json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        )
        print(json.dumps({"status": document["status"], "rows": len(document["rows"])}))
    elif args.command == "check":
        validate_mapping(read(MAPPING))
        print("PASS: all source rows and explicit acceptance obligations unchanged")
    elif args.command == "self-test":
        self_test()
    else:
        result = publish(args.completion, args.output)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "acceptance_id": result["acceptance_id"],
                    "counts": result["acceptance_counts"],
                }
            )
        )


if __name__ == "__main__":
    main()
