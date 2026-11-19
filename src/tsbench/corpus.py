"""Frozen real-corpus intake and canonical audit, independent of the benchmark worker."""
from bisect import bisect_right
from datetime import datetime
import gzip
import hashlib
import math
from pathlib import Path
import re
import struct
from typing import Callable
import zlib

from .assets import ContractError, content_id, load_json, local_file, require, verify_asset
from .contracts import Contract, load_contract

MANIFEST_V1 = "datasets/manifests/first-batch-real-v1.json"
MANIFEST = "datasets/manifests/first-batch-real-v2.json"
MANIFEST_V3 = "datasets/manifests/first-batch-real-v3.json"
INTAKE_V1 = "datasets/manifests/first-batch-real-intake.json"
INTAKE_V2 = "datasets/manifests/first-batch-real-intake-v2.json"
INTAKE_V3 = "datasets/manifests/first-batch-real-intake-v3.json"
FEATURE_POLICY = "catalog/capabilities/corpus_features_v3.json"
BOUNDARY_PREFIX = "datasets/fixtures/corpus-boundaries-v1"
BOUNDARY_GENERATOR = "datasets/generators/generate_corpus_boundaries.py"
RELEASES = {1: (MANIFEST_V1, INTAKE_V1), 2: (MANIFEST, INTAKE_V2), 3: (MANIFEST_V3, INTAKE_V3)}
PARTITIONS = ("train", "development", "test")
DOMAINS = ("sensor", "energy", "traffic", "finance", "server_metrics", "scientific_computing")
TIME = {"unit": "second", "storage_dtype": "<i8", "epoch": "1970-01-01 00:00:00",
        "interpretation": "source_civil_label_coordinate_not_utc", "timezone": None}
EPOCH = datetime(1970, 1, 1)
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}")
NUMERIC = {sep: re.compile(rf"-?[0-9]+(?:{re.escape(sep)}[0-9]+)?") for sep in (".", ",")}
MPI_SENTINEL_BITS = struct.pack("<d", -9999)
UCI_CHANNELS = tuple(range(1, 371, 23))[:16]
UCI_COLUMNS = tuple((f"MT_{i:03}", "kW") for i in UCI_CHANNELS)
MPI_COLUMNS = (
    ("pressure", "mbar"), ("air_temperature", "degC"), ("potential_temperature", "K"), ("dewpoint", "degC"),
    ("relative_humidity", "%"), ("saturation_vapour_pressure", "mbar"), ("actual_vapour_pressure", "mbar"),
    ("vapour_pressure_deficit", "mbar"), ("specific_humidity", "g/kg"), ("water_vapour", "mmol/mol"),
    ("air_density", "g/m^3"), ("wind_speed", "m/s"), ("max_wind_speed", "m/s"), ("wind_direction", "deg"),
    ("rain", "mm"), ("raining_duration", "s"), ("short_wave_downward_radiation", "W/m^2"),
    ("photosynthetically_active_radiation", "umol/m^2/s"), ("max_photosynthetically_active_radiation", "umol/m^2/s"),
    ("logger_temperature", "degC"), ("co2", "ppm"),
)
# Select fixed original header labels, without inspecting compressibility. Units
# are intentionally unspecified: the CSV headers carry no sensor/pair units.
TRAFFIC_LABELS = (*map(str, range(0, 811, 27)), "OT")
EXCHANGE_LABELS = (*map(str, range(7)), "OT")
TRAFFIC_COLUMNS = tuple((f"channel_{c}", "source-unspecified") for c in TRAFFIC_LABELS)
EXCHANGE_COLUMNS = tuple((f"rate_{c}", "source-unspecified") for c in EXCHANGE_LABELS)
WESTERMO_PROFILE = "westermo_system1_elapsed_v1"
CMIP6_PROFILE = "ceda_cmip6_gsat_year_v1"
WESTERMO_COLUMNS = (("load-1m", "load_average"), ("load-5m", "load_average"), ("load-15m", "load_average"),
                    ("sys-mem-available", "byte"), ("sys-mem-total", "byte"),
                    ("cpu-iowait", "seconds_per_second"), ("cpu-system", "seconds_per_second"),
                    ("cpu-user", "seconds_per_second"), ("server-up", "source-unspecified"))
