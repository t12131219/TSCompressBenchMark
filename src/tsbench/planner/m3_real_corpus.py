"""Freeze the updated M3 full real-corpus execution denominator.

This planner deliberately does not turn the M0 applicability definition into a
qualification result.  It creates the single-run work ledger skeleton that the
M3 executor must fill with actual codec evidence.
"""
from dataclasses import dataclass
from pathlib import Path

from ..assets import content_id, digest, load_json, local_file, require, verify_asset
from .m3_corad import (DRIVER as CORAD_DRIVER, ROUTES as CORAD_ROUTES,
                       bind as bind_corad, check_route as check_corad)
from .m3_alp_specialized import bind as bind_alp_specialized
from .m3_batch_specialized import PCODEC as PCODEC_SPECIALIZED, LZBENCH as LZBENCH_BASELINE, bind as bind_batch_specialized
from .m3_corad_specialized import bind as bind_corad_specialized
from .m3_corad_repair import bind as bind_corad_repair
from .m3_fixed_batch import DRIVER as FIXED_BATCH_DRIVER, ROUTES as FIXED_BATCH_ROUTES, bind as bind_fixed_batch
from .m3_gorilla_specialized import bind_specialized as bind_gorilla_specialized, load_repair
from .m3_huff0_table import (DRIVER as HUFF0_TABLE_DRIVER, KEY as HUFF0_TABLE_KEY,
                             bind as bind_huff0_table, check_route as check_huff0_table)
from .m3_huff0_fec1 import (DRIVER as HUFF0_FEC1_DRIVER, KEY as HUFF0_FEC1_KEY,
                            bind as bind_huff0_fec1, check_route as check_huff0_fec1)
from .huff0_bmi2 import KEY as HUFF0_PORTABLE_KEY
from .m3_huff0_specialized import bind as bind_huff0_specialized
from .m3_intmult import bind_intmult
from .m3_lzbench_session import (DRIVER as LZBENCH_SESSION_DRIVER, ROUTES as LZBENCH_SESSION_ROUTES,
                                 bind as bind_lzbench_session, check_route as check_lzbench_session)
from .m3_lzbench_specialized import bind as bind_lzbench_specialized
from .m3_lzbench_profiles import bind as bind_lzbench_profiles
from .m3_lzbench_workers import (DRIVER as LZBENCH_WORKERS_DRIVER, ROUTES as LZBENCH_WORKERS_ROUTES,
                                 bind as bind_lzbench_workers, check_route as check_lzbench_workers)
from .m3_pbepla import (DRIVER as PBEPLA_DRIVER, ROUTES as PBEPLA_ROUTES,
                       bind_corpus as bind_pbepla, check_route as check_pbepla_route)
from .m3_pbepla_specialized import bind as bind_pbepla_specialized
from .m3_pbepla_repair import bind as bind_pbepla_repair
from .m3_selfstar import DRIVERS as SELFSTAR_DRIVERS, available as selfstar_available, bind_selfstar
from .m3_sprintz import BATCH as SPRINTZ_BATCH_ROUTE, DRIVER as SPRINTZ_BATCH_DRIVER, bind_sprintz
from .m3_titchy import BATCH as TITCHY_BATCH_ROUTE, BATCH_DRIVER as TITCHY_BATCH_DRIVER, bind_titchy
from .m3_zfp import DRIVER as ZFP_DRIVER, ROUTES as ZFP_ROUTES, bind_corpus as bind_zfp_corpus, check_route as check_zfp_route
from .m3_zfp_specialized import bind as bind_zfp_specialized
from .m3_zstd_dictionary import (DRIVER as ZSTD_DICTIONARY_DRIVER, KEY as ZSTD_DICTIONARY_KEY,
                                  bind as bind_zstd_dictionary, check_route as check_zstd_dictionary)
from .native_corpus import verify_native_corpus_plan

SCHEMA = "bmk.m3-real-corpus-plan/1"
PCODEC_PAGE_ROUTES = {(11, "source-pages"), (11, "native-pages")}
PCODEC_PAGE_DRIVER = "pcodec-pages-control/1"
TITCHY_ACCESS_ROUTES = {(85, "batch-range"), (85, "loaded-file-access")}
TITCHY_ACCESS_DRIVER = "titchy-access-control/1"
TITCHY_STREAM_ROUTE = (85, "packet-stream")
TITCHY_STREAM_DRIVER = "titchy-stream-control/1"
SPRINTZ_QUERY_ROUTE = (19, "query")
SPRINTZ_QUERY_DRIVER = "sprintz-corpus-query/1"
GORILLA_CORPUS_ROUTES = {(7, route) for route in ("tv-batch", "append-resume", "iterator")}
GORILLA_CORPUS_DRIVER = "gorilla-corpus-control/1"


def _gorilla_corpus_binding(root: Path, build: dict) -> dict | None:
    entry = build["plugins"]["gorilla-tv"]
    parent = Path(entry["library"]["path"]).parent
    exe = (parent / "tsbench_gorilla_corpus_control").as_posix()
    if not (root / exe).exists():
        return None
    dependency = (parent / "libgorilla_c.so").as_posix()
    require(len(entry["dependencies"]) == 1 and entry["dependencies"][0]["path"] == dependency,
            "Gorilla corpus control must share the locked C11 dependency")
    verify_asset(root, entry["dependencies"][0])
    return {"executable": _ref(root, exe), "dependency": _ref(root, dependency),
            "adapter": _ref(root, "src/tsbench/application/m3_gorilla.py"),
            "wire_validator": _ref(root, "src/tsbench/qualification/gorilla.py")}


def _sprintz_query_binding(root: Path, build: dict) -> dict | None:
    entry = build["plugins"]["sprintz-fire"]
    parent = Path(entry["library"]["path"]).parent
    exe = (parent / "tsbench_sprintz_corpus_query_control").as_posix()
    if not (root / exe).exists():
        return None
    dependency = (parent / "librepaired_codec.so").as_posix()
    require(len(entry["dependencies"]) == 1 and entry["dependencies"][0]["path"] == dependency,
            "Sprintz query control must share the locked Sprintz dependency")
    verify_asset(root, entry["dependencies"][0])
    return {"executable": _ref(root, exe), "dependency": _ref(root, dependency),
            "adapter": _ref(root, "src/tsbench/application/m3_sprintz_query.py"),
            "wire_validator": _ref(root, "src/tsbench/qualification/sprintz.py")}


def _titchy_binding(root: Path, build: dict, mode: str) -> dict | None:
    entry = build["plugins"]["titchy-batch"]
    parent = Path(entry["library"]["path"]).parent
    control = (parent / f"tsbench_titchy_corpus_{mode}_control").as_posix()
    if not (root / control).exists():
        return None
    dependency = (parent / "libtitchy_c.so").as_posix()
    require(len(entry["dependencies"]) == 1 and entry["dependencies"][0]["path"] == dependency,
            f"Titchy {mode} control must share the locked Titchy dependency")
    verify_asset(root, entry["dependencies"][0])
    return {"executable": _ref(root, control), "dependency": _ref(root, dependency),
            "adapter": _ref(root, f"src/tsbench/application/m3_titchy_{mode}.py"),
            "wire_validator": _ref(root, "src/tsbench/qualification/titchy_wire.py"),
            **({"invoker": _ref(root, "src/tsbench/application/m3_titchy_access.py")} if mode == "stream" else {})}


