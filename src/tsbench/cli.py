"""Thin command-line adapter. No plan or acceptance logic lives here."""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import signal
from threading import Event
import tempfile

from .api import (audit_smoke_restore, NativePlanRequest, PlanRequest, SmokePlanRequest, check_corpus, check_full_corpus, check_sources, load_request, plan,
                  plan_comparison, plan_native, plan_native_requirements, plan_smoke, profile_corpus, report_native, report_smoke, run_native, run_smoke)
from .assets import ContractError, load_json, local_file, require
from .corpus import RELEASES
from .corpus_ingress import MANIFEST as FULL_CORPUS
from .api import plan_native_corpus, verify_native_corpus_plan
from .planner.native_corpus import POLICY as NATIVE_CORPUS_POLICY
from .plugins import discover
from .runtime import create_build_lock
from .planner.smoke import DEV_SUITE
from .planner.tv import SUITE as TV_SUITE
from .planner.recipe import plan_recipe
from .planner.service_recipes import plan_service_recipes, verify_service_recipes
from .qualification.native_evidence import audit_native_qualification
from .application.native_submission import SCHEMA as NATIVE_SUBMISSION, plan_native_submission, run_native_submission
from .application.m0_acceptance import audit_m0
from .application.m0_real_corpus_acceptance import audit_m0_real_corpus
from .application.m1_acceptance import audit_m1
from .application.m1_real_corpus_acceptance import audit_m1_real_corpus
from .application.m2_acceptance import audit_m2
from .application.m3_acceptance import audit_m3
from .application.m4_acceptance import audit_m4
from .api import plan_native_admission, plan_tv, report_tv, restore_tv, run_tv
from .api import audit_batch_execution, plan_batch_execution, report_batch_execution, run_batch_execution
from .api import TimingPlanRequest, compare_timing_repeats, plan_timing, report_timing, run_timing
from .api import M2RealCorpusPlanRequest, audit_m2_real_corpus, plan_m2_real_corpus
from .api import M3RealCorpusPlanRequest, plan_m3_real_corpus, check_m3_real_corpus_plan, plan_m3_input_switch
from .api import audit_m3_intmult_run, run_m3_real_corpus
from .api import plan_profile, report_profile, run_profile, verify_service_plan


def _publish(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".bmk-write-", dir=path.parent) as temp:
        staged = Path(temp) / "plan.json"
        with staged.open("w", encoding="utf-8", newline="\n") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        # The requested lock is immutable. Never overwrite an existing plan.
        path.hardlink_to(staged)


