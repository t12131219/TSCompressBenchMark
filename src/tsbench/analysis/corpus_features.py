"""Descriptive, partition-local measurements; never a codec qualification."""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
import struct

import numpy as np

from ..assets import ContractError, content_id, digest, load_json, local_file, require, verify_asset
from ..corpus import (BOUNDARY_GENERATOR, DOMAINS, PARTITIONS, PROFILES, TIME, TIME_AXES, check_corpus,
                      load_boundary_fixtures, load_feature_policy, nominal_step)

PPM = 1_000_000


@dataclass
class Rows:
    timestamps: bytearray = field(default_factory=bytearray)
    values: bytearray = field(default_factory=bytearray)

    def add(self, instant: int, row: bytes) -> None:
        self.timestamps.extend(struct.pack("<q", instant))
        self.values.extend(row)


def _fraction(numerator: int, denominator: int) -> int | None:
    return (numerator * PPM + denominator // 2) // denominator if denominator else None


def _pearson(x: np.ndarray, y: np.ndarray, minimum: int) -> tuple[int | None, int]:
    paired = np.isfinite(x) & np.isfinite(y)
    n = int(np.count_nonzero(paired))
    if n < minimum:
        return None, n
    a, b = x[paired], y[paired]
    if np.min(a) == np.max(a) or np.min(b) == np.max(b):
        return None, n
    # Scale before subtracting the mean, so even binary64 extrema do not overflow.
    a = a / np.max(np.abs(a))
    b = b / np.max(np.abs(b))
    a -= np.mean(a)
    b -= np.mean(b)
    norm = np.sqrt(np.sum(a * a)) * np.sqrt(np.sum(b * b))
    if not norm:
        return None, n
    r = np.clip(np.sum(a * b) / norm, -1., 1.)
    return round(float(r) * PPM), n


def _time(t: np.ndarray, nominal: int | None, large_gap: int) -> dict:
    # Corpus civil seconds and the tiny timestamp fixture fit within this subtraction.
    ordered = [int(x) for x in t]
    steps = [b - a for a, b in zip(ordered, ordered[1:])]
    return {"first": ordered[0] if ordered else None, "last": ordered[-1] if ordered else None,
            "regular": bool(steps) and steps[0] > 0 and all(d == steps[0] for d in steps),
            "negative": sum(n < 0 for n in ordered), "duplicate_steps": steps.count(0),
            "backward_steps": sum(d < 0 for d in steps),
            "max_positive_step": max((d for d in steps if d > 0), default=None),
            "nominal_step": nominal,
            "large_gaps": sum(d >= nominal * large_gap for d in steps) if nominal else None}


def _value(v: np.ndarray, thresholds: dict, lag: int | None) -> dict:
    minimum = thresholds["minimum_shape_rows"]
    finite = v[np.isfinite(v)]
    n = len(finite)
    zeros = int(np.count_nonzero(finite == 0))
    # Keep adjacency: invalid cells are never skipped to create a new delta.
    with np.errstate(over="ignore", invalid="ignore"):
        diff = np.diff(v)
    diff = diff[np.isfinite(diff)]
    forward, backward = int(np.count_nonzero(diff > 0)), int(np.count_nonzero(diff < 0))
    nonzero = np.abs(diff[diff != 0])
    direction = _fraction(max(forward, backward), len(diff))
    zero_fraction = _fraction(zeros, n)
    jumps = 0
    if len(diff) >= minimum - 1 and len(nonzero):
        scaled = nonzero / np.max(nonzero)
        cutoff = np.median(scaled) * thresholds["jump_over_nonzero_delta_median"]
        if cutoff > 0:
            jumps = int(np.count_nonzero(scaled >= cutoff))
    period, pairs = _pearson(v[:-lag], v[lag:], minimum) if lag is not None else (None, 0)
    traits = []
    if n >= minimum:
        if np.min(finite) == np.max(finite):
            traits.append("constant")
        if zero_fraction >= thresholds["sparse_zero_fraction_ppm"]:
            traits.append("sparse_zero")
        if len(diff) >= minimum - 1 and direction >= thresholds["trend_direction_fraction_ppm"]:
            traits.append("trend_indicator")
        if jumps:
            traits.append("jump_indicator")
        if period is not None and period >= thresholds["period_correlation_ppm"]:
            traits.append("periodicity_indicator")
    negative_zero = int(np.count_nonzero((finite == 0) & np.signbit(finite)))
    if negative_zero:
        traits.append("float_special_bits")
    return {"usable_rows": n, "min": float(np.min(finite)) if n else None,
            "max": float(np.max(finite)) if n else None, "negative_zero": negative_zero,
            "zero_fraction_ppm": zero_fraction, "finite_adjacent_deltas": len(diff),
            "dominant_direction_fraction_ppm": direction, "jump_count": jumps,
            "seasonal_pairs": pairs, "seasonal_pearson_ppm": period, "traits": traits}


def _partition(row: Rows, dataset: dict, split: str, policy: dict) -> dict:
    columns = [name for name, _ in PROFILES[dataset["header_profile"]][0]]
    source = dataset["audit"]["partitions"][split]
    n = source["rows"]
    t = np.frombuffer(row.timestamps, dtype="<i8")
    values = np.frombuffer(row.values, dtype="<f8").reshape((n, len(columns)))
    thresholds = policy["thresholds"]
    nominal = nominal_step(dataset)
    time = _time(t, nominal, thresholds["large_gap_nominal_steps"])
    lag_ticks = policy["seasonal_lag_ticks"][dataset["id"]]
    lag, rem = divmod(lag_ticks or 0, nominal)
    # No interpolation/bridging calendar gaps or remapping across a split.
    eligible = lag > 0 and rem == 0 and time["regular"] and time["max_positive_step"] == nominal and n >= 2 * lag
    lag = lag if eligible else None
    work = values.copy()
    sentinel = work == -9999 if dataset["header_profile"] == "project_mpi_21_v1" else None
    if sentinel is not None:
        work[sentinel] = np.nan
    features = [{"name": name, "literal_sentinel": int(np.count_nonzero(sentinel[:, i])) if sentinel is not None else 0,
                 **_value(work[:, i], thresholds, lag)} for i, name in enumerate(columns)]
    strongest = weakest = None
    assessed = strong = weak = 0
    for i, j in combinations(range(len(columns)), 2):
        score, pairs = _pearson(work[:, i], work[:, j], thresholds["minimum_shape_rows"])
        if score is None:
            continue
        item = {"columns": [columns[i], columns[j]], "pearson_ppm": score, "paired_rows": pairs}
        assessed += 1
        strong += abs(score) >= thresholds["strong_abs_pearson_ppm"]
        weak += abs(score) <= thresholds["weak_abs_pearson_ppm"]
        if strongest is None or abs(score) > abs(strongest["pearson_ppm"]):
            strongest = item
        if weakest is None or abs(score) < abs(weakest["pearson_ppm"]):
            weakest = item
    return {"split": split, "canonical_id": source["canonical_id"], "rows": n,
            "logical_bytes": source["logical_bytes"], "time": time,
            "seasonal_lag_ticks": lag_ticks, "seasonal_lag_rows_assessed": lag,
            "columns": features, "same_axis_pearson": {"possible_pairs": len(columns) * (len(columns)-1) // 2,
                      "assessed_pairs": assessed, "strong_pairs": strong, "weak_pairs": weak,
                      "strongest": strongest, "weakest": weakest}}


def _small_npy(path: Path, dtype: str, shape: tuple[int, ...]) -> np.ndarray:
    require(all(type(n) is int and 0 < n <= 512 for n in shape) and path.stat().st_size <= 4096,
            "feature fixture exceeds size limit")
    with path.open("rb") as stream:
        try:
            version = np.lib.format.read_magic(stream)
            require(version == (1, 0), f"invalid fixture NPY version: {path.name}")
            stored_shape, fortran, descr = np.lib.format.read_array_header_1_0(stream, max_header_size=1024)
        except (ValueError, EOFError) as exc:
            raise ContractError(f"invalid fixture NPY: {path.name}") from exc
        require(stored_shape == shape and not fortran and descr.str == dtype,
                f"fixture NPY shape or dtype mismatch: {path.name}")
        payload = stream.read(4097)
        require(len(payload) == int(np.prod(shape)) * descr.itemsize, f"fixture NPY payload mismatch: {path.name}")
    return np.frombuffer(payload, dtype=descr).reshape(shape)


def _fixtures(root: Path, policy: dict) -> tuple[dict, list[dict]]:
    manifest = load_json(local_file(root, policy["fixture_manifest"]))
    require(manifest.get("schema") == "bmk.fixtures/1" and manifest.get("generator_id") == "m0-fixtures/v1",
            "unexpected corpus fixture manifest")
    files = {key: verify_asset(root, ref) for key, ref in manifest["files"].items()}
    for key, path in files.items():
        require(path.stat().st_size == manifest["files"][key]["bytes"], "fixture size mismatch")

    def data(name: str, dtypes: tuple[str, ...]) -> tuple[list[np.ndarray], int]:
        obj = manifest["objects"][name]
        refs = obj["formats"]["npy"]
        require(len(refs) == len(dtypes), f"fixture file count mismatch: {name}")
        return [_small_npy(files[path], dtype, (obj["rows"],)) for path, dtype in zip(refs, dtypes)], obj["rows"]

    (t, v), rows = data("tiny-tv", ("<i8", "<f8"))
    floats, float_rows = data("f64-boundaries", ("<f8",))
    integers, int_rows = data("i64-boundaries", ("<i8",))
    f, i = floats[0], integers[0]
    exp, mantissa = (f.view("<u8") >> 52) & 0x7ff, f.view("<u8") & ((1 << 52) - 1)
    return manifest, [
        {"object": "tiny-tv", "rows": rows, "time": _time(t, None, policy["thresholds"]["large_gap_nominal_steps"]),
         "value_negative_zero": int(np.count_nonzero((v == 0) & np.signbit(v)))},
        {"object": "f64-boundaries", "rows": float_rows, "nan": int(np.count_nonzero(np.isnan(f))),
         "infinity": int(np.count_nonzero(np.isinf(f))), "subnormal": int(np.count_nonzero((exp == 0) & (mantissa != 0)))},
        {"object": "i64-boundaries", "rows": int_rows, "min": int(i.min()), "max": int(i.max())},
    ]


def _boundary_features(root: Path, policy: dict) -> tuple[dict, list[tuple[str, str, str]]]:
    doc, contract, files = load_boundary_fixtures(root, policy["boundary_manifest"])
    arrays = {name: _small_npy(files[name], ref["dtype"], tuple(ref["shape"])) for name, ref in doc["files"].items()}
    marks = []

    def mark(ref: str, axis: str, *labels: str) -> None:
        marks.extend((axis, label, ref) for label in labels)

    integer_edges = {}
    for name in doc["integer_extrema"]:
        x = arrays[name]
        label = name.split("-")[0]
        require(x.ndim == 1 and x.dtype.kind + str(x.dtype.itemsize * 8) == label,
                f"wrong signedness, width or rank: {name}")
        limits = np.iinfo(x.dtype)
        lo, hi = int(x.min()), int(x.max())
        require(lo == limits.min and hi == limits.max, f"missing integer extrema: {name}")
        integer_edges[label] = {"min": lo, "max": hi, "elements": len(x)}
        mark(name, "types", label)
        mark(name, "numeric", "integer_extrema")
    f = arrays[doc["float_special"]]
    require(f.dtype.str == "<f4" and f.ndim == 1, "wrong f32 special fixture type or rank")
    bits = f.view("<u4")
    words = {int(w) for w in bits}
    require({0, 1, 1 << 31, 0x7F800000, 0xFF800000, 0x7FC00011, 0x7FC000EF} <= words,
            "f32 fixture missing signed zero, subnormal, infinities or distinct NaN payloads")
    mark(doc["float_special"], "types", "f32")
    mark(doc["float_special"], "numeric", "float_special_bits")
    mark(doc["float_special"], "anomalies", "nan", "infinity")
    matrices = {}
    for name, rank in zip(doc["spatial_fields"], (2, 3), strict=True):
        x = arrays[name]
        require(x.ndim == rank and x.dtype.kind == "f" and all(n > 1 for n in x.shape), f"wrong field layout: {name}")
        matrices[name] = {"shape": list(x.shape), "order": "C", "dtype": x.dtype.str}
        mark(name, "structure", name)
    series = []
    for spec in doc["different_axes"]:
        t, x = arrays[spec["axis"]], arrays[spec["values"]]
        require(t.ndim == 1 and x.shape == t.shape and t.dtype.str == "<i8" and x.dtype.str == "<f8",
                f"invalid T/V fixture: {spec['axis']}")
        time = _time(t, spec["nominal_step_ns"], policy["thresholds"]["large_gap_nominal_steps"])
        mark(spec["axis"], "structure", "regular" if time["regular"] else "irregular")
        for label, field in (("negative_timestamp", "negative"), ("duplicate_timestamp", "duplicate_steps"),
                             ("large_gap", "large_gaps")):
            if time[field]:
                mark(spec["axis"], "anomalies", label)
        row = {**spec, "time": time, "rows": len(t)}
        if name := spec.get("validity"):
            mask = arrays[name]
            require(mask.dtype.str == "|b1" and mask.shape == t.shape and np.all(mask.view("u1") <= 1),
                    "validity mask differs from axis/values or contains non-boolean words")
            missing = x[~mask]
            require(0 < len(missing) < len(x) and np.all(np.isfinite(missing) & (missing != 0)) and
                    np.any(np.isnan(x[mask])), "masked-value fixture does not distinguish validity from numeric content")
            row.update(missing_rows=np.flatnonzero(~mask).tolist(), valid_nan_rows=np.flatnonzero(mask & np.isnan(x)).tolist())
            mark(name, "types", "bool")
            mark(name, "anomalies", "missing_validity")
        else:
            row["value_profile"] = _value(x, policy["thresholds"], None)
            for trait in row["value_profile"]["traits"]:
                mark(spec["values"], "numeric", trait)
        series.append(row)
    require(len({s["rows"] for s in series}) > 1, "independent axes fixture must have unequal lengths")
    mark("different-axes-object", "dependence", "different_axes_in_object")
    mark("different-axes-object", "structure", "different_lengths", "multivariate")
    random = arrays[doc["noise"]["file"]]
    unique = int(len(np.unique(random)))
    require(random.dtype.str == "<f4" and random.shape == (256,) and unique > 200 and np.all(np.abs(random) <= 1),
            "pseudorandom fixture is not the declared bounded stress input")
    mark(doc["noise"]["file"], "numeric", "noise")
    generator = digest(local_file(root, BOUNDARY_GENERATOR))
    manifest = content_id(doc)
    return {"binding_id": content_id({"manifest": manifest, "generator_sha256": generator}),
            "manifest_id": manifest, "schema_id": contract.document_id, "generator_sha256": generator,
            "integer_extrema": integer_edges, "spatial_fields": matrices, "different_axes": series,
            "timestamp_semantics": doc["timestamp_semantics"], "noise": {**doc["noise"], "unique_values": unique},
            "f32_special": {"words": [f"{word:08x}" for word in bits]}}, marks


def profile_corpus(root: Path) -> dict:
    """Recompute canonical identities and record evidence separately for every coverage requirement."""
    policy, schema = load_feature_policy(root)
    doc = load_json(local_file(root, policy["corpus_manifest"]))
    rows: dict[tuple[str, str], Rows] = {}

    def observe(spec: dict, split: str, instant: int, payload: bytes) -> None:
        key = (spec["id"], split)
        if key not in rows:
            rows[key] = Rows()
        rows[key].add(instant, payload)

    audit = check_corpus(root, policy["corpus_manifest"], parse=True, observe=observe)
    datasets = [{"id": d["id"], "domain": d["domain"], "source_cluster": d["source_cluster"],
                 "time_axis": TIME_AXES.get(d["header_profile"], TIME),
                 "partitions": [_partition(rows.pop((d["id"], split)), d, split, policy) for split in PARTITIONS]}
                for d in doc["datasets"]]
    fixtures, synthetic = _fixtures(root, policy)
    coverage = {axis: {label: {"real": [], "synthetic": []} for label in members}
                for axis, members in policy["axes"].items()}

    def add(kind: str, axis: str, label: str, ref: str) -> None:
        coverage[axis][label][kind].append(ref)

    p = policy["thresholds"]
    for dataset in datasets:
        add("real", "domains", dataset["domain"], dataset["id"])
        for part in dataset["partitions"]:
            ref = f'{dataset["id"]}/{part["split"]}'
            for label in ("i64", "f64", "timestamp", "mixed"):
                add("real", "types", label, ref)
            add("real", "structure", "multivariate", ref)
            add("real", "structure", "regular" if part["time"]["regular"] else "irregular", ref)
            add("real", "dependence", "shared_axis", ref)
            for strength in ("strong", "weak"):
                if part["same_axis_pearson"][strength + "_pairs"]:
                    add("real", "dependence", strength + "_pearson", ref)
            for item in part["columns"]:
                for trait in item["traits"]:
                    add("real", "numeric", trait, ref + "/" + item["name"])
            if part["rows"] >= p["long_min_rows"]:
                add("real", "size", "long_sequence_available", ref)
            for label, field in (("negative_timestamp", "negative"), ("duplicate_timestamp", "duplicate_steps"),
                                 ("large_gap", "large_gaps")):
                if part["time"][field]:
                    add("real", "anomalies", label, ref)
    for item in synthetic:
        name = item["object"]
        if item["rows"] <= p["very_short_max_rows"]:
            add("synthetic", "size", "very_short", name)
        add("synthetic", "structure", "univariate", name)
        if name == "tiny-tv":
            for label in ("i64", "f64", "timestamp", "mixed"):
                add("synthetic", "types", label, name)
            if not item["time"]["regular"]:
                add("synthetic", "structure", "irregular", name)
            if item["time"]["negative"]:
                add("synthetic", "anomalies", "negative_timestamp", name)
        elif name == "f64-boundaries":
            add("synthetic", "types", "f64", name)
            for label in ("nan", "infinity"):
                if item[label]:
                    add("synthetic", "anomalies", label, name)
            if item["nan"] or item["infinity"] or item["subnormal"]:
                add("synthetic", "numeric", "float_special_bits", name)
        else:
            add("synthetic", "types", "i64", name)
            if item["min"] == -(1 << 63) and item["max"] == (1 << 63) - 1:
                add("synthetic", "numeric", "integer_extrema", name)
    boundaries, marks = _boundary_features(root, policy)
    for axis, label, ref in marks:
        add("synthetic", axis, label, f"corpus-boundaries-v1/{ref}")
    for axis, members in coverage.items():
        for label, item in members.items():
            item["status"] = ("real_and_synthetic" if item["real"] and item["synthetic"] else
                              "real_observed" if item["real"] else "synthetic_only" if item["synthetic"] else "gap")
            if item["status"] == "gap":
                item["reason"] = ("requires_real_independent_source" if axis == "domains" else
                                  "requires_method_and_resource_contract" if label in
                                  {"block_boundary_triplet", "cache_inside", "cache_outside", "resource_refusal"} else
                                  "no_noise_model_or_independent_residual_test" if label == "noise" else
                                  "threshold_not_observed_in_profiled_partitions" if label == "trend_indicator" else
                                  "no_matching_verified_object_or_observation")
    require(set(coverage["domains"]) == set(DOMAINS) and audit["corpus_id"] == content_id(doc),
            "corpus feature report identity mismatch")
    body = {"schema": "bmk.corpus-feature-report/3", "evidence_scope": "descriptive_not_qualification",
            "policy_id": content_id(policy), "policy_schema_id": schema.document_id,
            "fixture_manifest_id": content_id(fixtures), "corpus_audit": audit,
            "datasets": datasets, "synthetic": synthetic, "boundaries": boundaries, "coverage": coverage}
    return {**body, "profile_id": content_id(body)}