def _pcodec_pages_binding(root: Path, build: dict) -> dict | None:
    parent = Path(build["plugins"]["pcodec-source-auto"]["library"]["path"]).parent
    control = (parent / "tsbench_pcodec_pages_control").as_posix()
    if not (root / control).exists():
        return None
    for plugin in ("pcodec-source-auto", "pcodec-c-native-auto"):
        entry = build["plugins"][plugin]
        dependency = (parent / "libpcodec_c.so").as_posix()
        require(len(entry["dependencies"]) == 1 and entry["dependencies"][0]["path"] == dependency,
                "pcodec pages control must share the locked pcodec dependency")
        verify_asset(root, entry["dependencies"][0])
    return {"executable": _ref(root, control),
            "dependency": _ref(root, dependency),
            "adapter": _ref(root, "src/tsbench/application/m3_pcodec_pages.py")}

ROUTE_PLUGIN = {
    (9, "auto-batch"): "alp-auto",
    (9, "decode-backends"): "alp-auto",
    (11, "source-auto"): "pcodec-source-auto",
    (11, "c-native-auto"): "pcodec-c-native-auto",
    (11, "source-pages"): "pcodec-source-auto",
    (11, "native-pages"): "pcodec-c-native-auto",
    (11, "intmult"): "pcodec-c-native-auto",
    (19, "fire-batch"): "sprintz-fire",
    (19, "query"): "sprintz-fire",
    (85, "batch"): "titchy-batch",
    (85, "packet-stream"): "titchy-batch",
    (85, "loaded-file-access"): "titchy-batch",
    (85, "batch-range"): "titchy-batch",
    (7, "tv-batch"): "gorilla-tv",
    (7, "append-resume"): "gorilla-tv",
    (7, "iterator"): "gorilla-tv",
    (31, "field-baseline"): "zfp-reversible",
    (31, "field-modes"): "zfp-reversible",
    (31, "openmp-encode"): "zfp-reversible",
    (31, "fixed-rate-array"): "zfp-reversible",
    (40, "zstd-baseline"): "zstd",
    (40, "zstd-session"): "zstd",
    (40, "zstd-dictionary"): "zstd",
    (40, "zstd-workers"): "zstd",
    (39, "xz-baseline"): "xz-baseline",
    (39, "xz-session"): "xz-baseline",
    (39, "xz-workers"): "xz-baseline",
    (4, "selfstar-batch"): "selfstar-batch",
    (4, "selfstar-incremental"): "selfstar-batch",
    (29, "huff0-reference"): "huff0-reference",
    (29, "huff0-shared-table"): "huff0-reference",
    (87, "pbepla-progressive"): "pbepla-rr",
    (87, "pbepla-replay"): "pbepla-rr",
    (80, "corad-inference"): "corad-frozen",
    (80, "corad-c-training"): "corad-frozen",
    (80, "corad-source-training"): "corad-frozen",
}


@dataclass(frozen=True, slots=True)
class M3RealCorpusPlanRequest:
    m0_receipt: str
    m1_receipt: str
    m2_receipt: str
    native_definition: str
    build_lock: str
    gorilla_state_repair_lock: str | None = None
    huff0_portable_build: str | None = None
    pbepla_repair_provenance: str | None = None
    measurement_cpu: int | None = None
    corad_repair_provenance: str | None = None
    measurement_fixed_batch_worker: str | None = None
    measurement_column_batch_worker: str | None = None
    corad_specialist_amendment: str | None = None
    measurement_gorilla: bool = False
    measurement_pcodec_pages_tool: str | None = None
    measurement_abi_corpus_worker: str | None = None
    measurement_selfstar_corpus_worker: str | None = None
    measurement_zfp: tuple[str, str, str] | None = None
    measurement_zfp_cpus: tuple[int, int] | None = None
    measurement_titchy_grouped: str | None = None
    measurement_zstd_dictionary_grouped: str | None = None
    measurement_lzbench_tools: tuple[str, str] | None = None
    measurement_lzbench_cpus: tuple[int, int, int] | None = None
    measurement_sprintz_query_grouped: str | None = None
    measurement_huff0_table_grouped: str | None = None
    measurement_corad_clock: str | None = None
    measurement_corad_raw_encode: bool = False


def _ref(root: Path, relative: str) -> dict:
    path = local_file(root, relative)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": digest(path)}


def _receipt(root: Path, relative: str, schema: str, stage: str) -> dict:
    value = load_json(local_file(root, relative))
    require(value.get("schema") == schema and value.get("stage") == stage and
            value.get("stage_accepted") is True and value.get("qualification_granted") is False,
            f"{relative} is not an accepted {stage} predecessor")
    require(value.get("receipt_id") == content_id({k: v for k, v in value.items() if k != "receipt_id"}),
            f"{relative} receipt ID is stale")
    return value


def _build_plugins(build: dict) -> set[str]:
    plugins = build.get("plugins", {})
    require(isinstance(plugins, dict), "M3 build lock has no plugin map")
    return set(plugins)