CMIP6_MODELS = ("ACCESS-CM2", "ACCESS-ESM1-5", "AWI-CM-1-1-MR", "BCC-CSM2-MR", "CAMS-CSM1-0",
                "CanESM5-CanOE", "CanESM5", "CESM2")
CMIP6_COLUMNS = tuple((name, "degree_Celsius_anomaly") for name in CMIP6_MODELS)
TIME_AXES = {
    WESTERMO_PROFILE: {"unit": "second", "storage_dtype": "<i8", "epoch": "start_of_source_collection",
                       "interpretation": "elapsed_seconds_since_collection_start", "timezone": None},
    CMIP6_PROFILE: {"unit": "year", "storage_dtype": "<i8", "epoch": None,
                   "interpretation": "source_annual_label_not_instant", "timezone": None},
}
# Header, separator, decimal point, max rows; limits protect an explicit audit
# against inconsistent/malformed local assets. Horizons remain in the lock.
PROFILES = {
    "project_uci_16_v1": (UCI_COLUMNS, ";", ",", 150_000),
    "project_mpi_21_v1": (MPI_COLUMNS, ",", ".", 60_000),
    "project_unique_traffic_32_v1": (TRAFFIC_COLUMNS, ",", ".", 20_000),
    "project_unique_exchange_8_v1": (EXCHANGE_COLUMNS, ",", ".", 10_000),
    WESTERMO_PROFILE: (WESTERMO_COLUMNS, ",", ".", 4_320),
    CMIP6_PROFILE: (CMIP6_COLUMNS, ",", ".", 171),
}


def load_feature_policy(root: Path, path: str = FEATURE_POLICY) -> tuple[dict, Contract]:
    contract = load_contract(root, "corpus-feature-policy")
    doc = load_json(local_file(root, path))
    contract.validate(doc, path)
    manifest = load_json(local_file(root, doc["corpus_manifest"]))
    require(isinstance(manifest, dict) and isinstance(manifest.get("datasets"), list) and
            all(isinstance(d, dict) and isinstance(d.get("id"), str) for d in manifest["datasets"]) and
            set(doc.get("seasonal_lag_ticks", doc.get("seasonal_lag_seconds", {}))) ==
            {d["id"] for d in manifest["datasets"]},
            "seasonal lag map must cover exactly the frozen datasets")
    return doc, contract


def load_boundary_fixtures(root: Path, path: str) -> tuple[dict, Contract, dict[str, Path]]:
    contract = load_contract(root, "corpus-boundary-fixtures")
    doc = load_json(local_file(root, path))
    contract.validate(doc, path)
    keys = set(doc["integer_extrema"]) | set(doc["spatial_fields"]) | {doc["float_special"], doc["noise"]["file"]}
    for series in doc["different_axes"]:
        keys.update(series[name] for name in ("axis", "values", "validity") if name in series)
    require(keys == set(doc["files"]), "boundary fixture manifest has missing or unbound files")
    files = {}
    for key, asset in doc["files"].items():
        require(asset["path"] == f"{BOUNDARY_PREFIX}/{key}.npy", f"unexpected boundary fixture path: {key}")
        p = local_file(root, asset["path"])
        require(p.stat().st_size == asset["bytes"], f"boundary fixture size mismatch: {key}")
        files[key] = verify_asset(root, asset)
    return doc, contract, files


def civil_seconds(text: str) -> int:
    require(type(text) is str and STAMP.fullmatch(text) is not None, f"invalid civil timestamp: {text!r}")
    try:
        delta = datetime.fromisoformat(text) - EPOCH
        return delta.days * 86_400 + delta.seconds
    except ValueError as exc:
        raise ContractError(f"invalid civil timestamp: {text!r}") from exc


