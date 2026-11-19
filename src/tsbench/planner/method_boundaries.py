"""Frozen inputs and pass/fail criteria shared by planning and the boundary probe."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import struct

from ..assets import canonical_bytes, content_id, load_json, local_file, require
from ..contracts import load_contract
from ..corpus import load_boundary_fixtures, load_feature_policy
from ..plugins import discover, resolve
from .corpus_windows import bind_window, read_held_out_boundary_window, read_labeled_tv_window

CASES = "configs/suites/m0_method_boundaries_v1/cases.json"
PROBE = "tsbench.worker.method-boundaries"
SPEC = {
    "alp-auto": ("value", "alpn-auto-encoder", "scalar-unfused"),
    "zstd": ("bytes", "ln-zstd-baseline", "ln-zstd-baseline"),
    "gorilla-tv": ("timestamp_value", "gorilla-c11", "gorilla-c11"),
}


def sha(data: bytes) -> str:
    return sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class BoundaryCase:
    definition: dict
    columns: tuple[bytes, ...]
    schema: bytes


def plan_boundary_cases(root: Path) -> tuple[dict, list[BoundaryCase]]:
    from ..analysis.corpus_features import _small_npy

    cfg = load_json(local_file(root, CASES))
    contract = load_contract(root, "method-boundaries")
    contract.validate(cfg, CASES)
    trips = {r["method"]: r for r in cfg["triplets"]}
    require(trips.keys() == SPEC.keys(), "method triplet coverage differs")
    feature, _ = load_feature_policy(root)
    boundaries, _, fixtures = load_boundary_fixtures(root, feature["boundary_manifest"])
    registry = discover(root, selected=set(trips))
    options = {method: resolve(root, method, row["options"], registry=registry) for method, row in trips.items()}
    rows = []

    def add(method, name, n, values, times=None, *, dtype=10, vectors=None, reject=False, provenance):
        route = trips[method]
        tv = times is not None
        types, columns = ((7, 10), (times, values)) if tv else ((dtype,), (values,))
        require(len(values) == n * (4 if dtype == 9 else 8) and (not tv or len(times) == n * 8),
                "materialized case has inconsistent shape")
        schema = b'{"time_unit":"ms"}' if tv else canonical_bytes({"dtype": dtype, "rank": 1, "role": "value"})
        role, encoder, decoder = SPEC[method]
        require(role in registry[method]["manifest"]["roles"], f"case role missing in manifest: {method}")
        base = {"case": name, "method": method, "rows": n, "input_bytes": sum(map(len, columns)),
                "input_column_sha256": [sha(x) for x in columns], "schema_sha256": sha(schema),
                "expected": "resource_limit_7" if reject else "verified", **provenance}
        d = {"row": base, "selection": route["selection"], "route": route["route"],
             "task": "whole_object" if tv else "values_only", "plugin_role": role,
             "configuration_id": options[method]["configuration_id"], "options": options[method]["options"],
             "abi_types": list(types), "predicted_access": "whole_object_batch", "threads": 1,
             "expected_encode_backend": encoder, "expected_decode_backend": decoder,
             "expected_aln1_vectors": vectors, "artifact_basename": None if reject else name + ".bmk"}
        rows.append(BoundaryCase({**d, "case_id": content_id(d)}, columns, schema))

    for case in cfg["triplets"]:
        method, n = case["method"], case["rows"]
        require(case["window"]["count"] == n + 1, f"boundary window must include the plus-one row: {method}")
        bound, ticks, values = read_held_out_boundary_window(root, cfg["corpus"], cfg["corpus_id"], case["window"])
        times = None
        if method == "gorilla-tv":
            times = b"".join(struct.pack("<q", t * 1000) for (t,) in struct.iter_unpack("<q", ticks))
        for delta, label in ((-1, "minus"), (0, "at"), (1, "plus")):
            count = n + delta
            add(method, f"{method}-{label}", count, values[:count*8], times[:count*8] if times is not None else None,
                vectors=1 + (delta == 1) if case["plus_one"] == "verify_new_vector" else None,
                reject=delta == 1 and case["plus_one"] == "expect_resource_limit_7",
                provenance={"window": bound, "prefix_rows": count, "boundary": case["boundary"], "delta": delta})
        if method == cfg["fixture"]["method"]:
            spec = cfg["fixture"]
            data = _small_npy(fixtures[spec["name"]], spec["dtype"], (spec["rows"],))
            add(method, "alp-auto-f32-special", spec["rows"], data.tobytes(), dtype=9, vectors=1,
                provenance={"fixture": boundaries["files"][spec["name"]]})
    domains = cfg["domain_windows"]
    for window in domains["windows"]:
        bound = bind_window(root, domains["corpus"], domains["corpus_id"], window)
        axis, ticks, values = read_labeled_tv_window(root, bound)
        require(axis["timezone"] is None and axis["interpretation"] in {
            "elapsed_seconds_since_collection_start", "source_annual_label_not_instant"}, "unexpected source time axis")
        for method in domains["methods"]:
            add(method, f"{window['dataset']}-{method}", window["count"], values,
                provenance={"task": "values_only", "window": bound, "time_axis_not_encoded": axis,
                            "coordinate_sha256_not_charged": sha(ticks)})
    require(len(rows) == 14 and len({case.definition["row"]["case"] for case in rows}) == len(rows),
            "method boundary case closure changed")
    bundle = {"config_id": content_id(cfg), "config_schema_id": contract.document_id, "test": PROBE,
              "evidence_path": "method-boundaries/report.json", "case_policy": cfg["run_policy"],
              "cases": [r.definition for r in rows]}
    return {**bundle, "bundle_id": content_id(bundle)}, rows