def _project_definition(definition: dict, *, pcodec_pages: bool, titchy_access: bool,
                        titchy_stream: bool, sprintz_query: bool, gorilla_corpus: bool,
                        sprintz_batch: bool = False, selfstar: bool = False,
                        titchy_batch: bool = False, zfp_corpus: bool = False, pbepla_corpus: bool = False,
                        lzbench_session: bool = False, zstd_dictionary: bool = False,
                        lzbench_workers: bool = False, huff0_table: bool = False,
                        huff0_fec1: bool = False, corad_corpus: bool = False,
                        fixed_batch: bool = False) -> tuple[list, list, list]:
    """The only allowed execution projection from the accepted M0 definition."""
    route_rows = []
    for route in definition["routes"]:
        binding = route["binding"]
        key = (binding["selection"], binding["route"])
        require(key in ROUTE_PLUGIN, f"M3 route has no execution binding: {key}")
        corad = corad_corpus and key in CORAD_ROUTES
        if corad:
            check_corad(binding)
        pages = pcodec_pages and key in PCODEC_PAGE_ROUTES
        if pages:
            require(binding["view"] == "f64_columns" and binding["operation"] == "complete_page_and_drain" and
                    binding["partition"] == "full" and binding["rows_per_unit"] == 65536 and
                    binding["options"] == {"page_values": 4096, "decode_request_values": 257},
                    "pcodec page options differ from control contract")
        pbepla = pbepla_corpus and key in PBEPLA_ROUTES
        if pbepla:
            check_pbepla_route(binding)
        lz_session = lzbench_session and key in LZBENCH_SESSION_ROUTES
        if lz_session:
            check_lzbench_session(binding)
        zstd_dict = zstd_dictionary and key == ZSTD_DICTIONARY_KEY
        if zstd_dict:
            check_zstd_dictionary(binding)
        lz_workers = lzbench_workers and key in LZBENCH_WORKERS_ROUTES
        if lz_workers:
            check_lzbench_workers(binding)
        huff_table = huff0_table and key == HUFF0_TABLE_KEY
        if huff_table:
            check_huff0_table(binding)
        huff_fec1 = huff0_fec1 and key == HUFF0_FEC1_KEY
        if huff_fec1:
            check_huff0_fec1(binding)
        zfp = zfp_corpus and key in ZFP_ROUTES
        if zfp:
            check_zfp_route(binding)
        titchy_abi = titchy_batch and key == TITCHY_BATCH_ROUTE
        if titchy_abi:
            require(binding['view'] == 'u64_bitcast_per_f64_column' and binding['operation'] == 'roundtrip' and
                    binding['partition'] == 'full' and binding['rows_per_unit'] == 65536 and binding['options'] == {},
                    'Titchy public ABI scope differs from native input contract')
        access = titchy_access and key in TITCHY_ACCESS_ROUTES
        stream = titchy_stream and key == TITCHY_STREAM_ROUTE
        query = sprintz_query and key == SPRINTZ_QUERY_ROUTE
        fire = sprintz_batch and key == SPRINTZ_BATCH_ROUTE
        gorilla = gorilla_corpus and key in GORILLA_CORPUS_ROUTES
        if gorilla:
            operation, options = {"tv-batch": ("roundtrip", {}),
                                  "append-resume": ("append_snapshot_resume", {"snapshot_offset": "midpoint"}),
                                  "iterator": ("iterate_forward_seek", {})}[key[1]]
            require(binding["view"] == "tv_per_value_column_ms" and binding["operation"] == operation and
                    binding["partition"] == "full" and binding["rows_per_unit"] == 512 and binding["options"] == options,
                    "Gorilla TV scope differs from the C11 corpus control contract")
        ordered = selfstar and key in SELFSTAR_DRIVERS
        if ordered:
            operation = 'ordered_roundtrip' if key[1] == 'selfstar-batch' else 'push_finish_ordered_restore'
            require(binding['view'] == 'f64_columns' and binding['operation'] == operation and
                    binding['partition'] == 'full' and binding.get('rows_per_unit') is None and
                    binding['options'] == {'native_block_values': 512, 'state': 'same_column'},
                    'SElf* corpus routes require a full ordered object per column')
        if fire:
            require(binding["view"] == "u16_le_limbs_per_f64_column" and binding["operation"] == "roundtrip" and
                    binding["partition"] == "full" and binding["rows_per_unit"] == 8192 and binding["options"] == {"lanes": 4},
                    "Sprintz batch scope differs from the public ABI control contract")
        if query:
            require(binding["view"] == "u16_le_limbs_per_f64_column" and binding["operation"] == "query_unsigned_channels" and
                    binding["partition"] == "full" and binding["rows_per_unit"] == 8192 and
                    binding["options"] == {"lanes": 4, "aggregates": ["count", "sum", "max"],
                                           "semantics": "unsigned_u16_limbs_not_original_f64"},
                    "Sprintz query scope differs from the control contract")
        if access:
            operation, pattern = ("range_with_full_validation", "midpoint_half_open_window") if key[1] == "batch-range" else (
                "point_bit_range", "first_middle_last_and_midpoint_half_open_window")
            require(binding["view"] == "u64_bitcast_per_f64_column" and binding["operation"] == operation and
                    binding["partition"] == "full" and binding["rows_per_unit"] == 65536 and
                    binding["options"] == {"pattern": pattern}, "Titchy access options differ from control contract")
        if stream:
            require(binding["view"] == "u64_bitcast_per_f64_column" and
                    binding["operation"] == "push_backpressure_finish_reset" and binding["partition"] == "full" and
                    binding.get("rows_per_unit") is None and binding["options"] == {},
                    "Titchy stream extent or operation differs from control contract")
        route_rows.append({
            "selection": binding["selection"], "route": binding["route"],
            "route_contract_id": route["original_contract"]["route_contract_id"],
            "plugin": ROUTE_PLUGIN[key], "view": binding["view"],
            "operation": binding["operation"],
            "driver": (PCODEC_PAGE_DRIVER if pages else TITCHY_ACCESS_DRIVER if access else TITCHY_STREAM_DRIVER
                       if stream else SPRINTZ_QUERY_DRIVER if query else SPRINTZ_BATCH_DRIVER if fire else GORILLA_CORPUS_DRIVER
                       if gorilla else SELFSTAR_DRIVERS[key] if ordered else TITCHY_BATCH_DRIVER if titchy_abi
                       else ZFP_DRIVER if zfp else PBEPLA_DRIVER if pbepla else LZBENCH_SESSION_DRIVER if lz_session
                       else ZSTD_DICTIONARY_DRIVER if zstd_dict else LZBENCH_WORKERS_DRIVER if lz_workers
                       else HUFF0_TABLE_DRIVER if huff_table else HUFF0_FEC1_DRIVER if huff_fec1 else CORAD_DRIVER if corad
                       else FIXED_BATCH_DRIVER if fixed_batch and key in FIXED_BATCH_ROUTES
                       else "m3_real_corpus_executor_v1"),
        })
    routes = {(r["selection"], r["route"]): r for r in route_rows}
    work_items = []
    for decision in definition["decisions"]:
        route = routes[(decision["selection"], decision["route"])]
        terminal = decision["state"] != "input_domain_matches"
        work_items.append({
            "work_item_id": decision["decision_id"],
            "dataset_id": decision["dataset_id"],
            "source_cluster": decision["source_cluster"],
            "canonical_object_id": decision["canonical_object_id"],
            "selection": decision["selection"], "route": decision["route"],
            "route_contract_id": decision["route_contract_id"],
            "plugin": route["plugin"], "view": decision["view"],
            "operation": decision["operation"], "operation_config_id": decision["operation_config_id"],
            "input": decision["input"], "applicability": decision["state"],
            "execution_state": "not_applicable" if terminal else "not_run",
            "reasons": decision["reasons"], "qualification_granted": False,
        })
    obligations = []
    for row in definition["obligations"]:
        obligations.append({**row, "execution_state": "not_run", "qualification_granted": False})
    return route_rows, work_items, obligations