def time_coordinate(profile: str, text: str) -> int:
    if profile == WESTERMO_PROFILE:
        require(type(text) is str and re.fullmatch(r"0|[1-9][0-9]{0,8}", text) is not None,
                f"invalid elapsed second label: {text!r}")
        return int(text)
    if profile == CMIP6_PROFILE:
        require(type(text) is str and re.fullmatch(r"[1-9][0-9]{3}", text) is not None,
                f"invalid annual label: {text!r}")
        return int(text)
    return civil_seconds(text)


def nominal_step(dataset: dict) -> int:
    return dataset["nominal_step_ticks" if dataset["header_profile"] in TIME_AXES else "nominal_step_seconds"]


def f64(token: str, decimal_point: str) -> bytes:
    require(NUMERIC[decimal_point].fullmatch(token) is not None, f"invalid numeric literal: {token!r}")
    value = float(token.replace(decimal_point, "."))
    require(math.isfinite(value), f"non-finite numeric literal: {token!r}")
    return struct.pack("<d", value)


def _row(raw: bytes, separator: str) -> list[str]:
    require(0 < len(raw) <= 4096 and raw.endswith(b"\n") and b"\r" not in raw, "invalid normalized corpus line")
    try:
        return raw[:-1].decode("ascii").split(separator)
    except UnicodeError as exc:
        raise ContractError("non-ASCII normalized corpus line") from exc


RowObserver = Callable[[dict, str, int, bytes], None]


def audit_asset(path: Path, dataset: dict, *, observe: RowObserver | None = None) -> dict:
    """Parse all rows; hash T and each V column per split, preserving input order."""
    profile = dataset["header_profile"]
    columns, separator, decimal_point, limit = PROFILES[profile]
    step = nominal_step(dataset)
    names = [c[0] for c in columns]
    thresholds = [time_coordinate(profile, stamp) for stamp in dataset["split_at"]]
    require(len(thresholds) == 2 and thresholds[0] < thresholds[1], "invalid corpus split boundaries")
    buffers = [[hashlib.sha256() for _ in range(1 + len(columns))] for _ in PARTITIONS]
    counts = [0] * len(PARTITIONS)
    intervals = [{"first_timestamp": None, "last_timestamp": None} for _ in PARTITIONS]
    steps = {"nominal": 0, "duplicates": 0, "positive_non_nominal": 0, "backward": 0}
    sentinel_cells, total, previous = 0, 0, None
    try:
        with gzip.open(path, "rb") as stream:
            require(_row(stream.readline(4097), separator) == ["timestamp", *names], "corpus header mismatch")
            while raw := stream.readline(4097):
                total += 1
                require(total <= limit, "corpus row limit exceeded")
                stamp, *values = _row(raw, separator)
                require(len(values) == len(columns), f"corpus row width mismatch at data row {total}")
                instant = time_coordinate(profile, stamp)
                if previous is not None:
                    diff = instant - previous
                    key = ("nominal" if diff == step else
                           "duplicates" if diff == 0 else "positive_non_nominal" if diff > 0 else "backward")
                    steps[key] += 1
                previous = instant
                split = bisect_right(thresholds, instant)
                require(split == 0 or intervals[split - 1]["first_timestamp"] is not None,
                        "input crossed an empty chronological partition")
                require(not any(counts[split + 1:]), "corpus split membership goes backward")
                counts[split] += 1
                if intervals[split]["first_timestamp"] is None:
                    intervals[split]["first_timestamp"] = stamp
                intervals[split]["last_timestamp"] = stamp
                buffers[split][0].update(struct.pack("<q", instant))
                row = [] if observe is not None else None
                for j, token in enumerate(values, 1):
                    encoded = f64(token, decimal_point)
                    buffers[split][j].update(encoded)
                    if row is not None:
                        row.append(encoded)
                    if dataset["header_profile"] == "project_mpi_21_v1" and encoded == MPI_SENTINEL_BITS:
                        sentinel_cells += 1  # exactly -9999 as a value, not an inferred validity bit
                if observe is not None and row is not None:
                    observe(dataset, PARTITIONS[split], instant, b"".join(row))
    except (EOFError, gzip.BadGzipFile, zlib.error) as exc:
        raise ContractError(f"invalid corpus gzip: {path.name}: {exc}") from exc
    require(all(counts), "empty corpus split")
    canonical = {"timestamp": TIME_AXES.get(profile, TIME), "values": [{"name": name, "unit": unit, "storage_dtype": "<f8"}
                                                for name, unit in columns], "layout": "contiguous_columns"}
    splits = {}
    for i, split in enumerate(PARTITIONS):
        identity = {"schema": canonical, "rows": counts[i], "columns_sha256": [h.hexdigest() for h in buffers[i]]}
        splits[split] = {**intervals[i], "rows": counts[i], "logical_bytes": counts[i] * (1 + len(columns)) * 8,
                         "canonical_id": content_id(identity)}
    return {"rows": total, "value_columns": len(columns), "timestamp_steps": steps, "literal_minus_9999": sentinel_cells,
            "partitions": splits}