def main(argv=None, *, default_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bmk", allow_abbrev=False)
    parser.add_argument("--root", type=Path, default=default_root or Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-sources", allow_abbrev=False)
    corpus = commands.add_parser("check-corpus", allow_abbrev=False)
    corpus.add_argument("--parse", action="store_true", help="recompute canonical hashes from all locked real data")
    corpus.add_argument("--version", type=int, choices=tuple(RELEASES), default=3, help="frozen corpus version")
    full_corpus = commands.add_parser("check-full-corpus", allow_abbrev=False)
    full_corpus.add_argument("--manifest", default=FULL_CORPUS, help="project-relative full corpus manifest")
    full_corpus.add_argument("--parse", action="store_true", help="stream all rows and verify canonical identities")
    commands.add_parser("corpus-profile", allow_abbrev=False, help="verify and profile the current frozen corpus and fixtures")
    commands.add_parser("plugins", allow_abbrev=False).add_argument("action", choices=["list"])
    planner = commands.add_parser("plan", allow_abbrev=False)
    planner.add_argument("--config", help="project-relative TOML request")
    planner.add_argument("--suite")
    planner.add_argument("--max-workers", type=int)
    planner.add_argument("--out", type=Path)
    verify_plan = commands.add_parser("service-plan-verify", allow_abbrev=False,
                                      help="rederive a frozen service scope from local configuration")
    verify_plan.add_argument("--plan", type=Path, required=True)
    resolve_services = commands.add_parser("service-recipe-plan", allow_abbrev=False,
                                           help="reconcile the full service scope against bound development recipes")
    resolve_services.add_argument("--bindings", required=True, help="project-relative provider registry JSON")
    resolve_services.add_argument("--build-lock", required=True, help="project-relative development build lock")
    resolve_services.add_argument("--max-workers", type=int, default=1)
    resolve_services.add_argument("--out", type=Path)
    commands.add_parser("service-recipe-verify", allow_abbrev=False).add_argument("--plan", type=Path, required=True)
    compare = commands.add_parser("comparison-plan", allow_abbrev=False, help="freeze one comparison contract; does not grant admission")
    compare.add_argument("--config", required=True, help="project-relative comparison contract JSON")
    compare.add_argument("--out", type=Path)
    build = commands.add_parser("lock-build", allow_abbrev=False)
    build.add_argument("--worker", required=True)
    build.add_argument("--plugin", action="append", default=[], metavar="ID=LOCAL_DSO")
    build.add_argument("--out", type=Path, required=True)
    profile = commands.add_parser("profile-plan", allow_abbrev=False, help="freeze independent native profiling controls")
    profile.add_argument("--plain-build", required=True)
    profile.add_argument("--profile-build", required=True)
    profile.add_argument("--out", type=Path)
    commands.add_parser("profile-run", allow_abbrev=False).add_argument("--plan", required=True)
    commands.add_parser("profile-report", allow_abbrev=False).add_argument("run_id")
    timing = commands.add_parser("timing-plan", allow_abbrev=False, help="freeze a CPU-pinned M2 diagnostic plan")
    timing.add_argument("--build-dir", required=True)
    timing.add_argument("--cpu", required=True, type=int)
    timing.add_argument("--out", type=Path)
    m2_real_plan = commands.add_parser("m2-real-corpus-plan", allow_abbrev=False, help="bind updated M0/M1 real-corpus receipts to M2 timing evidence")
    m2_real_plan.add_argument("--m0-receipt", required=True)
    m2_real_plan.add_argument("--m1-receipt", required=True)
    m2_real_plan.add_argument("--timing-plan", required=True)
    m2_real_plan.add_argument("--out", type=Path, required=True)
    timing_run = commands.add_parser("timing-run", allow_abbrev=False)
    timing_run.add_argument("--plan", required=True)
    commands.add_parser("timing-report", allow_abbrev=False).add_argument("run_id")
    repeats = commands.add_parser("timing-compare-repeats", allow_abbrev=False)
    repeats.add_argument("first_run")
    repeats.add_argument("second_run")
    smoke = commands.add_parser("smoke-plan", allow_abbrev=False)
    smoke.add_argument("--build-lock", required=True)
    smoke.add_argument("--suite", default=DEV_SUITE, help="local lossless suite ID")
    smoke.add_argument("--input-config", help="project-relative M1 full-corpus input request")
    smoke.add_argument("--native-definition", help="project-relative rederived M0 native corpus definition to bind")
    smoke.add_argument("--out", type=Path)
    run = commands.add_parser("smoke-run", allow_abbrev=False)
    run.add_argument("--plan", required=True, help="project-relative frozen smoke plan")
    report = commands.add_parser("smoke-report", allow_abbrev=False)
    report.add_argument("run_id")
    restore = commands.add_parser("smoke-restore-audit", allow_abbrev=False, help="decode sealed samples in a files-only Linux namespace")
    restore.add_argument("run_id")
    native = commands.add_parser("native-plan", allow_abbrev=False, help="freeze the complete M0 native preflight")
    native.add_argument("--build-dir", type=Path, required=True)
    native.add_argument("--huff0-portable-build", type=Path, help="separate ENTROPY_DYNAMIC_BMI2=OFF build for same-run Huff0 decode control")
    native.add_argument("--out", type=Path)
    requirements = commands.add_parser("native-contract-plan", allow_abbrev=False,
                                       help="freeze native obligations and identify unbound cases (does not run)")
    requirements.add_argument("--out", type=Path)
    corpus_plan = commands.add_parser("native-corpus-plan", allow_abbrev=False,
                                      help="freeze all real-input native applicability decisions (not a run)")
    corpus_plan.add_argument("--manifest", default=FULL_CORPUS)
    corpus_plan.add_argument("--policy", default=NATIVE_CORPUS_POLICY)
    corpus_plan.add_argument("--out", type=Path)
    commands.add_parser("native-corpus-verify", allow_abbrev=False).add_argument("--plan", type=Path, required=True)
    admission = commands.add_parser("native-admission-plan", allow_abbrev=False,
                                    help="freeze first-batch native domain, quality, recovery and outstanding obligations")
    admission.add_argument("--out", type=Path)
    m3_real_plan = commands.add_parser("m3-real-corpus-plan", allow_abbrev=False, help="freeze the updated M3 full real-corpus denominator")
    m3_real_plan.add_argument("--switch-from", help="verified baseline M3 plan; keep its builds, policies and receipts, switch only input definition")
    m3_real_plan.add_argument("--m0-receipt")
    m3_real_plan.add_argument("--m1-receipt")
    m3_real_plan.add_argument("--m2-receipt")
    m3_real_plan.add_argument("--native-definition", required=True)
    m3_real_plan.add_argument("--build-lock")
    m3_real_plan.add_argument("--gorilla-state-repair-lock", help="explicit C11 derivative for Gorilla state routes only")
    m3_real_plan.add_argument("--huff0-portable-build", help="recipe-matched BMI2-off build for the same-run Huff0 condition")
    m3_real_plan.add_argument("--pbepla-repair-provenance", help="versioned native PBEP v1/v2 derivative provenance")
    m3_real_plan.add_argument("--measurement-cpu", type=int, help="freeze explicit in-run diagnostic clocks (not host exclusivity)")
    m3_real_plan.add_argument("--measurement-fixed-batch-worker", help="bind fixed-batch timing worker with --measurement-cpu")
    m3_real_plan.add_argument("--measurement-column-batch-worker", help="bind ALP/Titchy native batch timing worker")
    m3_real_plan.add_argument("--corad-repair-provenance", help="versioned wire-compatible native CORAD reference guard")
    m3_real_plan.add_argument("--measurement-gorilla", action="store_true", help="bind native C11 Gorilla measurement lanes")
    m3_real_plan.add_argument("--measurement-pcodec-pages-tool", help="bind the frozen isolated pcodec page controller")
    m3_real_plan.add_argument("--measurement-abi-corpus-worker", help="bind the whole-file Sprintz/Huff0 ABI worker")
    m3_real_plan.add_argument("--measurement-selfstar-corpus-worker", help="bind the whole-column SElf* worker")
    m3_real_plan.add_argument("--measurement-titchy-grouped", help="bind Titchy stream and native access grouped tool")
    m3_real_plan.add_argument("--measurement-zstd-dictionary-grouped", help="bind the isolated Zstd dictionary training and held-out grouped tool")
    m3_real_plan.add_argument("--measurement-lzbench-tools", nargs=2, metavar=("SESSION", "WORKERS"),
                              help="bind the two whole-file Zstd/XZ clock tools")
    m3_real_plan.add_argument("--measurement-lzbench-cpus", nargs=3, type=int, metavar=("CPU1", "CPU2", "CPU3"),
                              help="freeze three physical cores for the matched native worker cohort")
    m3_real_plan.add_argument("--measurement-sprintz-query-grouped", help="bind the bounded whole-file Sprintz native query tool")
    m3_real_plan.add_argument("--measurement-huff0-table-grouped", help="bind native ETB1 table and held-out clocks")
    m3_real_plan.add_argument("--measurement-corad-clock", help="bind native calls and train-only Source CORAD clocks")
    m3_real_plan.add_argument("--measurement-corad-raw-encode", action="store_true",
                              help="also time original text ingress and durable encode for CORAD inference")
    m3_real_plan.add_argument("--measurement-zfp", nargs=3, metavar=("FIELD", "OBSERVER", "ARRAY"),
                              help="bind reversible field timing, separate observer, and fixed-rate array")
    m3_real_plan.add_argument("--measurement-zfp-cpus", nargs=2, type=int, metavar=("CPU1", "CPU2"),
                              help="freeze matched field budget on two distinct physical cores")
    m3_real_plan.add_argument("--corad-specialist-amendment", help="apply a content-bound M0 CORAD amendment")
    m3_real_plan.add_argument("--out", type=Path, required=True)
    m3_real_verify = commands.add_parser("m3-real-corpus-verify", allow_abbrev=False)
    m3_real_verify.add_argument("--plan", type=Path, required=True)
    m3_real_run = commands.add_parser("m3-real-corpus-run", allow_abbrev=False, help="run updated M3 real-corpus work items in one ledger")
    m3_real_run.add_argument("--plan", required=True)
    m3_real_run.add_argument("--results", type=Path, default=Path("results/m3-real-runs"))
    m3_real_run.add_argument("--max-work-items", type=int)
    m3_real_run.add_argument("--summary", action="store_true", help="print terminal counts and the sealed report path, not all ledger rows")
    m3_real_run.add_argument("--route", action="append", dest="routes", help="development preflight route filter; never a formal M3 receipt")
    m3_real_run.add_argument("--dataset", action="append", dest="datasets", help="development preflight dataset ID; omits specialized obligations")
    m3_intmult_audit = commands.add_parser("m3-intmult-audit", allow_abbrev=False, help="verify one sealed M3 IntMult run")
    m3_intmult_audit.add_argument("--plan", required=True)
    m3_intmult_audit.add_argument("--run", type=Path, required=True)
    m3_intmult_audit.add_argument("--replay", action="store_true", help="also replay from the run's sealed assets")
    native_run = commands.add_parser("native-run", allow_abbrev=False)
    native_run.add_argument("--build-dir", type=Path, required=True)
    native_run.add_argument("--huff0-portable-build", type=Path, help="separate ENTROPY_DYNAMIC_BMI2=OFF build for same-run Huff0 decode control")
    native_run.add_argument("--plan", type=Path, required=True)
    native_run.add_argument("--results", type=Path, default=Path("results/native-preflight"))
    native_report = commands.add_parser("native-report", allow_abbrev=False)
    native_report.add_argument("run", type=Path)
    batch = commands.add_parser("batch-execution-plan", allow_abbrev=False,
                                help="bind frozen native batch candidates to a local build and per-artifact restoration")
    batch.add_argument("--build-lock", type=Path, required=True)
    batch.add_argument("--suite", choices=("gorilla", "linear-v1", "extended-v1", "extended-v2", "extended-v3", "extended-v4", "extended-v5", "extended-v6", "extended-v7", "extended-v8", "extended-v9", "extended-v10", "extended-v11", "extended-v12", "extended-v13", "extended-v14", "extended-v15", "extended-v16", "extended-v17", "extended-v18", "extended-v19", "extended-v20"),
                       default="gorilla")
    batch.add_argument("--direct-control", help="project-relative direct control executable next to the selected DSO")
    batch.add_argument("--alp-fenv-control", help="project-relative rounding control executable next to ALP")
    batch.add_argument("--titchy-direct-control", help="project-relative native C11 control executable next to Titchy")
    batch.add_argument("--xz-direct-control", help="project-relative direct XZ control executable next to XZ")
    batch.add_argument("--pcodec-direct-control", help="project-relative direct control next to both pcodec plugins")
    batch.add_argument("--pcodec-wrapped-driver", help="project-relative wrapped-page driver next to the pcodec plugins")
    batch.add_argument("--out", type=Path)
    batch.add_argument("--gorilla-direct-control", help="project-relative C11 control alongside the Gorilla plugin (extended-v5)")
    batch.add_argument("--titchy-access-control", help="project-relative Titchy access driver (extended-v9/v10)")
    batch.add_argument("--titchy-stream-control", help="project-relative Titchy packet stream driver (extended-v10 and later)")
    batch.add_argument("--sprintz-direct-control", help="project-relative Sprintz driver alongside its plugin (extended-v8)")
    batch.add_argument("--huff0-direct-control", help="project-relative Huff0 driver alongside its plugin (extended-v7)")
    batch.add_argument("--huff0-portable-build", help="project-relative distinct Huff0 BMI2-OFF build (extended-v20)")
    batch.add_argument("--selfstar-direct-control", help="project-relative ordered SElf* driver alongside its plugin (extended-v6)")
    m0 = commands.add_parser("m0-acceptance-audit", allow_abbrev=False,
                             help="recompute the M0 freeze/skeleton receipt; does not grant native qualification")
    for name, help_text in (("native-submission", "project-relative native submission report"),
                            ("service-plan", "project-relative frozen service scope plan"),
                            ("corpus-check", "project-relative parsed corpus check"),
                            ("feature-report", "project-relative descriptive corpus feature report"),
                            ("source-check", "project-relative source closure check"),
                            ("build-result", "project-relative empty-build result directory")):
        m0.add_argument("--" + name, required=True, help=help_text)
    m0.add_argument("--out", type=Path, required=True)
    m0_real = commands.add_parser("m0-real-corpus-acceptance-audit", allow_abbrev=False,
                             help="recompute the updated M0 real-corpus binding receipt")
    for name, help_text in (("predecessor", "project-relative accepted original M0 receipt"),
                            ("corpus-check", "project-relative parsed full-corpus lock"),
                            ("native-definition", "project-relative rederived native applicability definition"),
                            ("binding", "project-relative content-bound input binding")):
        m0_real.add_argument("--" + name, required=True, help=help_text)
    m0_real.add_argument("--out", type=Path, required=True)
    m1_real = commands.add_parser("m1-real-corpus-acceptance-audit", allow_abbrev=False,
                             help="recompute the updated M1 real-input slice receipt")
    for name, help_text in (("predecessor", "project-relative updated M0 receipt"),
                            ("plan", "project-relative updated M1 plan"),
                            ("report", "project-relative updated M1 report"),
                            ("restore", "project-relative independent restore audit"),
                            ("controls", "project-relative updated M1 control record")):
        m1_real.add_argument("--" + name, required=True, help=help_text)
    m1_real.add_argument("--out", type=Path, required=True)
    m1 = commands.add_parser("m1-acceptance-audit", allow_abbrev=False,
                             help="recompute the M1 minimum lossless vertical-slice receipt")
    m1.add_argument("--plan", required=True, help="project-relative frozen M1 plan")
    m1.add_argument("--report", required=True, help="project-relative derived M1 report")
    m1.add_argument("--restore", required=True, help="project-relative independent M1 restore audit")
    m1.add_argument("--out", type=Path, required=True)
    m2 = commands.add_parser("m2-acceptance-audit", allow_abbrev=False,
                             help="recompute the M2 measurement and scheduler protocol receipt")
    m2.add_argument("--plan", required=True)
    m2.add_argument("--report-a", required=True)
    m2.add_argument("--report-b", required=True)
    m2.add_argument("--repeat", required=True)
    m2.add_argument("--negative-controls", required=True)
    m2.add_argument("--out", type=Path, required=True)
    m2_real = commands.add_parser("m2-real-corpus-acceptance-audit", allow_abbrev=False,
                             help="recompute the updated M2 real-corpus measurement receipt")
    for name in ("plan", "report-a", "report-b", "repeat", "controls"):
        m2_real.add_argument("--" + name, required=True)
    m2_real.add_argument("--out", type=Path, required=True)
    m3 = commands.add_parser("m3-acceptance-audit", allow_abbrev=False,
                             help="recompute the M3 native function and data pipeline receipt")
    for name in ("native-report", "gorilla-report", "gorilla-restore", "composition-report", "composition-restore",
                 "composition-controls", "cross-format-report", "cross-format-restore", "cross-format-controls",
                 "limbs-report", "limbs-restore", "limbs-controls"):
        m3.add_argument("--" + name, required=True)
    m3.add_argument("--out", type=Path, required=True)
    m4 = commands.add_parser("m4-acceptance-audit", allow_abbrev=False,
                             help="recompute the M4 native profiling and measurement-controls receipt")
    m4.add_argument("--plan", required=True, help="project-relative frozen M4 profiling plan")
    m4.add_argument("--report", required=True, help="project-relative recomputed M4 profiling report")
    m4.add_argument("--controls", required=True, help="project-relative M4 measurement controls")
    m4.add_argument("--out", type=Path, required=True)
    submit = commands.add_parser("native-submission-plan", allow_abbrev=False,
                                 help="freeze capacity and retention admission for a complete native preflight")
    submit.add_argument("--execution-plan", type=Path, required=True)
    submit.add_argument("--predecessor-audit", required=True, help="project-relative sealed M0 candidate audit")
    submit.add_argument("--out", type=Path)
    batch_run = commands.add_parser("batch-execution-run", allow_abbrev=False)
    batch_run.add_argument("--plan", type=Path, required=True)
    batch_run.add_argument("--results", type=Path, required=True)
    commands.add_parser("batch-execution-report", allow_abbrev=False).add_argument("run", type=Path)
    commands.add_parser("batch-execution-restore", allow_abbrev=False).add_argument("run", type=Path)
    commands.add_parser("native-qualification-audit", allow_abbrev=False,
                        help="replay a single sealed native candidate against the qualification contract").add_argument("run", type=Path)
    tv = commands.add_parser("tv-plan", allow_abbrev=False, help="freeze complete-object development comparisons")
    tv.add_argument("--build-lock", required=True)
    tv.add_argument("--suite", default=TV_SUITE)
    tv.add_argument("--out", type=Path)
    recipe = commands.add_parser("recipe-plan", allow_abbrev=False, help="lower a recipe to a frozen TV development plan")
    recipe.add_argument("--recipe", required=True, help="project-relative recipe JSON")
    recipe.add_argument("--build-lock", required=True)
    recipe.add_argument("--out", type=Path)
    commands.add_parser("tv-run", allow_abbrev=False).add_argument("--plan", required=True)
    commands.add_parser("tv-report", allow_abbrev=False).add_argument("run", type=Path)
    commands.add_parser("tv-restore-audit", allow_abbrev=False).add_argument("run", type=Path)
    args = parser.parse_args(argv)
    exit_code = 0
    try:
        if args.command == "check-sources":
            check = check_sources(args.root)
            result = {"sources_lock_id": check["sources_lock_id"], "verified_assets": check["verified_assets"],
                      "sources": len(check["sources"]), "selections": len(check["selections"]),
                      "evidence_level": "source_files_only"}
        elif args.command == "check-corpus":
            result = check_corpus(args.root, RELEASES[args.version][0], parse=args.parse)
        elif args.command == "check-full-corpus":
            result = check_full_corpus(args.root, args.manifest, parse=args.parse)
        elif args.command == "corpus-profile":
            result = profile_corpus(args.root)
        elif args.command == "plugins":
            result = {"plugins": discover(args.root)}
        elif args.command == "service-plan-verify":
            result = verify_service_plan(args.root,load_json(args.plan))
        elif args.command == "service-recipe-plan":
            result = plan_service_recipes(args.root,args.bindings,args.build_lock,args.max_workers)
        elif args.command == "service-recipe-verify":
            result = verify_service_recipes(args.root,load_json(args.plan))
        elif args.command == "comparison-plan":
            result = plan_comparison(args.root, args.config)
        elif args.command == "lock-build":
            pairs = [value.split("=", 1) for value in args.plugin]
            require(all(len(pair) == 2 and all(pair) for pair in pairs), "plugins require ID=LOCAL_DSO")
            libraries = dict(pairs)
            require(len(libraries) == len(pairs), "duplicate plugin ID in build binding")
            result = create_build_lock(args.root, args.worker, libraries)
        elif args.command == "smoke-plan":
            result = plan_smoke(args.root, SmokePlanRequest(args.build_lock, args.suite, args.input_config,
                                                            args.native_definition))
        elif args.command == "native-plan":
            result = plan_native(args.root, NativePlanRequest(args.build_dir, args.huff0_portable_build))
        elif args.command == "native-contract-plan":
            result = plan_native_requirements(args.root)
        elif args.command == "native-corpus-plan":
            result = plan_native_corpus(args.root, args.manifest, args.policy)
        elif args.command == "native-corpus-verify":
            result = verify_native_corpus_plan(args.root, load_json(args.plan))
        elif args.command == "m3-real-corpus-plan":
            baseline_args = (args.m0_receipt, args.m1_receipt, args.m2_receipt, args.build_lock)
            if args.switch_from:
                require(not any((*baseline_args, args.gorilla_state_repair_lock, args.huff0_portable_build,
                                 args.pbepla_repair_provenance, args.corad_repair_provenance))
                        and args.measurement_cpu is None and args.measurement_fixed_batch_worker is None
                        and args.measurement_column_batch_worker is None and args.corad_specialist_amendment is None
                        and not args.measurement_gorilla and args.measurement_pcodec_pages_tool is None
                        and args.measurement_abi_corpus_worker is None and args.measurement_selfstar_corpus_worker is None
                        and args.measurement_zfp is None and args.measurement_zfp_cpus is None
                        and args.measurement_titchy_grouped is None and args.measurement_zstd_dictionary_grouped is None
                        and args.measurement_lzbench_tools is None and args.measurement_lzbench_cpus is None
                        and args.measurement_sprintz_query_grouped is None and args.measurement_huff0_table_grouped is None
                        and args.measurement_corad_clock is None and not args.measurement_corad_raw_encode,
                        "M3 input switch cannot override baseline receipts or build bindings")
                result = plan_m3_input_switch(args.root, args.switch_from, args.native_definition)
            else:
                require(all(baseline_args), "M3 full corpus requires M0/M1/M2 receipts and a build lock")
                result = plan_m3_real_corpus(args.root, M3RealCorpusPlanRequest(
                    args.m0_receipt, args.m1_receipt, args.m2_receipt, args.native_definition, args.build_lock,
                    args.gorilla_state_repair_lock, args.huff0_portable_build, args.pbepla_repair_provenance,
                    args.measurement_cpu, args.corad_repair_provenance, args.measurement_fixed_batch_worker,
                    args.measurement_column_batch_worker, args.corad_specialist_amendment, args.measurement_gorilla,
                    args.measurement_pcodec_pages_tool, args.measurement_abi_corpus_worker,
                    args.measurement_selfstar_corpus_worker,
                    tuple(args.measurement_zfp) if args.measurement_zfp else None,
                    tuple(args.measurement_zfp_cpus) if args.measurement_zfp_cpus else None,
                    args.measurement_titchy_grouped, args.measurement_zstd_dictionary_grouped,
                    tuple(args.measurement_lzbench_tools) if args.measurement_lzbench_tools else None,
                    tuple(args.measurement_lzbench_cpus) if args.measurement_lzbench_cpus else None,
                    args.measurement_sprintz_query_grouped, args.measurement_huff0_table_grouped,
                    args.measurement_corad_clock, args.measurement_corad_raw_encode))
        elif args.command == "m3-real-corpus-verify":
            result = check_m3_real_corpus_plan(args.root, load_json(args.plan)) or {"plan_verified": True}
        elif args.command == "m3-real-corpus-run":
            results = args.results if args.results.is_absolute() else args.root / args.results
            results.mkdir(parents=True, exist_ok=True)
            result = run_m3_real_corpus(args.root, load_json(local_file(args.root, args.plan)), results,
                                        limit=args.max_work_items,
                                        route_filter=set(args.routes) if args.routes else None,
                                        dataset_filter=set(args.datasets) if args.datasets else None)
            if args.summary:
                result = {**{k: result[k] for k in ('schema', 'run_id', 'plan_content_id', 'partial_preflight',
                                                   'selected_corpus_decisions', 'selected_work_items', 'statuses',
                                                   'obligation_statuses', 'stage_accepted', 'qualification_granted',
                                                   'timing_admitted')},
                          'report': str((results / result['run_id'] / 'report.json').resolve())}
        elif args.command == "m3-intmult-audit":
            run = args.run if args.run.is_absolute() else args.root / args.run
            result = audit_m3_intmult_run(args.root, load_json(local_file(args.root, args.plan)), run, replay=args.replay)
        elif args.command == "native-admission-plan":
            result = plan_native_admission(args.root)
        elif args.command == "m0-acceptance-audit":
            result = audit_m0(args.root, native_submission=args.native_submission, service_plan=args.service_plan,
                              corpus_check=args.corpus_check, feature_report=args.feature_report,
                              source_check=args.source_check, build_result=args.build_result)
        elif args.command == "m0-real-corpus-acceptance-audit":
            result = audit_m0_real_corpus(args.root, predecessor=args.predecessor, corpus_check=args.corpus_check,
                                          native_definition=args.native_definition, binding=args.binding)
        elif args.command == "m1-real-corpus-acceptance-audit":
            result = audit_m1_real_corpus(args.root, predecessor=args.predecessor, plan=args.plan,
                                          report=args.report, restore=args.restore, controls=args.controls)
        elif args.command == "m1-acceptance-audit":
            result = audit_m1(args.root, plan=args.plan, report=args.report, restore=args.restore)
        elif args.command == "m2-acceptance-audit":
            result = audit_m2(args.root, plan=args.plan, report_a=args.report_a, report_b=args.report_b,
                              repeat=args.repeat, negative_controls=args.negative_controls)
        elif args.command == "m2-real-corpus-acceptance-audit":
            result = audit_m2_real_corpus(args.root, plan=args.plan, report_a=args.report_a, report_b=args.report_b,
                                          repeat=args.repeat, controls=args.controls)
        elif args.command == "m3-acceptance-audit":
            result = audit_m3(args.root, native_report=args.native_report, gorilla_report=args.gorilla_report,
                              gorilla_restore=args.gorilla_restore, composition_report=args.composition_report,
                              composition_restore=args.composition_restore, composition_controls=args.composition_controls,
                              cross_format_report=args.cross_format_report, cross_format_restore=args.cross_format_restore,
                              cross_format_controls=args.cross_format_controls, limbs_report=args.limbs_report,
                              limbs_restore=args.limbs_restore, limbs_controls=args.limbs_controls)
        elif args.command == "m4-acceptance-audit":
            result = audit_m4(args.root, plan=args.plan, report=args.report, controls=args.controls)
        elif args.command == "native-submission-plan":
            result = plan_native_submission(args.root, load_json(args.execution_plan), args.predecessor_audit)
        elif args.command == "batch-execution-plan":
            result = plan_batch_execution(args.root, load_json(args.build_lock), direct_control=args.direct_control, suite=args.suite,
                                          fenv_control=args.alp_fenv_control, titchy_control=args.titchy_direct_control,
                                          xz_control=args.xz_direct_control, pcodec_control=args.pcodec_direct_control,
                                          wrapped_driver=args.pcodec_wrapped_driver,gorilla_control=args.gorilla_direct_control,
                                          selfstar_control=args.selfstar_direct_control,huff0_control=args.huff0_direct_control,
                                          sprintz_control=args.sprintz_direct_control,titchy_access_control=args.titchy_access_control,
                                          titchy_stream_control=args.titchy_stream_control,huff0_portable_build=args.huff0_portable_build)
        elif args.command == "tv-plan":
            result = plan_tv(args.root, args.build_lock, args.suite)
        elif args.command == "recipe-plan":
            result = plan_recipe(args.root, args.build_lock, args.recipe)
        elif args.command == "profile-plan":
            result = plan_profile(args.root, args.plain_build, args.profile_build)
        elif args.command == "timing-plan":
            result = plan_timing(args.root, TimingPlanRequest(args.build_dir, args.cpu))
        elif args.command == "m2-real-corpus-plan":
            result = plan_m2_real_corpus(args.root, M2RealCorpusPlanRequest(args.m0_receipt, args.m1_receipt, args.timing_plan))
        elif args.command in {"smoke-run", "native-run", "tv-run", "batch-execution-run", "timing-run", "profile-run"}:
            native = args.command == "native-run"
            batch_run = args.command == "batch-execution-run"
            document = load_json(args.plan if native or batch_run else local_file(args.root, args.plan))
            cancelled = Event()
            previous = {}
            def request_cancel(_signal, _frame):
                cancelled.set()
            try:
                for sig in (signal.SIGINT, signal.SIGTERM):
                    previous[sig] = signal.signal(sig, request_cancel)
                if native:
                    result = run_native(args.root, NativePlanRequest(args.build_dir, args.huff0_portable_build), document, args.results,
                                        cancelled=cancelled.is_set)
                elif batch_run:
                    execute = run_native_submission if isinstance(document, dict) and document.get("schema") == NATIVE_SUBMISSION else run_batch_execution
                    result = execute(args.root, document, args.results, cancelled=cancelled.is_set)
                elif args.command == "profile-run":
                    result = run_profile(args.root, document, cancelled=cancelled.is_set)
                elif args.command == "timing-run":
                    result = run_timing(args.root, document, cancelled=cancelled.is_set)
                elif args.command == "tv-run":
                    result = run_tv(args.root, document, cancelled=cancelled.is_set)
                else:
                    result = run_smoke(args.root, document, cancelled=cancelled.is_set)
            finally:
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
            if batch_run:
                exit_code = 0 if result["all_product_expectations_met"] else 1
            elif args.command == "timing-run":
                exit_code = 0 if result["all_batches_verified"] else 1
            elif args.command == "tv-run":
                exit_code = 0 if result["verified"] and result["recovery"]["ready"] else 1
            else:
                exit_code = 0 if result["all_probes_passed" if native else "all_verified"] else 1
            if not native and result.get("recovery", {}).get("status") == "unavailable":
                exit_code = 1
        elif args.command == "smoke-restore-audit":
            result = audit_smoke_restore(args.root, args.run_id)
        elif args.command == "profile-report":
            result = report_profile(args.root, args.run_id)
        elif args.command == "timing-report":
            result = report_timing(args.root, args.run_id)
        elif args.command == "timing-compare-repeats":
            result = compare_timing_repeats(args.root, args.first_run, args.second_run)
        elif args.command == "smoke-report":
            result = report_smoke(args.root, args.run_id)
        elif args.command == "tv-report":
            result = report_tv(args.run)
        elif args.command == "tv-restore-audit":
            result = restore_tv(args.run)
        elif args.command == "batch-execution-report":
            result = report_batch_execution(args.run)
        elif args.command == "batch-execution-restore":
            result = audit_batch_execution(args.run)
        elif args.command == "native-qualification-audit":
            result = audit_native_qualification(args.root,args.run)
        elif args.command == "native-report":
            result = report_native(args.run)
        else:
            request = load_request(args.root, args.config) if args.config else PlanRequest()
            if args.suite is not None:
                request = replace(request, suite=args.suite)
            if args.max_workers is not None:
                request = replace(request, max_workers=args.max_workers)
            result = plan(args.root, request).document
        text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if args.command in {"plan", "native-contract-plan", "native-admission-plan", "native-corpus-plan", "m3-real-corpus-plan", "service-recipe-plan"} and args.out:
            _publish(args.out, text)
            print(json.dumps({"plan_content_id": result["plan_content_id"], "runnable": result["runnable"],
                              "coverage": result["coverage"], "out": str(args.out)}, ensure_ascii=False))
        elif args.command in {"lock-build", "smoke-plan", "native-plan", "comparison-plan", "tv-plan", "recipe-plan", "batch-execution-plan", "native-submission-plan", "timing-plan", "m2-real-corpus-plan", "profile-plan"} and args.out:
            _publish(args.out, text)
            key = {"lock-build":"build_id", "comparison-plan":"comparison_id"}.get(args.command,"plan_content_id")
            print(json.dumps({key: result[key], **({"coverage": result["coverage"]} if args.command == "native-plan" else {}),
                              "out": str(args.out)}, ensure_ascii=False))
        elif args.command in {"m0-acceptance-audit", "m0-real-corpus-acceptance-audit", "m1-real-corpus-acceptance-audit", "m1-acceptance-audit", "m2-acceptance-audit", "m2-real-corpus-acceptance-audit", "m3-acceptance-audit", "m4-acceptance-audit"} and args.out:
            _publish(args.out, text)
            print(json.dumps({"receipt_id": result["receipt_id"], "stage": result["stage"],
                              "stage_accepted": result["stage_accepted"], "out": str(args.out)}, ensure_ascii=False))
        else:
            sys.stdout.write(text)
    except (ContractError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "rejected", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return exit_code