def plan_m3_real_corpus(root: Path, request: M3RealCorpusPlanRequest) -> dict:
    root = root.resolve(strict=True)
    m0 = _receipt(root, request.m0_receipt, "bmk.m0-real-corpus-stage-receipt/1", "M0")
    m1 = _receipt(root, request.m1_receipt, "bmk.m1-real-corpus-stage-receipt/1", "M1")
    m2 = _receipt(root, request.m2_receipt, "bmk.m2-real-corpus-stage-receipt/1", "M2")
    definition = load_json(local_file(root, request.native_definition))
    verified = verify_native_corpus_plan(root, definition)
    require(verified["definition_verified"] and
            digest(local_file(root, request.native_definition)) == m0["evidence"]["native_definition"]["sha256"],
            "M3 definition is not the accepted M0 r8 definition")
    build = load_json(local_file(root, request.build_lock))
    worker_path = Path(build["worker"]["path"]).with_name("tsbench_corpus_worker").as_posix()
    corpus_worker = _ref(root, worker_path)
    plugins = _build_plugins(build)
    missing = sorted(set(ROUTE_PLUGIN.values()) - plugins)
    require(not missing, f"M3 build lock is missing selected route plugins: {', '.join(missing)}")
    fixed_batch = bind_fixed_batch(root, build, definition)

    page_control = _pcodec_pages_binding(root, build)
    access_control = _titchy_binding(root, build, "access")
    stream_control = _titchy_binding(root, build, "stream")
    sprintz_control = _sprintz_query_binding(root, build)
    gorilla_control = _gorilla_corpus_binding(root, build)
    zfp_control = bind_zfp_corpus(root, build)
    pbepla_control = bind_pbepla(root, build)
    pbepla_repair = (bind_pbepla_repair(root, request.pbepla_repair_provenance, request.build_lock, build, pbepla_control)
                     if request.pbepla_repair_provenance else None)
    lzbench_control = bind_lzbench_session(root, build)
    zstd_dictionary = bind_zstd_dictionary(root,build)
    lzbench_workers = bind_lzbench_workers(root,build)
    huff0_table = bind_huff0_table(root,build)
    huff0_fec1 = bind_huff0_fec1(root, build)
    corad = bind_corad(root, build)
    selfstar = selfstar_available(root, build)
    route_rows, work_items, obligations = _project_definition(
        definition, fixed_batch=True, pcodec_pages=page_control is not None, titchy_access=access_control is not None,
        titchy_stream=stream_control is not None, sprintz_query=sprintz_control is not None,
        gorilla_corpus=gorilla_control is not None, selfstar=selfstar, zfp_corpus=zfp_control is not None,
        pbepla_corpus=pbepla_control is not None, lzbench_session=lzbench_control is not None,
        zstd_dictionary=zstd_dictionary is not None,lzbench_workers=lzbench_workers is not None,
        huff0_table=huff0_table is not None, huff0_fec1=huff0_fec1 is not None, corad_corpus=corad is not None)
    specialized = {"pcodec_intmult": bind_intmult(root, obligations, page_control)} if page_control else {}
    for family, corpus in ((PCODEC_SPECIALIZED, page_control), (LZBENCH_BASELINE, lzbench_control)):
        batch = bind_batch_specialized(root, build, obligations, family, corpus)
        if batch is not None:
            specialized[family] = batch
    alp = bind_alp_specialized(root, build, obligations)
    if alp is not None:
        specialized['alp'] = alp
    sprintz = bind_sprintz(root, build, obligations, sprintz_control)
    if sprintz is not None:
        specialized["sprintz"] = sprintz
    titchy = bind_titchy(root, build, obligations, access_control, stream_control)
    if titchy is not None:
        specialized["titchy"] = titchy
    zfp = bind_zfp_specialized(root, build, obligations, zfp_control)
    if zfp is not None:
        specialized["zfp"] = zfp
    pbepla = bind_pbepla_specialized(root, build, obligations, pbepla_control)
    if pbepla is not None:
        specialized["pbepla"] = pbepla
    lzbench_specialized = bind_lzbench_specialized(root, build, obligations, lzbench_control)
    if lzbench_specialized is not None:
        specialized['lzbench_session'] = lzbench_specialized
    lzbench_profiles = bind_lzbench_profiles(root,build,obligations,zstd_dictionary,lzbench_workers)
    if lzbench_profiles is not None:
        specialized['lzbench_profiles'] = lzbench_profiles
    huff0_specialized = bind_huff0_specialized(root, build, obligations, huff0_fec1, huff0_table,
                                             request.huff0_portable_build)
    if huff0_specialized is not None:
        specialized['huff0'] = huff0_specialized
    corad_specialized = bind_corad_specialized(root, build, obligations, corad)
    corad_repair = (bind_corad_repair(root, request.corad_repair_provenance, request.build_lock, build, corad, corad_specialized)
                    if request.corad_repair_provenance else None)
    if corad_specialized is not None:
        specialized['corad'] = corad_specialized
    if selfstar:
        specialized['selfstar'] = bind_selfstar(root, build, obligations)
    if sprintz is not None or titchy is not None:
        route_rows, work_items, obligations = _project_definition(
            definition, fixed_batch=True, pcodec_pages=page_control is not None, titchy_access=access_control is not None,
            titchy_stream=stream_control is not None, sprintz_query=sprintz_control is not None,
            gorilla_corpus=gorilla_control is not None, sprintz_batch=sprintz is not None,
            selfstar=selfstar, titchy_batch=titchy is not None, zfp_corpus=zfp_control is not None,
            pbepla_corpus=pbepla_control is not None, lzbench_session=lzbench_control is not None,
            zstd_dictionary=zstd_dictionary is not None,lzbench_workers=lzbench_workers is not None,
            huff0_table=huff0_table is not None, huff0_fec1=huff0_fec1 is not None, corad_corpus=corad is not None)
    repair = None
    if request.gorilla_state_repair_lock is not None:
        require(gorilla_control, "M3 Gorilla state repair needs the original corpus control")
        repair = load_repair(root, build, request.gorilla_state_repair_lock)
        specialized["gorilla"] = bind_gorilla_specialized(root, obligations, build, repair)
    body = {
        "schema": SCHEMA, "target_stage": "M3", "stage_accepted": False,
        "runnable": True, "qualification_granted": False, "timing_admitted": False,
        "predecessors": {
            "m0_real_corpus_receipt": {**_ref(root, request.m0_receipt), "receipt_id": m0["receipt_id"]},
            "m1_real_corpus_receipt": {**_ref(root, request.m1_receipt), "receipt_id": m1["receipt_id"]},
            "m2_real_corpus_receipt": {**_ref(root, request.m2_receipt), "receipt_id": m2["receipt_id"]},
        },
        "definition": {"plan": _ref(root, request.native_definition),
                       "plan_content_id": definition["plan_content_id"],
                       "coverage": definition["coverage"]},
        "build": {"lock": _ref(root, request.build_lock), "build_id": build.get("build_id"),
                  "worker": _ref(root, build["worker"]["path"]), "corpus_worker": corpus_worker,
                  "plugins": sorted(plugins),
                  "fixed_batch": fixed_batch,
                  **({"pcodec_pages": page_control} if page_control else {}),
                  **({"titchy_access": access_control} if access_control else {}),
                  **({"titchy_stream": stream_control} if stream_control else {}),
                  **({"sprintz_query": sprintz_control} if sprintz_control else {}),
                  **({"gorilla_corpus": gorilla_control} if gorilla_control else {}),
                  **({"gorilla_state_repair": repair} if repair else {}),
                  **({"zfp_corpus": zfp_control} if zfp_control else {}),
                  **({"pbepla_corpus": pbepla_control} if pbepla_control else {}),
                  **({"pbepla_repair": pbepla_repair} if pbepla_repair else {}),
                  **({"lzbench_session": lzbench_control} if lzbench_control else {}),
                  **({"zstd_dictionary": zstd_dictionary} if zstd_dictionary else {}),
                  **({"lzbench_workers": lzbench_workers} if lzbench_workers else {}),
                  **({"huff0_table": huff0_table} if huff0_table else {}),
                  **({"huff0_fec1": huff0_fec1} if huff0_fec1 else {}),
                  **({"corad_corpus": corad} if corad else {}),
                  **({"corad_repair": corad_repair} if corad_repair else {})},
        "execution_policy": {
            "submit": "one_frozen_plan_one_run_one_main_ledger",
            "internal_scheduling": "bounded_parallel_or_checkpoint_resume_without_sharded_receipts",
            "verification": "artifact_each_or_operation_specific_validator",
            "outside_domain": "recorded_not_executed",
            "quality_failure": "recorded_not_green",
            "hardware_pending": "recorded_not_green",
            "external_support": "none_in_M3_native_run",
        },
        "routes": route_rows, "work_items": work_items, "obligations": obligations,
        **({"specialized": specialized} if specialized else {}),
        "coverage": {
            "datasets": definition["coverage"]["datasets"], "routes": definition["coverage"]["routes"],
            "file_route_decisions": len(work_items),
            "input_domain_matches": sum(x["applicability"] == "input_domain_matches" for x in work_items),
            "outside_declared_domain": sum(x["applicability"] == "outside_declared_domain" for x in work_items),
            "condition_not_triggered": sum(x["applicability"] == "condition_not_triggered" for x in work_items),
            "required_obligations": sum(x["kind"] == "required" for x in obligations),
            "conditional_obligations": sum(x["kind"] == "conditional" for x in obligations),
            "executable_work_items": sum(x["execution_state"] == "not_run" for x in work_items),
            "executed_work_items": 0, "qualified_work_items": 0,
        },
    }
    require(not request.measurement_gorilla or request.measurement_column_batch_worker is not None,
            'Gorilla timing requires the prior fixed and column batch bindings')
    require(request.measurement_zstd_dictionary_grouped is None or request.measurement_titchy_grouped is not None,
            'Zstd dictionary timing requires the preceding Titchy binding')
    lzbench_args = ()
    if request.measurement_lzbench_tools is not None or request.measurement_lzbench_cpus is not None:
        require(request.measurement_lzbench_tools and request.measurement_lzbench_cpus and request.measurement_zstd_dictionary_grouped,
                'lzbench timing needs two tools, three CPUs and the preceding dictionary binding')
        lzbench_args = (*request.measurement_lzbench_tools,list(request.measurement_lzbench_cpus))
    require(request.measurement_sprintz_query_grouped is None or lzbench_args,
            'Sprintz query timing requires the preceding session and worker binding')
    require(request.measurement_huff0_table_grouped is None or request.measurement_sprintz_query_grouped is not None,
            'ETB1 timing requires the preceding Sprintz query binding')
    require(request.measurement_corad_clock is None or request.measurement_huff0_table_grouped is not None,
            'CORAD timing requires the preceding Huff0 ETB1 binding')
    require(not request.measurement_corad_raw_encode or request.measurement_corad_clock is not None and request.measurement_zfp is not None,
            'CORAD raw encode timing requires the complete v13 measurement bindings')
    if any(x is not None for x in (request.measurement_zfp, request.measurement_zfp_cpus, request.measurement_titchy_grouped)):
        if request.measurement_corad_raw_encode:
            from .m3_in_run_measurement_v14 import freeze
        elif request.measurement_corad_clock is not None:
            from .m3_in_run_measurement_v13 import freeze
        elif request.measurement_huff0_table_grouped is not None:
            from .m3_in_run_measurement_v12 import freeze
        elif request.measurement_sprintz_query_grouped is not None:
            from .m3_in_run_measurement_v11 import freeze
        elif lzbench_args:
            from .m3_in_run_measurement_v10 import freeze
        elif request.measurement_zstd_dictionary_grouped is not None:
            from .m3_in_run_measurement_v9 import freeze
        elif request.measurement_titchy_grouped is None:
            from .m3_in_run_measurement_v7 import freeze
        else:
            from .m3_in_run_measurement_v8 import freeze
        require(request.measurement_gorilla and request.measurement_cpu is not None and all((
            request.measurement_fixed_batch_worker, request.measurement_column_batch_worker,
            request.measurement_pcodec_pages_tool, request.measurement_abi_corpus_worker,
            request.measurement_selfstar_corpus_worker, request.measurement_zfp, request.measurement_zfp_cpus)),
            'ZFP timing requires three tools, two field CPUs and the preceding bindings')
        body['measurement'] = freeze(root, body, request.measurement_cpu, request.measurement_fixed_batch_worker,
                                     request.measurement_column_batch_worker, request.measurement_pcodec_pages_tool,
                                     request.measurement_abi_corpus_worker, request.measurement_selfstar_corpus_worker,
                                     *request.measurement_zfp, list(request.measurement_zfp_cpus),
                                     *(x for x in (request.measurement_titchy_grouped,request.measurement_zstd_dictionary_grouped)
                                       if x is not None), *lzbench_args,
                                     *(x for x in (request.measurement_sprintz_query_grouped,request.measurement_huff0_table_grouped,
                                                   request.measurement_corad_clock)
                                       if x is not None))
    elif request.measurement_abi_corpus_worker is not None or request.measurement_selfstar_corpus_worker is not None:
        from .m3_in_run_measurement_v6 import freeze
        require(request.measurement_gorilla and request.measurement_cpu is not None and all((
            request.measurement_fixed_batch_worker, request.measurement_column_batch_worker,
            request.measurement_pcodec_pages_tool, request.measurement_abi_corpus_worker,
            request.measurement_selfstar_corpus_worker)), 'whole-file timing requires both workers and preceding bindings')
        body['measurement'] = freeze(root, body, request.measurement_cpu, request.measurement_fixed_batch_worker,
                                     request.measurement_column_batch_worker, request.measurement_pcodec_pages_tool,
                                     request.measurement_abi_corpus_worker, request.measurement_selfstar_corpus_worker)
    elif request.measurement_pcodec_pages_tool is not None:
        from .m3_in_run_measurement_v5 import freeze
        require(request.measurement_gorilla and request.measurement_cpu is not None and
                request.measurement_fixed_batch_worker is not None and request.measurement_column_batch_worker is not None,
                'pcodec page timing requires the preceding Gorilla and batch bindings')
        body['measurement'] = freeze(root, body, request.measurement_cpu, request.measurement_fixed_batch_worker,
                                     request.measurement_column_batch_worker, request.measurement_pcodec_pages_tool)
    elif request.measurement_column_batch_worker is not None:
        if request.measurement_gorilla:
            from .m3_in_run_measurement_v4 import freeze
        else:
            from .m3_in_run_measurement_v3 import freeze
        require(request.measurement_cpu is not None and request.measurement_fixed_batch_worker is not None,
                'column batch timing requires --measurement-cpu and --measurement-fixed-batch-worker')
        body['measurement'] = freeze(root, body, request.measurement_cpu, request.measurement_fixed_batch_worker,
                                     request.measurement_column_batch_worker)
    elif request.measurement_fixed_batch_worker is not None:
        from .m3_in_run_measurement_v2 import freeze
        require(request.measurement_cpu is not None, 'fixed batch timing worker requires --measurement-cpu')
        body['measurement'] = freeze(root, body, request.measurement_cpu, request.measurement_fixed_batch_worker)
    elif request.measurement_cpu is not None:
        from .m3_in_run_measurement import freeze
        body['measurement'] = freeze(root, body, request.measurement_cpu)
    if request.corad_specialist_amendment is not None:
        from .m0_corad_guard_amendment import bind
        require(request.measurement_column_batch_worker is not None, 'CORAD amendment requires the current measured executor')
        body['corad_specialist_amendment'] = bind(root, request.corad_specialist_amendment,
            body['predecessors']['m0_real_corpus_receipt'], body['definition']['plan'], corad_specialized, corad_repair)
    return {**body, "plan_content_id": content_id(body)}