def intake_assets(root: Path, ref: dict) -> tuple[list[dict], tuple[str, ...]]:
    """Resolve the immutable legacy intake and optionally one local-only extension."""
    doc = load_json(verify_asset(root, ref))
    require(isinstance(doc, dict), "corpus intake must be a JSON object")
    paths = [ref["path"]]
    if ref["path"] == INTAKE_V3:
        load_contract(root, "corpus-domain-intake").validate(doc, INTAKE_V3)
        require(doc.get("base_intake", {}).get("path") == INTAKE_V2 and doc.get("base_manifest", {}).get("path") == MANIFEST,
                "v3 intake must extend v2")
        inherited, deps = intake_assets(root, doc["base_intake"])
        verify_asset(root, doc["base_manifest"])
        for spec in doc["datasets"]:
            for asset in (spec["source_asset"], spec["license_evidence"], spec["attribution"]):
                file = verify_asset(root, asset)
                require(file.stat().st_size == asset["bytes"], f"source evidence size mismatch: {spec['id']}")
                paths.append(asset["path"])
        return [*inherited, *doc["datasets"]], (*deps, *paths, MANIFEST)
    if ref["path"] == INTAKE_V2:
        require(doc.keys() == {"schema", "base_intake", "datasets"} and
                doc["schema"] == "bmk.first-batch-real-intake/2" and
                isinstance(doc["base_intake"], dict) and doc["base_intake"].keys() == {"path", "sha256"} and
                doc["base_intake"]["path"] == INTAKE_V1,
                "unexpected corpus extension or base intake")
        base = doc["base_intake"]
        additional = doc["datasets"]
        require(type(additional) is list and len(additional) == 2 and
                all(isinstance(d, dict) and d.get("provenance_policy") == "user_verified_local_copy"
                    and d.keys().isdisjoint({"upstream", "spdx", "rights_page", "original_copy"}) for d in additional),
                "invalid corpus extension datasets")
        paths.append(INTAKE_V1)
        doc = load_json(verify_asset(root, base))
    else:
        require(ref["path"] == INTAKE_V1, "unknown corpus intake path")
        additional = []
    require(isinstance(doc, dict) and doc.get("schema") == "bmk.first-batch-real-intake/1" and
            isinstance(doc.get("datasets"), list) and len(doc["datasets"]) == 2,
            "unexpected base corpus intake schema or denominator")
    verify_asset(root, doc["license"])
    paths.append(doc["license"]["path"])
    return [*doc["datasets"], *additional], tuple(paths)


