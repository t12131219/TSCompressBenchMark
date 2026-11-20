"""M3 measured primary executor for a frozen CORAD evidence amendment."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import tempfile
import uuid

from ..assets import ContractError, content_id, digest, load_json, local_file, require
from ..planner.m3_corad import ROUTES as CORAD_ROUTES
from .m3_corad import run_file as run_corad_file, stage as stage_corad
from .m3_alp_specialized import run_specialized as run_alp_specialized
from .m3_batch_specialized import run_specialized as run_batch_specialized
from ..planner.m3_batch_specialized import FAMILIES as BATCH_SPECIALIZED_FAMILIES
from .m3_corad_specialized_v2 import run_specialized as run_corad_specialized
from ..planner.m3_fixed_batch import DIRECTORY as FIXED_BATCH_RUNTIME, ROUTES as FIXED_BATCH_ROUTES
from .m3_fixed_batch import run_fixed_batch
from ..planner.m3_intmult import KEY as INTMULT_KEY
from ..planner.m3_huff0_fec1 import DIRECTORY as HUFF0_FEC1_RUNTIME, KEY as HUFF0_FEC1_KEY
from ..planner.m3_huff0_table import KEY as HUFF0_TABLE_KEY
from ..recovery import stage_recovery
from .m3_huff0_fec1 import run_fec1
from .m3_huff0_specialized import run_specialized as run_huff0_specialized
from .m3_huff0_table import run_table as run_huff0_table
from ..planner.m3_lzbench_session import ROUTES as LZBENCH_SESSION_ROUTES
from .m3_lzbench_session import run_session as run_lzbench_session
from .m3_lzbench_specialized import run_specialized as run_lzbench_specialized
from ..planner.lzbench_profiles import ROUTES as LZBENCH_PROFILE_ROUTES
from .m3_lzbench_profiles import run_specialized as run_lzbench_profiles
from ..planner.m3_lzbench_workers import ROUTES as LZBENCH_WORKERS_ROUTES
from .m3_lzbench_workers import run_workers as run_lzbench_workers
from ..planner.m3_pbepla import PROGRESSIVE, REPLAY, ROUTES as PBEPLA_ROUTES
from .m3_pbepla_repair import run_corpus as run_pbepla_repair
from .m3_pbepla_specialized import run_specialized as run_pbepla_specialized
from ..planner.m3_selfstar import DRIVERS as SELFSTAR_DRIVERS
from ..planner.m3_sprintz import BATCH as SPRINTZ_BATCH_ROUTE
from ..planner.m3_real_corpus import (GORILLA_CORPUS_ROUTES, PCODEC_PAGE_ROUTES, SPRINTZ_QUERY_ROUTE, TITCHY_ACCESS_ROUTES, TITCHY_STREAM_ROUTE,
                                    check_m3_real_corpus_plan)
from .m3_gorilla import run_gorilla
from .m3_gorilla_specialized import run_bound_corpus, run_specialized
from .m3_pcodec_pages import run_pcodec_pages
from .m3_intmult import run_intmult
from .m3_selfstar import run_selfstar, run_specialized as run_selfstar_specialized
from .m3_sprintz import run_batch as run_sprintz_batch, run_specialized as run_sprintz_specialized
from .m3_sprintz_query import SprintzHardwarePending, run_sprintz_query
from ..planner.m3_titchy import BATCH as TITCHY_BATCH_ROUTE
from .m3_titchy import run_batch as run_titchy_batch, run_specialized as run_titchy_specialized, stage_titchy
from .m3_titchy_access import run_titchy_access
from ..planner.m3_zfp import ROUTES as ZFP_ROUTES
from .m3_zfp import run_corpus as run_zfp_corpus
from .m3_zfp_specialized import run_specialized as run_zfp_specialized
from .m3_titchy_stream import run_titchy_stream
from ..planner.m3_zstd_dictionary import KEY as ZSTD_DICTIONARY_KEY
from .m3_zstd_dictionary import run_dictionary as run_zstd_dictionary

from .m3_real_corpus_execution import SCHEMA, _entry_map, _relevant, _run_bytes, _run_value, _stage_dataset
from .m3_primary_measurement import observe
from ..supervisor.timing_resource import reserve


def run_m3_real_corpus(root: Path, plan: dict, results: Path, *, limit: int | None = None,
                        route_filter: set[str] | None = None, dataset_filter: set[str] | None = None) -> dict:
    with reserve():
        return _execute(root, plan, results, limit, route_filter, dataset_filter)


def _execute(root, plan, results, limit, route_filter, dataset_filter):
    require('measurement' in plan, 'M3 measured execution requires a frozen timing population')
    root = root.resolve(strict=True)
    check_m3_real_corpus_plan(root, plan)
    build = load_json(local_file(root, plan["build"]["lock"]["path"]))
    definition = load_json(local_file(root, plan["definition"]["plan"]["path"]))
    entries = _entry_map(root, definition)
    pbepla_pairs = {(r["dataset_id"],r["route"]): r for r in plan["work_items"] if (r["selection"],r["route"]) in PBEPLA_ROUTES}
    route_names = {r["route"] for r in plan["routes"]}
    require(route_filter is None or bool(route_filter) and route_filter <= route_names, "unknown M3 preflight route")
    require(dataset_filter is None or bool(dataset_filter) and dataset_filter <= entries.keys(), 'unknown M3 preflight dataset')
    selected = [item for item in plan["work_items"] if (route_filter is None or item["route"] in route_filter) and
                (dataset_filter is None or item['dataset_id'] in dataset_filter)]
    if limit is not None:
        require(type(limit) is int and limit > 0, "M3 preflight limit must be positive")
        selected = [r for r in selected if r["applicability"] == "input_domain_matches"][:limit]
    require(selected, "M3 request selects no corpus decisions")
    corad_binding = plan['build'].get('corad_corpus')
    corad_names = {r for _, r in CORAD_ROUTES}
    if corad_binding and route_filter and route_filter & corad_names:
        require(corad_names <= route_filter, 'CORAD preflight requires all producer and inference routes in the same run')
    corad_items = {}
    for i in selected:
        if (i['selection'], i['route']) in CORAD_ROUTES and i['applicability'] == 'input_domain_matches':
            corad_items.setdefault(i['dataset_id'], {})[i['route']] = i
    run_id = uuid.uuid4().hex
    run = results.resolve() / run_id
    run.mkdir(parents=True, exist_ok=False)
    fixed_batch_binding = plan['build'].get('fixed_batch')
    fixed_batch_error = ''
    if fixed_batch_binding and any((i['selection'], i['route']) in FIXED_BATCH_ROUTES and
                                   i['applicability'] == 'input_domain_matches' for i in selected):
        try:
            stage_recovery(root, run, fixed_batch_binding['decoder'], directory=FIXED_BATCH_RUNTIME)
        except (ContractError, OSError) as exc:
            fixed_batch_error = str(exc) or type(exc).__name__
    fec1_binding = plan['build'].get('huff0_fec1')
    if fec1_binding and any((i['selection'], i['route']) == HUFF0_FEC1_KEY and
                           i['applicability'] == 'input_domain_matches' for i in selected):
        stage_recovery(root, run, fec1_binding['decoder'], directory=HUFF0_FEC1_RUNTIME)
    corad_cache, corad_errors = {}, {}
    corad_bridge, corad_dependency_error = None, ''
    if corad_binding and any(group.keys() == corad_names for group in corad_items.values()):
        try:
            corad_bridge = stage_corad(root, run, corad_binding)
        except (ContractError, OSError) as exc:
            corad_dependency_error = str(exc) or type(exc).__name__
    rows = []
    counts = {}
    ledger = run / "ledger.jsonl"

    def append(entry):
        with ledger.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    for item in selected:
        row = {"work_item_id": item["work_item_id"], "dataset_id": item["dataset_id"],
               "selection": item["selection"], "route": item["route"], "operation": item["operation"],
               "applicability": item["applicability"], "status": "not_run", "reason": "", "evidence": None}
        pcodec_pages = (item["selection"], item["route"]) in PCODEC_PAGE_ROUTES and "pcodec_pages" in plan["build"]
        titchy_bound = 'titchy' in plan.get('specialized', {})
        titchy_batch = (item['selection'], item['route']) == TITCHY_BATCH_ROUTE and titchy_bound
        titchy_access = (item["selection"], item["route"]) in TITCHY_ACCESS_ROUTES and "titchy_access" in plan["build"]
        titchy_stream = (item["selection"], item["route"]) == TITCHY_STREAM_ROUTE and "titchy_stream" in plan["build"]
        sprintz_query = (item["selection"], item["route"]) == SPRINTZ_QUERY_ROUTE and "sprintz_query" in plan["build"]
        selfstar = (item["selection"], item["route"]) in SELFSTAR_DRIVERS and "selfstar" in plan.get("specialized", {})
        sprintz_batch = (item["selection"], item["route"]) == SPRINTZ_BATCH_ROUTE and "sprintz" in plan.get("specialized", {})
        gorilla = (item["selection"], item["route"]) in GORILLA_CORPUS_ROUTES and "gorilla_corpus" in plan["build"]
        zfp = (item["selection"], item["route"]) in ZFP_ROUTES and "zfp_corpus" in plan["build"]
        pbepla = (item["selection"], item["route"]) in PBEPLA_ROUTES and "pbepla_corpus" in plan["build"]
        lz_session = (item['selection'], item['route']) in LZBENCH_SESSION_ROUTES and 'lzbench_session' in plan['build']
        zstd_dict = (item['selection'],item['route']) == ZSTD_DICTIONARY_KEY and 'zstd_dictionary' in plan['build']
        lz_workers = (item['selection'],item['route']) in LZBENCH_WORKERS_ROUTES and 'lzbench_workers' in plan['build']
        huff_table = (item['selection'],item['route']) == HUFF0_TABLE_KEY and 'huff0_table' in plan['build']
        huff_fec1 = (item['selection'], item['route']) == HUFF0_FEC1_KEY and fec1_binding is not None
        fixed_batch = fixed_batch_binding is not None and (item['selection'], item['route']) in FIXED_BATCH_ROUTES
        if item["applicability"] != "input_domain_matches":
            row.update(status=item["applicability"], reason="; ".join(item["reasons"]))
        elif fixed_batch and fixed_batch_error:
            row.update(status='dependency_failed', reason=fixed_batch_error)
        elif corad_binding and (item['selection'], item['route']) in CORAD_ROUTES:
            dataset, route = item['dataset_id'], item['route']
            group = corad_items[dataset]
            if group.keys() != corad_names:
                row.update(status='not_run', reason='bounded preflight excludes one or more same-run CORAD dependencies')
            elif corad_bridge is None:
                row.update(status='dependency_failed', reason=corad_dependency_error)
            else:
                if dataset not in corad_cache and dataset not in corad_errors:
                    try:
                        corad_cache[dataset] = run_corad_file(root, plan, entries[dataset], group, run, corad_bridge)
                    except (ContractError, OSError, RuntimeError) as exc:
                        corad_errors[dataset] = str(exc) or type(exc).__name__
                if dataset in corad_errors:
                    row.update(status='failed', reason=corad_errors[dataset])
                else:
                    row.update(corad_cache[dataset].pop(route))
        elif not (pcodec_pages or titchy_access or titchy_stream or titchy_batch or sprintz_query or sprintz_batch or selfstar or gorilla or zfp or pbepla or lz_session or zstd_dict or lz_workers or huff_table or huff_fec1 or _relevant(item)):
            row.update(status="pending_driver", reason="route-specific operation driver not yet bound")
        else:
            try:
                with tempfile.TemporaryDirectory(prefix="m3-corpus-work-") as td:
                    work = Path(td)
                    entry = entries[item["dataset_id"]]
                    if huff_table:
                        evidence=run_huff0_table(root,plan,item,entry,work,run)
                    elif huff_fec1:
                        staged = _stage_dataset(root, entry, work, item['view'])
                        evidence = run_fec1(plan, item, entry, staged, work, run)
                    elif zstd_dict:
                        evidence = run_zstd_dictionary(root,plan,item,entry,work,run)
                    elif lz_workers:
                        staged = _stage_dataset(root,entry,work,item['view'])
                        evidence = run_lzbench_workers(root,plan,item,entry,staged,work,run)
                    elif lz_session:
                        staged = _stage_dataset(root, entry, work, item['view'])
                        evidence = run_lzbench_session(root, plan, item, entry, staged, work, run)
                    elif pbepla:
                        partner = pbepla_pairs[item['dataset_id'], PROGRESSIVE if item['route'] == REPLAY else REPLAY]
                        evidence = run_pbepla_repair(root, plan, item, partner, entry, work, run)
                    elif zfp:
                        evidence = run_zfp_corpus(root, plan, item, entry, work, run)
                    elif pcodec_pages:
                        staged = _stage_dataset(root, entry, work, item["view"])
                        evidence = run_pcodec_pages(root, plan, item, staged, work, run)
                    elif titchy_batch:
                        evidence = run_titchy_batch(root, plan, item, entry, work, run)
                    elif titchy_access:
                        staged = stage_titchy(root, entry, work) if titchy_bound else _stage_dataset(root, entry, work, item["view"])
                        evidence = run_titchy_access(root, plan, item, staged, work, run)
                    elif titchy_stream:
                        staged = stage_titchy(root, entry, work) if titchy_bound else _stage_dataset(root, entry, work, item["view"])
                        evidence = run_titchy_stream(root, plan, item, staged, work, run)
                    elif selfstar:
                        evidence = run_selfstar(root, plan, item, entry, work, run)
                    elif sprintz_batch:
                        evidence = run_sprintz_batch(root, plan, item, entry, work, run)
                    elif sprintz_query:
                        evidence = run_sprintz_query(root, plan, item, entry, work, run)
                    elif gorilla:
                        runner = run_bound_corpus if "gorilla_state_repair" in plan["build"] else run_gorilla
                        evidence = runner(root, plan, item, entry, work, run)
                    elif fixed_batch:
                        staged = _stage_dataset(root, entry, work, item['view'])
                        evidence = run_fixed_batch(item, staged, work, run, fixed_batch_binding)
                    elif item["view"] == "v_bytes_interleaved":
                        evidence = _run_bytes(root, plan, item, entry, work, build)
                    else:
                        evidence = _run_value(root, plan, item, entry, work, build)
                    rejected = evidence['quality_rejected_units'] if zfp or pbepla else 0
                    failed = evidence['failed_units'] if pbepla or zstd_dict else 0
                    reasons = []
                    if huff_table and evidence['errors']:
                        failed=len(evidence['errors'])
                        reasons.extend(evidence['errors'])
                    elif lz_workers and evidence['unmet_worker_observations']:
                        failed = len(evidence['unmet_worker_observations'])
                        reasons.append('native worker census differs from requirement: '+', '.join(evidence['unmet_worker_observations']))
                    elif failed and zstd_dict:
                        reasons.append(evidence.get('failure_reason',f'{failed} frozen Zstd dictionary frames failed validation'))
                    elif failed:
                        reasons.append(f'{failed} frozen PBEPLA windows failed native execution or validation')
                    if rejected:
                        reasons.append(f'{rejected} frozen {"PBEPLA" if pbepla else "ZFP array"} windows exceeded the quality bound')
                    row.update(status='failed' if failed else 'quality_rejected' if rejected else 'verified',
                               evidence=evidence, reason='; '.join(reasons))
            except SprintzHardwarePending as exc:
                row.update(status="hardware_pending", reason=str(exc))
            except (ContractError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
                row.update(status="failed", reason=str(exc))
        row['measurement'] = observe(root, plan, item, entries[item['dataset_id']], pbepla_pairs, run, row)
        rows.append(row)
        counts[row["status"]] = counts.get(row["status"], 0) + 1
        append(row)
    obligations = [{"entry_kind": "specialized_obligation", "obligation_id": o["obligation_id"],
                    "selection": o["selection"], "route": o["route"], "check": o["check"], "kind": o["kind"],
                    "status": "not_run", "reason": "no specialized driver bound to the frozen obligation", "evidence": None}
                   for o in plan["obligations"] if limit is None and dataset_filter is None and
                   (route_filter is None or o["route"] in route_filter)]
    intmult = [o for o in obligations if (o["selection"], o["route"]) == INTMULT_KEY]
    binding = plan.get("specialized", {}).get("pcodec_intmult")
    specialized = {"pcodec_intmult": run_intmult(root, run, binding, intmult)} if binding and intmult else {}
    if 'pcodec_intmult' in specialized:
        for product in specialized['pcodec_intmult']['fixtures'].values():
            append({'entry_kind': 'specialized_product', 'selection': INTMULT_KEY[0], 'route': INTMULT_KEY[1], **product})
    for family, (_, routes, _, _, _) in BATCH_SPECIALIZED_FAMILIES.items():
        batch_rows = [o for o in obligations if (o['selection'], o['route']) in routes]
        batch_binding = plan.get('specialized', {}).get(family)
        if batch_rows and batch_binding:
            specialized[family] = run_batch_specialized(root, run, batch_binding, batch_rows, append)
    alp_rows = [o for o in obligations if o['selection'] == 9]
    alp_binding = plan.get('specialized', {}).get('alp')
    if alp_rows and alp_binding:
        specialized['alp'] = run_alp_specialized(root, run, alp_binding, alp_rows, append)
    gorilla_rows = [o for o in obligations if o["selection"] == 7]
    gorilla_binding = plan.get("specialized", {}).get("gorilla")
    if gorilla_rows and gorilla_binding:
        specialized["gorilla"] = run_specialized(root, run, gorilla_binding, gorilla_rows, append, build=plan["build"])
    sprintz_rows = [o for o in obligations if o["selection"] == 19]
    sprintz_binding = plan.get("specialized", {}).get("sprintz")
    if sprintz_rows and sprintz_binding:
        specialized["sprintz"] = run_sprintz_specialized(root, run, sprintz_binding, sprintz_rows, append)
    selfstar_rows = [o for o in obligations if o["selection"] == 4]
    selfstar_binding = plan.get("specialized", {}).get("selfstar")
    if selfstar_rows and selfstar_binding:
        specialized["selfstar"] = run_selfstar_specialized(root, run, selfstar_binding, selfstar_rows, append)
    titchy_rows = [o for o in obligations if o['selection'] == 85]
    titchy_binding = plan.get('specialized', {}).get('titchy')
    if titchy_rows and titchy_binding:
        specialized['titchy'] = run_titchy_specialized(root, run, titchy_binding, titchy_rows, append)
    zfp_rows = [o for o in obligations if o['selection'] == 31]
    zfp_binding = plan.get('specialized', {}).get('zfp')
    if zfp_rows and zfp_binding:
        specialized['zfp'] = run_zfp_specialized(root, run, zfp_binding, zfp_rows, append)
    pbepla_rows = [o for o in obligations if o['selection'] == 87]
    pbepla_binding = plan.get('specialized', {}).get('pbepla')
    if pbepla_rows and pbepla_binding:
        specialized['pbepla'] = run_pbepla_specialized(root, run, pbepla_binding, pbepla_rows, append)
    lzbench_rows = [o for o in obligations if (o['selection'],o['route']) in LZBENCH_SESSION_ROUTES]
    lzbench_binding = plan.get('specialized',{}).get('lzbench_session')
    if lzbench_rows and lzbench_binding:
        specialized['lzbench_session'] = run_lzbench_specialized(root,run,lzbench_binding,lzbench_rows,append)
    profile_rows = [o for o in obligations if (o['selection'],o['route']) in LZBENCH_PROFILE_ROUTES]
    profile_binding = plan.get('specialized',{}).get('lzbench_profiles')
    if profile_rows and profile_binding:
        specialized['lzbench_profiles'] = run_lzbench_profiles(root,run,profile_binding,profile_rows,append)
    huff0_rows = [o for o in obligations if o['selection'] == 29]
    huff0_binding = plan.get('specialized', {}).get('huff0')
    if huff0_rows and huff0_binding:
        specialized['huff0'] = run_huff0_specialized(root, run, huff0_binding, huff0_rows, append)
    corad_rows = [o for o in obligations if (o['selection'], o['route']) in CORAD_ROUTES]
    corad_specialized = plan.get('specialized', {}).get('corad')
    if corad_rows and corad_specialized:
        specialized['corad'] = run_corad_specialized(root, run, corad_specialized, plan['corad_specialist_amendment'], corad_rows, append)
    obligation_counts = {}
    for row in obligations:
        obligation_counts[row["status"]] = obligation_counts.get(row["status"], 0) + 1
        append(row)
    report = {"schema": SCHEMA, "run_id": run_id, "plan_content_id": plan["plan_content_id"],
              "stage_accepted": False, "qualification_granted": False, "timing_admitted": False,
              "partial_preflight": limit is not None or route_filter is not None or dataset_filter is not None,
              "route_filter": sorted(route_filter) if route_filter is not None else None,
              **({'dataset_filter': sorted(dataset_filter)} if dataset_filter is not None else {}),
              **({'max_work_items': limit} if limit is not None else {}),
              "planned_work_items": len(plan["work_items"]),
              "selected_work_items": sum(r["applicability"] == "input_domain_matches" for r in selected),
              "selected_corpus_decisions": len(selected), "statuses": dict(sorted(counts.items())),
              "obligations": obligations, "obligation_statuses": dict(sorted(obligation_counts.items())),
              "specialized": specialized,
              "rows": rows, "artifact_retention": "verified_then_released_after_hash_and_size",
              "execution_policy": plan["execution_policy"]}
    (run / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    seal = {"schema": "bmk.m3-real-corpus-run-seal/1", "run_id": run_id,
            "plan_content_id": plan["plan_content_id"], "report_sha256": digest(run / "report.json"),
            "ledger_sha256": digest(ledger)}
    (run / "completion.json").write_text(json.dumps({**seal, "seal_id": content_id(seal)}, indent=2) + "\n", encoding="utf-8")
    return report