def check_m3_real_corpus_plan(root: Path, plan: dict) -> None:
    if "input_switch" in plan:
        from .m3_input_switch import check_input_switch
        return check_input_switch(root, plan)
    require(plan.get("schema") == SCHEMA and plan.get("target_stage") == "M3" and
            plan.get("stage_accepted") is False and plan.get("runnable") is True and
            plan.get("qualification_granted") is False and plan.get("timing_admitted") is False,
            "invalid M3 real-corpus plan header")
    require(plan.get("plan_content_id") == content_id({k: v for k, v in plan.items() if k != "plan_content_id"}),
            "M3 real-corpus plan content ID is stale")
    if 'measurement' in plan:
        from .m3_in_run_measurement import SCHEMA as MEASUREMENT_V1, freeze as freeze_v1
        from .m3_in_run_measurement_v2 import SCHEMA as MEASUREMENT_V2, freeze as freeze_v2
        from .m3_in_run_measurement_v3 import SCHEMA as MEASUREMENT_V3, freeze as freeze_v3
        from .m3_in_run_measurement_v4 import SCHEMA as MEASUREMENT_V4, freeze as freeze_v4
        from .m3_in_run_measurement_v5 import SCHEMA as MEASUREMENT_V5, freeze as freeze_v5
        from .m3_in_run_measurement_v6 import SCHEMA as MEASUREMENT_V6, freeze as freeze_v6
        from .m3_in_run_measurement_v7 import SCHEMA as MEASUREMENT_V7, freeze as freeze_v7
        from .m3_in_run_measurement_v8 import SCHEMA as MEASUREMENT_V8, freeze as freeze_v8
        from .m3_in_run_measurement_v9 import SCHEMA as MEASUREMENT_V9, freeze as freeze_v9
        from .m3_in_run_measurement_v10 import SCHEMA as MEASUREMENT_V10, freeze as freeze_v10
        from .m3_in_run_measurement_v11 import SCHEMA as MEASUREMENT_V11, freeze as freeze_v11
        from .m3_in_run_measurement_v12 import SCHEMA as MEASUREMENT_V12, freeze as freeze_v12
        from .m3_in_run_measurement_v13 import SCHEMA as MEASUREMENT_V13, freeze as freeze_v13
        from .m3_in_run_measurement_v14 import SCHEMA as MEASUREMENT_V14, freeze as freeze_v14
        m = plan['measurement']
        cpu = m['environment']['cpu']
        require(m['schema'] in (MEASUREMENT_V1, MEASUREMENT_V2, MEASUREMENT_V3, MEASUREMENT_V4, MEASUREMENT_V5, MEASUREMENT_V6, MEASUREMENT_V7, MEASUREMENT_V8, MEASUREMENT_V9, MEASUREMENT_V10, MEASUREMENT_V11, MEASUREMENT_V12, MEASUREMENT_V13, MEASUREMENT_V14),
                'unknown M3 measurement version')
        latter = {MEASUREMENT_V7:freeze_v7,MEASUREMENT_V8:freeze_v8,MEASUREMENT_V9:freeze_v9,MEASUREMENT_V10:freeze_v10,MEASUREMENT_V11:freeze_v11,MEASUREMENT_V12:freeze_v12,MEASUREMENT_V13:freeze_v13, MEASUREMENT_V14:freeze_v14}
        if m['schema'] in latter:
            z = m['zfp']
            fn = latter[m['schema']]
            extra = [m[k]['worker']['path'] for k in ('titchy_grouped','zstd_dictionary_grouped') if k in m]
            if m['schema'] in (MEASUREMENT_V10,MEASUREMENT_V11,MEASUREMENT_V12,MEASUREMENT_V13, MEASUREMENT_V14):
                lz = m['lzbench_clock']
                extra.extend((lz['tools']['session']['path'],lz['tools']['workers']['path'],[x['cpu'] for x in lz['worker_environment']]))
            extra.extend(m[k]['worker']['path'] for k in ('sprintz_query_grouped','huff0_table_grouped','corad_clock') if k in m)
            frozen = fn(root, plan, cpu, m['fixed_batch']['worker']['path'], m['column_batch']['worker']['path'],
                               m['pcodec_pages']['tool']['path'], m['whole']['abi']['worker']['path'],
                               m['whole']['selfstar']['worker']['path'], z['field']['tools']['timing']['path'],
                               z['field']['tools']['observer']['path'], next(iter(z['array']['tools'].values()))['path'],
                               [e['cpu'] for e in z['field_environment']],
                               *extra)
        elif m['schema'] == MEASUREMENT_V6:
            frozen = freeze_v6(root, plan, cpu, m['fixed_batch']['worker']['path'], m['column_batch']['worker']['path'],
                               m['pcodec_pages']['tool']['path'], m['whole']['abi']['worker']['path'],
                               m['whole']['selfstar']['worker']['path'])
        elif m['schema'] == MEASUREMENT_V5:
            frozen = freeze_v5(root, plan, cpu, m['fixed_batch']['worker']['path'], m['column_batch']['worker']['path'],
                               m['pcodec_pages']['tool']['path'])
        elif m['schema'] == MEASUREMENT_V4:
            frozen = freeze_v4(root, plan, cpu, m['fixed_batch']['worker']['path'], m['column_batch']['worker']['path'])
        elif m['schema'] == MEASUREMENT_V3:
            frozen = freeze_v3(root, plan, cpu, m['fixed_batch']['worker']['path'], m['column_batch']['worker']['path'])
        elif m['schema'] == MEASUREMENT_V2:
            frozen = freeze_v2(root, plan, cpu, m['fixed_batch']['worker']['path'])
        else:
            frozen = freeze_v1(root, plan, cpu)
        require(m == frozen, 'M3 in-run measurement contract differs')
    accepted_definition = None
    for name, schema, stage in (("m0_real_corpus_receipt", "bmk.m0-real-corpus-stage-receipt/1", "M0"),
                                ("m1_real_corpus_receipt", "bmk.m1-real-corpus-stage-receipt/1", "M1"),
                                ("m2_real_corpus_receipt", "bmk.m2-real-corpus-stage-receipt/1", "M2")):
        ref = plan["predecessors"][name]
        predecessor = _receipt(root, ref["path"], schema, stage)
        require(ref["sha256"] == digest(local_file(root, ref["path"])) and
                ref["receipt_id"] == predecessor["receipt_id"], f"stale M3 predecessor binding: {name}")
        if stage == "M0":
            accepted_definition = predecessor["evidence"]["native_definition"]["sha256"]
    build_ref = plan["build"]["lock"]
    require(build_ref["sha256"] == digest(local_file(root, build_ref["path"])), "M3 build lock binding is stale")
    for key in ("worker", "corpus_worker"):
        ref = plan["build"][key]
        require(ref["sha256"] == digest(local_file(root, ref["path"])), f"M3 {key} binding is stale")
    if "pcodec_pages" in plan["build"]:
        current = _pcodec_pages_binding(root, load_json(local_file(root, build_ref["path"])))
        require(current is not None and current == plan["build"]["pcodec_pages"],
                "M3 pcodec pages control binding is stale")
        require({(r["selection"], r["route"]) for r in plan["routes"] if r["driver"] == PCODEC_PAGE_DRIVER}
                == PCODEC_PAGE_ROUTES, "M3 pcodec pages control has the wrong route scope")
    if "titchy_access" in plan["build"]:
        current = _titchy_binding(root, load_json(local_file(root, build_ref["path"])), "access")
        require(current is not None and current == plan["build"]["titchy_access"], "M3 Titchy access control binding is stale")
        require({(r["selection"], r["route"]) for r in plan["routes"] if r["driver"] == TITCHY_ACCESS_DRIVER}
                == TITCHY_ACCESS_ROUTES, "M3 Titchy access control has the wrong route scope")
    if "titchy_stream" in plan["build"]:
        current = _titchy_binding(root, load_json(local_file(root, build_ref["path"])), "stream")
        require(current is not None and current == plan["build"]["titchy_stream"], "M3 Titchy stream control binding is stale")
    if "sprintz_query" in plan["build"]:
        current = _sprintz_query_binding(root, load_json(local_file(root, build_ref["path"])))
        require(current is not None and current == plan["build"]["sprintz_query"], "M3 Sprintz query control binding is stale")
    if "gorilla_corpus" in plan["build"]:
        current = _gorilla_corpus_binding(root, load_json(local_file(root, build_ref["path"])))
        require(current is not None and current == plan["build"]["gorilla_corpus"], "M3 Gorilla TV control binding is stale")
    if "pbepla_corpus" in plan["build"]:
        current = bind_pbepla(root, load_json(local_file(root, build_ref["path"])))
        require(current is not None and current == plan["build"]["pbepla_corpus"], "M3 PBEPLA corpus binding is stale")
    if "pbepla_repair" in plan["build"]:
        selected = plan["build"]["pbepla_repair"]
        build = load_json(local_file(root, build_ref['path']))
        require(selected == bind_pbepla_repair(root, selected['provenance']['path'], build_ref['path'], build,
                                               plan['build'].get('pbepla_corpus')), 'M3 PBEPLA repair binding is stale')
    if "zfp_corpus" in plan["build"]:
        current = bind_zfp_corpus(root, load_json(local_file(root, build_ref["path"])))
        require(current is not None and current == plan["build"]["zfp_corpus"], "M3 ZFP corpus control binding is stale")
    if 'lzbench_session' in plan['build']:
        current = bind_lzbench_session(root, load_json(local_file(root,build_ref['path'])))
        require(current is not None and current==plan['build']['lzbench_session'], 'M3 lzbench corpus session binding is stale')
    if 'zstd_dictionary' in plan['build']:
        current = bind_zstd_dictionary(root,load_json(local_file(root,build_ref['path'])))
        require(current is not None and current==plan['build']['zstd_dictionary'],'M3 Zstd corpus dictionary binding is stale')
    if 'lzbench_workers' in plan['build']:
        current = bind_lzbench_workers(root,load_json(local_file(root,build_ref['path'])))
        require(current is not None and current==plan['build']['lzbench_workers'],'M3 lzbench corpus worker binding is stale')
    if 'huff0_table' in plan['build']:
        current=bind_huff0_table(root,load_json(local_file(root,build_ref['path'])))
        require(current is not None and current==plan['build']['huff0_table'],'M3 Huff0 table binding is stale')
    if 'huff0_fec1' in plan['build']:
        current = bind_huff0_fec1(root, load_json(local_file(root, build_ref['path'])))
        require(current is not None and current == plan['build']['huff0_fec1'], 'M3 Huff0 FEC1 binding is stale')
    if 'corad_corpus' in plan['build']:
        current = bind_corad(root, load_json(local_file(root, build_ref['path'])))
        require(current is not None and current == plan['build']['corad_corpus'], 'M3 CORAD execution binding is stale')
    ref = plan["definition"]["plan"]
    require(ref == _ref(root, ref["path"]) and ref["sha256"] == accepted_definition,
            "M3 definition is not the accepted M0 definition")
    definition = load_json(local_file(root, ref["path"]))
    fixed_batch = "fixed_batch" in plan["build"]
    if fixed_batch:
        build = load_json(local_file(root, build_ref['path']))
        require(plan['build']['fixed_batch'] == bind_fixed_batch(root, build, definition),
                'M3 fixed batch runtime or execution code binding is stale')
    specialized = plan.get("specialized", {})
    routes, work_items, obligations = _project_definition(
        definition, fixed_batch=fixed_batch, pcodec_pages="pcodec_pages" in plan["build"], titchy_access="titchy_access" in plan["build"],
        titchy_stream="titchy_stream" in plan["build"], sprintz_query="sprintz_query" in plan["build"],
        gorilla_corpus="gorilla_corpus" in plan["build"], sprintz_batch="sprintz" in specialized,
        selfstar="selfstar" in specialized, titchy_batch="titchy" in specialized, zfp_corpus="zfp_corpus" in plan["build"],
        pbepla_corpus="pbepla_corpus" in plan["build"], lzbench_session='lzbench_session' in plan['build'],
        zstd_dictionary='zstd_dictionary' in plan['build'],lzbench_workers='lzbench_workers' in plan['build'],
        huff0_table='huff0_table' in plan['build'], huff0_fec1='huff0_fec1' in plan['build'],
        corad_corpus='corad_corpus' in plan['build'])
    require((routes, work_items, obligations) == (plan["routes"], plan["work_items"], plan["obligations"]),
            "M3 route, corpus decision, or obligation differs from accepted M0 definition")
    repair = plan["build"].get("gorilla_state_repair")
    require(set(specialized) <= {"pcodec_intmult", "gorilla", "sprintz", "selfstar", "titchy", "zfp", "pbepla", 'lzbench_session', 'lzbench_profiles', 'huff0', 'corad', 'alp', PCODEC_SPECIALIZED, LZBENCH_BASELINE} and
            ("gorilla_state_repair" in plan["build"]) == ("gorilla" in specialized) == (repair is not None),
            "M3 specialized driver and repair lock scope differ")
    for family, corpus_key in ((PCODEC_SPECIALIZED, 'pcodec_pages'), (LZBENCH_BASELINE, 'lzbench_session')):
        if family in specialized:
            build = load_json(local_file(root, build_ref['path']))
            require(specialized[family] == bind_batch_specialized(root, build, obligations, family, plan['build'].get(corpus_key)),
                    f'M3 {family} specialist binding differs from frozen obligations')
    if 'alp' in specialized:
        build = load_json(local_file(root, build_ref['path']))
        require(specialized['alp'] == bind_alp_specialized(root, build, obligations),
                'M3 ALP specialist binding differs from frozen obligations')
    if "pcodec_intmult" in specialized:
        require("pcodec_pages" in plan["build"] and
                specialized["pcodec_intmult"] == bind_intmult(root, obligations, plan["build"]["pcodec_pages"]),
                "M3 specialized IntMult execution binding differs from frozen obligations")
    if "sprintz" in specialized:
        build = load_json(local_file(root, build_ref["path"]))
        require("sprintz_query" in plan["build"] and specialized["sprintz"] is not None and
                specialized["sprintz"] == bind_sprintz(root, build, obligations, plan["build"]["sprintz_query"]),
                "M3 Sprintz execution binding differs from frozen obligations")
    if "selfstar" in specialized:
        build = load_json(local_file(root, build_ref["path"]))
        require(specialized["selfstar"] == bind_selfstar(root, build, obligations),
                "M3 SElf* execution binding differs from frozen obligations")
    if 'titchy' in specialized:
        build = load_json(local_file(root, build_ref['path']))
        require(specialized['titchy'] is not None and specialized['titchy'] == bind_titchy(
            root, build, obligations, plan['build'].get('titchy_access'), plan['build'].get('titchy_stream')),
            'M3 Titchy execution binding differs from frozen obligations')
    if "zfp" in specialized:
        build = load_json(local_file(root, build_ref["path"]))
        require(specialized["zfp"] is not None and specialized["zfp"] == bind_zfp_specialized(
            root, build, obligations, plan["build"].get("zfp_corpus")),
            "M3 ZFP specialist binding differs from frozen obligations")
    if "pbepla" in specialized:
        build = load_json(local_file(root, build_ref["path"]))
        require(specialized["pbepla"] == bind_pbepla_specialized(
            root, build, obligations, plan["build"].get("pbepla_corpus")),
            "M3 PBEPLA specialist binding differs from frozen obligations")
    if 'lzbench_session' in specialized:
        build = load_json(local_file(root,build_ref['path']))
        require(specialized['lzbench_session']==bind_lzbench_specialized(root,build,obligations,plan['build'].get('lzbench_session')),
                'M3 lzbench session specialist binding differs from frozen obligations')
    if 'lzbench_profiles' in specialized:
        build = load_json(local_file(root,build_ref['path']))
        require(specialized['lzbench_profiles']==bind_lzbench_profiles(root,build,obligations,plan['build'].get('zstd_dictionary'),
                plan['build'].get('lzbench_workers')),'M3 lzbench profiles specialist binding differs from frozen obligations')
    if 'huff0' in specialized:
        build = load_json(local_file(root, build_ref['path']))
        huff0 = specialized['huff0']
        portable = huff0.get(HUFF0_PORTABLE_KEY, {}).get('build_dir')
        require(huff0 == bind_huff0_specialized(root, build, obligations, plan['build'].get('huff0_fec1'),
                                               plan['build'].get('huff0_table'), portable),
                'M3 Huff0 specialist binding differs from frozen obligations')
    if 'corad_specialist_amendment' in plan:
        from .m0_corad_guard_amendment import bind
        from .m3_in_run_measurement_v3 import SCHEMA as CLOCK_V3
        from .m3_in_run_measurement_v4 import SCHEMA as CLOCK_V4
        from .m3_in_run_measurement_v5 import SCHEMA as CLOCK_V5
        from .m3_in_run_measurement_v6 import SCHEMA as CLOCK_V6
        from .m3_in_run_measurement_v7 import SCHEMA as CLOCK_V7
        from .m3_in_run_measurement_v8 import SCHEMA as CLOCK_V8
        from .m3_in_run_measurement_v9 import SCHEMA as CLOCK_V9
        from .m3_in_run_measurement_v10 import SCHEMA as CLOCK_V10
        from .m3_in_run_measurement_v11 import SCHEMA as CLOCK_V11
        from .m3_in_run_measurement_v12 import SCHEMA as CLOCK_V12
        from .m3_in_run_measurement_v13 import SCHEMA as CLOCK_V13
        from .m3_in_run_measurement_v14 import SCHEMA as CLOCK_V14
        amendment = plan['corad_specialist_amendment']
        require(plan.get('measurement', {}).get('schema') in (CLOCK_V3, CLOCK_V4, CLOCK_V5, CLOCK_V6, CLOCK_V7, CLOCK_V8, CLOCK_V9, CLOCK_V10, CLOCK_V11, CLOCK_V12, CLOCK_V13, CLOCK_V14) and amendment == bind(root,
            amendment['receipt']['path'], plan['predecessors']['m0_real_corpus_receipt'], plan['definition']['plan'],
            specialized.get('corad'), plan['build'].get('corad_repair')), 'M3 CORAD amendment binding differs')
    if 'corad' in specialized:
        build = load_json(local_file(root, build_ref['path']))
        require(specialized['corad'] == bind_corad_specialized(root, build, obligations, plan['build'].get('corad_corpus')),
                'M3 CORAD specialist binding differs from frozen obligations')
    if 'corad_repair' in plan['build']:
        guard = plan['build']['corad_repair']
        build = load_json(local_file(root,build_ref['path']))
        require(guard==bind_corad_repair(root,guard['provenance']['path'],build_ref['path'],build,
                                       plan['build'].get('corad_corpus'),specialized.get('corad')),
                'M3 CORAD repair binding differs')
    if repair is not None:
        build = load_json(local_file(root, build_ref["path"]))
        require("gorilla_corpus" in plan["build"] and repair == load_repair(root, build, repair["lock"]["path"]) and
                specialized["gorilla"] == bind_gorilla_specialized(root, obligations, build, repair),
                "M3 Gorilla repair identity or specialized execution binding differs from plan")
    verified = verify_native_corpus_plan(root, definition)
    require(definition["plan_content_id"] == plan["definition"]["plan_content_id"] and
            definition["coverage"] == plan["definition"]["coverage"] and
            verified["coverage"]["file_route_decisions"] == plan["coverage"]["file_route_decisions"],
            "M3 plan denominator differs from accepted native corpus definition")
    require(plan["coverage"]["input_domain_matches"] == 724 and
            plan["coverage"]["outside_declared_domain"] == 74 and
            plan["coverage"]["condition_not_triggered"] == 30 and
            plan["coverage"]["required_obligations"] == 180 and
            plan["coverage"]["conditional_obligations"] == 6,
            "M3 applicability denominator differs from r8")
    require((plan["coverage"]["datasets"], plan["coverage"]["routes"], plan["coverage"]["executable_work_items"],
             plan["coverage"]["executed_work_items"], plan["coverage"]["qualified_work_items"]) == (23, 36, 724, 0, 0),
            "M3 plan has inconsistent coverage or claims execution before launch")