def check_corpus(root: Path, manifest: str = MANIFEST_V3, *, parse: bool = False,
                 contract: Contract | None = None, observe: RowObserver | None = None) -> dict:
    require(observe is None or parse, "row observer requires canonical parsing")
    contract = contract or load_contract(root, "corpus")
    doc = load_json(local_file(root, manifest))
    contract.validate(doc, manifest)
    intake, _ = intake_assets(root, doc["intake"])
    if doc["intake"]["path"] == INTAKE_V3:
        base_manifest = load_json(local_file(root, MANIFEST))
        require(doc["datasets"][:len(base_manifest["datasets"])] == base_manifest["datasets"],
                "v3 corpus changed a frozen v2 dataset")
    recipes = {x["id"]: x for x in intake}
    require(len(recipes) == len(intake) == len(doc["datasets"]), "corpus intake/dataset denominator mismatch")
    profiles = set()
    seen = set()
    for dataset in doc["datasets"]:
        key = dataset["id"]
        require(key not in seen and key in recipes, f"unmatched or duplicate corpus dataset: {key}")
        seen.add(key)
        spec = recipes[key]
        profile = dataset["header_profile"]
        require(all(dataset[k] == spec[k] for k in ("id", "source_cluster", "domain", "split_at", "header_profile"))
                and nominal_step(dataset) == nominal_step(spec)
                and dataset["asset"]["path"] == spec["asset_path"], f"corpus dataset differs from intake: {key}")
        if relative := spec.get("original_copy"):
            original, = spec["unique_members"]
            file = verify_asset(root, {**original, "path": relative})
            require(file.stat().st_size == original["bytes"], f"corpus original copy byte count mismatch: {key}")
        profiles.add(dataset["source_cluster"])
        path = verify_asset(root, dataset["asset"])
        require(path.stat().st_size == dataset["asset"]["bytes"], f"corpus byte count mismatch: {key}")
        audit = dataset["audit"]
        cols, sep, dec, max_rows = PROFILES[dataset["header_profile"]]
        require((sep, dec) == (spec["delimiter"], spec["decimal_point"]), f"corpus delimiter contract drift: {key}")
        parts = audit["partitions"]
        bounds = [None, *(time_coordinate(profile, t) for t in dataset["split_at"]), None]
        require(audit["value_columns"] == len(cols) and audit["rows"] <= max_rows and
                ("rows" not in spec or audit["rows"] == spec["rows"]) and
                sum(x["rows"] for x in parts.values()) == audit["rows"] == sum(audit["timestamp_steps"].values()) + 1,
                f"inconsistent rows, columns or timestamps: {key}")
        for j, split in enumerate(PARTITIONS):
            part = parts[split]
            first, last = (time_coordinate(profile, part[k]) for k in ("first_timestamp", "last_timestamp"))
            require((bounds[j] is None or first >= bounds[j]) and (bounds[j + 1] is None or last < bounds[j + 1]) and
                    first <= last and part["logical_bytes"] == part["rows"] * (1 + len(cols)) * 8,
                    f"inconsistent chronological bounds or logical bytes: {key}/{split}")
        if parse:
            require(audit_asset(path, dataset, observe=observe) == audit, f"canonical corpus audit mismatch: {key}")
    domains = {x["domain"] for x in doc["datasets"]}
    require(doc["state"] != "domain_coverage_only" or domains == set(DOMAINS) and len(profiles) == len(DOMAINS),
            "domain coverage requires six independent source clusters")
    return {"corpus_id": content_id(doc), "state": doc["state"], "datasets": len(seen), "source_clusters": len(profiles),
            "partitions": len(PARTITIONS) * len(seen), "included_domains": [d for d in DOMAINS if d in domains],
            "missing_domains": [d for d in DOMAINS if d not in domains],
            "stored_bytes": sum(d["asset"]["bytes"] for d in doc["datasets"]),
            "logical_bytes": sum(p["logical_bytes"] for d in doc["datasets"] for p in d["audit"]["partitions"].values()),
            "rows": sum(d["audit"]["rows"] for d in doc["datasets"]), "canonical_audit_performed": parse}
